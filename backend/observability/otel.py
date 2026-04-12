"""Optional OpenTelemetry setup.

If `PHOENIX_COLLECTOR_ENDPOINT` is set in the environment, install the
OpenInference LangChain instrumentation and export spans via OTLP. This is
purely additive: the in-app LLM cards work without OTel via the LangChain
callback handler in `callbacks.py`.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("assistant.observability")

_instrumented = False


def init_otel() -> None:
    global _instrumented
    if _instrumented:
        return
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
    if not endpoint:
        log.info("OTel: PHOENIX_COLLECTOR_ENDPOINT not set — skipping")
        return
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as exc:
        log.warning("OTel deps missing, skipping: %s", exc)
        return

    provider = TracerProvider(resource=Resource.create({"service.name": "assistant"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    LangChainInstrumentor().instrument()
    _instrumented = True
    log.info("OTel initialized — exporting to %s", endpoint)
