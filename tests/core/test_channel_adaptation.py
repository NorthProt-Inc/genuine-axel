"""Tests for channel adaptation."""

import pytest
from backend.core.persona.channel_adaptation import (
    get_channel_hint,
    get_channel_config,
    ChannelConfig,
    DEFAULT_CHANNELS,
)


class TestChannelAdaptation:

    def test_discord_casual(self):
        hint = get_channel_hint("discord")
        assert "casual" in hint.lower()

    def test_unknown_channel_defaults(self):
        config = get_channel_config("unknown_channel")
        assert isinstance(config, ChannelConfig)
        assert config.formality == 0.3
        assert config.verbosity == 0.5

    def test_hint_string_format(self):
        hint = get_channel_hint("discord")
        assert isinstance(hint, str)
        assert len(hint) > 0

    def test_telegram_concise(self):
        hint = get_channel_hint("telegram")
        assert "concise" in hint.lower()

    def test_cli_casual(self):
        hint = get_channel_hint("cli")
        assert "casual" in hint.lower()

    def test_all_channels_have_config(self):
        for channel in DEFAULT_CHANNELS:
            config = get_channel_config(channel)
            assert 0 <= config.formality <= 1
            assert 0 <= config.verbosity <= 1
