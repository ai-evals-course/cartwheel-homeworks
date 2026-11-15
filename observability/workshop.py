"""Opt-in local Workshop interactions alongside the existing Langfuse pipeline.

Raindrop records the turn boundary; a standard OTLP exporter mirrors existing
spans. Langfuse/OpenLLMetry continue to own the provider and instrumentation.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from opentelemetry import trace

log = logging.getLogger("cartwheel.workshop")
_span_processor = None


def setup_span_export():
    """Add a local OTLP destination to the application's existing provider.

    Called after Langfuse setup, once per process. Never initialize a provider
    or change existing processors, instrumentations, or OTLP environment vars.
    """
    global _span_processor
    destination = os.environ.get("RAINDROP_LOCAL_DEBUGGER", "").strip()
    if not destination:
        return False
    if _span_processor is not None:
        return True
    provider = trace.get_tracer_provider()
    if not hasattr(provider, "add_span_processor"):
        log.warning("Workshop span export needs an initialized OpenTelemetry provider")
        return False
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Explicit nonempty headers prevent inheriting cloud OTLP credentials.
        exporter = OTLPSpanExporter(
            endpoint=destination.rstrip("/") + "/traces",
            headers={"Content-Type": "application/x-protobuf"}, timeout=5,
        )
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        _span_processor = processor
        return True
    except Exception:
        log.warning("Workshop could not attach its local span exporter")
        return False


@lru_cache(maxsize=1)
def get_client():
    destination = os.environ.get("RAINDROP_LOCAL_DEBUGGER", "").strip()
    if not destination:
        return None
    from raindrop import Raindrop

    return Raindrop(api_key=None, local_workshop_url=destination,
                    tracing_enabled=False, auto_instrument=False)


def begin_turn(ctx, session_id, message, prompt_version, scenario_id, model):
    try:
        client = get_client()
        if client is None:
            return None
        properties = {"cartwheel.session_id": session_id, "cartwheel.user_role": ctx.role,
                      "cartwheel.user_id": str(ctx.user_id), "cartwheel.prompt_version": prompt_version}
        if scenario_id:
            properties["cartwheel.scenario_id"] = scenario_id
        return client.begin(
            user_id=str(ctx.user_id), event="cartwheel.session_message",
            input=message if _capture_content() else None, convo_id=session_id,
            properties=properties, model=model,
        )
    except Exception:
        log.warning("Workshop could not start this turn's interaction")
        return None


def finish_turn(interaction, output):
    if interaction is None:
        return
    try:
        interaction.finish(output=output if _capture_content() else None)
    except Exception:
        log.warning("Workshop could not finish this turn's interaction")


def shutdown():
    if _span_processor is not None:
        try:
            _span_processor.force_flush(timeout_millis=5000)
        except Exception:
            log.warning("Workshop could not flush all spans")
    if not get_client.cache_info().currsize:
        return
    try:
        client = get_client()
        if client is not None:
            client.shutdown()
    except Exception:
        log.warning("Workshop shutdown could not flush all interactions")


def _capture_content():
    return os.environ.get("TRACELOOP_TRACE_CONTENT", "false").lower() == "true"
