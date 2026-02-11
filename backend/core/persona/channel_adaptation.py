"""Per-channel formality/verbosity tuning."""

from dataclasses import dataclass
from typing import Dict
from backend.core.logging import get_logger

_log = get_logger("core.persona")


@dataclass
class ChannelConfig:
    """Channel-specific configuration."""

    formality: float = 0.3  # 0.0 (casual) - 1.0 (formal)
    verbosity: float = 0.5  # 0.0 (terse) - 1.0 (verbose)


DEFAULT_CHANNELS: Dict[str, ChannelConfig] = {
    "discord": ChannelConfig(0.2, 0.3),
    "telegram": ChannelConfig(0.1, 0.2),
    "slack": ChannelConfig(0.5, 0.5),
    "cli": ChannelConfig(0.0, 0.4),
    "webchat": ChannelConfig(0.3, 0.5),
    "mcp": ChannelConfig(0.4, 0.6),
}


def get_channel_config(channel_id: str) -> ChannelConfig:
    """Get configuration for a channel.

    Args:
        channel_id: Channel identifier

    Returns:
        ChannelConfig for the channel (default if unknown)
    """
    return DEFAULT_CHANNELS.get(channel_id, ChannelConfig())


def get_channel_hint(channel_id: str) -> str:
    """Generate persona hint for channel.

    Args:
        channel_id: Channel identifier

    Returns:
        Hint string for LLM persona tuning
    """
    config = get_channel_config(channel_id)
    hints = []

    if config.formality < 0.3:
        hints.append("casual tone, use contractions")
    elif config.formality > 0.6:
        hints.append("formal and professional")

    if config.verbosity < 0.3:
        hints.append("be concise, short responses")
    elif config.verbosity > 0.7:
        hints.append("detailed explanations welcome")

    return ". ".join(hints) if hints else ""
