# CHUK MCP Runtime
A generic framework for creating MCP (Messaging Control Protocol) servers that can be installed as a package on any MCP server.

## Features

- Flexible configuration system with YAML support
- Automatic tool discovery and registration
- Configurable logging
- Server registry for managing multiple MCP servers
- Runtime for hosting MCP tools
- Easy-to-use tool decorator for registering functions as MCP tools

## Installation

```bash
# Install from PyPI
pip install chuk-mcp-runtime

# Install with optional dependencies
pip install chuk-mcp-runtime[websocket,dev]

# Install from source
git clone https://github.com/yourusername/chuk-mcp-runtime.git
cd chuk-mcp-runtime
pip install -e .
```

## Quick Start

### 1. Create a configuration file

Create a `config.yaml` file:

```yaml
host:
  name: "my-chuk-mcp-server"
  log_level: "INFO"

server:
  type: "stdio"

tools:
  registry_module: "chuk_mcp_runtime.common.mcp_tool_decorator"
  registry_attr: "TOOLS_REGISTRY"

mcp_servers:
  my_server:
    location: "./my_server"
    enabled: true
    tools:
      module: "my_server.tools"
      enabled: true
```

### 2. Create a tools module

Create a file `my_server/tools.py`:

```python
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool

@mcp_tool(name="greet", description="Generate a greeting")
def greet(name: str, formal: bool = False) -> str:
    """
    Generate a greeting message.
    
    Args:
        name: Name to greet.
        formal: Whether to use a formal greeting.
        
    Returns:
        Greeting message.
    """
    if formal:
        return f"Good day, {name}. It is a pleasure to meet you."
    else:
        return f"Hey {name}! How's it going?"
```

### 3. Run the server

You can run the server in several ways:

```bash
# Using the command-line entry point
chuk-mcp-server

# Using the Python module
python -m chuk_mcp_runtime

# With a specific config file
CHUK_MCP_CONFIG_PATH=./my_config.yaml chuk-mcp-server
```

## Creating a Custom MCP Server

### Basic Server

```python
import asyncio
from chuk_mcp_runtime.server.server import MCPServer
from chuk_mcp_runtime.server.config_loader import load_config
from chuk_mcp_runtime.common.mcp_tool_decorator import mcp_tool

# Define tools
@mcp_tool(name="example", description="Example tool")
def example_tool(param: str) -> dict:
    return {"result": f"Processed: {param}"}

async def main():
    # Load config
    config = load_config()
    
    # Create tools registry
    tools_registry = {"example": example_tool}
    
    # Create and run server
    server = MCPServer(config, tools_registry=tools_registry)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
```

### Using Server Registry

For more complex setups with multiple server components:

```python
import asyncio
from chuk_mcp_runtime.server.config_loader import load_config, find_project_root
from chuk_mcp_runtime.server.server_registry import ServerRegistry
from chuk_mcp_runtime.server.server import MCPServer

async def main():
    # Load config
    config = load_config()
    
    # Find project root
    project_root = find_project_root()
    
    # Initialize server registry
    server_registry = ServerRegistry(project_root, config)
    
    # Load server components
    loaded_modules = server_registry.load_server_components()
    
    # Create and run server
    server = MCPServer(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
```

## Configuration Options

The configuration system supports the following settings:

### Host Configuration

```yaml
host:
  name: "my-mcp-server"  # Server name
  log_level: "INFO"      # Logging level (DEBUG, INFO, WARNING, ERROR)
```

### Server Configuration

```yaml
server:
  type: "stdio"     # Server type (stdio, websocket)
  host: "localhost" # For websocket server
  port: 8080        # For websocket server
```

### Logging Configuration

```yaml
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  reset_handlers: false
  quiet_libraries: true
```

### Tool Configuration

```yaml
tools:
  registry_module: "mcp_runtime.common.mcp_tool_decorator"
  registry_attr: "TOOLS_REGISTRY"
```

### MCP Server Configurations

```yaml
mcp_servers:
  example_server:
    location: "servers/example_server"
    enabled: true
    tools:
      module: "example_server.tools"
      enabled: true
    resources:
      module: "example_server.resources"
      enabled: true
    prompts:
      module: "example_server.prompts"
      enabled: true
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.