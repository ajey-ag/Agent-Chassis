"""Config loading: YAML file + .env, merged into one typed object.

Design: the YAML is the single source of truth for behavior (fallback order,
tiers, models); .env holds only secrets. ${VAR} interpolation is deliberately
NOT supported inside the YAML -- secrets are looked up by env-var *name*
(api_key_env) so the config file can be committed safely.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "config.yaml"

load_dotenv(ROOT / ".env")


@dataclass
class ProviderConfig:
    name: str
    kind: str                    # "gemini" | "openai_compat"
    model: str
    base_url: str
    api_key_env: str = ""
    max_context_tokens: int | None = None

    @property
    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env) or None

    @property
    def is_configured(self) -> bool:
        """A provider with no key requirement (local ollama) is always configured."""
        return not self.api_key_env or bool(self.api_key)


@dataclass
class Config:
    raw: dict[str, Any]
    fallback_order: list[str]
    providers: dict[str, ProviderConfig]
    failure_threshold: int
    cooldown_seconds: int
    max_iterations: int
    system_prompt_extra: str
    tool_tiers: dict[str, int]
    sandbox_dir: Path
    data_dir: Path
    config_path: Path = field(default=DEFAULT_CONFIG_PATH)

    def tier_for(self, tool_name: str) -> int:
        # Default to tier 3 (approval required) for anything not explicitly listed.
        return int(self.tool_tiers.get(tool_name, 3))

    def save_tool_tier(self, tool_name: str, tier: int) -> None:
        """Persist a tier change back to the YAML so it survives restarts."""
        self.tool_tiers[tool_name] = tier
        self.raw.setdefault("tool_tiers", {})[tool_name] = tier
        self.config_path.write_text(yaml.safe_dump(self.raw, sort_keys=False), encoding="utf-8")

    def save_fallback_order(self, order: list[str]) -> None:
        unknown = [p for p in order if p not in self.providers]
        if unknown:
            raise ValueError(f"Unknown providers: {unknown}")
        self.fallback_order = order
        self.raw["router"]["fallback_order"] = order
        self.config_path.write_text(yaml.safe_dump(self.raw, sort_keys=False), encoding="utf-8")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    providers = {
        name: ProviderConfig(
            name=name,
            kind=p["kind"],
            model=p["model"],
            base_url=p["base_url"].rstrip("/"),
            api_key_env=p.get("api_key_env") or "",
            max_context_tokens=p.get("max_context_tokens"),
        )
        for name, p in raw.get("providers", {}).items()
    }

    cb = raw.get("router", {}).get("circuit_breaker", {})
    paths = raw.get("paths", {})
    sandbox = ROOT / paths.get("sandbox_dir", "sandbox")
    data = ROOT / paths.get("data_dir", "data")
    sandbox.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)

    return Config(
        raw=raw,
        fallback_order=list(raw.get("router", {}).get("fallback_order", [])),
        providers=providers,
        failure_threshold=int(cb.get("failure_threshold", 3)),
        cooldown_seconds=int(cb.get("cooldown_seconds", 120)),
        max_iterations=int(raw.get("agent", {}).get("max_iterations", 15)),
        system_prompt_extra=raw.get("agent", {}).get("system_prompt_extra", "") or "",
        tool_tiers={k: int(v) for k, v in (raw.get("tool_tiers") or {}).items()},
        sandbox_dir=sandbox,
        data_dir=data,
        config_path=path,
    )
