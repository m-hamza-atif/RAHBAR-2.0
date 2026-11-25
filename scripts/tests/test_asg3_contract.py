from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_gate_config_and_independent_lanes():
    check = module(ROOT / "scripts/validate_asg3.py").validate
    docs = list(yaml.safe_load_all(subprocess.check_output(["kubectl", "kustomize", "k8s/overlays/asg3"])))
    job = yaml.safe_load((ROOT / "k8s/eval-job.yaml").read_text())
    check(docs, job)
    broken = deepcopy(job)
    broken["spec"]["backoffLimit"] = 4
    with pytest.raises(AssertionError):
        check(docs, broken)


@pytest.mark.parametrize("gate_status", [0, 1])
def test_job_preserves_gate_status(monkeypatch, tmp_path, gate_status):
    worker = module(ROOT / "eval/cluster_job.py")
    monkeypatch.setattr(worker, "check_models", lambda: None)
    monkeypatch.setenv("EVAL_RESULTS_DIR", str(tmp_path))
    monkeypatch.setenv("GATE_CONFIG_PATH", str(ROOT / "eval/gate_config.yaml"))
    monkeypatch.setenv("STABLE_API", "stable")
    monkeypatch.setenv("CANDIDATE_API", "candidate")
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, gate_status if cmd[1].endswith("release_gate.py") else 0, b"decision\n")

    monkeypatch.setattr(worker.subprocess, "run", run)
    assert worker.main() == gate_status
    assert [cmd[cmd.index("--api") + 1] for cmd in calls[:2]] == ["stable", "candidate"]
    assert calls[2][:2] == [sys.executable, "eval/release_gate.py"]
    assert list(tmp_path.glob("*/gate.txt"))[0].read_bytes() == b"decision\n"


def test_failed_evaluation_prevents_live_patch(monkeypatch):
    release = module(ROOT / "scripts/ragops_cluster.py")
    monkeypatch.setattr(release, "ready", lambda resource: None)
    monkeypatch.setattr(release, "read", lambda resource: {"spec": {"suspend": True}})
    monkeypatch.setattr(release, "api_image", lambda deployment: "sha256:test")
    monkeypatch.setattr(release, "endpoint", lambda resource: {"configuration": {"collection": resource}})

    def reject(job):
        raise RuntimeError("evaluation job failed")

    monkeypatch.setattr(release, "new_job", reject)
    monkeypatch.setattr(release, "patch_live", lambda patch: pytest.fail("rejected candidate reached rollout"))
    with pytest.raises(RuntimeError, match="evaluation job failed"):
        release.evaluate(promote=True)
