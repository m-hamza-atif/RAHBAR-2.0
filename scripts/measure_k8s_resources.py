"""Sample actual container CPU/memory with the requests and limits from the same pod."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from ragops_cluster import K

PATH = Path("docs/evidence/k8s_resources_asg3.txt")


def summary():
    groups = {}
    for line in PATH.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = (row["phase"], row["container"], row["pod"])
        group = groups.setdefault(key, [0, 0, 0])
        group[0] += 1
        group[1] = max(group[1], int(row["cpu"].removesuffix("m")))
        group[2] = max(group[2], int(row["memory"].removesuffix("Mi")))
    print("Phase       Container   Pod                                        Samples   Peak mCPU   Peak Mi")
    for (phase, name, pod), (n, cpu, memory) in sorted(groups.items()):
        print(f"{phase:<11} {name:<11} {pod:<42} {n:7d} {cpu:11d} {memory:9d}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=["idle", "ingestion", "queries", "evaluation", "candidate", "concurrent", "summary"])
    p.add_argument("--samples", type=int, default=6)
    p.add_argument("--interval", type=int, default=15)
    args = p.parse_args()
    if args.samples < 1 or args.interval < 1:
        p.error("samples and interval must be positive")
    if args.phase == "summary":
        summary()
        return
    PATH.parent.mkdir(exist_ok=True, parents=True)
    for n in range(args.samples):
        pods = json.loads(subprocess.check_output([*K, "get", "pods", "-o", "json"]))["items"]
        rows = subprocess.check_output([*K, "top", "pods", "--containers", "--no-headers"], text=True)
        resources = {(pod["metadata"]["name"], c["name"]): c["resources"] for pod in pods
                     for c in pod["spec"]["containers"]}
        records = []
        for row in rows.splitlines():
            pod, container, cpu, memory = row.split()
            if (pod, container) not in resources or not cpu.endswith("m") or not memory.endswith("Mi"):
                continue
            records.append({"time": datetime.now(timezone.utc).isoformat(), "phase": args.phase,
                            "pod": pod, "container": container, "cpu": cpu, "memory": memory,
                            **resources[pod, container]})
        if not records:
            raise RuntimeError("No measured containers. Retry after metrics-server collects a sample.")
        with PATH.open("a", encoding="utf-8") as out:
            for record in records:
                print(json.dumps(record), file=out)
        print(rows, flush=True)
        if n + 1 < args.samples:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
