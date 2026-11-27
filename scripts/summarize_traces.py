"""Summarize completed and failed queries in a trailing UTC window."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from math import ceil
from statistics import mean, median
import sys

from trace_records import read_records

STAGES = ("cache_ms", "embed_ms", "retrieve_ms", "rerank_ms", "generate_ms", "total_ms")


def p95(values: list[float]) -> float | None:
    return sorted(values)[ceil(len(values) * .95) - 1] if values else None


def summarize(minutes: int) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes)
    scores = []
    durations: dict[str, list[float]] = {stage: [] for stage in STAGES}
    total = completed = cache_hits = abstentions = injections = 0
    for trace in read_records():
        seen = datetime.fromisoformat(trace["timestamp"])
        if not start <= seen <= now:
            continue
        total += 1
        if trace["abstained"] is not None:
            completed += 1
            abstentions += int(trace["abstained"])
            cache_hits += int(trace["cache_hit"])
        if trace["top1_similarity"] is not None:
            scores.append(trace["top1_similarity"])
        for stage, values in durations.items():
            duration = trace["latency_per_stage"][stage]
            if duration > 0:
                values.append(duration)
        injections += sum(action.get("source") in {"query", "evidence"}
                          for action in trace["guardrail_actions"])
    return {
        "window_minutes": minutes, "queries": total, "completed": completed,
        "top1_similarity": {
            "count": len(scores), "min": min(scores) if scores else None,
            "p50": median(scores) if scores else None, "mean": mean(scores) if scores else None,
            "max": max(scores) if scores else None,
        },
        "abstention_rate": abstentions / completed if completed else None,
        "cache_hit_rate": cache_hits / completed if completed else None,
        "p95_latency_per_stage_ms": {stage: p95(samples) for stage, samples in durations.items()},
        "injection_attempts_flagged": injections,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, required=True)
    args = parser.parse_args()
    if args.minutes < 1:
        parser.error("--minutes must be positive")
    try:
        print(json.dumps(summarize(args.minutes), indent=2))
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        print(f"Cannot summarize traces: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
