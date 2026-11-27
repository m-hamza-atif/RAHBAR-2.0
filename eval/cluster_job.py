"""Run both Services against the packaged datasets, then return the actual gate status."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import httpx


def check_models():
    rows = httpx.get(os.environ["OLLAMA_BASE_URL"] + "/api/tags", timeout=20).raise_for_status().json()["models"]
    installed = {row["name"]: row["digest"] for row in rows}
    for model in json.loads(Path("eval/model-manifest.json").read_text())["models"]:
        if installed.get(model["name"]) != model["digest"]:
            raise ValueError(f"Missing or different model revision for {model['name']}")


def main():
    run_id = os.getenv("EVAL_JOB_UID") or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12])
    if not re.fullmatch(r"[\w-]+", run_id):
        raise ValueError("Invalid evaluation Job UID")
    run = Path(os.environ["EVAL_RESULTS_DIR"]) / run_id
    run.mkdir(parents=True, exist_ok=True)
    print(f"RESULT_DIR={run}", flush=True)
    config = run / "gate_config.yaml"
    current_rules = Path(os.environ["GATE_CONFIG_PATH"]).read_bytes()
    if config.exists() and config.read_bytes() != current_rules:
        raise ValueError("Gate thresholds changed since evaluation started")
    if not config.exists():
        pending_config = config.with_suffix(".tmp")
        pending_config.write_bytes(current_rules)
        pending_config.replace(config)
    try:
        check_models()
        for name, address in (("baseline", "STABLE_API"), ("candidate", "CANDIDATE_API")):
            subprocess.run([sys.executable, "eval/run_eval.py", "--suite", "ragops", "--api",
                            os.environ[address], "--cluster-retry", "--golden", "eval/golden.jsonl",
                            "--embedding-pairs", "eval/embedding_pairs.jsonl", "--stochasticity-check",
                            "--out", str(run / (name + ".json"))], check=True)
    except (httpx.RequestError, subprocess.CalledProcessError) as exc:
        print(f"Scoring interrupted: {exc}", file=sys.stderr, flush=True)
        return 2
    gate = subprocess.run([sys.executable, "eval/release_gate.py", "--baseline",
                           str(run / "baseline.json"), "--candidate", str(run / "candidate.json"),
                           "--config", str(config)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (run / "gate.txt").write_bytes(gate.stdout)
    print(gate.stdout.decode(), end="", flush=True)
    return gate.returncode


if __name__ == "__main__":
    sys.exit(main())
