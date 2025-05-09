"""
OpenAI API Compatibility Module for CHUK MCP Runtime

This version builds **underscore‑style** wrappers whose *Python signatures*
match the remote tool schema so front‑ends (and OpenAI) always see the right
parameters.
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY, Tool

logger = logging.getLogger("chuk_mcp_runtime.common.openai_compatibility")
logger.addHandler(logging.NullHandler())

# ───────────────────────── helpers ──────────────────────────

def to_openai_compatible_name(name: str) -> str:
    """Replace dots with underscores and strip disallowed chars."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name.replace(".", "_"))


def from_openai_compatible_name(name: str) -> str:
    """Naïve reverse mapping (underscores → dots)."""
    return name.replace("_", ".")

# ─────────────────── dynamic wrapper factory ─────────────────────

def _build_wrapper_from_schema(*, alias_name: str, target: Callable, schema: Dict[str, Any]) -> Callable:
    """Generate a coroutine whose signature mirrors *schema*.

    The hidden *target* parameter is appended **after** all user‑visible
    parameters so it can safely receive a default value.
    """

    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    arg_parts: List[str] = []
    kw_map: List[str] = []
    for pname in props:
        if pname in required:
            arg_parts.append(pname)
        else:
            arg_parts.append(f"{pname}=None")
        kw_map.append(f"'{pname}': {pname}")

    # hidden target param goes LAST so default binding is valid
    arg_sig = ", ".join(arg_parts)
    if arg_sig:
        arg_sig += ", __target=__default_target"
    else:
        arg_sig = "__target=__default_target"

    kwargs_dict = "{" + ", ".join(kw_map) + "}"

    src = f"""
async def _alias({arg_sig}):
    kwargs = {kwargs_dict}
    kwargs = {{k: v for k, v in kwargs.items() if v is not None}}
    res = __target(**kwargs)
    if inspect.isawaitable(res):
        res = await res
    return res
"""
    loc: Dict[str, Any] = {"inspect": inspect, "__default_target": target}
    exec(src, loc)
    fn = loc["_alias"]
    fn.__name__ = alias_name
    return fn

# ─────────────────── public wrapper builder ─────────────────────

def create_openai_compatible_wrapper(original_name: str, original_func: Callable) -> Optional[Callable]:
    """Return a wrapper with an OpenAI‑safe name *and* real signature."""

    # Priority 1: metadata from remote MCP list‑tools
    meta_dict: Optional[Dict[str, Any]] = getattr(original_func, "_proxy_metadata", None)
    schema: Dict[str, Any]
    description: str

    if meta_dict and meta_dict.get("inputSchema"):
        schema = copy.deepcopy(meta_dict["inputSchema"])
        description = meta_dict.get("description", "")
    elif hasattr(original_func, "_mcp_tool"):
        m = original_func._mcp_tool  # type: ignore[attr-defined]
        schema = copy.deepcopy(getattr(m, "inputSchema", {}))
        description = getattr(m, "description", "")
    else:
        logger.warning("No schema for %s – skipping OpenAI wrapper", original_name)
        return None

    if "properties" not in schema and isinstance(schema, dict):
        schema = {"type": "object", "properties": schema, "required": schema.get("required", [])}

        # Strip leading "proxy." if present to avoid redundant prefix
    clean_name = original_name.replace("proxy.", "", 1)
    alias_name = to_openai_compatible_name(clean_name)
    alias_fn = _build_wrapper_from_schema(alias_name=alias_name, target=original_func, schema=schema)

    alias_meta = Tool(name=alias_name, description=description.strip().replace("\n", " "), inputSchema=schema)
    alias_fn._mcp_tool = alias_meta  # type: ignore[attr-defined]

    return alias_fn

# ─────────────────── adapter class (unchanged API) ─────────────
class OpenAIToolsAdapter:
    """Expose registry in an OpenAI‑friendly way and allow execution."""

    def __init__(self, registry: Optional[Dict[str, Callable]] = None):
        self.registry = registry or TOOLS_REGISTRY
        self.openai_to_original: Dict[str, str] = {}
        self.original_to_openai: Dict[str, str] = {}
        self._build_maps()

    def _build_maps(self):
        """Populate name maps, stripping leading ``proxy.`` when present."""
        self.openai_to_original.clear()
        self.original_to_openai.clear()
        for original in self.registry:
            core_name = original.replace("proxy.", "", 1)
            openai_name = to_openai_compatible_name(core_name)
            self.openai_to_original[openai_name] = original
            self.original_to_openai[original] = openai_name

    # ---------- wrapper registration -------------------------------- --------------------------------
    def register_openai_compatible_wrappers(self):
        for o, fn in list(self.registry.items()):
            if "." not in o or o in self.original_to_openai.values():
                continue
            if to_openai_compatible_name(o) in self.registry:
                continue
            w = create_openai_compatible_wrapper(o, fn)
            if w is None:
                continue
            self.registry[w._mcp_tool.name] = w  # type: ignore[attr-defined]
            logger.debug("Registered OpenAI wrapper: %s → %s", w._mcp_tool.name, o)

    # ---------- schema export ---------------------------------------
    def get_openai_tools_definition(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for n, fn in self.registry.items():
            if "." in n or not hasattr(fn, "_mcp_tool"):
                continue
            meta = fn._mcp_tool  # type: ignore[attr-defined]
            out.append({
                "type": "function",
                "function": {
                    "name": n,
                    "description": meta.description,
                    "parameters": meta.inputSchema,
                },
            })
        return out

    # ---------- execution wrapper -----------------------------------
    async def execute_tool(self, name: str, **kw):
        fn = self.registry.get(name) or self.registry.get(self.openai_to_original.get(name, ""))
        if fn is None:
            raise ValueError(f"Tool not found: {name}")
        res = fn(**kw)
        if asyncio.iscoroutine(res):
            res = await res
        return res

    # ---------- translate -------------------------------------------
    def translate_name(self, name: str, to_openai: bool = True) -> str:
        if to_openai:
            return self.original_to_openai.get(name, to_openai_compatible_name(name))
        return self.openai_to_original.get(name, from_openai_compatible_name(name))


adapter = OpenAIToolsAdapter()

def initialize_openai_compatibility():
    adapter.register_openai_compatible_wrappers()
    return adapter
