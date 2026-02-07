"""Tests for research config module."""



def test_browser_max_uses_exists():
    from backend.protocols.mcp.research.config import BROWSER_MAX_USES

    assert isinstance(BROWSER_MAX_USES, int)
    assert BROWSER_MAX_USES > 0


def test_browser_idle_timeout_exists():
    from backend.protocols.mcp.research.config import BROWSER_IDLE_TIMEOUT

    assert isinstance(BROWSER_IDLE_TIMEOUT, int)
    assert BROWSER_IDLE_TIMEOUT > 0


def test_selector_timeout_ms_exists():
    from backend.protocols.mcp.research.config import SELECTOR_TIMEOUT_MS

    assert isinstance(SELECTOR_TIMEOUT_MS, int)
    assert SELECTOR_TIMEOUT_MS > 0


def test_page_timeout_ms_from_backend_config():
    from backend.protocols.mcp.research.config import PAGE_TIMEOUT_MS
    from backend.config import RESEARCH_PAGE_TIMEOUT_MS

    assert PAGE_TIMEOUT_MS == RESEARCH_PAGE_TIMEOUT_MS


def test_navigation_timeout_ms_from_backend_config():
    from backend.protocols.mcp.research.config import NAVIGATION_TIMEOUT_MS
    from backend.config import RESEARCH_NAVIGATION_TIMEOUT_MS

    assert NAVIGATION_TIMEOUT_MS == RESEARCH_NAVIGATION_TIMEOUT_MS


def test_max_content_length_from_backend_config():
    from backend.protocols.mcp.research.config import MAX_CONTENT_LENGTH
    from backend.config import RESEARCH_MAX_CONTENT_LENGTH

    assert MAX_CONTENT_LENGTH == RESEARCH_MAX_CONTENT_LENGTH


def test_excluded_tags_is_list():
    from backend.protocols.mcp.research.config import EXCLUDED_TAGS

    assert isinstance(EXCLUDED_TAGS, list)
    assert "script" in EXCLUDED_TAGS
    assert "style" in EXCLUDED_TAGS


def test_ad_patterns_is_list():
    from backend.protocols.mcp.research.config import AD_PATTERNS

    assert isinstance(AD_PATTERNS, list)
    assert "ad" in AD_PATTERNS
    assert "cookie" in AD_PATTERNS


def test_user_agents_is_list():
    from backend.protocols.mcp.research.config import USER_AGENTS

    assert isinstance(USER_AGENTS, list)
    assert len(USER_AGENTS) >= 3
