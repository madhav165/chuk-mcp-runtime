# chuk_mcp_runtime/dependencies.py
"""
Centralized dependency management for CHUK MCP Runtime.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any, Dict, Optional, Set, Tuple, Type, TypeVar, Union
from dataclasses import dataclass, field

from chuk_mcp_runtime.logging import get_logger

T = TypeVar('T')

logger = get_logger("chuk_mcp_runtime.dependencies")


@dataclass
class DependencyInfo:
    """Information about a dependency."""
    name: str
    import_path: str
    install_command: str
    description: str
    required: bool = False
    alternatives: list[str] = field(default_factory=list)


class DependencyManager:
    """Centralized management of optional dependencies with lazy loading."""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._availability: Dict[str, bool] = {}
        self._failed_imports: Set[str] = set()
        
        # Define all known dependencies
        self._dependencies = {
            'chuk_artifacts': DependencyInfo(
                name='chuk_artifacts',
                import_path='chuk_artifacts',
                install_command='pip install chuk-artifacts',
                description='Artifact storage and management system',
                required=False
            ),
            'chuk_sessions': DependencyInfo(
                name='chuk_sessions',
                import_path='chuk_sessions',
                install_command='pip install chuk-sessions',
                description='Session management system',
                required=False
            ),
            'chuk_tool_processor': DependencyInfo(
                name='chuk_tool_processor',
                import_path='chuk_tool_processor',
                install_command='pip install chuk-tool-processor',
                description='Tool processing and registry system',
                required=False
            ),
            'pydantic': DependencyInfo(
                name='pydantic',
                import_path='pydantic',
                install_command='pip install pydantic',
                description='Data validation and schema generation',
                required=False
            ),
            'dotenv': DependencyInfo(
                name='dotenv',
                import_path='dotenv',
                install_command='pip install python-dotenv',
                description='Environment variable loading from .env files',
                required=False
            ),
            'jwt': DependencyInfo(
                name='jwt',
                import_path='jwt',
                install_command='pip install PyJWT',
                description='JSON Web Token implementation',
                required=True  # Used for authentication
            ),
            'mcp': DependencyInfo(
                name='mcp',
                import_path='mcp',
                install_command='pip install mcp',
                description='Model Context Protocol implementation',
                required=True
            ),
            'starlette': DependencyInfo(
                name='starlette',
                import_path='starlette',
                install_command='pip install starlette',
                description='ASGI framework for HTTP server',
                required=True
            ),
            'uvicorn': DependencyInfo(
                name='uvicorn',
                import_path='uvicorn',
                install_command='pip install uvicorn',
                description='ASGI server implementation',
                required=True
            ),
        }
    
    def is_available(self, package: str) -> bool:
        """Check if a package is available for import."""
        if package not in self._availability:
            try:
                importlib.import_module(package)
                self._availability[package] = True
                logger.debug(f"Dependency {package} is available")
            except ImportError:
                self._availability[package] = False
                self._failed_imports.add(package)
                if package in self._dependencies:
                    dep_info = self._dependencies[package]
                    if dep_info.required:
                        logger.error(f"Required dependency {package} is not available. Install with: {dep_info.install_command}")
                    else:
                        logger.debug(f"Optional dependency {package} is not available. Install with: {dep_info.install_command}")
        
        return self._availability[package]
    
    def get_module(self, package: str, fallback: Any = None, required: bool = False) -> Any:
        """
        Get module with caching and fallback.
        
        Args:
            package: Package name to import
            fallback: Fallback value if import fails (for optional deps)
            required: Whether this dependency is required
            
        Returns:
            The imported module or fallback value
            
        Raises:
            ImportError: If required dependency is not available
        """
        if package in self._cache:
            return self._cache[package]
        
        if self.is_available(package):
            try:
                module = importlib.import_module(package)
                self._cache[package] = module
                return module
            except ImportError as e:
                if required:
                    raise ImportError(f"Required dependency {package} failed to import: {e}") from e
                logger.warning(f"Failed to import {package}: {e}")
        
        if required:
            dep_info = self._dependencies.get(package)
            install_cmd = dep_info.install_command if dep_info else f"pip install {package}"
            raise ImportError(f"Required dependency {package} is not available. Install with: {install_cmd}")
        
        self._cache[package] = fallback
        return fallback
    
    def get_class(self, package: str, class_name: str, fallback: Optional[Type] = None, required: bool = False) -> Any:
        """
        Get a specific class from a module.
        
        Args:
            package: Package name
            class_name: Class name to import
            fallback: Fallback class if import fails
            required: Whether this is required
            
        Returns:
            The class or fallback
        """
        module = self.get_module(package, required=required)
        if module is None:
            return fallback
        
        try:
            return getattr(module, class_name)
        except AttributeError:
            if required:
                raise ImportError(f"Class {class_name} not found in {package}")
            logger.debug(f"Class {class_name} not found in {package}, using fallback")
            return fallback
    
    def get_function(self, package: str, function_name: str, fallback: Optional[callable] = None, required: bool = False) -> Any:
        """
        Get a specific function from a module.
        
        Args:
            package: Package name
            function_name: Function name to import
            fallback: Fallback function if import fails
            required: Whether this is required
            
        Returns:
            The function or fallback
        """
        module = self.get_module(package, required=required)
        if module is None:
            return fallback
        
        try:
            return getattr(module, function_name)
        except AttributeError:
            if required:
                raise ImportError(f"Function {function_name} not found in {package}")
            logger.debug(f"Function {function_name} not found in {package}, using fallback")
            return fallback
    
    def check_requirements(self) -> Tuple[bool, list[str]]:
        """
        Check all required dependencies.
        
        Returns:
            Tuple of (all_satisfied, missing_dependencies)
        """
        missing = []
        for dep_name, dep_info in self._dependencies.items():
            if dep_info.required and not self.is_available(dep_name):
                missing.append(f"{dep_name} ({dep_info.install_command})")
        
        return len(missing) == 0, missing
    
    def get_availability_report(self) -> Dict[str, Any]:
        """Get a report of all dependency availability."""
        report = {
            'available': {},
            'missing': {},
            'required_missing': [],
            'optional_missing': []
        }
        
        for dep_name, dep_info in self._dependencies.items():
            is_available = self.is_available(dep_name)
            
            if is_available:
                report['available'][dep_name] = {
                    'description': dep_info.description,
                    'required': dep_info.required
                }
            else:
                report['missing'][dep_name] = {
                    'description': dep_info.description,
                    'install_command': dep_info.install_command,
                    'required': dep_info.required
                }
                
                if dep_info.required:
                    report['required_missing'].append(dep_name)
                else:
                    report['optional_missing'].append(dep_name)
        
        return report
    
    def create_stub_class(self, class_name: str, error_message: str) -> Type:
        """Create a stub class that raises an error when instantiated."""
        
        class StubClass:
            def __init__(self, *args, **kwargs):
                raise ImportError(error_message)
        
        StubClass.__name__ = class_name
        StubClass.__qualname__ = class_name
        return StubClass
    
    def create_stub_function(self, function_name: str, error_message: str) -> callable:
        """Create a stub function that raises an error when called."""
        
        def stub_function(*args, **kwargs):
            raise ImportError(error_message)
        
        stub_function.__name__ = function_name
        return stub_function


# Global dependency manager instance
deps = DependencyManager()


# Convenience functions for common dependency patterns
def require_dependency(package: str) -> Any:
    """Require a dependency (raises ImportError if not available)."""
    return deps.get_module(package, required=True)


def optional_dependency(package: str, fallback: Any = None) -> Any:
    """Get an optional dependency with fallback."""
    return deps.get_module(package, fallback=fallback, required=False)


def check_all_requirements() -> None:
    """Check all required dependencies and raise if any are missing."""
    satisfied, missing = deps.check_requirements()
    if not satisfied:
        error_msg = "Missing required dependencies:\n" + "\n".join(f"  - {dep}" for dep in missing)
        raise ImportError(error_msg)


# Pre-configured dependency getters for common cases
def get_chuk_artifacts():
    """Get chuk_artifacts module or None if not available."""
    return deps.get_module('chuk_artifacts')


def get_chuk_sessions():
    """Get chuk_sessions module or None if not available."""
    return deps.get_module('chuk_sessions')


def get_pydantic():
    """Get pydantic module or None if not available."""
    return deps.get_module('pydantic')


def get_dotenv():
    """Get dotenv module or None if not available."""
    return deps.get_module('dotenv')


# Specific class/function getters with fallbacks
def get_artifact_store_class():
    """Get ArtifactStore class or a stub that raises ImportError."""
    return deps.get_class(
        'chuk_artifacts', 
        'ArtifactStore',
        fallback=deps.create_stub_class(
            'ArtifactStore',
            'chuk_artifacts package required. Install with: pip install chuk-artifacts'
        )
    )


def get_session_manager_class():
    """Get SessionManager class or a stub that raises ImportError."""
    return deps.get_class(
        'chuk_sessions.session_manager',
        'SessionManager', 
        fallback=deps.create_stub_class(
            'SessionManager',
            'chuk_sessions package required. Install with: pip install chuk-sessions'
        )
    )


def get_create_model_function():
    """Get pydantic's create_model function or None."""
    return deps.get_function('pydantic', 'create_model')


def get_load_dotenv_function():
    """Get python-dotenv's load_dotenv function or None."""
    return deps.get_function('dotenv', 'load_dotenv')


# Constants for availability checking
CHUK_ARTIFACTS_AVAILABLE = deps.is_available('chuk_artifacts')
CHUK_SESSIONS_AVAILABLE = deps.is_available('chuk_sessions')
PYDANTIC_AVAILABLE = deps.is_available('pydantic')
DOTENV_AVAILABLE = deps.is_available('dotenv')
CHUK_TOOL_PROCESSOR_AVAILABLE = deps.is_available('chuk_tool_processor')


# Export public API
__all__ = [
    'deps',
    'DependencyManager',
    'DependencyInfo',
    'require_dependency',
    'optional_dependency', 
    'check_all_requirements',
    'get_chuk_artifacts',
    'get_chuk_sessions',
    'get_pydantic',
    'get_dotenv',
    'get_artifact_store_class',
    'get_session_manager_class',
    'get_create_model_function',
    'get_load_dotenv_function',
    'CHUK_ARTIFACTS_AVAILABLE',
    'CHUK_SESSIONS_AVAILABLE', 
    'PYDANTIC_AVAILABLE',
    'DOTENV_AVAILABLE',
    'CHUK_TOOL_PROCESSOR_AVAILABLE',
]