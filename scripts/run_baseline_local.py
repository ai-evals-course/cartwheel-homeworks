"""Run evaluation cases k times locally, in place of Harbor in Docker.

The handout's path is `harbor run -e docker`. Docker cannot be installed on this
machine, and the agent's model is an internal endpoint a GitHub runner cannot reach, so
Harbor's containers are replaced by the course's own replay engine. See
analysis/report/hw6-ci-substitution.md.

What Harbor would do, and what happens here instead:

  fresh Docker container per trial  ->  replay.rollout.world_reset re-seeds a
                                        deterministic world before every rollout
  Harbor agent adapter              ->  replay.rollout.run_case runs the real agent
  Reward Kit code checks            ->  replay.rollout.apply_checks, unchanged
  Reward Kit judge call             ->  the frozen Homework 5 judge, called through the
                                        same parser used to validate it
  reward per trial                  ->  the same pass/fail per rollout

The judge is NOT called through replay.rollout.judge_reply. That helper parses
`"answer": "pass"` and sets no max_tokens; this judge emits {"critique", "result"} and
its model returns empty content without a large budget, so judge_reply would score every
case as a silent pass. analysis/tools/muse_classify parses the real format and sets the
budget, so it is reused here.

    .venv/bin/python scripts/run_baseline_local.py --case e-001
    .venv/bin/python scripts/run_baseline_local.py --all -k 5
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
from replay.rollout import (  # noqa: E402
    apply_checks, judge_trace_text, load_frozen_judge, run_case, world_reset,
)

# Overridable so parallel workers each get their own world. world_reset sets
# CARTWHEEL_DB as a process-global environment variable, so two cases sharing a
# process would repoint each other's database mid-run. Parallelism must be by
# process, never by thread.
WORLD = REPO / ".hw6-logs" / "world"
OUT = REPO / ".hw6-logs" / "baselines"
CASES = REPO / "eval_cases" / "cases.jsonl"


def load_cases() -> list[dict]:
    return [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]


def judge_verdict(judge: dict, transcript: dict) -> tuple[str, str]:
    """Ask the frozen judge about one transcript. Returns (pass|fail, critique)."""
    from analysis.tools.muse_classify import MAX_TOKENS, _parse
    import os
    import urllib.request

    base = (os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")
    key = os.environ["OPENAI_API_KEY"]
    model = judge["model"]
    model = model.split("/", 1)[1] if model.startswith("openai/") else model

    lines = []
    for turn in transcript["turns"]:
        lines.append(f"[user] {turn['user']}")
        for call in turn.get("tool_calls") or []:
            lines.append(f"[tool call] {call['name']} {json.dumps(call.get('args'))}")
            lines.append(f"[tool result] {call['name']}: {json.dumps(call.get('result'))}")
        lines.append(f"[assistant] {turn['reply']}")

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": judge["prompt_text"]},
            {"role": "user", "content":
                "Evaluate this trace and reply with the JSON object described above.\n\n"
                "TRACE\n" + "\n".join(lines)},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    data = json.loads(urllib.request.urlopen(req, timeout=300).read())
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    label, critique = _parse(content)          # 1 = Pass, 0 = Fail
    return ("pass" if label == 1 else "fail"), critique


def make_runner(case: dict, model: str | None, world: Path | None = None):
    world = world or WORLD
    judges = case["expected"].get("judges") or {}
    frozen = {m: load_frozen_judge(m) for m in judges}

    def runner() -> dict:
        # A timeout or connection failure means this attempt produced no data. The
        # handout is explicit that a case must not be classified from a trial with an
        # infrastructure error, so these are raised as ReplayInfraError and the harness
        # resets and retries the same rollout. A model that answers and answers wrongly
        # is a real failure and is never retried.
        try:
            transcript = run_case(case, model=model)
        except Exception as exc:                       # noqa: BLE001
            name = type(exc).__name__
            if any(w in name for w in ("Timeout", "Connection", "APIError",
                                       "ServiceUnavailable", "RateLimit")):
                raise ReplayInfraError(f"{name}: {str(exc)[:160]}") from exc
            raise
        checks = apply_checks(case, transcript, world / "cartwheel.db")
        verdicts, critiques = {}, {}
        for mode, want in judges.items():
            got, critique = judge_verdict(frozen[mode], transcript)
            verdicts[mode] = got
            critiques[mode] = critique
        judge_ok = all(verdicts.get(m) == want for m, want in judges.items())
        return {
            "passed": checks["passed"] and judge_ok,
            "checks_passed": checks["passed"],
            "checks_failed": checks["failed"],
            "judges": verdicts,
            "judge_critiques": critiques,
            "final_reply": transcript["final_reply"],
            "tool_calls": [c["name"] for t in transcript["turns"]
                           for c in (t.get("tool_calls") or [])],
        }

    return runner


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", help="case id; repeatable")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-k", type=int, default=5, help="rollouts per case")
    ap.add_argument("--model", default=None, help="defaults to CARTWHEEL_MODEL")
    ap.add_argument("--world-dir", default=None,
                    help="private world directory; required when running in parallel")
    args = ap.parse_args()

    import os
    model = args.model or os.environ.get("CARTWHEEL_MODEL")
    if not model:
        raise SystemExit("set CARTWHEEL_MODEL in .env or pass --model")

    global WORLD
    if args.world_dir:
        WORLD = Path(args.world_dir)
        WORLD.mkdir(parents=True, exist_ok=True)

    cases = load_cases()
    wanted = ([c for c in cases if c["id"] in set(args.case)] if args.case
              else cases if args.all else [])
    if not wanted:
        raise SystemExit("pass --case <id> (repeatable) or --all")

    OUT.mkdir(parents=True, exist_ok=True)
    reset = world_reset(WORLD)
    print(f"model {model}   {len(wanted)} case(s) x {args.k} rollouts "
          f"= {len(wanted) * args.k} agent runs")
    print("judge calls: " +
          str(sum(len(c['expected'].get('judges') or {}) for c in wanted) * args.k) + "\n")

    for case in wanted:
        t0 = time.time()
        rollouts = replay_case(make_runner(case, model, WORLD), reset, n=args.k)
        passes = sum(1 for r in rollouts if r["passed"])
        kind = "regression" if passes == args.k else "capability"
        rate = passes / args.k
        path = OUT / f"{case['id']}.json"
        path.write_text(json.dumps(
            {"case_id": case["id"], "mode": case["mode"], "n": args.k,
             "passes": passes, "observed_pass_rate": rate,
             "classification": kind, "model": model,
             "rollouts": rollouts}, indent=1) + "\n")
        marks = "".join("." if r["passed"] else "x" for r in rollouts)
        print(f"  {case['id']}  {case['mode']:30} [{marks}]  {passes}/{args.k}  "
              f"-> {kind:11} {time.time() - t0:5.0f}s")
        if kind == "capability":
            why = {d for r in rollouts for d in r["checks_failed"]}
            for d in sorted(why)[:2]:
                print(f"       failed check: {d}")


if __name__ == "__main__":
    main()
