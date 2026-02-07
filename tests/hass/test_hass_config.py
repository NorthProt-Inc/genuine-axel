"""Tests for HASS configuration and dead code removal."""


class TestDeadCodeRemoval:
    """Module-level dead constants should be removed."""

    def test_no_module_level_max_retries(self):
        """MAX_RETRIES was dead code shadowed by _get_hass_config()."""
        import backend.core.tools.hass_ops as mod

        assert not hasattr(mod, "MAX_RETRIES")

    def test_get_hass_config_returns_tuple(self):
        """_get_hass_config should return (timeout, retries) from config."""
        from backend.core.tools.hass_ops import _get_hass_config

        timeout, retries = _get_hass_config()
        assert isinstance(timeout, float)
        assert isinstance(retries, int)
