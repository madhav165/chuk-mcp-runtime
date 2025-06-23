# CHUK MCP Runtime

CHUK MCP Runtime is a flexible, secure framework that connects local and remote MCP (Model Context Protocol) servers. It enables you to:

- Host your own Python-based MCP tools locally with configurable timeouts
- Connect to remote MCP servers through stdio or SSE protocols
- Provide OpenAI-compatible function calling interfaces
- Create proxy layers that expose multiple MCP servers through a single endpoint
- Configure per-tool timeout settings for reliable execution
- Manage sessions and artifacts with built-in tools (when enabled)

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

## Security Model

**IMPORTANT**: CHUK MCP Runtime follows a **secure-by-default** approach:

- **All built-in tools are disabled by default**
- Session management tools require explicit enablement
- Artifact storage tools require explicit enablement
- Tools must be individually enabled in configuration
- This prevents unexpected tool exposure and reduces attack surface

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
    """
    Get the current time in the specified timezone.
    
    Args:
        timezone: Target timezone (e.g., 'UTC', 'America/New_York')
    """
    from datetime import datetime
    import pytz
    
    tz = pytz.timezone(timezone)
    now = datetime.now(tz)  
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")

@mcp_tool(name="calculate_sum", description="Calculate the sum of two numbers", timeout=10)
async def calculate_sum(a: int, b: int) -> dict:
    """
    Calculate the sum of two numbers.
    
    Args:
        a: First number
        b: Second number
    """
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

# Global tool settings
tools:
  registry_module: "chuk_mcp_runtime.common.mcp_tool_decorator"
  registry_attr: "TOOLS_REGISTRY"
  timeout: 60  # Default timeout for all tools

# Session management (optional - disabled by default)
sessions:
  sandbox_id: "my-app"
  default_ttl_hours: 24

# Session tools (disabled by default - must enable explicitly)
session_tools:
  enabled: true  # Must explicitly enable
  tools:
    get_current_session: {enabled: true}
    set_session: {enabled: true}
    clear_session: {enabled: true}
    create_session: {enabled: true}

# Artifact storage (disabled by default - must enable explicitly)
artifacts:
  enabled: true  # Must explicitly enable
  storage_provider: "filesystem"
  session_provider: "memory"
  bucket: "my-artifacts"
  tools:
    upload_file: {enabled: true}
    write_file: {enabled: true}
    read_file: {enabled: true}
    list_session_files: {enabled: true}
    delete_file: {enabled: true}
    get_file_metadata: {enabled: true}

# Local tool modules
mcp_servers:
  my_tools:
    enabled: true
    location: "./my_tools"
    tools:
      enabled: true
      module: "my_tools.tools"
```

### 3. Run the server

```bash
uv run -m chuk_mcp_runtime.main --config config.yaml
```

## Built-in Tool Categories

CHUK MCP Runtime provides two categories of built-in tools that can be optionally enabled:

### Session Management Tools

**Status**: Disabled by default - must be explicitly enabled

Tools for managing session context and lifecycle:

- `get_current_session`: Get information about the current session
- `set_session`: Set the session context for operations  
- `clear_session`: Clear the current session context
- `list_sessions`: List all active sessions
- `get_session_info`: Get detailed session information
- `create_session`: Create a new session with metadata

**Enable in config**:
```yaml
session_tools:
  enabled: true
  tools:
    get_current_session: {enabled: true}
    set_session: {enabled: true}
    # ... enable other tools as needed
```

### Artifact Storage Tools

**Status**: Disabled by default - must be explicitly enabled

Tools for file storage and management within sessions:

- `upload_file`: Upload files with base64 content
- `write_file`: Create or update text files
- `read_file`: Read file contents
- `list_session_files`: List files in current session
- `delete_file`: Delete files
- `list_directory`: List directory contents
- `copy_file`: Copy files within session
- `move_file`: Move/rename files
- `get_file_metadata`: Get file metadata
- `get_presigned_url`: Generate presigned download URLs
- `get_storage_stats`: Get storage statistics

**Enable in config**:
```yaml
artifacts:
  enabled: true
  storage_provider: "filesystem"  # or "ibm_cos", "s3", etc.
  session_provider: "memory"      # or "redis"
  tools:
    upload_file: {enabled: true}
    write_file: {enabled: true}
    read_file: {enabled: true}
    # ... enable other tools as needed
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
    """Call an external API with timeout protection."""
    # Implementation here
    pass
```

**Configuration priority** (highest to lowest):
1. Per-tool timeout in decorator: `@mcp_tool(timeout=30)`
2. Global timeout in config: `tools.timeout: 60`
3. Environment variable: `MCP_TOOL_TIMEOUT=60`
4. Default: 60 seconds

### Advanced Tool Features

Tools support:
- **Type hints** for automatic JSON schema generation
- **Docstring parsing** for parameter descriptions  
- **Async execution** with timeout protection
- **Error handling** with graceful degradation
- **Session management** for stateful operations
- **Thread-safe initialization** with race condition protection

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

# Session management
sessions:
  sandbox_id: "combined-app"

# Enable session tools
session_tools:
  enabled: true
  tools:
    get_current_session: {enabled: true}
    create_session: {enabled: true}

# Enable artifact tools
artifacts:
  enabled: true
  storage_provider: "filesystem"
  tools:
    write_file: {enabled: true}
    read_file: {enabled: true}
    list_session_files: {enabled: true}

# Local tools
mcp_servers:
  local_tools:
    enabled: true
    location: "./my_tools"
    tools:
      enabled: true
      module: "my_tools.tools"

# Proxy configuration
proxy:
  enabled: true
  namespace: "proxy"
  openai_compatible: false
  
# Remote servers (managed by proxy)
mcp_servers:
  time:
    enabled: true
    type: "stdio"
    command: "uvx"
    args: ["mcp-server-time", "--local-timezone", "America/New_York"]
  
  echo:
    enabled: true
    type: "stdio"
    command: "python"
    args: ["examples/echo_server/main.py"]
```

Start the combined server:

```bash
uv run -m chuk_mcp_runtime.main --config combined_config.yaml
```

## Transport Options

CHUK MCP Runtime supports multiple transport mechanisms:

### stdio (Standard Input/Output)
```yaml
server:
  type: "stdio"
```

### Server-Sent Events (SSE)
```yaml
server:
  type: "sse"

sse:
  host: "0.0.0.0"
  port: 8000
  sse_path: "/sse"
  message_path: "/messages/"
  health_path: "/health"
```

### Streamable HTTP
```yaml
server:
  type: "streamable-http"

streamable-http:
  host: "127.0.0.1"
  port: 3000
  mcp_path: "/mcp"
  json_response: true
  stateless: true
```

## Security Features

### Authentication
```yaml
server:
  auth: "bearer"  # Enables JWT authentication

# Set JWT secret in environment
# JWT_SECRET_KEY=your-secret-key
```

### Tool Security
- All built-in tools disabled by default
- Granular per-tool enablement
- Session isolation for artifact storage
- Input validation on all tool parameters
- Timeout protection against runaway operations

## Environment Variables

CHUK MCP Runtime supports configuration through environment variables for flexibility in different deployment scenarios:

### Core Configuration
- `CHUK_MCP_CONFIG_PATH`: Path to configuration YAML file
- `CHUK_MCP_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `MCP_TOOL_TIMEOUT`: Default timeout for all tools (seconds)
- `TOOL_TIMEOUT`: Alternative name for tool timeout

### Session Management
- `MCP_SANDBOX_ID`: Sandbox identifier for session management
- `CHUK_SANDBOX_ID`: Alternative sandbox ID variable
- `SANDBOX_ID`: Alternative sandbox ID variable
- `POD_NAME`: Used as fallback for sandbox ID in containerized environments

### Artifact Storage
- `ARTIFACT_STORAGE_PROVIDER`: Storage backend (filesystem, ibm_cos, s3, etc.)
- `ARTIFACT_SESSION_PROVIDER`: Session provider (memory, redis)
- `ARTIFACT_BUCKET`: Storage bucket name
- `ARTIFACT_FS_ROOT`: Filesystem root for local storage

### Artifact Storage - Cloud Providers
#### IBM Cloud Object Storage
- `IBM_COS_ENDPOINT`: IBM COS endpoint URL
- `IBM_COS_ACCESS_KEY_ID`: Access key ID
- `IBM_COS_SECRET_ACCESS_KEY`: Secret access key
- `IBM_COS_REGION`: Region name

#### AWS S3
- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key
- `AWS_DEFAULT_REGION`: AWS region

### Session Providers
#### Redis
- `SESSION_REDIS_URL`: Redis connection URL
- `SESSION_REDIS_HOST`: Redis host
- `SESSION_REDIS_PORT`: Redis port
- `SESSION_REDIS_DB`: Redis database number
- `SESSION_REDIS_PASSWORD`: Redis password

### Authentication
- `JWT_SECRET_KEY`: Secret key for JWT token validation
- `JWT_ALGORITHM`: JWT algorithm (default: HS256)
- `JWT_ALLOWED_ALGORITHMS`: Comma-separated list of allowed algorithms
- `JWT_LEEWAY`: Clock drift tolerance in seconds (default: 1)

### Proxy Configuration
- `HUB_ID`: Hub identifier for distributed deployments
- `POD_IP`: Pod IP address for service discovery
- `HOSTNAME`: Alternative hostname for service discovery
- `HUB_URL`: Hub URL for sandbox registration
- `HUB_ADDR`: Hub address for communication
- `HUB_TOKEN`: Authentication token for hub communication
- `SBX_TRANSPORT`: Transport protocol for sandbox communication

### Example Environment Setup

```bash
# Basic configuration
export CHUK_MCP_LOG_LEVEL=INFO
export MCP_TOOL_TIMEOUT=60
export MCP_SANDBOX_ID=my-app

# Artifact storage with filesystem
export ARTIFACT_STORAGE_PROVIDER=filesystem
export ARTIFACT_FS_ROOT=/var/lib/mcp-artifacts

# Session management with Redis
export ARTIFACT_SESSION_PROVIDER=redis
export SESSION_REDIS_URL=redis://localhost:6379/0

# JWT authentication
export JWT_SECRET_KEY=your-secret-key-here

# Run the server
uv run -m chuk_mcp_runtime.main --config config.yaml
```

### Docker Example

```dockerfile
FROM python:3.11-slim

# Install runtime
RUN pip install chuk-mcp-runtime

# Set environment variables
ENV CHUK_MCP_LOG_LEVEL=INFO
ENV MCP_TOOL_TIMEOUT=60
ENV ARTIFACT_STORAGE_PROVIDER=filesystem
ENV ARTIFACT_FS_ROOT=/app/artifacts
ENV MCP_SANDBOX_ID=docker-app

# Copy configuration
COPY config.yaml /app/config.yaml
WORKDIR /app

CMD ["python", "-m", "chuk_mcp_runtime.main", "--config", "config.yaml"]
```

Environment variables take precedence in this order:
1. Command line arguments (highest)
2. Environment variables
3. Configuration file values
4. Default values (lowest)

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
chuk-mcp-server [OPTIONS]
```

Options:
- `--config FILE`: YAML configuration file
- `-c FILE`: Short form of --config
- Environment variable: `CHUK_MCP_CONFIG_PATH`

## Troubleshooting

### Common Issues

**"Tool not found" errors**:
- Check that tools are properly enabled in configuration
- Verify tool registration in the specified module
- Ensure async function signatures are correct

**Session validation errors**:
- Verify session management is configured
- Check that session tools are enabled if using session features
- Ensure proper async/await usage in tool implementations

**Timeout errors**:
- Increase tool timeout settings
- Check for blocking operations in async tools
- Monitor resource usage during tool execution

### Debug Logging

Enable detailed logging:

```yaml
logging:
  level: "DEBUG"
  loggers:
    "chuk_mcp_runtime.tools": "DEBUG"
    "chuk_mcp_runtime.session": "DEBUG"
    "chuk_mcp_runtime.proxy": "DEBUG"
```

## Examples

See the `examples/` directory for complete working examples:
- Basic tool creation
- Session management
- Artifact storage
- Proxy configurations
- Combined local + remote setups

## Contributing

Contributions are welcome! Please see CONTRIBUTING.md for guidelines.

## License

MIT License - see LICENSE file for details.