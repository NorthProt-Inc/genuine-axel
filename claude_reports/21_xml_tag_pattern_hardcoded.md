# 21. `_XML_TAG_PATTERN` 하드코딩된 도구 이름

> 분석 날짜: 2026-02-06
> 분석 범위: `backend/core/filters/xml_filter.py`, `backend/core/filters/__init__.py`, `backend/core/chat_handler.py`, `backend/core/services/react_service.py`, `backend/core/tools/opus_executor.py`, `backend/core/mcp_client.py`, `backend/core/mcp_tools/` (레지스트리)

## 요약

`xml_filter.py`의 `MCP_TOOL_TAGS`에 MCP 도구 이름이 하드코딩되어 있으며, 실제 도구 레지스트리(32개)와 11개의 도구가 불일치합니다. 누락된 도구의 XML 태그가 LLM 출력에 포함되면 사용자에게 그대로 노출됩니다. `CORE_TOOLS` (mcp_client.py)도 별도 하드코딩으로, 도구 이름이 3곳에서 독립 관리되는 샷건 수술 구조입니다.

## 발견사항

### CRITICAL

(해당 없음)

### HIGH

- **MCP_TOOL_TAGS와 실제 레지스트리 간 11개 도구 누락**: (`backend/core/filters/xml_filter.py:27-55`)
  - 실제 등록된 32개 도구 중 다음 11개가 `MCP_TOOL_TAGS`에 없음:
    - `check_task_status`, `get_recent_logs`, `google_deep_research`, `hass_execute_scene`
    - `list_artifacts`, `list_available_logs`, `memory_stats`, `read_artifact`
    - `search_codebase_regex`, `system_status`, `tool_metrics`
  - 영향: LLM이 이 도구들의 XML 태그를 텍스트로 출력하면 `strip_xml_tags()`가 제거하지 못하고 사용자에게 `<system_status>...</system_status>` 같은 원시 태그가 노출됨
  - 개선안: 도구 레지스트리에서 자동 생성

    ```python
    # xml_filter.py
    from backend.core.mcp_tools import list_tools as list_registered_tools

    def _get_mcp_tool_names() -> FrozenSet[str]:
        """Get MCP tool names dynamically from registry."""
        try:
            return frozenset(t.name for t in list_registered_tools())
        except Exception:
            return _FALLBACK_MCP_TOOL_TAGS  # 하드코딩 폴백

    MCP_TOOL_TAGS: FrozenSet[str] = _get_mcp_tool_names()
    ```

- **도구 이름 3중 하드코딩 (샷건 수술)**: (`xml_filter.py:27-55`, `mcp_client.py:17-32`, 레지스트리 `@register_tool`)
  - `MCP_TOOL_TAGS` (xml_filter.py), `CORE_TOOLS` (mcp_client.py), `@register_tool` 데코레이터 (mcp_tools/*.py) 3곳에서 도구 이름을 독립적으로 관리
  - 도구 추가/삭제 시 최소 2곳을 수동 동기화해야 하며 누락 가능성 높음
  - 영향: 도구 추가 시 xml_filter.py 업데이트를 잊으면 해당 태그가 사용자에게 노출되고, mcp_client.py의 CORE_TOOLS를 안 고치면 우선순위 정렬이 작동하지 않음
  - 개선안: 레지스트리를 단일 소스로 사용

    ```python
    # mcp_client.py
    from backend.core.mcp_tools import get_tool_schemas

    def _get_core_tool_names() -> list[str]:
        """Derive core tools from registry categories."""
        CORE_CATEGORIES = {"file", "system", "research", "delegation", "hass"}
        return [t.name for t in get_tool_schemas()
                if getattr(t, 'category', '') in CORE_CATEGORIES]
    ```

### MEDIUM

- **`MCP_PARAM_TAGS` 불완전한 파라미터 목록**: (`backend/core/filters/xml_filter.py:57-72`)
  - 7개의 파라미터 이름만 하드코딩(`entity_id`, `brightness`, `color`, `file_pattern`, `file_paths`, `category`, `importance`)
  - 실제 MCP 도구들은 `query`, `command`, `path`, `content`, `model`, `timeout`, `scene_name`, `log_type`, `duration` 등 수십 개의 파라미터를 사용
  - 개선안: 도구 스키마의 `inputSchema.properties` 키에서 자동 추출하거나, 파라미터 태그는 제네릭 패턴(`<[a-z_]+>`)으로 처리

    ```python
    def _get_mcp_param_names() -> FrozenSet[str]:
        """Extract all parameter names from tool schemas."""
        params = set()
        for tool in get_tool_schemas():
            if hasattr(tool, 'inputSchema') and 'properties' in tool.inputSchema:
                params.update(tool.inputSchema['properties'].keys())
        return frozenset(params)
    ```

- **모듈 임포트 시점 패턴 빌드로 도구 추가 시 재시작 필요**: (`backend/core/filters/xml_filter.py:90`)
  - `_XML_TAG_PATTERN = _build_tag_pattern()`이 모듈 임포트 시 한 번만 실행됨
  - 동적 도구 로딩이나 플러그인 추가 시 패턴이 갱신되지 않음
  - 현재는 서버 재시작으로 해결되지만, 향후 hot-reload 지원 시 문제
  - 개선안: 레지스트리 기반 동적 생성으로 전환하면 자연스럽게 해결

- **`_TOOL_BLOCK_PATTERN`과 `_PARTIAL_TOOL_PATTERN`의 태그 범위 불일치**: (`backend/core/filters/xml_filter.py:93-101`)
  - `_TOOL_BLOCK_PATTERN`은 `function_call|tool_call|tool_use|invoke` 4개만 매칭
  - `_PARTIAL_TOOL_PATTERN`은 `function_call|tool_call|tool_use|invoke|call:` 5개 매칭 (`call:` 추가)
  - `INTERNAL_TAGS`에는 `function_call|tool_call|tool_result|tool_use|antthinking` 등이 있어 또 다른 범위
  - 개선안: 블록 패턴과 파셜 패턴의 태그 목록을 상수로 통합

    ```python
    _TOOL_CALL_TAGS = ("function_call", "tool_call", "tool_use", "invoke")
    _TOOL_BLOCK_PATTERN = re.compile(
        r'<(?:' + '|'.join(_TOOL_CALL_TAGS) + r')[^>]*>.*?</(?:' + '|'.join(_TOOL_CALL_TAGS) + r')>',
        re.IGNORECASE | re.DOTALL
    )
    _PARTIAL_TOOL_PATTERN = re.compile(
        r'<(?:' + '|'.join(_TOOL_CALL_TAGS) + r'|call:)[^>]*$',
        re.IGNORECASE
    )
    ```

### LOW

- **주석 "분리하여 동적 로드 가능하도록"이 실제로는 정적**: (`backend/core/filters/xml_filter.py:10`)
  - `# === Tag Constants (분리하여 동적 로드 가능하도록) ===` 주석이 있으나, 실제로는 모두 하드코딩된 `frozenset` 리터럴
  - 영향: 코드 의도와 실제 구현의 불일치로 유지보수자 혼란
  - 개선안: 동적 로드를 실제로 구현하거나, 주석을 현실에 맞게 수정

- **`get_all_filter_tags()` 미사용 유틸리티**: (`backend/core/filters/xml_filter.py:149-151`)
  - 이 함수는 프로젝트 내 어디에서도 호출되지 않음 (Grep 결과 확인)
  - 디버깅/테스트용이라는 docstring이 있으나 테스트도 없음
  - 개선안: 삭제하거나 실제 테스트에서 활용

## 개선 제안

### 핵심 방향: 도구 레지스트리를 단일 진실의 원천(Single Source of Truth)으로

현재 도구 이름이 3곳에서 독립 관리되어 동기화 누락이 구조적으로 발생합니다. 근본적 해결은 `@register_tool` 데코레이터가 부여한 레지스트리 데이터를 xml_filter와 mcp_client 모두 참조하게 하는 것입니다.

```python
# backend/core/filters/xml_filter.py (개선안)

import re
from typing import FrozenSet

# === Internal tags (LLM 프로토콜 고유, 변경 빈도 낮음) ===
INTERNAL_TAGS: FrozenSet[str] = frozenset({
    "attempt_completion", "result", "thought", "thinking",
    "reflection", "function_call", "tool_call", "tool_result",
    "tool_use", "antthinking", "search_quality_reflection",
    "search_quality_score",
})

# === MCP tool/param tags (레지스트리에서 동적 로드) ===
def _load_mcp_tags() -> tuple[FrozenSet[str], FrozenSet[str]]:
    """Load MCP tool names and param names from the tool registry."""
    try:
        from backend.core.mcp_tools import list_tools
        tools = list_tools()
        tool_names = frozenset(t.name for t in tools)
        param_names: set[str] = set()
        for t in tools:
            if hasattr(t, 'inputSchema'):
                props = t.inputSchema.get('properties', {})
                param_names.update(props.keys())
        return tool_names, frozenset(param_names)
    except Exception:
        # Fallback: import 실패 시 (테스트 환경 등)
        return _FALLBACK_TOOL_TAGS, _FALLBACK_PARAM_TAGS

# Fallback constants (레지스트리 로드 실패 시에만 사용)
_FALLBACK_TOOL_TAGS: FrozenSet[str] = frozenset({...})  # 현재 목록
_FALLBACK_PARAM_TAGS: FrozenSet[str] = frozenset({...})  # 현재 목록

MCP_TOOL_TAGS, MCP_PARAM_TAGS = _load_mcp_tags()
```

이 방식은:
1. 도구 추가/삭제 시 `xml_filter.py` 수정 불필요
2. 순환 임포트 방지 (lazy import)
3. 테스트/독립 실행 시 폴백으로 안전
4. `CORE_TOOLS`도 동일한 패턴으로 레지스트리 카테고리 기반 도출 가능

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| MCP_TOOL_TAGS 누락 도구 11개 수동 추가 | ★☆☆ 쉬움 | frozenset에 문자열 11개 추가만으로 즉시 해결 |
| 레지스트리 기반 동적 로드 전환 | ★★☆ 보통 | 순환 임포트 회피 필요, 폴백 로직 설계 필요 |
| MCP_PARAM_TAGS 동적 추출 | ★★☆ 보통 | 스키마 구조 파싱 필요, 일부 도구 inputSchema 형식 확인 필요 |
| CORE_TOOLS 레지스트리 연동 | ★★☆ 보통 | 카테고리 기반 필터링, 기존 우선순위 로직과 통합 |
| _TOOL_BLOCK_PATTERN 태그 상수 통합 | ★☆☆ 쉬움 | 상수 추출 후 두 패턴에서 공유 |
| get_all_filter_tags() 정리 | ★☆☆ 쉬움 | 삭제 또는 테스트 작성 |
