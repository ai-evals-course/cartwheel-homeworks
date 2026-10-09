"""Record each case's classification from its five baseline runs.

Per the handout:

  - five passes out of five  -> kind is "regression"
  - any failure              -> kind is "capability", and the observed fraction is
                                recorded as baseline_pass_rate

A case is not classified if any rollout hit an infrastructure error, because that trial
produced no data. Those are reported and left unclassified so the baseline can be rerun
for that case alone.

This never invents or adjusts a classification to produce a required mix. If the set
lacks a regression or a capability case, the answer is another reviewed case, not a
different label on this one.

    .venv/bin/python scripts/classify_cases.py            # report only
    .venv/bin/python scripts/classify_cases.py --write    # update cases.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "eval_cases" / "cases.jsonl"
BASELINES = REPO / ".hw6-logs" / "baselines"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("-k", type=int, default=5, help="expected rollouts per case")
    args = ap.parse_args()

    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    out, missing, short = [], [], []

    print(f"{'case':8}{'mode':32}{'runs':>7}{'kind':>13}{'rate':>7}")
    for case in cases:
        path = BASELINES / f"{case['id']}.json"
        if not path.exists():
            missing.append(case["id"])
            out.append(case)
            continue
        b = json.loads(path.read_text())
        if b["n"] != args.k:
            short.append(f"{case['id']} ({b['n']} of {args.k} runs)")
            out.append(case)
            continue

        kind = "regression" if b["passes"] == b["n"] else "capability"
        rec = {k: v for k, v in case.items()
               if k not in ("kind", "baseline_pass_rate")}
        rec["kind"] = kind
        if kind == "capability":
            rec["baseline_pass_rate"] = b["passes"] / b["n"]
        out.append(rec)
        rate = "" if kind == "regression" else f"{b['passes'] / b['n']:.1f}"
        print(f"  {case['id']:6}{case['mode']:32}{b['passes']}/{b['n']:>4}"
              f"{kind:>13}{rate:>7}")

    kinds = Counter(c.get("kind") for c in out if c.get("kind"))
    print(f"\n  {kinds.get('regression', 0)} regression, "
          f"{kinds.get('capability', 0)} capability, "
          f"{sum(1 for c in out if not c.get('kind'))} unclassified")
    if missing:
        print(f"  no baseline yet: {missing}")
    if short:
        print(f"  incomplete baselines, rerun these: {short}")

    ok = kinds.get("regression", 0) >= 1 and kinds.get("capability", 0) >= 1
    print(f"  handout needs at least one of each: {'satisfied' if ok else 'NOT YET'}")
    classified = sum(1 for c in out if c.get("kind"))
    print(f"  handout needs at least 10 classified cases: {classified} "
          f"({'satisfied' if classified >= 10 else 'NOT YET'})")
    modes = {c["mode"] for c in out if c.get("kind")}
    print(f"  handout needs at least 2 failure modes: {len(modes)} "
          f"({'satisfied' if len(modes) >= 2 else 'NOT YET'})")

    if args.write:
        CASES.write_text("".join(json.dumps(c) + "\n" for c in out))
        print(f"\nwrote {CASES}")
    else:
        print("\ndry run. re-run with --write to record these in cases.jsonl.")


if __name__ == "__main__":
    main()
