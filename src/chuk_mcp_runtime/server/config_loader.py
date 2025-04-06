# chuk_mcp_runtime/server/config_loader.py
"""
Configuration Loader Module

This module provides functionality to load and manage 
configuration files for CHUK MCP servers from multiple potential locations.
"""
import os
import yaml
import logging
from typing import Dict, Any, List, Optional

# logger
logger = logging.getLogger("chuk_mcp_runtime.config")

def load_config(config_paths: Optional[List[str]] = None, 
                default_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Load server configuration from config files.
    
    Args:
        config_paths: List of paths to search for config files. If None, uses default search paths.
        default_config: Default configuration to use if no config file is found.
    
    Returns:
        A dictionary containing the configuration settings.
    """
    if config_paths is None:
        # Default search paths relative to current working directory
        config_paths = [
            os.path.join(os.getcwd(), "config.yaml"),
            os.path.join(os.getcwd(), "config.yml"),
            os.environ.get("CHUK_MCP_CONFIG_PATH", ""),
        ]
        
        # Add config in package directory if run from package
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_paths.append(os.path.join(package_dir, "config.yaml"))
    
    # Filter out empty paths
    config_paths = [p for p in config_paths if p]
    
    # Try to load from each path
    for path in config_paths:
        if os.path.exists(path):
            logger.info(f"Loading configuration from {path}")
            try:
                with open(path, 'r') as f:
                    config = yaml.safe_load(f)
                    if config is None:  # Empty YAML file
                        continue
                    return config
            except Exception as e:
                logger.warning(f"Error loading config from {path}: {e}")
    
    # Use default configuration if provided or create a minimal one
    if default_config is None:
        logger.warning("No configuration file found, using minimal default configuration")
        default_config = {
            "host": {
                "name": "generic-mcp-server", 
                "log_level": "INFO"
            },
            "mcp_servers": {}
        }
    else:
        logger.warning("No configuration file found, using provided default configuration")
    
    return default_config

def find_project_root(start_dir: Optional[str] = None) -> str:
    """
    Find the project root directory by looking for markers like config.yaml,
    pyproject.toml, etc.
    
    Args:
        start_dir: Directory to start the search from. If None, uses current directory.
    
    Returns:
        Absolute path to the project root directory.
    """
    if start_dir is None:
        start_dir = os.getcwd()
    
    current_dir = os.path.abspath(start_dir)
    
    # Markers that indicate a project root
    markers = ['config.yaml', 'config.yml', 'pyproject.toml', 'setup.py']
    
    # Maximum depth to search up
    max_depth = 10
    depth = 0
    
    while depth < max_depth:
        # Check if any markers exist in current directory
        if any(os.path.exists(os.path.join(current_dir, marker)) for marker in markers):
            return current_dir
        
        # Go up one directory
        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:  # Reached the filesystem root
            break
        
        current_dir = parent_dir
        depth += 1
    
    # If no project root found, return the starting directory
    logger.warning(f"No project root markers found, using {start_dir} as project root")
    return os.path.abspath(start_dir)

def get_config_value(config: Dict[str, Any], path: str, default: Any = None) -> Any:
    """
    Get a value from a nested configuration dictionary using a dot-separated path.
    
    Args:
        config: Configuration dictionary.
        path: Dot-separated path to the value (e.g., "host.name").
        default: Default value to return if the path is not found.
    
    Returns:
        The value at the specified path, or the default value if not found.
    """
    keys = path.split('.')
    result = config
    
    for key in keys:
        if isinstance(result, dict) and key in result:
            result = result[key]
        else:
            return default
    
    return result