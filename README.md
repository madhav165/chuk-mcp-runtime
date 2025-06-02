# CHUK MCP Runtime

CHUK MCP Runtime is a flexible framework that connects local and remote MCP (Model Context Protocol) servers. It enables you to:

- Host your own Python-based MCP tools locally with configurable timeouts
- Connect to remote MCP servers through stdio or SSE protocols
- Provide OpenAI-compatible function calling interfaces
- Create proxy layers that expose multiple MCP servers through a single endpoint
- Configure per-tool timeout settings for reliable execution

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
async def get_current_time(timezone: str = "UTC") -> str:
    """Get the current time in the specified timezone."""
    from datetime import datetime
    import pytz
    
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)  
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")

@mcp_tool(name="calculate_sum", description="Calculate the sum of two numbers")
async def calculate_sum(a: int, b: int) -> dict:
    """Calculate the sum of two numbers."""
    result = a + b
    return {
        "operation": "addition",
        "operands": [a, b],
        "result": result
    }
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

## Tool Configuration

### Timeout Settings

CHUK MCP Runtime supports configurable timeouts for tools to handle long-running operations:

```python
# Tool with custom timeout
@mcp_tool(
    name="api_call",
    description="Call external API", 
    timeout=30  # 30 second timeout
)
async def api_call(url: str) -> dict:
    # Implementation here
    pass
```

```yaml
# config.yaml timeout settings
tools:
  timeout: 60  # Default timeout for all tools
  tool_configs:
    api_call:
      timeout: 45  # Override specific tool timeout
```

Environment variable: `MCP_TOOL_TIMEOUT=60`

### Advanced Tool Features

Tools support:
- **Type hints** for automatic schema generation
- **Docstring parsing** for parameter descriptions  
- **Async execution** with timeout protection
- **Error handling** with graceful degradation
- **Session management** for stateful operations

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