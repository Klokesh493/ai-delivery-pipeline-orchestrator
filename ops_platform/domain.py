"""Validate a delivery DAG and bind release decisions to the actual artifact bytes."""
import base64
import hashlib
import json
from typing import List, Literal

from pydantic import Field, model_validator

from .agent_loop import Probe
from .contracts import Count, Identifier, Positive, Record, unique

TITLE = "AI Delivery Pipeline Orchestrator"
BRIEF = "Inspect CI graph dependencies, artifact bytes, and release quality gates."
SOURCES = ["pipeline", "artifact", "quality"]


class Step(Record):
    id: Identifier
    kind: Literal["test", "scan", "build", "canary", "deploy"]
    needs: List[Identifier] = Field(max_length=20)
    result: Literal["pass", "fail", "pending"]


class Artifact(Record):
    content_base64: str = Field(max_length=32000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Quality(Record):
    artifact_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    tests: Positive
    failures: Count
    critical_findings: Count
    candidate_requests: Positive
    candidate_errors: Count
    baseline_requests: Positive
    baseline_errors: Count
    candidate_p95_ms: Positive
    baseline_p95_ms: Positive
    max_latency_ratio_percent: Positive = 120
    max_error_increase_ppm: Count = 1000

    @model_validator(mode="after")
    def totals(self):
        if (self.failures > self.tests or self.candidate_errors > self.candidate_requests
                or self.baseline_errors > self.baseline_requests):
            raise ValueError("invalid quality count totals")
        return self


class Case(Record):
    pipeline: List[Step] = Field(min_length=1, max_length=50)
    artifact: Artifact
    quality: Quality

    @model_validator(mode="after")
    def graph(self):
        unique([step.id for step in self.pipeline], "step ids")
        known = {step.id for step in self.pipeline}
        pending = {step.id: set(step.needs) for step in self.pipeline}
        if any(not deps <= known for deps in pending.values()):
            raise ValueError("unknown dependency")
        completed = set()
        while pending:
            available = {name for name, deps in pending.items() if deps <= completed}
            if not available:
                raise ValueError("dependency cycle")
            completed.update(available)
            pending = {name: deps for name, deps in pending.items() if name not in available}
        base64.b64decode(self.artifact.content_base64, validate=True)
        return self


def prepare(case):
    source = case.model_dump()
    probes = [Probe(key, "Read " + key + " evidence", lambda key=key: source[key])
              for key in SOURCES]

    def decide(evidence):
        blockers = []
        steps = {step.id: step for step in case.pipeline}
        deploys = [step for step in case.pipeline if step.kind == "deploy"]
        if len(deploys) != 1:
            blockers.append("exactly one deployment target is required")
        ancestors = set()
        queue = list(deploys[0].needs) if len(deploys) == 1 else []
        while queue:
            current = queue.pop()
            if current not in ancestors:
                ancestors.add(current)
                queue.extend(steps[current].needs)
        ancestor_kinds = {steps[name].kind for name in ancestors}
        if not {"test", "scan", "build", "canary"} <= ancestor_kinds:
            blockers.append("deployment must depend on test, scan, build and canary evidence")
        if any(steps[name].result != "pass" for name in ancestors):
            blockers.append("a prerequisite has not passed")
        # A build must depend on tests and scans, and canary must depend on a build.
        def has_ancestor(step, required):
            seen, pending = set(), list(step.needs)
            while pending:
                name = pending.pop()
                if name not in seen:
                    seen.add(name)
                    pending.extend(steps[name].needs)
            return required <= {steps[name].kind for name in seen}
        if any(not has_ancestor(step, {"test", "scan"}) for step in case.pipeline if step.kind == "build"):
            blockers.append("build bypasses test or scan")
        if any(not has_ancestor(step, {"build"}) for step in case.pipeline if step.kind == "canary"):
            blockers.append("canary bypasses build")
        content = base64.b64decode(case.artifact.content_base64, validate=True)
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != case.artifact.sha256:
            blockers.append("artifact digest mismatch")
        quality = case.quality
        if quality.artifact_sha256 != actual_hash:
            blockers.append("quality evidence belongs to a different artifact")
        if quality.failures or quality.critical_findings:
            blockers.append("tests or critical security findings block release")
        difference = (quality.candidate_errors * quality.baseline_requests
                      - quality.baseline_errors * quality.candidate_requests)
        if difference * 1000000 > (
                quality.max_error_increase_ppm * quality.candidate_requests * quality.baseline_requests):
            blockers.append("canary error rate regression")
        if quality.candidate_p95_ms * 100 > quality.baseline_p95_ms * quality.max_latency_ratio_percent:
            blockers.append("canary latency regression")
        return {"decision": "release_ready" if not blockers else "release_hold",
                "ready": not blockers, "citations": SOURCES, "blockers": blockers,
                "artifact_sha256": actual_hash,
                "reason": "Artifact, DAG and quality gates passed." if not blockers
                          else "Release evidence does not satisfy the delivery policy."}

    return probes, decide


def bundle(report):
    return {"release-manifest.json": json.dumps(
        {"artifact_sha256": report["artifact_sha256"], "decision": report["decision"],
         "evidence": report["citations"]}, indent=2)}
