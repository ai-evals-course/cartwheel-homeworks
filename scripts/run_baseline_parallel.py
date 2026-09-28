"""Run baseline cases across several worker processes.

Harbor would give each trial its own Docker container. Without Docker, concurrency has
to come from somewhere, and it must be **processes, not threads**:
``replay.rollout.world_reset`` sets ``CARTWHEEL_DB`` in ``os.environ``, which is
process-global, so two cases sharing a process would silently repoint each other's
database mid-run.

So each worker is a separate ``run_baseline_local.py`` invocation with its own
``--world-dir``. Rollouts of one case stay strictly serial inside a worker, which is what
``replay_case`` requires: reset, run, reset, run.

    .venv/bin/python scripts/run_baseline_parallel.py --all -k 5 -j 4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKERS_DIR = REPO / ".hw6-logs" / "workers"
OUT = REPO / ".hw6-logs" / "baselines"
CASES = REPO / "eval_cases" / "cases.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("-j", type=int, default=4, help="worker processes")
    ap.add_argument("--model", required=True)
    args = ap.parse_args()

    cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
    ids = ([c["id"] for c in cases if c["id"] in set(args.case)] if args.case
           else [c["id"] for c in cases] if args.all else [])
    if not ids:
        raise SystemExit("pass --case <id> (repeatable) or --all")

    # Deal the cases round-robin so every worker gets a similar mix, rather than one
    # worker taking all the slow judge-scored cases.
    groups: list[list[str]] = [[] for _ in range(min(args.j, len(ids)))]
    for i, cid in enumerate(ids):
        groups[i % len(groups)].append(cid)

    judge_cases = sum(1 for c in cases
                      if c["id"] in ids and c["expected"].get("judges"))
    print(f"model {args.model}")
    print(f"{len(ids)} cases x {args.k} rollouts = {len(ids) * args.k} agent runs, "
          f"{judge_cases * args.k} judge calls")
    print(f"{len(groups)} worker processes, each with a private world\n")
    for i, g in enumerate(groups):
        print(f"  worker {i}: {' '.join(g)}")
    print()

    WORKERS_DIR.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    procs = []
    for i, group in enumerate(groups):
        world = WORKERS_DIR / f"w{i}"
        log = WORKERS_DIR / f"w{i}.log"
        cmd = [sys.executable, str(REPO / "scripts" / "run_baseline_local.py"),
               "-k", str(args.k), "--model", args.model, "--world-dir", str(world)]
        for cid in group:
            cmd += ["--case", cid]
        procs.append((i, group, subprocess.Popen(
            cmd, cwd=REPO, stdout=log.open("w"), stderr=subprocess.STDOUT), log))

    failed = []
    for i, group, p, log in procs:
        rc = p.wait()
        tail = log.read_text().strip().splitlines()
        status = "ok" if rc == 0 else f"EXIT {rc}"
        print(f"  worker {i} {status}")
        for line in tail:
            if line.strip().startswith("e-"):
                print(f"    {line.strip()}")
        if rc != 0:
            failed.append(i)
            print(f"    see {log}")

    mins = (time.time() - t0) / 60
    print(f"\nfinished in {mins:.0f} min")
    if failed:
        print(f"WORKERS FAILED: {failed} — results are incomplete")
        raise SystemExit(1)

    done = sorted(OUT.glob("e-*.json"))
    print(f"{len(done)} of {len(ids)} cases have results")
    print("\nnext: .venv/bin/python scripts/classify_cases.py")


if __name__ == "__main__":
    main()
