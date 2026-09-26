"""Convert Cartwheel evaluation cases into generated Harbor tasks."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from replay.rollout import EVAL_CASES_PATH, load_frozen_judge

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".harbor" / "tasks"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SOURCE_PACKAGES = ("agent", "observability", "seed", "replay", "harbor_adapter")
STUB_PACKAGES = ("scenarios", "server", "analysis", "optimize")

MODEL_IDS = {
    "claude-opus-4-6": "anthropic/claude-opus-4-6",
    "glm-5.2": "together_ai/zai-org/GLM-5.2",
    "gemini-flash": "gemini/gemini-flash-latest",
    "gemini-flash-lite": "gemini/gemini-flash-lite-latest",
    "gpt-nano": "gpt-5.5-nano",
}


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _judge_model(model: str) -> str:
    if model in MODEL_IDS:
        return MODEL_IDS[model]
    return model


def _provider_key(model: str) -> str | None:
    normalized = _judge_model(model)
    if (
        model.startswith("gpt-")
        or re.match(r"^o\d", model)
        or normalized.startswith("openai/")
    ):
        return "OPENAI_API_KEY"
    if model.startswith("claude-"):
        return "ANTHROPIC_API_KEY"
    if model.startswith("gemini-"):
        return "GEMINI_API_KEY"
    provider = normalized.split("/", 1)[0]
    known = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "together_ai": "TOGETHER_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }.get(provider)
    if known:
        return known
    if "/" in normalized and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", provider):
        return f"{provider.upper().replace('-', '_')}_API_KEY"
    return None


def load_export_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Load cases without requiring their baseline classification yet."""
    path = path or EVAL_CASES_PATH
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return cases


def _validate_case(
    case: dict[str, Any], seen: set[str], *, baseline: bool = False
) -> None:
    case_id = str(case.get("id", ""))
    if not SAFE_NAME.fullmatch(case_id):
        raise ValueError(f"case id must be safe for a directory name: {case_id!r}")
    if case_id in seen:
        raise ValueError(f"duplicate case id: {case_id}")
    seen.add(case_id)
    kind = case.get("kind")
    if baseline:
        if kind is not None:
            raise ValueError(
                f"{case_id}: remove kind before the baseline run"
            )
        if "baseline_pass_rate" in case:
            raise ValueError(
                f"{case_id}: remove baseline_pass_rate before the baseline run"
            )
    else:
        if kind not in {"regression", "capability"}:
            raise ValueError(f"{case_id}: kind must be regression or capability")
        if kind == "capability" and "baseline_pass_rate" not in case:
            raise ValueError(f"{case_id}: capability cases need baseline_pass_rate")
        if kind == "capability":
            rate = case["baseline_pass_rate"]
            if rate not in {0.0, 0.2, 0.4, 0.6, 0.8}:
                raise ValueError(
                    f"{case_id}: baseline_pass_rate must come from five runs"
                )
    mode = str(case.get("mode", ""))
    if not SAFE_NAME.fullmatch(mode):
        raise ValueError(f"{case_id}: mode must be safe for a file name")
    case_input = case.get("input", {})
    for key in ("role", "user_id", "message"):
        if key not in case_input:
            raise ValueError(f"{case_id}: input is missing {key}")
    initial_state = case.get("initial_state", {})
    if initial_state.get("world") != "reseed":
        raise ValueError(f"{case_id}: only initial_state.world='reseed' is supported")
    if initial_state.get("fixture") is not None:
        raise ValueError(f"{case_id}: named fixtures are not supported yet")
    expected = case.get("expected", {})
    if not expected.get("assertions"):
        raise ValueError(f"{case_id}: expected.assertions cannot be empty")
    if not expected.get("checks") and not expected.get("judges"):
        raise ValueError(f"{case_id}: add at least one code check or accepted judge")


def _copy_python_package(source: Path, destination: Path) -> None:
    for path in source.rglob("*.py"):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _copy_runtime(task_dir: Path) -> None:
    app = task_dir / "environment" / "cartwheel"
    app.mkdir(parents=True)
    for name in SOURCE_PACKAGES:
        _copy_python_package(REPO_ROOT / name, app / name)
    for name in STUB_PACKAGES:
        package = app / name
        package.mkdir()
        (package / "__init__.py").write_text("")
    for name in ("README.md", "facts.yaml", "pyproject.toml", "uv.lock"):
        shutil.copy2(REPO_ROOT / name, app / name)


def _task_toml(case: dict[str, Any], judges: list[dict[str, Any]]) -> str:
    lines = [
        'schema_version = "1.4"',
        "",
        "[task]",
        f'name = "cartwheel/evals__{case["id"]}"',
        'version = "1.0.0"',
        f"description = {_toml_string(case['expected']['assertions'][0])}",
        'authors = [{ name = "Cartwheel course staff" }]',
        'keywords = ["cartwheel", "agent-evals", "rewardkit"]',
        "",
        "[metadata]",
        f"case_id = {_toml_string(case['id'])}",
        f"kind = {_toml_string(case.get('kind', 'unclassified'))}",
        f"mode = {_toml_string(case['mode'])}",
        "",
        "[verifier]",
        "timeout_sec = 300.0",
    ]
    keys = sorted({key for judge in judges if (key := _provider_key(judge["model"]))})
    if keys:
        lines.extend(["", "[verifier.env]"])
        lines.extend(f'{key} = "${{{key}}}"' for key in keys)
    lines.extend(
        [
            "",
            "[agent]",
            "timeout_sec = 600.0",
            "",
            "[environment]",
            'network_mode = "public"',
            "build_timeout_sec = 900.0",
            "cpus = 2",
            "memory_mb = 4096",
            "storage_mb = 8192",
            "",
            "[[artifacts]]",
            'source = "/app/cartwheel-result.json"',
        ]
    )
    return "\n".join(lines) + "\n"


def _instruction(case: dict[str, Any]) -> str:
    followups = case["input"].get("followups", [])
    lines = [
        f"Run Cartwheel evaluation case `{case['id']}`.",
        "",
        f"Opening request: {case['input']['message']}",
    ]
    if followups:
        lines.extend(["", "Scripted followups:"])
        lines.extend(f"{index}. {message}" for index, message in enumerate(followups, 1))
    return "\n".join(lines) + "\n"


def _checks_py() -> str:
    return '''from __future__ import annotations

import json
import sys
from pathlib import Path

from rewardkit import criterion

sys.path.insert(0, "/app")
from replay.rollout import apply_checks


@criterion
def cartwheel_code_checks(workspace: Path) -> bool:
    case = json.loads((workspace / "case.json").read_text())
    evidence = json.loads((workspace / "cartwheel-result.json").read_text())
    outcome = apply_checks(
        case,
        evidence["transcript"],
        workspace / "data" / "cartwheel.db",
    )
    return bool(outcome["passed"])
'''


def _judge_py(mode: str, expected: str, judge: dict[str, Any]) -> str:
    """Run one frozen judge through the DocETL contract used in HW5."""
    del mode
    template = '''from __future__ import annotations

import json
import tempfile
from pathlib import Path

from docetl.api import Dataset, MapOp, Pipeline, PipelineOutput, PipelineStep
from rewardkit import criterion

from replay.rollout import judge_trace_text

PROMPT = __PROMPT__
MODEL = __MODEL__
EXPECTED = __EXPECTED__


def _decode(row: dict) -> str:
    critique = row.get("critique")
    if not isinstance(critique, str) or not critique.strip():
        raise ValueError("judge result needs a critique")
    raw = str(row.get("result", "")).strip().lower().rstrip(".")
    if raw in {"pass", "passed"}:
        return "pass"
    if raw in {"fail", "failed"}:
        return "fail"
    return "fail"


@criterion
def cartwheel_judge(workspace: Path) -> bool:
    evidence = json.loads((workspace / "cartwheel-result.json").read_text())
    content = judge_trace_text(evidence["transcript"])
    with tempfile.TemporaryDirectory(prefix="cartwheel-judge-") as directory:
        root = Path(directory)
        input_path = root / "input.json"
        output_path = root / "output.json"
        input_path.write_text(
            json.dumps([{"trace_id": "current", "content": content}])
        )
        operation = MapOp(
            name="classify_failure_mode",
            type="map",
            model=MODEL,
            prompt=(
                PROMPT
                + "\\n\\n--- Trace to evaluate ---\\n"
                + "{{ input.content }}\\n\\n"
                + "First write a critique of the trace against the criterion. "
                + "Use specific evidence from the provided trace. Then return result "
                + "as exactly Pass when the named failure is absent, or Fail when present."
            ),
            output={"schema": {"critique": "string", "result": "string"}},
        )
        pipeline = Pipeline(
            name="cartwheel_judge",
            datasets={"traces": Dataset(type="file", path=str(input_path))},
            operations=[operation],
            steps=[
                PipelineStep(
                    name="classify",
                    input="traces",
                    operations=["classify_failure_mode"],
                )
            ],
            output=PipelineOutput(
                type="file",
                path=str(output_path),
                intermediate_dir=str(root),
            ),
        )
        pipeline.run()
        rows = json.loads(output_path.read_text())
    if len(rows) != 1:
        raise ValueError("judge returned an unexpected number of results")
    return _decode(rows[0]) == EXPECTED
'''
    return (
        template.replace("__PROMPT__", repr(judge["prompt_text"]))
        .replace("__MODEL__", repr(_judge_model(judge["model"])))
        .replace("__EXPECTED__", repr(expected))
    )


def _reward_toml(judge_names: list[str]) -> str:
    weights = {"checks": "1.0"}
    weights.update({_toml_string(name): "1.0" for name in judge_names})
    inline = ", ".join(f"{name} = {weight}" for name, weight in weights.items())
    return "\n".join(
        [
            "[scoring.checks]",
            'aggregation = "all-pass"',
            "",
            "[[reward]]",
            'name = "reward"',
            'aggregation = "all-pass"',
            f"weights = {{ {inline} }}",
            "",
        ]
    )


def _dockerfile() -> str:
    return '''FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_LINK_MODE=copy
ENV OPENAI_AGENTS_DISABLE_TRACING=1

WORKDIR /app
COPY cartwheel/pyproject.toml cartwheel/uv.lock cartwheel/README.md /app/
RUN uv sync --frozen --no-dev --no-install-project
COPY cartwheel/ /app/
RUN uv sync --frozen --no-dev
'''


def _write_task(root: Path, case: dict[str, Any]) -> None:
    task_dir = root / case["id"]
    environment = task_dir / "environment"
    tests = task_dir / "tests"
    environment.mkdir(parents=True)
    tests.mkdir()

    judges: list[dict[str, Any]] = []
    judge_names: list[str] = []
    for mode, expected in case["expected"].get("judges", {}).items():
        if expected not in {"pass", "fail"}:
            raise ValueError(f"{case['id']}: judge expectation must be pass or fail")
        judge = load_frozen_judge(mode)
        if not judge.get("prompt_text") or not judge.get("model"):
            raise ValueError(f"{case['id']}: frozen judge {mode!r} is incomplete")
        judges.append(judge)
        filename = f"judge_{mode}"
        judge_names.append(filename)
        (tests / f"{filename}.py").write_text(_judge_py(mode, expected, judge))

    (task_dir / "task.toml").write_text(_task_toml(case, judges))
    (task_dir / "instruction.md").write_text(_instruction(case))
    (environment / "Dockerfile").write_text(_dockerfile())
    (tests / "checks.py").write_text(_checks_py())
    (tests / "reward.toml").write_text(_reward_toml(judge_names))
    test_sh = tests / "test.sh"
    test_sh.write_text(
        "#!/bin/sh\nset -eu\n"
        "uvx --from 'harbor-rewardkit==0.2.1' --with 'docetl==0.3.0' "
        "rewardkit /tests\n"
    )
    test_sh.chmod(0o755)

    _copy_runtime(task_dir)
    (environment / "cartwheel" / "case.json").write_text(
        json.dumps(case, indent=2, ensure_ascii=False) + "\n"
    )


def export_tasks(
    cases_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT,
    *,
    baseline: bool = False,
    case_ids: set[str] | None = None,
    require_suite: bool = True,
) -> list[Path]:
    """Export every Cartwheel case and replace the generated task directory."""
    cases = load_export_cases(cases_path)
    if case_ids is not None:
        cases = [case for case in cases if case.get("id") in case_ids]
        missing = case_ids - {str(case.get("id")) for case in cases}
        if missing:
            raise ValueError(f"unknown case id(s): {', '.join(sorted(missing))}")
    if not cases:
        raise ValueError("the evaluation case set is empty")
    seen: set[str] = set()
    for case in cases:
        _validate_case(case, seen, baseline=baseline)
    if not baseline and require_suite:
        if len(cases) < 10:
            raise ValueError("the final evaluation set needs at least 10 cases")
        modes = {case["mode"] for case in cases}
        if len(modes) < 2:
            raise ValueError(
                "the final evaluation set must cover at least two failure modes"
            )
        kinds = {case["kind"] for case in cases}
        if kinds != {"regression", "capability"}:
            raise ValueError(
                "the final evaluation set needs a regression and a capability case"
            )

    output_dir = output_dir.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir.parent) as temp:
        generated = Path(temp) / "tasks"
        generated.mkdir()
        for case in cases:
            _write_task(generated, case)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        generated.replace(output_dir)
    return [output_dir / case["id"] for case in cases]
