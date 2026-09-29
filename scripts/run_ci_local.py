"""Run the classified evaluation cases and apply the CI decision, without Docker.

This is the local stand-in for the `complete-evaluations` job in
`.github/workflows/evals.yml`. That job cannot run on GitHub Actions here: the agent's
model is an internal endpoint a hosted runner cannot reach, and its credential must not
be sent to a third-party CI provider. See analysis/report/hw6-ci-substitution.md.

What is preserved exactly:

  * the same cases, from eval_cases/cases.jsonl, with their pinned classifications
  * the same five attempts per case
  * ``harbor_adapter.summary.summarize_job`` builds the report, so the table and the
    block/pass gate are the course's code, not a reimplementation
  * that summariser calls ``tests.eval.passk`` for pass@1, pass@3, pass@5, pass^5 and
    the CI decision -- the graded functions

Trials are written in the shape Harbor records them, so the summariser reads them
unchanged. A trial that hit an infrastructure error is written with a null reward, which
the summariser reports separately instead of counting as a failure.

    .venv/bin/python scripts/run_ci_local.py --job-name hw6-evals \\
        --model openai/rl-muse-spark-1-1-playground
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from observability.instrument import load_env  # noqa: E402

load_env()

from harbor_adapter.summary import summarize_job  # noqa: E402
from replay.harness import ReplayInfraError, replay_case  # noqa: E402
from replay.rollout import world_reset  # noqa: E402
from scripts.run_baseline_local import load_cases, make_runner  # noqa: E402

JOBS = REPO / ".hw6-logs" / "jobs"
WORLD = REPO / ".hw6-logs" / "ci-world"
CASES = REPO / "eval_cases" / "cases.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-name", default="hw6-evals")
    ap.add_argument("-k", "--n-attempts", type=int, default=5)
    ap.add_argument("--model", required=True)
    ap.add_argument("--case", action="append", help="limit to these ids")
    args = ap.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] in set(args.case)]
    unclassified = [c["id"] for c in cases if not c.get("kind")]
    if unclassified:
        raise SystemExit(
            f"these cases have no classification, run the baseline first: {unclassified}")

    job = JOBS / args.job_name
    job.mkdir(parents=True, exist_ok=True)
    WORLD.mkdir(parents=True, exist_ok=True)
    reset = world_reset(WORLD)

    print(f"model {args.model}")
    print(f"{len(cases)} cases x {args.n_attempts} attempts = "
          f"{len(cases) * args.n_attempts} agent runs")
    print(f"judge calls: "
          f"{sum(len(c['expected'].get('judges') or {}) for c in cases) * args.n_attempts}\n")

    trials = []
    for case in cases:
        t0 = time.time()
        # A runner that records infrastructure failures as a null reward rather than
        # letting them end the job, matching how Harbor reports a trial with no reward.
        import scripts.run_baseline_local as base
        base.WORLD = WORLD
        inner = make_runner(case, args.model, WORLD)

        def runner(_inner=inner):
            try:
                return _inner()
            except ReplayInfraError as exc:
                return {"passed": False, "infra_error": str(exc),
                        "checks_failed": [], "judges": {}, "tool_calls": [],
                        "final_reply": ""}

        rollouts = replay_case(runner, reset, n=args.n_attempts)
        for i, r in enumerate(rollouts):
            # Written in the shape harbor_adapter.summary reads: a task_name ending in
            # the case id, and the reward nested under verifier_result.rewards.reward.
            # An infrastructure error carries no verifier_result at all, which the
            # summariser reports as "did not produce a reward" rather than a failure.
            trial = {"task_name": f"cartwheel/{case['id']}", "attempt": i,
                     "exception_info": r.get("infra_error"),
                     "metadata": {"checks_failed": r.get("checks_failed"),
                                  "judges": r.get("judges"),
                                  "tool_calls": r.get("tool_calls")}}
            if not r.get("infra_error"):
                trial["verifier_result"] = {
                    "rewards": {"reward": 1.0 if r["passed"] else 0.0}}
            trials.append(trial)
        marks = "".join("." if r["passed"] else
                        ("!" if r.get("infra_error") else "x") for r in rollouts)
        passes = sum(1 for r in rollouts if r["passed"])
        print(f"  {case['id']}  {case['kind']:11} [{marks}] {passes}/{args.n_attempts}  "
              f"{time.time() - t0:5.0f}s")

    (job / "result.json").write_text(
        json.dumps({"trial_results": trials}, indent=1) + "\n")
    print(f"\nresult -> {job / 'result.json'}")

    # When only a subset was run, summarise only that subset. Passing the full case
    # file makes the report list every case that was not run as "incomplete", which
    # buries the result under nine rows of noise.
    cases_path = CASES
    if args.case:
        subset = job / "cases-subset.jsonl"
        subset.write_text("".join(json.dumps(c) + "\n" for c in cases))
        cases_path = subset
    markdown, passed = summarize_job(job, cases_path=cases_path,
                                     expected_attempts=args.n_attempts)
    (job / "summary.md").write_text(markdown)
    print()
    print(markdown, end="")
    print(f"\nCI gate: {'PASS' if passed else 'BLOCK'}")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
