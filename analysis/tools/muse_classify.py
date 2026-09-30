"""Judge classifier that talks to the Muse endpoint directly, bypassing DocETL.

DocETL enforces structured output with a named-function ``tool_choice``. The endpoint
here accepts only ``tool_choice: "auto"`` and rejects the call:

    OpenAIException - only "auto" is supported for tool_choice

So the schema is requested in the prompt instead and the reply is parsed. The rest of
the pipeline is untouched: ``run_judge`` accepts a ``classify`` callable in place of
the DocETL backend, and this returns the same ``JudgeBatch`` of binary predictions plus
critiques, so caching, resume, alignment and disagreement review all work unchanged.

Substitution number four, after Langfuse, Raindrop and gpt-4o-mini. Recorded in
analysis/report/workshop_notes.md.

Label convention: the helpers expect **1 for Pass, 0 for Fail**.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from analysis.helpers.scale import JudgeBatch, load_store_traces

TIMEOUT = 300
WORKERS = 4          # the endpoint answers in ~5s; four at a time keeps a batch brisk
# These are reasoning models: they spend output tokens thinking before they answer, and
# return empty content rather than a truncated one when the budget runs out. Homework 3
# hit the same wall. Input is only ~4.5k tokens at worst, so the budget here is all
# headroom for reasoning.
MAX_TOKENS = 16000
RETRY_TOKENS = 32000


def _endpoint() -> tuple[str, str]:
    base = (os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE") or "")
    key = os.environ.get("OPENAI_API_KEY", "")
    if not base or not key:
        raise RuntimeError("OPENAI_BASE_URL and OPENAI_API_KEY must be set")
    return base.rstrip("/"), key


def _trace_text(trace: dict) -> str:
    """Render one trace for the judge: the conversation and the tool evidence."""
    lines = []
    for m in trace.get("trace") or []:
        role = m.get("role")
        if role == "tool_call":
            lines.append(f"[tool call] {m.get('name')} {m.get('arguments') or ''}")
        elif role == "tool_result":
            lines.append(f"[tool result] {m.get('name')}: {m.get('text') or ''}")
        else:
            lines.append(f"[{role}] {m.get('text') or ''}")
    return "\n".join(lines)


def _parse(content: str) -> tuple[int, str]:
    """Return (label, critique). 1 = Pass, 0 = Fail."""
    obj = None
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            obj = None
    if isinstance(obj, dict) and obj.get("result"):
        verdict = str(obj["result"]).strip().lower()
        critique = str(obj.get("critique") or "").strip()
    else:
        # The model answered in prose. Fall back to the verdict word, and keep the whole
        # reply as the critique so a human reviewing disagreements still sees reasoning.
        verdict = ("fail" if re.search(r"\bfail\b", content, re.I)
                   else "pass" if re.search(r"\bpass\b", content, re.I) else "")
        critique = " ".join(content.split())
    if verdict.startswith("pass"):
        return 1, critique or "(no critique returned)"
    if verdict.startswith("fail"):
        return 0, critique or "(no critique returned)"
    raise ValueError(f"no verdict in judge reply: {content[:200]!r}")


def make_classifier(model: str):
    """Build the ``classify`` callable ``run_judge`` expects.

    The judge is registered as ``openai/<model>`` because that is how LiteLLM routes to
    an OpenAI-compatible endpoint. LiteLLM strips the prefix before the call; talking to
    the endpoint directly means stripping it here, or the server is asked for a model it
    has never heard of and answers 404.
    """
    base, key = _endpoint()
    model = model.split("/", 1)[1] if model.startswith("openai/") else model

    def ask(prompt_text: str, trace: dict) -> tuple[str, int, str]:
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": prompt_text},
                {"role": "user", "content":
                    "Evaluate this trace and reply with the JSON object described above.\n\n"
                    "TRACE\n" + _trace_text(trace)},
            ],
            "temperature": 0,
            "_trace_id": trace["trace_id"],
        }).encode()
        return _post(base, key, body)

    def _post(base, key, body, budget=MAX_TOKENS, retried=False):
        payload = json.loads(body)
        payload["max_tokens"] = budget
        # Carried alongside the request so the parallel map can match replies to traces;
        # the server would reject an unknown field, so it never goes over the wire.
        trace_id = payload.pop("_trace_id")
        req = urllib.request.Request(
            f"{base}/chat/completions", data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read())
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        if not content.strip():
            if not retried:
                # Ran out of budget mid-thought. One more attempt with more headroom.
                return _post(base, key, body, RETRY_TOKENS, retried=True)
            raise ValueError(
                f"judge returned empty content at {budget} max_tokens "
                f"(finish_reason={choice.get('finish_reason')}). The model is spending "
                "its whole budget on reasoning; raise RETRY_TOKENS or shorten the prompt.")
        label, critique = _parse(content)
        return trace_id, label, critique

    def classify(prompt_text: str, trace_ids: list[str]) -> JudgeBatch:
        store = {t["trace_id"]: t for t in load_store_traces()}
        missing = [t for t in trace_ids if t not in store]
        if missing:
            raise ValueError(f"traces not in the judge trace source: {missing[:3]}")
        batch = JudgeBatch()
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for tid, label, critique in pool.map(
                    lambda t: ask(prompt_text, store[t]), trace_ids):
                batch[tid] = label
                batch.critiques[tid] = critique
        return batch

    return classify
