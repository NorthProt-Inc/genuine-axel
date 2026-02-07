"""Tests for parse_color function in hass_ops."""

from backend.core.tools.hass_ops import parse_color


class TestParseColorNamedColors:
    """Named color lookups from COLOR_MAP."""

    def test_warmwhite_returns_warm_rgb(self):
        result = parse_color("warmwhite")
        assert result is not None
        assert result == [255, 200, 150]

    def test_warm_white_with_space(self):
        result = parse_color("warm white")
        assert result is not None
        assert result == [255, 200, 150]

    def test_existing_warm_still_works(self):
        assert parse_color("warm") == [255, 200, 150]

    def test_red(self):
        assert parse_color("red") == [255, 0, 0]

    def test_korean_color(self):
        assert parse_color("빨강") == [255, 0, 0]


class TestParseColorHex:
    """Hex color parsing."""

    def test_hex_with_hash(self):
        assert parse_color("#FF0000") == [255, 0, 0]

    def test_hex_without_hash(self):
        assert parse_color("00FF00") == [0, 255, 0]

    def test_hex_lowercase(self):
        assert parse_color("#ff0000") == [255, 0, 0]


class TestParseColorHSL:
    """HSL color parsing."""

    def test_hsl_format(self):
        result = parse_color("hsl(0,100,50)")
        assert result is not None
        assert len(result) == 3


class TestParseColorRGB:
    """RGB color parsing."""

    def test_rgb_format(self):
        result = parse_color("rgb(255,0,0)")
        assert result == [255, 0, 0]


class TestParseColorEdgeCases:
    """Edge cases and invalid input."""

    def test_empty_string_returns_none(self):
        assert parse_color("") is None

    def test_none_returns_none(self):
        assert parse_color(None) is None

    def test_unknown_color_returns_none(self):
        assert parse_color("nonexistent_color_xyz") is None

    def test_whitespace_handling(self):
        assert parse_color("  red  ") == [255, 0, 0]
