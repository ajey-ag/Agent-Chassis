"""ToolRegistry: plain Python functions -> JSON-Schema tool specs.

A tool is just a type-hinted function with a Google-style docstring. The
registry introspects hints + docstring to build the JSON Schema the LLM
sees, so there is exactly one source of truth (the function itself) and no
separate schema files to drift out of sync.

Permission tiers (from config.yaml, default 3):
  1 auto-run | 2 auto-run + prominent log | 3 queued for human approval
The registry only *reports* the tier; enforcement lives in the agent loop,
so the same registry can be exposed over MCP without duplicating policy.
"""
from __future__ import annotations

import inspect
import re
import typing
from dataclasses import dataclass
from typing import Any, Callable

from ..llm.schema import ToolSpec

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean",
               list: "array", dict: "object"}


def _annotation_to_schema(ann: Any) -> dict:
    origin = typing.get_origin(ann)
    if origin is typing.Union or str(origin) == "types.UnionType":  # Optional[X] / X | None
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        return _annotation_to_schema(args[0]) if args else {"type": "string"}
    if origin in (list, typing.List):
        args = typing.get_args(ann)
        item = _annotation_to_schema(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item}
    if origin in (dict, typing.Dict):
        return {"type": "object"}
    if origin is typing.Literal:
        return {"type": "string", "enum": list(typing.get_args(ann))}
    return {"type": _PY_TO_JSON.get(ann, "string")}


def _parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Returns (description, {param: description}) from a Google-style docstring."""
    if not doc:
        return "", {}
    lines = doc.strip().splitlines()
    desc_lines: list[str] = []
    params: dict[str, str] = {}
    in_args = False
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if re.match(r"^(Args|Arguments|Parameters)\s*:\s*$", stripped):
            in_args = True
            continue
        if re.match(r"^(Returns|Raises|Yields|Examples?)\s*:\s*$", stripped):
            in_args = False
            continue
        if in_args:
            m = re.match(r"^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$", stripped)
            if m:
                current = m.group(1)
                params[current] = m.group(2)
            elif current and stripped:
                params[current] += " " + stripped
        else:
            desc_lines.append(stripped)
    description = " ".join(l for l in desc_lines if l).strip()
    return description, params


@dataclass
class RegisteredTool:
    name: str
    fn: Callable
    spec: ToolSpec


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, fn: Callable | None = None, *, name: str | None = None):
        """Usable as @registry.register or @registry.register(name=...)."""
        def deco(f: Callable):
            tool_name = name or f.__name__
            doc_desc, param_docs = _parse_docstring(inspect.getdoc(f) or "")
            sig = inspect.signature(f)
            hints = typing.get_type_hints(f)
            props: dict[str, dict] = {}
            required: list[str] = []
            for pname, param in sig.parameters.items():
                if pname in ("self", "cls"):
                    continue
                schema = _annotation_to_schema(hints.get(pname, str))
                if pname in param_docs:
                    schema["description"] = param_docs[pname]
                props[pname] = schema
                if param.default is inspect.Parameter.empty:
                    required.append(pname)
                else:
                    schema["default"] = param.default if not callable(param.default) else None
            spec = ToolSpec(
                name=tool_name,
                description=doc_desc or f"Tool {tool_name}",
                parameters={"type": "object", "properties": props, "required": required},
            )
            self._tools[tool_name] = RegisteredTool(tool_name, f, spec)
            return f
        return deco(fn) if fn is not None else deco

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def has(self, name: str) -> bool:
        return name in self._tools

    def call(self, name: str, arguments: dict) -> str:
        """Execute a tool, always returning a string (what LLMs consume).
        Raises KeyError for unknown tools -- the agent loop turns that into
        a structured 'no such tool' message back to the model."""
        tool = self._tools[name]
        result = tool.fn(**arguments)
        return result if isinstance(result, str) else str(result)
