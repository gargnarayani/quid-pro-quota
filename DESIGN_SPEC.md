# DESIGN SPECIFICATION - PROJECT QUIDPRO QUOTA (ADK 2.0)

## Version: 2.0.0
## Codename: Project QuidPro Quota
## Framework: Google Agent Development Kit (ADK 2.0)
## Target: Google Cloud Run (us-central1)

---

## 1. Executive Summary & Core Mechanics

Project QuidPro Quota is a decentralized, zero-trust resource clearinghouse and fallback network designed to prevent API token/quota exhaustion (HTTP 429) and maximize the utility of local developer compute resources (such as idle GPUs/VRAM). The architecture orchestrates two major rings of operation under a strict token budget:

1. **Pool 1: Multi-Tenant Key Vault & Circuit Breaker**
   Dynamically shifts requests across local alternative API configurations (e.g., alternate Gemini accounts or secondary workspace profiles) using a strict temporal isolation matrix. When a key experiences a rate limit (HTTP 429), the circuit breaker rotates credentials to an alternate key in less than 2500ms.
2. **Pool 2: Peer-to-Peer Proxy-Compute Swap Network**
   Connects to a local mesh overlay network via Secure WebSockets (WSS) and Kademlia DHT node discovery. When local Pool 1 keys are completely depleted, Pool 2 trades remote API execution on peer systems in exchange for hosting isolated, sandboxed offline compute workloads locally.

---

## 2. Multi-Agent Topology

The system uses a decoupled graph workflow orchestrated by the ADK 2.0 Graph Canvas:

### Cognitive Supervisor (Root Agent)
- Governs the parent graph canvas layout and routes tasks along healthy edge conditions.
- Ingests live diagnostics from the telemetry server and updates the local terminal user interface (TUI).
- Catch-all and recovery coordinator for exceptions.

### Branch A: Operations & Dynamic Resource Routing
- **Crypto-Router Agent**: Gatekeeps local credential rotation pools. Monitors API response codes and maps alternate key allocations under a strict 2000ms processing timeout.
- **Kernel Guardian Agent**: Manages P2P mesh discovery and ledger tasks. Splits large compute arrays into 10% balanced sub-batches and handles asynchronous node distribution.
- **Exchange Auditor Agent**: Long-running analytical ledger engine. Computes fair token-to-hardware currency values based on real-time market demand metrics.

### Branch B: Red/Blue/Green Security Triad
- **Blue Team Defense Agent**: Monitors remote connection health. Triggers a Dual-Phase Graceful Quiescence sequence to safely drop the network link upon anomalous peer behavior.
- **Green Team Sandbox Agent**: Manages local container containment boundaries. Constrains untrusted guest payloads to zero-privilege gVisor runtime containers with Memory = 2GB and CPU = 10% cgroupsv2 limits.
- **Probabilistic Agent Judge**: Audits transaction logs for compliance, scrubbing developer keys, paths, and tokens before transmission. Raises `google.adk.ToolException` on prompt injection detection.

---

## 3. Key Architectural Requirements & Safety Resiliency

### A. Automated Token Vault Circuit-Breaker Triggering (HTTP 429 Exhaustion)
- **Target Component**: `Crypto-Router Agent`
- **Specification**: When a Gemini API call encounters an HTTP 429 response, the circuit-breaker intercepts it, blacklists the key for 300 seconds, and rotates to the next available token key in Pool 1. The total latency for circuit-breaker interception, credential rotation, and query completion must be less than 2500ms.

### B. TUI Stream Ingestion Overload Rate-Limiting Truncation
- **Target Component**: `app.py` / Telemetry Server
- **Specification**: The local dashboard ingests diagnostic streams from peer nodes. To prevent buffer overflows and terminal UI freezing, a rate-limiting thread monitors the display buffer. If the ingestion rate exceeds 16KB/s, it truncates incoming display chunk buffers without crashing the parent data ingestion thread.

### C. Micro-Turn Malicious Guest Payload Execution and Container Quarantine
- **Target Component**: `Green Team Sandbox Agent`
- **Specification**: Untrusted guest compute payloads run inside a container restricted via `cgroupsv2`. Failsafe limits are hard-capped at **Memory = 2GB** and **CPU = 10%**. Upon a boundary breach (e.g. attempting to read host files, exceed limits, or escape the sandbox), the system triggers quarantine and freezes the container within 100ms.

### D. Stateless Checkpoint Enforcement
- **Specification**: Every 10 iterations, the system aggregates transaction ledger variables, captures a signed cryptographic JSON snapshot of metrics, and persists it to a secure stream path (GCS bucket or secure volume mount) to survive Cloud Run instance recycles.

### E. High-Stakes Human-in-the-Loop (HITL) Safety Seal
- **Specification**: Transition from Pool 1 to Pool 2 (P2P Barter Mesh) requires explicit developer confirmation via the ADK 2.0 `RequestInput` function node, freezing graph propagation until approved.

---

## 4. Gherkin Feature Matrix (tests/features/quota_resiliency.feature)

The behavior of these subsystems is strictly enforced through a Gherkin behavior-driven test suite:

- **Scenario 1**: Automated Token Vault Circuit-Breaker Triggering under HTTP 429 Exhaustion.
- **Scenario 2**: TUI Stream Ingestion Overload Rate-Limiting Truncation.
- **Scenario 3**: Micro-Turn Malicious Guest Payload Execution and Container Quarantine.
