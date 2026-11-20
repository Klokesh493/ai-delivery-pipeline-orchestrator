# Engineering case study

## Engineering problem

A green stage can be unrelated to the artifact being released, and a pipeline can bypass required checks through an incorrect dependency graph.

## Design choices

Graph validation rejects cycles and unknown dependencies. Builds must depend on test and scan evidence, and canaries must depend on a build. Quality reports include the artifact digest so a passing report from a different artifact cannot authorize export.

## Implementation

I built a release orchestration API that validates the pipeline DAG, binds quality evidence to the SHA-256 of decoded artifact bytes, checks test and scan outcomes, and compares canary error rates and latency before exporting a release manifest.

The API and CLI share ops_platform.service.evaluate. Domain contracts and decisions live in ops_platform/domain.py. SQLite persistence is implemented in ops_platform/storage.py. Prometheus metrics are created per API instance. The deployment directory contains the supplied observability and Kubernetes configuration.

## Technical challenges

A digest mismatch, prerequisite bypass, pending gate, failed test, critical finding, or canary regression holds the release. Threshold comparisons include an explicit allowance at the configured boundary.

Retry handling also matters across all workflows. A duplicate client request reuses its report, while stale approvals fail with HTTP 409. An unavailable model records an incomplete report that cannot be approved. HEC failures leave audit events pending.

## Validation results

6 labeled domain scenarios passed. The actual local Qwen run returned release_ready for ready.json and release_hold for hold.json. Captured reports include the model name, probe trace, content digests, and cited evidence. API and domain tests cover the decision policy and workflow failure cases. [Validation details](VALIDATION.md)

## Lessons learned

A release decision needs both a valid dependency path and evidence bound to the exact artifact.

## Remaining scope

Stage results and canary measurements are synthetic supplied evidence. The platform validates and orchestrates the approval workflow. It does not execute remote CI jobs or deploy the application. Authenticating external stage attestations is a future integration.
