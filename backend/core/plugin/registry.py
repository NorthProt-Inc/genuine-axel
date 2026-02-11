"""In-memory plugin registry."""

from backend.core.plugin.types import PluginManifest


class PluginRegistry:
    """Manages registered plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginManifest] = {}

    def register(self, manifest: PluginManifest) -> None:
        self._plugins[manifest.name] = manifest

    def unregister(self, name: str) -> None:
        self._plugins.pop(name, None)

    def get(self, name: str) -> PluginManifest | None:
        return self._plugins.get(name)

    def has(self, name: str) -> bool:
        return name in self._plugins

    def list_all(self) -> list[PluginManifest]:
        return list(self._plugins.values())
