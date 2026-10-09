"""Replace trials that produced no data, until a job has the attempts it needs.

The handout requires that a case is not analysed from a trial with an infrastructure
error, and that the fix is to repair the infrastructure and rerun. Two consecutive
15-attempt batches each lost exactly two trials to `ServiceUnavailable`, so rerunning
the whole batch is unlikely to converge and costs 36 minutes a time.

This keeps the trials that produced a result and runs only the shortfall. That is not
selection on outcome: a trial with an infrastructure error has no outcome. Nothing that
reached the model is ever discarded, whatever its verdict.

Errored trials are not deleted. They move to `discarded_trials` in the same file, so the
record shows how many attempts it took and why.

    .venv/bin/python scripts/topup_trials.py \\
        --job hw6-capability-15 --case e-009 --need 15 \\
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

from replay.harness import ReplayInfraError, replay_case  # noqa: E402
from replay.rollout import world_reset  # noqa: E402
from scripts.run_baseline_local import load_cases, make_runner  # noqa: E402

JOBS = REPO / ".hw6-logs" / "jobs"
WORLD = REPO / ".hw6-logs" / "ci-world"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--need", type=int, default=15)
    ap.add_argument("--model", required=True)
    ap.add_argument("--max-rounds", type=int, default=6)
    args = ap.parse_args()

    job = JOBS / args.job
    path = job / "result.json"
    data = json.loads(path.read_text())
    case = next(c for c in load_cases() if c["id"] == args.case)

    mine = [t for t in data["trial_results"]
            if str(t.get("task_name", "")).endswith(args.case)]
    others = [t for t in data["trial_results"] if t not in mine]
    clean = [t for t in mine if t.get("exception_info") is None
             and t.get("verifier_result") is not None]
    discarded = data.get("discarded_trials", []) + [t for t in mine if t not in clean]

    print(f"{args.case} in {args.job}")
    print(f"  trials with a result: {len(clean)} of {args.need} needed")
    print(f"  discarded, no data:   {len(discarded)} (kept in the file for the record)\n")

    import scripts.run_baseline_local as base
    base.WORLD = WORLD
    reset = world_reset(WORLD)
    provider, _, name = args.model.partition("/")

    rounds = 0
    while len(clean) < args.need and rounds < args.max_rounds:
        rounds += 1
        short = args.need - len(clean)
        print(f"  round {rounds}: running {short} replacement trial(s)")
        inner = make_runner(case, args.model, WORLD)

        def runner(_inner=inner):
            try:
                return _inner()
            except ReplayInfraError as exc:
                return {"passed": False, "infra_error": str(exc), "checks_failed": [],
                        "judges": {}, "tool_calls": [], "final_reply": ""}

        t0 = time.time()
        for r in replay_case(runner, reset, n=short):
            i = len(clean) + len(discarded)
            trial = {"task_name": f"cartwheel/{args.case}",
                     "trial_name": f"{args.case}-attempt-{i}",
                     "attempt": i,
                     "exception_info": r.get("infra_error"),
                     "agent_info": {"model_info": {"name": name or args.model,
                                                   "provider": provider if name else None}},
                     "metadata": {"checks_failed": r.get("checks_failed"),
                                  "judges": r.get("judges"),
                                  "tool_calls": r.get("tool_calls")}}
            if r.get("infra_error"):
                discarded.append(trial)
                print(f"      trial {i}: no data ({r['infra_error'][:50]})")
            else:
                trial["verifier_result"] = {
                    "rewards": {"reward": 1.0 if r["passed"] else 0.0}}
                clean.append(trial)
                print(f"      trial {i}: {'pass' if r['passed'] else 'fail'}")
        print(f"      {time.time() - t0:.0f}s, now {len(clean)}/{args.need} clean\n")

    # Renumber so the analysed set reads 0..need-1 in the order the trials were taken.
    for i, t in enumerate(clean):
        t["attempt"] = i
        t["trial_name"] = f"{args.case}-attempt-{i}"

    data["trial_results"] = others + clean
    data["discarded_trials"] = discarded
    path.write_text(json.dumps(data, indent=1) + "\n")

    passes = sum(1 for t in clean
                 if t["verifier_result"]["rewards"]["reward"] >= 1.0)
    print(f"{len(clean)} trials with a result, {passes} passed")
    print(f"{len(discarded)} discarded for producing no data")
    if len(clean) < args.need:
        raise SystemExit(f"still short of {args.need}; run again when the endpoint is healthier")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
