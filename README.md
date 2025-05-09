# CHUK MCP Runtime

CHUK MCP Runtime connects local and remote MCP (Model Context Protocol) servers. Host your own Python-based MCP tools locally or connect to remote servers over stdio or SSE.

## Installation

```bash
# Basic installation
uv pip install chuk-mcp-runtime

# With optional dependencies
uv pip install chuk-mcp-runtime[websocket,dev]

# Make sure to install tzdata for proper timezone support
uv pip install tzdata
```

## Quick Start: Proxy Examples

### Example 1: stdio → stdio (Basic Proxy)

Run an MCP stdio server and expose it through the proxy layer over stdio.

```yaml
# stdio_proxy_config.yaml
proxy:
  enabled: true
  namespace: "proxy"

mcp_servers:
  time:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--local-timezone", "America/New_York"]
```

Run the proxy:

```bash
# Using config file
chuk-mcp-proxy --config stdio_proxy_config.yaml

# Using command-line arguments (two equivalent methods)
# Method 1: Using --args (everything after --args goes to the command)
uv run chuk-mcp-proxy --stdio time --command uvx --args mcp-server-time --local-timezone America/New_York

# Method 2: Using -- (everything after -- goes to the command)
uv run chuk-mcp-proxy --stdio time --command uvx -- mcp-server-time --local-timezone America/New_York

```

Once the proxy is running, you'll see output like:
```
Running servers : time
Wrapped tools   : proxy.time.get_current_time, proxy.time.convert_time
```

Example tool calls:

```json
{
  "name": "proxy.time.get_current_time",
  "arguments": {
    "timezone": "America/New_York"
  }
}
```

```json
{
  "name": "proxy.time.convert_time",
  "arguments": {
    "time": "2025-05-08T12:00:00",
    "source_timezone": "UTC",
    "target_timezone": "America/New_York"
  }
}
```

> **Note:** If you encounter timezone errors (e.g., `ZoneInfoNotFoundError: 'No time zone found with key BST'`), make sure you have the `tzdata` package installed: `uv pip install tzdata`

### Example 2: stdio → SSE (Web Exposure)

Expose a local stdio MCP server as an SSE endpoint for web clients.

```yaml
# sse_proxy_config.yaml
proxy:
  enabled: true
  namespace: "proxy"

# Local stdio server to proxy
mcp_servers:
  time:
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--timezone", "America/New_York"]

# SSE server configuration
server:
  type: "sse"
  port: 8000
  host: "localhost"
  sse_path: "/sse"
  message_path: "/message"
```

Run the SSE proxy:

```bash
# Start the server
chuk-mcp-server --config sse_proxy_config.yaml
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

## Creating Custom MCP Tools

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
chuk-mcp-server --config config.yaml
```

## Combined Local + Proxy Server

Run a local MCP server that also connects to remote servers.

```yaml
# combined_config.yaml
host:
  name: "combined-server"
  log_level: "INFO"

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
  
  # Remote servers
  mcp_servers:
    time:
      type: "stdio"
      command: "uvx"
      args: ["mcp-server-time", "--local-timezone", "America/New_York"]
```

Start the combined server:

```bash
chuk-mcp-server --config combined_config.yaml
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
- `--args ...`: Additional args for the stdio command (or use `--` to separate arguments)
- `--url URL`: SSE base URL
- `--api-key KEY`: SSE API key (or set API_KEY env var)
- `--keep-aliases`: Keep single-dot aliases proxy.<tool>

### chuk-mcp-server

```
chuk-mcp-server [CONFIG_PATH]
```

Options:
- `CONFIG_PATH`: Path to configuration YAML (optional, defaults to searching common locations)
- Environment variable: `CHUK_MCP_CONFIG_PATH` can be used instead of command-line argument

## Using Proxy Tools Programmatically

```python
import asyncio
from chuk_mcp_runtime.entry import run_runtime
from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY

async def example():
    # Access the proxied tool by its fully qualified name
    time_tool = TOOLS_REGISTRY.get("proxy.time.get_current_time")
    
    # Call the tool
    time_result = await time_tool(timezone="America/New_York")
    
    print(f"Current time: {time_result}")

if __name__ == "__main__":
    # Run in background
    loop = asyncio.get_event_loop()
    loop.create_task(run_runtime())
    loop.run_until_complete(example())
```

## Troubleshooting

### Timezone Errors

If you encounter errors like `ZoneInfoNotFoundError: 'No time zone found with key BST'`, it's because the Python zoneinfo module is missing the required timezone data. To fix this:

```bash
# Install the tzdata package
uv pip install tzdata
```

This is particularly important when working with the time server example.

### Command-line Arguments

If you see errors like:
```
mcp-server-time: error: unrecognized arguments: --timezone America/New_York
```

Check that:
1. You're using the correct parameter name (`--local-timezone` for the time server, not `--timezone`)
2. Your command-line arguments are being passed correctly to the tool

Two ways to pass arguments to the child process:
```bash
# Method 1: Using --args (everything after --args goes to the command)
chuk-mcp-proxy --stdio time --command uvx --args mcp-server-time --local-timezone America/New_York

# Method 2: Using -- (everything after -- goes to the command)
chuk-mcp-proxy --stdio time --command uvx -- mcp-server-time --local-timezone America/New_York
```

## License

MIT Licensemcp-proxy [OPTIONS]
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
- `--keep-aliases`: Keep single-dot aliases proxy.<tool>

### chuk-mcp-server

```
chuk-mcp-server [CONFIG_PATH]
```

Options:
- `CONFIG_PATH`: Path to configuration YAML (optional, defaults to searching common locations)
- Environment variable: `CHUK_MCP_CONFIG_PATH` can be used instead of command-line argument

## Using Proxy Tools Programmatically

```python
import asyncio
from chuk_mcp_runtime.entry import run_runtime
from chuk_mcp_runtime.common.mcp_tool_decorator import TOOLS_REGISTRY

async def example():
    # Access the proxied tool by its fully qualified name
    time_tool = TOOLS_REGISTRY.get("proxy.time.get_current_time")
    
    # Call the tool
    time_result = await time_tool(timezone="America/New_York")
    
    print(f"Current time: {time_result}")

if __name__ == "__main__":
    # Run in background
    loop = asyncio.get_event_loop()
    loop.create_task(run_runtime())
    loop.run_until_complete(example())
```

## License

MIT License