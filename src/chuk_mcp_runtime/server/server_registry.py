# chuk_mcp_runtime/server/server_registry.py
"""
Server Registry Module for CHUK MCP Tool Servers - Async Native Implementation

This module provides a ServerRegistry class for managing 
CHUK MCP tool servers and their components.
"""
import os
import sys
import importlib
import asyncio
from typing import List, Dict, Any, Tuple, Optional, Set
from pathlib import Path
import venv
import subprocess

# get the logger
from chuk_mcp_runtime.server.logging_config import get_logger
from chuk_mcp_runtime.common.mcp_tool_decorator import scan_for_tools, get_tool_functions

class ServerRegistry:
    """Registry for managing MCP tool servers with components"""
    def __init__(self, project_root: str, config: Dict[str, Any]):
        """
        Initialize the server registry.
        
        Args:
            project_root: The root directory of the project.
            config: Configuration dictionary.
        """
        self.project_root = project_root
        self.config = config
        
        # Initialize logger
        self.logger = get_logger("chuk_mcp_runtime.server_registry", config)
        
        self.server_paths, self.components = self._setup_server_paths()
        self._setup_python_paths()
        self._setup_python_venvs()
        self.loaded_modules = {}

    def find_server_root(self, src_path: str) -> Path:
        """
        Given the 'location' path from config (pointing to /src),
        return the parent directory where pyproject.toml should live.
        """
        resolved_src_path = Path(src_path).resolve()
        if resolved_src_path.name != "src":
            raise ValueError(
                f"Expected a 'src' directory, got: {resolved_src_path.name}"
            )
        
        project_root = resolved_src_path.parent
        pyproject = project_root / "pyproject.toml"
        if not pyproject.exists():
            raise FileNotFoundError(f"pyproject.toml not found at {pyproject}")
        
        return project_root

    def create_venv(self, venv_path: Path) -> None:
        """
        Create a virtual environment at the given path.
        If the venv already exists, it does nothing.
        """
        if venv_path.exists():
            print(f"✅ Venv already exists at: {venv_path}")
            return

        print(f"🚀 Creating venv at: {venv_path}")
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(venv_path)
        print("✅ Venv created.")

    def ensure_uv_installed(self) -> None:
        """
        Ensure that the `uv` CLI tool is installed in the current Python environment.
        
        Checks if `uv` is available by running `uv --version`.
        If not found, installs or upgrades `uv` using pip.
        
        Raises:
            subprocess.CalledProcessError: If the installation fails.
        """
        try:
            subprocess.run(
                ["uv", "--version"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.logger.info("✅ 'uv' is already installed.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.info("⬇️ 'uv' not found, installing...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "uv"],
                check=True,
            )
            self.logger.info("✅ 'uv' installed successfully.")

    def install_with_uv(self, server_root: Path, venv_path: Path) -> None:
        """
        Use the system-level `uv` to install the package located at `server_root`
        into the virtual environment specified by `venv_path`.
        
        Args:
            server_root (Path): Path to the root directory of the package to install.
            venv_path (Path): Path to the target virtual environment directory.
        
        Raises:
            subprocess.CalledProcessError: If the `uv pip install .` command fails.
        """
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_path / 'bin'}:{env.get('PATH', '')}"
        
        self.logger.info(f"Installing package at {server_root} into venv at {venv_path} using 'uv'...")
        
        subprocess.run(
            ["uv", "pip", "install", "."],
            cwd=server_root,
            env=env,
            check=True,
        )
        
        self.logger.info(f"✅ Package installed successfully into venv at {venv_path}.")
    
    def _setup_python_venvs(self) -> None:
        # self.logger.info('self.project_root=%s', self.project_root)
        self.logger.info('self.components=%s', self.components)

        for server_name, server_path in self.server_paths.items():
            try:
                server_root_path = self.find_server_root(server_path)
                self.logger.info(f'server {server_name} is at root {server_root_path}')
                venv_path = server_root_path / ".venv"
                self.create_venv(venv_path)
                self.ensure_uv_installed()
                self.install_with_uv(server_root_path, venv_path)
            except FileNotFoundError:
                self.logger.error('pyproject.toml not found in server root')
                raise
            except Exception as e:
                self.logger.error('Error setting up venv: %s', e)
                raise
    
    def _setup_server_paths(self) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, Any]]]]:
        """
        Process server configurations and resolve paths.
        
        Returns:
            Tuple of (server_paths, components) dictionaries.
        """
        server_paths = {}
        components = {}
        
        # Add core paths
        core_paths = self.config.get("core", {})
        for name, location in core_paths.items():
            full_path = os.path.join(self.project_root, location)
            # Always add path, even if it doesn't exist
            server_paths[name] = full_path
            
            if not os.path.exists(full_path):
                self.logger.warning(f"Core path does not exist: {full_path}")
        
        # Process MCP servers
        mcp_servers = self.config.get("mcp_servers", {})
        for server_name, server_config in mcp_servers.items():
            if isinstance(server_config, dict) and server_config.get("enabled", True):
                location = server_config.get("location")
                if location:
                    # Handle both absolute and relative paths
                    if os.path.isabs(location):
                        full_path = location
                    else:
                        full_path = os.path.join(self.project_root, location)
                    
                    # Always add server path
                    server_paths[server_name] = full_path
                    components[server_name] = []
                    
                    # Process components (tools, resources, prompts)
                    self._add_component(server_name, server_config, "tools", components)
                    self._add_component(server_name, server_config, "resources", components)
                    self._add_component(server_name, server_config, "prompts", components)
                    
                    if not os.path.exists(full_path):
                        self.logger.warning(f"MCP server location does not exist: {full_path}")
        
        # Auto-discovery for testing
        if self.config.get("auto_discover", False):
            self._auto_discover_servers(server_paths, components)
        
        core_servers = [name for name in server_paths.keys() if name in core_paths]
        mcp_servers_list = [name for name in server_paths.keys() if name not in core_paths]
        
        self.logger.debug(f"Core paths: {', '.join(core_servers) if core_servers else 'None'}")
        self.logger.debug(f"MCP servers: {', '.join(mcp_servers_list) if mcp_servers_list else 'None'}")
        
        return server_paths, components
    
    def _auto_discover_servers(self, server_paths: Dict[str, str], 
                              components: Dict[str, List[Dict[str, Any]]]) -> None:
        """
        Automatically discover test servers.
        
        Args:
            server_paths: Dictionary to add server paths to.
            components: Dictionary to add components to.
        """
        # Add known test servers
        test_servers = self.config.get("auto_discover_servers", [
            "time_server", 
            "echo_server", 
            "test_server"
        ])
        
        for server_name in test_servers:
            if server_name not in server_paths:
                # Create a mock path
                mock_path = os.path.join(self.project_root, "servers", server_name, "src")
                server_paths[server_name] = mock_path
                components[server_name] = []
                
                # Add a mock tools component
                components[server_name].append({
                    "type": "tools",
                    "module": f"{server_name}.tools",
                    "auto_discovered": True
                })
    
    def _add_component(self, server_name: str, server_config: Dict[str, Any], 
                       component_type: str, components: Dict[str, List[Dict[str, Any]]]) -> None:
        """
        Add a component (tools, resources, prompts) to the components dictionary.
        
        Args:
            server_name: Name of the server.
            server_config: Configuration for the server.
            component_type: Type of component (tools, resources, prompts).
            components: Dictionary to add the component to.
        """
        component_config = server_config.get(component_type, {})
        if not isinstance(component_config, dict):
            return
            
        enabled = component_config.get("enabled", True)
        module = component_config.get("module")
        
        if enabled and module:
            components[server_name].append({
                "type": component_type,
                "module": module,
                "auto_discovered": False
            })
    
    def _setup_python_paths(self) -> None:
        """Add server source directories to Python path"""
        # Add paths to sys.path in reverse order for correct priority
        paths = list(self.server_paths.values())
        for path in reversed(paths):
            if path not in sys.path:
                self.logger.debug(f"Adding {path} to sys.path")
                sys.path.insert(0, path)
    
    async def load_server_components(self) -> Dict[str, Any]:
        """
        Load all enabled components from configured servers.
        
        Returns:
            Dictionary of loaded modules.
        """
        # Set to track tool modules for scanning
        tool_modules: Set[str] = set()
        
        # Process each server and its components
        for server_name, server_components in self.components.items():
            for component in server_components:
                module_name = component["module"]
                component_type = component["type"]
                auto_discovered = component.get("auto_discovered", False)

                # Skip if already loaded
                # if module_name in self.loaded_modules:
                #     self.logger.debug(f"Module {module_name} already loaded")
                #     continue
                
                # For testing, always try to import the module
                try:
                    # self.logger.debug(f"Loading {component_type} from {module_name}" + 
                    #                (" (auto-discovered)" if auto_discovered else ""))
                    
                    # # Import the module
                    # self.loaded_modules[module_name] = importlib.import_module(module_name)
                    
                    # If it's a tools component, add to the scan list
                    if component_type == "tools":
                        tool_modules.add(module_name)
                except ImportError as e:
                    # If it's for testing, we'll catch the import error but not raise it
                    if auto_discovered:
                        self.logger.debug(f"Auto-discovered module {module_name} not found: {e}")
                    else:
                        self.logger.warning(f"Failed to import {module_name}: {e}")
        
        # Scan for tools in any tool modules
        if tool_modules:
            await scan_for_tools(list(tool_modules))
            # await get_tool_functions(list(tool_modules))

        
        # for tool_name, tool_func in tool_funcs.items():
            # self.logger.info(f'{tool_name=} {tool_func=}')
        
        return self.loaded_modules
        
    def get_loaded_modules(self) -> Dict[str, Any]:
        """
        Get all loaded modules.
        
        Returns:
            Dictionary of loaded modules.
        """
        return self.loaded_modules