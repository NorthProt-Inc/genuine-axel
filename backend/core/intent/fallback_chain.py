"""Intent classifier fallback chain architecture.

Supports Protocol-based pluggable classifiers with confidence-based fallback.
"""

from typing import Protocol, runtime_checkable

from backend.core.intent.classifier import IntentResult
from backend.core.logging import get_logger

_log = get_logger("core.intent.chain")


@runtime_checkable
class IntentClassifier(Protocol):
    """Protocol for intent classifiers."""

    def classify(self, text: str) -> IntentResult: ...


class ClassifierChain:
    """Chains multiple classifiers with confidence-based fallback.

    Tries each classifier in order. Returns the first result above
    min_confidence. If none meets the threshold, returns the best result.
    """

    def __init__(
        self,
        classifiers: list[IntentClassifier],
        min_confidence: float = 0.5,
    ) -> None:
        self.classifiers = classifiers
        self.min_confidence = min_confidence

    def classify(self, text: str) -> IntentResult:
        best: IntentResult | None = None

        for classifier in self.classifiers:
            try:
                result = classifier.classify(text)
            except Exception:
                _log.warning(
                    "classifier_error",
                    classifier=type(classifier).__name__,
                )
                continue

            if result.confidence >= self.min_confidence:
                return result

            if best is None or result.confidence > best.confidence:
                best = result

        if best is not None:
            return best

        return IntentResult("chat", 0.1, "fallback")
