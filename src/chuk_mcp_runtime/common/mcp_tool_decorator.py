# chuk_mcp_runtime/common/mcp_tool_decorator.py
"""
CHUK MCP Tool Decorator Module

This module provides decorators for registering functions as CHUK MCP tools
with automatic input schema generation based on function signatures.
"""
import inspect
from functools import wraps
from typing import Dict, Any, Callable, Optional, Type, get_type_hints
import logging

# We'll try to import pydantic, but provide fallbacks if it's not available
try:
    from pydantic import create_model
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    logging.getLogger("chuk_mcp_runtime.tools").warning(
        "Pydantic not available, using fallback schema generation"
    )

# Import MCP types, with fallback if not available
try:
    from mcp.types import Tool
    HAS_MCP_TYPES = True
except ImportError:
    HAS_MCP_TYPES = False
    logging.getLogger("chuk_mcp_runtime.tools").warning(
        "MCP types not available, using fallback Tool class"
    )
    
    # Fallback Tool class for when MCP types are not available
    class Tool:
        def __init__(self, name: str, description: str, inputSchema: Dict[str, Any]):
            self.name = name
            self.description = description
            self.inputSchema = inputSchema

# Global registry for MCP tool functions
TOOLS_REGISTRY = {}

def _get_type_schema(annotation: Type) -> Dict[str, Any]:
    """
    Convert a Python type annotation to a JSON Schema type.
    
    Args:
        annotation: Type annotation to convert.
        
    Returns:
        JSON Schema representation of the type.
    """
    # Map Python types to JSON Schema types
    if annotation == str:
        return {"type": "string"}
    elif annotation == int:
        return {"type": "integer"}
    elif annotation == float:
        return {"type": "number"}
    elif annotation == bool:
        return {"type": "boolean"}
    elif annotation == list or getattr(annotation, "__origin__", None) == list:
        # Handle List[...] type
        return {"type": "array"}
    elif annotation == dict or getattr(annotation, "__origin__", None) == dict:
        # Handle Dict[...] type
        return {"type": "object"}
    # Add more type mappings as needed
    return {"type": "string"}  # Default to string

def create_input_schema(func: Callable) -> Dict[str, Any]:
    """
    Create a JSON Schema for the function's parameters.
    
    Args:
        func: The function to create a schema for.
        
    Returns:
        A JSON Schema object representing the function's parameters.
    """
    sig = inspect.signature(func)
    
    if HAS_PYDANTIC:
        # Use Pydantic for schema generation if available
        fields = {}
        for param in sig.parameters.values():
            annotation = param.annotation if param.annotation != inspect.Parameter.empty else str
            fields[param.name] = (annotation, ...)
        
        InputModel = create_model(f"{func.__name__.capitalize()}Input", **fields)
        return InputModel.model_json_schema()
    else:
        # Fallback schema generation without Pydantic
        properties = {}
        required = []
        
        type_hints = get_type_hints(func)
        
        for param in sig.parameters.values():
            if param.name == 'self':
                continue
                
            # Get type annotation if available
            annotation = type_hints.get(param.name, str)
            
            # Add to properties
            properties[param.name] = _get_type_schema(annotation)
            
            # Add required if no default value
            if param.default == inspect.Parameter.empty:
                required.append(param.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }

def mcp_tool(name: str = None, description: str = None):
    """
    Decorator to register an MCP tool function and auto-generate its input JSON schema.
    
    Args:
        name: Name of the tool. If None, uses the function name.
        description: Description of the tool. If None, uses the function's docstring.
    
    Returns:
        Decorated function with _mcp_tool attribute.
    """
    def decorator(func):
        # Use function name if name not provided
        tool_name = name or func.__name__
        
        # Use docstring if description not provided
        tool_description = description
        if tool_description is None and func.__doc__:
            tool_description = func.__doc__.strip()
        elif tool_description is None:
            tool_description = f"Tool: {tool_name}"
        
        # Create input schema based on function signature
        input_schema = create_input_schema(func)
        
        # Create Tool instance
        tool = Tool(
            name=tool_name,
            description=tool_description,
            inputSchema=input_schema
        )
        
        # Register the function in the global registry.
        TOOLS_REGISTRY[tool_name] = func
        
        # Attach the tool metadata to the function for introspection.
        func._mcp_tool = tool

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

def register_tools_from_module(module):
    """
    Scan a module for functions decorated with @mcp_tool and register them.
    
    Args:
        module: The module to scan for tools.
        
    Returns:
        Dictionary of registered tools from the module.
    """
    module_tools = {}
    
    for name in dir(module):
        item = getattr(module, name)
        if callable(item) and hasattr(item, '_mcp_tool'):
            tool_name = item._mcp_tool.name
            TOOLS_REGISTRY[tool_name] = item
            module_tools[tool_name] = item
            
    return module_tools

def clear_tools_registry():
    """Clear the global tools registry."""
    TOOLS_REGISTRY.clear()