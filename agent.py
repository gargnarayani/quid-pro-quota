import os
import json
import asyncio
from typing import Dict, Any, Generator, AsyncGenerator
from pydantic import BaseModel, Field

# Monkeypatch ToolException into google.adk for framework compliance
import google.adk
class ToolException(Exception):
    """Raised when there is an unrecoverable tools or network failure."""
    pass
google.adk.ToolException = ToolException

from google.adk.workflow import Workflow, node, START, Edge
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from sub_agents.guardian import (
    create_crypto_router_agent,
    create_kernel_guardian_agent,
    create_exchange_auditor_agent,
    create_blue_team_defense_agent,
    create_green_team_sandbox_agent,
    create_probabilistic_agent_judge
)
from tools.crypto_router import rotate_key_tool, BLACKLIST
from tools.exchange_auditor import record_transaction_tool, AUDITOR

SIMULATION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".telemetry_sim.json")

class WorkflowInput(BaseModel):
    prompt: str = Field(description="The user query or compute payload task to process.")

class WorkflowOutput(BaseModel):
    status: str
    result: str
    log_trail: str

@node(rerun_on_resume=True)
async def supervisor_node(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    """Cognitive Supervisor Node.
    Reads telemetry, checks quota levels, manages fallback pools, and handles HITL checkpoints.
    """
    # 1. Read simulated host diagnostics
    token_capacity = 100.0
    if os.path.exists(SIMULATION_FILE):
        try:
            with open(SIMULATION_FILE, "r") as f:
                data = json.load(f)
                token_capacity = data.get("token_capacity_percent", 100.0)
        except Exception:
            pass

    yield Event(
        output={"status": "checking_diagnostics"},
        state={"token_capacity": token_capacity},
        content=f"Supervisor checking telemetry. Current local token capacity: {token_capacity}%"
    )

    # Robust parsing of prompt_text from types.Content or dictionary
    if hasattr(node_input, "parts") and node_input.parts:
        prompt_text = node_input.parts[0].text
    elif isinstance(node_input, dict):
        prompt_text = node_input.get("prompt", "")
    else:
        prompt_text = str(node_input)

    log_trail = f"[Supervisor] Ingested task: '{prompt_text}'\n"

    # Enforce TUI Rate Limiter simulation check (16KB limit)
    if len(prompt_text.encode("utf-8")) > 16384:
         yield Event(
             output=WorkflowOutput(
                 status="failure",
                 result="TUI Buffer Overflow Alert",
                 log_trail=log_trail + "[ALERT] Input exceeds 16KB TUI visualization limit. Truncated."
             )
         )
         return

    # Check for simulated malicious payload (Prompt Injection simulation)
    if "compromise" in prompt_text.lower() or "injection" in prompt_text.lower():
         yield Event(
             output={"status": "compromise_detected"},
             content="Probabilistic Agent Judge identified security compromise in prompt. Raising P2P Link Outage."
         )
         raise google.adk.ToolException("P2P_LINK_OUTAGE")

    # Determine fallback routing based on token thresholds
    # Thresholds: Depletion > 25% (Capacity <= 75%) triggers Kademlia DHT Discovery.
    # Depletion > 85% (Capacity <= 15%) triggers Pool 2 (P2P Barter Mesh).
    if token_capacity <= 15.0:
        # HITL Security Seal: Confirm transition to Pool 2 P2P barter mesh
        if "approve_p2p" not in ctx.resume_inputs:
            yield RequestInput(
                interrupt_id="approve_p2p",
                message="[CHECKPOINT] Local token capacity is critical (<= 15%). Confirm transition to Pool 2 (P2P Barter Mesh)? (yes/no)"
            )
            return
        
        user_response = ctx.resume_inputs["approve_p2p"]
        if str(user_response).strip().lower() != "yes":
            yield Event(output={"status": "rejected_by_user"}, content="P2P swap rejected by developer.")
            raise google.adk.ToolException("P2P_LINK_OUTAGE")

        log_trail += "[Pool 2] HITL Approved. Escalating to P2P Mesh overlay...\n"
        
        # Branch A: Kademlia Discovery
        log_trail += "[Branch A] Kernel Guardian executing DHT Node Discovery sweep...\n"
        await asyncio.sleep(0.1) # Simulate discovery
        
        # Branch B: Security sandbox payload execution
        log_trail += "[Branch B] Green Team Sandbox initializing zero-privilege gVisor containment (cgroupsv2: Memory=2GB, CPU=10%)...\n"
        await asyncio.sleep(0.1)
        
        # Exchange Auditor logs transactions
        audit_res = AUDITOR.record_compute_time("peer_buddy_node_1", 2.5, 250)
        log_trail += f"[Exchange Auditor] Parity updated: iteration {audit_res['iteration']}. Checkpoint saved: {audit_res['checkpoint_saved']}\n"
        
        final_result = f"Processed payload on remote peer: '{prompt_text}'"
        yield Event(
            output=WorkflowOutput(status="success", result=final_result, log_trail=log_trail),
            content="Task completed successfully via Pool 2 P2P mesh."
        )

    elif token_capacity <= 75.0:
        # Pool 1: Multi-Tenant Key Vault & Circuit Breaker
        log_trail += "[Pool 1] Rotation trigger activated (Quota <= 75%). Rotating keys...\n"
        
        # Crypto-Router selects alt keys
        rotate_res = await rotate_key_tool(provider="gemini")
        if rotate_res["status"] == "success":
            key_in_use = rotate_res["key"]
            log_trail += f"[Crypto-Router] Acquired active key: {key_in_use}\n"
            final_result = f"Processed payload locally using rotated key ({key_in_use}): '{prompt_text}'"
            yield Event(
                output=WorkflowOutput(status="success", result=final_result, log_trail=log_trail),
                content="Task completed locally using rotated credentials."
            )
        else:
            log_trail += f"[Crypto-Router] Rotation failed: {rotate_res['message']}. Escaping to P2P.\n"
            raise google.adk.ToolException("P2P_LINK_OUTAGE")
            
    else:
        # Default local execution
        log_trail += "[Default] processing task locally on primary token."
        final_result = f"Processed payload locally: '{prompt_text}'"
        yield Event(
            output=WorkflowOutput(status="success", result=final_result, log_trail=log_trail),
            content="Task completed locally on primary credential."
        )

@node()
def self_healing_node(ctx: Context, node_input: Any) -> Event:
    """Self-Healing Canvas Node.
    Triggers when google.adk.ToolException('P2P_LINK_OUTAGE') is caught.
    Safely routes task to local offline execution queue.
    """
    return Event(
        output=WorkflowOutput(
            status="self_healing_offline",
            result="Local Offline Queue Processed",
            log_trail="[SELF-HEALING] Caught P2P_LINK_OUTAGE. Applying exponential backoff. Swapping to local offline execution queue."
        ),
        content="P2P Link Outage recovered. Task completed via local offline queue."
    )

# Root supervisor graph workflow
root_agent = Workflow(
    name="quidproquota_agent",
    input_schema=WorkflowInput,
    output_schema=WorkflowOutput,
    edges=[
        Edge(from_node=START, to_node=supervisor_node),
        Edge(from_node=supervisor_node, to_node=self_healing_node, route="compromise_detected")
    ],
    rerun_on_resume=True
)
