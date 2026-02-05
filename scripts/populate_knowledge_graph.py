#!/usr/bin/env python3

import asyncio
import os
import sys
import argparse
import shutil
import json
from datetime import datetime

from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from backend.config import DATA_ROOT, SQLITE_MEMORY_PATH, KNOWLEDGE_GRAPH_PATH

from backend.memory.permanent import LongTermMemory
from backend.memory.recent import SessionArchive
from backend.memory.graph_rag import GraphRAG, KnowledgeGraph
from backend.core.utils.gemini_wrapper import GenerativeModelWrapper

async def populate_knowledge_graph(
    batch_size: int = 10,
    max_memories: int = 500,
    clean: bool = False,
    dry_run: bool = False
):

    print("=" * 60)
    mode_str = "[DRY RUN] " if dry_run else ""
    print(f"{mode_str}Knowledge Graph Population v2.0")
    print("=" * 60)

    print("\n[1/5] Initializing components...")

    model = GenerativeModelWrapper(client_or_model="gemini-3-pro-preview")
    fallback_model = model
    ltm = LongTermMemory()
    session_archive = SessionArchive()

    kg_path = str(KNOWLEDGE_GRAPH_PATH)

    if clean and not dry_run:
        backup_path = str(DATA_ROOT / f"knowledge_graph_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        if os.path.exists(kg_path):
            print(f"       Backing up to {backup_path}")
            shutil.copy(kg_path, backup_path)
            print("       Clearing existing graph...")
            os.remove(kg_path)

    kg = KnowledgeGraph(persist_path=kg_path)
    gr = GraphRAG(model=model, graph=kg)

    print(f"       LTM:     {ltm.get_stats().get('total_memories', 0)} memories")
    print(f"       SQLite:  {session_archive.get_stats().get('total_sessions', 0)} sessions")
    print(f"       KG:      {kg.get_stats().get('total_entities', 0)} entities (before)")

    print("\n[2/5] Loading memories from all sources...")
    documents = []

    chroma_data = ltm.collection.get(
        limit=max_memories,
        include=["documents"]
    )
    chroma_docs = chroma_data.get('documents', [])
    documents.extend([(doc, "chromadb") for doc in chroma_docs])
    print(f"       ChromaDB: {len(chroma_docs)} documents")

    try:
        import sqlite3
        conn = sqlite3.connect(str(SQLITE_MEMORY_PATH))
        cursor = conn.execute("""
            SELECT content FROM messages
            WHERE LENGTH(content) > 50
            ORDER BY id DESC
            LIMIT ?
        """, (max_memories,))
        sql_docs = [row[0] for row in cursor.fetchall()]
        documents.extend([(doc, "sqlite") for doc in sql_docs])
        conn.close()
        print(f"       SQLite:   {len(sql_docs)} messages")
    except Exception as e:
        print(f"       SQLite:   Error - {e}")

    total = len(documents)
    print(f"       Total:    {total} documents")

    if not documents:
        print("       No documents to process!")
        return

    print(f"\n[3/5] Extracting entities (batch size: {batch_size})...")
    processed = 0
    total_entities = 0
    total_filtered = 0
    total_relations = 0
    errors = 0
    fallback_uses = 0
    checkpoint_path = str(DATA_ROOT / "kg_populate_checkpoint.json")

    start_batch = 0
    if os.path.exists(checkpoint_path) and not clean:
        try:
            with open(checkpoint_path) as f:
                checkpoint = json.load(f)
                start_batch = checkpoint.get("last_batch", 0)
                print(f"       Resuming from checkpoint: batch {start_batch + 1}")
        except json.JSONDecodeError as e:
            print(f"       Warning: Checkpoint JSON invalid, starting fresh: {e}")
        except FileNotFoundError:
            pass  # 체크포인트 없음은 정상
        except Exception as e:
            print(f"       Warning: Checkpoint read failed: {e}")

    for i in range(0, total, batch_size):
        batch = documents[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total + batch_size - 1) // batch_size

        print(f"       Batch {batch_num}/{total_batches}...", end=" ", flush=True)

        batch_entities = 0
        batch_filtered = 0
        batch_relations = 0

        for doc, source in batch:
            try:

                if len(doc) < 50:
                    continue

                if dry_run:

                    batch_entities += 1
                    processed += 1
                    continue

                result = await gr.extract_and_store(doc[:800], source=source)

                if "error" in result:

                    gr_fallback = GraphRAG(model=fallback_model, graph=kg)
                    result = await gr_fallback.extract_and_store(doc[:800], source=source)
                    if "error" not in result:
                        fallback_uses += 1

                if "error" not in result:
                    batch_entities += result.get("entities_added", 0)
                    batch_filtered += result.get("entities_filtered", 0)
                    batch_relations += result.get("relations_added", 0)
                    processed += 1
                else:
                    errors += 1

            except Exception as e:
                errors += 1

        total_entities += batch_entities
        total_filtered += batch_filtered
        total_relations += batch_relations

        print(f"✓ +{batch_entities} entities, -{batch_filtered} filtered, +{batch_relations} relations")

        if batch_num % 5 == 0 and not dry_run:
            kg.save()
            with open(checkpoint_path, 'w') as f:
                json.dump({"last_batch": batch_num, "processed": processed}, f)
            print(f"       [Checkpoint saved: batch {batch_num}]")

        await asyncio.sleep(0.3)

    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)

    print("\n[4/5] Saving knowledge graph...")
    if not dry_run:
        kg.save()

    print("\n[5/5] Verifying quality...")
    final_stats = kg.get_stats()
    entities_count = final_stats.get('total_entities', 0)

    single_mention = 0
    for e in kg.entities.values():
        if e.mentions == 1:
            single_mention += 1
    single_ratio = (single_mention / entities_count * 100) if entities_count > 0 else 0

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Documents processed: {processed}/{total}")
    print(f"  Errors:              {errors}")
    print(f"  Entities added:      {total_entities}")
    print(f"  Entities filtered:   {total_filtered} (importance < 0.6)")
    print(f"  Relations added:     {total_relations}")
    print(f"  Final entities:      {entities_count}")
    print(f"  Single-mention:      {single_mention} ({single_ratio:.1f}%)")
    print(f"  Entity types:        {final_stats.get('entity_types', {})}")
    print("=" * 60)

    if single_ratio < 30:
        print(" Quality check PASSED (single-mention < 30%)")
    else:
        print(f"  Quality check WARNING (single-mention {single_ratio:.1f}% > 30%)")

    session_archive.close(silent=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Populate Knowledge Graph from memories")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size for processing")
    parser.add_argument("--max-memories", type=int, default=500, help="Maximum memories to process")
    parser.add_argument("--clean", action="store_true", help="Backup and clear existing graph first")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without saving")

    args = parser.parse_args()

    asyncio.run(populate_knowledge_graph(
        batch_size=args.batch_size,
        max_memories=args.max_memories,
        clean=args.clean,
        dry_run=args.dry_run
    ))
