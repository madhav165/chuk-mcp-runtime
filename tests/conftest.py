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
        
    async def start_servers(self):
        """Mock start_servers implementation."""
        self.running_servers["test_server"] = {"wrappers": {}}
        
    async def stop_servers(self):
        """Mock stop_servers implementation."""
        self.running_servers.clear()
        
    def get_all_tools(self):
        """Mock get_all_tools implementation."""
        return {"proxy.test_server.tool": MagicMock(return_value="mock result")}
        
    async def process_text(self, text):
        """Mock process_text implementation."""
        return [{"content": "Processed text", "tool": "proxy.test.tool"}]

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
        self.bootstrap_called = False
    def load_server_components(self):
        self.bootstrap_called = True

class DummyMCPServer:
    def __init__(self, config):
        self.serve_called = False
        self.server_name = "test-server"
        
    async def serve(self, custom_handlers=None):
        self.serve_called = True
        self.custom_handlers = custom_handlers

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

@pytest.fixture(scope="session")
def ensure_mocked_modules():
    """Ensure that all required modules are mocked."""
    yield
    # Clean up mocks after tests
    for module in list(sys.modules.keys()):
        if module.startswith("chuk_tool_processor"):
            del sys.modules[module]