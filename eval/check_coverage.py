"""Measure semantic coverage of a fixed live-query sample by a golden dataset."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sys

import httpx

from ragops_eval import make_embedder, read_jsonl, similarity
from run_eval import golden_digest


def score_coverage(live, golden, embed, similarity_threshold):
    indexed = [(row["id"], embed(row["question"])) for row in golden]
    rows = []
    for query in live:
        vector = embed(query["question"])
        score, closest = max((similarity(vector, other), key) for key, other in indexed)
        rows.append({**query, "nearest_golden_id": closest, "cosine": score,
                     "covered": score >= similarity_threshold})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--similarity-threshold", type=float, default=.78)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        target = float(os.getenv("COVERAGE_THRESHOLD", ".85"))
        if not math.isfinite(target) or not 0 <= target <= 1 or not 0 <= args.similarity_threshold <= 1:
            raise ValueError("thresholds must be fractions between zero and one")
        profile = {
            "embed_model": os.getenv("EMBED_MODEL", "nomic-embed-text"),
            "llm_provider": os.getenv("LLM_PROVIDER", "ollama-host"),
            "embed_dim": int(os.getenv("EMBED_DIM", "384" if os.getenv("EMBED_MODEL") == "stub"
                                      or os.getenv("LLM_PROVIDER") == "stub" else "768")),
        }
        live = read_jsonl(args.live)
        golden = read_jsonl(args.golden)
        if len({row["id"] for row in live}) != len(live):
            raise ValueError("live query IDs must be unique")
        if len({row["id"] for row in golden}) != len(golden):
            raise ValueError("golden query IDs must be unique")
        with httpx.Client(timeout=60) as client:
            rows = score_coverage(live, golden, make_embedder(client, profile), args.similarity_threshold)
        uncovered = Counter(row["topic"] for row in rows if not row["covered"])
        covered = sum(row["covered"] for row in rows)
        rate = covered / len(rows)
        passed = rate >= target
        report = {"golden_sha256": golden_digest(args.golden), "live_sha256": golden_digest(args.live),
                  "embedding": profile, "embedding_version": os.getenv("EMBED_VERSION"),
                  "similarity_threshold": args.similarity_threshold, "coverage_threshold": target,
                  "total": len(rows), "covered": covered, "coverage": rate, "passed": passed,
                  "uncovered_by_topic": dict(sorted(uncovered.items())), "rows": rows}
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Coverage: {covered}/{len(rows)} ({rate:.1%}) at cosine >= {args.similarity_threshold:.2f}")
        for topic, count in sorted(uncovered.items()):
            print(f"  Uncovered {topic}: {count}")
        print(f"Coverage gate: {'PASS' if passed else 'FAIL'} (target {target:.1%})")
        return 0 if passed else 1
    except (OSError, ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
        print(f"Coverage check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
