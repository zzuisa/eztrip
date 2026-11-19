"""External, versioned multi-agent configuration with safe built-in fallback."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml

ROOT = Path(os.getenv("EZTRIP_AGENT_CONFIG_DIR", "/app/agent-config"))

def _read(name: str) -> dict[str, Any]:
    try:
        with (ROOT / name).open(encoding="utf-8") as f:
            value = yaml.safe_load(f) or {}
        return value if isinstance(value, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}

AGENTS = _read("agents.yaml").get("agents", {})
MODEL_ALIASES = {
    "travel-fast": os.getenv("LLM_AGENT_MODEL_FAST", "deepseek-v3.2"),
    "travel-reasoning": os.getenv("LLM_AGENT_MODEL_REASONING", "deepseek-v3.2"),
    "travel-tool": os.getenv("LLM_AGENT_MODEL_TOOL", "deepseek-v3.2"),
}

def agent(name: str) -> dict[str, Any]:
    value = AGENTS.get(name, {})
    return value if isinstance(value, dict) else {}

def model(name: str, default: str) -> str:
    value = agent(name).get("model")
    selected = str(value).strip() if value else default
    return MODEL_ALIASES.get(selected, selected)

def prompt(name: str, default: str) -> str:
    return default
