import sys
from pathlib import Path
from typing import Dict, Any

AXEL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AXEL_ROOT))

from backend.core.logging import get_logger

_log = get_logger("protocols.memory")

def _get_memory_components():
    """Get memory components directly from AppState (no caching)."""
    from backend.api.deps import get_state

    state = get_state()
    mm = state.memory_manager
    ltm = state.long_term_memory
    sa = mm.session_archive if mm else None
    gr = mm.graph_rag if mm else None
    return mm, ltm, sa, gr

async def store_memory(
    content: str,
    category: str = "conversation",
    importance: float = 0.5
) -> Dict[str, Any]:

    _log.info("REQ handling", tool="store_memory", params=["content", "category", "importance"])
    _, long_term, _, graph_rag = _get_memory_components()

    if not long_term:
        return {"success": False, "error": "Long-term memory not available"}

    try:

        valid_categories = ["fact", "preference", "conversation", "insight"]
        if category not in valid_categories:
            category = "conversation"

        importance = max(0.0, min(1.0, importance))

        memory_id = long_term.add(
            content=content,
            memory_type=category,
            importance=importance,
            source_session="mcp_tool"
        )

        _log.info(
            "RES complete",
            tool="store_memory",
            memory_id=memory_id[:8] if memory_id else None,
            category=category,
            importance=importance,
            content_len=len(content)
        )

        if graph_rag:
            try:
                await graph_rag.extract_and_store(content, source="mcp_memory")
            except Exception as e:
                _log.debug("GraphRAG extraction skipped", error=str(e))

        return {
            "success": True,
            "memory_id": memory_id,
            "category": category,
            "importance": importance
        }

    except Exception as e:
        _log.error("Tool failed", tool="store_memory", error=str(e))
        return {"success": False, "error": str(e)}

async def retrieve_context(
    query: str,
    max_results: int = 10
) -> Dict[str, Any]:

    _log.info("REQ handling", tool="retrieve_context", params=["query", "max_results"])
    _, long_term, _, graph_rag = _get_memory_components()

    context_parts = []
    metadata = {
        "chromadb_results": 0,
        "graph_entities": 0,
        "graph_relations": 0
    }

    if long_term:
        try:
            results = long_term.query(query, n_results=max_results)
            if results:
                metadata["chromadb_results"] = len(results)

                def get_sort_timestamp(mem):

                    meta = mem.get("metadata", {})
                    ts = meta.get("event_timestamp") or meta.get("created_at") or ""
                    parsed = _parse_timestamp(ts)

                    from datetime import datetime, timezone
                    return parsed if parsed else datetime(1970, 1, 1, tzinfo=timezone.utc)

                sorted_results = sorted(results, key=get_sort_timestamp, reverse=True)

                memory_lines = ["[MEMORY CONTEXT]"]
                for idx, mem in enumerate(sorted_results, 1):
                    content = mem.get("content", "")
                    meta = mem.get("metadata", {})

                    timestamp = meta.get("event_timestamp") or meta.get("created_at") or ""

                    formatted_dt, temporal_label = _format_temporal_label(timestamp)

                    content_preview = content[:250].replace("\n", " ").strip()
                    if len(content) > 250:
                        content_preview += "..."

                    memory_lines.append(
                        f'{idx}. [{formatted_dt} | {temporal_label}] "{content_preview}"'
                    )

                if len(memory_lines) > 1:
                    context_parts.append("\n".join(memory_lines))
        except Exception as e:
            _log.warning("ChromaDB search failed", error=str(e))

    if graph_rag:
        try:
            import asyncio
            graph_result = await asyncio.to_thread(graph_rag.query_sync, query)
            if graph_result and graph_result.context:
                metadata["graph_entities"] = len(graph_result.entities)
                metadata["graph_relations"] = len(graph_result.relations)
                context_parts.append(f"## Relationship Context\n{graph_result.context}")
        except Exception as e:
            _log.debug("GraphRAG search skipped", error=str(e))

    if context_parts:
        context = "\n\n".join(context_parts)
        _log.info(
            "RES complete",
            tool="retrieve_context",
            query_len=len(query),
            chromadb=metadata["chromadb_results"],
            graph_entities=metadata["graph_entities"],
            graph_relations=metadata["graph_relations"]
        )
        return {
            "success": True,
            "context": context,
            "metadata": metadata
        }

    return {
        "success": True,
        "context": "No relevant memories found.",
        "metadata": metadata
    }

def _parse_timestamp(timestamp_str: str):
    """Parse timestamp string to datetime object.

    Supports multiple formats: ISO 8601, with/without timezone.

    Args:
        timestamp_str: Timestamp string to parse

    Returns:
        datetime object with UTC timezone, or None if parsing fails
    """
    from datetime import datetime, timezone

    if not timestamp_str:
        return None

    formats = ['%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']
    timestamp_str = timestamp_str.replace('Z', '+00:00')

    for fmt in formats:
        try:
            parsed = datetime.strptime(timestamp_str, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue

    # fromisoformat도 시도 (Python 3.11+에서 더 유연함)
    try:
        parsed = datetime.fromisoformat(timestamp_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        pass

    _log.debug("Unparseable timestamp", timestamp=timestamp_str[:30])
    return None

def _format_temporal_label(timestamp_str: str) -> tuple[str, str]:

    from datetime import datetime, timezone

    if not timestamp_str:
        return ("unknown", "OLD")

    mem_time = _parse_timestamp(timestamp_str)
    if not mem_time:
        return ("unknown", "OLD")

    try:
        now_time = datetime.now(timezone.utc)
        delta = now_time - mem_time
        hours = delta.total_seconds() / 3600

        formatted_dt = mem_time.strftime("%Y-%m-%d %H:%M")

        if hours < 24:
            label = "LATEST"
        else:
            label = "OLD"

        return (formatted_dt, label)
    except Exception as e:
        _log.debug("Temporal label calculation failed", timestamp=timestamp_str[:30], error=str(e))
        return ("unknown", "OLD")

def _format_memory_age(timestamp_str: str) -> str:
    """Format memory age as human-readable relative time.

    Args:
        timestamp_str: ISO timestamp string

    Returns:
        Relative time string (e.g., '2h ago', 'yesterday', '3d ago')
    """
    from datetime import datetime, timezone

    if not timestamp_str:
        return ""

    mem_time = _parse_timestamp(timestamp_str)
    if not mem_time:
        return ""

    try:
        now_time = datetime.now(timezone.utc)
        delta = now_time - mem_time

        hours = delta.total_seconds() / 3600
        days = delta.days

        if hours < 1:
            return "just now"
        elif hours < 24:
            return f"{int(hours)}h ago"
        elif days == 1:
            return "yesterday"
        elif days < 7:
            return f"{days}d ago"
        elif days < 30:
            return f"{days // 7}w ago"
        elif days < 365:
            return f"{days // 30}mo ago"
        else:
            return mem_time.strftime("%Y-%m-%d")
    except Exception as e:
        _log.debug("Memory age formatting failed", timestamp=timestamp_str[:30], error=str(e))
        return ""

async def get_recent_logs(limit: int = 50) -> Dict[str, Any]:

    _log.info("REQ handling", tool="get_recent_logs", params=["limit"])
    memory_manager, _, session_archive, _ = _get_memory_components()

    result = {
        "success": True,
        "session_summaries": "",
        "interaction_count": 0,
        "recent_interactions": []
    }

    if not session_archive:
        result["success"] = False
        result["error"] = "Session archive not available"
        return result

    try:

        summaries = session_archive.get_recent_summaries(limit=min(limit, 20), max_tokens=5000)
        result["session_summaries"] = summaries if summaries else "No recent sessions."

        try:
            stats = session_archive.get_stats()
            result["interaction_count"] = stats.get("total_interactions", 0)

            if hasattr(session_archive, 'get_recent_interactions'):
                interactions = session_archive.get_recent_interactions(limit=min(limit, 10))
                result["recent_interactions"] = interactions
        except Exception as e:
            _log.debug("Interaction logs not available", error=str(e))

        _log.info(
            "RES complete",
            tool="get_recent_logs",
            summaries_len=len(result["session_summaries"]),
            interactions=result["interaction_count"]
        )

        return result

    except Exception as e:
        _log.error("Tool failed", tool="get_recent_logs", error=str(e))
        return {"success": False, "error": str(e)}

__all__ = [
    "store_memory",
    "retrieve_context",
    "get_recent_logs",
]
