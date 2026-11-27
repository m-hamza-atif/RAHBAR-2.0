"""Compare two RAGOps reports using a mounted or local YAML configuration."""
import argparse
import json
from math import isfinite
import os
from pathlib import Path
import sys

import yaml


def metric(value: object, field: str, maximum: float = 1) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    if not 0 <= value <= maximum:
        raise ValueError(f"{field} is outside its allowed range")
    return float(value)


def evaluate(baseline: dict, candidate: dict, config: dict) -> list[tuple[str, bool, str]]:
    for report in (baseline, candidate):
        if report["schema"] != "ragops-v1" or report["cache_bypass"] is not True:
            raise ValueError("release comparisons require cache-bypassed RAGOps reports")
    for field in ("golden_sha256", "pairs_sha256"):
        if not baseline[field] or baseline[field] != candidate[field]:
            raise ValueError(f"reports differ on {field}")
    for key in ("embed_model", "embed_dim", "embed_version", "llm_provider", "llm_model",
                "generation_seed", "temperature"):
        if baseline["configuration"][key] != candidate["configuration"][key]:
            raise ValueError(f"reports differ on {key}")
    if baseline["end_to_end"]["faithfulness_method"] != candidate["end_to_end"]["faithfulness_method"]:
        raise ValueError("reports use different faithfulness measures")
    drop = (metric(baseline["retrieval"]["recall_at_5"], "baseline recall@5")
            - metric(candidate["retrieval"]["recall_at_5"], "candidate recall@5"))
    end_to_end = candidate["end_to_end"]
    values = {
        "max_recall5_drop": drop,
        "min_faithfulness": metric(end_to_end["faithfulness"], "faithfulness"),
        "max_p95_latency_ms": metric(end_to_end["p95_latency_ms"], "p95 latency", float("inf")),
        "min_abstention_correctness": metric(end_to_end["abstention_correctness"], "abstention correctness"),
    }
    results = []
    for key, observed in values.items():
        threshold = metric(config[key], key, float("inf") if key == "max_p95_latency_ms" else 1)
        upper_bound = key.startswith("max_")
        passed = observed <= threshold + 1e-9 if upper_bound else observed >= threshold - 1e-9
        results.append((key, passed, f"{observed:.4f} {'<=' if upper_bound else '>='} {threshold:.4f}"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(os.getenv("GATE_CONFIG_PATH", "./eval/gate_config.yaml")))
    args = parser.parse_args()
    try:
        old = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
        new = json.loads(args.candidate.read_text(encoding="utf-8-sig"))
        config = yaml.safe_load(args.config.read_text(encoding="utf-8-sig"))
        decisions = evaluate(old, new, config)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"Release gate failed to evaluate: {exc}", file=sys.stderr)
        return 1
    for key, passed, explanation in decisions:
        print(f"{'PASS' if passed else 'FAIL'}  {key:<28} {explanation}")
    decision = all(result[1] for result in decisions)
    print(f"Release gate: {'PASS' if decision else 'FAIL'}")
    return 0 if decision else 1


if __name__ == "__main__":
    sys.exit(main())
