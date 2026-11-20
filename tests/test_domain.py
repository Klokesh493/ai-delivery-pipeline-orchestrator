import json
from pathlib import Path

import pytest

from ops_platform.service import evaluate

def fixture(name):
    return json.loads((Path("examples") / (name + ".json")).read_text())


def test_cycle_and_unknown_dependency_rejected():
    source = fixture("ready")
    source["pipeline"][0]["needs"] = ["deploy"]
    with pytest.raises(ValueError):
        evaluate(source)
    source["pipeline"][0]["needs"] = ["missing"]
    with pytest.raises(ValueError):
        evaluate(source)

def test_canary_must_depend_on_build():
    source = fixture("ready")
    source["pipeline"][3]["needs"] = ["tests", "scan"]
    source["pipeline"][4]["needs"].append("build")
    assert "canary bypasses build" in evaluate(source)["blockers"]

def test_pending_prerequisite_holds():
    source = fixture("ready")
    source["pipeline"][0]["result"] = "pending"
    assert evaluate(source)["decision"] == "release_hold"

def test_exact_latency_threshold_is_allowed():
    source = fixture("ready")
    source["quality"]["candidate_p95_ms"] = 120
    assert evaluate(source)["decision"] == "release_ready"
