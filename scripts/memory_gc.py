import sys
import os
import asyncio
import argparse
import json
import sqlite3
from pathlib import Path

if os.path.exists('/app'):
    sys.path.insert(0, '/app')
else:

    sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import (
    WORKING_MEMORY_PATH,
    SQLITE_MEMORY_PATH,
    CHROMADB_PATH,
)

from backend.memory.permanent import LongTermMemory, MemoryConfig
from backend.memory.recent import SessionArchive
from backend.memory import MemoryManager
from backend.core.identity.ai_brain import IdentityManager
from collections import defaultdict

init_state = None
import hashlib

# Try to import native module for optimized vector operations
try:
    import axnmihn_native as _native
    _HAS_NATIVE = True
except ImportError:
    _native = None
    _HAS_NATIVE = False

SIZE_THRESHOLD = 50_000
OVERSIZED_PATTERNS = [
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/webp;base64,",
]

def get_content_hash(content: str) -> str:

    normalized = content.lower().strip()[:200]
    return hashlib.md5(normalized.encode()).hexdigest()

def phase1_hash_dedup(ltm, all_data, dry_run: bool = False) -> list:
    """Phase 1: Hash-based exact duplicate removal."""

    print("\n[Phase 1] Hash-based deduplication (exact matches)...")

    hash_to_ids = defaultdict(list)

    for i, (doc_id, doc, meta) in enumerate(zip(
        all_data['ids'],
        all_data['documents'],
        all_data['metadatas'] or [{}] * len(all_data['ids'])
    )):
        content_hash = get_content_hash(doc)
        hash_to_ids[content_hash].append({
            'id': doc_id,
            'doc': doc,
            'meta': meta or {},
            'importance': (meta or {}).get('importance', 0.5)
        })

    duplicates_to_delete = []

    for content_hash, entries in hash_to_ids.items():
        if len(entries) > 1:
            entries.sort(key=lambda x: x['importance'], reverse=True)
            for dup in entries[1:]:
                duplicates_to_delete.append(dup['id'])
                print(f"  [HASH] {dup['doc'][:50]}...")

    if duplicates_to_delete:
        if not dry_run:
            ltm.delete_memories(duplicates_to_delete)
            print(f"  Deleted {len(duplicates_to_delete)} exact duplicates")
        else:
            print(f"  [DRY RUN] Would delete {len(duplicates_to_delete)} exact duplicates")
    else:
        print("  No exact duplicates found.")

    return duplicates_to_delete

def _phase2_native(ltm, threshold: float) -> list[dict]:
    """Phase 2 implementation using native C++ vector_ops.

    Fetches all embeddings from ChromaDB in a single call, then uses
    native find_duplicates_by_embedding for O(N^2) batch comparison.
    Eliminates per-memory API calls entirely.

    Args:
        ltm: LongTermMemory instance
        threshold: Similarity threshold for duplicate detection

    Returns:
        List of duplicate dicts with id, original_id, similarity, preview
    """
    import numpy as np

    results = ltm.get_all_memories(
        include=["documents", "metadatas", "embeddings"]
    )

    if not results["ids"] or not results.get("embeddings"):
        return []

    ids = results["ids"]
    docs = results["documents"] or [""] * len(ids)
    embeddings_raw = results["embeddings"]
    metadatas = results["metadatas"] or [{}] * len(ids)

    # Filter out entries without valid embeddings
    valid_indices: list[int] = []
    valid_embeddings: list[list[float]] = []
    for i, emb in enumerate(embeddings_raw):
        if emb is not None and len(emb) > 0:
            valid_indices.append(i)
            valid_embeddings.append(emb)

    if len(valid_embeddings) < 2:
        return []

    embeddings = np.array(valid_embeddings, dtype=np.float64)
    print(f"  Native batch: {len(valid_embeddings)} embeddings, dim={embeddings.shape[1]}")

    dup_pairs = _native.vector_ops.find_duplicates_by_embedding(embeddings, threshold)
    print(f"  Found {len(dup_pairs)} duplicate pairs via native")

    # For each pair, decide which to keep (higher importance wins)
    to_delete: list[dict] = []
    delete_ids: set[str] = set()

    for vi, vj, sim in dup_pairs:
        idx_i = valid_indices[vi]
        idx_j = valid_indices[vj]
        id_i = ids[idx_i]
        id_j = ids[idx_j]

        if id_i in delete_ids and id_j in delete_ids:
            continue

        meta_i = metadatas[idx_i] or {}
        meta_j = metadatas[idx_j] or {}
        imp_i = meta_i.get("importance", 0.5)
        imp_j = meta_j.get("importance", 0.5)

        # Keep the one with higher importance
        if imp_i >= imp_j:
            keep_id, remove_id, remove_idx = id_i, id_j, idx_j
        else:
            keep_id, remove_id, remove_idx = id_j, id_i, idx_i

        if remove_id not in delete_ids:
            delete_ids.add(remove_id)
            preview = (docs[remove_idx] or "")[:50]
            to_delete.append({
                "id": remove_id,
                "original_id": keep_id,
                "similarity": sim,
                "preview": preview,
            })

    return to_delete


def _phase2_python(ltm, threshold: float) -> list[dict]:
    """Phase 2 fallback using per-memory API calls.

    Args:
        ltm: LongTermMemory instance
        threshold: Similarity threshold for duplicate detection

    Returns:
        List of duplicate dicts with id, original_id, similarity, preview
    """
    results = ltm.get_all_memories(include=["documents", "metadatas"])

    if not results["ids"]:
        return []

    total = len(results["ids"])
    to_delete: list[dict] = []
    keep_ids: set[str] = set()
    delete_id_set: set[str] = set()

    batch_size = 50
    processed = 0

    for i in range(total):
        doc_id = results["ids"][i]
        doc_content = results["documents"][i] if results["documents"] else ""

        if doc_id in delete_id_set or doc_id in keep_ids:
            continue

        if not doc_content:
            continue

        similar = ltm.find_similar_memories(
            content=doc_content[:500],
            threshold=0.0,
            n_results=5,
        )

        processed += 1
        if processed % batch_size == 0:
            print(f"  Processed {processed}/{total} documents...")

        for sim_mem in similar:
            sim_id = sim_mem.get("id")
            similarity = sim_mem.get("similarity", 0)

            if sim_id == doc_id:
                continue

            if similarity >= threshold and sim_id not in keep_ids:
                if sim_id not in delete_id_set:
                    preview = sim_mem.get("content", "")[:50]
                    to_delete.append({
                        "id": sim_id,
                        "original_id": doc_id,
                        "similarity": similarity,
                        "preview": preview,
                    })
                    delete_id_set.add(sim_id)

        keep_ids.add(doc_id)

    return to_delete


def phase2_semantic_dedup(ltm, dry_run: bool = False) -> list:
    """Phase 2: Semantic deduplication using embedding similarity.

    Uses native C++ vector_ops when available for batch processing
    (single DB call + C++ AVX2 O(N^2) comparison).
    Falls back to per-memory API calls otherwise.
    """
    threshold = MemoryConfig.DUPLICATE_THRESHOLD
    print(f"\n[Phase 2] Semantic deduplication (threshold: {threshold})...")

    if _HAS_NATIVE:
        print("  Using native vector_ops (batch mode)")
        to_delete = _phase2_native(ltm, threshold)
    else:
        print("  Using Python fallback (per-memory API calls)")
        to_delete = _phase2_python(ltm, threshold)

    if to_delete:
        for d in to_delete:
            print(f"  [{d['similarity']:.2f}] {d['preview']}...")

        if not dry_run:
            ltm.delete_memories([d["id"] for d in to_delete])
            print(f"  Deleted {len(to_delete)} semantic duplicates")
        else:
            print(f"  [DRY RUN] Would delete {len(to_delete)} semantic duplicates")
    else:
        print("  No semantic duplicates found.")

    return [d["id"] for d in to_delete]

def phase3_consolidation(ltm, dry_run: bool = False) -> dict:

    print("\n[Phase 3] Consolidation (decay cleanup)...")
    if dry_run:
         print("  [DRY RUN] Skipping consolidation update (would check decay)")
         return {"checked": 0, "deleted": 0, "preserved": 0}

    report = ltm.consolidate_memories()
    print(f"  Checked: {report.get('checked', 0)}")
    print(f"  Deleted (decayed): {report.get('deleted', 0)}")
    print(f"  Preserved: {report.get('preserved', 0)}")
    return report

def phase4_smart_eviction(memory_manager, dry_run: bool = False) -> dict:

    print("\n[Phase 4] Smart Eviction (MemGPT-style)...")

    if not memory_manager or not memory_manager.memgpt:
        print("  Skipped: MemGPT not available")
        return {}

    try:
        report = memory_manager.memgpt.smart_eviction(dry_run=dry_run)
        evicted = report.get('evicted', 0)
        candidates = report.get('candidates', 0)
        print(f"  Candidates: {candidates}")
        if dry_run:
            print(f"  [DRY RUN] Would evict: {evicted}")
        else:
            print(f"  Evicted: {evicted}")
        return report
    except Exception as e:
        print(f"  Error: {e}")
        return {}

async def phase5_session_summarize(session_archive) -> dict:
    """Session Archive - 만료 메시지 축약 (summarize_expired 사용)"""
    print("\n[Phase 5] Session Archive summarization...")

    if not session_archive:
        print("  Skipped: SessionArchive not available")
        return {"sessions_processed": 0, "messages_archived": 0}

    try:
        result = await session_archive.summarize_expired()
        print(f"  Sessions summarized: {result.get('sessions_processed', 0)}")
        print(f"  Messages archived: {result.get('messages_archived', 0)}")
        return result
    except Exception as e:
        print(f"  Error: {e}")
        return {"sessions_processed": 0, "messages_archived": 0, "error": str(e)}

async def phase6_episodic_to_semantic(memory_manager) -> dict:

    print("\n[Phase 6] Episodic→Semantic transformation...")

    if not memory_manager or not memory_manager.memgpt:
        print("  Skipped: MemGPT not available")
        return {}

    try:
        report = await memory_manager.memgpt.episodic_to_semantic(dry_run=False)
        transformed = report.get('transformations', 0)
        print(f"  Transformations: {transformed}")
        return report
    except Exception as e:
        print(f"  Error: {e}")
        return {}

#async def phase7_persona_evolution(ltm) -> tuple:
#
#    print("\n[Phase 7] Persona evolution...")
#
#    try:
#        from backend.api.memory import _evolve_persona_from_memories
#        count, insights = await _evolve_persona_from_memories()
#        print(f"  New insights ({count}): {insights}")
#        return count, insights
#    except Exception as e:
#        print(f"  Error: {e}")
#        return 0, []

def phase8_sleep_learning(insights: list, dry_run: bool = False) -> dict:

    print("\n[Phase 8] Sleep Learning (Evolution Protocol)...")

    if not insights:
        print("  Skipped: No new insights to consolidate.")
        return {}

    path = Path("mutations/memory.json")
    if not path.exists():
        print("  Skipped: Mutation memory not found.")
        return {}

    try:
        from datetime import datetime
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        new_entries = []
        for insight in insights:
            entry = {
                "task": "Sleep Cycle Consolidation",
                "status": "SUCCESS",
                "lessons_learned": insight,
                "optimized_logic": f"Derived from insight: {insight}",
                "timestamp": datetime.now().isoformat()
            }
            new_entries.append(entry)

        if not dry_run:
            if "experience_buffer" not in data:
                data["experience_buffer"] = []
            data["experience_buffer"].extend(new_entries)
            data["last_sync"] = datetime.now().isoformat()

            if "structural_rules" not in data:
                data["structural_rules"] = []

            for insight in insights:

                if len(insight) < 100 and insight not in data["structural_rules"]:
                     data["structural_rules"].append(f"Learned Rule: {insight}")

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"  Consolidated {len(new_entries)} insights into mutation memory.")
        if dry_run:
            print("  (Dry Run: File not modified)")
        return {"added": len(new_entries)}

    except Exception as e:
        print(f"  Error: {e}")
        return {}

def phase9_knowledge_graph_prune(min_age_days: int = 7, dry_run: bool = False) -> dict:

    print("\n[Phase 9] Knowledge Graph pruning...")

    try:
        from backend.memory.graph_rag import KnowledgeGraph
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        kg = KnowledgeGraph()
        VANCOUVER_TZ = ZoneInfo("America/Vancouver")
        now = datetime.now(VANCOUVER_TZ)
        cutoff = now - timedelta(days=min_age_days)

        to_delete = []
        for eid, entity in kg.entities.items():

            if entity.mentions < 3:
                try:
                    created = datetime.fromisoformat(entity.created_at)
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=VANCOUVER_TZ)
                    if created < cutoff:
                        to_delete.append(eid)
                except (ValueError, TypeError, AttributeError):

                    pass

        if not dry_run:
            for eid in to_delete:
                del kg.entities[eid]

        relation_decay_rate = 0.1
        decayed_relations = 0
        pruned_relations = 0
        orphan_relations = []

        for rid, rel in list(kg.relations.items()):

            if rel.source_id not in kg.entities or rel.target_id not in kg.entities:
                orphan_relations.append(rid)
                continue

            try:
                created = datetime.fromisoformat(rel.created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=VANCOUVER_TZ)
                age_weeks = (now - created).days / 7

                original_weight = getattr(rel, 'weight', 1.0)

                new_weight = original_weight * ((1 - relation_decay_rate) ** age_weeks)

                if new_weight < 0.1:

                    if not dry_run:
                        del kg.relations[rid]
                    pruned_relations += 1
                elif new_weight < original_weight:

                    if not dry_run and hasattr(rel, 'weight'):
                        rel.weight = new_weight
                    decayed_relations += 1
            except (ValueError, TypeError, AttributeError):

                pass

        if not dry_run:
            for rid in orphan_relations:
                if rid in kg.relations:
                    del kg.relations[rid]

        if not dry_run:
            kg.save()

        result = {
            "entities_pruned": len(to_delete),
            "relations_orphaned": len(orphan_relations),
            "relations_decayed": decayed_relations,
            "relations_pruned": pruned_relations
        }
        prefix = "[DRY RUN] " if dry_run else ""
        print(f"  {prefix}Entities pruned: {len(to_delete)}")
        print(f"  {prefix}Orphan relations removed: {len(orphan_relations)}")
        print(f"  {prefix}Relations decayed: {decayed_relations}")
        print(f"  {prefix}Weak relations pruned: {pruned_relations}")
        return result

    except Exception as e:
        print(f"  Error: {e}")
        return {"error": str(e)}

async def main_async(dry_run: bool = False):

    print("=" * 60)
    mode_str = "[DRY RUN] " if dry_run else ""
    print(f"{mode_str}Memory Garbage Collection")
    print("=" * 60)

    gc_errors = []

    ltm = LongTermMemory()
    session_archive = SessionArchive()

    memory_manager = None
    try:
        from backend.core.utils.gemini_client import get_gemini_client
        from backend.config import DEFAULT_GEMINI_MODEL

        gemini_client = get_gemini_client()
        memory_manager = MemoryManager(client=gemini_client, model_name=DEFAULT_GEMINI_MODEL)
    except Exception as e:
        print(f"Note: MemoryManager not available ({e})")

    identity_manager = IdentityManager()

    try:
        from backend.api.deps import init_state
        init_state(
            long_term_memory=ltm,
            memory_manager=memory_manager,
            identity_manager=identity_manager
        )
    except ImportError:
        print("Note: init_state not available (MCP not installed)")

    all_data = ltm.get_all_memories(include=['documents', 'metadatas'], limit=5000)

    if not all_data['documents']:
        print("No memories found.")
        return

    initial_count = len(all_data['documents'])
    print(f"Total memories: {initial_count}")

    print("\n[Phase 0] Cleanup oversized entries (>50KB, base64)...")
    wm_result = cleanup_working_memory(dry_run=dry_run, threshold=SIZE_THRESHOLD)
    sql_result = cleanup_sqlite(dry_run=dry_run, threshold=SIZE_THRESHOLD)
    chroma_result = cleanup_chromadb(dry_run=dry_run, threshold=SIZE_THRESHOLD)
    phase0_cleaned = wm_result.get('removed', 0) + sql_result.get('oversized', 0) + chroma_result.get('oversized', 0)
    print(f"  Working Memory: {wm_result.get('removed', 0)} {'would be ' if dry_run else ''}removed")
    print(f"  SQLite: {sql_result.get('oversized', 0)} {'would be ' if dry_run else ''}removed")
    print(f"  ChromaDB: {chroma_result.get('oversized', 0)} {'would be ' if dry_run else ''}removed")

    if phase0_cleaned > 0 and not dry_run:
        all_data = ltm.get_all_memories(include=['documents', 'metadatas'], limit=5000)
        print(f"  Refreshed: {len(all_data['documents'])} memories remaining")

    if dry_run:
        print("\n" + "=" * 60)
        print("CONVERGENCE SIMULATION (Continuing to full check...)")
        print("=" * 60)

    import traceback

    try:
        hash_deleted = phase1_hash_dedup(ltm, all_data, dry_run=dry_run)
    except Exception as e:
        gc_errors.append({"phase": 1, "error": str(e), "traceback": traceback.format_exc()})
        hash_deleted = []

    try:
        semantic_deleted = phase2_semantic_dedup(ltm, dry_run=dry_run)
    except Exception as e:
        gc_errors.append({"phase": 2, "error": str(e), "traceback": traceback.format_exc()})
        semantic_deleted = []

    try:
        consolidation_report = phase3_consolidation(ltm, dry_run=dry_run)
    except Exception as e:
        gc_errors.append({"phase": 3, "error": str(e), "traceback": traceback.format_exc()})
        consolidation_report = {}

    try:
        eviction_report = phase4_smart_eviction(memory_manager, dry_run=dry_run)
    except Exception as e:
        gc_errors.append({"phase": 4, "error": str(e), "traceback": traceback.format_exc()})
        eviction_report = {}

    try:
        session_result = await phase5_session_summarize(session_archive)
        session_summarized = session_result.get('sessions_processed', 0)
        messages_archived = session_result.get('messages_archived', 0)
    except Exception as e:
        gc_errors.append({"phase": 5, "error": str(e), "traceback": traceback.format_exc()})
        session_summarized = 0
        messages_archived = 0

    try:
        episodic_report = await phase6_episodic_to_semantic(memory_manager)
    except Exception as e:
        gc_errors.append({"phase": 6, "error": str(e), "traceback": traceback.format_exc()})
        episodic_report = {}

    try:
        persona_count, persona_insights = await phase7_persona_evolution(ltm)
    except Exception as e:
        gc_errors.append({"phase": 7, "error": str(e), "traceback": traceback.format_exc()})
        persona_count, persona_insights = 0, []

    try:
        sleep_learning_report = phase8_sleep_learning(persona_insights, dry_run=dry_run)
    except Exception as e:
        gc_errors.append({"phase": 8, "error": str(e), "traceback": traceback.format_exc()})
        sleep_learning_report = {}

    # Phase 9 제거됨 - KG pruning은 dedup_knowledge_graph.py로 분리
    # 주 1회 별도 실행 권장: python scripts/dedup_knowledge_graph.py --apply
    kg_prune_report = {"skipped": True, "reason": "moved to dedup_knowledge_graph.py"}

    print("\n" + "=" * 60)
    final_count = ltm.count()

    r_hash = len(hash_deleted)
    r_semantic = len(semantic_deleted)
    r_decay = consolidation_report.get('deleted', 0)
    r_evict = eviction_report.get('evicted', 0)

    print(f"SUMMARY:")
    print(f"  Initial memories:     {initial_count}")
    print(f"  Oversize cleanup:     -{phase0_cleaned}")
    print(f"  Hash dedup:           -{r_hash}")
    print(f"  Semantic dedup:       -{r_semantic}")
    print(f"  Decay cleanup:        -{r_decay}")
    print(f"  Smart eviction:       -{r_evict}")

    print(f"  Sessions summarized:  {session_summarized}")
    print(f"  Messages archived:    {messages_archived}")
    print(f"  Episodic→Semantic:    {episodic_report.get('transformations', 0)}")
    print(f"  Persona insights:     {persona_count}")
    print(f"  Sleep Learning:       {sleep_learning_report.get('added', 0)} mutations")
    if kg_prune_report.get('skipped'):
        print(f"  KG pruning:           Skipped (use dedup_knowledge_graph.py)")
    else:
        print(f"  KG entities pruned:   {kg_prune_report.get('entities_pruned', 0)}")
        print(f"  KG relations decayed: {kg_prune_report.get('relations_decayed', 0)}")
        print(f"  KG relations pruned:  {kg_prune_report.get('relations_pruned', 0)}")

    if dry_run:
        total_reduction = phase0_cleaned + r_hash + r_semantic + r_decay + r_evict

        simulated_final = initial_count - total_reduction + episodic_report.get('transformations', 0)
        print("-" * 30)
        print(f"  [DRY RUN] Final DB Count: {final_count} (Unchanged)")
        print(f"  [DRY RUN] Projected Final: {simulated_final} (If executed)")
    else:
        print(f"  Final memories:       {final_count}")

    if gc_errors:
        print("-" * 30)
        print(f"  ERRORS:               {len(gc_errors)}")
        for err in gc_errors:
            print(f"    Phase {err['phase']}: {err['error']}")
            if err.get('traceback'):
                # traceback의 마지막 몇 줄만 표시
                tb_lines = err['traceback'].strip().split('\n')
                for line in tb_lines[-4:]:
                    print(f"      {line}")

    print("=" * 60)

    session_archive.close(silent=True)

def cmd_check():

    print("=" * 60)
    print("MEMORY STATUS CHECK")
    print("=" * 60)

    print("\n[1] WORKING MEMORY (RAM-tier)")
    wm_path = WORKING_MEMORY_PATH
    try:
        if wm_path.exists():
            with open(wm_path, "r", encoding="utf-8") as f:
                wm = json.load(f)
            messages = wm.get("messages", [])
            print(f"    Turns: {len(messages)}")
            print(f"    Session ID: {wm.get('session_id', 'N/A')[:8]}...")
            if messages:
                last_content = messages[-1].get('content', '')[:50]
                print(f"    Last message: {last_content}...")
        else:
            print("    File not found")
    except Exception as e:
        print(f"    Error: {e}")

    print("\n[2] SESSION ARCHIVE (SQLite)")
    db_path = SQLITE_MEMORY_PATH
    try:
        if db_path.exists():
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM sessions")
            session_count = cursor.fetchone()[0]
            print(f"    Sessions: {session_count}")

            cursor.execute("SELECT COUNT(*) FROM messages")
            message_count = cursor.fetchone()[0]
            print(f"    Messages: {message_count}")

            cursor.execute("SELECT id, summary, created_at FROM sessions ORDER BY created_at DESC LIMIT 3")
            recent = cursor.fetchall()
            if recent:
                print("    Recent sessions:")
                for s in recent:
                    session_id = str(s[0])[:8]
                    summary = (s[1][:30] if s[1] else 'No summary')
                    print(f"      - {session_id}... | {summary}...")

            conn.close()
        else:
            print("    Database not found")
    except Exception as e:
        print(f"    Error: {e}")

    print("\n[3] LONG-TERM MEMORY (ChromaDB)")
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMADB_PATH))
        collections = client.list_collections()
        print(f"    Collections: {len(collections)}")

        for col in collections:
            count = col.count()
            print(f"    - {col.name}: {count} memories")

            if count > 0:
                sample = col.peek(3)
                if sample and sample.get("documents"):
                    doc = sample['documents'][0][:50]
                    print(f"      Sample: {doc}...")
    except Exception as e:
        print(f"    Error: {e}")

    print("\n" + "=" * 60)
    print("CHECK COMPLETE")
    print("=" * 60)

def cleanup_working_memory(dry_run: bool = True, threshold: int = SIZE_THRESHOLD) -> dict:

    path = WORKING_MEMORY_PATH
    if not path.exists():
        return {"status": "skipped", "reason": "file not found"}

    with open(path) as f:
        data = json.load(f)

    original_count = len(data.get("messages", []))
    clean_messages = []
    removed = []

    for msg in data.get("messages", []):
        content = msg.get("content", "")
        size = len(content)
        is_oversized = size > threshold
        has_base64 = any(p in content for p in OVERSIZED_PATTERNS)

        if is_oversized or has_base64:
            removed.append({
                "role": msg.get("role"),
                "size": size,
                "reason": "base64" if has_base64 else "oversized"
            })
        else:
            clean_messages.append(msg)

    result = {
        "status": "dry_run" if dry_run else "cleaned",
        "original": original_count,
        "remaining": len(clean_messages),
        "removed": len(removed),
    }

    if not dry_run and removed:
        data["messages"] = clean_messages
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return result

def cleanup_sqlite(dry_run: bool = True, threshold: int = SIZE_THRESHOLD) -> dict:

    db_path = SQLITE_MEMORY_PATH
    if not db_path.exists():
        return {"status": "skipped", "reason": "file not found"}

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT id FROM messages WHERE length(content) > ?
    """, (threshold,))
    oversized = cursor.fetchall()

    result = {
        "status": "dry_run" if dry_run else "cleaned",
        "oversized": len(oversized),
    }

    if not dry_run and oversized:
        ids = [r[0] for r in oversized]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", ids)
        conn.commit()

    conn.close()
    return result

def cleanup_chromadb(dry_run: bool = True, threshold: int = SIZE_THRESHOLD) -> dict:

    try:
        import chromadb
    except ImportError:
        return {"status": "skipped", "reason": "chromadb not installed"}

    if not CHROMADB_PATH.exists():
        return {"status": "skipped", "reason": "directory not found"}

    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))

    try:
        coll = client.get_collection("axnmihn_memory")
    except Exception as e:

        return {"status": "skipped", "reason": f"collection not found: {type(e).__name__}"}

    results = coll.get(include=["documents"])
    oversized_ids = []

    for i, doc in enumerate(results["documents"]):
        if len(doc) > threshold or any(p in doc for p in OVERSIZED_PATTERNS):
            oversized_ids.append(results["ids"][i])

    result = {
        "status": "dry_run" if dry_run else "cleaned",
        "oversized": len(oversized_ids),
    }

    if not dry_run and oversized_ids:
        coll.delete(ids=oversized_ids)

    return result

def cmd_cleanup(dry_run: bool = True, threshold: int = SIZE_THRESHOLD):

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}Memory Cleanup (threshold: {threshold:,} bytes)")
    print("=" * 60)

    print("\n Working Memory:")
    result = cleanup_working_memory(dry_run, threshold)
    print(f"   Status: {result['status']}")
    if "removed" in result:
        print(f"   Removed: {result['removed']} messages")

    print("\n SQLite:")
    result = cleanup_sqlite(dry_run, threshold)
    print(f"   Status: {result['status']}")
    if "oversized" in result:
        print(f"   Oversized: {result['oversized']} messages")

    print("\n ChromaDB:")
    result = cleanup_chromadb(dry_run, threshold)
    print(f"   Status: {result['status']}")
    if "oversized" in result:
        print(f"   Oversized: {result['oversized']} documents")

    print("\n" + "=" * 60)
    if dry_run:
        print("Run without --dry-run to actually delete.")

def main():

    parser = argparse.ArgumentParser(
        description="Memory GC - Unified memory management tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/memory_gc.py              # Full 7-phase GC (default)
  python scripts/memory_gc.py check        # Status check only
  python scripts/memory_gc.py cleanup      # Remove oversized entries
  python scripts/memory_gc.py cleanup --dry-run  # Preview cleanup
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("check", help="Check status across all memory layers (read-only)")

    cleanup_parser = subparsers.add_parser("cleanup", help="Remove oversized entries (>50KB, base64 images)")
    cleanup_parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    cleanup_parser.add_argument("--threshold", type=int, default=SIZE_THRESHOLD, help="Size threshold in bytes")

    full_parser = subparsers.add_parser("full", help="Complete 7-phase garbage collection")
    full_parser.add_argument("--dry-run", action="store_true", help="Simulate without deleting")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check()
    elif args.command == "cleanup":
        threshold = args.threshold if hasattr(args, 'threshold') else SIZE_THRESHOLD
        cmd_cleanup(dry_run=args.dry_run, threshold=threshold)
    elif args.command == "full" or args.command is None:

        dry_run = getattr(args, 'dry_run', False)
        asyncio.run(main_async(dry_run=dry_run))

if __name__ == "__main__":
    main()
