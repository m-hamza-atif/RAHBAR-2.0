"""Validate the rendered Assignment 03 profile and the independently applicable eval Job."""
from pathlib import Path
import subprocess

import yaml


def validate(docs, evaluation):
    by = {(d["kind"], d["metadata"]["name"]): d for d in docs}
    assert len(by) == len(docs)
    assert all(d["metadata"].get("namespace") == "rahbar" for d in [*docs, evaluation] if d["kind"] != "Namespace")
    assert evaluation["metadata"]["name"] == "rahbar-eval"
    assert evaluation["spec"]["backoffLimit"] == 0
    assert evaluation["spec"]["template"]["spec"]["restartPolicy"] == "Never"
    gate = by["ConfigMap", "rahbar-gate-config"]["data"]["gate_config.yaml"]
    assert yaml.safe_load(gate) == yaml.safe_load(Path("eval/gate_config.yaml").read_text())
    for obj in [*docs, evaluation]:
        if obj["kind"] not in ("Deployment", "StatefulSet", "CronJob", "Job"):
            continue
        spec = obj["spec"].get("jobTemplate", obj)["spec"]["template"]["spec"]
        assert spec["automountServiceAccountToken"] is False and spec["enableServiceLinks"] is False
        for c in spec["containers"]:
            assert c["securityContext"]["readOnlyRootFilesystem"]
            assert all(c["resources"][bound][unit] for bound in ("requests", "limits") for unit in ("cpu", "memory"))
            assert all(any(v["name"] == m["name"] for v in spec["volumes"]) or obj["kind"] == "StatefulSet"
                       for m in c["volumeMounts"])
        for v in spec["volumes"]:
            if "persistentVolumeClaim" in v:
                assert ("PersistentVolumeClaim", v["persistentVolumeClaim"]["claimName"]) in by
    cron = by["CronJob", "ragops-reindex"]["spec"]
    assert cron["concurrencyPolicy"] == "Forbid" and cron["suspend"]
    assert cron["jobTemplate"]["spec"] == by["Job", "ragops-indexer"]["spec"]
    collections = []
    for lane, suffix in (("stable", ""), ("candidate", "-candidate")):
        name = "rahbar-api" + suffix
        deployment = by["Deployment", name]["spec"]
        template = deployment["template"]
        assert deployment["strategy"]["rollingUpdate"] == {"maxSurge": 1, "maxUnavailable": 0}
        assert by["Service", name]["spec"]["selector"] == template["metadata"]["labels"]
        assert template["metadata"]["labels"]["lane"] == lane
        reader = template["spec"]["containers"][0]
        writer = by["Job", "ragops-indexer" + suffix]["spec"]["template"]["spec"]["containers"][0]
        renv, wenv = ({e["name"]: e["value"] for e in c["env"]} for c in (reader, writer))
        for key in ("EMBED_MODEL", "EMBED_DIM", "EMBED_VERSION", "LLM_PROVIDER", "CHROMA_COLLECTION"):
            assert renv[key] == wenv[key]
        assert writer["command"] + writer["args"] == ["python", "/app/entrypoint.py", "--incremental"]
        assert renv["TRACE_DIR"] == "/data/traces" and renv["GENERATION_SEED"] == "42"
        assert any(m["name"] == "state-" + lane and m["mountPath"] == "/data" for m in writer["volumeMounts"])
        collections.append(renv["CHROMA_COLLECTION"])
    assert len(set(collections)) == 2
    spec = evaluation["spec"]["template"]["spec"]
    assert any(v.get("configMap", {}).get("name") == "rahbar-gate-config" for v in spec["volumes"])
    assert spec["containers"][0]["command"] == ["python", "eval/cluster_job.py"]


def check(kubeconform):
    p = Path(".artifacts/asg3.yaml")
    p.write_bytes(subprocess.check_output(["kubectl", "kustomize", "k8s/overlays/asg3"]))
    job = Path("k8s/eval-job.yaml")
    validate(list(yaml.safe_load_all(p.read_text(encoding="utf-8"))), yaml.safe_load(job.read_text()))
    policy = Path(".artifacts/asg3-model-egress.yaml")
    policy.write_text(Path("k8s/overlays/asg3/model-egress.template").read_text().replace("MODEL_CIDR", "192.0.2.1/32"))
    subprocess.run([kubeconform, "-strict", "-summary", "-kubernetes-version", "1.32.0",
                    str(p), str(job), str(policy)], check=True)
    print("asg3: invariants and strict schema PASS")
