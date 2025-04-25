# chuk_mcp_runtime/common/mcp_tool_decorator.py
"""
CHUK MCP Tool Decorator Module

This module provides decorators for registering functions as CHUK MCP tools
with automatic input schema generation based on function signatures.
Supports both synchronous and asynchronous functions.
"""
import inspect
import asyncio
from functools import wraps
from typing import Any, Callable, Dict, Type, TypeVar, get_type_hints
import logging

T = TypeVar("T")

# Try to import Pydantic
try:
    from pydantic import create_model
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    logging.getLogger("chuk_mcp_runtime.tools").warning(
        "Pydantic not available, using fallback schema generation"
    )

# Try to import the MCP Tool class
try:
    from mcp.types import Tool
except ImportError:
    class Tool:
        def __init__(self, name: str, description: str, inputSchema: Dict[str, Any]):
            self.name = name
            self.description = description
            self.inputSchema = inputSchema

# Global registry of tool functions (always the async wrapper)
TOOLS_REGISTRY: Dict[str, Callable[..., Any]] = {}

def _get_type_schema(annotation: Type) -> Dict[str, Any]:
    """Map Python types to JSON Schema."""
    if annotation == str:
        return {"type": "string"}
    if annotation == int:
        return {"type": "integer"}
    if annotation == float:
        return {"type": "number"}
    if annotation == bool:
        return {"type": "boolean"}
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return {"type": "array"}
    if origin is dict:
        return {"type": "object"}
    return {"type": "string"}

def create_input_schema(func: Callable[..., Any]) -> Dict[str, Any]:
    """
    Build a JSON Schema for the parameters of `func`, using Pydantic if available.
    """
    sig = inspect.signature(func)
    if HAS_PYDANTIC:
        fields: Dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
            fields[name] = (ann, ...)
        Model = create_model(f"{func.__name__.capitalize()}Input", **fields)
        return Model.model_json_schema()
    else:
        props: Dict[str, Any] = {}
        required = []
        hints = get_type_hints(func)
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            ann = hints.get(name, str)
            props[name] = _get_type_schema(ann)
            if param.default is inspect.Parameter.empty:
                required.append(name)
        return {"type": "object", "properties": props, "required": required}

def mcp_tool(name: str = None, description: str = None):
    """
    Decorator to register a tool. Works with both sync and async functions.
    """
    def decorator(func: Callable[..., Any]):
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").strip() or f"Tool: {tool_name}"

        # Build input schema and metadata
        schema = create_input_schema(func)
        tool = Tool(name=tool_name, description=tool_desc, inputSchema=schema)

        # Create an async wrapper for this tool
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)
        else:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

        # Attach metadata on the wrapper
        wrapper._mcp_tool = tool  # type: ignore
        # Provide a sync helper
        def sync_helper(*args, **kwargs):
            loop = asyncio.get_event_loop()
            if loop.is_running():
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(wrapper(*args, **kwargs))
                finally:
                    new_loop.close()
            else:
                return loop.run_until_complete(wrapper(*args, **kwargs))
        wrapper.sync = sync_helper  # type: ignore

        # Register the wrapper, not the original func
        TOOLS_REGISTRY[tool_name] = wrapper
        return wrapper  # always async

    return decorator

async def execute_tool_async(tool_name: str, **kwargs) -> Any:
    """
    Asynchronously execute a registered tool.
    """
    if tool_name not in TOOLS_REGISTRY:
        raise KeyError(f"Tool '{tool_name}' not registered")
    fn = TOOLS_REGISTRY[tool_name]
    return await fn(**kwargs)

def execute_tool(tool_name: str, **kwargs) -> Any:
    """
    Synchronously execute a registered tool (for compatibility).
    """
    if tool_name not in TOOLS_REGISTRY:
        raise KeyError(f"Tool '{tool_name}' not registered")
    fn = TOOLS_REGISTRY[tool_name]
    return fn.sync(**kwargs)