"""Prometheus-compatible metrics system.

Lightweight, zero-dependency metrics with Counter, Gauge, and Histogram types.
"""

from dataclasses import dataclass, field


@dataclass
class Counter:
    """Monotonically increasing counter."""

    name: str
    help: str
    _value: float = field(default=0, init=False, repr=False)

    @property
    def value(self) -> float:
        return self._value

    def inc(self, amount: float = 1) -> None:
        if amount < 0:
            raise ValueError("Counter cannot decrease")
        self._value += amount

    def format(self) -> str:
        return (
            f"# HELP {self.name} {self.help}\n"
            f"# TYPE {self.name} counter\n"
            f"{self.name} {self._value}"
        )


@dataclass
class Gauge:
    """Value that can go up and down."""

    name: str
    help: str
    _value: float = field(default=0, init=False, repr=False)

    @property
    def value(self) -> float:
        return self._value

    def set(self, val: float) -> None:
        self._value = val

    def inc(self, amount: float = 1) -> None:
        self._value += amount

    def dec(self, amount: float = 1) -> None:
        self._value -= amount

    def format(self) -> str:
        return (
            f"# HELP {self.name} {self.help}\n"
            f"# TYPE {self.name} gauge\n"
            f"{self.name} {self._value}"
        )


@dataclass
class Histogram:
    """Observation-based histogram with configurable buckets."""

    name: str
    help: str
    buckets: list[float] = field(default_factory=lambda: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10])
    _counts: dict[float, int] = field(default_factory=dict, init=False, repr=False)
    _count: int = field(default=0, init=False, repr=False)
    _total: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.buckets = sorted(self.buckets)
        self._counts = {b: 0 for b in self.buckets}

    @property
    def count(self) -> int:
        return self._count

    @property
    def total(self) -> float:
        return self._total

    def observe(self, value: float) -> None:
        self._count += 1
        self._total += value
        for b in self.buckets:
            if value <= b:
                self._counts[b] += 1

    def format(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help}",
            f"# TYPE {self.name} histogram",
        ]
        cumulative = 0
        for b in self.buckets:
            cumulative += self._counts[b]
            lines.append(f'{self.name}_bucket{{le="{b}"}} {cumulative}')
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._count}')
        lines.append(f"{self.name}_sum {self._total}")
        lines.append(f"{self.name}_count {self._count}")
        return "\n".join(lines)


class MetricsRegistry:
    """Registry for all metrics."""

    def __init__(self) -> None:
        self._metrics: dict[str, Counter | Gauge | Histogram] = {}

    def counter(self, name: str, help_text: str) -> Counter:
        if name in self._metrics:
            return self._metrics[name]  # type: ignore[return-value]
        c = Counter(name, help_text)
        self._metrics[name] = c
        return c

    def gauge(self, name: str, help_text: str) -> Gauge:
        if name in self._metrics:
            return self._metrics[name]  # type: ignore[return-value]
        g = Gauge(name, help_text)
        self._metrics[name] = g
        return g

    def histogram(
        self, name: str, help_text: str, buckets: list[float] | None = None
    ) -> Histogram:
        if name in self._metrics:
            return self._metrics[name]  # type: ignore[return-value]
        h = Histogram(name, help_text, buckets=buckets or [0.01, 0.05, 0.1, 0.5, 1, 5, 10])
        self._metrics[name] = h
        return h

    def format_all(self) -> str:
        return "\n\n".join(m.format() for m in self._metrics.values())
