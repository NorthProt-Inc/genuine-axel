"""Tests for YAML-based device registry."""

import yaml
from pathlib import Path


class TestLoadDeviceConfig:
    """Loading device config from YAML."""

    def test_load_full_config(self, tmp_path: Path):
        """Should parse all sections from YAML."""
        config_data = {
            "lights": [
                {"entity_id": "light.test_1", "name": "Test 1"},
                {"entity_id": "light.test_2", "name": "Test 2"},
            ],
            "other_devices": {
                "printer": {"entity_id": "sensor.test_printer"},
            },
            "sensor_aliases": {
                "battery": "sensor.test_battery",
            },
            "sensor_groups": {
                "battery": ["sensor.test_battery"],
            },
        }
        yaml_path = tmp_path / "hass_devices.yaml"
        yaml_path.write_text(yaml.dump(config_data))

        from backend.core.tools.hass_device_registry import load_device_config

        result = load_device_config(yaml_path)

        assert result.lights == ["light.test_1", "light.test_2"]
        assert result.other_devices == {"printer": "sensor.test_printer"}
        assert result.sensor_aliases == {"battery": "sensor.test_battery"}
        assert result.sensor_groups == {"battery": ["sensor.test_battery"]}

    def test_missing_file_returns_defaults(self, tmp_path: Path):
        """Should return empty defaults when file doesn't exist."""
        from backend.core.tools.hass_device_registry import load_device_config

        result = load_device_config(tmp_path / "nonexistent.yaml")

        assert result.lights == []
        assert result.other_devices == {}
        assert result.sensor_aliases == {}
        assert result.sensor_groups == {}

    def test_partial_yaml(self, tmp_path: Path):
        """Should handle YAML with only some keys."""
        yaml_path = tmp_path / "partial.yaml"
        yaml_path.write_text(yaml.dump({"lights": [{"entity_id": "light.x"}]}))

        from backend.core.tools.hass_device_registry import load_device_config

        result = load_device_config(yaml_path)
        assert result.lights == ["light.x"]
        assert result.other_devices == {}

    def test_empty_yaml(self, tmp_path: Path):
        """Should handle empty YAML file."""
        yaml_path = tmp_path / "empty.yaml"
        yaml_path.write_text("")

        from backend.core.tools.hass_device_registry import load_device_config

        result = load_device_config(yaml_path)
        assert result.lights == []

    def test_light_names_preserved(self, tmp_path: Path):
        """Light names should be accessible via light_names property."""
        config_data = {
            "lights": [
                {"entity_id": "light.a", "name": "Light A"},
                {"entity_id": "light.b", "name": "Light B"},
            ],
        }
        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text(yaml.dump(config_data))

        from backend.core.tools.hass_device_registry import load_device_config

        result = load_device_config(yaml_path)
        assert result.light_names == {"light.a": "Light A", "light.b": "Light B"}


class TestDeviceConfigDataclass:
    """DeviceConfig dataclass structure."""

    def test_default_construction(self):
        from backend.core.tools.hass_device_registry import DeviceConfig

        cfg = DeviceConfig()
        assert cfg.lights == []
        assert cfg.other_devices == {}
        assert cfg.sensor_aliases == {}
        assert cfg.sensor_groups == {}

    def test_known_entities_union(self, tmp_path: Path):
        """known_entities should be union of all entity IDs."""
        config_data = {
            "lights": [{"entity_id": "light.a"}],
            "other_devices": {"fan": {"entity_id": "fan.b"}},
            "sensor_aliases": {"bat": "sensor.c"},
        }
        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text(yaml.dump(config_data))

        from backend.core.tools.hass_device_registry import load_device_config

        result = load_device_config(yaml_path)
        known = result.known_entities
        assert "light.a" in known
        assert "fan.b" in known
        assert "sensor.c" in known
