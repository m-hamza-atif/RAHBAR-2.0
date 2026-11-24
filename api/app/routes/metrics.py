"""Prometheus metrics at /metrics (section 4.8).

Request count and latency are wired up already. Add your own the same way:
retrieval latency, generation latency, cache hits, abstentions, fallbacks, tokens.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, Gauge, generate_latest

router = APIRouter()

REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

RETRIEVAL = Histogram("rahbar_retrieval_seconds", "Retrieval latency")
GENERATION = Histogram("rahbar_generation_seconds", "Generation latency")
CACHE_HITS = Counter("rahbar_cache_hits_total", "Semantic cache hits")
CACHE_MISSES = Counter("rahbar_cache_misses_total", "Semantic cache misses or skips")
CACHE_RATIO = Gauge("rahbar_cache_hit_ratio", "Process-local cache hit ratio")
ABSTENTIONS = Counter("rahbar_abstentions_total", "Honest abstentions")
FALLBACKS = Counter("rahbar_fallback_total", "Safe generation fallbacks")
PROMPT_TOKENS = Counter("rahbar_prompt_tokens_total", "Provider tokens or whitespace estimates")
COMPLETION_TOKENS = Counter("rahbar_completion_tokens_total", "Provider tokens or whitespace estimates")
TRACE_WRITE_FAILURES = Counter("rahbar_trace_write_failures_total", "Trace stdout or file write failures")
QUERY_STAGE = Histogram("rahbar_query_stage_seconds", "Query stage latency", ["stage"],
                        buckets=(.001, .005, .01, .025, .05, .1, .25, .5, 1, 2, 5, 10, 30, 60, 120))
TOP1 = Histogram("rahbar_top1_similarity", "Top retrieval similarity before relevance filtering",
                 buckets=(0, .1, .2, .3, .35, .4, .5, .6, .7, .8, .9, .95, 1))
TOP1_MIN = Gauge("rahbar_top1_similarity_min", "Minimum top-1 similarity in this process")
TOP1_MAX = Gauge("rahbar_top1_similarity_max", "Maximum top-1 similarity in this process")
QUERY_OUTCOMES = Counter("rahbar_query_outcomes_total", "Processed query outcomes", ["outcome"])
INJECTION_ATTEMPTS = Counter("rahbar_injection_attempts_total", "Flagged query or evidence items", ["source"])

_similarity_lock = Lock()
_similarity_bounds: tuple[float, float] | None = None


def update_cache_ratio() -> None:
    hits = CACHE_HITS._value.get()
    total = hits + CACHE_MISSES._value.get()
    CACHE_RATIO.set(hits/total if total else 0)


def observe_query_trace(trace: dict[str, Any]) -> None:
    global _similarity_bounds
    for stage, milliseconds in trace["latency_per_stage"].items():
        if milliseconds > 0:
            QUERY_STAGE.labels(stage=stage.removesuffix("_ms")).observe(milliseconds / 1000)
    score = trace["top1_similarity"]
    if score is not None:
        TOP1.observe(score)
        with _similarity_lock:
            minimum, maximum = _similarity_bounds or (score, score)
            _similarity_bounds = min(minimum, score), max(maximum, score)
            TOP1_MIN.set(_similarity_bounds[0])
            TOP1_MAX.set(_similarity_bounds[1])
    outcome = ("error" if trace["abstained"] is None else
               "abstained" if trace["abstained"] else "answered")
    QUERY_OUTCOMES.labels(outcome=outcome).inc()
    for action in trace["guardrail_actions"]:
        if action.get("source") in {"evidence", "query"}:
            INJECTION_ATTEMPTS.labels(source=action["source"]).inc()
