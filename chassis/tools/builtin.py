"""Starter tools. Each is a plain function; the registry builds schemas from
the type hints and docstrings automatically.

Safety notes baked into the tools themselves (defense in depth -- the tier
system gates *whether* a tool runs, these constraints limit *what* it can do
once running):
  - write_file is jailed to the sandbox directory
  - shell_exec has a hard timeout and runs in the sandbox cwd
  - http_request (non-GET) is separate from http_get so they can sit in
    different tiers
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import httpx

from ..config import Config
from .registry import ToolRegistry


def build_default_registry(config: Config) -> ToolRegistry:
    registry = ToolRegistry()
    sandbox = config.sandbox_dir.resolve()
    sandbox.mkdir(exist_ok=True)

    @registry.register
    def web_search(query: str, max_results: int = 5) -> str:
        """Search the web (DuckDuckGo) and return titles, URLs and snippets.

        Args:
            query: The search query.
            max_results: Number of results to return (1-10).
        """
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # older package name
        results = list(DDGS().text(query, max_results=min(max_results, 10)))
        if not results:
            return "No results found."
        return "\n\n".join(
            f"{i+1}. {r.get('title')}\n   {r.get('href')}\n   {r.get('body', '')[:300]}"
            for i, r in enumerate(results)
        )

    @registry.register
    def read_file(path: str) -> str:
        """Read a local text file and return its contents (truncated to 20000 chars).

        Args:
            path: Absolute or sandbox-relative file path.
        """
        p = Path(path)
        if not p.is_absolute():
            p = sandbox / p
        text = p.read_text(encoding="utf-8", errors="replace")
        return text[:20000] + ("\n...[truncated]" if len(text) > 20000 else "")

    @registry.register
    def write_file(path: str, content: str) -> str:
        """Write content to a file inside the sandbox output directory.
        Paths are always resolved inside the sandbox; escaping it is refused.

        Args:
            path: File path relative to the sandbox directory.
            content: Full text content to write.
        """
        target = (sandbox / path).resolve()
        if not target.is_relative_to(sandbox):
            return "ERROR: path escapes the sandbox directory; refused."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {target}"

    @registry.register
    def shell_exec(command: str, timeout_seconds: int = 30) -> str:
        """Execute a shell command in the sandbox directory and return stdout+stderr.

        Args:
            command: The shell command to run.
            timeout_seconds: Kill the command after this many seconds (max 120).
        """
        try:
            proc = subprocess.run(
                command, shell=True, cwd=sandbox, capture_output=True, text=True,
                timeout=min(timeout_seconds, 120),
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: command timed out after {timeout_seconds}s"
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        return f"[exit {proc.returncode}]\n{out[:20000]}"

    @registry.register
    def http_get(url: str) -> str:
        """Fetch a URL with HTTP GET and return the response body (truncated).

        Args:
            url: The URL to fetch.
        """
        resp = httpx.get(url, timeout=30, follow_redirects=True,
                         headers={"User-Agent": "agent-chassis/1.0"})
        return f"[{resp.status_code}] {resp.text[:20000]}"

    @registry.register
    def http_request(method: str, url: str, body: str = "", content_type: str = "application/json") -> str:
        """Send a non-GET HTTP request (POST/PUT/DELETE/PATCH). Can mutate
        external state, which is why it is tier-gated separately from http_get.

        Args:
            method: HTTP method (POST, PUT, DELETE, PATCH).
            url: The URL to send the request to.
            body: Raw request body.
            content_type: Content-Type header value.
        """
        resp = httpx.request(method.upper(), url, content=body or None, timeout=30,
                             headers={"Content-Type": content_type, "User-Agent": "agent-chassis/1.0"})
        return f"[{resp.status_code}] {resp.text[:20000]}"

    return registry
