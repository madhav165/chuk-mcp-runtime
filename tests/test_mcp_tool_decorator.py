import pytest
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool, TOOLS_REGISTRY, create_input_schema

@mcp_tool()
def dummy_tool(arg1: int, arg2: str):
    """Dummy tool for testing"""
    return f"arg1: {arg1}, arg2: {arg2}"

def test_mcp_tool_decorator():
    # Check if dummy_tool has been decorated with _mcp_tool metadata
    assert hasattr(dummy_tool, "_mcp_tool")
    tool_meta = dummy_tool._mcp_tool
    assert hasattr(tool_meta, "name")
    assert hasattr(tool_meta, "description")
    assert hasattr(tool_meta, "inputSchema")
    
    # Check registration in global registry
    assert dummy_tool.__name__ in TOOLS_REGISTRY

def test_create_input_schema():
    schema = create_input_schema(dummy_tool)
    # The schema should be a dict containing a list of required fields
    assert isinstance(schema, dict)
    required_fields = schema.get("required", [])
    assert "arg1" in required_fields
    assert "arg2" in required_fields
