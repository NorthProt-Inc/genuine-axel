from fastapi import APIRouter, Depends
from backend.core.logging import get_logger
from backend.llm import get_llm_client
from backend.api.deps import get_state, require_api_key
from datetime import datetime, timedelta

_logger = get_logger("api.memory")

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

    state = get_state()

    if not state.long_term_memory:
        return 0, []

    try:
        all_data = state.long_term_memory.collection.get(
            include=["documents", "metadatas"],
            limit=30
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
            _logger.warning("LLM returned empty response for persona evolution")
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
                _logger.info("AI Brain evolved", new_insights=added)
            return added, insights[:3]

        return 0, []

    except Exception as e:
        import traceback
        _logger.error("AI Brain evolution error", error=str(e), traceback=traceback.format_exc())
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
        _logger.info("Session ended", result=str(result))
        return result
    except Exception as e:
        _logger.error("Session end error", error=str(e))
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
        _logger.error("Get sessions error", error=str(e))
        return {"sessions": [], "error": str(e)}

@router.get("/memory/search")
async def search_memory(query: str, limit: int = 20):

    state = get_state()

    results = []

    if state.long_term_memory:
        try:
            chroma_results = state.long_term_memory.search(query, limit=limit)
            for doc, meta, score in chroma_results:
                results.append({
                    "id": meta.get("uuid", ""),
                    "type": meta.get("memory_type", "memory"),
                    "title": meta.get("memory_type", "Memory"),
                    "content": doc[:200] if doc else "",
                    "timestamp": meta.get("timestamp", ""),
                    "score": score
                })
        except Exception as e:
            _logger.warning("ChromaDB search error", error=str(e))

    if state.memory_manager and state.memory_manager.session_archive:
        try:
            sessions = state.memory_manager.session_archive.get_sessions_by_date(
                datetime.now() - timedelta(days=30),
                datetime.now()
            )
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
            _logger.warning("Session search error", error=str(e))

    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {"results": results[:limit]}

@router.get("/memory/session/{session_id}")
async def get_session_detail(session_id: str):

    state = get_state()

    if not state.memory_manager or not state.memory_manager.session_archive:
        return {"error": "Session archive not available"}

    try:

        with state.memory_manager.session_archive._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT role, content, timestamp FROM messages
                WHERE session_id = ? ORDER BY turn_id ASC
            """, (session_id,))
            rows = cursor.fetchall()

        messages = [
            {"role": row[0], "content": row[1], "timestamp": row[2]}
            for row in rows
        ]

        return {"session_id": session_id, "messages": messages}
    except Exception as e:
        _logger.error("Get session detail error", error=str(e))
        return {"error": str(e)}
