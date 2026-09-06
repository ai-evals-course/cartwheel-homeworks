"""Resolve an explicit trace source for selection and judge scaling.

The file and Langfuse readers each return normalized records. Keep their
normalization at the I/O boundary; do not normalize live records again here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import langfuse_io, selection


def load_trace_source(source: str | Path | None) -> list[dict[str, Any]]:
    """Load a JSON/JSONL export or the explicit ``"langfuse"`` source.

    Live requests require configured Langfuse and nonempty results. To work
    offline, pass an export path, including the committed demo export.
    File validation and normalization belong to ``selection.load_traces``.
    """
    if isinstance(source, str) and source.lower() == "langfuse":
        if not langfuse_io.is_configured():
            raise langfuse_io.LangfuseNotConfigured(
                "Langfuse is not configured. Configure LANGFUSE_PUBLIC_KEY, "
                "LANGFUSE_SECRET_KEY, and LANGFUSE_HOST, or pass a trace "
                "export path for offline analysis."
            )
        traces = langfuse_io.fetch_traces()
        if not traces:
            raise ValueError("Langfuse returned no traces for the Module 2 slice")
        return traces
    return selection.load_traces(source)
