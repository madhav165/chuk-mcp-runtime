import os
import sys
import pytest

from chuk_mcp_runtime.entry import run_runtime, main

# --- Dummy Implementations for Testing ---

class DummyServerRegistry:
    def __init__(self, project_root, config):
        self.project_root = project_root
        self.config = config
        self.bootstrap_called = False

    def load_server_components(self):
        self.bootstrap_called = True

class DummyMCPServer:
    def __init__(self, config):
        self.config = config
        self.serve_called = False

    async def serve(self):
        self.serve_called = True

def dummy_load_config(config_paths, default_config):
    # Return a simple configuration dictionary.
    return {"dummy_key": "dummy_value"}

def dummy_configure_logging(config):
    # Do nothing for testing.
    pass

def dummy_find_project_root(start_dir=None):
    return "dummy_project_root"

# --- Patching Fixtures ---

@pytest.fixture(autouse=True)
def patch_entry(monkeypatch):
    monkeypatch.setattr("chuk_mcp_runtime.entry.load_config", dummy_load_config)
    monkeypatch.setattr("chuk_mcp_runtime.entry.configure_logging", dummy_configure_logging)
    monkeypatch.setattr("chuk_mcp_runtime.entry.find_project_root", dummy_find_project_root)
    monkeypatch.setattr("chuk_mcp_runtime.entry.ServerRegistry", DummyServerRegistry)
    monkeypatch.setattr("chuk_mcp_runtime.entry.MCPServer", DummyMCPServer)

# --- Updated Dummy run_runtime for synchronous behavior ---

def dummy_run_runtime_success(*args, **kwargs):
    # Synchronous dummy that simulates a successful run.
    return None

def dummy_run_runtime_failure(*args, **kwargs):
    # Synchronous dummy that raises an exception.
    raise Exception("Simulated failure")

# --- Tests ---

def test_main_success(monkeypatch, capsys):
    # Patch asyncio.run with our synchronous dummy that returns successfully.
    monkeypatch.setattr("chuk_mcp_runtime.entry.asyncio.run", dummy_run_runtime_success)
    # Set sys.argv to simulate invocation with a config path.
    monkeypatch.setattr(sys, "argv", ["dummy", "dummy_config.yaml"])

    try:
        main(default_config={"dummy_default": True})
    except SystemExit:
        pytest.fail("main() should not exit with error on success")
    
    captured = capsys.readouterr()
    # Expect no error messages on stderr.
    assert captured.err == ""

def test_main_failure(monkeypatch, capsys):
    # Patch asyncio.run with our synchronous dummy that raises an exception.
    monkeypatch.setattr("chuk_mcp_runtime.entry.asyncio.run", dummy_run_runtime_failure)
    # Set sys.argv to simulate invocation.
    monkeypatch.setattr(sys, "argv", ["dummy"])
    
    with pytest.raises(SystemExit) as e_info:
        main(default_config={"dummy_default": True})
    
    # Verify that SystemExit was raised with code 1.
    assert e_info.value.code == 1
    
    captured = capsys.readouterr()
    assert "Error starting CHUK MCP server: Simulated failure" in captured.err
