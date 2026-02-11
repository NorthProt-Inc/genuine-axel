"""Plugin manifest and permission types."""

from dataclasses import dataclass, field
from enum import Enum


class PluginPermission(str, Enum):
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    TOOL_REGISTER = "tool:register"
    NETWORK = "network"
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"


@dataclass
class PluginManifest:
    """Plugin metadata and configuration."""

    name: str
    version: str
    description: str
    permissions: list[PluginPermission] = field(default_factory=list)
    author: str = ""
    config_schema: dict | None = None
