# chuk_mcp_runtime/common/mcp_tool_decorator.py
"""
CHUK MCP Tool Decorator Module - Async Native Implementation

This module provides decorators for registering functions as CHUK MCP tools
with automatic input schema generation based on function signatures.
All functions are async native with no sync fallbacks.
"""
import inspect
import importlib
from functools import wraps
from typing import Any, Callable, Dict, Type, TypeVar, get_type_hints, Optional, List
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

# Global registry of tool functions (always async)
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

async def create_input_schema(func: Callable[..., Any]) -> Dict[str, Any]:
    """
    Build a JSON Schema for the parameters of `func`, using Pydantic if available.
    """
    sig = inspect.signature(func)
    if HAS_PYDANTIC:
        fields: Dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name == "self" or name.startswith("__"):  # Skip internal parameters
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
            if name == "self" or name.startswith("__"):  # Skip internal parameters
                continue
            ann = hints.get(name, str)
            props[name] = _get_type_schema(ann)
            if param.default is inspect.Parameter.empty:
                required.append(name)
        return {"type": "object", "properties": props, "required": required}

def mcp_tool(name: str = None, description: str = None):
    """
    Decorator to register an async tool.
    Only works with async functions - no synchronous functions allowed.
    """
    def decorator(original_func: Callable[..., Any]):
        # Ensure function is async
        if not inspect.iscoroutinefunction(original_func):
            raise TypeError(f"Function {original_func.__name__} must be async (use 'async def')")
            
        tool_name = name or original_func.__name__
        tool_desc = description or (original_func.__doc__ or "").strip() or f"Tool: {tool_name}"

        # Store a reference to the original function
        @wraps(original_func)
        async def wrapper(*args, **kwargs):
            # Forward all arguments directly to the original function
            return await original_func(*args, **kwargs)
            
        # We'll set up the function's schema and metadata later during initialization
        wrapper._needs_init = True
        wrapper._init_name = tool_name
        wrapper._init_desc = tool_desc
        wrapper._orig_func = original_func
        
        # Register immediately
        TOOLS_REGISTRY[tool_name] = wrapper
        
        return wrapper

    return decorator

async def initialize_tool_registry():
    """
    Initialize all tools in the registry that need initialization.
    """
    for tool_name, func in list(TOOLS_REGISTRY.items()):
        if hasattr(func, '_needs_init') and func._needs_init:
            await _initialize_tool(tool_name, func)

async def _initialize_tool(tool_name: str, placeholder: Callable):
    """Initialize a specific tool."""
    if not hasattr(placeholder, '_needs_init') or not placeholder._needs_init:
        return
        
    original_func = placeholder._orig_func
    schema = await create_input_schema(original_func)
    tool = Tool(
        name=placeholder._init_name, 
        description=placeholder._init_desc, 
        inputSchema=schema
    )
    
    @wraps(original_func)
    async def wrapper(*args, **kwargs):
        try:
            # Forward all arguments directly to the original function
            return await original_func(*args, **kwargs)
        except TypeError as e:
            # Better error handling for parameter mismatches
            sig = inspect.signature(original_func)
            valid_params = [p for p in sig.parameters if not p.startswith('__')]
            logging.error(f"Error calling {tool_name}: {e}. Valid parameters: {valid_params}")
            raise
    
    # Attach metadata
    wrapper._mcp_tool = tool
    wrapper._needs_init = False
    wrapper._orig_func = original_func
    
    # Replace in registry
    TOOLS_REGISTRY[tool_name] = wrapper

async def execute_tool(tool_name: str, **kwargs) -> Any:
    """
    Execute a registered tool asynchronously.
    """
    if tool_name not in TOOLS_REGISTRY:
        raise KeyError(f"Tool '{tool_name}' not registered")
    
    # Initialize if needed
    func = TOOLS_REGISTRY[tool_name]
    if hasattr(func, '_needs_init') and func._needs_init:
        await _initialize_tool(tool_name, func)
        func = TOOLS_REGISTRY[tool_name]
    
    # Execute the tool
    return await func(**kwargs)

async def scan_for_tools(module_paths: List[str]) -> None:
    """
    Scan the provided modules for decorated tools and initialize them.
    
    Args:
        module_paths: List of dotted module paths to scan
    """
    for module_path in module_paths:
        try:
            importlib.import_module(module_path)
        except ImportError as e:
            logging.getLogger("chuk_mcp_runtime.tools").warning(
                f"Failed to import module {module_path}: {e}"
            )
    
    # Initialize all tools that have been registered
    await initialize_tool_registry()

async def get_tool_metadata(tool_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get metadata for a tool or all tools.
    
    Args:
        tool_name: Optional name of the tool to get metadata for
                  If None, returns metadata for all tools
    
    Returns:
        Dict of tool metadata or dict of dicts
    """
    # Initialize any tools that need it
    await initialize_tool_registry()
    
    if tool_name:
        if tool_name not in TOOLS_REGISTRY:
            raise KeyError(f"Tool '{tool_name}' not registered")
        func = TOOLS_REGISTRY[tool_name]
        if hasattr(func, '_mcp_tool'):
            return {
                "name": func._mcp_tool.name,
                "description": func._mcp_tool.description,
                "inputSchema": func._mcp_tool.inputSchema
            }
        return {}
    
    # Return metadata for all tools
    result = {}
    for name, func in TOOLS_REGISTRY.items():
        if hasattr(func, '_mcp_tool'):
            result[name] = {
                "name": func._mcp_tool.name,
                "description": func._mcp_tool.description,
                "inputSchema": func._mcp_tool.inputSchema
            }
    
    return result