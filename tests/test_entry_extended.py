import os
import sys
import pytest

import chuk_mcp_runtime.entry as entry

# --- Dummy implementations for entry.py tests ---

class DummyServerRegistry:
    def __init__(self, project_root, config):
        self.bootstrap_called = False
    def load_server_components(self):
        self.bootstrap_called = True

class DummyMCPServer:
    def __init__(self, config):
        self.serve_called = False
    async def serve(self):
        self.serve_called = True

# --- Patch out I/O and logging ---
@pytest.fixture(autouse=True)
def patch_entry(monkeypatch):
    monkeypatch.setattr(entry, "load_config", lambda paths, default: {})
    monkeypatch.setattr(entry, "configure_logging", lambda cfg: None)
    # Provide a DummyLogger with debug/info methods
    class DummyLogger:
        def debug(self, *args, **kwargs): pass
        def info(self, *args, **kwargs):  pass
    monkeypatch.setattr(entry, "get_logger", lambda name: DummyLogger())
    monkeypatch.setattr(entry, "find_project_root", lambda *a, **kw: "/tmp")
    monkeypatch.setattr(entry, "ServerRegistry", DummyServerRegistry)
    monkeypatch.setattr(entry, "MCPServer", DummyMCPServer)
    yield
    os.environ.pop("NO_BOOTSTRAP", None)


def test_run_runtime_with_bootstrap(monkeypatch):
    # Spy on DummyMCPServer.serve
    served = {}
    class SpyServer(DummyMCPServer):
        async def serve(self):
            served['ok'] = True

    monkeypatch.setattr(entry, "MCPServer", SpyServer)
    entry.run_runtime(config_paths=["cfg"], default_config={}, bootstrap_components=True)
    assert served.get('ok', False) is True


def test_run_runtime_skip_bootstrap_flag(monkeypatch):
    os.environ["NO_BOOTSTRAP"] = "1"
    called = {}
    class NoBoot(DummyServerRegistry):
        def load_server_components(self):
            called['boot'] = True

    monkeypatch.setattr(entry, "ServerRegistry", NoBoot)
    entry.run_runtime(bootstrap_components=True)
    assert 'boot' not in called


def test_run_runtime_no_bootstrap_arg(monkeypatch):
    called = {}
    class NoBoot(DummyServerRegistry):
        def load_server_components(self):
            called['boot'] = True

    monkeypatch.setattr(entry, "ServerRegistry", NoBoot)
    entry.run_runtime(bootstrap_components=False)
    assert 'boot' not in called


def test_main_success(monkeypatch, capsys):
    # Stub out run_runtime and patch entry.asyncio.run to no-op
    monkeypatch.setattr(entry, "run_runtime", lambda *a, **kw: None)
    monkeypatch.setattr(entry.asyncio, "run", lambda coro: None)

    monkeypatch.setattr(sys, "argv", ["prog", "cfg.yaml"])
    # Should not raise or print errors
    entry.main(default_config={})
    assert capsys.readouterr().err == ""


def test_main_failure(monkeypatch, capsys):
    # Make run_runtime raise
    def boom(*a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(entry, "run_runtime", boom)
    # Stub entry.asyncio.run so it doesn't error
    monkeypatch.setattr(entry.asyncio, "run", lambda coro: None)

    monkeypatch.setattr(sys, "argv", ["prog"])
    with pytest.raises(SystemExit) as ei:
        entry.main(default_config={})
    assert ei.value.code == 1
    assert "Error starting CHUK MCP server: boom" in capsys.readouterr().err