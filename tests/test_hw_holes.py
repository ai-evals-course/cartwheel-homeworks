"""Contract tests for homework implementations.

Each test is marked xfail(raises=NotImplementedError): it "fails as
expected" while the hole is unimplemented, and flips to passing (XPASS)
once you implement the function correctly. If your implementation is wrong,
the test fails loudly with an assertion error instead. Run the tests alongside the inspection steps in each homework.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agent import db, tools
from agent.auth import AuthContext

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
SHOPPER_2 = AuthContext(user_id=2, role="shopper")
MERCHANT_STORE_1 = AuthContext(user_id=9001, role="merchant", store_id=1)
SUPPORT = AuthContext(user_id=9501, role="support")


def hw(n: int, name: str):
    return pytest.mark.xfail(
        raises=NotImplementedError,
        reason=f"HW{n}: implement {name}",
        strict=False,
    )


# ---------------------------------------------------------------------------
# Homework 1: agent/tools.py
# ---------------------------------------------------------------------------


@hw(1, "get_policy")
def test_hw1_get_policy(world: dict) -> None:
    result = tools.get_policy(SHOPPER_1, "cw-returns")
    assert result["ok"] is True
    assert result["policy_id"] == "cw-returns"
    assert "30" in result["body"]
    assert "policy_id:" not in result["body"]  # front matter stripped

    missing = tools.get_policy(SHOPPER_1, "cw-does-not-exist")
    assert missing["ok"] is False
    assert missing["error"] == "not_found"


@hw(1, "search_products")
def test_hw1_search_products(world: dict) -> None:
    # Use a token guaranteed to exist: the last word of a real product title.
    conn = db.connect()
    try:
        title = conn.execute(
            "SELECT title FROM products WHERE store_id = 1 ORDER BY id LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()
    token = title.split()[-1]

    result = tools.search_products(SHOPPER_1, token, store="Blue Heron Ceramics")
    assert result["ok"] is True
    assert result["count"] == len(result["products"]) >= 1
    prices = [p["price_usd"] for p in result["products"]]
    assert prices == sorted(prices)
    assert all(p["store_id"] == 1 for p in result["products"])
    assert all(token.lower() in p["title"].lower() for p in result["products"])

    assert tools.search_products(SHOPPER_1, "")["error"] == "invalid_argument"
    assert tools.search_products(SHOPPER_1, "mug", store="No Such Store")["error"] == "not_found"


@hw(1, "list_my_orders")
def test_hw1_list_my_orders(world: dict) -> None:
    conn = db.connect()
    try:
        expected_user = [o.id for o in db.list_orders_for_user(conn, 1)]
        expected_store = [o.id for o in db.list_orders_for_store(conn, 1)]
    finally:
        conn.close()

    shopper = tools.list_my_orders(SHOPPER_1)
    assert shopper["ok"] is True
    assert [o["order_id"] for o in shopper["orders"]] == expected_user
    assert shopper["count"] == len(expected_user)

    merchant = tools.list_my_orders(MERCHANT_STORE_1)
    assert merchant["ok"] is True
    assert [o["order_id"] for o in merchant["orders"]] == expected_store

    support = tools.list_my_orders(SUPPORT)
    assert support["ok"] is False
    assert support["error"] == "invalid_argument"


@hw(1, "cancel_order")
def test_hw1_cancel_order(world_copy: Path) -> None:
    conn = sqlite3.connect(world_copy)
    try:
        order_id, owner_id = conn.execute(
            "SELECT id, user_id FROM orders WHERE status = 'placed' ORDER BY id LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    owner = AuthContext(user_id=owner_id, role="shopper")
    stranger = AuthContext(user_id=owner_id + 1, role="shopper")

    # Scope check comes first: a stranger learns nothing.
    denied = tools.cancel_order(stranger, order_id, "not mine")
    assert denied["ok"] is False
    assert denied["error"] == "permission_denied"

    # Pre-shipment rule: a delivered order is not cancellable even in scope.
    delivered = tools.cancel_order(SHOPPER_1, 4127, "too late")
    assert delivered["ok"] is False
    assert delivered["error"] == "not_eligible"

    # Happy path persists the status.
    result = tools.cancel_order(owner, order_id, "changed my mind")
    assert result == {"ok": True, "order_id": order_id, "status": "cancelled"}
    conn = sqlite3.connect(world_copy)
    try:
        status = conn.execute(
            "SELECT status FROM orders WHERE id = ?", (order_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "cancelled"

    missing = tools.cancel_order(SHOPPER_1, 999_999, "ghost")
    assert missing["error"] == "not_found"


@hw(1, "find_order")
def test_hw1_find_order(world: dict) -> None:
    # Shopper 1 owns order 4127, which contains a product.
    conn = sqlite3.connect(world["db"])
    try:
        product_name = conn.execute(
            "SELECT p.title FROM orders o JOIN products p ON o.product_id = p.id WHERE o.id = 4127"
        ).fetchone()[0]
    finally:
        conn.close()

    result = tools.find_order(SHOPPER_1, product_name)
    assert result["ok"] is True
    assert isinstance(result["orders"], list)
    assert any(o["order_id"] == 4127 for o in result["orders"])

    # No match returns an empty list, not an error.
    empty = tools.find_order(SHOPPER_1, "zzzznonexistent9999")
    assert empty == {"ok": True, "orders": []}


# ---------------------------------------------------------------------------
# Homework 2: instrumentation and authenticated endpoint
# ---------------------------------------------------------------------------


@hw(2, "create_session")
def test_hw2_create_session_binds_verified_identity(world: dict) -> None:
    from server import app as server_app

    server_app._SESSIONS.clear()
    response = server_app.create_session(
        server_app.SessionCreate(user_id=9002, role="merchant")
    )
    payload = server_app.verify_token(response["token"])

    assert response["session_id"] in server_app._SESSIONS
    assert payload is not None
    assert payload["session_id"] == response["session_id"]
    assert payload["user_id"] == 9002
    assert payload["role"] == "merchant"
    assert payload["store_id"] == 2


@pytest.mark.xfail(
    raises=NotImplementedError,
    reason="optional ATIF reader extension",
    strict=False,
)
def test_optional_atif_export() -> None:
    from scenarios.atif_export import export_trace

    trace = {
        "id": "trace-1",
        "name": "cartwheel-support",
        "observations": [
            {
                "id": "obs-tool",
                "parentObservationId": "obs-gen",
                "type": "SPAN",
                "name": "get_order",
                "startTime": "2026-07-01T10:00:02Z",
                "input": {"order_id": 4127},
                "output": {"ok": True},
                "model": None,
                "usage": None,
                "metadata": {"cartwheel.user_role": "shopper"},
            },
            {
                "id": "obs-gen",
                "parentObservationId": None,
                "type": "GENERATION",
                "name": "llm-call",
                "startTime": "2026-07-01T10:00:01Z",
                "input": "where is my order",
                "output": "let me check",
                "model": "gpt-5.5",
                "usage": {"input": 4000, "output": 500},
                "metadata": None,
            },
        ],
    }
    trajectory = export_trace(trace)
    assert trajectory["session_id"] == "trace-1"
    assert trajectory["agent"]["model"] == "gpt-5.5"
    steps = trajectory["steps"]
    assert [s["step_id"] for s in steps] == ["obs-gen", "obs-tool"]  # startTime order
    assert steps[0]["source"] == "agent"
    assert steps[0]["usage"] == {"input_tokens": 4000, "output_tokens": 500}
    assert steps[1]["source"] == "tool"
    assert steps[1]["tool_call"]["tool_name"] == "get_order"
    assert steps[1]["parent_step_id"] == "obs-gen"


# ---------------------------------------------------------------------------
# Homework 6: CI, and Homework 7: CD
# ---------------------------------------------------------------------------


@hw(6, "pass_at_k")
def test_hw6_pass_at_k_matches_the_worked_values() -> None:
    from tests.eval.passk import pass_at_k

    assert pass_at_k(8, 6, 1) == pytest.approx(0.75)
    assert pass_at_k(8, 6, 2) == pytest.approx(27 / 28)
    assert pass_at_k(8, 6, 4) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        pass_at_k(0, 0, 0)


@hw(6, "pass_hat_k")
def test_hw6_pass_hat_k_matches_the_worked_values() -> None:
    from tests.eval.passk import pass_hat_k

    assert pass_hat_k(8, 6, 2) == pytest.approx(15 / 28)
    assert pass_hat_k(8, 6, 4) == pytest.approx(15 / 70)
    assert pass_hat_k(8, 6, 8) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        pass_hat_k(4, 5, 1)


@hw(6, "case_passes")
def test_hw6_case_passes_uses_the_reliability_rule() -> None:
    from tests.eval.passk import case_passes

    assert case_passes("regression", 5, 5)["decision"] == "pass"
    assert case_passes("regression", 4, 5)["decision"] == "block"
    assert case_passes("capability", 3, 5, 0.6)["decision"] == "pass"
    assert case_passes("capability", 2, 5, 0.6)["decision"] == "pass"
    assert case_passes("capability", 1, 5, 0.6)["decision"] == "pass"
    assert case_passes("capability", 0, 5, 0.6)["decision"] == "pass"


@hw(6, "replay_case")
def test_hw6_replay_resets_every_attempt_and_never_retries_a_verdict() -> None:
    from replay.harness import ReplayInfraError, replay_case

    events: list[str] = []
    outcomes: list[object] = [
        ReplayInfraError("timeout"),
        {"passed": False},
        {"passed": True},
    ]

    def reset() -> None:
        events.append("reset")

    def runner() -> dict:
        events.append("run")
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    records = replay_case(runner, reset, n=2, max_infra_retries=1)
    assert events == ["reset", "run", "reset", "run", "reset", "run"]
    assert [record["passed"] for record in records] == [False, True]
    assert [record["rollout"] for record in records] == [0, 1]


@hw(6, "summarize_rollouts")
def test_hw6_rollout_summary_reports_rate_modes_and_steps() -> None:
    from replay.harness import summarize_rollouts

    records = [
        {"passed": True, "steps": 2},
        {"passed": False, "failure_modes": ["mode-a"], "steps": 4},
        {"passed": False, "failure_modes": ["mode-a", "mode-b"], "steps": 6},
        {"passed": True, "steps": 8},
    ]
    summary = summarize_rollouts(records, bootstrap_iterations=200, seed=7)
    assert summary["n"] == 4
    assert summary["failures"] == 2
    assert summary["failure_rate"] == pytest.approx(0.5)
    assert summary["ci_low"] <= summary["failure_rate"] <= summary["ci_high"]
    assert summary["mode_counts"] == {"mode-a": 2, "mode-b": 1}
    assert summary["steps"] == {"min": 2, "median": 5.0, "max": 8}


@hw(7, "select_traces")
def test_hw7_sampling_keeps_the_random_sample_separate_from_risk_groups() -> None:
    from monitoring.sample import select_traces

    traces = [
        {"id": f"trace-{i}", "risk": i in {1, 4}, "negative": i in {4, 7}}
        for i in range(10)
    ]
    original = [dict(trace) for trace in traces]
    plan = select_traces(
        traces,
        random_rate=0.2,
        risk_groups={
            "risk": lambda trace: trace["risk"],
            "negative": lambda trace: trace["negative"],
        },
        seed=7,
    )
    assert len(plan["random"]) == 2
    assert [trace["id"] for trace in plan["risk_groups"]["risk"]] == [
        "trace-1",
        "trace-4",
    ]
    assert [trace["id"] for trace in plan["risk_groups"]["negative"]] == [
        "trace-4",
        "trace-7",
    ]
    sampled_ids = [trace["id"] for trace in plan["to_judge"]]
    assert len(sampled_ids) == len(set(sampled_ids))
    assert {"trace-1", "trace-4", "trace-7"} <= set(sampled_ids)
    assert traces == original


@hw(7, "corrected_mode_prevalence")
def test_hw7_corrected_prevalence_uses_both_sources_of_uncertainty() -> None:
    from monitoring.correct import corrected_mode_prevalence

    sample_predictions = [1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    test_labels = [1, 1, 1, 1, 0, 0, 0, 0]
    test_predictions = [1, 1, 1, 0, 0, 0, 0, 1]
    first = corrected_mode_prevalence(
        sample_predictions,
        test_labels,
        test_predictions,
        bootstrap_iterations=500,
        seed=7,
    )
    second = corrected_mode_prevalence(
        sample_predictions,
        test_labels,
        test_predictions,
        bootstrap_iterations=500,
        seed=7,
    )
    assert first == second
    assert first["raw"] == pytest.approx(0.3)
    assert first["corrected"] == pytest.approx(0.1)
    assert first["test_tpr"] == pytest.approx(0.75)
    assert first["test_tnr"] == pytest.approx(0.75)
    assert first["ci_low"] <= first["corrected"] <= first["ci_high"]


@hw(7, "build_score_records")
def test_hw7_score_records_are_stable_and_complete() -> None:
    from monitoring.write_scores import build_score_records

    estimate = {
        "raw": 0.2,
        "corrected": 0.15,
        "ci_low": 0.08,
        "ci_high": 0.24,
        "n_sample": 100,
    }
    verdicts = {"trace-a": 1, "trace-b": 0}
    first = build_score_records(
        "unsupported_policy_claim", verdicts, estimate, "2026-W28"
    )
    second = build_score_records(
        "unsupported_policy_claim", verdicts, estimate, "2026-W28"
    )
    assert first == second
    assert len(first) == 3
    assert [record["trace_id"] for record in first] == ["trace-a", "trace-b", None]
    assert [record["value"] for record in first] == [1.0, 0.0, 0.15]
    assert all(len(record["score_id"]) == 32 for record in first)
    assert first[-1]["comment"] == "95% CI 0.08-0.24, raw 0.2, n=100"


@hw(6, "find_leaks")
def test_hw6_leakage_check_normalizes_text_and_ignores_short_inputs() -> None:
    from scripts.check_leakage import find_leaks

    evaluation_inputs = {
        "e-002": "Please refund order 3980 because it arrived too late.",
        "e-001": "Show me order 4127 and tell me whether it was delivered.",
        "short": "thanks",
    }
    prompt_texts = {
        "agent": "SHOW ME ORDER 4127\n and tell me whether it was delivered.",
        "judge": "Example: Please refund order 3980 because it arrived too late.",
    }
    leaks = find_leaks(evaluation_inputs, prompt_texts, min_chars=24)
    assert [(leak["case_id"], leak["prompt"]) for leak in leaks] == [
        ("e-001", "agent"),
        ("e-002", "judge"),
    ]
    assert all(len(leak["excerpt"]) <= 60 for leak in leaks)


# ---------------------------------------------------------------------------
# Module 2: error-analysis skill (select with -k m2)
#
# The helper and tool state invariant tests run against the committed demo
# state copied per test by the `analysis_state` fixture. They run offline and
# make no model calls.
#
# The mode under test in the demo state is `unsupported_policy_claim`, whose
# frozen judge v3 reproduces the Artifact G numbers.
# ---------------------------------------------------------------------------

DEMO_MODE = "unsupported_policy_claim"
DEMO_JUDGE = f"{DEMO_MODE}-v3"


# ----- helper / invariant tests: these PASS -------------------------------


def test_m2_splits_are_disjoint(analysis_state) -> None:
    """Splits are disjoint and no train example leaks into dev or test
    (leakage inflates every downstream number)."""
    import json

    splits = json.loads((analysis_state / "splits.json").read_text())[DEMO_MODE]
    train, dev, test = set(splits["train"]), set(splits["dev"]), set(splits["test"])
    assert train and dev and test
    assert train.isdisjoint(dev)
    assert train.isdisjoint(test)
    assert dev.isdisjoint(test)
    # The committed split matches the pinned Artifact E shape.
    assert len(train) == 20 and len(dev) == 50 and len(test) == 50


def test_m2_split_labels_produces_disjoint_stratified_splits(analysis_state) -> None:
    """`split_labels` run fresh yields disjoint splits with both classes
    present in each, and refuses a class that is too thin."""
    from analysis.helpers import GuardViolation, split_labels, tools

    assignment = split_labels(DEMO_MODE, seed=7, min_per_class=10)
    train, dev, test = (set(assignment[k]) for k in ("train", "dev", "test"))
    assert train.isdisjoint(dev) and train.isdisjoint(test) and dev.isdisjoint(test)

    labels = {r["trace_id"]: r["label"] for r in tools._load_labels(DEMO_MODE)}
    for split in (assignment["dev"], assignment["test"]):
        classes = {labels[t] for t in split if t in labels}
        assert classes == {0, 1}, "each eval split must hold both classes"

    # A production-oriented minimum of 30 is more than the demo pool supports,
    # so the guard must refuse rather than emit an unstable split.
    with pytest.raises(GuardViolation):
        split_labels(DEMO_MODE, seed=7, min_per_class=30)


def test_m2_test_split_locked_until_frozen(analysis_state) -> None:
    """`judge_alignment` on `test` raises for an unfrozen judge; `test` only
    unlocks after `freeze_judge` (freeze precedes test)."""
    from analysis.helpers import GuardViolation, judge_alignment

    # v0 exists in the demo state and is not frozen.
    with pytest.raises(GuardViolation):
        judge_alignment(f"{DEMO_MODE}-v0", "test")

    # The frozen v3 allows it.
    result = judge_alignment(DEMO_JUDGE, "test")
    assert result["n"] > 0
    assert len(result["tpr_interval"]) == 2
    assert len(result["tnr_interval"]) == 2
    assert result["tpr_interval"][0] <= result["tpr"] <= result["tpr_interval"][1]
    assert result["tnr_interval"][0] <= result["tnr"] <= result["tnr_interval"][1]


def test_m2_freeze_is_one_way(analysis_state) -> None:
    """Freezing is one-way per version: re-freezing a frozen judge raises."""
    from analysis.helpers import GuardViolation, freeze_judge, register_judge

    # A fresh draft version can be frozen exactly once.
    reg = register_judge(DEMO_MODE, "a fresh draft prompt for testing", "claude-opus-4-6")
    jid = reg["judge_id"]
    freeze_judge(jid)
    with pytest.raises(GuardViolation):
        freeze_judge(jid)


def test_m2_corrected_prevalence_needs_freeze(analysis_state) -> None:
    """`corrected_prevalence` refuses an unfrozen judge (no test TPR/TNR)."""
    from analysis.helpers import GuardViolation, corrected_prevalence

    with pytest.raises(GuardViolation):
        corrected_prevalence(f"{DEMO_MODE}-v0", "all")


def test_m2_iteration_log_has_three_plus_rows_changing(analysis_state) -> None:
    """The hill-climbing log has 3+ rows with changing TPR/TNR, plus the one
    logged label flip (Artifact F)."""
    from analysis.helpers import iteration_log

    rows = iteration_log(DEMO_MODE)
    assert len(rows) >= 3
    tprs = [r["dev_tpr"] for r in rows]
    tnrs = [r["dev_tnr"] for r in rows]
    assert len(set(tprs)) > 1, "TPR must change across iterations"
    assert len(set(tnrs)) > 1, "TNR must change across iterations"
    # Pass TPR improves across the refinement.
    assert tprs[0] < tprs[-1]
    assert sum(r["label_flips"] for r in rows) >= 1, "the demo logs one flip"


def test_m2_label_flip_is_append_only(analysis_state) -> None:
    """A flip appends a superseding record and never overwrites: the old
    record survives with a `superseded_by` pointer, and the live label is the
    flipped one."""
    import json

    from analysis.helpers import tools

    path = analysis_state / "labels" / f"{DEMO_MODE}.jsonl"
    raw = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    flipped = [r for r in raw if r.get("superseded_by")]
    assert flipped, "the demo has at least one superseded (flipped) label"
    dead = flipped[0]
    # Both the dead record and its replacement are still on disk.
    successors = [r for r in raw if r.get("label_id") == dead["superseded_by"]]
    assert successors, "the replacement record must be present too"
    # The live label for that trace is the successor's, not the dead one's.
    live = {r["trace_id"]: r["label"] for r in tools._load_labels(DEMO_MODE)}
    assert live[dead["trace_id"]] == successors[0]["label"]
    assert successors[0]["label"] != dead["label"], "a flip changes the label"


def test_m2_corrected_prevalence_reproduces_artifact_g(analysis_state) -> None:
    """`corrected_prevalence` reproduces the Artifact G point estimate from
    the committed labels and predictions: raw failure rate 0.180, test Pass
    TPR 0.947 / Fail TNR 0.833 -> corrected failure prevalence 0.163. The
    bootstrap CI is reproducible under the pinned seed."""
    from analysis.helpers import corrected_prevalence

    est = corrected_prevalence(DEMO_JUDGE, "all", seed=7)
    assert est["raw"] == pytest.approx(0.180, abs=1e-4)
    assert est["test_tpr"] == pytest.approx(0.947, abs=1e-3)
    assert est["test_tnr"] == pytest.approx(0.833, abs=1e-3)
    assert round(est["corrected"], 3) == 0.163
    assert est["backend"] == "python-bootstrap"
    # A real interval, ordered around the point estimate.
    assert est["ci_low"] < est["corrected"] < est["ci_high"]
    # Reproducible under the same seed.
    est2 = corrected_prevalence(DEMO_JUDGE, "all", seed=7)
    assert (est2["ci_low"], est2["ci_high"]) == (est["ci_low"], est["ci_high"])


def test_m2_judge_alignment_matches_artifact_f(analysis_state) -> None:
    """Dev and test alignment reproduce the Artifact F frozen-v3 numbers."""
    from analysis.helpers import judge_alignment

    dev = judge_alignment(DEMO_JUDGE, "dev")
    assert dev["tpr"] == pytest.approx(0.9487, abs=1e-3)  # 37/39 passes
    assert dev["tnr"] == pytest.approx(0.9091, abs=1e-3)  # 10/11 failures

    test = judge_alignment(DEMO_JUDGE, "test")
    assert (test["tp"], test["fn"], test["tn"], test["fp"]) == (36, 2, 10, 2)


def test_m2_run_judge_never_calls_a_model_offline(analysis_state) -> None:
    """`run_judge` uses cached predictions and, when it must classify, the
    injected stub. It must never reach a live/DocETL backend in a test: with
    no backend configured and no stub, the scaling path raises rather than
    calling out."""
    import os

    from analysis.helpers import run_judge, tools
    from analysis.helpers import scale

    # Cached dev predictions come back with no classify callable and no
    # network: the frozen judge already has them cached.
    preds = run_judge(DEMO_JUDGE, split="dev")
    assert preds and set(preds.values()) <= {0, 1}

    # The scaling boundary refuses to fall through to a live call.
    os.environ.pop("CARTWHEEL_SCALE_BACKEND", None)
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    with pytest.raises(RuntimeError):
        scale.classify_store("prompt", "gemini-flash", ["store-0000"])

    # A stub classifier is honored and cached (still no live call).
    reg_ids = ["store-0000", "store-0001"]
    got = scale.classify_store("p", "m", reg_ids, classify=lambda _p, ids: {i: 1 for i in ids})
    assert got == {"store-0000": 1, "store-0001": 1}


def test_m2_run_judge_persists_store_predictions_for_prevalence(analysis_state) -> None:
    """A store run writes the rows consumed by corrected_prevalence."""
    from analysis.helpers import run_judge, tools

    judge = tools._load_judge(DEMO_JUDGE)
    judge.pop("store_predictions", None)
    tools._state.write_json(tools._judge_path(DEMO_JUDGE), judge)

    predictions = run_judge(
        DEMO_JUDGE,
        split="store",
        classify=lambda _prompt, ids: {
            trace_id: int(index % 5 == 0)
            for index, trace_id in enumerate(ids)
        },
    )

    persisted = tools._load_judge(DEMO_JUDGE)["store_predictions"]["predictions"]
    assert len(predictions) == 500
    assert len(persisted) == 500
    assert persisted[0]["trace_id"] == "store-0000"
    assert persisted[0]["segments"] == {"role": "merchant"}
    assert {row["pred"] for row in persisted} <= {0, 1}


def test_m2_failure_report_matches_artifact_l_schema(analysis_state, tmp_path) -> None:
    """The failure report validates against the Artifact L schema, and every
    report mode traces to a human annotation with 3+ examples."""
    import json

    from analysis.helpers import failure_report

    out = tmp_path / "failure_report.json"
    report = failure_report(out)
    assert out.exists() and out.with_suffix(".md").exists()

    # Top-level shape.
    assert "modes" in report and report["modes"]

    # The originating-annotation map, to prove human origin per mode.
    patterns = json.loads((analysis_state / "patterns.json").read_text())
    created_from = {m["name"]: m.get("created_from", []) for m in patterns["modes"]}
    annotations = json.loads((analysis_state / "annotations.json").read_text())
    human_ann_ids = {a["trace_id"] for a in annotations["annotations"] if a.get("author") == "human"}

    required = {
        "name", "definition", "requirement_source", "evaluator",
        "labeled_counts", "human_judgment_counts", "prevalence", "examples",
        "evaluation_case_candidates",
    }
    for mode in report["modes"]:
        assert required <= set(mode), f"{mode.get('name')} missing keys"
        # Examples: 3 or more.
        assert len(mode["examples"]) >= 3
        # Prevalence block schema.
        assert set(mode["prevalence"]) >= {"raw", "corrected", "ci_low", "ci_high", "confidence"}
        # Evaluator schema: judge carries test TPR/TNR + hash; code does not.
        ev = mode["evaluator"]
        assert ev["type"] in ("judge", "code")
        if ev["type"] == "judge":
            assert set(ev) >= {
                "type", "judge_id", "prompt_hash", "test_tpr", "test_tnr",
                "test_tpr_interval", "test_tnr_interval", "test_class_counts",
                "decision",
            }
        # Human origin: the mode traces to human annotations, 3+ of them.
        origins = created_from.get(mode["name"], [])
        assert len(origins) >= 1, f"{mode['name']} has no originating annotation"
        assert set(origins) <= human_ann_ids, "origins must be human annotations"

    # The judge-backed lead mode carries the corrected Artifact G prevalence.
    lead = next(mode for mode in report["modes"] if mode["name"] == DEMO_MODE)
    assert lead["name"] == DEMO_MODE
    assert round(lead["prevalence"]["corrected"], 3) == 0.163
    # The demo judge gets 36/38 passes and 10/12 failures right.
    evaluator = lead["evaluator"]
    assert evaluator["test_tpr_interval"] == [0.8271, 0.9854]
    assert evaluator["test_tnr_interval"] == [0.552, 0.953]

def test_m2_file_selection_is_deterministic_and_resumable(
    analysis_state, tmp_path, monkeypatch
) -> None:
    """Select a repeatable batch, then resume after changing directories."""
    import json

    from analysis.helpers import select_traces, next_to_label

    # A tiny synthetic export with feature vectors, written to a temp file.
    traces = [
        {"id": f"x{i}", "features": {"turn_count": i % 5, "tool_call_count": i % 3,
                                     "distinct_tools": i % 4, "has_retrieval": i % 2,
                                     "tokens": 100 * (i % 7)}}
        for i in range(40)
    ]
    monkeypatch.chdir(tmp_path)
    export = Path("export.json")
    export.write_text(json.dumps({"traces": traces}))

    picks_a = select_traces(export, k=24, strategy="diversity")
    picks_b = select_traces(export, k=24, strategy="diversity")
    assert [p["trace_id"] for p in picks_a] == [p["trace_id"] for p in picks_b]
    assert all(p.get("reason") for p in picks_a)
    ids = [p["trace_id"] for p in picks_a]
    assert len(ids) == len(set(ids)) <= 24
    # The manifest is persisted to the (copied) state dir.
    assert (analysis_state / "samples.json").exists()
    assert (analysis_state / "sample_manifest.json").exists()
    saved = json.loads((analysis_state / "samples.json").read_text())
    assert isinstance(saved, list) and saved
    assert set(saved[0]) >= {"trace_id", "reason", "trace", "features", "meta"}

    # Resume from the full export, even after changing directories.
    monkeypatch.chdir(analysis_state)
    candidates = next_to_label("resumed", k=len(traces), strategy="random")
    assert {c["trace_id"] for c in candidates} == {t["id"] for t in traces}


def test_m2_module1_export_is_normalized_for_review(analysis_state, tmp_path) -> None:
    """A raw Module 1 Langfuse export becomes a renderable review record."""
    import json

    from analysis.helpers import select_traces

    export = tmp_path / "support_traces.json"
    export.write_text(
        json.dumps(
            {
                "traces": [
                    {
                        "id": "abc123",
                        "input": "Can I return order 4127?",
                        "output": "I will check the return policy.",
                        "metadata": {
                            "cartwheel.scenario_id": "support-0001",
                            "cartwheel.user_role": "shopper",
                        },
                        "observations": [
                            {
                                "name": "tool.search_help_center",
                                "type": "TOOL",
                                "input": {"query": "return policy"},
                                "output": {"documents": ["returns-001"]},
                            }
                        ],
                    }
                ]
            }
        )
    )
    samples = select_traces(export, k=1, strategy="random")
    assert samples[0]["trace_id"] == "abc123"
    assert samples[0]["meta"]["scenario_id"] == "support-0001"
    roles = [message["role"] for message in samples[0]["trace"]]
    assert roles == ["user", "tool_call", "tool_result", "assistant"]


def test_m2_langfuse_identifier_is_preserved_for_score_writes() -> None:
    """A live Langfuse id must not be hashed into a different trace id."""
    from analysis.helpers.langfuse_io import logical_to_langfuse_id

    trace_id = "0123456789abcdef0123456789abcdef"
    assert logical_to_langfuse_id(trace_id) == trace_id


def test_m2_next_to_label_enriches_from_confirmed(analysis_state, tmp_path) -> None:
    """`next_to_label` in `enrich` mode returns unlabeled candidates ranked by
    similarity to confirmed failures, each with a signal, no model call."""
    import json

    from analysis.helpers import next_to_label

    traces = [
        {"id": "seed_fail", "text": "invented store credit fallback not in any policy doc"},
        {"id": "near", "text": "store credit offered though no policy doc mentions store credit"},
        {"id": "far", "text": "where is my package tracking number please"},
    ]
    export = tmp_path / "e.json"
    export.write_text(json.dumps({"traces": traces}))
    # Point next_to_label at this export and seed a confirmed failure by
    # writing a label for seed_fail into the copied state.
    from analysis.helpers import _state
    _state.append_jsonl(
        _state.state_path("labels", "adhoc_mode.jsonl"),
        {"trace_id": "seed_fail", "label": 1, "source": "human", "ts": "t", "label_id": "seed_fail#0"},
    )
    cands = next_to_label("adhoc_mode", k=2, strategy="enrich", trace_source=str(export))
    ids = [c["trace_id"] for c in cands]
    assert "seed_fail" not in ids, "already-labeled traces are excluded"
    assert ids and ids[0] == "near", "the semantic neighbor ranks first"
    assert all(c.get("signal") for c in cands)


def test_m2_next_to_label_resumes_live_source(analysis_state, monkeypatch) -> None:
    from analysis.helpers import langfuse_io, select_traces, next_to_label
    from analysis.helpers.normalization import normalize_traces

    traces = normalize_traces([{"id": "live", "text": "hello"}])
    monkeypatch.setattr(langfuse_io, "is_configured", lambda: True)
    monkeypatch.setattr(langfuse_io, "fetch_traces", lambda: traces)
    select_traces("langfuse", k=1)
    assert next_to_label("resumed", k=1, strategy="random") == [
        {"trace_id": "live", "signal": "random"}
    ]


@pytest.mark.parametrize("configured, error", [(False, RuntimeError), (True, ValueError)])
def test_m2_unavailable_live_source_raises(
    analysis_state, monkeypatch, configured, error
) -> None:
    """Missing setup or an empty live dataset should give a useful error."""
    from analysis.helpers import langfuse_io, select_traces

    monkeypatch.setattr(langfuse_io, "is_configured", lambda: configured)
    monkeypatch.setattr(langfuse_io, "fetch_traces", lambda: [])
    with pytest.raises(error, match="Langfuse"):
        select_traces("langfuse", k=1)


# --------------------------------------------------------------------------
# Grading a student's OWN submission (mode-agnostic; opt-in).
#
# The 14 tests above verify the skill's machinery against the pinned DEMO
# state (mode `unsupported_policy_claim`, prevalence 0.163). They cannot also
# grade a real submission, whose modes and numbers differ per student and have
# no fixed answer. These checks grade the STRUCTURE of a submission instead:
# point CARTWHEEL_SUBMISSION_STATE at a student's committed `analysis/state/`
# and they run mode-agnostically over THEIR splits and judges. They SKIP when
# the env var is unset, so the default run (starter repo, CI) stays green.
# --------------------------------------------------------------------------

def _submission_state():
    import os
    from pathlib import Path

    raw = os.environ.get("CARTWHEEL_SUBMISSION_STATE")
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


_grades_submission = pytest.mark.skipif(
    _submission_state() is None,
    reason="set CARTWHEEL_SUBMISSION_STATE=<path to a student's analysis/state> to grade it",
)


@_grades_submission
def test_m2_submission_splits_are_disjoint() -> None:
    """Every mode the student split has pairwise-disjoint train/dev/test (no
    trace leaks across splits, so no metric is inflated)."""
    import json

    state = _submission_state()
    splits_path = state / "splits.json"
    assert splits_path.exists(), "submission has no splits.json"
    splits = json.loads(splits_path.read_text())
    assert splits, "submission split no modes"
    for mode, sp in splits.items():
        train, dev, test = set(sp["train"]), set(sp["dev"]), set(sp["test"])
        assert train.isdisjoint(dev), f"{mode}: train and dev overlap"
        assert train.isdisjoint(test), f"{mode}: train and test overlap"
        assert dev.isdisjoint(test), f"{mode}: dev and test overlap"


@_grades_submission
def test_m2_submission_has_a_frozen_judge_per_split_mode() -> None:
    """Every mode the student built splits for has at least one FROZEN judge
    (you must freeze before you report; an unfrozen judge means the test split
    was never locked)."""
    import json

    state = _submission_state()
    splits = json.loads((state / "splits.json").read_text())
    judges_dir = state / "judges"
    assert judges_dir.exists(), "submission has no judges/ directory"
    frozen_modes = set()
    for jf in judges_dir.glob("*.json"):
        if jf.name.startswith("_history"):
            continue
        j = json.loads(jf.read_text())
        if j.get("status") == "frozen" and j.get("frozen_at"):
            frozen_modes.add(j.get("mode"))
    for mode in splits:
        assert mode in frozen_modes, f"{mode}: no frozen judge (freeze before reporting)"


@hw(1, "find_order")
@pytest.mark.parametrize("ctx,scope", [(SHOPPER_1, "shopper"), (AuthContext(user_id=9002, role="merchant", store_id=2), "merchant"), (SUPPORT, "support")])
def test_hw1_find_order_roles_and_old_matches(order_search_cases, ctx, scope):
    title, expected = order_search_cases
    result = tools.find_order(ctx, title)
    assert result["ok"] is True
    with db.connection() as conn:
        wanted = [db.get_order(conn, order_id).to_public_dict() for order_id in expected[scope][:5]]
    assert result["orders"] == wanted
    assert tools.find_order(ctx, "zzzznonexistent9999") == {"ok": True, "orders": []}
