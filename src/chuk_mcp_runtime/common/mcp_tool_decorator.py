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
TOOL_REGISTRY = TOOLS_REGISTRY

def _extract_param_descriptions(func: Callable[..., Any]) -> Dict[str, str]:
    """Extract parameter descriptions from function docstring."""
    import inspect
    
    docstring = inspect.getdoc(func)
    if not docstring:
        return {}
    
    descriptions = {}
    lines = docstring.split('\n')
    
    # Look for Args: section
    in_args_section = False
    for line in lines:
        line = line.strip()
        
        if line.lower().startswith('args:'):
            in_args_section = True
            continue
        elif line.lower().startswith(('returns:', 'raises:', 'yields:', 'note:')):
            in_args_section = False
            continue
        
        if in_args_section and ':' in line:
            # Parse parameter descriptions like "param_name: Description text"
            parts = line.split(':', 1)
            if len(parts) == 2:
                param_name = parts[0].strip()
                description = parts[1].strip()
                descriptions[param_name] = description
    
    return descriptions


def _get_type_schema(annotation: Type) -> Dict[str, Any]:
    """Map Python types to JSON Schema with better Optional handling."""
    import typing
    
    # Handle Optional types (Union[X, None])
    if hasattr(typing, 'get_origin') and hasattr(typing, 'get_args'):
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        
        if origin is typing.Union:
            # Check if it's Optional (Union[X, None])
            if len(args) == 2 and type(None) in args:
                # Get the non-None type
                non_none_type = args[0] if args[1] is type(None) else args[1]
                return _get_type_schema(non_none_type)
    
    # Handle basic types
    if annotation == str:
        return {"type": "string"}
    if annotation == int:
        return {"type": "integer"}
    if annotation == float:
        return {"type": "number"}
    if annotation == bool:
        return {"type": "boolean"}
    
    # Handle generic types
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return {"type": "array"}
    if origin is dict:
        return {"type": "object"}
    
    # Handle string representations of types (from get_type_hints)
    if isinstance(annotation, str):
        if annotation in ('str', 'typing.Optional[str]', 'Optional[str]'):
            return {"type": "string"}
        elif annotation in ('int', 'typing.Optional[int]', 'Optional[int]'):
            return {"type": "integer"}
        elif annotation in ('bool', 'typing.Optional[bool]', 'Optional[bool]'):
            return {"type": "boolean"}
        elif annotation in ('float', 'typing.Optional[float]', 'Optional[float]'):
            return {"type": "number"}
    
    # Special handling for common None-able types
    if str(annotation).startswith('typing.Union') or str(annotation).startswith('typing.Optional'):
        # Try to extract the base type from string representation
        if 'str' in str(annotation):
            return {"type": "string"}
        elif 'int' in str(annotation):
            return {"type": "integer"}
        elif 'bool' in str(annotation):
            return {"type": "boolean"}
        elif 'float' in str(annotation):
            return {"type": "number"}
    
    # Default fallback
    return {"type": "string"}


async def create_input_schema(func: Callable[..., Any]) -> Dict[str, Any]:
    """
    Build a JSON Schema for the parameters of `func`, using Pydantic if available.
    Enhanced to extract parameter descriptions from docstrings.
    """
    sig = inspect.signature(func)
    param_descriptions = _extract_param_descriptions(func)
    
    if HAS_PYDANTIC:
        fields: Dict[str, Any] = {}
        for name, param in sig.parameters.items():
            if name == "self" or name.startswith("__"):  # Skip internal parameters
                continue
            ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
            
            # Handle Optional parameters correctly
            if param.default is not inspect.Parameter.empty:
                fields[name] = (ann, param.default)
            else:
                fields[name] = (ann, ...)
                
        Model = create_model(f"{func.__name__.capitalize()}Input", **fields)
        schema = Model.model_json_schema()
        
        # Add descriptions from docstring
        if "properties" in schema and param_descriptions:
            for param_name, description in param_descriptions.items():
                if param_name in schema["properties"]:
                    schema["properties"][param_name]["description"] = description
                    
        return schema
    else:
        props: Dict[str, Any] = {}
        required = []
        hints = get_type_hints(func)
        
        for name, param in sig.parameters.items():
            if name == "self" or name.startswith("__"):  # Skip internal parameters
                continue
                
            ann = hints.get(name, str)
            param_schema = _get_type_schema(ann)
            
            # Add description if available
            if name in param_descriptions:
                param_schema["description"] = param_descriptions[name]
                
            props[name] = param_schema
            
            # Only mark as required if no default value
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