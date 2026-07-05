import os
import sys
import json
import time
import asyncio
import argparse
import webbrowser
import threading
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from agent import root_agent, SIMULATION_FILE, ToolException
from tools.crypto_router import BLACKLIST, KEY_VAULT
from tools.exchange_auditor import AUDITOR

app_runner = FastAPI(title="Project QuidPro Quota Control Center")

# Wire the ADK App (name matches project directory 'quidproquota-agent')
adk_app = App(name="quidproquota-agent", root_agent=root_agent)

# TUI Stream Rate-Limiter State
class TUILimiter:
    def __init__(self):
        self.bytes_sent_in_last_second = 0
        self.window_start = time.time()
        self.limit_bytes_per_sec = 16384  # 16 KB/sec threshold

    def filter_chunk(self, chunk: str) -> tuple[str, bool]:
        """Filter inbound peer chunks to protect visualizer buffer.
        
        Returns:
            A tuple (filtered_chunk, is_truncated)
        """
        now = time.time()
        # Reset window every 1 second
        if now - self.window_start >= 1.0:
            self.bytes_sent_in_last_second = 0
            self.window_start = now

        chunk_bytes = len(chunk.encode("utf-8"))
        if self.bytes_sent_in_last_second + chunk_bytes > self.limit_bytes_per_sec:
            # Truncate chunk to fit within remaining limit
            allowed_bytes = max(0, self.limit_bytes_per_sec - self.bytes_sent_in_last_second)
            truncated_bytes = chunk.encode("utf-8")[:allowed_bytes]
            truncated_chunk = truncated_bytes.decode("utf-8", errors="ignore")
            self.bytes_sent_in_last_second += len(truncated_bytes)
            return truncated_chunk + " ... [TRUNCATED BY TUI LIMITER]", True
            
        self.bytes_sent_in_last_second += chunk_bytes
        return chunk, False

TUI_LIMITER = TUILimiter()

def set_simulated_token_capacity(percent: float, cpu=12.0, ram=8.5, gpu=0.0, vram=0.0, frame_drops=False):
    """Write simulated capacity levels to telemetry config file."""
    with open(SIMULATION_FILE, "w") as f:
        json.dump({
            "token_capacity_percent": percent,
            "cpu_usage_percent": cpu,
            "ram_usage_gb": ram,
            "gpu_usage_percent": gpu,
            "vram_usage_gb": vram,
            "simulate_frame_drops": frame_drops
        }, f)

# Seed initial simulation file
set_simulated_token_capacity(100.0)

# In-memory registry for WebSocket clients
ACTIVE_CONNECTIONS: list[WebSocket] = []

async def broadcast_telemetry(active_node: str = "IDLE"):
    """Broadcast state to all connected UI clients."""
    now = time.time()
    blacklist_status = []
    for k, v in list(BLACKLIST.items()):
        remaining = max(0, int(v - now))
        if remaining > 0:
            blacklist_status.append({"key": k, "remaining_seconds": remaining})
        else:
            BLACKLIST.pop(k, None)

    # Read simulation values
    token_capacity = 100.0
    cpu = 12.0
    ram = 8.5
    vram = 0.0
    gpu = 0.0
    frame_drops = False
    if os.path.exists(SIMULATION_FILE):
        try:
            with open(SIMULATION_FILE, "r") as f:
                data = json.load(f)
                token_capacity = data.get("token_capacity_percent", token_capacity)
                cpu = data.get("cpu_usage_percent", cpu)
                ram = data.get("ram_usage_gb", ram)
                vram = data.get("vram_usage_gb", vram)
                gpu = data.get("gpu_usage_percent", gpu)
                frame_drops = data.get("simulate_frame_drops", frame_drops)
        except Exception:
            pass

    msg = {
        "type": "telemetry",
        "cpu_usage_percent": cpu,
        "ram_usage_gb": ram,
        "gpu_usage_percent": gpu,
        "vram_usage_gb": vram,
        "token_capacity_percent": token_capacity,
        "simulate_frame_drops": frame_drops,
        "blacklist": blacklist_status,
        "vault": KEY_VAULT,
        "ledger": AUDITOR.ledger,
        "active_node": active_node
    }
    dead_connections = []
    for ws in ACTIVE_CONNECTIONS:
        try:
            await ws.send_json(msg)
        except Exception:
            dead_connections.append(ws)
    for dc in dead_connections:
        if dc in ACTIVE_CONNECTIONS:
            ACTIVE_CONNECTIONS.remove(dc)

async def run_chaos_test(test_type: str, ws: Optional[WebSocket] = None):
    """Execute chaos test runs and stream outcomes to WebSocket or stdout."""
    runner = InMemoryRunner(app=adk_app)
    session = await runner.session_service.create_session(app_name="quidproquota-agent", user_id="dev_user")
    
    # 1. Setup simulated environment state
    if test_type == "healthy":
        set_simulated_token_capacity(100.0, cpu=10.0, ram=8.0, gpu=0.0, vram=0.0)
        prompt = "Healthy local execution request"
    elif test_type == "key_rotation" or test_type == "429":
        set_simulated_token_capacity(50.0, cpu=15.0, ram=8.2, gpu=5.0, vram=0.1)
        prompt = "Trigger alternate key rotation"
    elif test_type == "p2p_hitl_approved":
        set_simulated_token_capacity(10.0, cpu=45.0, ram=9.5, gpu=60.0, vram=2.4)
        prompt = "P2P clearing task payload"
        await runner.session_service.update_session_state(
            app_name="quidproquota-agent",
            session_id=session.id,
            state_delta={"resume_inputs": {"approve_p2p": "yes"}}
        )
    elif test_type == "p2p_hitl_rejected":
        set_simulated_token_capacity(10.0, cpu=40.0, ram=9.3, gpu=55.0, vram=2.2)
        prompt = "P2P barter task payload"
        await runner.session_service.update_session_state(
            app_name="quidproquota-agent",
            session_id=session.id,
            state_delta={"resume_inputs": {"approve_p2p": "no"}}
        )
    elif test_type == "buffer_overflow" or test_type == "overload":
        set_simulated_token_capacity(100.0, cpu=12.0, ram=8.4, gpu=0.0, vram=0.0)
        # Construct large payload to exceed 16KB/s visualization buffer threshold
        prompt = "STREAM_INGESTION_OVERFLOW_" + ("X" * 25000)
    elif test_type == "malicious_payload" or test_type == "malicious":
        set_simulated_token_capacity(100.0, cpu=14.0, ram=8.6, gpu=0.0, vram=0.0)
        prompt = "malicious compromise script trigger cgroupsv2 freeze quarantine"
    else:
        return

    # Helper to send log messages
    async def log_out(text: str, is_alert: bool = False):
        if ws:
            await ws.send_json({"type": "log", "message": text, "is_alert": is_alert})
        else:
            print(f"Log: {text}")

    await log_out(f"=== Starting Chaos Run: {test_type} ===")
    
    # Simulate network frame drop latency if enabled
    if os.path.exists(SIMULATION_FILE):
        try:
            with open(SIMULATION_FILE, "r") as f:
                sim_data = json.load(f)
                if sim_data.get("simulate_frame_drops", False):
                    await log_out("[CHAOS HARNESS] Simulating frame drop. Artificial socket latency injected (+1000ms)...")
                    await asyncio.sleep(1.0)
        except Exception:
            pass

    await log_out(f"Dispatched Payload size: {len(prompt.encode('utf-8'))} bytes")

    content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    
    try:
        # Route visually in sub-agent graph layout
        await broadcast_telemetry("SUPERVISOR")
        await log_out("[Graph Node] Transitioned to Cognitive Supervisor Node.")
        
        # Check rate limits before graph processes
        if len(prompt.encode("utf-8")) > 16384:
            await log_out("[TUI LIMITER] Rate-limit check active: payload exceeds 16KB limit.", is_alert=True)
            # Filter and truncate visualization
            filtered, is_trunc = TUI_LIMITER.filter_chunk(prompt)
            await log_out(f"[TUI Stream] Inbound visualization: {filtered[:200]}...", is_alert=is_trunc)
        
        async for event in runner.run_async(
            user_id="dev_user",
            session_id=session.id,
            new_message=content
        ):
            # Check capacity to route telemetry highlight
            if os.path.exists(SIMULATION_FILE):
                try:
                    with open(SIMULATION_FILE, "r") as f:
                        sim_cap = json.load(f).get("token_capacity_percent", 100.0)
                        if sim_cap <= 15.0:
                            await broadcast_telemetry("BRANCH_B")
                        elif sim_cap <= 75.0:
                            await broadcast_telemetry("BRANCH_A")
                except Exception:
                    pass

            if event.output is not None:
                output_str = json.dumps(event.output) if not isinstance(event.output, str) else event.output
                filtered, truncated = TUI_LIMITER.filter_chunk(output_str)
                await log_out(f"Workflow Event: {filtered}", is_alert=truncated)
                
    except ToolException as e:
        await broadcast_telemetry("SELF_HEALING")
        await log_out(f"[SELF-HEALING] Caught P2P_LINK_OUTAGE: {e}", is_alert=True)
        await log_out("[Graph Node] Transitioned to Self-Healing recovery edge.")
    except Exception as e:
        await log_out(f"Runtime Exception: {e}", is_alert=True)

    await broadcast_telemetry("IDLE")
    await log_out("Chaos Run complete.")

# Tailwind Dashboard HTML
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Project QuidPro Quota - Realtime Control Center</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        slate: {
                            950: '#07080c',
                            900: '#0d0e12',
                            800: '#15181e',
                        },
                        cyan: {
                            400: '#00f0ff',
                            500: '#06b6d4',
                        },
                        violet: {
                            500: '#7a00ff',
                        }
                    }
                }
            }
        }
    </script>
    <style>
        .glass-card {
            background: rgba(21, 24, 30, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(12px);
        }
        .text-glow {
            text-shadow: 0 0 10px rgba(0, 240, 255, 0.3);
        }
        .border-glow {
            box-shadow: 0 0 15px rgba(0, 240, 255, 0.15);
        }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-6 font-sans">

    <!-- Top Alert Ticker Banner -->
    <div id="ticker-banner" class="fixed top-0 left-0 w-full bg-gradient-to-r from-red-500 to-amber-500 text-white py-2.5 px-4 font-black uppercase text-center tracking-wider text-sm shadow-lg shadow-red-500/20 z-50 hidden transition-all duration-300">
        ⚠️ STREAM OVERLOAD ALERT: Visual buffer exceeded 16KB/s. Payload truncated. telemetric processing intact.
    </div>

    <!-- Header -->
    <header class="flex justify-between items-center pb-5 mb-6 border-b border-slate-800/80 mt-10">
        <div>
            <h1 class="text-3xl font-extrabold bg-gradient-to-r from-cyan-400 to-violet-500 bg-clip-text text-transparent tracking-wide text-glow">
                PROJECT QUIDPRO QUOTA
            </h1>
            <p class="text-xs text-slate-400 mt-1 uppercase tracking-widest font-semibold">ADK 2.0 Telemetry & Resource Routing Console</p>
        </div>
        <div class="flex items-center gap-3 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-4 py-2 rounded-full text-xs font-black tracking-wider uppercase">
            <span class="w-2.5 h-2.5 bg-emerald-500 rounded-full animate-ping"></span>
            Telemetry Agent Connected
        </div>
    </header>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <!-- System Diagnostics Panel -->
        <div class="glass-card rounded-xl p-5 border-glow">
            <h2 class="text-xs font-black text-cyan-400 uppercase tracking-widest border-b border-slate-800 pb-2 mb-4">
                System Diagnostics
            </h2>
            
            <div class="space-y-4">
                <div>
                    <div class="flex justify-between text-sm mb-1">
                        <span class="text-slate-300">Token Vault Quota</span>
                        <span id="capacity-val" class="font-bold text-cyan-400">100%</span>
                    </div>
                    <div class="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div id="capacity-bar" class="h-full bg-gradient-to-r from-cyan-400 to-violet-500 rounded-full transition-all duration-500" style="width: 100%"></div>
                    </div>
                </div>

                <div>
                    <div class="flex justify-between text-sm mb-1">
                        <span class="text-slate-300">CPU Core Allocation</span>
                        <span id="cpu-val" class="font-semibold text-slate-200">12%</span>
                    </div>
                    <div class="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div id="cpu-bar" class="h-full bg-emerald-500 rounded-full transition-all duration-500" style="width: 12%"></div>
                    </div>
                </div>

                <div>
                    <div class="flex justify-between text-sm mb-1">
                        <span class="text-slate-300">RAM Allocation</span>
                        <span id="ram-val" class="font-semibold text-slate-200">8.5 GB</span>
                    </div>
                    <div class="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div id="ram-bar" class="h-full bg-emerald-500 rounded-full transition-all duration-500" style="width: 53%"></div>
                    </div>
                </div>

                <div>
                    <div class="flex justify-between text-sm mb-1">
                        <span class="text-slate-300">GPU Core Load</span>
                        <span id="gpu-val" class="font-semibold text-slate-200">0%</span>
                    </div>
                    <div class="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div id="gpu-bar" class="h-full bg-emerald-500 rounded-full transition-all duration-500" style="width: 0%"></div>
                    </div>
                </div>

                <div>
                    <div class="flex justify-between text-sm mb-1">
                        <span class="text-slate-300">VRAM Allocation</span>
                        <span id="vram-val" class="font-semibold text-slate-200">0.0 GB</span>
                    </div>
                    <div class="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div id="vram-bar" class="h-full bg-emerald-500 rounded-full transition-all duration-500" style="width: 0%"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Multi-Agent Flow Viewer -->
        <div class="glass-card rounded-xl p-5 border-glow">
            <h2 class="text-xs font-black text-cyan-400 uppercase tracking-widest border-b border-slate-800 pb-2 mb-4">
                Multi-Agent Flow Canvas
            </h2>
            
            <div class="flex flex-col items-center justify-center space-y-4 py-3">
                <!-- Start Node -->
                <div id="node-START" class="w-32 py-2 text-center text-xs font-bold border border-slate-700 bg-slate-800/40 rounded-lg transition-all duration-300">
                    START
                </div>
                <div class="w-0.5 h-4 bg-slate-800"></div>

                <!-- Supervisor Node -->
                <div id="node-SUPERVISOR" class="w-48 py-2 text-center text-xs font-bold border border-slate-700 bg-slate-800/40 rounded-lg transition-all duration-300">
                    COGNITIVE SUPERVISOR
                </div>
                
                <div class="flex items-center gap-10 w-full justify-center">
                    <div class="flex flex-col items-center">
                        <div class="w-0.5 h-4 bg-slate-800"></div>
                        <div id="node-BRANCH_A" class="w-36 py-2 text-center text-xs font-bold border border-slate-700 bg-slate-800/40 rounded-lg transition-all duration-300">
                            BRANCH A<br><span class="text-[10px] text-slate-400">Operations Pool</span>
                        </div>
                    </div>
                    
                    <div class="flex flex-col items-center">
                        <div class="w-0.5 h-4 bg-slate-800"></div>
                        <div id="node-BRANCH_B" class="w-36 py-2 text-center text-xs font-bold border border-slate-700 bg-slate-800/40 rounded-lg transition-all duration-300">
                            BRANCH B<br><span class="text-[10px] text-slate-400">Security Sandbox</span>
                        </div>
                    </div>
                </div>

                <div class="w-0.5 h-4 bg-slate-800"></div>
                <!-- Self-Healing Node -->
                <div id="node-SELF_HEALING" class="w-40 py-2 text-center text-xs font-bold border border-slate-700 bg-slate-800/40 rounded-lg transition-all duration-300">
                    SELF-HEALING EDGE
                </div>
            </div>
        </div>

        <!-- Chaos Harness Panel -->
        <div class="glass-card rounded-xl p-5 border-glow">
            <h2 class="text-xs font-black text-cyan-400 uppercase tracking-widest border-b border-slate-800 pb-2 mb-4">
                Chaos Control Harness
            </h2>
            
            <div class="space-y-4">
                <div class="flex items-center gap-4">
                    <span class="text-xs font-medium text-slate-400 w-32">Quota Capacity:</span>
                    <input type="range" id="sim-capacity" min="0" max="100" value="100" class="flex-grow accent-cyan-400" oninput="updateSimState()">
                    <span id="sim-cap-label" class="text-xs text-cyan-400 font-bold w-8 text-right">100%</span>
                </div>

                <div class="flex items-center gap-4">
                    <span class="text-xs font-medium text-slate-400 w-32">CPU load limit:</span>
                    <input type="range" id="sim-cpu" min="0" max="100" value="12" class="flex-grow accent-cyan-400" oninput="updateSimState()">
                    <span id="sim-cpu-label" class="text-xs text-cyan-400 font-bold w-8 text-right">12%</span>
                </div>

                <div class="flex items-center gap-4 border-t border-slate-800/60 pt-3">
                    <span class="text-xs font-medium text-slate-400">Simulate Frame Drops:</span>
                    <input type="checkbox" id="sim-frame-drops" class="accent-cyan-400" onchange="updateSimState()">
                </div>

                <div class="border-t border-slate-800/60 pt-4 mt-2">
                    <p class="text-xs font-bold text-violet-400 mb-2.5">Simulate Scenario Failures:</p>
                    <div class="grid grid-cols-3 gap-2">
                        <button onclick="runTest('healthy')" class="text-xs font-bold border border-slate-700 bg-slate-800/30 py-2.5 rounded-lg hover:bg-cyan-400 hover:text-slate-950 hover:border-cyan-400 transition-all duration-200">
                            Healthy Run
                        </button>
                        <button onclick="runTest('429')" class="text-xs font-bold border border-red-500/20 bg-red-950/10 text-red-400 py-2.5 rounded-lg hover:bg-red-500 hover:text-white hover:border-red-500 transition-all duration-200">
                            API 429
                        </button>
                        <button onclick="runTest('overload')" class="text-xs font-bold border border-amber-500/20 bg-amber-950/10 text-amber-400 py-2.5 rounded-lg hover:bg-amber-500 hover:text-white hover:border-amber-500 transition-all duration-200">
                            Overload
                        </button>
                    </div>
                    <div class="grid grid-cols-3 gap-2 mt-2">
                        <button onclick="runTest('p2p_hitl_approved')" class="text-xs font-bold border border-slate-700 bg-slate-800/30 py-2.5 rounded-lg hover:bg-cyan-400 hover:text-slate-950 hover:border-cyan-400 transition-all duration-200">
                            P2P Accept
                        </button>
                        <button onclick="runTest('p2p_hitl_rejected')" class="text-xs font-bold border border-slate-700 bg-slate-800/30 py-2.5 rounded-lg hover:bg-cyan-400 hover:text-slate-950 hover:border-cyan-400 transition-all duration-200">
                            P2P Reject
                        </button>
                        <button onclick="runTest('malicious')" class="text-xs font-bold border border-red-500/20 bg-red-950/10 text-red-400 py-2.5 rounded-lg hover:bg-red-500 hover:text-white hover:border-red-500 transition-all duration-200">
                            Injection
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <!-- Credential vault matrix -->
        <div class="glass-card rounded-xl p-5 border-glow">
            <h2 class="text-xs font-black text-cyan-400 uppercase tracking-widest border-b border-slate-800 pb-2 mb-4">
                Vault Rotation & Blacklist Cooling Matrix
            </h2>
            
            <div id="blacklist-container" class="space-y-2 mb-4">
                <p class="text-xs text-slate-400">Vault healthy. Cooldown array empty.</p>
            </div>
            
            <div class="border-t border-slate-800/60 pt-4">
                <p class="text-xs font-bold text-violet-400 mb-2">Vault Allocation Pools:</p>
                <div id="vault-pools" class="text-xs text-slate-300 space-y-1"></div>
            </div>
        </div>

        <!-- Ledger ledger panel -->
        <div class="glass-card rounded-xl p-5 border-glow">
            <h2 class="text-xs font-black text-cyan-400 uppercase tracking-widest border-b border-slate-800 pb-2 mb-4">
                Exchange Accounting Parity
            </h2>
            
            <div class="grid grid-cols-2 gap-4">
                <div class="bg-slate-900/50 p-4 rounded-lg border border-slate-800">
                    <p class="text-xs text-slate-400 uppercase tracking-wider">Total Tokens Settled</p>
                    <p id="ledger-tokens" class="text-3xl font-black mt-1 text-slate-200">0</p>
                </div>
                <div class="bg-slate-900/50 p-4 rounded-lg border border-slate-800">
                    <p class="text-xs text-slate-400 uppercase tracking-wider">Accumulated Credits</p>
                    <p id="ledger-credits" class="text-3xl font-black mt-1 text-emerald-400">0.0</p>
                </div>
            </div>
            
            <p class="text-[11px] text-slate-400 mt-4 leading-relaxed">
                * Zero-Trust Stateless Checkpoints: Persisting signed JSON state snapshots to secure stream path every 10 ledger transactions (incorporating GCP KMS signatures).
            </p>
        </div>
    </div>

    <!-- Live Director's Log Trace Stream -->
    <div class="glass-card rounded-xl p-5 border-glow">
        <h2 class="text-xs font-black text-cyan-400 uppercase tracking-widest border-b border-slate-800 pb-2 mb-4">
            Live Director's log & Trace Stream
        </h2>
        
        <div id="terminal" class="bg-slate-950 p-4 rounded-lg h-60 overflow-y-auto font-mono text-xs text-emerald-400 space-y-2 border border-slate-900">
            <div class="text-slate-500">> Telemetry stream listening. System diagnostics ready.</div>
        </div>
    </div>

    <script>
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

        socket.onmessage = function(event) {
            const data = JSON.parse(event.data);
            
            if (data.type === "telemetry") {
                updateTelemetryUI(data);
            } else if (data.type === "log") {
                addLogLine(data.message, data.is_alert);
            }
        };

        function updateTelemetryUI(data) {
            // Update gauges
            document.getElementById("capacity-val").textContent = data.token_capacity_percent + "%";
            document.getElementById("capacity-bar").style.width = data.token_capacity_percent + "%";
            
            const capBar = document.getElementById("capacity-bar");
            if (data.token_capacity_percent <= 15) {
                capBar.className = "h-full bg-red-500 rounded-full transition-all duration-500";
            } else {
                capBar.className = "h-full bg-gradient-to-r from-cyan-400 to-violet-500 rounded-full transition-all duration-500";
            }

            document.getElementById("cpu-val").textContent = data.cpu_usage_percent.toFixed(1) + "%";
            document.getElementById("cpu-bar").style.width = data.cpu_usage_percent + "%";

            document.getElementById("ram-val").textContent = data.ram_usage_gb.toFixed(1) + " GB";
            document.getElementById("ram-bar").style.width = (data.ram_usage_gb / 16.0 * 100.0) + "%";

            document.getElementById("gpu-val").textContent = data.gpu_usage_percent.toFixed(1) + "%";
            document.getElementById("gpu-bar").style.width = data.gpu_usage_percent + "%";

            document.getElementById("vram-val").textContent = data.vram_usage_gb.toFixed(1) + " GB";
            document.getElementById("vram-bar").style.width = (data.vram_usage_gb / 12.0 * 100.0) + "%";

            // Update ledger
            document.getElementById("ledger-tokens").textContent = data.ledger.total_tokens_consumed;
            document.getElementById("ledger-credits").textContent = data.ledger.credits_earned.toFixed(1);

            // Update Graph Flow Highlighting
            const flowNodes = ["START", "SUPERVISOR", "BRANCH_A", "BRANCH_B", "SELF_HEALING"];
            flowNodes.forEach(node => {
                const element = document.getElementById("node-" + node);
                if (data.active_node === node) {
                    element.className = "w-32 py-2 text-center text-xs font-bold border border-cyan-400 bg-cyan-950/40 text-cyan-200 shadow-[0_0_15px_rgba(0,240,255,0.4)] rounded-lg transition-all duration-300";
                    if (node === "SUPERVISOR" || node === "SELF_HEALING") element.className = element.className.replace("w-32", "w-48");
                    if (node === "BRANCH_A" || node === "BRANCH_B") element.className = element.className.replace("w-32", "w-36");
                } else {
                    element.className = "w-32 py-2 text-center text-xs font-bold border border-slate-700 bg-slate-800/40 rounded-lg transition-all duration-300";
                    if (node === "SUPERVISOR" || node === "SELF_HEALING") element.className = element.className.replace("w-32", "w-48");
                    if (node === "BRANCH_A" || node === "BRANCH_B") element.className = element.className.replace("w-32", "w-36");
                }
            });

            // Update Blacklist
            const blContainer = document.getElementById("blacklist-container");
            if (data.blacklist.length === 0) {
                blContainer.innerHTML = `<p class="text-xs text-slate-400">Vault healthy. Cooldown array empty.</p>`;
            } else {
                let blHtml = "";
                data.blacklist.forEach(item => {
                    blHtml += `
                        <div class="flex justify-between bg-red-950/20 border border-red-500/20 px-3 py-2 rounded-lg text-xs">
                            <span class="font-bold text-red-400">${item.key}</span>
                            <span class="text-red-500 font-semibold">${item.remaining_seconds}s cooling</span>
                        </div>
                    `;
                });
                blContainer.innerHTML = blHtml;
            }

            // Update Vault Configurations
            const pools = document.getElementById("vault-pools");
            let poolsHtml = "";
            for (let provider in data.vault) {
                poolsHtml += `<div class="mb-1"><strong>${provider}</strong>: ${data.vault[provider].join(", ")}</div>`;
            }
            pools.innerHTML = poolsHtml;

            // Sync simulation checkboxes/sliders
            document.getElementById("sim-capacity").value = data.token_capacity_percent;
            document.getElementById("sim-cap-label").textContent = data.token_capacity_percent + "%";
            document.getElementById("sim-cpu").value = data.cpu_usage_percent;
            document.getElementById("sim-cpu-label").textContent = Math.round(data.cpu_usage_percent) + "%";
            document.getElementById("sim-frame-drops").checked = data.simulate_frame_drops;
        }

        function addLogLine(text, isAlert) {
            const term = document.getElementById("terminal");
            const div = document.createElement("div");
            if (isAlert) {
                div.className = "text-red-400 font-bold border-l-2 border-red-500 pl-2 py-0.5";
            } else {
                div.className = "text-emerald-400";
            }
            div.textContent = "> " + text;
            term.appendChild(div);
            term.scrollTop = term.scrollHeight;

            const ticker = document.getElementById("ticker-banner");
            if (text.includes("TRUNCATED BY TUI LIMITER")) {
                ticker.classList.remove("hidden");
                setTimeout(() => {
                    ticker.classList.add("hidden");
                }, 8000);
            }
        }

        function updateSimState() {
            const capacity = parseFloat(document.getElementById("sim-capacity").value);
            const cpu = parseFloat(document.getElementById("sim-cpu").value);
            const frameDrops = document.getElementById("sim-frame-drops").checked;
            
            document.getElementById("sim-cap-label").textContent = capacity + "%";
            document.getElementById("sim-cpu-label").textContent = cpu + "%";

            socket.send(JSON.stringify({
                action: "set_simulation",
                token_capacity: capacity,
                cpu: cpu,
                frame_drops: frameDrops
            }));
        }

        function runTest(testType) {
            addLogLine(`[Harness] Launching simulation run: ${testType}`, false);
            socket.send(JSON.stringify({
                action: "run_test",
                test_type: testType
            }));
        }
    </script>
</body>
</html>
"""

@app_runner.get("/", response_class=HTMLResponse)
async def get_dashboard():
    return DASHBOARD_HTML

@app_runner.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ACTIVE_CONNECTIONS.append(websocket)
    try:
        await broadcast_telemetry()
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            action = payload.get("action")
            
            if action == "set_simulation":
                capacity = payload.get("token_capacity", 100.0)
                cpu = payload.get("cpu", 12.0)
                frame_drops = payload.get("frame_drops", False)
                ram = 8.5 + (cpu / 20.0)
                gpu = 0.0 if capacity > 15.0 else 60.0
                vram = 0.0 if capacity > 15.0 else 2.5
                set_simulated_token_capacity(capacity, cpu, ram, gpu, vram, frame_drops)
                await broadcast_telemetry()
                
            elif action == "run_test":
                test_type = payload.get("test_type")
                asyncio.create_task(run_chaos_test(test_type, websocket))
                
    except WebSocketDisconnect:
        if websocket in ACTIVE_CONNECTIONS:
            ACTIVE_CONNECTIONS.remove(websocket)

async def periodic_telemetry_broadcast():
    """Periodically check and push updates."""
    while True:
        try:
            await broadcast_telemetry()
        except Exception:
            pass
        await asyncio.sleep(1.0)

# Launch background task for broadcasting telemetry and auto-launch
@app_runner.on_event("startup")
async def startup_event():
    asyncio.create_task(periodic_telemetry_broadcast())
    
    # Launch Google Chrome browser directly to http://127.0.0.1:8080
    def open_browser():
        time.sleep(1.5)
        print("Launching dashboard in browser at http://127.0.0.1:8080...")
        webbrowser.open('http://127.0.0.1:8080')
    
    threading.Thread(target=open_browser, daemon=True).start()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QuidPro Quota Run Harness")
    parser.add_argument("--healthy", action="store_true", help="Run healthy scenario test")
    parser.add_argument("--key_rotation", action="store_true", help="Run key rotation test")
    parser.add_argument("--p2p_hitl_approved", action="store_true", help="Run P2P barter mesh approved test")
    parser.add_argument("--p2p_hitl_rejected", action="store_true", help="Run P2P barter mesh rejected test")
    parser.add_argument("--buffer_overflow", action="store_true", help="Run stream buffer overload limit test")
    parser.add_argument("--malicious_payload", action="store_true", help="Run malicious prompt injection check")
    args = parser.parse_args()

    # Determine command invocation mode
    is_cli_run = any([
        args.healthy, args.key_rotation, args.p2p_hitl_approved,
        args.p2p_hitl_rejected, args.buffer_overflow, args.malicious_payload
    ])

    if is_cli_run:
        # CLI Chaos Execution mode
        if args.healthy:
            asyncio.run(run_chaos_test("healthy"))
        elif args.key_rotation:
            asyncio.run(run_chaos_test("key_rotation"))
        elif args.p2p_hitl_approved:
            asyncio.run(run_chaos_test("p2p_hitl_approved"))
        elif args.p2p_hitl_rejected:
            asyncio.run(run_chaos_test("p2p_hitl_rejected"))
        elif args.buffer_overflow:
            asyncio.run(run_chaos_test("buffer_overflow"))
        elif args.malicious_payload:
            asyncio.run(run_chaos_test("malicious_payload"))
    else:
        # Startup server on port 8080
        print("Starting Project QuidPro Quota Dashboard Server on port 8080...")
        uvicorn.run(app_runner, host="127.0.0.1", port=8080)
