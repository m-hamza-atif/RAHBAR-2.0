"""Operate the single-node Assignment 03 cluster from the repository root."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import time
from uuid import uuid4

import yaml

K = ["kubectl", "--context", "kind-rahbar-asg3", "-n", "rahbar"]
OVERLAY = Path("k8s/overlays/asg3")
INSPECT = "deployment/ragops-inspect"
LIVE = "deployment/rahbar-api"
CANDIDATE = LIVE + "-candidate"
EVIDENCE = Path("docs/evidence")


def k(*args, data=None, show=True):
    if show:
        print("$", " ".join([*K, *args]), flush=True)
    return subprocess.run([*K, *args], input=data, capture_output=False, stdout=subprocess.PIPE,
                          check=True, encoding="utf-8").stdout


def read(resource, *, show=True):
    return json.loads(k("get", resource, "-o", "json", show=show))


def apply(obj):
    print(k("apply", "-f", "-", data=json.dumps(obj)), end="")


def ready(resource):
    print(k("rollout", "status", resource, "--timeout=600s"), end="")


def pod_python(resource, program, *args):
    return k("exec", resource, "--", "python", "-c", program, *args)


def rendered():
    return list(yaml.safe_load_all(subprocess.check_output(
        ["kubectl", "kustomize", str(OVERLAY)], encoding="utf-8")))


def infra(address):
    ip = ipaddress.IPv4Address(address)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        raise ValueError("Supply the cluster-reachable IPv4 address of the model service")
    objects = rendered()
    for obj in objects:
        name = obj["metadata"]["name"]
        if obj["kind"] == "Job" or (obj["kind"] == "Deployment" and name.startswith("rahbar-api")):
            continue
        if name == "rahbar-config":
            obj["data"]["OLLAMA_BASE_URL"] = f"http://{ip}:11434"
        if name == "ragops-inspect":
            obj["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {"name": "OLLAMA_BASE_URL", "value": f"http://{ip}:11434"})
        apply(obj)
    policy = yaml.safe_load((OVERLAY / "model-egress.template").read_text().replace("MODEL_CIDR", f"{ip}/32"))
    apply(policy)
    for resource in ("deployment/redis", "statefulset/chroma", INSPECT):
        ready(resource)
    print(pod_python(INSPECT, "from eval.cluster_job import check_models; check_models(); print('model digests verified')"))


def seed_archive(source, stream):
    rows = json.loads((source / "_index.json").read_text(encoding="utf-8"))
    manifest = dict(re.findall(r"\| `([^`]+)` \| [\d,]+ \| `([0-9a-f]{64})` \|",
                               Path("corpus/MANIFEST.md").read_text(encoding="utf-8")))
    if not rows or len(rows) != len(manifest) or {row["file"] for row in rows} != set(manifest):
        raise ValueError("Seed needs the complete manifest-listed Batch A snapshot")
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for row in rows:
            name = row["file"]
            path = source / name
            if path.resolve().parent != source.resolve() or path.is_symlink():
                raise ValueError(f"Unexpected source path {name}")
            with path.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != manifest[name] or row["sha256"] != manifest[name]:
                    raise ValueError(f"Corpus digest mismatch: {name}")
            archive.add(path, arcname=name, recursive=False)
        archive.add(source / "_index.json", arcname="_index.json", recursive=False)
    stream.seek(0)


def writer(lane):
    return yaml.safe_load((OVERLAY / ("writer.yaml" if lane == "stable" else "candidate-writer.yaml")).read_text())


def seed(source, lane, claim=None):
    # Build the complete tar first. Publish with one same-volume rename, never reseed an active lake.
    with tempfile.TemporaryFile() as stream:
        seed_archive(source, stream)
        spec = writer(lane)["spec"]["template"]["spec"]
        if claim:
            state = next(v for v in spec["volumes"] if "persistentVolumeClaim" in v)
            state["persistentVolumeClaim"]["claimName"] = claim
        name = "seed-" + lane + "-" + uuid4().hex[:8]
        spec["restartPolicy"] = "Never"
        c = spec["containers"][0]
        c.update(image="rahbar-eval:asg3", command=["sleep", "900"], args=[])
        obj = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name}, "spec": spec}
        print(k("create", "-f", "-", data=json.dumps(obj)))
        try:
            k("wait", "--for=condition=Ready", "pod/" + name, "--timeout=180s")
            staging = "/data/" + name
            k("exec", name, "--", "mkdir", staging)
            subprocess.run([*K, "exec", "-i", name, "--", "tar", "--no-same-owner", "-xf", "-", "-C", staging],
                           stdin=stream, check=True)
            print(pod_python(name, "import os,sys; from pathlib import Path; p=Path('/data/lake'); "
                             "assert not p.exists(), 'lake already initialized'; os.rename(sys.argv[1], p)", staging))
        finally:
            print(k("delete", "pod", name))


def wait_job(name):
    print(f"Waiting for Job {name} to complete or fail.", flush=True)
    failures = 0
    while True:
        try:
            job = json.loads(k("get", "job/" + name, "--request-timeout=15s", "-o", "json", show=False))
        except subprocess.CalledProcessError:
            failures += 1
            if failures == 12:
                raise
            print(f"Job status unavailable; check {failures} of 12", flush=True)
            time.sleep(10)
            continue
        failures = 0
        conditions = {v["type"] for v in job.get("status", {}).get("conditions", []) if v["status"] == "True"}
        if conditions & {"Failed", "Complete"}:
            if job["spec"].get("podFailurePolicy"):
                pods = json.loads(k("get", "pods", "-l",
                                    "batch.kubernetes.io/controller-uid=" + job["metadata"]["uid"],
                                    "--sort-by=.metadata.creationTimestamp", "-o", "json"))["items"]
                attempts = []
                for pod in pods:
                    pod_name = pod["metadata"]["name"]
                    try:
                        log = k("logs", pod_name)
                    except subprocess.CalledProcessError:
                        log = f"Pod log unavailable (phase {pod['status']['phase']})"
                    attempts.append(f"Pod {pod_name}\n{log}")
                logs = "\n".join(attempts)
            else:
                logs = k("logs", "job/" + name)
            EVIDENCE.mkdir(exist_ok=True, parents=True)
            (EVIDENCE / (name + ".txt")).write_text(logs, encoding="utf-8")
            if match := re.search(r"^RESULT_DIR=(/data/eval-results/[\w-]+)$", logs, re.M):
                directory = match[1]
                target = Path("eval/results") / Path(directory).name
                target.mkdir(exist_ok=True)
                (target / "job.json").write_text(json.dumps({
                    "name": name, "uid": job["metadata"]["uid"],
                    "created_at": job["metadata"]["creationTimestamp"],
                    "status": job["status"],
                }, indent=2) + "\n", encoding="utf-8")
                files = set(k("exec", INSPECT, "--", "ls", "-1", directory).splitlines())
                for file in ("baseline.json", "candidate.json", "gate_config.yaml", "gate.txt",
                             "baseline.first-pass.json", "candidate.first-pass.json",
                             "baseline.initial.progress.json", "baseline.repeat.progress.json",
                             "candidate.initial.progress.json", "candidate.repeat.progress.json"):
                    if file not in files or (file.endswith(".first-pass.json") and file.replace(".first-pass", "") in files):
                        continue
                    if file.endswith(".progress.json") and file.split(".")[0] + ".json" in files:
                        continue
                    (target / file).write_text(k("exec", INSPECT, "--", "cat", directory + "/" + file),
                                               encoding="utf-8")
            print(logs, flush=True)
            if "Complete" not in conditions:
                raise RuntimeError(f"Job {name} failed; see its log and pod events")
            return logs
        time.sleep(5)


def new_job(obj):
    name = obj["metadata"]["name"] + "-" + uuid4().hex[:10]
    run = {**obj, "metadata": {**obj["metadata"], "name": name}}
    print(k("create", "-f", "-", data=json.dumps(run)))
    return wait_job(name)


def deploy(lane):
    obj = yaml.safe_load((OVERLAY / (lane + ".yaml")).read_text())
    apply(obj)
    ready("deployment/" + obj["metadata"]["name"])
    print(pod_python("deployment/" + obj["metadata"]["name"],
                     "import httpx,os; print(httpx.get(os.environ['OLLAMA_BASE_URL']+'/api/tags').raise_for_status().json())"))


def export_reports(claim):
    """Read writer evidence on a fresh pod without granting the inspector access to lake contents."""
    spec = writer("stable")["spec"]["template"]["spec"]
    spec.pop("serviceAccountName")
    spec["restartPolicy"] = "Never"
    spec["volumes"] = [{"name": "state", "persistentVolumeClaim": {"claimName": claim, "readOnly": True}}]
    container = spec["containers"][0]
    container.update(image="rahbar-eval:asg3", command=["python", "-c"],
                     args=["from pathlib import Path; import json; p=Path('/data/reports'); "
                           "print(json.dumps({f.name: json.loads(f.read_text()) for f in p.glob('verification_*.json')}))"],
                     volumeMounts=[{"name": "state", "mountPath": "/data", "readOnly": True}])
    name = "read-reports-" + uuid4().hex[:10]
    pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name}, "spec": spec}
    print(k("create", "-f", "-", data=json.dumps(pod)))
    try:
        k("wait", "--for=jsonpath={.status.phase}=Succeeded", "pod/" + name, "--timeout=180s")
        reports = json.loads(k("logs", name))
        if not reports:
            raise ValueError(f"No ingestion verification reports on {claim}")
        folder = Path("eval/results") / claim
        folder.mkdir(exist_ok=True, parents=True)
        for filename, report in sorted(reports.items()):
            if not re.fullmatch(r"verification_[\w-]+\.json", filename):
                raise ValueError(f"Unexpected verification filename: {filename}")
            path = folder / filename
            path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(path, report["counts"])
    finally:
        k("delete", "pod", name)


def endpoint(resource):
    url = "http://" + resource.split("/")[1] + ":8000/readyz"
    return json.loads(pod_python(INSPECT, "import httpx,sys;print(httpx.get(sys.argv[1]).raise_for_status().text)", url))


def api_image(deployment):
    labels = deployment["spec"]["selector"]["matchLabels"]
    selector = ",".join(f"{key}={value}" for key, value in sorted(labels.items()))
    pods = json.loads(k("get", "pods", "-l", selector, "-o", "json"))["items"]
    images = {status["imageID"] for pod in pods if not pod["metadata"].get("deletionTimestamp")
              for status in pod.get("status", {}).get("containerStatuses", [])
              if status["name"] == "api" and status["ready"]}
    if len(images) != 1:
        raise RuntimeError(f"Expected a single ready API image for {selector}: {images}")
    return images.pop()


def evaluate(promote, official_job=False):
    for resource in (LIVE, CANDIDATE):
        ready(resource)
    deployments = [read(r) for r in (LIVE, CANDIDATE)]
    images = [api_image(d) for d in deployments]
    gate = read("configmap/rahbar-gate-config")
    if not read("cronjob/ragops-reindex")["spec"]["suspend"]:
        raise ValueError("Suspend scheduled ingestion for the comparison")
    before = [endpoint(r) for r in (LIVE, CANDIDATE)]
    if before[0]["configuration"]["collection"] == before[1]["configuration"]["collection"]:
        raise ValueError("Comparison requires independent collection revisions")
    if official_job:
        if k("get", "job/rahbar-eval", "--ignore-not-found", "-o", "name").strip():
            raise ValueError("The fixed-name Job already exists. Omit --official-job for a new run.")
        result = k("apply", "-f", "k8s/eval-job.yaml")
        print(result, end="")
        if not result.strip().endswith(" created"):
            raise RuntimeError("The comparison must use a newly created Job")
        logs = wait_job("rahbar-eval")
    else:
        logs = new_job(yaml.safe_load(Path("k8s/eval-job.yaml").read_text()))
    directory = re.search(r"^RESULT_DIR=(/data/eval-results/[\w-]+)$", logs, re.M)[1]
    for name, dep, resource, initial, image in zip(("baseline", "candidate"), deployments,
                                                   (LIVE, CANDIDATE), before, images, strict=True):
        report = json.loads(k("exec", INSPECT, "--", "cat", directory + "/" + name + ".json"))
        now = endpoint(resource)
        if (now != initial or report["configuration"] != now["configuration"] or
                report["index_revision"] != now["index_revision"] or
                read(resource)["spec"]["template"] != dep["spec"]["template"] or api_image(dep) != image):
            raise RuntimeError("Evaluated configuration or index changed")
    if gate["metadata"]["resourceVersion"] != read("configmap/rahbar-gate-config")["metadata"]["resourceVersion"]:
        raise RuntimeError("Thresholds changed during evaluation")
    if promote:
        old, candidate = deployments
        patch = [{"op":"test", "path":"/metadata/resourceVersion", "value":read(LIVE)["metadata"]["resourceVersion"]},
                 {"op":"test", "path":"/spec/template", "value":old["spec"]["template"]},
                 {"op":"replace", "path":"/spec/template/spec", "value":candidate["spec"]["template"]["spec"]}]
        print(patch_live(patch))
        ready(LIVE)
        if endpoint(LIVE) != before[1] or api_image(read(LIVE)) != images[1]:
            raise RuntimeError("Live configuration, index or image differs after promotion")
        trace()


def patch_live(patch):
    # Use a file so Windows and POSIX kubectl receive identical JSON.
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "patch.json"
        path.write_text(json.dumps(patch), encoding="utf-8")
        return k("patch", LIVE, "--type=json", "--patch-file", str(path))


def trace():
    profile = endpoint(LIVE)
    req = "import httpx; print(httpx.post('http://rahbar-api:8000/api/ask', " \
          "json={'question':'When is a student placed on academic warning?', }, headers={'X-Cache-Bypass':'true'}, timeout=300).raise_for_status().text)"
    trace_id = json.loads(pod_python(INSPECT, req))["trace_id"]
    args = ("exec", INSPECT, "--", "python", "scripts/inspect_trace.py", "--trace-id", trace_id)
    record = json.loads(k(*args, "--record"))
    cfg = profile["configuration"]
    if (record["collection_name"], record["embedding_version"], record["index_revision"],
        record["model_params"]["top_k"], record["model_params"]["relevance_floor"]) != (
            cfg["collection"], cfg["embed_version"], profile["index_revision"], cfg["top_k"], cfg["relevance_floor"]):
        raise RuntimeError("Fresh trace does not match ready index and retrieval configuration")
    print(json.dumps(record), flush=True)
    print(k(*args))
    dest = Path("traces") / ("asg3-" + trace_id + ".jsonl")
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    p = parser.add_subparsers(dest="action", required=True)
    p.add_parser("infra").add_argument("--model-ip", required=True)
    s = p.add_parser("seed")
    s.add_argument("--source", type=Path, default=Path("corpus/raw"))
    for command in (s, p.add_parser("index"), p.add_parser("deploy"), p.add_parser("reports")):
        command.add_argument("lane", choices=("stable", "candidate"))
    for name in ("eval", "promote"):
        p.add_parser(name).add_argument("--official-job", action="store_true",
                                        help="use kubectl apply -f k8s/eval-job.yaml for the first run")
    p.add_parser("collect-job").add_argument("name", help="existing Job in the assignment namespace")
    for name in ("trace", "bad-release-demo", "sync-cron"):
        p.add_parser(name)
    args = parser.parse_args()
    if args.action == "infra":
        infra(args.model_ip)
    elif args.action == "seed":
        seed(args.source, args.lane)
    elif args.action == "index":
        new_job(writer(args.lane))
    elif args.action == "deploy":
        deploy(args.lane)
    elif args.action == "reports":
        export_reports("state-" + args.lane)
    elif args.action == "collect-job":
        wait_job(args.name)
    elif args.action == "trace":
        trace()
    elif args.action == "bad-release-demo":
        previous = trace()
        other = {"rahbar_policies": "rahbar_policies_candidate",
                 "rahbar_policies_candidate": "rahbar_policies"}[previous["configuration"]["collection"]]
        print(k("set", "env", LIVE, "CHROMA_COLLECTION=" + other, "RELEVANCE_FLOOR=0.99", "TOP_K=1"))
        try:
            ready(LIVE)
            trace()
        finally:
            print(k("rollout", "undo", LIVE))
            ready(LIVE)
        if trace() != previous:
            raise RuntimeError("Rollback did not restore the previous profile and index revision")
    elif args.action == "sync-cron":
        collection = endpoint(LIVE)["configuration"]["collection"]
        lane = {"rahbar_policies":"stable", "rahbar_policies_candidate":"candidate"}[collection]
        cron = yaml.safe_load((OVERLAY / "schedule.yaml").read_text())
        cron["spec"]["jobTemplate"]["spec"] = writer(lane)["spec"]
        cron["spec"]["suspend"] = False
        apply(cron)
    else:
        evaluate(args.action == "promote", args.official_job)


if __name__ == "__main__":
    main()
