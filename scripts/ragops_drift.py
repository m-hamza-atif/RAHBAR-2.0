"""Run Parts A/E on a new lake and collection; keep all production Services unchanged."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

import yaml

from ragops_cluster import INSPECT, OVERLAY, apply, k, new_job, ready, seed, writer


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path("corpus/raw"))
    args = p.parse_args()
    name = "drift-" + uuid4().hex[:10]
    print("Isolated experiment", name, flush=True)
    claim = next(yaml.safe_load_all((OVERLAY / "storage.yaml").read_text()))
    claim["metadata"]["name"] = name
    apply(claim)
    seed(args.source, "stable", claim=name)
    job = writer("stable")
    job["metadata"]["name"] = name + "-index"
    spec = job["spec"]["template"]["spec"]
    spec["volumes"][1]["persistentVolumeClaim"]["claimName"] = name
    container = spec["containers"][0]
    collection = name.replace("-", "_")
    for item in container["env"]:
        if item["name"] == "CHROMA_COLLECTION":
            item["value"] = collection
    new_job(job)
    new_job(job)
    api = yaml.safe_load((OVERLAY / "stable.yaml").read_text())
    api["metadata"]["name"] = name
    api["spec"]["replicas"] = 1
    api["spec"]["template"]["metadata"]["labels"]["lane"] = name
    api["spec"]["selector"]["matchLabels"]["lane"] = name
    for item in api["spec"]["template"]["spec"]["containers"][0]["env"]:
        if item["name"] == "CHROMA_COLLECTION":
            item["value"] = collection
    service = next(yaml.safe_load_all((OVERLAY / "api-services.yaml").read_text()))
    service["metadata"]["name"] = name
    service["spec"]["selector"]["lane"] = name
    apply(service)
    apply(api)
    ready("deployment/" + name)

    def score(stage):
        result = name + "-" + stage + ".json"
        evaluation = yaml.safe_load(Path("k8s/eval-job.yaml").read_text())
        evaluation["metadata"]["name"] = name + "-" + stage
        evaluation["spec"]["template"]["spec"]["containers"][0]["command"] = [
            "python", "eval/run_eval.py", "--suite", "ragops", "--api", "http://" + name + ":8000",
            "--golden", "eval/golden.jsonl", "--embedding-pairs", "eval/embedding_pairs.jsonl",
            "--out", "/data/eval-results/" + result]
        new_job(evaluation)
        Path("eval/results", result).write_text(k("exec", INSPECT, "--", "cat", "/data/eval-results/" + result),
                                               encoding="utf-8")

    score("before")
    batch = {p.name: p.read_text(encoding="utf-8") for p in Path("corpus/batch_b").glob("*.md")
             if p.name != "README.md"}
    apply({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name}, "data": batch})
    # Stage the synthetic material once on this experiment's private PVC.
    spec["volumes"].append({"name": "batch", "configMap": {"name": name}})
    container["volumeMounts"].append({"name": "batch", "mountPath": "/batch", "readOnly": True})
    container["command"] = ["sh", "-ec"]
    container["args"] = ["cp /batch/*.md /data/lake/ && exec python /app/entrypoint.py --incremental"]
    job["metadata"]["name"] = name + "-batch"
    logs = new_job(job)
    print(logs)
    score("after")
    container["command"] = ["python", "/app/entrypoint.py"]
    container["args"] = ["--rollback-doc", "academic-rules", "--to-version", "2026-06"]
    job["metadata"]["name"] = name + "-restore"
    new_job(job)
    print(k("get", "svc/" + name, "-o", "name"))
    print("Restored the June edition in the experiment collection", json.dumps(collection))


if __name__ == "__main__":
    main()
