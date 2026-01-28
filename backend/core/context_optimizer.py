from dataclasses import dataclass
from typing import Dict, List, Literal
from backend.core.logging import get_logger

_log = get_logger("core.ctx_opt")

@dataclass
class SectionBudget:

    name: str
    max_chars: int
    priority: int
    overflow_strategy: Literal["truncate", "summarize", "drop"] = "truncate"
    header_template: str = "## {name}"

TIER_BUDGETS: Dict[str, Dict[str, SectionBudget]] = {
    "axel": {
        "system_prompt": SectionBudget(
            name="System",
            max_chars=30_000,
            priority=1,
            overflow_strategy="truncate",
            header_template=""
        ),
        "temporal": SectionBudget(
            name="대화 맥락",
            max_chars=10_000,
            priority=2,
            overflow_strategy="truncate",
            header_template="## {name}"
        ),
        "working_memory": SectionBudget(
            name="현재 대화",
            max_chars=800_000,
            priority=3,
            overflow_strategy="summarize",
            header_template="## {name}"
        ),
        "session_archive": SectionBudget(
            name="세션 기록",
            max_chars=300_000,
            priority=4,
            overflow_strategy="truncate",
            header_template="## {name}"
        ),
        "long_term": SectionBudget(
            name="장기 기억",
            max_chars=500_000,
            priority=5,
            overflow_strategy="truncate",
            header_template="## {name}"
        ),
        "graphrag": SectionBudget(
            name="관계 기반 지식",
            max_chars=200_000,
            priority=6,
            overflow_strategy="truncate",
            header_template="## {name}"
        ),
    },
}

class ContextOptimizer:

    def __init__(self, tier: str = "axel"):

        self.tier = tier if tier in TIER_BUDGETS else "axel"
        self.budgets = TIER_BUDGETS[self.tier]
        self.sections: Dict[str, str] = {}
        self._stats = {
            "sections_added": 0,
            "sections_truncated": 0,
            "sections_summarized": 0,
            "sections_dropped": 0,
            "total_chars_raw": 0,
            "total_chars_final": 0,
        }

    def add_section(self, name: str, content: str) -> None:

        if not content or not content.strip():
            return

        budget = self.budgets.get(name)
        if not budget:
            _log.warning("Unknown section, using default budget", section=name)
            budget = SectionBudget(name=name, max_chars=2000, priority=99)

        self._stats["sections_added"] += 1
        self._stats["total_chars_raw"] += len(content)

        processed_content = self._apply_budget(content, budget)

        if processed_content:
            self.sections[name] = processed_content
            self._stats["total_chars_final"] += len(processed_content)

    def _apply_budget(self, content: str, budget: SectionBudget) -> str:

        if budget.max_chars <= 0:
            self._stats["sections_dropped"] += 1
            return ""

        if len(content) <= budget.max_chars:
            return content

        if budget.overflow_strategy == "truncate":
            self._stats["sections_truncated"] += 1
            return self._truncate(content, budget.max_chars)

        elif budget.overflow_strategy == "summarize":
            self._stats["sections_summarized"] += 1
            return self._summarize_overflow(content, budget.max_chars)

        elif budget.overflow_strategy == "drop":
            self._stats["sections_dropped"] += 1
            _log.debug("Section dropped due to size", section=budget.name, chars=len(content))
            return ""

        return self._truncate(content, budget.max_chars)

    def _truncate(self, content: str, max_chars: int) -> str:

        if len(content) <= max_chars:
            return content

        suffix = "\n... (truncated)"
        keep = max_chars - len(suffix)

        if keep <= 0:
            return content[:max_chars]

        return content[:keep].rstrip() + suffix

    def _summarize_overflow(self, content: str, max_chars: int) -> str:

        recent_budget = int(max_chars * 0.85)
        summary_budget = max_chars - recent_budget

        turns = self._split_turns(content)

        if len(turns) <= 3:

            return self._truncate(content, max_chars)

        recent_turns = []
        recent_chars = 0

        for turn in reversed(turns):
            if recent_chars + len(turn) > recent_budget:
                break
            recent_turns.insert(0, turn)
            recent_chars += len(turn)

        older_turns = turns[:len(turns) - len(recent_turns)]
        older_count = len(older_turns)

        if older_count > 0:

            older_preview_items = []
            for t in older_turns[:5]:
                lines = t.strip().split('\n')
                first_line = lines[0][:100] if lines else ""
                if first_line:
                    older_preview_items.append(first_line)

            older_preview = "\n  - ".join(older_preview_items) if older_preview_items else ""
            summary = f"[이전 대화 요약: {older_count}개 메시지]\n  - {older_preview}"

            if len(summary) > summary_budget:
                summary = summary[:summary_budget - 3] + "...]"

            return summary + "\n\n" + "\n\n".join(recent_turns)

        return "\n\n".join(recent_turns)

    def _split_turns(self, content: str) -> List[str]:

        import re

        pattern = r'(?=\[(?:User|Assistant|user|assistant|Mark|Axel)\]:|\[\d+[분시간일])'
        turns = re.split(pattern, content)

        return [t.strip() for t in turns if t.strip()]

    def build(self) -> str:

        if not self.sections:
            return ""

        sorted_sections = sorted(
            self.sections.items(),
            key=lambda x: self.budgets.get(x[0], SectionBudget(name="", max_chars=0, priority=99)).priority
        )

        parts = []

        for name, content in sorted_sections:
            if not content or not content.strip():
                continue

            budget = self.budgets.get(name)
            if budget and budget.header_template:
                header = budget.header_template.format(name=budget.name)
                if header:
                    parts.append(f"{header}\n{content}")
                else:
                    parts.append(content)
            else:
                parts.append(content)

        result = "\n\n".join(parts)

        _log.info(
            "Context optimized",
            tier=self.tier,
            sections=self._stats["sections_added"],
            truncated=self._stats["sections_truncated"],
            summarized=self._stats["sections_summarized"],
            dropped=self._stats["sections_dropped"],
            raw_chars=self._stats["total_chars_raw"],
            final_chars=self._stats["total_chars_final"],
            tokens_approx=self._stats["total_chars_final"] // 4
        )

        return result

    def format_as_bullets(self, items: List[str], max_items: int = 10) -> str:

        if not items:
            return ""

        formatted = []
        for item in items[:max_items]:

            item = item.strip()
            if not item:
                continue

            if len(item) > 200:
                item = item[:197] + "..."

            formatted.append(f"- {item}")

        if len(items) > max_items:
            formatted.append(f"- ... ({len(items) - max_items} more)")

        return "\n".join(formatted)

    def get_stats(self) -> Dict:

        return self._stats.copy()

def get_dynamic_system_prompt(tier: str, full_prompt: str) -> str:

    budget = TIER_BUDGETS.get(tier, TIER_BUDGETS["axel"]).get("system_prompt")
    if budget and len(full_prompt) > budget.max_chars:
        return full_prompt[:budget.max_chars - 20] + "\n... (truncated)"

    return full_prompt

def estimate_tokens(text: str) -> int:

    return len(text) // 4
