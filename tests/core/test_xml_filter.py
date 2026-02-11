"""Tests for backend.core.filters.xml_filter."""

import pytest
from backend.core.filters.xml_filter import (
    strip_xml_tags,
    has_partial_tool_tag,
    get_all_filter_tags,
    INTERNAL_TAGS,
    MCP_TOOL_TAGS,
    MCP_PARAM_TAGS,
)


# ---------------------------------------------------------------------------
# strip_xml_tags
# ---------------------------------------------------------------------------


class TestStripXmlTags:
    """Tests for the strip_xml_tags function."""

    # -- Empty / None input --------------------------------------------------

    def test_empty_string(self):
        assert strip_xml_tags("") == ""

    def test_none_input(self):
        assert strip_xml_tags(None) is None

    def test_whitespace_only(self):
        result = strip_xml_tags("   ")
        assert result.strip() == ""

    # -- Plain text without tags passes through ------------------------------

    def test_plain_text_unchanged(self):
        text = "Hello, this is plain text."
        assert strip_xml_tags(text) == text

    def test_html_tags_preserved(self):
        """HTML tags like <b> are not in the filter set, so they stay."""
        text = "<b>Bold text</b>"
        assert strip_xml_tags(text) == text

    # -- Internal tags stripped, content preserved ---------------------------

    def test_thinking_tags_stripped(self):
        text = "<thinking>internal thought</thinking>Visible output"
        result = strip_xml_tags(text)
        assert "<thinking>" not in result
        assert "</thinking>" not in result
        assert "internal thought" in result
        assert "Visible output" in result

    def test_reflection_tags_stripped(self):
        text = "<reflection>reflecting here</reflection>Answer"
        result = strip_xml_tags(text)
        assert "<reflection>" not in result
        assert "reflecting here" in result
        assert "Answer" in result

    def test_antthinking_tags_stripped(self):
        text = "<antthinking>ant logic</antthinking>Response"
        result = strip_xml_tags(text)
        assert "<antthinking>" not in result
        assert "ant logic" in result

    def test_thought_tag_stripped(self):
        text = "<thought>deep thought</thought>Output"
        result = strip_xml_tags(text)
        assert "<thought>" not in result
        assert "deep thought" in result

    def test_search_quality_tags_stripped(self):
        text = "<search_quality_reflection>good</search_quality_reflection>"
        result = strip_xml_tags(text)
        assert "<search_quality_reflection>" not in result
        assert "good" in result

    def test_search_quality_score_stripped(self):
        text = "<search_quality_score>8</search_quality_score>"
        result = strip_xml_tags(text)
        assert "<search_quality_score>" not in result
        assert "8" in result

    # -- MCP tool tags stripped ----------------------------------------------

    def test_mcp_tool_tags_stripped(self):
        for tag in ("read_file", "web_search", "store_memory", "hass_control_light"):
            text = f"<{tag}>content</{tag}>"
            result = strip_xml_tags(text)
            assert f"<{tag}>" not in result
            assert f"</{tag}>" not in result

    def test_run_command_tag_stripped(self):
        text = "<run_command>ls -la</run_command>"
        result = strip_xml_tags(text)
        assert "<run_command>" not in result
        assert "ls -la" in result

    def test_list_directory_tag_stripped(self):
        text = "<list_directory>/home</list_directory>"
        result = strip_xml_tags(text)
        assert "<list_directory>" not in result

    def test_retrieve_context_tag_stripped(self):
        text = "<retrieve_context>query</retrieve_context>"
        result = strip_xml_tags(text)
        assert "<retrieve_context>" not in result

    # -- MCP param tags stripped ---------------------------------------------

    def test_entity_id_param_tag_stripped(self):
        text = "<entity_id>light.living_room</entity_id>"
        result = strip_xml_tags(text)
        assert "<entity_id>" not in result
        assert "light.living_room" in result

    def test_brightness_param_tag_stripped(self):
        text = "<brightness>80</brightness>"
        result = strip_xml_tags(text)
        assert "<brightness>" not in result
        assert "80" in result

    def test_parameters_tag_stripped(self):
        text = "<parameters>some params</parameters>"
        result = strip_xml_tags(text)
        assert "<parameters>" not in result

    def test_invoke_tag_stripped(self):
        text = "<invoke>something</invoke>"
        result = strip_xml_tags(text)
        assert "<invoke>" not in result

    # -- call: prefix tags ---------------------------------------------------

    def test_call_prefix_tag_stripped(self):
        text = "<call:some_function>args</call:some_function>"
        result = strip_xml_tags(text)
        assert "<call:" not in result

    # -- Complete tool call blocks removed entirely --------------------------

    def test_complete_function_call_block_removed(self):
        text = "Before<function_call>do_something()</function_call>After"
        result = strip_xml_tags(text)
        assert "do_something()" not in result
        assert "Before" in result
        assert "After" in result

    def test_complete_tool_call_block_removed(self):
        text = "Before<tool_call>execute</tool_call>After"
        result = strip_xml_tags(text)
        assert "execute" not in result
        assert "Before" in result
        assert "After" in result

    def test_complete_tool_use_block_removed(self):
        text = "Before<tool_use>usage</tool_use>After"
        result = strip_xml_tags(text)
        assert "usage" not in result

    def test_complete_invoke_block_removed(self):
        text = "Start<invoke>call</invoke>End"
        result = strip_xml_tags(text)
        assert "call" not in result
        assert "Start" in result
        assert "End" in result

    def test_multiline_tool_block_removed(self):
        text = "Before\n<function_call>\nline1\nline2\n</function_call>\nAfter"
        result = strip_xml_tags(text)
        assert "line1" not in result
        assert "line2" not in result
        assert "Before" in result
        assert "After" in result

    # -- Excessive blank lines cleaned up ------------------------------------

    def test_excessive_blank_lines_collapsed(self):
        text = "Line1\n\n\n\n\nLine2"
        result = strip_xml_tags(text)
        assert "\n\n\n" not in result
        assert "Line1" in result
        assert "Line2" in result

    # -- Case insensitivity --------------------------------------------------

    def test_case_insensitive_tag_stripping(self):
        text = "<THINKING>thought</THINKING>Result"
        result = strip_xml_tags(text)
        assert "<THINKING>" not in result
        assert "thought" in result

    # -- Mixed content -------------------------------------------------------

    def test_mixed_content_preserves_visible_text(self):
        text = (
            "Hello! <thinking>let me think</thinking>"
            "<tool_call>secret_call</tool_call>"
            " Here is your answer."
        )
        result = strip_xml_tags(text)
        assert "Hello!" in result
        assert "Here is your answer." in result
        assert "secret_call" not in result

    # -- Tags with attributes ------------------------------------------------

    def test_tags_with_attributes_stripped(self):
        text = '<thinking type="internal">thought</thinking>Result'
        result = strip_xml_tags(text)
        assert "<thinking" not in result
        assert "thought" in result

    # -- Tool block removal preserves spacing --------------------------------

    def test_tool_block_removal_inserts_space_between_korean(self):
        """Tool block between Korean text should leave a space."""
        text = "백엔드에서<tool_call>do_something()</tool_call>특수문자"
        result = strip_xml_tags(text)
        assert "백엔드에서" in result
        assert "특수문자" in result
        assert "백엔드에서특수문자" not in result  # should NOT be glued

    def test_tool_block_removal_inserts_space_between_text(self):
        text = "한글텍스트<function_call>call()</function_call>이어지는텍스트"
        result = strip_xml_tags(text)
        assert "한글텍스트이어지는텍스트" not in result  # should NOT be glued


# ---------------------------------------------------------------------------
# has_partial_tool_tag
# ---------------------------------------------------------------------------


class TestHasPartialToolTag:
    """Tests for the has_partial_tool_tag function."""

    def test_empty_string(self):
        assert has_partial_tool_tag("") is False

    def test_none_input(self):
        assert has_partial_tool_tag(None) is False

    def test_no_partial_tag(self):
        assert has_partial_tool_tag("Normal text without tags") is False

    def test_complete_tag_not_partial(self):
        assert has_partial_tool_tag("<function_call>complete</function_call>") is False

    def test_partial_function_call(self):
        assert has_partial_tool_tag("Some text <function_call") is True

    def test_partial_tool_call(self):
        assert has_partial_tool_tag("Some text <tool_call") is True

    def test_partial_tool_use(self):
        assert has_partial_tool_tag("Some text <tool_use") is True

    def test_partial_invoke(self):
        assert has_partial_tool_tag("Some text <invoke") is True

    def test_partial_call_prefix(self):
        assert has_partial_tool_tag("Some text <call:something") is True

    def test_partial_tag_only_in_last_100_chars(self):
        """Partial tag detection only checks last 100 chars."""
        # Partial tag buried far before the tail -- should not match
        text = "<function_call" + "x" * 200
        assert has_partial_tool_tag(text) is False

    def test_partial_tag_in_tail(self):
        text = "x" * 50 + "<tool_call"
        assert has_partial_tool_tag(text) is True


# ---------------------------------------------------------------------------
# get_all_filter_tags
# ---------------------------------------------------------------------------


class TestGetAllFilterTags:
    """Tests for the get_all_filter_tags function."""

    def test_returns_frozenset(self):
        result = get_all_filter_tags()
        assert isinstance(result, frozenset)

    def test_contains_internal_tags(self):
        result = get_all_filter_tags()
        for tag in INTERNAL_TAGS:
            assert tag in result

    def test_contains_mcp_tool_tags(self):
        result = get_all_filter_tags()
        for tag in MCP_TOOL_TAGS:
            assert tag in result

    def test_contains_mcp_param_tags(self):
        result = get_all_filter_tags()
        for tag in MCP_PARAM_TAGS:
            assert tag in result

    def test_size_equals_union_of_all_sets(self):
        result = get_all_filter_tags()
        expected_size = len(INTERNAL_TAGS | MCP_TOOL_TAGS | MCP_PARAM_TAGS)
        assert len(result) == expected_size

    def test_specific_tags_present(self):
        result = get_all_filter_tags()
        assert "thinking" in result
        assert "reflection" in result
        assert "web_search" in result
        assert "entity_id" in result
        assert "invoke" in result


# ---------------------------------------------------------------------------
# Tag set constants
# ---------------------------------------------------------------------------


class TestTagConstants:
    """Validate the tag constant frozen sets."""

    def test_internal_tags_is_frozenset(self):
        assert isinstance(INTERNAL_TAGS, frozenset)

    def test_mcp_tool_tags_is_frozenset(self):
        assert isinstance(MCP_TOOL_TAGS, frozenset)

    def test_mcp_param_tags_is_frozenset(self):
        assert isinstance(MCP_PARAM_TAGS, frozenset)

    def test_no_overlap_between_sets(self):
        """The three tag sets should have no overlap."""
        assert INTERNAL_TAGS.isdisjoint(MCP_TOOL_TAGS)
        assert INTERNAL_TAGS.isdisjoint(MCP_PARAM_TAGS)
        assert MCP_TOOL_TAGS.isdisjoint(MCP_PARAM_TAGS)

    def test_internal_tags_nonempty(self):
        assert len(INTERNAL_TAGS) > 0

    def test_mcp_tool_tags_nonempty(self):
        assert len(MCP_TOOL_TAGS) > 0

    def test_mcp_param_tags_nonempty(self):
        assert len(MCP_PARAM_TAGS) > 0
