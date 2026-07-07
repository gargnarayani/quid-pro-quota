# QuidPro Quota

> A multi-agent resiliency framework built with the Google Agent Development Kit (ADK) that keeps AI applications running when API rate limits are reached through intelligent key rotation, automated recovery, and secure local fallback execution.

---

## Overview

Modern AI applications often depend on external LLM APIs. While these services are powerful, they are also constrained by rate limits and quota restrictions. When an application exceeds its available quota, requests fail with HTTP 429 errors, interrupting workflows and reducing reliability.

QuidPro Quota addresses this problem by introducing a resilient, multi-agent architecture that detects quota failures, automatically rotates to available credentials, and, when necessary, transitions workloads to a secure local execution environment instead of allowing requests to fail.

Rather than treating API limits as fatal errors, the system treats them as routing decisions.

---

## Motivation

As AI-powered applications scale, reliability becomes just as important as model quality. A single exhausted API key can halt an entire pipeline despite other credentials or local computing resources remaining available.

QuidPro Quota was designed to explore how autonomous agents can coordinate recovery strategies without requiring manual intervention. By combining workflow orchestration, fault detection, credential management, and sandboxed execution, the project demonstrates a practical approach to building more resilient AI systems.

---

## Architecture

The project is organized around a collection of specialized agents coordinated through a workflow graph built with Google ADK.

### Supervisor Agent

The supervisor acts as the central orchestrator for every request. It manages workflow state, routes execution between agents, and handles recovery when failures occur.

Responsibilities include:

- Coordinating agent execution
- Tracking workflow state
- Catching runtime exceptions
- Redirecting failed tasks into recovery paths

---

### Crypto Router Agent

The Crypto Router manages API credentials.

When an API responds with an HTTP 429 error, the router:

- Temporarily removes the exhausted credential from circulation
- Places it into a timed blacklist
- Selects the next available credential
- Continues execution without restarting the workflow

If credential lookup itself becomes unresponsive, timeout protection prevents the workflow from hanging indefinitely.

---

### Exchange Auditor

The Exchange Auditor records execution activity and maintains a lightweight transaction ledger.

Its responsibilities include:

- Tracking execution statistics
- Recording token exchange values
- Periodically creating signed checkpoints
- Verifying checkpoint integrity using HMAC-SHA256

This allows workflow state to survive process restarts while protecting checkpoint files from tampering.

---

### Boundary Guard (`sub_agents/guardian.py` & `skills/boundary_guard/`)

The Boundary Guard is responsible for safely executing local workloads and protecting the system from potentially unsafe or malicious tasks. It is composed of two specialized agents that work together to isolate execution and monitor runtime behavior.

Green Team Sandbox Agent
- Executes tasks within resource-constrained environments.
- Enforces CPU and memory limits to prevent workloads from consuming excessive system resources.
- Provides a controlled execution environment for local fallback tasks.

Probabilistic Agent Judge
- Continuously monitors execution logs and agent interactions for suspicious behavior, including prompt injection attempts and unexpected outputs.
- Detects anomalies during runtime and raises a `ToolException("P2P_LINK_OUTAGE")` when intervention is required.
- Signals the supervisor agent to transition the workflow into a safe recovery path, preventing compromised tasks from continuing execution.

---

## Fault Recovery Workflow

The recovery process follows four primary stages:

1. A request encounters an HTTP 429 rate-limit error.
2. The exhausted credential is temporarily blacklisted.
3. A replacement credential is selected automatically.
4. If no credentials remain available, execution transitions into the local sandbox queue until cloud resources become available again.

This approach minimizes downtime while avoiding repeated failed requests.

---

## Technology Stack

- **Google Agent Development Kit (ADK)**
- **Python 3.11+**
- **FastAPI**
- **WebSockets**
- **FastMCP**
- **Uvicorn**
- **asyncio**
- **HMAC-SHA256**
- **uv** package manager
- **Gherkin / Cucumber** behavioral specifications

---

## Project Structure

```text
quid-pro-quota/
│
├── agent.py
├── app.py
├── tools/
│   ├── crypto_router.py
│   └── exchange_auditor.py
│
├── skills/
│   ├── proxy_broker/
│   ├── market_valuator/
│   └── boundary_guard/
│
├── quota_resiliency.feature
├── pyproject.toml
└── README.md
```

---

## 🛠️ System Prerequisites & Host Dependencies

Before initializing the local orchestration daemon, ensure your workstation satisfies the following software and system environment configurations:

* **Python Runtime:** Python 3.11 or higher (managed via `uv` for lightning-fast environment provisioning).
* **Package Manager:** `uv` (Astral's ultra-fast dependency manager).
* **Operating System Isolation:** Linux / macOS (supporting kernel-level resource constraints and local sandboxing wrappers via POSIX processes).
* **Terminal Interface:** The official Antigravity CLI toolkit installed (`agy`).

---

## 🚀 Local Deployment & Installation Steps

Follow these exact steps to clone, configure, and initialize the system environment on your local workstation.

### Step 1: Clone the Core Codebase and Setup the Virtual Sandbox
Leverage `uv` to pull down dependencies and initialize an isolated virtual workspace environment natively without polluting global system paths:

```bash
# Clone the repository structure
git clone [https://github.com/your-username/project-quidpro-quota.git](https://github.com/your-username/project-quidpro-quota.git)
cd project-quidpro-quota

# Sync and install localized locked dependencies via uv
uv sync

**### Step 2: Initialize the Local QuidPro Quota Daemon**
Launch the background FastAPI controller web server and the native ADK 2.0 execution graph runner. This node manages local telemetry and hosts your loopback fallback gateway interface:

```bash
# Spin up the orchestration daemon bound locally to port 8000
uv run uvicorn app:app --host 127.0.0.1 --port 8000 --reload

Once initialized, open your browser and navigate to http://127.0.0.1:8080 to access the interactive FastAPI Control Room Dashboard to monitor physical telemetry and logging traces in real time.

**### Step 3: Inject the Local Fallback Configuration into Antigravity**
Open or create your global Antigravity CLI configuration file located at ~/.gemini/antigravity-cli/settings.json. Update or paste the parameters below exactly as written to point upstream failures directly to your local daemon loopback interface.

(Note: To prevent the markdown parser from flattening lines in your editor, this snippet is wrapped inside a formatting-safe HTML block)

**### Step 4: Launch the Antigravity TUI**
Initialize your active terminal workspace workspace exactly as you normally would. The local proxy will now silently intercept downstream exceptions:

```bash
agy

---

## Testing

The project includes behavior-driven specifications that validate resiliency and recovery behavior.

Example scenarios include:

- API quota exhaustion
- Credential rotation
- Recovery after network failures
- Sandbox isolation
- Workflow checkpoint verification

---

## Design Principles

QuidPro Quota was built around several guiding principles:

- **Graceful degradation** instead of abrupt failure
- **Autonomous recovery** through coordinated agents
- **Security-first execution** with isolated workloads
- **State-aware workflows** that preserve progress across failures
- **Modular architecture** that allows new agents and recovery strategies to be added with minimal changes

---

## Future Work

Potential extensions include:

- Distributed peer-to-peer resource sharing between devices
- Predictive quota forecasting using historical usage patterns
- Dynamic workload scheduling across heterogeneous hardware
- Support for additional LLM providers and cloud platforms
- Visualization of workflow graphs and recovery metrics

---

## License

This project was developed as a hackathon prototype exploring resilient multi-agent systems for AI infrastructure.
