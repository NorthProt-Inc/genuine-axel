from fastapi import APIRouter, Depends
from backend.core.logging import get_logger
from backend.llm import get_llm_client
from backend.api.deps import get_state, require_api_key
from datetime import datetime, timedelta

_log = get_logger("api.memory")

router = APIRouter(tags=["Memory"], dependencies=[Depends(require_api_key)])

@router.post("/memory/consolidate")
async def consolidate_memory():

    state = get_state()

    if state.long_term_memory:
        report = state.long_term_memory.consolidate_memories()
        insights_added, insights_text = await _evolve_persona_from_memories()
        report["insights_added"] = insights_added
        report["insights_text"] = insights_text
        return {"status": "success", "report": report}
    return {"status": "error", "message": "Memory not initialized"}

async def _evolve_persona_from_memories():
    """Evolve persona based on recent memories."""
    state = get_state()

    if not state.long_term_memory:
        return 0, []

    try:
        # PERF-033: Fetch only what we need (limit 20)
        all_data = state.long_term_memory.get_all_memories(
            include=["documents", "metadatas"],
            limit=20
        )

        if not all_data or not all_data.get('documents'):
            return 0, []

        documents = all_data.get('documents', [])
        metadatas = all_data.get('metadatas', [])

        memory_lines = []
        for doc, meta in zip(documents[:20], metadatas[:20] or [{}]*20):
            content = doc[:200] if doc else ""
            user_query = meta.get('user_query', '') if meta else ""
            if user_query and content:
                memory_lines.append(f"- User: {user_query[:80]} / AI: {content[:100]}")
            elif content:
                memory_lines.append(f"- {content}")

        memory_text = "\n".join(memory_lines)

        prompt = f"""아래 대화 기록을 분석해서 사용자에 대해 새롭게 알 수 있는 인사이트를 추출해줘.

대화 기록:
{memory_text}

규칙:
- 사용자의 성격, 선호도, 행동 패턴에 대한 인사이트만 추출
- 이미 알고 있는 정보(한국어 사용, 개발자 등)는 제외
- 새로운 발견만 포함
- 최대 3개의 인사이트
- 각 인사이트는 한 줄로 간결하게

형식:
1. [인사이트 1]
2. [인사이트 2]
3. [인사이트 3]

인사이트:"""

        llm = get_llm_client("gemini")
        response = await llm.generate(prompt, max_tokens=300)

        if not response:
            _log.warning("LLM returned empty response for persona evolution")
            return 0, []

        insights = []
        for line in response.split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-")):
                insight = line.lstrip("0123456789.-) ").strip()
                if insight and len(insight) > 10:
                    insights.append(insight)

        if insights and state.identity_manager:
            added = await state.identity_manager.evolve(insights[:3])
            if added > 0:
                _log.info("AI Brain evolved", new_insights=added)
            return added, insights[:3]

        return 0, []

    except Exception as e:
        import traceback
        _log.error("AI Brain evolution error", error=str(e), traceback=traceback.format_exc())
        return 0, []

@router.get("/memory/stats")
async def get_memory_stats():

    state = get_state()

    if state.memory_manager:
        return state.memory_manager.get_stats()
    elif state.long_term_memory:
        return {"permanent": state.long_term_memory.get_stats()}
    return {"error": "Memory not initialized"}

@router.post("/session/end")
async def end_session():

    state = get_state()

    if not state.memory_manager:
        return {"status": "error", "message": "MemoryManager not initialized"}

    try:
        result = await state.memory_manager.end_session()
        _log.info("Session ended", result=str(result))
        return result
    except Exception as e:
        _log.error("Session end error", error=str(e))
        return {"status": "error", "message": str(e)}

@router.get("/memory/sessions")
async def get_sessions():

    state = get_state()

    if not state.memory_manager or not state.memory_manager.session_archive:
        return {"sessions": []}

    try:

        summaries = state.memory_manager.session_archive.get_recent_summaries(limit=50)
        return {"sessions": summaries}
    except Exception as e:
        _log.error("Get sessions error", error=str(e))
        return {"sessions": [], "error": str(e)}

@router.get("/memory/search")
async def search_memory(query: str, limit: int = 20):

    state = get_state()

    results = []

    if state.long_term_memory:
        try:
            chroma_results = state.long_term_memory.query(query, n_results=limit)
            for item in chroma_results:
                meta = item.get("metadata", {})
                results.append({
                    "id": meta.get("uuid", "") if isinstance(meta, dict) else "",
                    "type": meta.get("memory_type", "memory") if isinstance(meta, dict) else "memory",
                    "title": meta.get("memory_type", "Memory") if isinstance(meta, dict) else "Memory",
                    "content": str(item.get("content", ""))[:200],
                    "timestamp": meta.get("timestamp", "") if isinstance(meta, dict) else "",
                    "score": item.get("similarity", 0)
                })
        except Exception as e:
            _log.warning("ChromaDB search error", error=str(e))

    if state.memory_manager and state.memory_manager.session_archive:
        try:
            sessions = state.memory_manager.session_archive.get_sessions_by_date(
                (datetime.now() - timedelta(days=30)).isoformat(),
                datetime.now().isoformat()
            )
            if isinstance(sessions, str):
                # get_sessions_by_date returns formatted string, not a list
                pass
            else:
                for session in sessions:
                    if query.lower() in session.get("summary", "").lower():
                        results.append({
                            "id": session.get("session_id", ""),
                            "type": "session",
                            "title": "Session",
                            "content": session.get("summary", "")[:200],
                            "timestamp": session.get("ended_at", ""),
                            "conversation_id": session.get("session_id"),
                            "score": 0.5
                        })
        except Exception as e:
            _log.warning("Session search error", error=str(e))

    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {"results": results[:limit]}

@router.get("/memory/session/{session_id}")
async def get_session_detail(session_id: str):

    state = get_state()

    if not state.memory_manager or not state.memory_manager.session_archive:
        return {"error": "Session archive not available"}

    try:
        archive = state.memory_manager.session_archive

        detail = archive.get_session_detail(session_id)

        if not detail:
            # sessions 테이블에 없는 경우 messages만 반환
            messages = archive.get_session_messages(session_id)
            return {"session_id": session_id, "messages": messages}

        session_info = detail.get("session", {})
        messages = detail.get("messages", [])

        return {
            "session_id": session_id,
            "summary": session_info.get("summary"),
            "key_topics": session_info.get("key_topics"),
            "emotional_tone": session_info.get("emotional_tone"),
            "messages": messages
        }
    except Exception as e:
        _log.error("Get session detail error", error=str(e))
        return {"error": str(e)}


@router.get("/memory/interaction-logs")
async def get_interaction_logs(limit: int = 20):
    """Retrieve model routing logs with model, tier, latency, and token stats."""
    state = get_state()

    if not state.memory_manager or not state.memory_manager.session_archive:
        return {"logs": [], "error": "Session archive not available"}

    try:
        logs = state.memory_manager.session_archive.get_recent_interaction_logs(limit)
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        _log.error("Get interaction logs error", error=str(e))
        return {"logs": [], "error": str(e)}


@router.get("/memory/interaction-stats")
async def get_interaction_stats():
    """Get usage statistics summary by model and tier."""
    state = get_state()

    if not state.memory_manager or not state.memory_manager.session_archive:
        return {"error": "Session archive not available"}

    try:
        return state.memory_manager.session_archive.get_interaction_stats()
    except Exception as e:
        _log.error("Get interaction stats error", error=str(e))
        return {"error": str(e)}
