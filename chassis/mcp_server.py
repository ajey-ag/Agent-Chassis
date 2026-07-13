"""MCP server wrapper around the same ToolRegistry the agent uses.

Run:  python -m chassis.mcp_server          (stdio transport)
Then point any MCP client (Claude Desktop, Claude Code, etc.) at it.

Tradeoffs vs. the native Python registry, inline as promised:
  + MCP makes the SAME tools usable from any MCP-speaking client without
    writing another integration -- the registry is defined once.
  + Process isolation: a crashing tool takes down the MCP server process,
    not your agent.
  - Latency: every call crosses a process boundary and a JSON-RPC hop;
    in-process registry calls are a plain function call.
  - MCP has no concept of our permission tiers, so exposure policy must be
    enforced HERE: we only expose tier-1 and tier-2 tools over MCP. Tier-3
    tools are omitted entirely, because an external MCP client bypasses our
    approval queue -- the dashboard is the only path to tier-3 execution.
"""
from __future__ import annotations

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import load_config
from .logging_setup import init_event_log, log_event
from .tools.builtin import build_default_registry


def build_server(config=None) -> Server:
    config = config or load_config()
    init_event_log(config.data_dir)
    registry = build_default_registry(config)
    server = Server("agent-chassis-tools")

    exposed = [s for s in registry.specs() if config.tier_for(s.name) <= 2]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(name=s.name, description=s.description, inputSchema=s.parameters)
                for s in exposed]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if config.tier_for(name) >= 3 or not registry.has(name):
            return [TextContent(type="text", text=f"ERROR: tool '{name}' is not exposed over MCP.")]
        log_event("mcp_tool_call", tool=name, arguments=arguments, tier=config.tier_for(name))
        try:
            result = registry.call(name, arguments)
        except Exception as e:  # noqa: BLE001
            result = f"ERROR: {e}"
        return [TextContent(type="text", text=result)]

    return server


async def _main() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_main)
