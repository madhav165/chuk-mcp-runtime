# tests/conftest.py
# Mock imports need to happen before ANY imports
import sys
from unittest.mock import MagicMock

# Create mocks for all the modules we need before they get imported
mock_modules = {
    "chuk_tool_processor": MagicMock(),
    "chuk_tool_processor.mcp": MagicMock(),
    "chuk_tool_processor.registry": MagicMock(),
    "chuk_tool_processor.models": MagicMock(),
    "chuk_tool_processor.models.tool_call": MagicMock()
}

# Add them to sys.modules
for mod_name, mock in mock_modules.items():
    sys.modules[mod_name] = mock

# Mock the ProxyServerManager class to avoid import errors
class MockProxyServerManager:
    """Mock implementation of ProxyServerManager for testing."""
    def __init__(self, config, project_root):
        self.running_servers = {}
        self.config = config
        self.project_root = project_root
        self.openai_mode = config.get("proxy", {}).get("openai_compatible", False)
        self.tools = {
            "proxy.test_server.tool": MagicMock(return_value="mock result")
        }
        
    async def start_servers(self):
        """Mock start_servers implementation."""
        self.running_servers["test_server"] = {"wrappers": {}}
        
    async def stop_servers(self):
        """Mock stop_servers implementation."""
        self.running_servers.clear()
        
    async def get_all_tools(self):
        """Mock get_all_tools implementation."""
        return self.tools
        
    async def process_text(self, text):
        """Mock process_text implementation."""
        return [{"content": "Processed text", "tool": "proxy.test.tool", "processed": True, "text": text}]
    
    async def call_tool(self, name, **kwargs):
        """Mock call_tool implementation that supports tool name resolution."""
        # Simple tool name resolution
        if name.startswith("proxy."):
            parts = name.split(".")
            if len(parts) >= 3:
                server = parts[1]
                tool = parts[-1]
        elif "_" in name:
            parts = name.split("_", 1)
            if len(parts) == 2:
                server, tool = parts
                name = f"proxy.{server}.{tool}"
        
        return f"Result from {name} with args {kwargs}"

# Create a proxy manager module with the mock class
proxy_manager_mod = MagicMock()
proxy_manager_mod.ProxyServerManager = MockProxyServerManager
sys.modules["chuk_mcp_runtime.proxy.manager"] = proxy_manager_mod

# After these mocks are in place, we can import pytest
import pytest
import asyncio
import os

# Other mock classes
class DummyServerRegistry:
    def __init__(self, project_root, config):
        self.project_root = project_root
        self.config = config
        self.bootstrap_called = False
    
    async def load_server_components(self):
        self.bootstrap_called = True
        return {}

class DummyMCPServer:
    def __init__(self, config):
        self.config = config
        self.serve_called = False
        self.server_name = "test-server"
        self.registered_tools = []
        self.tools_registry = {}
        
    async def serve(self, custom_handlers=None):
        self.serve_called = True
        self.custom_handlers = custom_handlers
        
    async def register_tool(self, name, func):
        self.registered_tools.append(name)
        self.tools_registry[name] = func

# Helper function to safely run async code in tests
def run_async(coro):
    """Run an async coroutine in tests safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    return loop.run_until_complete(coro)

class AsyncMock(MagicMock):
    """Mock that works with async functions."""
    async def __call__(self, *args, **kwargs):
        return super(AsyncMock, self).__call__(*args, **kwargs)
        
    # Add support for async context manager
    async def __aenter__(self, *args, **kwargs):
        return self.__enter__(*args, **kwargs)
        
    async def __aexit__(self, *args, **kwargs):
        return self.__exit__(*args, **kwargs)

@pytest.fixture(scope="session", autouse=True)
def ensure_mocked_modules():
    """Ensure that all required modules are mocked."""
    yield
    # Clean up mocks after tests
    for module in list(sys.modules.keys()):
        if module.startswith("chuk_tool_processor"):
            del sys.modules[module]

@pytest.fixture
def clear_tools_registry():
    """Clear the tools registry before and after tests."""
    from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY
    
    # Clear before test
    saved_registry = dict(TOOLS_REGISTRY)
    TOOLS_REGISTRY.clear()
    
    yield
    
    # Restore after test
    TOOLS_REGISTRY.clear()
    TOOLS_REGISTRY.update(saved_registry)