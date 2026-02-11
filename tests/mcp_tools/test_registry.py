"""Tests for backend.core.mcp_tools.__init__ -- Tool registry and metrics.

Covers:
  - register_tool decorator
  - get_tool_handler / list_tools / get_tools_by_category
  - get_tool_metadata / is_tool_registered
  - get_tool_schemas (with MCP disabled filtering)
  - ToolMetrics dataclass and metrics functions
"""

import time
from unittest.mock import patch

import pytest

from backend.core.mcp_tools import (
    ToolMetrics,
    _tool_handlers,
    _tool_metadata,
    _tool_metrics,
    get_all_metrics,
    get_tool_handler,
    get_tool_metadata,
    get_tool_metrics,
    get_tool_schemas,
    get_tools_by_category,
    is_tool_registered,
    list_tools,
    register_tool,
    reset_metrics,
)


# ===========================================================================
# ToolMetrics dataclass
# ===========================================================================


class TestToolMetrics:
    def test_defaults(self):
        m = ToolMetrics()
        assert m.call_count == 0
        assert m.success_count == 0
        assert m.error_count == 0
        assert m.total_duration_ms == 0.0
        assert m.last_call_at is None
        assert m.last_error is None
        assert m.last_error_at is None

    def test_avg_duration_zero_calls(self):
        m = ToolMetrics()
        assert m.avg_duration_ms == 0.0

    def test_avg_duration_computed(self):
        m = ToolMetrics(call_count=4, total_duration_ms=200.0)
        assert m.avg_duration_ms == 50.0

    def test_success_rate_zero_calls(self):
        m = ToolMetrics()
        assert m.success_rate == 0.0

    def test_success_rate_computed(self):
        m = ToolMetrics(call_count=10, success_count=7)
        assert m.success_rate == pytest.approx(0.7)

    def test_to_dict_keys(self):
        m = ToolMetrics(call_count=1, success_count=1, total_duration_ms=42.567)
        d = m.to_dict()
        expected_keys = {
            "call_count",
            "success_count",
            "error_count",
            "avg_duration_ms",
            "total_duration_ms",
            "success_rate",
            "last_call_at",
            "last_error",
            "last_error_at",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_durations_rounded(self):
        m = ToolMetrics(call_count=3, total_duration_ms=100.12345)
        d = m.to_dict()
        assert d["total_duration_ms"] == 100.12
        assert d["avg_duration_ms"] == 33.37  # 100.12345/3 rounded to 2dp

    def test_to_dict_success_rate_formatted(self):
        m = ToolMetrics(call_count=4, success_count=3)
        d = m.to_dict()
        assert d["success_rate"] == "75.0%"

    def test_to_dict_last_error_truncated(self):
        m = ToolMetrics(last_error="x" * 200)
        d = m.to_dict()
        assert len(d["last_error"]) == 100

    def test_to_dict_last_error_none(self):
        m = ToolMetrics()
        d = m.to_dict()
        assert d["last_error"] is None


# ===========================================================================
# register_tool decorator
# ===========================================================================


class TestRegisterTool:
    def test_registers_handler(self):
        @register_tool("_test_tool_a", category="test")
        async def handler_a(args):
            return "ok"

        assert "_test_tool_a" in _tool_handlers
        assert _tool_handlers["_test_tool_a"] is handler_a

    def test_registers_metadata(self):
        @register_tool(
            "_test_tool_b",
            category="test",
            description="Test description",
            input_schema={"type": "object"},
        )
        async def handler_b(args):
            """Handler docstring."""
            return "ok"

        meta = _tool_metadata["_test_tool_b"]
        assert meta["category"] == "test"
        assert meta["description"] == "Test description"
        assert meta["input_schema"] == {"type": "object"}
        assert meta["docstring"] == "Handler docstring."

    def test_overwrite_logs_warning(self):
        @register_tool("_test_overwrite", category="test")
        async def first(args):
            return "first"

        # Re-register same name -- should not raise, just warn
        @register_tool("_test_overwrite", category="test")
        async def second(args):
            return "second"

        # The second handler replaces the first
        assert _tool_handlers["_test_overwrite"] is second

    async def test_wrapper_tracks_success_metrics(self):
        @register_tool("_test_metric_ok", category="test")
        async def handler_ok(args):
            return "result"

        await handler_ok({})

        metrics = _tool_metrics["_test_metric_ok"]
        assert metrics.call_count == 1
        assert metrics.success_count == 1
        assert metrics.error_count == 0
        assert metrics.total_duration_ms > 0
        assert metrics.last_call_at is not None

    async def test_wrapper_tracks_error_metrics(self):
        @register_tool("_test_metric_err", category="test")
        async def handler_err(args):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await handler_err({})

        metrics = _tool_metrics["_test_metric_err"]
        assert metrics.call_count == 1
        assert metrics.success_count == 0
        assert metrics.error_count == 1
        assert metrics.last_error == "boom"
        assert metrics.last_error_at is not None

    async def test_wrapper_accumulates_duration(self):
        @register_tool("_test_duration", category="test")
        async def handler_dur(args):
            return "ok"

        await handler_dur({})
        await handler_dur({})

        metrics = _tool_metrics["_test_duration"]
        assert metrics.call_count == 2
        assert metrics.success_count == 2


# ===========================================================================
# get_tool_handler
# ===========================================================================


class TestGetToolHandler:
    def test_existing_tool(self):
        @register_tool("_test_get_handler", category="test")
        async def h(args):
            return "ok"

        assert get_tool_handler("_test_get_handler") is h

    def test_unknown_tool_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown tool"):
            get_tool_handler("_nonexistent_tool_xyz")


# ===========================================================================
# list_tools
# ===========================================================================


class TestListTools:
    def test_returns_sorted_list(self):
        @register_tool("_test_zzz", category="test")
        async def hz(args):
            pass

        @register_tool("_test_aaa", category="test")
        async def ha(args):
            pass

        result = list_tools()
        assert isinstance(result, list)
        # Verify sorted order
        assert result == sorted(result)
        assert "_test_aaa" in result
        assert "_test_zzz" in result


# ===========================================================================
# get_tools_by_category
# ===========================================================================


class TestGetToolsByCategory:
    def test_filters_by_category(self):
        @register_tool("_test_cat_a", category="alpha")
        async def ha(args):
            pass

        @register_tool("_test_cat_b", category="beta")
        async def hb(args):
            pass

        alpha_tools = get_tools_by_category("alpha")
        assert "_test_cat_a" in alpha_tools
        assert "_test_cat_b" not in alpha_tools

    def test_empty_category(self):
        result = get_tools_by_category("_nonexistent_category_xyz")
        assert result == []


# ===========================================================================
# get_tool_metadata
# ===========================================================================


class TestGetToolMetadata:
    def test_existing_tool(self):
        @register_tool(
            "_test_meta",
            category="test",
            description="Meta test",
            input_schema={"type": "object"},
        )
        async def hm(args):
            """My docstring."""
            pass

        meta = get_tool_metadata("_test_meta")
        assert meta is not None
        assert meta["category"] == "test"
        assert meta["description"] == "Meta test"
        assert meta["docstring"] == "My docstring."

    def test_nonexistent_returns_none(self):
        assert get_tool_metadata("_nonexistent_meta_xyz") is None


# ===========================================================================
# is_tool_registered
# ===========================================================================


class TestIsToolRegistered:
    def test_registered(self):
        @register_tool("_test_is_reg", category="test")
        async def hr(args):
            pass

        assert is_tool_registered("_test_is_reg") is True

    def test_unregistered(self):
        assert is_tool_registered("_unregistered_xyz") is False


# ===========================================================================
# get_tool_schemas (MCP visibility filtering)
# ===========================================================================


class TestGetToolSchemas:
    @patch("backend.config.MCP_DISABLED_TOOLS", set())
    @patch("backend.config.MCP_DISABLED_CATEGORIES", set())
    def test_returns_tools_with_input_schema(self):
        @register_tool(
            "_test_schema_vis",
            category="test",
            description="Visible tool",
            input_schema={"type": "object", "properties": {}},
        )
        async def hv(args):
            pass

        schemas = get_tool_schemas()
        names = [t.name for t in schemas]
        assert "_test_schema_vis" in names

    @patch("backend.config.MCP_DISABLED_TOOLS", set())
    @patch("backend.config.MCP_DISABLED_CATEGORIES", set())
    def test_skips_tools_without_input_schema(self):
        @register_tool("_test_no_schema", category="test", description="No schema")
        async def hns(args):
            pass

        schemas = get_tool_schemas()
        names = [t.name for t in schemas]
        assert "_test_no_schema" not in names

    @patch("backend.config.MCP_DISABLED_TOOLS", {"_test_disabled"})
    @patch("backend.config.MCP_DISABLED_CATEGORIES", set())
    def test_disabled_tool_excluded(self):
        @register_tool(
            "_test_disabled",
            category="test",
            description="Disabled tool",
            input_schema={"type": "object", "properties": {}},
        )
        async def hd(args):
            pass

        schemas = get_tool_schemas()
        names = [t.name for t in schemas]
        assert "_test_disabled" not in names

    @patch("backend.config.MCP_DISABLED_TOOLS", set())
    @patch("backend.config.MCP_DISABLED_CATEGORIES", {"blocked_cat"})
    def test_disabled_category_excluded(self):
        @register_tool(
            "_test_blocked_cat",
            category="blocked_cat",
            description="Blocked category tool",
            input_schema={"type": "object", "properties": {}},
        )
        async def hbc(args):
            pass

        schemas = get_tool_schemas()
        names = [t.name for t in schemas]
        assert "_test_blocked_cat" not in names

    @patch("backend.config.MCP_DISABLED_TOOLS", set())
    @patch("backend.config.MCP_DISABLED_CATEGORIES", set())
    def test_description_falls_back_to_docstring(self):
        @register_tool(
            "_test_docstring_desc",
            category="test",
            input_schema={"type": "object", "properties": {}},
        )
        async def hdd(args):
            """First line of docstring.\nSecond line."""
            pass

        schemas = get_tool_schemas()
        tool = next(t for t in schemas if t.name == "_test_docstring_desc")
        assert tool.description == "First line of docstring."

    @patch("backend.config.MCP_DISABLED_TOOLS", set())
    @patch("backend.config.MCP_DISABLED_CATEGORIES", set())
    def test_description_falls_back_to_tool_name(self):
        @register_tool(
            "_test_no_desc",
            category="test",
            input_schema={"type": "object", "properties": {}},
        )
        async def hnd(args):
            pass

        # Overwrite docstring to None
        _tool_metadata["_test_no_desc"]["docstring"] = None

        schemas = get_tool_schemas()
        tool = next(t for t in schemas if t.name == "_test_no_desc")
        assert tool.description == "Tool: _test_no_desc"

    @patch("backend.config.MCP_DISABLED_TOOLS", set())
    @patch("backend.config.MCP_DISABLED_CATEGORIES", set())
    def test_returns_mcp_tool_objects(self):
        from mcp.types import Tool

        @register_tool(
            "_test_tool_type",
            category="test",
            description="Type check",
            input_schema={"type": "object", "properties": {}},
        )
        async def htt(args):
            pass

        schemas = get_tool_schemas()
        tool = next(t for t in schemas if t.name == "_test_tool_type")
        assert isinstance(tool, Tool)
        assert tool.inputSchema == {"type": "object", "properties": {}}


# ===========================================================================
# Metrics functions
# ===========================================================================


class TestMetricsFunctions:
    async def test_get_tool_metrics_after_call(self):
        @register_tool("_test_gm", category="test")
        async def hgm(args):
            return "ok"

        await hgm({})

        result = get_tool_metrics("_test_gm")
        assert result is not None
        assert result["call_count"] == 1
        assert result["success_count"] == 1

    def test_get_tool_metrics_unregistered(self):
        assert get_tool_metrics("_nonexistent_metrics_xyz") is None

    async def test_get_all_metrics(self):
        @register_tool("_test_all_m", category="test")
        async def ham(args):
            return "ok"

        await ham({})

        all_m = get_all_metrics()
        assert "_test_all_m" in all_m
        assert all_m["_test_all_m"]["call_count"] == 1

    async def test_reset_metrics_specific(self):
        @register_tool("_test_reset_one", category="test")
        async def hro(args):
            return "ok"

        await hro({})
        assert _tool_metrics["_test_reset_one"].call_count == 1

        reset_metrics("_test_reset_one")
        assert _tool_metrics["_test_reset_one"].call_count == 0

    async def test_reset_metrics_all(self):
        @register_tool("_test_reset_all_a", category="test")
        async def hra(args):
            return "ok"

        @register_tool("_test_reset_all_b", category="test")
        async def hrb(args):
            return "ok"

        await hra({})
        await hrb({})

        reset_metrics()
        assert len(_tool_metrics) == 0

    def test_reset_metrics_nonexistent_no_error(self):
        reset_metrics("_totally_fake_name")  # should not raise
