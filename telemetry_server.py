import os
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("TelemetryServer")

SIMULATION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".telemetry_sim.json")

@mcp.tool()
def get_host_diagnostics() -> str:
    """Retrieve host telemetry metrics including CPU, RAM, GPU, VRAM, and Token status.
    
    Returns:
        A JSON string containing the diagnostic values.
    """
    token_capacity = 100.0
    cpu_usage = 12.0
    ram_usage = 8.5
    vram_usage = 0.0
    gpu_usage = 0.0

    if os.path.exists(SIMULATION_FILE):
        try:
            with open(SIMULATION_FILE, "r") as f:
                data = json.load(f)
                token_capacity = data.get("token_capacity_percent", token_capacity)
                cpu_usage = data.get("cpu_usage_percent", cpu_usage)
                ram_usage = data.get("ram_usage_gb", ram_usage)
                vram_usage = data.get("vram_usage_gb", vram_usage)
                gpu_usage = data.get("gpu_usage_percent", gpu_usage)
        except Exception:
            pass

    diagnostics = {
        "cpu_usage_percent": cpu_usage,
        "ram_usage_gb": ram_usage,
        "gpu_usage_percent": gpu_usage,
        "vram_usage_gb": vram_usage,
        "token_capacity_percent": token_capacity
    }
    return json.dumps(diagnostics)

if __name__ == "__main__":
    mcp.run()
