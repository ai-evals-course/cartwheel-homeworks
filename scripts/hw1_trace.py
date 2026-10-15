"""Trace viewer for hw1-session.jsonl. It reads the records and changes nothing.

    python3 scripts/hw1_trace.py                     one line per conversation
    python3 scripts/hw1_trace.py show B15 [B3 ...]   conversations as traces, with an evidence check
                                 [--full]            ... with full tool arguments and results
    python3 scripts/hw1_trace.py tools               which tools each conversation called
    python3 scripts/hw1_trace.py evidence            the evidence check for every conversation
    python3 scripts/hw1_trace.py partc               the Part C conversation before and after the edit
    python3 scripts/hw1_trace.py prompt [REV]        the prompt edit, with both prompt versions (git)
    uv run python scripts/hw1_trace.py call USER TOOL [key=value ...]
                                                     run one read-only tool as USER on the local data

Labels follow file order: B1, B2, ... for Part B (a repeated request becomes
B7a, B7b) and C-before, C-after1, ... for records with a prompt_version.
Record numbers (1-20) work too.

The evidence check is a heuristic. It finds dollar amounts, dates, durations,
order counts, and ticket, refund and product ids in the agent's messages, then
looks for the same value in that conversation's tool results. A value that is
found can still be attached to the wrong thing: a price is flagged when its
sentence names a different product than the one the price belongs to. It also
lists policy-sounding phrases and whether any policy source was consulted.

`call` reads the current database, which can differ from the recorded state
after a refund or cancellation (reset with `uv run python -m seed.generate`).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "hw1-session.jsonl"
PROMPT_BEFORE_REV = "244fd9e"  # Part A commit, before the Part C prompt edit
LIST_LIMIT = 20  # TOOL-5: list_my_orders returns at most 20 records

TOOLS = [  # registered tools, with short column headers
    ("search_help_center", "help"),
    ("get_policy", "policy"),
    ("check_return_eligibility", "elig"),
    ("get_order", "order"),
    ("find_order", "find"),
    ("list_my_orders", "list"),
    ("search_products", "prod"),
    ("issue_refund", "refund"),
    ("cancel_order", "cancel"),
    ("escalate_to_human", "escal"),
]
SHORT = dict(TOOLS)
POLICY_SOURCES = ("get_policy", "search_help_center", "check_return_eligibility")
READ_TOOLS = {
    "get_policy": ("agent.tools", "get_policy"),
    "search_help_center": ("agent.agent", "search_help_center_logic"),
    "search_products": ("agent.tools", "search_products"),
    "get_order": ("agent.agent", "get_order_logic"),
    "list_my_orders": ("agent.tools", "list_my_orders"),
    "find_order": ("agent.tools", "find_order"),
    "check_return_eligibility": ("agent.tools", "check_return_eligibility"),
}

COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
BOLD, DIM, RED, GREEN, YELLOW, CYAN = "1", "2", "31", "32", "33", "36"
WIDTH = min(shutil.get_terminal_size((110, 30)).columns, 120)


def paint(text: str, *codes: str) -> str:
    return f"\033[{';'.join(codes)}m{text}\033[0m" if COLOR and codes else text


MARK = {"ok": ("✓", GREEN), "bad": ("✗", RED), "warn": ("⚠", YELLOW)}


def mark(status: str) -> str:
    symbol, color = MARK[status]
    return paint(symbol, color, BOLD)


# ---------------------------------------------------------------------------
# Records and labels
# ---------------------------------------------------------------------------


def load() -> list[dict[str, Any]]:
    with RECORDS.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def make_labels(recs: list[dict[str, Any]]) -> list[str]:
    names: dict[int, str] = {}
    groups: list[list[int]] = []
    for i, r in enumerate(recs):
        if "prompt_version" in r:
            continue
        if groups and recs[groups[-1][-1]]["request"] == r["request"]:
            groups[-1].append(i)
        else:
            groups.append([i])
    for n, group in enumerate(groups, 1):
        for k, i in enumerate(group):
            names[i] = f"B{n}" + ("abcdefgh"[k] if len(group) > 1 else "")
    part_c = [i for i, r in enumerate(recs) if "prompt_version" in r]
    if part_c:
        first = recs[part_c[0]]["prompt_version"]
        before = [i for i in part_c if recs[i]["prompt_version"] == first]
        after = [i for i in part_c if recs[i]["prompt_version"] != first]
        for tag, group in (("C-before", before), ("C-after", after)):
            for k, i in enumerate(group, 1):
                names[i] = tag + (str(k) if len(group) > 1 else "")
    return [names[i] for i in range(len(recs))]


def pick(recs: list[dict[str, Any]], labels: list[str], key: str) -> int:
    lowered = [label.lower() for label in labels]
    if key.lower() in lowered:
        return lowered.index(key.lower())
    if key.isdigit() and 1 <= int(key) <= len(recs):
        return int(key) - 1
    sys.exit(f"no record {key!r}; labels: {', '.join(labels)}")


def agent_messages(r: dict[str, Any]) -> list[str]:
    if "turns" in r:
        return [m for turn in r["turns"] for m in turn["agent"]]
    return [r["response"]]


def plain(text: str) -> str:
    return text.replace("**", "")


def requirement(r: dict[str, Any]) -> str:
    req = r["requirement"]
    return ",".join(req) if isinstance(req, list) else str(req)


def met(r: dict[str, Any]) -> str:
    return paint("yes", GREEN) if r["met_requirement"] else paint("NO", RED, BOLD)


def pad(text: str, width: int) -> str:
    """Left-justify by visible width, ignoring color codes."""
    visible = len(re.sub(r"\033\[[0-9;]*m", "", text))
    return text + " " * max(0, width - visible)


def wrap(text: str, indent: int, width: int = WIDTH) -> list[str]:
    lines = []
    for raw in plain(text).splitlines() or [""]:
        lines += textwrap.wrap(raw, width - indent) or [""]
    return lines


# ---------------------------------------------------------------------------
# Tool calls and results
# ---------------------------------------------------------------------------


def money(value: float) -> str:
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def call_line(call: dict[str, Any], full: bool) -> str:
    parts = []
    for key, value in call["arguments"].items():
        text = json.dumps(value, ensure_ascii=False)
        if not full and len(text) > 100:
            text = text[:96] + '..."'
        parts.append(f"{key}={text}")
    return paint(call["name"], CYAN, BOLD) + "(" + ", ".join(parts) + ")"


def order_line(o: dict[str, Any]) -> str:
    bits = [f"order {o['order_id']}", o["status"], money(o["total_usd"])]
    for field in ("ordered_at", "shipped_at", "delivered_at"):
        if o.get(field):
            bits.append(f"{field.split('_')[0]} {o[field]}")
        elif field == "delivered_at" and o["status"] in ("delivered", "refunded"):
            bits.append(paint("delivered_at MISSING", YELLOW, BOLD))
    dates = [o[f] for f in ("ordered_at", "shipped_at", "delivered_at") if o.get(f)]
    if dates != sorted(dates):
        bits.append(paint("dates out of order", YELLOW, BOLD))
    flag = o.get("refund_eligible")
    bits.append(paint(f"refund_eligible {str(flag).lower()}", GREEN if flag else RED))
    if o.get("store_name"):
        bits.append(o["store_name"])
    return " · ".join(bits)


def describe(name: str, result: Any, full: bool = False) -> list[str]:
    """One or more short lines that summarize a tool result."""
    if not isinstance(result, dict):
        return [str(result)[:200]]
    if result.get("ok") is False:
        return [paint(f"✗ {result.get('error')}", RED, BOLD) + f"  {result.get('reason', '')}"]
    if "order" in result:
        return [order_line(result["order"])]
    if "orders" in result:
        lines = [order_line(o) for o in result["orders"]] or ["no matching orders"]
        if len(lines) > 6 and not full:
            hidden = len(lines) - 4
            lines = lines[:3] + [paint(f"... {hidden} more orders (--full shows all) ...", DIM)] + lines[-1:]
        if name == "list_my_orders" and result.get("count") == LIST_LIMIT:
            lines.append(paint(
                f"count {LIST_LIMIT} is the tool's maximum: older orders may be cut off, "
                "and nothing in the result says so", YELLOW))
        return lines
    if "products" in result:
        lines = []
        for p in result["products"]:
            price = money(p["price_usd"])
            if p["price_usd"] <= 0:
                price = paint(price + "  invalid price", RED, BOLD)
            lines.append(f"#{p['product_id']} {p['title']}  {price}")
        return lines or ["no matching products"]
    if "ticket_id" in result:
        return [f"ticket {result['ticket_id']} · SLA {result['sla_hours']} h"]
    if "refund_id" in result:
        line = f"refund {result['refund_id']} · {money(result['amount_usd'])} · {result['status']}"
        return [line, paint(f"note: {result.get('note', '')}", DIM)]
    if result.get("status") == "cancelled":
        return [f"order {result['order_id']} → cancelled"]
    if "body" in result:
        return [f"{result['policy_id']} · {result['title']}", paint(result["body"], DIM)]
    if "results" in result:
        return [f"{h['policy_id']} ({h['score']}) {h['title']}" for h in result["results"]]
    if "eligible" in result:
        lines = [
            f"eligible {json.dumps(result['eligible'])} · {result['reason']} · "
            f"window {result['return_window_days']} days ({result['window_source']}) · "
            f"last return day {result['last_return_day'] or 'null'} · as of {result['as_of']}",
            f"policy ids {', '.join(result['policy_ids'])}",
        ]
        if result["data_issues"]:
            lines.append(paint("data issues: " + "; ".join(result["data_issues"]), YELLOW, BOLD))
        if result.get("note"):
            lines.append(paint(f"note: {result['note']}", DIM))
        return lines
    return [json.dumps(result, ensure_ascii=False)[:300]]


# ---------------------------------------------------------------------------
# Evidence check
# ---------------------------------------------------------------------------

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
MONEY = re.compile(r"(-)?\$\s?(-)?(\d+(?:,\d{3})*(?:\.\d+)?)")
DURATION = re.compile(r"\b(\d+)(?:\s*(?:-|–|to)\s*(\d+))?\s+(?:business\s+)?(days?|hours?)\b", re.I)
DATE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", re.I)
IDS = re.compile(r"\b(ticket|refund|product)(?:\s+id)?\s*#?\s*(\d+)\b", re.I)
COUNT = re.compile(r"\b(\d+)\s+orders?\b", re.I)
POLICY_ID = re.compile(r"\b(?:cw-[a-z-]+|store-[a-z0-9-]+-policy)\b")
POLICY_PHRASES = re.compile(
    r"return window|refund window|window has (?:already )?closed|return polic\w*|refund polic\w*"
    r"|standard return\w*|business days|exception|threshold|won't be charged|card issuer"
    r"|credit card company|for security reasons",
    re.I,
)


def leaves(obj: Any, path: str, owner: str | None = None) -> Iterator[tuple[str, str, Any, str | None]]:
    """(path, key, value, owner) for every scalar; owner is the product title or order id."""
    if isinstance(obj, dict):
        if "title" in obj:
            owner = obj["title"]
        elif "order_id" in obj:
            owner = f"order {obj['order_id']}"
        for key, value in obj.items():
            yield from leaves(value, f"{path}.{key}", owner)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from leaves(value, f"{path}[{i}]", owner)
    else:
        yield path, re.sub(r"\[\d+\]$", "", path.rsplit(".", 1)[-1]), obj, owner


def sentences(text: str) -> list[str]:
    return [s.strip(" -") for s in re.split(r"(?<=[.!?])\s+|\n+", plain(text)) if s.strip(" -")]


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evidence(r: dict[str, Any]) -> dict[str, Any]:
    facts = []
    for n, call in enumerate(r["tool_calls"]):
        facts += list(leaves(call["result"], call["name"]))
    titles = {value for _, key, value, _ in facts if key == "title"}
    strings = [(path, value) for path, _, value, _ in facts if isinstance(value, str)]
    text = "\n".join(agent_messages(r))
    claims: dict[tuple[str, str], tuple[str, str]] = {}

    def add(shown: str, status: str, detail: str) -> None:
        claims.setdefault((shown, detail), (status, detail))

    for sentence in sentences(text):
        named = [t for t in titles if t.lower() in sentence.lower()]
        for m in MONEY.finditer(sentence):
            value = float(m.group(3).replace(",", "")) * (-1 if (m.group(1) or m.group(2)) else 1)
            hits = [(p, owner) for p, key, v, owner in facts
                    if is_number(v) and re.search(r"usd|price|total|amount", key) and abs(v - value) < 0.005]
            hits += [(p, None) for p, s in strings if f"${value:g}" in s]
            shown = m.group(0)
            if not hits:
                add(shown, "bad", "not in any tool result")
            elif named and not any(owner in named for _, owner in hits):
                owners = sorted({owner for _, owner in hits if owner})
                add(shown, "warn", f"belongs to {', '.join(owners)}, but the sentence names {', '.join(named)}")
            else:
                add(shown, "ok", hits[0][0] + (f" ({hits[0][1]})" if hits[0][1] else ""))
        for m in DURATION.finditer(sentence):
            numbers = [int(g) for g in m.groups()[:2] if g]
            stem = "hour" if m.group(3).lower().startswith("hour") else "day"
            keyed = [p for p, key, v, _ in facts
                     if is_number(v) and v in numbers and (stem in key or (stem == "hour" and "sla" in key))]
            phrased = [p for p, s in strings for d in DURATION.finditer(s)
                       if [int(g) for g in d.groups()[:2] if g] == numbers]
            hits = phrased or (keyed if len(numbers) == 1 else [])
            add(m.group(0), "ok" if hits else "bad", hits[0] if hits else "not in any tool result")
        for m in DATE.finditer(sentence):
            month, day, year = MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)), m.group(3)
            hits = [p for p, s in strings
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) and s[5:] == f"{month:02d}-{day:02d}"
                    and (year is None or s[:4] == year)]
            add(m.group(0), "ok" if hits else "bad", hits[0] if hits else "not in any tool result")
        for m in IDS.finditer(sentence):
            field, number = f"{m.group(1).lower()}_id", int(m.group(2))
            hits = [p for p, key, v, _ in facts if key == field and v == number]
            add(m.group(0), "ok" if hits else "bad", hits[0] if hits else "not in any tool result")
        for m in COUNT.finditer(sentence):
            number = int(m.group(1))
            hits = [p for p, key, v, _ in facts if key == "count" and v == number]
            if hits and hits[0].startswith("list_my_orders") and number == LIST_LIMIT:
                add(m.group(0), "warn", f"{hits[0]} is capped at {LIST_LIMIT}; it is not a total")
            else:
                add(m.group(0), "ok" if hits else "bad", hits[0] if hits else "not in any tool result")

    return {
        "policy_calls": [c["name"] for c in r["tool_calls"] if c["name"] in POLICY_SOURCES],
        "cited": sorted(set(POLICY_ID.findall(text))),
        "phrases": sorted({m.group(0).lower() for m in POLICY_PHRASES.finditer(plain(text))}),
        "claims": [(shown, status, detail) for (shown, _), (status, detail) in claims.items()],
    }


def print_evidence(r: dict[str, Any]) -> None:
    ev = evidence(r)
    print(paint("EVIDENCE CHECK", BOLD) + paint("  heuristic: the agent's values vs this conversation's tool results", DIM))
    calls = ", ".join(ev["policy_calls"]) or paint("none", RED)
    print(f"  policy sources called   {calls}" + paint("   (get_policy, search_help_center, check_return_eligibility)", DIM))
    print(f"  policy ids cited        {', '.join(ev['cited']) or paint('none', RED)}")
    phrases = ", ".join(f'"{p}"' for p in ev["phrases"])
    if phrases and not ev["policy_calls"]:
        phrases = paint(phrases, YELLOW) + paint("   (no policy source behind them)", DIM)
    print(f"  policy-sounding phrases {phrases or 'none'}")
    if ev["claims"]:
        print("  values")
        width = max(len(shown) for shown, _, _ in ev["claims"]) + 2
        for shown, status, detail in ev["claims"]:
            color = {"ok": DIM, "bad": RED, "warn": YELLOW}[status]
            print(f"    {mark(status)} {shown:<{width}}{paint(detail, color)}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_list(recs: list[dict[str, Any]], labels: list[str]) -> None:
    header = f"{'#':<10}{'role user':<14}{'met':<5}{'requirement':<15}{'source':<15}{'tools':<27}request"
    print(paint(header, BOLD))
    for label, r in zip(labels, recs):
        tools = " › ".join(SHORT.get(c["name"], c["name"]) for c in r["tool_calls"]) or "-"
        request = r["request"].replace("\n", " ")
        line = (f"{label:<10}{r['role'] + ' ' + str(r['user_id']):<14}{pad(met(r), 5)}"
                f"{requirement(r):<15}{r['problem_source'] or 'null':<15}{tools:<27}")
        room = max(20, WIDTH - 86)
        print(line + (request if len(request) <= room else request[: room - 1] + "…"))
    unmet = Counter(i for r in recs if not r["met_requirement"] for i in r["requirement"])
    print(f"\n{len(recs)} records · roles {dict(Counter(r['role'] for r in recs))} · "
          f"met {sum(r['met_requirement'] for r in recs)}/{len(recs)} · "
          f"sources {dict(Counter(r['problem_source'] or 'null' for r in recs))}")
    print(f"requirements not met (a record can count several): {dict(unmet.most_common())}")


def cmd_show(recs: list[dict[str, Any]], labels: list[str], keys: list[str], full: bool) -> None:
    for key in keys or ["B1"]:
        i = pick(recs, labels, key)
        r = recs[i]
        title = f" {labels[i]} · {r['role']} {r['user_id']}" + (
            f" · store {r['store_id']}" if r["store_id"] else "") + (
            f" · prompt_version {r['prompt_version']}" if "prompt_version" in r else "") + " "
        print(paint(title.ljust(WIDTH, "━"), BOLD))
        print(f"requirement {requirement(r)} · met {met(r)} · source {r['problem_source'] or 'null'}\n")
        print(paint("EXPECTED", BOLD) + paint("  written from SPEC.md before the run", DIM))
        for line in wrap(r["expected"], 2):
            print("  " + line)
        print()
        print(paint("TRACE", BOLD))
        if "turns" in r:
            for turn in r["turns"]:
                print_message("user", turn["user"])
                for message in turn["agent"]:
                    print_message("agent", message)
            print(paint("  tools, in call order (the record does not store which turn made each call)", DIM))
            print_calls(r, full)
        else:
            print_message("user", r["request"])
            print_calls(r, full)
            print_message("agent", r["response"])
        print()
        print_evidence(r)
        print()


def print_message(who: str, text: str) -> None:
    color = YELLOW if who == "user" else GREEN
    lines = wrap(text, 9)
    print(f"  {paint(f'{who:<6}', color, BOLD)} {lines[0]}")
    for line in lines[1:]:
        print(f"         {line}")


def print_calls(r: dict[str, Any], full: bool) -> None:
    if not r["tool_calls"]:
        print(f"  {paint('tool', CYAN, BOLD):<6}   {paint('no tool calls', DIM)}")
    for call in r["tool_calls"]:
        print(f"  {paint('tool  ', CYAN, BOLD)} {call_line(call, full)}")
        if full:
            for line in json.dumps(call["result"], indent=2, ensure_ascii=False).splitlines():
                print(f"           {paint(line, DIM)}")
        else:
            for line in describe(call["name"], call["result"], full):
                for part in textwrap.wrap(line, WIDTH - 11) or [""]:
                    print(f"           {part}")


def cmd_tools(recs: list[dict[str, Any]], labels: list[str]) -> None:
    print(paint(f"{'#':<10}" + "".join(f"{short:>8}" for _, short in TOOLS) + "   met", BOLD))
    for label, r in zip(labels, recs):
        cells = []
        for name, _ in TOOLS:
            calls = [c for c in r["tool_calls"] if c["name"] == name]
            failed = sum(c["result"].get("ok") is False for c in calls if isinstance(c["result"], dict))
            if not calls:
                cells.append(paint(f"{'·':>8}", DIM))
            elif failed:
                cells.append(paint(f"{f'{len(calls)}✗':>8}", RED, BOLD))
            else:
                cells.append(paint(f"{len(calls):>8}", GREEN))
        print(f"{label:<10}" + "".join(cells) + "   " + met(r))
    print(paint("legend: " + ", ".join(f"{short}={name}" for name, short in TOOLS), DIM))
    print(paint("count = calls in that conversation; ✗ = at least one returned ok: false", DIM))
    print()
    print(paint(f"{'tool':<26}{'calls':>6}{'ok':>5}  errors  conversations", BOLD))
    for name, _ in TOOLS:
        calls = [(label, c) for label, r in zip(labels, recs) for c in r["tool_calls"] if c["name"] == name]
        errors = Counter(c["result"].get("error") for _, c in calls if c["result"].get("ok") is False)
        users = sorted({label for label, _ in calls}, key=labels.index)
        ok = len(calls) - sum(errors.values())
        text = f"{name:<26}{len(calls):>6}{ok:>5}  {dict(errors) or '-'!s:<7} {', '.join(users) or paint('never called', RED)}"
        print(text)
    print(paint("check_return_eligibility was added after Part B; only the Part C conversations had it.", DIM))


def cmd_evidence(recs: list[dict[str, Any]], labels: list[str]) -> None:
    print(paint(f"{'#':<10}{'met':<5}{'policy':>7}{'cited':>7}{'phrases':>9}{'✓':>4}{'✗':>4}{'⚠':>4}   unsupported or misattributed values", BOLD))
    totals = Counter()
    for label, r in zip(labels, recs):
        ev = evidence(r)
        counts = Counter(status for _, status, _ in ev["claims"])
        problems = [shown for shown, status, _ in ev["claims"] if status != "ok"]
        totals.update(policy=bool(ev["policy_calls"]), cited=bool(ev["cited"]),
                      phrases=bool(ev["phrases"]), problems=bool(problems),
                      phrases_unsourced=bool(ev["phrases"]) and not ev["policy_calls"])
        bad = paint(f"{counts['bad']:>4}", RED) if counts["bad"] else f"{0:>4}"
        warn = paint(f"{counts['warn']:>4}", YELLOW) if counts["warn"] else f"{0:>4}"
        print(f"{label:<10}{pad(met(r), 5)}{len(ev['policy_calls']):>7}{len(ev['cited']):>7}"
              f"{len(ev['phrases']):>9}{counts['ok']:>4}{bad}{warn}   " + paint(", ".join(problems), YELLOW))
    n = len(recs)
    print()
    print(f"conversations that called a policy source:         {totals['policy']}/{n}")
    print(f"conversations that cited a policy id:              {totals['cited']}/{n}")
    print(f"conversations with policy-sounding phrases:        {totals['phrases']}/{n}"
          f" ({totals['phrases_unsourced']} with no policy source)")
    print(f"conversations with an unsupported or misattributed value: {totals['problems']}/{n}")
    print(paint("policy = calls to get_policy, search_help_center or check_return_eligibility; "
                "phrases = policy-sounding phrases; ✓/✗/⚠ = values found / not found / misattributed", DIM))


def cmd_partc(recs: list[dict[str, Any]], labels: list[str]) -> None:
    part_c = [r for r in recs if "prompt_version" in r]
    if not part_c:
        sys.exit("no record has a prompt_version")
    request = part_c[0]["request"]
    tally: dict[str, list[bool]] = {}
    print(paint(f'Part C test: "{request}"', BOLD) + "\n")
    for label, r in zip(labels, recs):
        if r["request"] != request:
            continue
        version = r.get("prompt_version", "not recorded (Part B)")
        tally.setdefault(version, []).append(r["met_requirement"])
        print(paint(f"── {label} · prompt_version {version} · {requirement(r)} ", BOLD) + met(r))
        for call in r["tool_calls"]:
            print("   " + call_line(call, full=False))
            for line in describe(call["name"], call["result"]):
                print("      " + line)
        for line in wrap(r["response"], 3):
            print("   " + paint(line, GREEN))
        for shown, status, detail in evidence(r)["claims"]:
            if status != "ok":
                print(f"   {mark(status)} {shown}  {paint(detail, YELLOW)}")
        print()
    for version, results in tally.items():
        print(f"prompt_version {version:<22} met {sum(results)}/{len(results)}")


def template_from(source: str) -> str:
    match = re.search(r'SYSTEM_PROMPT_TEMPLATE = """\\\n(.*?)"""', source, re.S)
    if not match:
        sys.exit("SYSTEM_PROMPT_TEMPLATE not found")
    return match.group(1)


def cmd_prompt(recs: list[dict[str, Any]], labels: list[str], rev: str) -> None:
    old_source = subprocess.run(
        ["git", "show", f"{rev}:agent/agent.py"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    old = template_from(old_source)
    new = template_from((ROOT / "agent" / "agent.py").read_text(encoding="utf-8"))
    for name, template in ((f"{rev}:agent/agent.py", old), ("agent/agent.py (working tree)", new)):
        version = hashlib.sha256(template.encode()).hexdigest()[:12]
        used = [label for label, r in zip(labels, recs) if r.get("prompt_version") == version]
        print(f"prompt_version {paint(version, BOLD)}  {name:<32}" + (f"used by {', '.join(used)}" if used else ""))
    print()
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), "before", "after", lineterm="", n=2):
        color = GREEN if line.startswith("+") else RED if line.startswith("-") else CYAN if line.startswith("@@") else ""
        print(paint(line, color, BOLD) if color in (GREEN, RED) else paint(line, color) if color else line)


def cmd_call(args: list[str]) -> None:
    if len(args) < 2:
        sys.exit("usage: call USER TOOL [key=value ...]")
    user_id, name = int(args[0]), args[1]
    if name not in READ_TOOLS:
        sys.exit(f"{name!r} is not a read-only tool here; choose from: {', '.join(READ_TOOLS)}")
    kwargs = {}
    for pair in args[2:]:
        key, _, raw = pair.partition("=")
        try:
            kwargs[key] = json.loads(raw)
        except json.JSONDecodeError:
            kwargs[key] = raw
    sys.path.insert(0, str(ROOT))
    import importlib

    from agent import db
    from agent.auth import AuthContext

    with db.connection() as conn:
        user = db.get_user(conn, user_id)
    if user is None:
        sys.exit(f"no user {user_id}")
    ctx = AuthContext(user_id=user.id, role=user.role, store_id=user.store_id)
    module, function = READ_TOOLS[name]
    result = getattr(importlib.import_module(module), function)(ctx, **kwargs)
    shown = ", ".join(f"{k}={json.dumps(v)}" for k, v in kwargs.items())
    print(paint(f"as {user.role} {user.id}" + (f" (store {user.store_id})" if user.store_id else ""), BOLD)
          + f": {paint(name, CYAN, BOLD)}({shown})")
    for line in describe(name, result):
        print("  " + line)
    print()
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "list"
    if command == "call":
        cmd_call(args[1:])
        return
    recs = load()
    labels = make_labels(recs)
    if command == "list":
        cmd_list(recs, labels)
    elif command == "show":
        rest = [a for a in args[1:] if a != "--full"]
        cmd_show(recs, labels, rest, full="--full" in args)
    elif command == "tools":
        cmd_tools(recs, labels)
    elif command == "evidence":
        cmd_evidence(recs, labels)
    elif command == "partc":
        cmd_partc(recs, labels)
    elif command == "prompt":
        cmd_prompt(recs, labels, args[1] if len(args) > 1 else PROMPT_BEFORE_REV)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
