#!/usr/bin/env python3
"""Memory optimization script for voice communication readiness.

Cleans both SQLite and ChromaDB stores:
- Phase 1: Delete long/code-heavy conversation turns from SQLite
- Phase 2: Replace role labels in ChromaDB (User->Mark, Assistant/AI->Axel)
- Phase 3: Text cleaning via OpenAI API (emoji removal, spell check, etc.)
- Phase 4: Verification

Usage:
    python scripts/optimize_memory.py phase1 --dry-run
    python scripts/optimize_memory.py phase2 --dry-run
    python scripts/optimize_memory.py phase3 --dry-run --limit 10
    python scripts/optimize_memory.py all --dry-run
    python scripts/optimize_memory.py verify
"""

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


from dotenv import load_dotenv

# Suppress noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("google.genai").setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
DB_PATH = DATA_ROOT / "sqlite" / "sqlite_memory.db"
CHROMADB_PATH = DATA_ROOT / "chroma_db"
BACKUP_DIR = Path("/home/northprot/backups/axnmihn")
CHECKPOINT_DIR = DATA_ROOT / "optimize_checkpoints"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")

# ──────────────────────────────────────────────────────────────────────
# Phase 3 constants
# ──────────────────────────────────────────────────────────────────────
OPENAI_CONCURRENCY = 10
OPENAI_MODEL = "gpt-5-mini-2025-08-07"

CLEAN_TEXT_SYSTEM = "You are a text cleaning assistant. Return only the cleaned text, nothing else."

CLEAN_TEXT_PROMPT = """Clean this message following these rules exactly:
1. Remove ALL emojis and decorative special characters (keep standard punctuation)
2. Fix spelling and grammar errors (Korean and English)
3. When Korean+English equivalents appear together (e.g. "사과(apple)", "데이터베이스(database)"), keep ONLY the English word
4. Preserve original meaning, tone, and all factual content
5. Do NOT summarize or shorten
6. Return ONLY the cleaned text

Message:
{content}"""

# Regex for pre-filtering: detect emoji/special chars or Korean+English patterns
_EMOJI_RE = re.compile(
    "[\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"  # dingbats
    "\U000024c2-\U000024ff"  # enclosed alphanumerics (safe subset)
    "\U0001f170-\U0001f251"  # enclosed ideographic supplement
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols extended-A
    "\U00002600-\U000026ff"  # misc symbols
    "\U00002b00-\U00002bff"  # misc symbols and arrows (⭐ etc)
    "\U00003030\U0000303d"  # wavy dash, part alternation mark
    "\U00003297\U00003299"  # circled ideographs
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"  # ZWJ
    "\U0000200b-\U0000200f"  # zero-width chars
    "\U00002028-\U00002029"  # line/paragraph separators
    "]+",
    re.UNICODE,
)

# Korean word followed by (English) or English followed by (Korean)
_KO_EN_PAIR_RE = re.compile(
    r"[가-힣]+\s*\([a-zA-Z][a-zA-Z\s]*\)"  # 사과(apple)
    r"|[a-zA-Z]+\s*\([가-힣]+\)",  # apple(사과)
)


def _needs_cleaning(content: str) -> bool:
    """Check if content needs cleaning (emoji, ko-en pairs, smart quotes, bracket tags)."""
    if _EMOJI_RE.search(content):
        return True
    if _KO_EN_PAIR_RE.search(content):
        return True
    if _SMART_QUOTES_RE.search(content):
        return True
    if _BRACKET_TAG_RE.search(content):
        return True
    return False


# ======================================================================
# Phase 0: Preparation
# ======================================================================


def phase0_prepare() -> dict[str, int]:
    """Validate environment and create backups.

    Returns:
        Stats dict with message_count and chroma_count.
    """
    load_dotenv(PROJECT_ROOT / ".env")

    # Validate files
    if not DB_PATH.exists():
        logger.error("SQLite DB not found: %s", DB_PATH)
        sys.exit(1)
    if not CHROMADB_PATH.exists():
        logger.error("ChromaDB path not found: %s", CHROMADB_PATH)
        sys.exit(1)

    # Validate API keys
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if not gemini_key:
        logger.error("GEMINI_API_KEY not set")
        sys.exit(1)
    if not openai_key:
        logger.error("OPENAI_API_KEY not set")
        sys.exit(1)

    # Stats
    conn = sqlite3.connect(DB_PATH)
    msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()

    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))
    collection = client.get_or_create_collection("axnmihn_memory")
    chroma_count = collection.count()

    stats = {"message_count": msg_count, "chroma_count": chroma_count}
    logger.info("Current stats — SQLite: %d messages, ChromaDB: %d docs", msg_count, chroma_count)

    return stats


def phase0_backup() -> None:
    """Create backups of both stores."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    date_tag = datetime.now().strftime("%Y%m%d")

    sqlite_backup = BACKUP_DIR / f"sqlite_memory_pre_optimize_{date_tag}.db"
    chroma_backup = BACKUP_DIR / f"chroma_db_pre_optimize_{date_tag}"

    if sqlite_backup.exists():
        logger.info("SQLite backup already exists: %s", sqlite_backup)
    else:
        shutil.copy2(DB_PATH, sqlite_backup)
        logger.info("SQLite backup: %s", sqlite_backup)

    if chroma_backup.exists():
        logger.info("ChromaDB backup already exists: %s", chroma_backup)
    else:
        shutil.copytree(CHROMADB_PATH, chroma_backup)
        logger.info("ChromaDB backup: %s", chroma_backup)


# ======================================================================
# Phase 1: SQLite — delete long/code turns
# ======================================================================


def _should_delete_turn(axel_content: str) -> bool:
    """Determine if an Axel response turn should be deleted."""
    if len(axel_content) > 2000:
        return True

    code_blocks = re.findall(r"```[\s\S]*?```", axel_content)
    code_ratio = sum(len(b) for b in code_blocks) / max(len(axel_content), 1)
    if code_ratio > 0.5:
        return True

    # 4+ code block pairs = 8+ backtick-triple occurrences
    if axel_content.count("```") >= 8:
        return True

    return False


def phase1_delete_long_turns(dry_run: bool = False) -> dict:
    """Delete conversation turns with long/code-heavy Axel responses.

    Returns:
        Stats dict with counts.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get session info for protection window
    cursor.execute(
        """
        SELECT session_id, MAX(turn_id) AS max_turn
        FROM messages
        GROUP BY session_id
        """
    )
    session_max_turns = {row[0]: row[1] for row in cursor.fetchall()}

    # Find Axel messages that are deletion candidates
    cursor.execute(
        """
        SELECT id, session_id, turn_id, content, emotional_context
        FROM messages
        WHERE role = 'Axel'
        ORDER BY session_id, turn_id
        """
    )
    axel_messages = cursor.fetchall()

    target_axel_ids: list[int] = []
    protected_emotional = 0
    protected_recent = 0

    for msg_id, session_id, turn_id, content, emotional_ctx in axel_messages:
        if not _should_delete_turn(content):
            continue

        # Protect non-neutral emotional context
        if emotional_ctx and emotional_ctx.lower() != "neutral":
            protected_emotional += 1
            continue

        # Protect last 20 turns per session
        max_turn = session_max_turns.get(session_id, 0)
        if turn_id > max_turn - 20:
            protected_recent += 1
            continue

        target_axel_ids.append(msg_id)

    logger.info(
        "Phase 1 — Candidates: %d, Protected (emotional): %d, Protected (recent): %d",
        len(target_axel_ids),
        protected_emotional,
        protected_recent,
    )

    if not target_axel_ids:
        logger.info("Phase 1 — No turns to delete")
        conn.close()
        return {"deleted_turns": 0, "deleted_messages": 0, "orphans_deleted": 0}

    if dry_run:
        # Show sample
        for aid in target_axel_ids[:5]:
            cursor.execute("SELECT content FROM messages WHERE id = ?", (aid,))
            row = cursor.fetchone()
            if row:
                preview = row[0][:100].replace("\n", " ")
                logger.info("  [DRY-RUN] Would delete turn with Axel id=%d: %s...", aid, preview)
        if len(target_axel_ids) > 5:
            logger.info("  ... and %d more", len(target_axel_ids) - 5)
        conn.close()
        return {
            "deleted_turns": len(target_axel_ids),
            "deleted_messages": 0,
            "orphans_deleted": 0,
            "dry_run": True,
        }

    # Delete Axel messages AND their paired Mark messages
    id_placeholders = ",".join("?" * len(target_axel_ids))

    # Find paired Mark message IDs (turn_id - 1 in same session)
    cursor.execute(
        f"""
        SELECT m_mark.id
        FROM messages m_mark
        JOIN messages m_axel ON m_axel.session_id = m_mark.session_id
            AND m_mark.turn_id = m_axel.turn_id - 1
            AND m_mark.role = 'Mark'
        WHERE m_axel.role = 'Axel' AND m_axel.id IN ({id_placeholders})
        """,
        target_axel_ids,
    )
    paired_mark_ids = [row[0] for row in cursor.fetchall()]

    all_ids_to_delete = target_axel_ids + paired_mark_ids
    delete_placeholders = ",".join("?" * len(all_ids_to_delete))

    cursor.execute(
        f"DELETE FROM messages WHERE id IN ({delete_placeholders})",
        all_ids_to_delete,
    )
    turn_deleted = cursor.rowcount
    logger.info("Phase 1 — Deleted %d messages (%d turns)", turn_deleted, len(target_axel_ids))

    # Delete orphan messages (no matching pair)
    cursor.execute(
        """
        DELETE FROM messages WHERE id IN (
            SELECT m.id FROM messages m
            LEFT JOIN messages pair ON pair.session_id = m.session_id
                AND ((m.role = 'Mark' AND pair.turn_id = m.turn_id + 1 AND pair.role = 'Axel')
                  OR (m.role = 'Axel' AND pair.turn_id = m.turn_id - 1 AND pair.role = 'Mark'))
            WHERE pair.id IS NULL
        )
        """
    )
    orphans_deleted = cursor.rowcount
    if orphans_deleted:
        logger.info("Phase 1 — Deleted %d orphan messages", orphans_deleted)

    conn.commit()
    conn.close()

    return {
        "deleted_turns": len(target_axel_ids),
        "deleted_messages": turn_deleted,
        "orphans_deleted": orphans_deleted,
    }


# ======================================================================
# Phase 2: ChromaDB — role label replacement
# ======================================================================


def _replace_role_labels(content: str) -> str:
    """Replace generic role labels with specific names."""
    content = re.sub(r"\bUser:\s", "Mark: ", content)
    content = re.sub(r"\bAssistant:\s", "Axel: ", content)
    content = re.sub(r"\bAI:\s", "Axel: ", content)
    return content


class GeminiKeyRotator:
    """Thread-safe Gemini API key rotator for embedding calls."""

    def __init__(self) -> None:
        load_dotenv(PROJECT_ROOT / ".env")

        keys = [
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GEMINI_API_KEY_1"),
            os.getenv("GEMINI_API_KEY_2"),
        ]
        self.keys = [k for k in keys if k]
        if not self.keys:
            raise ValueError("No GEMINI_API_KEY found in .env")

        from google import genai

        self.clients = [genai.Client(api_key=k) for k in self.keys]
        self._idx = 0
        self._lock = __import__("threading").Lock()
        logger.info("Gemini API keys loaded: %d", len(self.keys))

    def get_client(self):
        with self._lock:
            client = self.clients[self._idx]
            self._idx = (self._idx + 1) % len(self.clients)
            return client


def _embed_single(
    client,
    text: str,
    model: str,
) -> list[float] | None:
    """Generate embedding for a single text."""
    try:
        result = client.models.embed_content(
            model=model,
            contents=text,
            config={"task_type": "retrieval_document"},
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        return None


def phase2_replace_labels(dry_run: bool = False) -> dict:
    """Replace role labels in ChromaDB and re-embed changed documents.

    Returns:
        Stats dict.
    """
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))
    collection = client.get_or_create_collection(
        name="axnmihn_memory",
        metadata={"hnsw:space": "cosine"},
    )

    all_data = collection.get(include=["documents", "metadatas"])
    total = len(all_data["ids"])
    logger.info("Phase 2 — Total ChromaDB documents: %d", total)

    # Find documents needing label changes
    changes: list[tuple[str, str, str]] = []  # (doc_id, old_content, new_content)
    for i, doc_id in enumerate(all_data["ids"]):
        content = all_data["documents"][i] if all_data["documents"] else ""
        if not content:
            continue
        new_content = _replace_role_labels(content)
        if new_content != content:
            changes.append((doc_id, content, new_content))

    logger.info("Phase 2 — Documents needing label change: %d / %d", len(changes), total)

    if not changes:
        return {"total": total, "changed": 0}

    if dry_run:
        for doc_id, old, new in changes[:5]:
            old_preview = old[:80].replace("\n", " ")
            new_preview = new[:80].replace("\n", " ")
            logger.info("  [DRY-RUN] %s", doc_id[:8])
            logger.info("    Old: %s", old_preview)
            logger.info("    New: %s", new_preview)
        if len(changes) > 5:
            logger.info("  ... and %d more", len(changes) - 5)
        return {"total": total, "changed": len(changes), "dry_run": True}

    # Re-embed changed documents
    rotator = GeminiKeyRotator()
    success = 0
    errors = 0

    # Process in batches of 100 for progress reporting
    batch_size = 100
    for batch_start in range(0, len(changes), batch_size):
        batch = changes[batch_start : batch_start + batch_size]

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {}
            for doc_id, _old, new_content in batch:
                gem_client = rotator.get_client()
                future = executor.submit(_embed_single, gem_client, new_content, EMBEDDING_MODEL)
                futures[future] = (doc_id, new_content)

            for future in as_completed(futures):
                doc_id, new_content = futures[future]
                embedding = future.result()
                if embedding:
                    collection.update(
                        ids=[doc_id],
                        documents=[new_content],
                        embeddings=[embedding],
                    )
                    success += 1
                else:
                    errors += 1

        logger.info(
            "Phase 2 — Batch %d/%d done (%d success so far)",
            batch_start // batch_size + 1,
            (len(changes) + batch_size - 1) // batch_size,
            success,
        )

    logger.info("Phase 2 — Updated: %d, Errors: %d", success, errors)
    return {"total": total, "changed": len(changes), "updated": success, "errors": errors}


# ======================================================================
# Phase 3: Text cleaning via OpenAI API
# ======================================================================


async def _clean_single_openai(
    client,
    semaphore: asyncio.Semaphore,
    content: str,
    item_id: str | int,
    max_retries: int = 3,
) -> tuple[str | int, str | None]:
    """Clean a single text item via OpenAI API.

    Returns:
        (item_id, cleaned_content) or (item_id, None) on failure/skip.
    """
    async with semaphore:
        for attempt in range(max_retries):
            try:
                response = await client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": CLEAN_TEXT_SYSTEM},
                        {"role": "user", "content": CLEAN_TEXT_PROMPT.format(content=content)},
                    ],
                    max_completion_tokens=2048,
                )
                cleaned = response.choices[0].message.content.strip()

                # Guard: empty or too short
                if not cleaned:
                    return (item_id, None)

                # Guard: over-shortened (>50% reduction)
                if len(cleaned) < len(content) * 0.5:
                    logger.warning(
                        "Over-shortened (%d -> %d chars), keeping original: id=%s",
                        len(content),
                        len(cleaned),
                        item_id,
                    )
                    return (item_id, None)

                return (item_id, cleaned)

            except Exception as e:
                error_str = str(e).lower()
                if "rate" in error_str or "429" in error_str:
                    wait = (attempt + 1) * 5
                    logger.warning("Rate limited, waiting %ds (attempt %d)", wait, attempt + 1)
                    await asyncio.sleep(wait)
                else:
                    logger.error("OpenAI error for id=%s: %s", item_id, e)
                    await asyncio.sleep(2)

    return (item_id, None)


async def _phase3_sqlite(
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    """Clean SQLite messages via OpenAI."""
    from openai import AsyncOpenAI

    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    semaphore = asyncio.Semaphore(OPENAI_CONCURRENCY)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = "SELECT id, content FROM messages ORDER BY id"
    if limit:
        query += f" LIMIT {limit}"
    cursor.execute(query)
    all_messages = cursor.fetchall()

    # Filter: skip short messages and those that don't need cleaning
    candidates: list[tuple[int, str]] = []
    for msg_id, content in all_messages:
        if not content or len(content.strip()) < 10:
            continue
        if not _needs_cleaning(content):
            continue
        candidates.append((msg_id, content))

    logger.info(
        "Phase 3 (SQLite) — Total: %d, Candidates for cleaning: %d",
        len(all_messages),
        len(candidates),
    )

    if not candidates:
        conn.close()
        return {"total": len(all_messages), "candidates": 0, "updated": 0}

    if dry_run:
        for msg_id, content in candidates[:5]:
            emojis = _EMOJI_RE.findall(content)
            ko_en = _KO_EN_PAIR_RE.findall(content)
            preview = content[:80].replace("\n", " ")
            logger.info(
                "  [DRY-RUN] id=%d emojis=%d ko_en=%d: %s",
                msg_id,
                len(emojis),
                len(ko_en),
                preview,
            )
        if len(candidates) > 5:
            logger.info("  ... and %d more", len(candidates) - 5)
        conn.close()
        return {
            "total": len(all_messages),
            "candidates": len(candidates),
            "updated": 0,
            "dry_run": True,
        }

    # Process via OpenAI in batches
    updated = 0
    skipped = 0
    batch_size = 50

    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]
        tasks = [
            _clean_single_openai(openai_client, semaphore, content, msg_id)
            for msg_id, content in batch
        ]
        results = await asyncio.gather(*tasks)

        for msg_id, cleaned in results:
            if cleaned:
                cursor.execute("UPDATE messages SET content = ? WHERE id = ?", (cleaned, msg_id))
                updated += 1
            else:
                skipped += 1

        conn.commit()
        logger.info(
            "Phase 3 (SQLite) — Batch %d/%d: updated=%d, skipped=%d",
            batch_start // batch_size + 1,
            (len(candidates) + batch_size - 1) // batch_size,
            updated,
            skipped,
        )

    conn.close()

    logger.info("Phase 3 (SQLite) — Updated: %d / %d candidates", updated, len(candidates))
    return {"total": len(all_messages), "candidates": len(candidates), "updated": updated}


async def _phase3_chroma(
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    """Clean ChromaDB documents via OpenAI, then re-embed."""
    import chromadb
    from openai import AsyncOpenAI

    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    semaphore = asyncio.Semaphore(OPENAI_CONCURRENCY)

    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))
    collection = client.get_or_create_collection(
        name="axnmihn_memory",
        metadata={"hnsw:space": "cosine"},
    )

    all_data = collection.get(include=["documents"])
    total = len(all_data["ids"])

    # Filter candidates
    candidates: list[tuple[str, str]] = []
    for i, doc_id in enumerate(all_data["ids"]):
        content = all_data["documents"][i] if all_data["documents"] else ""
        if not content or len(content.strip()) < 10:
            continue
        if not _needs_cleaning(content):
            continue
        candidates.append((doc_id, content))
        if limit and len(candidates) >= limit:
            break

    logger.info(
        "Phase 3 (ChromaDB) — Total: %d, Candidates for cleaning: %d",
        total,
        len(candidates),
    )

    if not candidates:
        return {"total": total, "candidates": 0, "updated": 0}

    if dry_run:
        for doc_id, content in candidates[:5]:
            emojis = _EMOJI_RE.findall(content)
            ko_en = _KO_EN_PAIR_RE.findall(content)
            preview = content[:80].replace("\n", " ")
            logger.info(
                "  [DRY-RUN] %s emojis=%d ko_en=%d: %s",
                doc_id[:8],
                len(emojis),
                len(ko_en),
                preview,
            )
        if len(candidates) > 5:
            logger.info("  ... and %d more", len(candidates) - 5)
        return {
            "total": total,
            "candidates": len(candidates),
            "updated": 0,
            "dry_run": True,
        }

    # Clean via OpenAI + re-embed, in batches
    rotator = GeminiKeyRotator()
    updated = 0
    errors = 0
    skipped = 0
    batch_size = 50

    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]

        # OpenAI cleaning
        tasks = [
            _clean_single_openai(openai_client, semaphore, content, doc_id)
            for doc_id, content in batch
        ]
        results = await asyncio.gather(*tasks)

        # Re-embed changed docs
        changed_docs: list[tuple[str, str]] = []
        for doc_id, cleaned in results:
            if cleaned:
                changed_docs.append((str(doc_id), cleaned))
            else:
                skipped += 1

        if changed_docs:
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {}
                for doc_id, new_content in changed_docs:
                    gem_client = rotator.get_client()
                    future = executor.submit(
                        _embed_single, gem_client, new_content, EMBEDDING_MODEL
                    )
                    futures[future] = (doc_id, new_content)

                for future in as_completed(futures):
                    doc_id, new_content = futures[future]
                    embedding = future.result()
                    if embedding:
                        collection.update(
                            ids=[doc_id],
                            documents=[new_content],
                            embeddings=[embedding],
                        )
                        updated += 1
                    else:
                        errors += 1

        logger.info(
            "Phase 3 (ChromaDB) — Batch %d/%d: updated=%d, skipped=%d, errors=%d",
            batch_start // batch_size + 1,
            (len(candidates) + batch_size - 1) // batch_size,
            updated,
            skipped,
            errors,
        )

    logger.info(
        "Phase 3 (ChromaDB) — Updated: %d, Errors: %d / %d candidates",
        updated,
        errors,
        len(candidates),
    )
    return {"total": total, "candidates": len(candidates), "updated": updated, "errors": errors}


async def phase3_clean_text(
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    """Run text cleaning on both stores."""
    sqlite_result = await _phase3_sqlite(dry_run=dry_run, limit=limit)
    chroma_result = await _phase3_chroma(dry_run=dry_run, limit=limit)
    return {"sqlite": sqlite_result, "chroma": chroma_result}


# ======================================================================
# Phase 3R: Regex-based text stripping (no LLM)
# ======================================================================

# More complete Korean-English pair patterns for replacement
_KO_EN_REPLACE_RE = re.compile(
    r"([가-힣]+)\s*\(([a-zA-Z][a-zA-Z\s\-]*)\)"  # 사과(apple) -> apple
)
_EN_KO_REPLACE_RE = re.compile(
    r"([a-zA-Z][a-zA-Z\s\-]*)\s*\(([가-힣]+)\)"  # apple(사과) -> apple
)


_SMART_QUOTES_RE = re.compile(r"[\u2018\u2019\u201c\u201d]")  # ' ' " "

# [bracketed content] — system tags, audit markers, etc.
_BRACKET_TAG_RE = re.compile(r"\[(?:System[^]]*|SYSTEM[^]]*|Semantic[^]]*|기억/[^]]*)\]")


def _strip_text(content: str) -> str:
    """Strip emojis, smart quotes, bracket tags, and normalize Korean-English pairs."""
    # Remove emojis
    result = _EMOJI_RE.sub("", content)

    # Remove smart quotes -> regular quotes
    result = _SMART_QUOTES_RE.sub("'", result)

    # Remove [System ...], [SYSTEM ...], [Semantic ...] bracket tags
    result = _BRACKET_TAG_RE.sub("", result)

    # Korean(English) -> English
    result = _KO_EN_REPLACE_RE.sub(r"\2", result)

    # English(Korean) -> English
    result = _EN_KO_REPLACE_RE.sub(r"\1", result)

    # Clean up: collapse multiple spaces, strip lines
    result = re.sub(r"  +", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = result.strip()

    return result


def phase3r_regex_strip(dry_run: bool = False, limit: int | None = None) -> dict:
    """Strip emojis and normalize Korean-English pairs using regex (no LLM).

    Also processes ChromaDB documents and re-embeds them.
    """
    # ── SQLite ──
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = "SELECT id, content FROM messages ORDER BY id"
    if limit:
        query += f" LIMIT {limit}"
    cursor.execute(query)
    all_messages = cursor.fetchall()

    sqlite_candidates = 0
    sqlite_updated = 0

    for msg_id, content in all_messages:
        if not content or len(content.strip()) < 5:
            continue
        if not _needs_cleaning(content):
            continue
        sqlite_candidates += 1
        stripped = _strip_text(content)
        if stripped != content and stripped:
            if dry_run:
                if sqlite_updated < 5:
                    logger.info(
                        "  [DRY-RUN] id=%d: '%s' -> '%s'",
                        msg_id,
                        content[:50].replace("\n", " "),
                        stripped[:50].replace("\n", " "),
                    )
            else:
                cursor.execute("UPDATE messages SET content = ? WHERE id = ?", (stripped, msg_id))
            sqlite_updated += 1

    if not dry_run:
        conn.commit()
    conn.close()

    logger.info(
        "Phase 3R (SQLite) — Candidates: %d, %s: %d",
        sqlite_candidates,
        "would update" if dry_run else "updated",
        sqlite_updated,
    )

    # ── ChromaDB ──
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))
    collection = client.get_or_create_collection(
        name="axnmihn_memory",
        metadata={"hnsw:space": "cosine"},
    )

    all_data = collection.get(include=["documents"])
    total_chroma = len(all_data["ids"])

    chroma_changes: list[tuple[str, str]] = []
    for i, doc_id in enumerate(all_data["ids"]):
        content = all_data["documents"][i] if all_data["documents"] else ""
        if not content or len(content.strip()) < 5:
            continue
        if not _needs_cleaning(content):
            continue
        stripped = _strip_text(content)
        if stripped != content and stripped:
            chroma_changes.append((doc_id, stripped))
            if limit and len(chroma_changes) >= limit:
                break

    logger.info(
        "Phase 3R (ChromaDB) — Total: %d, Changes: %d",
        total_chroma,
        len(chroma_changes),
    )

    chroma_updated = 0
    chroma_errors = 0

    if chroma_changes and not dry_run:
        rotator = GeminiKeyRotator()
        batch_size = 100

        for batch_start in range(0, len(chroma_changes), batch_size):
            batch = chroma_changes[batch_start : batch_start + batch_size]

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {}
                for doc_id, new_content in batch:
                    gem_client = rotator.get_client()
                    future = executor.submit(
                        _embed_single, gem_client, new_content, EMBEDDING_MODEL
                    )
                    futures[future] = (doc_id, new_content)

                for future in as_completed(futures):
                    doc_id, new_content = futures[future]
                    embedding = future.result()
                    if embedding:
                        collection.update(
                            ids=[doc_id],
                            documents=[new_content],
                            embeddings=[embedding],
                        )
                        chroma_updated += 1
                    else:
                        chroma_errors += 1

            logger.info(
                "Phase 3R (ChromaDB) — Batch %d/%d: updated=%d",
                batch_start // batch_size + 1,
                (len(chroma_changes) + batch_size - 1) // batch_size,
                chroma_updated,
            )
    elif dry_run and chroma_changes:
        for doc_id, stripped in chroma_changes[:5]:
            logger.info("  [DRY-RUN] %s: %s", doc_id[:8], stripped[:60].replace("\n", " "))
        if len(chroma_changes) > 5:
            logger.info("  ... and %d more", len(chroma_changes) - 5)
        chroma_updated = len(chroma_changes)

    return {
        "sqlite": {"candidates": sqlite_candidates, "updated": sqlite_updated},
        "chroma": {"total": total_chroma, "changed": len(chroma_changes), "updated": chroma_updated, "errors": chroma_errors},
    }


# ======================================================================
# Phase 4: Verification
# ======================================================================


def phase4_verify() -> dict:
    """Run verification checks on both stores."""
    results: dict = {}

    # Check 1: No long Axel messages remaining
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM messages WHERE role='Axel' AND LENGTH(content) > 2000"
    )
    long_axel = cursor.fetchone()[0]
    results["long_axel_remaining"] = long_axel
    logger.info("Verify — Long Axel messages (>2000 chars): %d", long_axel)

    # Check 2: No old role labels in ChromaDB
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMADB_PATH))
    collection = client.get_or_create_collection("axnmihn_memory")
    all_data = collection.get(include=["documents"])

    old_label_count = 0
    for doc in all_data["documents"] or []:
        if doc and (
            re.search(r"\bUser:\s", doc)
            or re.search(r"\bAssistant:\s", doc)
            or re.search(r"\bAI:\s", doc)
        ):
            old_label_count += 1
    results["old_labels_remaining"] = old_label_count
    logger.info("Verify — ChromaDB docs with old labels: %d", old_label_count)

    # Check 3: Random sample for emoji/ko-en patterns
    cursor.execute("SELECT id, content FROM messages ORDER BY RANDOM() LIMIT 10")
    samples = cursor.fetchall()
    emoji_found = 0
    ko_en_found = 0
    logger.info("Verify — Random 10-message sample:")
    for msg_id, content in samples:
        emojis = _EMOJI_RE.findall(content) if content else []
        ko_en = _KO_EN_PAIR_RE.findall(content) if content else []
        if emojis:
            emoji_found += 1
        if ko_en:
            ko_en_found += 1
        preview = (content or "")[:60].replace("\n", " ")
        logger.info(
            "  id=%d emojis=%d ko_en=%d: %s",
            msg_id,
            len(emojis),
            len(ko_en),
            preview,
        )

    results["sample_emoji_count"] = emoji_found
    results["sample_ko_en_count"] = ko_en_found

    # Overall stats
    msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    chroma_count = collection.count()
    results["final_message_count"] = msg_count
    results["final_chroma_count"] = chroma_count

    logger.info("Verify — Final stats: SQLite=%d messages, ChromaDB=%d docs", msg_count, chroma_count)

    conn.close()
    return results


# ======================================================================
# CLI
# ======================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memory optimization for voice communication readiness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/optimize_memory.py phase1 --dry-run
  python scripts/optimize_memory.py phase1
  python scripts/optimize_memory.py phase2 --dry-run
  python scripts/optimize_memory.py phase2
  python scripts/optimize_memory.py phase3 --dry-run
  python scripts/optimize_memory.py phase3 --limit 10
  python scripts/optimize_memory.py phase3
  python scripts/optimize_memory.py all --dry-run
  python scripts/optimize_memory.py all
  python scripts/optimize_memory.py verify
        """,
    )
    parser.add_argument(
        "phase",
        choices=["phase1", "phase2", "phase3", "strip", "all", "verify"],
        help="Which phase to run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying data",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of items to process (for testing)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()
    start_time = time.time()

    # Phase 0: always runs
    before_stats = phase0_prepare()
    if not args.dry_run and args.phase != "verify":
        phase0_backup()

    all_results: dict = {"before": before_stats}
    phases_to_run: list[str] = []

    if args.phase == "all":
        phases_to_run = ["phase1", "phase2", "strip"]
    elif args.phase == "verify":
        phases_to_run = ["verify"]
    else:
        phases_to_run = [args.phase]

    for phase in phases_to_run:
        if phase == "phase1":
            logger.info("=" * 60)
            logger.info("Phase 1: Delete long/code turns from SQLite")
            logger.info("=" * 60)
            all_results["phase1"] = phase1_delete_long_turns(dry_run=args.dry_run)

        elif phase == "phase2":
            logger.info("=" * 60)
            logger.info("Phase 2: Replace role labels in ChromaDB")
            logger.info("=" * 60)
            all_results["phase2"] = phase2_replace_labels(dry_run=args.dry_run)

        elif phase == "phase3":
            logger.info("=" * 60)
            logger.info("Phase 3: Text cleaning via OpenAI API")
            logger.info("=" * 60)
            all_results["phase3"] = asyncio.run(
                phase3_clean_text(dry_run=args.dry_run, limit=args.limit)
            )

        elif phase == "strip":
            logger.info("=" * 60)
            logger.info("Phase 3R: Regex text stripping (no LLM)")
            logger.info("=" * 60)
            all_results["strip"] = phase3r_regex_strip(
                dry_run=args.dry_run, limit=args.limit
            )

        elif phase == "verify":
            logger.info("=" * 60)
            logger.info("Phase 4: Verification")
            logger.info("=" * 60)
            all_results["verify"] = phase4_verify()

    elapsed = time.time() - start_time
    all_results["elapsed_seconds"] = round(elapsed, 1)

    # After stats
    if args.phase != "verify" and not args.dry_run:
        conn = sqlite3.connect(DB_PATH)
        after_msg = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()

        import chromadb

        chroma_client = chromadb.PersistentClient(path=str(CHROMADB_PATH))
        chroma_col = chroma_client.get_or_create_collection("axnmihn_memory")
        after_chroma = chroma_col.count()

        all_results["after"] = {"message_count": after_msg, "chroma_count": after_chroma}
        logger.info(
            "After — SQLite: %d messages (was %d), ChromaDB: %d docs (was %d)",
            after_msg,
            before_stats["message_count"],
            after_chroma,
            before_stats["chroma_count"],
        )

    logger.info("Total elapsed: %.1fs", elapsed)

    if args.json:
        print(json.dumps(all_results, indent=2, ensure_ascii=False))
    else:
        print()
        print("=" * 40)
        print("Memory Optimization Results")
        print("=" * 40)
        print(f"  Elapsed: {elapsed:.1f}s")
        if "phase1" in all_results:
            p1 = all_results["phase1"]
            print(f"  Phase 1: {p1.get('deleted_turns', 0)} turns deleted, "
                  f"{p1.get('orphans_deleted', 0)} orphans")
        if "phase2" in all_results:
            p2 = all_results["phase2"]
            print(f"  Phase 2: {p2.get('changed', 0)} labels changed, "
                  f"{p2.get('updated', 0)} re-embedded")
        if "phase3" in all_results:
            p3 = all_results["phase3"]
            sq = p3.get("sqlite", {})
            ch = p3.get("chroma", {})
            print(f"  Phase 3 (SQLite): {sq.get('updated', 0)}/{sq.get('candidates', 0)} cleaned")
            print(f"  Phase 3 (ChromaDB): {ch.get('updated', 0)}/{ch.get('candidates', 0)} cleaned")
        if "strip" in all_results:
            s = all_results["strip"]
            sq = s.get("sqlite", {})
            ch = s.get("chroma", {})
            print(f"  Strip (SQLite): {sq.get('updated', 0)}/{sq.get('candidates', 0)} stripped")
            print(f"  Strip (ChromaDB): {ch.get('updated', 0)}/{ch.get('changed', 0)} stripped")
        if "verify" in all_results:
            v = all_results["verify"]
            print(f"  Long Axel remaining: {v.get('long_axel_remaining', '?')}")
            print(f"  Old labels remaining: {v.get('old_labels_remaining', '?')}")
            print(f"  Final: SQLite={v.get('final_message_count', '?')}, "
                  f"ChromaDB={v.get('final_chroma_count', '?')}")
        if "after" in all_results:
            a = all_results["after"]
            b = all_results["before"]
            print(f"  Before/After: SQLite {b['message_count']} -> {a['message_count']}, "
                  f"ChromaDB {b['chroma_count']} -> {a['chroma_count']}")


if __name__ == "__main__":
    main()
