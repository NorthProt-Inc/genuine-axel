import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.config import WORKING_MEMORY_PATH
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.memory_tools")

async def _read_file_safe(path: Path) -> str:
    """Read file asynchronously using asyncio.to_thread."""
    import asyncio
    if not path.exists():
        return f"Error: File not found at {path}"
    try:
        return await asyncio.to_thread(path.read_text, encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {str(e)}"

@register_tool(
    "query_axel_memory",
    category="memory",
    description="Search specific keywords in Axel's working memory",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keyword to search for"}
        },
        "required": ["query"]
    }
)
async def query_axel_memory(arguments: dict[str, Any]) -> Sequence[TextContent]:
    query = arguments.get("query", "").lower()
    _log.debug("TOOL invoke", fn="query_axel_memory", query=query[:50] if query else None)

    if not query:
        _log.warning("TOOL fail", fn="query_axel_memory", err="query parameter required")
        return [TextContent(type="text", text="Error: query parameter is required")]

    memory_content = await _read_file_safe(WORKING_MEMORY_PATH)

    try:
        memory_data = json.loads(memory_content)
        messages = memory_data.get("messages", [])

        results = []
        for msg in reversed(messages[-50:]):
            if query in msg.get("content", "").lower():
                results.append(
                    f"[{msg.get('timestamp')}] {msg.get('role')}: {msg.get('content')[:200]}..."
                )

        if not results:
            _log.info("TOOL ok", fn="query_axel_memory", res_len=0)
            return [TextContent(type="text", text=f"No matches found for '{query}' in recent memory.")]

        _log.info("TOOL ok", fn="query_axel_memory", res_len=len(results))
        return [TextContent(type="text", text="\n".join(results))]

    except json.JSONDecodeError:
        _log.warning("TOOL fail", fn="query_axel_memory", err="memory file corrupt")
        return [TextContent(type="text", text="Error: Memory file is corrupt")]
    except Exception as e:
        _log.error("TOOL fail", fn="query_axel_memory", err=str(e)[:100])
        return [TextContent(type="text", text=f"Error searching memory: {str(e)}")]

@register_tool(
    "add_memory",
    category="memory",
    description="Inject a new memory into Axel's working memory",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Content of the memory"},
            "category": {"type": "string", "description": "Type of memory (observation, fact, code)", "default": "observation"}
        },
        "required": ["content"]
    }
)
async def add_memory(arguments: dict[str, Any]) -> Sequence[TextContent]:
    content = arguments.get("content", "")
    category = arguments.get("category", "observation")
    _log.debug("TOOL invoke", fn="add_memory", category=category, content_len=len(content) if content else 0)

    if not content:
        _log.warning("TOOL fail", fn="add_memory", err="content parameter required")
        return [TextContent(type="text", text="Error: content parameter is required")]

    valid_categories = ["observation", "fact", "code"]
    if category not in valid_categories:
        _log.warning("TOOL fail", fn="add_memory", err="invalid category", category=category)
        return [TextContent(
            type="text",
            text=f"Error: invalid category '{category}'. Must be one of: {', '.join(valid_categories)}"
        )]

    try:
        memory_file = WORKING_MEMORY_PATH

        if memory_file.exists():
            data = json.loads(memory_file.read_text())
        else:
            data = {"messages": []}

        new_entry = {
            "role": "system",
            "content": f"[INJECTED_MEMORY:{category.upper()}] {content}",
            "timestamp": datetime.now().isoformat(),
            "emotional_context": "neutral"
        }

        data["messages"].append(new_entry)

        if len(data["messages"]) > 100:
            data["messages"] = data["messages"][-100:]

        memory_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        _log.info("TOOL ok", fn="add_memory", category=category)
        return [TextContent(type="text", text="Memory injected successfully.")]

    except Exception as e:
        _log.error("TOOL fail", fn="add_memory", err=str(e)[:100])
        return [TextContent(type="text", text=f"Error injecting memory: {str(e)}")]

@register_tool(
    "store_memory",
    category="memory",
    description="""Store information to Axel's long-term memory and knowledge graph.

USE THIS WHEN:
- User shares important facts about themselves
- Discovering user preferences
- Learning new information worth remembering
- Storing insights from conversations

CATEGORIES:
- "fact": User facts (name, job, relationships, etc.)
- "preference": User preferences (likes, dislikes, habits)
- "conversation": Notable conversation content
- "insight": Learned insights or patterns

IMPORTANCE (0.0-1.0):
- 0.8+: Critical facts (user's name, important dates)
- 0.5-0.7: Useful preferences and context
- 0.3-0.5: General conversation content""",
    input_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Content to store in memory"},
            "category": {"type": "string", "enum": ["fact", "preference", "conversation", "insight"], "description": "Memory category", "default": "conversation"},
            "importance": {"type": "number", "description": "Importance score 0.0-1.0", "default": 0.5, "minimum": 0.0, "maximum": 1.0}
        },
        "required": ["content"]
    }
)
async def store_memory(arguments: dict[str, Any]) -> Sequence[TextContent]:
    content = arguments.get("content", "")
    category = arguments.get("category", "conversation")
    importance = arguments.get("importance", 0.5)
    _log.debug("TOOL invoke", fn="store_memory", category=category, importance=importance, content_len=len(content) if content else 0)

    if not content:
        _log.warning("TOOL fail", fn="store_memory", err="content parameter required")
        return [TextContent(type="text", text="Error: content parameter is required")]

    valid_categories = ["fact", "preference", "conversation", "insight"]
    if category not in valid_categories:
        _log.warning("TOOL fail", fn="store_memory", err="invalid category", category=category)
        return [TextContent(
            type="text",
            text=f"Error: invalid category '{category}'. Must be one of: {', '.join(valid_categories)}"
        )]

    if not isinstance(importance, (int, float)) or not 0.0 <= importance <= 1.0:
        _log.warning("TOOL fail", fn="store_memory", err="invalid importance value")
        return [TextContent(type="text", text="Error: importance must be a number between 0.0 and 1.0")]

    try:
        from backend.protocols.mcp.memory_server import store_memory as memory_store

        result = await memory_store(
            content=content,
            category=category,
            importance=importance
        )

        if result.get("success"):
            memory_id = result.get('memory_id') or 'N/A'
            memory_id_short = memory_id[:8] if memory_id != 'N/A' else 'N/A'
            _log.info("TOOL ok", fn="store_memory", memory_id=memory_id_short, category=category)
            return [TextContent(
                type="text",
                text=f"✓ Memory stored: {memory_id_short} (category={result.get('category')}, importance={result.get('importance')})"
            )]
        else:
            _log.warning("TOOL partial", fn="store_memory", err=result.get('error', 'unknown')[:100])
            return [TextContent(type="text", text=f"✗ Store failed: {result.get('error')}")]

    except Exception as e:
        _log.error("TOOL fail", fn="store_memory", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Memory Error: {str(e)}")]

@register_tool(
    "retrieve_context",
    category="memory",
    description="""ACTIVE MEMORY RECALL - Retrieve relevant memories for the current query.

USE THIS PROACTIVELY before responding when:
- User asks about something you might have discussed before
- User references past conversations ("remember when...")
- You need context about the user (name, preferences, etc.)
- The query relates to topics you've covered

This combines:
1. ChromaDB vector search (semantic similarity)
2. GraphRAG relationship search (entity connections)

Returns formatted context string with relevant memories.""",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query - what are you trying to remember?"},
            "max_results": {"type": "integer", "description": "Max memories to retrieve (default: 10)", "default": 10, "minimum": 1, "maximum": 25}
        },
        "required": ["query"]
    }
)
async def retrieve_context(arguments: dict[str, Any]) -> Sequence[TextContent]:
    query = arguments.get("query", "")
    max_results = arguments.get("max_results", 10)
    _log.debug("TOOL invoke", fn="retrieve_context", query=query[:50] if query else None, max_results=max_results)

    if not query:
        _log.warning("TOOL fail", fn="retrieve_context", err="query parameter required")
        return [TextContent(type="text", text="Error: query parameter is required")]

    if not isinstance(max_results, int) or max_results < 1 or max_results > 25:
        _log.warning("TOOL fail", fn="retrieve_context", err="invalid max_results")
        return [TextContent(type="text", text="Error: max_results must be an integer between 1 and 25")]

    try:
        from backend.protocols.mcp.memory_server import retrieve_context as memory_retrieve

        result = await memory_retrieve(
            query=query,
            max_results=max_results
        )

        if result.get("success"):
            context = result.get("context", "No context found.")
            metadata = result.get("metadata", {})
            chromadb_cnt = metadata.get('chromadb_results', 0)
            graph_cnt = metadata.get('graph_entities', 0)
            _log.info("TOOL ok", fn="retrieve_context", chromadb_cnt=chromadb_cnt, graph_cnt=graph_cnt)
            header = f"✓ Context Retrieved (ChromaDB: {chromadb_cnt}, Graph: {graph_cnt} entities)\n\n"
            return [TextContent(type="text", text=header + context)]
        else:
            _log.warning("TOOL partial", fn="retrieve_context", err=result.get('error', 'unknown')[:100])
            return [TextContent(type="text", text=f"✗ Retrieve failed: {result.get('error')}")]

    except Exception as e:
        _log.error("TOOL fail", fn="retrieve_context", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Memory Error: {str(e)}")]

@register_tool(
    "get_recent_logs",
    category="memory",
    description="""Get recent session summaries and interaction logs.

USE THIS FOR:
- Debugging conversation flow
- Understanding what happened in recent sessions
- Reviewing interaction history
- Getting context about recent conversations

Returns session summaries and interaction metadata.""",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max entries to return (default: 50)", "default": 50, "minimum": 1, "maximum": 100}
        },
        "required": []
    }
)
async def get_recent_logs(arguments: dict[str, Any]) -> Sequence[TextContent]:
    limit = arguments.get("limit", 50)
    _log.debug("TOOL invoke", fn="get_recent_logs", limit=limit)

    if not isinstance(limit, int) or limit < 1 or limit > 100:
        _log.warning("TOOL fail", fn="get_recent_logs", err="invalid limit")
        return [TextContent(type="text", text="Error: limit must be an integer between 1 and 100")]

    try:
        from backend.protocols.mcp.memory_server import get_recent_logs as memory_get_logs

        result = await memory_get_logs(limit=limit)

        if result.get("success"):
            summaries = result.get("session_summaries", "No summaries.")
            count = result.get("interaction_count", 0)
            _log.info("TOOL ok", fn="get_recent_logs", interaction_cnt=count)
            header = f"✓ Recent Logs ({count} total interactions)\n\n"
            return [TextContent(type="text", text=header + summaries)]
        else:
            _log.warning("TOOL partial", fn="get_recent_logs", err=result.get('error', 'unknown')[:100])
            return [TextContent(type="text", text=f"✗ Logs failed: {result.get('error')}")]

    except Exception as e:
        _log.error("TOOL fail", fn="get_recent_logs", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Logs Error: {str(e)}")]


@register_tool(
    "memory_stats",
    category="memory",
    description="""Get detailed memory system statistics.

Returns:
- Working memory: message count, size
- Long-term memory: document count, embedding stats
- Graph memory: entity and relationship counts
- Cache statistics""",
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    }
)
async def memory_stats(arguments: dict[str, Any]) -> Sequence[TextContent]:
    _log.debug("TOOL invoke", fn="memory_stats")

    try:
        output = ["✓ Memory System Statistics", "═" * 40, ""]

        # Working Memory stats
        try:
            if WORKING_MEMORY_PATH.exists():
                data = json.loads(WORKING_MEMORY_PATH.read_text())
                messages = data.get("messages", [])
                size_kb = WORKING_MEMORY_PATH.stat().st_size / 1024
                output.append("Working Memory:")
                output.append(f"  Messages: {len(messages)}")
                output.append(f"  File Size: {size_kb:.1f} KB")
            else:
                output.append("Working Memory: Not initialized")
        except Exception as e:
            output.append(f"Working Memory: Error - {str(e)[:50]}")

        output.append("")

        # Long-term Memory stats
        try:
            from backend.memory.permanent import LongTermMemory
            ltm = LongTermMemory()
            ltm_stats = ltm.get_stats()
            output.append("Long-term Memory (ChromaDB):")
            output.append(f"  Documents: {ltm_stats.get('total_documents', 'N/A')}")
            output.append(f"  Categories: {ltm_stats.get('categories', {})}")
            output.append(f"  Embedding Cache: {ltm_stats.get('embedding_cache_size', 0)} entries")
        except Exception as e:
            output.append(f"Long-term Memory: Error - {str(e)[:50]}")

        output.append("")

        # GraphRAG stats
        try:
            from backend.memory.graph_rag import GraphRAG
            graph = GraphRAG()
            graph_stats = graph.get_stats()
            output.append("Knowledge Graph:")
            output.append(f"  Entities: {graph_stats.get('entity_count', 0)}")
            output.append(f"  Relationships: {graph_stats.get('relationship_count', 0)}")
        except Exception as e:
            output.append(f"Knowledge Graph: Error - {str(e)[:50]}")

        output.append("")

        # Cache stats
        try:
            from backend.core.utils import get_all_cache_stats
            caches = get_all_cache_stats()
            if caches:
                output.append("Caches:")
                for name, stats in caches.items():
                    output.append(f"  {name}: {stats['size']}/{stats['maxsize']} (hit rate: {stats['hit_rate']})")
            else:
                output.append("Caches: None configured")
        except Exception as e:
            output.append(f"Caches: Error - {str(e)[:50]}")

        _log.info("TOOL ok", fn="memory_stats")
        return [TextContent(type="text", text="\n".join(output))]

    except Exception as e:
        _log.error("TOOL fail", fn="memory_stats", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Stats Error: {str(e)}")]
