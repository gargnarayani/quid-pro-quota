import time
import asyncio
from typing import Dict, List, Optional
from google.adk.tools import ToolContext

# In-memory storage for blacklisted keys: key_name -> release_timestamp
BLACKLIST: Dict[str, float] = {}
BLACKLIST_DURATION = 300.0  # 300 seconds

# Mock key vault
KEY_VAULT: Dict[str, List[str]] = {
    "gemini": ["gemini_key_primary", "gemini_key_alt1", "gemini_key_alt2"],
    "openai": ["openai_key_primary", "openai_key_alt1"],
    "claude": ["claude_key_primary", "claude_key_alt1"]
}

# Index pointers for round-robin rotation
PROVIDER_INDEX: Dict[str, int] = {
    "gemini": 0,
    "openai": 0,
    "claude": 0
}

def blacklist_key(key: str):
    """Add a key to the 300-second blacklist."""
    BLACKLIST[key] = time.time() + BLACKLIST_DURATION

def is_blacklisted(key: str) -> bool:
    """Check if a key is currently blacklisted."""
    if key in BLACKLIST:
        if time.time() < BLACKLIST[key]:
            return True
        else:
            del BLACKLIST[key]  # Expired
    return False

async def lookup_key_with_timeout(provider: str, delay_ms: float = 0) -> str:
    """Look up an active key for a provider with a strict 2000ms timeout.
    
    Args:
        provider: The provider name ('gemini', 'openai', 'claude').
        delay_ms: Simulates key vault retrieval network latency.
        
    Returns:
        The selected key string.
        
    Raises:
        TimeoutError: If key retrieval takes longer than 2000ms.
        ValueError: If all keys for the provider are blacklisted or invalid.
    """
    async def perform_lookup():
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
            
        if provider not in KEY_VAULT:
            raise ValueError(f"Unknown provider: {provider}")
            
        keys = KEY_VAULT[provider]
        start_idx = PROVIDER_INDEX[provider]
        n_keys = len(keys)
        
        for i in range(n_keys):
            idx = (start_idx + i) % n_keys
            key = keys[idx]
            if not is_blacklisted(key):
                # Update rotation index for next run
                PROVIDER_INDEX[provider] = (idx + 1) % n_keys
                return key
                
        raise ValueError(f"All keys for provider '{provider}' are currently blacklisted.")

    try:
        # Enforce 2000ms safety timeout limit
        return await asyncio.wait_for(perform_lookup(), timeout=2.0)
    except asyncio.TimeoutError:
        raise TimeoutError("Credential lookup exceeded safety limit of 2000ms.")

async def rotate_key_tool(provider: str, simulate_delay_ms: float = 0, tool_context: Optional[ToolContext] = None) -> dict:
    """ADK-compatible tool to rotate and retrieve active credentials.
    
    Args:
        provider: The provider target ('gemini', 'openai', 'claude').
        simulate_delay_ms: Simulates lookup delay (for latency validation).
        
    Returns:
        A dict containing the status and retrieved key.
    """
    try:
        key = await lookup_key_with_timeout(provider, simulate_delay_ms)
        return {"status": "success", "provider": provider, "key": key}
    except Exception as e:
        return {"status": "error", "message": str(e)}
