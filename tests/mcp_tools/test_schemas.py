"""Tests for backend.core.mcp_tools.schemas -- Pydantic input validation.

Each schema is tested for:
  - Valid input accepted
  - Default values applied correctly
  - Boundary values (min/max) accepted/rejected
  - Custom field_validators behave correctly
  - Enum values validated
"""

import pytest
from pydantic import ValidationError

from backend.core.mcp_tools.schemas import (
    AddMemoryInput,
    DeepResearchInput,
    DelegateToOpusInput,
    DeviceAction,
    GoogleDeepResearchInput,
    HassControlDeviceInput,
    HassControlLightInput,
    HassReadSensorInput,
    LightAction,
    MemoryCategory,
    ReadSystemLogsInput,
    RetrieveContextInput,
    RunCommandInput,
    SearchCodebaseInput,
    SearchDepth,
    StoreMemoryInput,
    TavilySearchInput,
    VisitWebpageInput,
    WebSearchInput,
)


# ===========================================================================
# Enums
# ===========================================================================


class TestLightAction:
    def test_values(self):
        assert LightAction.TURN_ON == "turn_on"
        assert LightAction.TURN_OFF == "turn_off"

    def test_is_str_enum(self):
        assert isinstance(LightAction.TURN_ON, str)

    def test_members_count(self):
        assert len(LightAction) == 2


class TestDeviceAction:
    def test_values(self):
        assert DeviceAction.TURN_ON == "turn_on"
        assert DeviceAction.TURN_OFF == "turn_off"

    def test_is_str_enum(self):
        assert isinstance(DeviceAction.TURN_ON, str)


class TestMemoryCategory:
    def test_all_members(self):
        names = {m.value for m in MemoryCategory}
        assert names == {"fact", "preference", "conversation", "insight"}

    def test_is_str_enum(self):
        assert isinstance(MemoryCategory.FACT, str)


class TestSearchDepth:
    def test_values(self):
        assert SearchDepth.BASIC == "basic"
        assert SearchDepth.ADVANCED == "advanced"


# ===========================================================================
# Home Assistant Schemas
# ===========================================================================


class TestHassControlLightInput:
    def test_minimal_valid(self):
        m = HassControlLightInput(action=LightAction.TURN_ON)
        assert m.entity_id == "all"
        assert m.brightness is None
        assert m.color is None

    def test_full_valid(self):
        m = HassControlLightInput(
            entity_id="light.living_room",
            action=LightAction.TURN_OFF,
            brightness=75,
            color="#FF0000",
        )
        assert m.entity_id == "light.living_room"
        assert m.brightness == 75
        assert m.color == "#FF0000"

    def test_entity_id_all_accepted(self):
        m = HassControlLightInput(entity_id="all", action="turn_on")
        assert m.entity_id == "all"

    def test_entity_id_domain_dot_entity_accepted(self):
        m = HassControlLightInput(entity_id="light.kitchen", action="turn_on")
        assert m.entity_id == "light.kitchen"

    def test_entity_id_without_dot_rejected(self):
        with pytest.raises(ValidationError, match="entity_id"):
            HassControlLightInput(entity_id="nodot", action="turn_on")

    def test_brightness_zero(self):
        m = HassControlLightInput(action="turn_on", brightness=0)
        assert m.brightness == 0

    def test_brightness_100(self):
        m = HassControlLightInput(action="turn_on", brightness=100)
        assert m.brightness == 100

    def test_brightness_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            HassControlLightInput(action="turn_on", brightness=-1)

    def test_brightness_above_100_rejected(self):
        with pytest.raises(ValidationError):
            HassControlLightInput(action="turn_on", brightness=101)

    # --- color validator ---

    def test_color_none(self):
        m = HassControlLightInput(action="turn_on", color=None)
        assert m.color is None

    def test_color_valid_hex(self):
        m = HassControlLightInput(action="turn_on", color="#00FF00")
        assert m.color == "#00FF00"

    def test_color_invalid_hex_rejected(self):
        with pytest.raises(ValidationError, match="hex"):
            HassControlLightInput(action="turn_on", color="#GGG")

    def test_color_hex_lowercase_accepted(self):
        m = HassControlLightInput(action="turn_on", color="#aabbcc")
        assert m.color == "#aabbcc"

    def test_color_hex_too_short_rejected(self):
        with pytest.raises(ValidationError, match="hex"):
            HassControlLightInput(action="turn_on", color="#FFF")

    def test_color_valid_hsl(self):
        m = HassControlLightInput(action="turn_on", color="hsl(240,100,50)")
        assert m.color == "hsl(240,100,50)"

    def test_color_invalid_hsl_format_rejected(self):
        with pytest.raises(ValidationError, match="hsl"):
            HassControlLightInput(action="turn_on", color="hsl(240, 100, 50)")

    def test_color_named_allowed(self):
        m = HassControlLightInput(action="turn_on", color="red")
        assert m.color == "red"

    def test_color_whitespace_stripped(self):
        m = HassControlLightInput(action="turn_on", color="  blue  ")
        assert m.color == "blue"

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            HassControlLightInput(action="toggle")


class TestHassControlDeviceInput:
    def test_valid(self):
        m = HassControlDeviceInput(entity_id="fan.bedroom", action=DeviceAction.TURN_ON)
        assert m.entity_id == "fan.bedroom"

    def test_entity_id_without_dot_rejected(self):
        with pytest.raises(ValidationError, match="entity_id"):
            HassControlDeviceInput(entity_id="nodot", action="turn_on")

    def test_entity_id_required(self):
        with pytest.raises(ValidationError):
            HassControlDeviceInput(action="turn_on")


class TestHassReadSensorInput:
    def test_valid(self):
        m = HassReadSensorInput(query="battery")
        assert m.query == "battery"

    def test_full_entity_id(self):
        m = HassReadSensorInput(query="sensor.temperature")
        assert m.query == "sensor.temperature"

    def test_query_required(self):
        with pytest.raises(ValidationError):
            HassReadSensorInput()


# ===========================================================================
# Memory Schemas
# ===========================================================================


class TestStoreMemoryInput:
    def test_minimal_valid(self):
        m = StoreMemoryInput(content="User's name is Bob")
        assert m.category == MemoryCategory.CONVERSATION
        assert m.importance == 0.5

    def test_full_valid(self):
        m = StoreMemoryInput(
            content="Important fact",
            category=MemoryCategory.FACT,
            importance=0.9,
        )
        assert m.category == MemoryCategory.FACT
        assert m.importance == 0.9

    def test_content_min_length_enforced(self):
        with pytest.raises(ValidationError):
            StoreMemoryInput(content="")

    def test_content_max_length_enforced(self):
        with pytest.raises(ValidationError):
            StoreMemoryInput(content="x" * 10001)

    def test_content_at_max_length_accepted(self):
        m = StoreMemoryInput(content="x" * 10000)
        assert len(m.content) == 10000

    def test_importance_zero_accepted(self):
        m = StoreMemoryInput(content="test", importance=0.0)
        assert m.importance == 0.0

    def test_importance_one_accepted(self):
        m = StoreMemoryInput(content="test", importance=1.0)
        assert m.importance == 1.0

    def test_importance_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            StoreMemoryInput(content="test", importance=-0.1)

    def test_importance_above_one_rejected(self):
        with pytest.raises(ValidationError):
            StoreMemoryInput(content="test", importance=1.1)

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            StoreMemoryInput(content="test", category="invalid")


class TestRetrieveContextInput:
    def test_minimal_valid(self):
        m = RetrieveContextInput(query="user preferences")
        assert m.max_results == 10

    def test_max_results_boundary(self):
        m = RetrieveContextInput(query="test", max_results=1)
        assert m.max_results == 1
        m = RetrieveContextInput(query="test", max_results=25)
        assert m.max_results == 25

    def test_max_results_below_one_rejected(self):
        with pytest.raises(ValidationError):
            RetrieveContextInput(query="test", max_results=0)

    def test_max_results_above_25_rejected(self):
        with pytest.raises(ValidationError):
            RetrieveContextInput(query="test", max_results=26)

    def test_query_min_length(self):
        with pytest.raises(ValidationError):
            RetrieveContextInput(query="")

    def test_query_max_length(self):
        with pytest.raises(ValidationError):
            RetrieveContextInput(query="x" * 501)


class TestAddMemoryInput:
    def test_minimal_valid(self):
        m = AddMemoryInput(content="Remember this")
        assert m.category == "observation"

    def test_all_categories(self):
        for cat in ["observation", "fact", "code"]:
            m = AddMemoryInput(content="test", category=cat)
            assert m.category == cat

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            AddMemoryInput(content="test", category="preference")

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            AddMemoryInput(content="")


# ===========================================================================
# Research Schemas
# ===========================================================================


class TestWebSearchInput:
    def test_minimal_valid(self):
        m = WebSearchInput(query="python asyncio")
        assert m.num_results == 5

    def test_query_min_length(self):
        with pytest.raises(ValidationError):
            WebSearchInput(query="x")  # min_length=2

    def test_query_at_min_length(self):
        m = WebSearchInput(query="ab")
        assert m.query == "ab"

    def test_num_results_boundaries(self):
        WebSearchInput(query="test", num_results=1)
        WebSearchInput(query="test", num_results=10)
        with pytest.raises(ValidationError):
            WebSearchInput(query="test", num_results=0)
        with pytest.raises(ValidationError):
            WebSearchInput(query="test", num_results=11)


class TestVisitWebpageInput:
    def test_valid_https(self):
        m = VisitWebpageInput(url="https://example.com")
        assert m.url == "https://example.com"

    def test_valid_http(self):
        m = VisitWebpageInput(url="http://example.com")
        assert m.url == "http://example.com"

    def test_missing_scheme_rejected(self):
        with pytest.raises(ValidationError, match="http"):
            VisitWebpageInput(url="example.com")

    def test_ftp_rejected(self):
        with pytest.raises(ValidationError, match="http"):
            VisitWebpageInput(url="ftp://example.com")

    def test_whitespace_stripped(self):
        m = VisitWebpageInput(url="  https://example.com  ")
        assert m.url == "https://example.com"


class TestDeepResearchInput:
    def test_valid(self):
        m = DeepResearchInput(query="How does GraphRAG work?")
        assert m.query == "How does GraphRAG work?"

    def test_min_length(self):
        with pytest.raises(ValidationError):
            DeepResearchInput(query="ab")  # min_length=3

    def test_at_min_length(self):
        m = DeepResearchInput(query="abc")
        assert m.query == "abc"


class TestTavilySearchInput:
    def test_minimal_valid(self):
        m = TavilySearchInput(query="test query")
        assert m.max_results == 5
        assert m.search_depth == SearchDepth.BASIC

    def test_advanced_depth(self):
        m = TavilySearchInput(query="test", search_depth=SearchDepth.ADVANCED)
        assert m.search_depth == SearchDepth.ADVANCED

    def test_max_results_boundaries(self):
        TavilySearchInput(query="test", max_results=1)
        TavilySearchInput(query="test", max_results=10)
        with pytest.raises(ValidationError):
            TavilySearchInput(query="test", max_results=0)
        with pytest.raises(ValidationError):
            TavilySearchInput(query="test", max_results=11)

    def test_query_min_length(self):
        with pytest.raises(ValidationError):
            TavilySearchInput(query="x")  # min_length=2


class TestGoogleDeepResearchInput:
    def test_minimal_valid(self):
        m = GoogleDeepResearchInput(query="What is quantum computing?")
        assert m.depth == 3
        assert m.async_mode is True

    def test_depth_boundaries(self):
        GoogleDeepResearchInput(query="valid query text", depth=1)
        GoogleDeepResearchInput(query="valid query text", depth=5)
        with pytest.raises(ValidationError):
            GoogleDeepResearchInput(query="valid query text", depth=0)
        with pytest.raises(ValidationError):
            GoogleDeepResearchInput(query="valid query text", depth=6)

    def test_query_min_length(self):
        with pytest.raises(ValidationError):
            GoogleDeepResearchInput(query="abcd")  # min_length=5

    def test_async_mode_false(self):
        m = GoogleDeepResearchInput(query="valid query text", async_mode=False)
        assert m.async_mode is False


# ===========================================================================
# System Schemas
# ===========================================================================


class TestRunCommandInput:
    def test_minimal_valid(self):
        m = RunCommandInput(command="ls -la")
        assert m.cwd is None
        assert m.timeout == 180

    def test_full_valid(self):
        m = RunCommandInput(command="echo hello", cwd="/tmp", timeout=60)
        assert m.cwd == "/tmp"
        assert m.timeout == 60

    def test_empty_command_rejected(self):
        with pytest.raises(ValidationError):
            RunCommandInput(command="")

    def test_timeout_boundaries(self):
        RunCommandInput(command="x", timeout=1)
        RunCommandInput(command="x", timeout=600)
        with pytest.raises(ValidationError):
            RunCommandInput(command="x", timeout=0)
        with pytest.raises(ValidationError):
            RunCommandInput(command="x", timeout=601)


class TestSearchCodebaseInput:
    def test_minimal_valid(self):
        m = SearchCodebaseInput(keyword="TODO")
        assert m.file_pattern == "*.py"
        assert m.case_sensitive is False
        assert m.max_results == 50

    def test_custom_values(self):
        m = SearchCodebaseInput(
            keyword="func",
            file_pattern="*.js",
            case_sensitive=True,
            max_results=10,
        )
        assert m.file_pattern == "*.js"
        assert m.case_sensitive is True
        assert m.max_results == 10

    def test_max_results_boundaries(self):
        SearchCodebaseInput(keyword="x", max_results=1)
        SearchCodebaseInput(keyword="x", max_results=100)
        with pytest.raises(ValidationError):
            SearchCodebaseInput(keyword="x", max_results=0)
        with pytest.raises(ValidationError):
            SearchCodebaseInput(keyword="x", max_results=101)


class TestReadSystemLogsInput:
    def test_defaults(self):
        m = ReadSystemLogsInput()
        assert m.log_file == "backend.log"
        assert m.lines == 50
        assert m.filter_keyword is None

    def test_custom_values(self):
        m = ReadSystemLogsInput(log_file="app.log", lines=200, filter_keyword="ERROR")
        assert m.log_file == "app.log"
        assert m.lines == 200
        assert m.filter_keyword == "ERROR"

    def test_lines_boundaries(self):
        ReadSystemLogsInput(lines=1)
        ReadSystemLogsInput(lines=1000)
        with pytest.raises(ValidationError):
            ReadSystemLogsInput(lines=0)
        with pytest.raises(ValidationError):
            ReadSystemLogsInput(lines=1001)


# ===========================================================================
# Delegation Schemas
# ===========================================================================


class TestDelegateToOpusInput:
    def test_minimal_valid(self):
        m = DelegateToOpusInput(instruction="Please refactor this module for clarity")
        assert m.file_paths is None
        assert m.model == "opus"

    def test_full_valid(self):
        m = DelegateToOpusInput(
            instruction="Add unit tests for the auth module",
            file_paths="backend/auth.py,tests/test_auth.py",
            model="sonnet",
        )
        assert m.file_paths == "backend/auth.py,tests/test_auth.py"
        assert m.model == "sonnet"

    def test_instruction_min_length(self):
        with pytest.raises(ValidationError):
            DelegateToOpusInput(instruction="short")  # min_length=10

    def test_instruction_at_min_length(self):
        m = DelegateToOpusInput(instruction="x" * 10)
        assert len(m.instruction) == 10

    def test_invalid_model_rejected(self):
        with pytest.raises(ValidationError):
            DelegateToOpusInput(
                instruction="valid instruction text",
                model="gpt-4",
            )

    def test_all_valid_models(self):
        for model in ["opus", "sonnet", "haiku"]:
            m = DelegateToOpusInput(
                instruction="valid instruction text",
                model=model,
            )
            assert m.model == model
