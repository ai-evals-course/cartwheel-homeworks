"""Lossless source records plus a readable, provenance-linked projection."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analysis.helpers._state import read_json, write_json
from analysis.helpers.normalization import _metadata


def now():
    return datetime.now(timezone.utc).isoformat()


def messages(value):
    if isinstance(value, dict):
        return value.get("messages", [])
    return value if isinstance(value, list) else []


def text(value):
    if isinstance(value, str):
        return value
    return "\n".join(str(p.get("content", "")) for m in messages(value)
                     for p in m.get("parts", []) if p.get("type") == "text")


DIMENSION_FIELDS = {
    "authenticated role": "role", "intent": "intent", "record involved": "record_involved",
    "order status": "order_status", "age since placement": "order_age_days_range",
    "applicable policy": "applicable_policy", "tools needed": "tools_needed",
    "difficulty": "difficulty", "user style": "user_style",
}


def group_sessions(traces, scenarios=()):
    scenario_tuples = {s["id"]: s.get("tuple", {}) for s in scenarios}
    groups = {}
    for raw in traces:
        meta = _metadata(raw)
        values = scenario_tuples.get(meta.get("cartwheel.scenario_id"), {})
        dimensions = {name: str(values[key]) for name, key in DIMENSION_FIELDS.items()
                      if values.get(key) is not None}
        if meta.get("cartwheel.user_role"):
            dimensions["authenticated role"] = meta["cartwheel.user_role"]
        sid = meta.get("cartwheel.session_id") or raw.get("sessionId") or "trace:" + raw["id"]
        group = groups.setdefault(sid, {"id": sid, "traces": []})
        group["traces"].append({
            "id": raw["id"], "timestamp": raw.get("timestamp") or "",
            "scenario": meta.get("cartwheel.scenario_id"),
            "role": meta.get("cartwheel.user_role"), "user_id": meta.get("cartwheel.user_id"),
            "prompt_version": meta.get("cartwheel.prompt_version"),
            "dimensions": dimensions,
            "preview": text(raw.get("input"))[:220],
        })
    for group in groups.values():
        group["traces"].sort(key=lambda t: (t["timestamp"], t["id"]))
    return sorted(groups.values(), key=lambda g: (g["traces"][0]["timestamp"], g["id"]))


def build_turn(raw):
    """Never use accumulated model inputs as new conversation messages.

    Tool observations have typed results; generation inputs often contain their
    Python-repr equivalents. Keep the typed values, and keep every raw record.
    """
    blocks, warnings, calls = [], [], []
    observations = sorted(raw.get("observations") or [], key=lambda o: (o.get("startTime") or "", o["id"]))

    def add_parts(value, obs_id, field, default_role):
        for mi, message in enumerate(messages(value)):
            for pi, part in enumerate(message.get("parts") or []):
                kind = part.get("type")
                if kind == "tool_call":
                    calls.append({**part, "observation_id": obs_id, "matched": False})
                elif kind in {"text", "reasoning", "thinking"}:
                    content = part.get("content", "")
                    blocks.append({"id": f"{obs_id}:{field}:{mi}:{pi}", "observation_id": obs_id,
                                   "field": f"{field}.{mi}.parts.{pi}.content",
                                   "role": "thinking" if kind != "text" else message.get("role", default_role),
                                   "text": str(content)})

    add_parts(raw.get("input"), "trace", "input", "user")
    generated = False
    for obs in observations:
        if obs.get("type") == "GENERATION":
            before = len(blocks)
            add_parts(obs.get("output"), obs["id"], "output", "assistant")
            generated = generated or len(blocks) > before
        elif obs.get("type") == "TOOL":
            candidates = [c for c in calls if not c["matched"] and c.get("name") == obs.get("name")
                          and c.get("arguments") == obs.get("input")]
            attrs = _metadata(obs)
            explicit_id = attrs.get("gen_ai.tool.call.id") or attrs.get("tool_call_id")
            if explicit_id:
                candidates = [c for c in candidates if c.get("id") == explicit_id]
            match = "call_id" if explicit_id and len(candidates) == 1 else "name_and_arguments" if len(candidates) == 1 else "ambiguous" if candidates else "unmatched"
            call = candidates[0] if len(candidates) == 1 else None
            if call:
                call["matched"] = True
            blocks.append({"id": obs["id"], "role": "tool", "observation_id": obs["id"],
                           "name": obs.get("name"), "arguments": obs.get("input"),
                           "result": obs.get("output"), "field": "output",
                           "call_id": call.get("id") if call else explicit_id, "match": match})
    for call in calls:
        if not call["matched"]:
            warnings.append(f"Tool call {call.get('id', call.get('name'))} has no uniquely matched observation; inspect raw evidence.")
    if not generated:
        add_parts(raw.get("output"), "trace", "output", "assistant")
    if not text(raw.get("input")):
        warnings.append("User input was not captured in the expected message format.")
    if not generated and not text(raw.get("output")):
        warnings.append("Assistant output was not captured in the expected message format.")
    return {"id": raw["id"], "timestamp": raw.get("timestamp"), "meta": _metadata(raw),
            "blocks": blocks, "warnings": warnings, "raw": raw,
            "models": sorted({o["model"] for o in observations if o.get("model")})}


def sync_label(trace_id, mode, value, comment):
    """Synchronous, idempotent write plus readback using the existing client.

    Retrying a saved judgment updates the same score, including after a timeout.
    Never treat an SDK background enqueue as a confirmed canonical write.
    """
    from analysis.helpers.langfuse_io import _client, logical_to_langfuse_id
    from langfuse.api.resources.score.types.create_score_request import CreateScoreRequest
    client = _client()
    score_id = hashlib.sha256(f"cartwheel-review:{trace_id}:{mode}".encode()).hexdigest()
    lf_id = logical_to_langfuse_id(trace_id, client)
    client.api.score.create(request=CreateScoreRequest(
        id=score_id, traceId=lf_id, name=mode, value=value,
        dataType="NUMERIC", comment=comment,
    ))
    saved = client.api.score_v_2.get_by_id(score_id)
    if saved.value != value or saved.trace_id != lf_id:
        raise RuntimeError("Score readback did not match the saved judgment")


class ReviewStore:
    """Single-user state, atomic snapshots and revision checks across tabs."""
    def __init__(self, root: Path, trace_ids: set[str], sync=sync_label):
        self.root, self.trace_ids, self.sync = root, trace_ids, sync
        self.path = root / "review_app.json"
        self.lock = threading.RLock()
        with self.lock:
            state = read_json(self.path, None)
            if state is not None and self._mark_reviewed(state, [a["trace_id"] for a in state["annotations"]]):
                self._persist(state)

    def _mark_reviewed(self, state, trace_ids):
        changed = False
        for trace_id in trace_ids:
            if (trace_id in self.trace_ids
                    and state["reviews"].get(trace_id, {}).get("status", "unreviewed") == "unreviewed"):
                state["reviews"][trace_id] = {"status": "reviewed", "updated_at": now()}
                changed = True
        return changed

    def read(self):
        with self.lock:
            state = read_json(self.path, None)
            if state is None:
                state = {"revision": 0, "annotations": [], "reviews": {}, "labels": {},
                         "modes": [], "decisions": {}}
            # External helper output remains separately owned and read-only here.
            suggestions = read_json(self.root / "suggestions.json", [])
            state["suggestions"] = suggestions if isinstance(suggestions, list) else suggestions.get("suggestions", [])
            patterns = read_json(self.root / "patterns.json", {"modes": []})
            if isinstance(patterns, dict):
                existing = patterns.get("modes", [])
                if not isinstance(existing, list):
                    existing = []
                if "modes" not in patterns:
                    existing = [{"id": k, **v} for k, v in patterns.items() if isinstance(v, dict)]
                ids = {m["id"] for m in state["modes"]}
                for mode in existing:
                    mid = mode.get("id") or mode.get("name")
                    if mid and mid not in ids:
                        state["modes"].append({**mode, "id": mid, "final": False})
            return state

    def _persist(self, state):
        state["revision"] += 1
        write_json(self.path, {k: v for k, v in state.items() if k != "suggestions"})

    def _link_suggestion_note(self, state, suggestion):
        """Link an existing accepted note to its proposed mode without labeling."""
        sid = suggestion["id"]
        if state["decisions"].get(sid, {}).get("decision") != "accept":
            return False
        annotation_id = "accepted:" + sid
        note = next((a for a in state["annotations"] if a["id"] == annotation_id
                     and a.get("source") == "human_accepted_ai"
                     and a["trace_id"] == suggestion.get("trace_id")), None)
        mode = next((m for m in state["modes"] if m["id"] == suggestion.get("mode")), None)
        if note is None or mode is None or annotation_id in mode.get("annotation_ids", []):
            return False
        mode.setdefault("annotation_ids", []).append(annotation_id)
        return True

    def apply(self, event):
        with self.lock:
            state = self.read()
            if "revision" in event and event["revision"] != state["revision"]:
                raise ValueError("Review state changed in another tab; reload before saving. Your draft is retained.")
            action, tid = event.get("action"), event.get("trace_id")
            if action in {"note", "delete_note", "review", "label"} and tid not in self.trace_ids:
                raise ValueError("Unknown trace")
            if action == "note":
                note = str(event.get("note", "")).strip()
                if not note or len(note) > 20000:
                    raise ValueError("Enter a note of 1–20000 characters")
                anchor = event.get("anchor", {})
                if not isinstance(anchor, dict):
                    raise ValueError("Invalid evidence anchor")
                aid = str(event.get("id") or uuid.uuid4())
                prior = next((a for a in state["annotations"] if a["id"] == aid), None)
                if prior and prior["trace_id"] != tid:
                    raise ValueError("Annotation belongs to another trace")
                annotation = {"id": aid, "trace_id": tid, "note": note,
                              "anchor": anchor, "updated_at": now(), "source": "human"}
                state["annotations"] = [a for a in state["annotations"] if a["id"] != aid] + [annotation]
                self._mark_reviewed(state, [tid])
            elif action == "delete_note":
                aid = event.get("id")
                note = next((a for a in state["annotations"] if a["id"] == aid and a["trace_id"] == tid), None)
                if note is None:
                    raise ValueError("Comment not found for this trace")
                if any(aid in mode.get("annotation_ids", []) for mode in state["modes"]):
                    raise ValueError("This comment supports a failure mode and cannot be deleted while it is linked")
                state["annotations"] = [a for a in state["annotations"] if a["id"] != aid]
                if (state["reviews"].get(tid, {}).get("status") == "first_failure"
                        and not any(a["trace_id"] == tid for a in state["annotations"])):
                    state["reviews"][tid] = {"status": "unreviewed", "updated_at": now()}
            elif action in {"mark_reviewed", "toggle_review"}:
                trace_ids = event.get("trace_ids")
                if (not isinstance(trace_ids, list) or not trace_ids
                        or any(not isinstance(tid, str) or tid not in self.trace_ids for tid in trace_ids)):
                    raise ValueError("Choose known traces to mark reviewed")
                has_comment = any(a["trace_id"] in trace_ids for a in state["annotations"])
                complete = all(state["reviews"].get(tid, {}).get("status") in
                               {"reviewed", "first_failure", "no_failure"} for tid in trace_ids)
                if action == "toggle_review" and complete and not has_comment:
                    for trace_id in trace_ids:
                        state["reviews"][trace_id] = {"status": "unreviewed", "updated_at": now()}
                else:
                    self._mark_reviewed(state, trace_ids)
            elif action == "review":
                status = event.get("status")
                if status not in {"first_failure", "no_failure", "unreviewed"}:
                    raise ValueError("Invalid review status")
                if status == "first_failure" and not any(a["trace_id"] == tid for a in state["annotations"]):
                    raise ValueError("Write an evidence note before marking the first failure")
                state["reviews"][tid] = {"status": status, "updated_at": now()}
            elif action == "mode":
                mid = str(event.get("id", ""))
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", mid) or not str(event.get("definition", "")).strip():
                    raise ValueError("Use a lowercase mode_id and a nonempty definition")
                previous = next((m for m in state["modes"] if m["id"] == mid), {})
                mode = {**previous, **{key: str(event.get(key, previous.get(key, "")))[:20000]
                                      for key in ("definition", "boundaries", "requirement", "examples")}}
                evaluator = str(event.get("evaluator_type", previous.get("evaluator_type", "")))
                if evaluator and evaluator not in {"code_check", "llm_judge"}:
                    raise ValueError("Choose code check or LLM judge as the evaluator type")
                mode["evaluator_type"] = evaluator
                supports = event.get("annotation_ids", [])
                if not isinstance(supports, list) or any(aid not in {a["id"] for a in state["annotations"]} for aid in supports):
                    raise ValueError("Supporting annotations must refer to saved human notes")
                mode["annotation_ids"] = list(dict.fromkeys(supports))
                mode.update(id=mid, final=event.get("final") is True)
                if "review_status" in event:
                    if event["review_status"] != "approved":
                        raise ValueError("Saving a reviewed mode requires an approved status")
                    mode["review_status"] = "approved"
                if mode["final"]:
                    missing = [label for key, label in (("boundaries", "neighboring-mode boundary"),
                                                       ("requirement", "requirement source"),
                                                       ("evaluator_type", "evaluator type"))
                               if not mode[key].strip()]
                    if not supports:
                        missing.append("originating human annotations")
                    if missing:
                        raise ValueError("Final modes require: " + ", ".join(missing))
                state["modes"] = [m for m in state["modes"] if m["id"] != mid] + [mode]
            elif action == "mode_review":
                mode = next((m for m in state["modes"] if m["id"] == event.get("id")), None)
                if mode is None:
                    raise ValueError("Unknown failure mode")
                if event.get("decision") != "rejected":
                    raise ValueError("Choose Reject, or use the editor to approve a mode")
                mode["review_status"] = "rejected"
            elif action == "label":
                mode = event.get("mode")
                if not any(m["id"] == mode and m.get("final") for m in state["modes"]):
                    raise ValueError("Confirm this mode as final in Taxonomy before labeling")
                value = event.get("value")
                if type(value) is not int or value not in {0, 1}:
                    raise ValueError("A label must be Present (1) or Absent (0)")
                key = tid + ":" + mode
                previous = state["labels"].get(key)
                history = copy.deepcopy(previous.get("history", [])) if previous else []
                if previous:
                    history.append({k: v for k, v in previous.items() if k != "history"})
                state["labels"][key] = {"trace_id": tid, "mode": mode, "value": value,
                                        "comment": str(event.get("comment", ""))[:20000],
                                        "updated_at": now(), "sync": "pending", "history": history}
            elif action == "suggestion":
                suggestion = next((s for s in state["suggestions"] if s.get("id") == event.get("id")), None)
                if not suggestion or suggestion.get("trace_id") not in self.trace_ids:
                    raise ValueError("Suggestion has no accessible trace")
                decision = event.get("decision")
                if decision not in {"accept", "reject"}:
                    raise ValueError("Choose accept or reject")
                sid = suggestion["id"]
                if sid in state["decisions"]:
                    if state["decisions"][sid]["decision"] == decision:
                        if decision == "accept" and self._link_suggestion_note(state, suggestion):
                            self._persist(state)
                        return state
                    raise ValueError("Suggestion already decided")
                state["decisions"][sid] = {"decision": decision, "updated_at": now()}
                if decision == "accept":
                    state["annotations"].append({"id": "accepted:" + sid,
                        "trace_id": suggestion["trace_id"], "note": suggestion.get("note") or suggestion.get("reason") or "Accepted suggestion",
                        "anchor": suggestion.get("anchor") or {"quote": suggestion.get("quote", "")},
                        "source": "human_accepted_ai", "updated_at": now()})
                    self._link_suggestion_note(state, suggestion)
                    self._mark_reviewed(state, [suggestion["trace_id"]])
            elif action != "retry":
                raise ValueError("Unknown review action")
            self._persist(state)  # Save before network I/O so an outage loses no judgment.
            if action in {"label", "retry"}:
                for label in state["labels"].values():
                    if label["sync"] != "pending":
                        continue
                    try:
                        self.sync(label["trace_id"], label["mode"], label["value"], label["comment"])
                        label["sync"] = "synced"
                    except Exception:
                        label["sync"] = "pending"
                self._persist(state)
            return state
