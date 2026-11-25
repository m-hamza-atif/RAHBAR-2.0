"""Change one threshold, verify the failed rule and image, then restore the original YAML."""
import json
from pathlib import Path
import tempfile

import yaml

from ragops_cluster import k, read, wait_job
from uuid import uuid4


def patch(text, resource_version):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "threshold.json"
        path.write_text(json.dumps({"metadata": {"resourceVersion": resource_version},
                                    "data": {"gate_config.yaml": text}}), encoding="utf-8")
        updated = json.loads(k("patch", "configmap/rahbar-gate-config", "--type=merge",
                               "--patch-file", str(path), "-o", "json"))
    print(yaml.safe_dump(updated["data"], sort_keys=False))
    return updated["metadata"]["resourceVersion"]


def attempt(expect_pass):
    job = yaml.safe_load(Path("k8s/eval-job.yaml").read_text())
    name = "threshold-" + uuid4().hex[:10]
    job["metadata"]["name"] = name
    print(k("create", "-f", "-", data=json.dumps(job)))
    try:
        logs = wait_job(name)
    except RuntimeError:
        if expect_pass:
            raise
        logs = k("logs", "job/" + name)
        if "FAIL  max_p95_latency_ms" not in logs or "Release gate: FAIL" not in logs:
            raise RuntimeError("Job failed for a different reason")
    else:
        if not expect_pass or "Release gate: PASS" not in logs:
            raise RuntimeError("Unexpected gate decision")
    pods = json.loads(k("get", "pod", "-l", "job-name=" + name, "-o", "json"))["items"]
    status = pods[0]["status"]["containerStatuses"][0]
    print(name, status["imageID"], status["state"]["terminated"]["exitCode"])
    return status["imageID"]


def main():
    gate = read("configmap/rahbar-gate-config")
    original = gate["data"]["gate_config.yaml"]
    image = attempt(True)
    rules = yaml.safe_load(original)
    rules["max_p95_latency_ms"] = 0
    changed = patch(yaml.safe_dump(rules), gate["metadata"]["resourceVersion"])
    try:
        if attempt(False) != image:
            raise RuntimeError("Evaluator image changed")
    finally:
        patch(original, changed)
    if attempt(True) != image:
        raise RuntimeError("Evaluator image changed after restoration")


if __name__ == "__main__":
    main()
