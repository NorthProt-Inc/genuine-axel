#!/usr/bin/env python3

import os
import sys
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import List, Tuple, Optional

from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from backend.config import KNOWLEDGE_GRAPH_PATH

# Try to import native module for optimized string operations
try:
    import axnmihn_native as _native
    _HAS_NATIVE = True
except ImportError:
    _native = None
    _HAS_NATIVE = False

KNOWN_ALIASES = {

    "mark": ["mark_(종민)", "mark(종민)", "종민_(mark)", "종민", "종민(mark)", "mark_종민"],

    "axel": ["axel_ai", "axel_(ai)", "악셀", "액셀"],

    "수면": ["sleep", "수면_(sleep)", "sleep_duration", "sleeping"],
    "건강": ["health", "건강_(health)"],
    "운동": ["exercise", "workout", "운동_(exercise)"],
    "공부": ["study", "studying", "학습"],
    "커피": ["coffee", "카페인", "caffeine"],

    "vs_code": ["vs_code_extension", "vscode", "visual_studio_code"],
    "chromadb": ["chroma_db", "chroma"],
    "docker": ["docker_container", "docker_compose"],
    "git": ["github", "git_repository"],

    "northprot": ["northprot_프로젝트", "northprot_project"],
    "axnmihn": ["axnmihn_backend", "axnmihn_project"],
}

RELATION_NORMALIZATION = {

    "uses": ["사용", "utilizes", "employs", "works_with"],
    "owns": ["소유", "has", "possesses"],
    "manages": ["관리", "handles", "maintains"],

    "resides_in": ["lives_in", "located_in", "based_in", "거주"],

    "knows": ["친구", "friend_of", "acquainted_with"],
    "works_with": ["collaborates_with", "partners_with"],

    "studies": ["learns", "takes_class", "takes_course", "공부"],
    "teaches": ["instructs", "educates"],

    "has_attribute": ["has_property", "characterized_by", "특성"],
    "prefers": ["likes", "enjoys", "favors", "선호"],
}

def normalize_name(name: str) -> str:

    n = name.lower()
    n = n.replace("_", " ").replace("-", " ").replace("(", " ").replace(")", " ")
    n = " ".join(n.split())
    return n

def string_similarity(a: str, b: str) -> float:
    """Calculate string similarity using Levenshtein distance.

    Uses native C++ implementation when available for ~30x speedup.
    """
    if _HAS_NATIVE:
        return _native.string_ops.string_similarity(a, b)
    return SequenceMatcher(None, a, b).ratio()

def extract_core_name(name: str) -> str:

    match = re.match(r'^([^_(]+)', name)
    return match.group(1).strip() if match else name

def find_alias_canonical(entity_id: str, entities: dict) -> Optional[str]:

    entity_lower = entity_id.lower()

    for canonical, aliases in KNOWN_ALIASES.items():
        if entity_lower == canonical:
            return None
        for alias in aliases:
            if entity_lower == alias.lower().replace(" ", "_"):

                canonical_id = canonical.lower().replace(" ", "_")
                if canonical_id in entities:
                    return canonical_id
    return None

def find_duplicates(entities: dict, threshold: float = 0.85) -> List[Tuple[str, str, float, str]]:
    """Find duplicate entities by name similarity.

    Uses native C++ batch processing when available for ~30x speedup
    on the O(N^2) string similarity comparisons.
    """
    duplicates = []
    seen_pairs = set()

    # Phase 1: Known aliases (exact match)
    for canonical, aliases in KNOWN_ALIASES.items():
        canonical_id = canonical.lower().replace(" ", "_")
        if canonical_id in entities:
            for alias in aliases:
                alias_id = alias.lower().replace(" ", "_")
                if alias_id in entities and alias_id != canonical_id:
                    pair = tuple(sorted([canonical_id, alias_id]))
                    if pair not in seen_pairs:
                        duplicates.append((canonical_id, alias_id, 1.0, "known_alias"))
                        seen_pairs.add(pair)

    # Phase 2: Core name matching
    core_to_ids = defaultdict(list)
    for eid, entity in entities.items():
        core = extract_core_name(entity.get("name", eid))
        core_to_ids[normalize_name(core)].append(eid)

    for core, ids in core_to_ids.items():
        if len(ids) > 1:
            ids_sorted = sorted(ids, key=lambda x: entities[x].get("mentions", 0), reverse=True)
            keep_id = ids_sorted[0]
            for remove_id in ids_sorted[1:]:
                pair = tuple(sorted([keep_id, remove_id]))
                if pair not in seen_pairs:
                    duplicates.append((keep_id, remove_id, 0.95, "core_name_match"))
                    seen_pairs.add(pair)

    # Phase 3: String similarity (O(N^2))
    entity_list = list(entities.items())
    n = len(entity_list)

    # Prepare normalized names
    names = [normalize_name(e.get("name", "")) for _, e in entity_list]

    # Use native batch processing if available
    if _HAS_NATIVE and n > 20:
        # Native batch comparison
        native_dups = _native.string_ops.find_string_duplicates(names, threshold)

        for i, j, sim in native_dups:
            id1, e1 = entity_list[i]
            id2, e2 = entity_list[j]

            pair = tuple(sorted([id1, id2]))
            if pair in seen_pairs:
                continue

            if e1.get("mentions", 0) >= e2.get("mentions", 0):
                duplicates.append((id1, id2, sim, "string_similarity"))
            else:
                duplicates.append((id2, id1, sim, "string_similarity"))
            seen_pairs.add(pair)
    else:
        # Python fallback
        for i in range(n):
            id1, e1 = entity_list[i]
            name1 = names[i]

            for j in range(i + 1, n):
                id2, e2 = entity_list[j]
                name2 = names[j]

                pair = tuple(sorted([id1, id2]))
                if pair in seen_pairs:
                    continue

                sim = string_similarity(name1, name2)
                if sim >= threshold:
                    if e1.get("mentions", 0) >= e2.get("mentions", 0):
                        duplicates.append((id1, id2, sim, "string_similarity"))
                    else:
                        duplicates.append((id2, id1, sim, "string_similarity"))
                    seen_pairs.add(pair)

    return duplicates

def find_dead_entities(entities: dict, relations: dict, min_age_days: int = 7) -> List[str]:

    dead = []
    cutoff = datetime.now().astimezone() - timedelta(days=min_age_days)

    related_entities = set()
    for rel in relations.values():
        related_entities.add(rel.get("source_id"))
        related_entities.add(rel.get("target_id"))

    for eid, entity in entities.items():
        mentions = entity.get("mentions", 0)

        if mentions > 0 or eid in related_entities:
            continue

        created_str = entity.get("created_at", "")
        if created_str:
            try:
                created = datetime.fromisoformat(created_str)
                if created < cutoff:
                    dead.append(eid)
            except ValueError:
                # 파싱 불가 날짜 → 오래된 것으로 간주
                dead.append(eid)

    return dead

def normalize_relation_type(rel_type: str) -> str:

    rel_lower = rel_type.lower().replace(" ", "_")

    for standard, variants in RELATION_NORMALIZATION.items():
        if rel_lower == standard or rel_lower in [v.lower() for v in variants]:
            return standard

    return rel_type

def find_orphan_relations(entities: dict, relations: dict) -> List[str]:

    orphans = []
    entity_ids = set(entities.keys())

    for rid, rel in relations.items():
        source = rel.get("source_id")
        target = rel.get("target_id")

        if source not in entity_ids or target not in entity_ids:
            orphans.append(rid)

    return orphans

def recalculate_importance(entities: dict, relations: dict) -> dict:

    in_degree = defaultdict(int)
    out_degree = defaultdict(int)

    for rel in relations.values():
        out_degree[rel.get("source_id")] += 1
        in_degree[rel.get("target_id")] += 1

    now = datetime.now().astimezone()

    for eid, entity in entities.items():
        mentions = entity.get("mentions", 0)
        total_degree = in_degree[eid] + out_degree[eid]

        last_accessed_str = entity.get("last_accessed", entity.get("created_at", ""))
        recency_factor = 0.5
        if last_accessed_str:
            try:
                last_accessed = datetime.fromisoformat(last_accessed_str)
                days_ago = (now - last_accessed).days
                recency_factor = max(0.5, 1.0 - (days_ago / 30) * 0.5)
            except (ValueError, TypeError):
                recency_factor = 0.5  # 명시적 기본값

        mention_score = min(1.0, mentions / 100)
        relation_score = min(1.0, total_degree / 20)

        importance = (
            0.5 * mention_score +
            0.3 * relation_score +
            0.2 * recency_factor
        )

        if entity.get("entity_type") == "person":
            importance = min(1.0, importance * 1.2)

        entity.setdefault("properties", {})["importance"] = round(importance, 2)

    return entities

def optimize_knowledge_graph(kg_path: str, dry_run: bool = True, prune_dead: bool = False):

    print("=" * 70)
    mode = "[DRY RUN] " if dry_run else ""
    print(f"{mode}Knowledge Graph Optimization")
    print("=" * 70)

    with open(kg_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    entities = data.get("entities", {})
    relations = data.get("relations", {})

    print(f"\n📊 Initial State:")
    print(f"   Entities: {len(entities)}")
    print(f"   Relations: {len(relations)}")

    print(f"\n[1/5] Finding duplicates...")
    duplicates = find_duplicates(entities, threshold=0.85)

    print(f"   Found {len(duplicates)} duplicate pairs:")
    for keep_id, remove_id, sim, reason in duplicates[:10]:
        keep_name = entities.get(keep_id, {}).get("name", keep_id)
        remove_name = entities.get(remove_id, {}).get("name", remove_id)
        print(f"   • {keep_name} ← {remove_name} ({reason}, {sim:.0%})")
    if len(duplicates) > 10:
        print(f"   ... and {len(duplicates) - 10} more")

    print(f"\n[2/5] Finding dead entities...")
    dead_entities = find_dead_entities(entities, relations) if prune_dead else []
    print(f"   Found {len(dead_entities)} dead entities (no mentions, no relations, >7 days old)")
    for eid in dead_entities[:5]:
        print(f"   • {entities[eid].get('name', eid)}")
    if len(dead_entities) > 5:
        print(f"   ... and {len(dead_entities) - 5} more")

    print(f"\n[3/5] Finding orphan relations...")
    orphan_relations = find_orphan_relations(entities, relations)
    print(f"   Found {len(orphan_relations)} orphan relations")

    print(f"\n[4/5] Analyzing relation types...")
    relation_types = defaultdict(int)
    for rel in relations.values():
        relation_types[rel.get("relation_type", "unknown")] += 1

    print(f"   Top relation types:")
    for rt, count in sorted(relation_types.items(), key=lambda x: -x[1])[:10]:
        normalized = normalize_relation_type(rt)
        marker = " → " + normalized if normalized != rt else ""
        print(f"   • {rt}: {count}{marker}")

    if dry_run:
        print(f"\n{'=' * 70}")
        print("[DRY RUN] No changes made. Run with --apply to execute.")
        print(f"{'=' * 70}")
        return

    print(f"\n[5/5] Applying changes...")

    id_mapping = {}
    merged_count = 0

    for keep_id, remove_id, sim, reason in duplicates:
        if remove_id in entities and keep_id in entities:
            keep_entity = entities[keep_id]
            remove_entity = entities[remove_id]

            keep_entity["mentions"] = keep_entity.get("mentions", 0) + remove_entity.get("mentions", 0)

            keep_last = keep_entity.get("last_accessed", "")
            remove_last = remove_entity.get("last_accessed", "")
            if remove_last > keep_last:
                keep_entity["last_accessed"] = remove_last

            id_mapping[remove_id] = keep_id
            del entities[remove_id]
            merged_count += 1

    print(f"   ✓ Merged {merged_count} duplicate entities")

    pruned_count = 0
    for eid in dead_entities:
        if eid in entities:
            del entities[eid]
            pruned_count += 1

    print(f"   ✓ Pruned {pruned_count} dead entities")

    updated_relations = {}
    normalized_count = 0

    for rid, rel in relations.items():
        source = id_mapping.get(rel["source_id"], rel["source_id"])
        target = id_mapping.get(rel["target_id"], rel["target_id"])

        if source not in entities or target not in entities:
            continue
        if source == target:
            continue

        old_type = rel["relation_type"]
        new_type = normalize_relation_type(old_type)
        if new_type != old_type:
            normalized_count += 1

        rel["source_id"] = source
        rel["target_id"] = target
        rel["relation_type"] = new_type

        new_rid = f"{source}--{new_type}-->{target}"
        if new_rid not in updated_relations:
            updated_relations[new_rid] = rel

    print(f"   ✓ Normalized {normalized_count} relation types")
    print(f"   ✓ Removed {len(relations) - len(updated_relations)} orphan/duplicate relations")

    entities = recalculate_importance(entities, updated_relations)
    print(f"   ✓ Recalculated importance scores")

    data["entities"] = entities
    data["relations"] = updated_relations
    data["last_optimized"] = datetime.now().astimezone().isoformat()

    with open(kg_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print("📊 Final State:")
    print(f"   Entities: {len(entities)}")
    print(f"   Relations: {len(updated_relations)}")
    print(f"{'=' * 70}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Knowledge Graph Optimization")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview changes without applying (default)")
    parser.add_argument("--apply", action="store_true",
                        help="Apply changes to knowledge graph")
    parser.add_argument("--prune", action="store_true",
                        help="Also prune dead entities (no mentions, no relations)")
    args = parser.parse_args()

    dry_run = not args.apply
    optimize_knowledge_graph(
        str(KNOWLEDGE_GRAPH_PATH),
        dry_run=dry_run,
        prune_dead=args.prune
    )
