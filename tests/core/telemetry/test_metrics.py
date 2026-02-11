"""Tests for Prometheus metrics (Wave 3.1)."""

import pytest

from backend.core.telemetry.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
)


class TestCounter:

    def test_initial_value(self):
        c = Counter("requests_total", "Total requests")
        assert c.value == 0

    def test_increment(self):
        c = Counter("requests_total", "Total requests")
        c.inc()
        assert c.value == 1

    def test_increment_by(self):
        c = Counter("requests_total", "Total requests")
        c.inc(5)
        assert c.value == 5

    def test_cannot_decrease(self):
        c = Counter("requests_total", "Total requests")
        c.inc(10)
        with pytest.raises(ValueError):
            c.inc(-1)

    def test_format_prometheus(self):
        c = Counter("requests_total", "Total requests")
        c.inc(42)
        text = c.format()
        assert "# HELP requests_total Total requests" in text
        assert "# TYPE requests_total counter" in text
        assert "requests_total 42" in text


class TestGauge:

    def test_initial_value(self):
        g = Gauge("active_connections", "Active connections")
        assert g.value == 0

    def test_set(self):
        g = Gauge("active_connections", "Active connections")
        g.set(10)
        assert g.value == 10

    def test_inc_dec(self):
        g = Gauge("active_connections", "Active connections")
        g.inc()
        g.inc()
        g.dec()
        assert g.value == 1

    def test_format_prometheus(self):
        g = Gauge("temperature", "Temperature")
        g.set(23.5)
        text = g.format()
        assert "# TYPE temperature gauge" in text
        assert "temperature 23.5" in text


class TestHistogram:

    def test_observe(self):
        h = Histogram("request_duration", "Duration", buckets=[0.1, 0.5, 1.0])
        h.observe(0.3)
        assert h.count == 1
        assert h.total == 0.3

    def test_buckets(self):
        h = Histogram("request_duration", "Duration", buckets=[0.1, 0.5, 1.0])
        h.observe(0.05)
        h.observe(0.3)
        h.observe(0.8)
        h.observe(1.5)
        assert h.count == 4

    def test_format_prometheus(self):
        h = Histogram("request_duration", "Duration", buckets=[0.1, 0.5])
        h.observe(0.05)
        h.observe(0.3)
        text = h.format()
        assert "# TYPE request_duration histogram" in text
        assert 'request_duration_bucket{le="0.1"}' in text
        assert "request_duration_count 2" in text


class TestMetricsRegistry:

    def test_register_counter(self):
        reg = MetricsRegistry()
        c = reg.counter("requests_total", "Total requests")
        assert isinstance(c, Counter)

    def test_register_gauge(self):
        reg = MetricsRegistry()
        g = reg.gauge("active_conns", "Active connections")
        assert isinstance(g, Gauge)

    def test_register_histogram(self):
        reg = MetricsRegistry()
        h = reg.histogram("duration", "Duration")
        assert isinstance(h, Histogram)

    def test_get_existing(self):
        reg = MetricsRegistry()
        c1 = reg.counter("test", "Test")
        c2 = reg.counter("test", "Test")
        assert c1 is c2

    def test_format_all(self):
        reg = MetricsRegistry()
        c = reg.counter("requests", "Requests")
        c.inc(10)
        g = reg.gauge("conns", "Connections")
        g.set(5)
        text = reg.format_all()
        assert "requests 10" in text
        assert "conns 5" in text
