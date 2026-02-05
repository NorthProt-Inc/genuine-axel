"""Legacy memory migration utilities."""

from typing import Dict, Any

import chromadb

from backend.core.logging import get_logger
from backend.config import CHROMADB_PATH
from .facade import PromotionCriteria

_log = get_logger("memory.migrator")


class LegacyMemoryMigrator:
    """Migrate data from old ChromaDB storage format."""

    def __init__(
        self,
        old_db_path: str = None,
        new_long_term=None,
    ):
        """Initialize migrator.

        Args:
            old_db_path: Path to old ChromaDB storage
            new_long_term: Target LongTermMemory instance
        """
        db_path = old_db_path or str(CHROMADB_PATH)
        self.old_client = chromadb.PersistentClient(path=db_path)
        self.new_long_term = new_long_term

    def analyze_existing(self) -> Dict[str, Any]:
        """Analyze existing data for migration.

        Returns:
            Report with counts and samples
        """
        report = {
            "total": 0,
            "promotable": 0,
            "rejected": 0,
            "by_reason": {},
            "samples": {"promotable": [], "rejected": []},
        }

        try:
            collections = self.old_client.list_collections()

            for coll in collections:
                results = coll.get(include=["documents", "metadatas"])

                for i, doc in enumerate(results.get("documents", [])):
                    report["total"] += 1

                    metadata = results["metadatas"][i] if results.get("metadatas") else {}
                    importance = metadata.get("importance", 0.3)
                    repetitions = metadata.get("repetition_count", 1)

                    should_keep, reason = PromotionCriteria.should_promote(
                        content=doc,
                        repetitions=repetitions,
                        importance=importance,
                    )

                    if should_keep:
                        report["promotable"] += 1
                        if len(report["samples"]["promotable"]) < 5:
                            report["samples"]["promotable"].append(
                                {"content": doc[:100], "reason": reason}
                            )
                    else:
                        report["rejected"] += 1
                        if len(report["samples"]["rejected"]) < 5:
                            report["samples"]["rejected"].append(
                                {"content": doc[:100], "reason": reason}
                            )

                    report["by_reason"][reason] = report["by_reason"].get(reason, 0) + 1

        except Exception as e:
            _log.error("Migration analysis error", error=str(e))

        return report

    def migrate(self, dry_run: bool = True) -> Dict[str, Any]:
        """Run migration.

        Args:
            dry_run: If True, only analyze without migrating

        Returns:
            Migration report
        """
        if not self.new_long_term and not dry_run:
            raise ValueError("new_long_term required for actual migration")

        report = self.analyze_existing()

        if dry_run:
            report["action"] = "dry_run"
            return report

        migrated = 0

        try:
            collections = self.old_client.list_collections()

            for coll in collections:
                results = coll.get(include=["documents", "metadatas"])

                for i, doc in enumerate(results.get("documents", [])):
                    metadata = results["metadatas"][i] if results.get("metadatas") else {}
                    importance = metadata.get("importance", 0.3)
                    repetitions = metadata.get("repetition_count", 1)

                    should_keep, reason = PromotionCriteria.should_promote(
                        content=doc,
                        repetitions=repetitions,
                        importance=importance,
                    )

                    if should_keep:
                        mem_type = metadata.get("type", "insight")
                        if mem_type == "conversation":
                            mem_type = "insight"

                        doc_id = self.new_long_term.add(
                            content=doc,
                            memory_type=mem_type,
                            importance=importance,
                            force=True,
                        )

                        if doc_id:
                            migrated += 1

        except Exception as e:
            _log.error("Migration error", error=str(e))

        report["action"] = "migrated"
        report["migrated_count"] = migrated

        return report
