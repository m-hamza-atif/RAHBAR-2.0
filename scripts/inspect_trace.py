"""Print the recorded retrieval context and exact generation messages for one query."""
import argparse
import json
import sys

from trace_records import read_records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--record", action="store_true", help="print the complete trace record")
    args = parser.parse_args()
    try:
        for trace in read_records():
            if trace["trace_id"] != args.trace_id:
                continue
            if args.record:
                print(json.dumps(trace, indent=2))
                return 0
            fields = ("trace_id", "generation_status", "cache_source_trace_id",
                      "generation_question", "context_passages", "prompt_hash",
                      "full_prompt", "prompt_attempts")
            result = {field: trace[field] for field in fields}
            result["generation_skip_reason"] = trace.get("generation_skip_reason")
            if source_id := trace["cache_source_trace_id"]:
                origin = next((record for record in read_records()
                               if record["trace_id"] == source_id), None)
                result["cached_from"] = {field: origin[field] for field in fields} if origin else None
            print(json.dumps(result, indent=2))
            return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Cannot inspect trace: {exc}", file=sys.stderr)
        return 1
    print(f"Trace ID not found: {args.trace_id}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
