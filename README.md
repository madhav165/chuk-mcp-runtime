# CHUK MCP Runtime

CHUK MCP Runtime is a flexible framework that connects local and remote MCP (Model Context Protocol) servers. It enables you to:

- Host your own Python-based MCP tools locally
- Connect to remote MCP servers through stdio or SSE protocols
- Provide OpenAI-compatible function calling interfaces
- Create proxy layers that expose multiple MCP servers through a single endpoint

## Installation

```bash
# Basic installation
uv pip install chuk-mcp-runtime

# With optional dependencies
uv pip install chuk-mcp-runtime[websocket,dev]

# Make sure to install tzdata for proper timezone support
uv pip install tzdata
```

## Core Components

The CHUK MCP Runtime consists of two main command-line tools:

1. **`chuk-mcp-server`**: Runs a complete MCP server with local tools and optional proxy support
2. **`chuk-mcp-proxy`**: Provides a lightweight proxy layer that wraps remote MCP servers

## Quick Start: Using the Proxy

The proxy layer allows you to expose tools from multiple MCP servers through a unified interface.

### Example 1: Basic Command Line Usage

Run an MCP proxy with a time server:

```bash
# Start a proxy to the time server with dot notation (proxy.time.get_current_time)
uv run -m chuk_mcp_runtime.proxy_cli --stdio time --command uvx --args mcp-server-time --local-timezone America/New_York

# Start a proxy with OpenAI-compatible underscore notation (time_get_current_time)
uv run -m chuk_mcp_runtime.proxy_cli --stdio time --command uvx --args mcp-server-time --local-timezone America/New_York --openai-compatible
```

You can also use the `--` separator for command arguments:

```bash
uv run -m chuk_mcp_runtime.proxy_cli --stdio time --command uvx -- mcp-server-time --local-timezone America/New_York
```

Once the proxy is running, you'll see output like:
```
Running servers : time
Wrapped tools   : proxy.time.get_current_time, proxy.time.convert_time
Smoke-test call : ...
```

### Example 2: Configuration File

Create a YAML configuration file:

```yaml
# stdio_proxy_config.yaml
proxy:
  enabled: true
  namespace: "proxy"
  openai_compatible: false  # Use true for underscore notation (time_get_current_time)

mcp_servers:
  time:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--local-timezone", "America/New_York"]
  
  echo:
    type: "stdio"
    command: "python"
    args: ["examples/echo_server/main.py"]
```

Run the proxy with the config file:

```bash
uv run -m chuk_mcp_runtime.proxy_cli --config stdio_proxy_config.yaml
```

### Example 3: OpenAI-Compatible Mode

To expose tools with underscore notation (compatible with OpenAI function calling):

```yaml
# openai_compatible_config.yaml
proxy:
  enabled: true
  namespace: "proxy"
  openai_compatible: true   # Enable underscore notation
  only_openai_tools: true   # Only register underscore-notation tools

mcp_servers:
  time:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--local-timezone", "America/New_York"]
```

Run with:

```bash
uv run -m chuk_mcp_runtime.proxy_cli --config openai_compatible_config.yaml
```

This exposes tools like `time_get_current_time` instead of `proxy.time.get_current_time`.

## Creating Local MCP Tools

### 1. Create a custom tool

```python
# my_tools/tools.py
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool

@mcp_tool(name="get_current_time", description="Get the current time in a timezone")
def get_current_time(timezone: str = "UTC") -> str:
    """Get the current time in the specified timezone."""
    from datetime import datetime
    import pytz
    
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")
```

### 2. Create a config file

```yaml
# config.yaml
host:
  name: "my-mcp-server"
  log_level: "INFO"

server:
  type: "stdio"

tools:
  registry_module: "chuk_mcp_runtime.common.mcp_tool_decorator"
  registry_attr: "TOOLS_REGISTRY"

mcp_servers:
  my_tools:
    location: "./my_tools"
    tools:
      module: "my_tools.tools"
```

### 3. Run the server

```bash
uv run -m chuk_mcp_runtime.main --config config.yaml
```

## Running a Combined Local + Proxy Server

You can run a single server that provides both local tools and proxied remote tools:

```yaml
# combined_config.yaml
host:
  name: "combined-server"
  log_level: "INFO"

# Local server configuration
server:
  type: "stdio"

tools:
  registry_module: "chuk_mcp_runtime.common.mcp_tool_decorator"
  registry_attr: "TOOLS_REGISTRY"

# Local tools
mcp_servers:
  local_tools:
    location: "./my_tools"
    tools:
      module: "my_tools.tools"

# Proxy configuration
proxy:
  enabled: true
  namespace: "proxy"
  openai_compatible: false
  
  # Remote servers
  mcp_servers:
    time:
      type: "stdio"
      command: "uvx"
      args: ["mcp-server-time", "--local-timezone", "America/New_York"]
    
    echo:
      type: "stdio"
      command: "python"
      args: ["examples/echo_server/main.py"]
```

Start the combined server:

```bash
uv run -m chuk_mcp_runtime.main --config combined_config.yaml
```

## Command Reference

### chuk-mcp-proxy

```
chuk-mcp-proxy [OPTIONS]
```

Options:
- `--config FILE`: YAML config file (optional, can be combined with flags below)
- `--stdio NAME`: Add a local stdio MCP server (repeatable)
- `--sse NAME`: Add a remote SSE MCP server (repeatable)
- `--command CMD`: Executable for stdio servers (default: python)
- `--cwd DIR`: Working directory for stdio server
- `--args ...`: Additional args for the stdio command
- `--url URL`: SSE base URL
- `--api-key KEY`: SSE API key (or set API_KEY env var)
- `--openai-compatible`: Use OpenAI-compatible tool names (underscores)

### chuk-mcp-server

```
chuk-mcp-server [CONFIG_PATH]
```

Options:
- `CONFIG_PATH`: Path to configuration YAML (optional, defaults to searching common locations)

Environment variables:
- `CHUK_MCP_CONFIG_PATH`: Alternative to providing config path as argument
- `CHUK_MCP_LOG_LEVEL`: Set logging level (INFO, DEBUG, etc.)
- `NO_BOOTSTRAP`: Set to disable component bootstrap at startup
- `API_KEY`: API key for SSE servers (alternative to --api-key)

## Using the Web Server

To expose MCP tools through a web interface:

```yaml
# web_server_config.yaml
host:
  name: "chuk-mcp-runtime"
  log_level: "INFO"

server:
  type: "sse"
  auth: "bearer" # this line is needed to enable bearer auth

proxy:
  enabled: true
  namespace: "proxy"

# Local stdio server to proxy
mcp_servers:
  time:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--local-timezone", "America/New_York"]

# SSE server configuration
server:
  type: "sse"
  port: 8000
  host: "localhost"
  sse_path: "/sse"
  message_path: "/message"
```

Run the SSE server:

```bash
uv run -m chuk_mcp_runtime.main --config web_server_config.yaml
```

Connect to the SSE endpoint:

```bash
# Subscribe to events
curl -N http://localhost:8000/sse

# Send a message
curl -X POST http://localhost:8000/message \
  -H "Content-Type: application/json" \
  -d '{
    "name": "proxy.time.get_current_time",
    "arguments": {
      "timezone": "America/New_York"
    }
  }'
```

## Using Proxy Tools Programmatically

```python
import asyncio
from chuk_mcp_runtime.proxy.manager import ProxyServerManager
from chuk_mcp_runtime.server.config_loader import load_config

async def example():
    # Load configuration
    config = load_config(["config.yaml"])
    
    # Initialize and start proxy manager
    proxy = ProxyServerManager(config, ".")
    await proxy.start_servers()
    
    try:
        # Get available tools
        tools = proxy.get_all_tools()
        print(f"Available tools: {', '.join(tools.keys())}")
        
        # Call time tool
        if "proxy.time.get_current_time" in tools:
            result = await tools["proxy.time.get_current_time"](timezone="UTC")
            print(f"Current time: {result}")
        
        # Or call directly through the proxy manager
        result = await proxy.call_tool("proxy.time.get_current_time", timezone="UTC")
        print(f"Current time (via manager): {result}")
    
    finally:
        # Clean up
        await proxy.stop_servers()

if __name__ == "__main__":
    asyncio.run(example())
```

## Troubleshooting

### Command-line Arguments

If you see errors like:
```
mcp-server-time: error: unrecognized arguments: --timezone America/New_York
```

Check that:
1. You're using the correct parameter name (`--local-timezone` for the time server, not `--timezone`)
2. Use either `--args` or `--` to properly pass arguments to the child process:

```bash
# Method 1: Using --args
uv run -m chuk_mcp_runtime.proxy_cli --stdio time --command uvx --args mcp-server-time --local-timezone America/New_York

# Method 2: Using --
uv run -m chuk_mcp_runtime.proxy_cli --stdio time --command uvx -- mcp-server-time --local-timezone America/New_York
```

### OpenAI Compatibility

If you're having issues with OpenAI compatibility:

1. Make sure `openai_compatible: true` is set in your proxy configuration
2. Tools will be exposed with underscore names (e.g., `time_get_current_time`)
3. If using `only_openai_tools: true`, only underscore notation will be registered

## License

MIT License