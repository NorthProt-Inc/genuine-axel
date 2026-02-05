"""Tests for native decay module."""

import math
import pytest
import sys
from pathlib import Path

# Add backend to path for importing decay_calculator
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Try to import native module
try:
    import axnmihn_native as native
    HAS_NATIVE = True
except ImportError:
    native = None
    HAS_NATIVE = False


def python_calculate(
    importance: float,
    hours_passed: float,
    access_count: int = 0,
    connection_count: int = 0,
    last_access_hours: float = -1.0,
    memory_type: int = 0,
    base_decay_rate: float = 0.002,
    min_retention: float = 0.1,
    access_stability_k: float = 0.3,
    relation_resistance_k: float = 0.1,
) -> float:
    """Pure Python implementation for verification."""
    type_multipliers = [1.0, 0.3, 0.5, 0.7]  # conv, fact, pref, insight

    if hours_passed < 0:
        return importance

    stability = 1.0 + access_stability_k * math.log(1 + access_count)
    resistance = min(1.0, connection_count * relation_resistance_k)
    type_mult = type_multipliers[memory_type]

    effective_rate = base_decay_rate * type_mult / stability * (1.0 - resistance)
    decayed = importance * math.exp(-effective_rate * hours_passed)

    # Recency paradox
    if last_access_hours >= 0 and hours_passed > 168.0 and last_access_hours < 24.0:
        decayed *= 1.3

    return max(decayed, importance * min_retention)


@pytest.fixture
def decay_config():
    """Create a DecayConfig with default values."""
    if not HAS_NATIVE:
        pytest.skip("Native module not available")

    config = native.decay_ops.DecayConfig()
    config.base_decay_rate = 0.002
    config.min_retention = 0.1
    config.access_stability_k = 0.3
    config.relation_resistance_k = 0.1
    config.set_type_multipliers(1.0, 0.3, 0.5, 0.7)
    return config


@pytest.mark.skipif(not HAS_NATIVE, reason="Native module not available")
class TestDecayCalculate:
    """Test single decay calculation."""

    def test_basic_decay(self, decay_config):
        """Test basic decay calculation."""
        inp = native.decay_ops.DecayInput(
            importance=1.0,
            hours_passed=100.0,
            access_count=0,
            connection_count=0,
            last_access_hours=-1.0,
            memory_type=0,
        )

        result = native.decay_ops.calculate(inp, decay_config)
        expected = python_calculate(1.0, 100.0)

        assert abs(result - expected) < 1e-6, f"Expected {expected}, got {result}"

    def test_no_decay_at_zero_hours(self, decay_config):
        """Test that no decay occurs at 0 hours."""
        inp = native.decay_ops.DecayInput(
            importance=0.8,
            hours_passed=0.0,
        )

        result = native.decay_ops.calculate(inp, decay_config)
        expected = python_calculate(0.8, 0.0)

        assert abs(result - expected) < 1e-6

    def test_access_count_slows_decay(self, decay_config):
        """Test that higher access count slows decay."""
        inp_no_access = native.decay_ops.DecayInput(
            importance=1.0, hours_passed=500.0, access_count=0
        )
        inp_high_access = native.decay_ops.DecayInput(
            importance=1.0, hours_passed=500.0, access_count=100
        )

        result_no = native.decay_ops.calculate(inp_no_access, decay_config)
        result_high = native.decay_ops.calculate(inp_high_access, decay_config)

        assert result_high > result_no, "Higher access count should slow decay"

    def test_connection_count_slows_decay(self, decay_config):
        """Test that graph connections slow decay."""
        inp_no_conn = native.decay_ops.DecayInput(
            importance=1.0, hours_passed=500.0, connection_count=0
        )
        inp_high_conn = native.decay_ops.DecayInput(
            importance=1.0, hours_passed=500.0, connection_count=10
        )

        result_no = native.decay_ops.calculate(inp_no_conn, decay_config)
        result_high = native.decay_ops.calculate(inp_high_conn, decay_config)

        assert result_high > result_no, "Higher connection count should slow decay"

    def test_fact_type_decays_slower(self, decay_config):
        """Test that facts decay slower than conversations."""
        inp_conv = native.decay_ops.DecayInput(
            importance=1.0, hours_passed=500.0, memory_type=0  # conversation
        )
        inp_fact = native.decay_ops.DecayInput(
            importance=1.0, hours_passed=500.0, memory_type=1  # fact
        )

        result_conv = native.decay_ops.calculate(inp_conv, decay_config)
        result_fact = native.decay_ops.calculate(inp_fact, decay_config)

        assert result_fact > result_conv, "Facts should decay slower than conversations"

    def test_recency_paradox_boost(self, decay_config):
        """Test recency paradox: old memory recently accessed gets boost."""
        # Old memory (>1 week = 168h) accessed recently (<24h)
        inp_with_boost = native.decay_ops.DecayInput(
            importance=1.0,
            hours_passed=200.0,  # >168h
            last_access_hours=10.0,  # <24h
        )
        inp_without_boost = native.decay_ops.DecayInput(
            importance=1.0,
            hours_passed=200.0,
            last_access_hours=50.0,  # >24h, no boost
        )

        result_with = native.decay_ops.calculate(inp_with_boost, decay_config)
        result_without = native.decay_ops.calculate(inp_without_boost, decay_config)

        assert result_with > result_without, "Recency paradox should apply boost"

    def test_minimum_retention(self, decay_config):
        """Test that result never goes below minimum retention."""
        inp = native.decay_ops.DecayInput(
            importance=1.0,
            hours_passed=100000.0,  # Very old
        )

        result = native.decay_ops.calculate(inp, decay_config)
        min_expected = 1.0 * 0.1  # importance * min_retention

        assert result >= min_expected - 1e-6, "Result should not go below minimum retention"

    def test_matches_python_implementation(self, decay_config):
        """Test that native matches Python implementation across many inputs."""
        test_cases = [
            (0.5, 50.0, 5, 2, -1.0, 0),
            (0.8, 100.0, 0, 0, -1.0, 1),
            (1.0, 200.0, 10, 5, 10.0, 2),
            (0.3, 1000.0, 50, 8, 100.0, 3),
            (0.9, 168.0, 1, 1, 23.0, 0),
            (0.7, 169.0, 1, 1, 23.0, 0),  # Just past recency threshold
        ]

        for imp, hrs, acc, conn, last, mtype in test_cases:
            inp = native.decay_ops.DecayInput(
                importance=imp,
                hours_passed=hrs,
                access_count=acc,
                connection_count=conn,
                last_access_hours=last,
                memory_type=mtype,
            )

            native_result = native.decay_ops.calculate(inp, decay_config)
            python_result = python_calculate(imp, hrs, acc, conn, last, mtype)

            assert abs(native_result - python_result) < 1e-6, (
                f"Mismatch for {(imp, hrs, acc, conn, last, mtype)}: "
                f"native={native_result}, python={python_result}"
            )


@pytest.mark.skipif(not HAS_NATIVE, reason="Native module not available")
class TestDecayBatch:
    """Test batch decay calculation."""

    def test_batch_matches_single(self, decay_config):
        """Test that batch results match individual calculations."""
        inputs = [
            native.decay_ops.DecayInput(0.5, 50.0, 5, 2, -1.0, 0),
            native.decay_ops.DecayInput(0.8, 100.0, 0, 0, -1.0, 1),
            native.decay_ops.DecayInput(1.0, 200.0, 10, 5, 10.0, 2),
        ]

        batch_results = native.decay_ops.calculate_batch(inputs, decay_config)
        single_results = [native.decay_ops.calculate(inp, decay_config) for inp in inputs]

        for i, (batch, single) in enumerate(zip(batch_results, single_results)):
            assert abs(batch - single) < 1e-6, f"Mismatch at index {i}"

    def test_numpy_batch(self, decay_config):
        """Test numpy array batch calculation."""
        import numpy as np

        n = 100
        importance = np.random.uniform(0.1, 1.0, n).astype(np.float64)
        hours_passed = np.random.uniform(0, 1000, n).astype(np.float64)
        access_count = np.random.randint(0, 50, n).astype(np.int32)
        connection_count = np.random.randint(0, 10, n).astype(np.int32)
        last_access_hours = np.random.uniform(-1, 100, n).astype(np.float64)
        memory_type = np.random.randint(0, 4, n).astype(np.int32)

        results = native.decay_ops.calculate_batch_numpy(
            importance, hours_passed, access_count,
            connection_count, last_access_hours, memory_type,
            decay_config
        )

        assert len(results) == n

        # Verify a few against Python
        for i in range(min(10, n)):
            expected = python_calculate(
                importance[i], hours_passed[i], access_count[i],
                connection_count[i], last_access_hours[i], memory_type[i]
            )
            assert abs(results[i] - expected) < 1e-6, f"Mismatch at index {i}"

    def test_empty_batch(self, decay_config):
        """Test empty batch handling."""
        results = native.decay_ops.calculate_batch([], decay_config)
        assert results == []


@pytest.mark.skipif(not HAS_NATIVE, reason="Native module not available")
class TestModuleInfo:
    """Test module information functions."""

    def test_has_avx2_returns_bool(self):
        """Test has_avx2 returns a boolean."""
        result = native.has_avx2()
        assert isinstance(result, bool)

    def test_has_neon_returns_bool(self):
        """Test has_neon returns a boolean."""
        result = native.has_neon()
        assert isinstance(result, bool)

    def test_version_exists(self):
        """Test that version attribute exists."""
        assert hasattr(native, "__version__")
        assert native.__version__ == "0.1.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
