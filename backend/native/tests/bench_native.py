#!/usr/bin/env python3
"""Benchmarks for native module performance."""

import math
import time
import sys
from pathlib import Path

import numpy as np

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    import axnmihn_native as native
    HAS_NATIVE = True
    print(f"Native module loaded (AVX2: {native.has_avx2()}, NEON: {native.has_neon()})")
except ImportError as e:
    print(f"Native module not available: {e}")
    HAS_NATIVE = False


def python_decay_calculate(
    importance: float,
    hours_passed: float,
    access_count: int = 0,
    connection_count: int = 0,
    last_access_hours: float = -1.0,
    memory_type: int = 0,
) -> float:
    """Pure Python decay calculation."""
    type_multipliers = [1.0, 0.3, 0.5, 0.7]
    base_decay_rate = 0.002
    min_retention = 0.1
    access_stability_k = 0.3
    relation_resistance_k = 0.1

    if hours_passed < 0:
        return importance

    stability = 1.0 + access_stability_k * math.log(1 + access_count)
    resistance = min(1.0, connection_count * relation_resistance_k)
    type_mult = type_multipliers[memory_type]

    effective_rate = base_decay_rate * type_mult / stability * (1.0 - resistance)
    decayed = importance * math.exp(-effective_rate * hours_passed)

    if last_access_hours >= 0 and hours_passed > 168.0 and last_access_hours < 24.0:
        decayed *= 1.3

    return max(decayed, importance * min_retention)


def python_cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Pure Python cosine similarity."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm < 1e-10:
        return 0.0
    return dot / norm


def benchmark_decay_single(n_iterations: int = 10000):
    """Benchmark single decay calculation."""
    print(f"\n=== Decay Single Calculation ({n_iterations} iterations) ===")

    # Python benchmark
    start = time.perf_counter()
    for _ in range(n_iterations):
        python_decay_calculate(0.8, 500.0, 10, 5, 20.0, 1)
    python_time = time.perf_counter() - start
    print(f"Python: {python_time*1000:.2f}ms ({n_iterations/python_time:.0f} ops/sec)")

    if HAS_NATIVE:
        config = native.decay_ops.DecayConfig()
        config.set_type_multipliers(1.0, 0.3, 0.5, 0.7)

        inp = native.decay_ops.DecayInput(0.8, 500.0, 10, 5, 20.0, 1)

        start = time.perf_counter()
        for _ in range(n_iterations):
            native.decay_ops.calculate(inp, config)
        native_time = time.perf_counter() - start
        print(f"Native: {native_time*1000:.2f}ms ({n_iterations/native_time:.0f} ops/sec)")
        print(f"Speedup: {python_time/native_time:.1f}x")


def benchmark_decay_batch(batch_sizes: list = [100, 1000, 5000, 10000]):
    """Benchmark batch decay calculation."""
    print("\n=== Decay Batch Calculation ===")

    for batch_size in batch_sizes:
        np.random.seed(42)
        importance = np.random.uniform(0.1, 1.0, batch_size)
        hours_passed = np.random.uniform(0, 1000, batch_size)
        access_count = np.random.randint(0, 50, batch_size)
        connection_count = np.random.randint(0, 10, batch_size)
        last_access_hours = np.random.uniform(-1, 100, batch_size)
        memory_type = np.random.randint(0, 4, batch_size)

        # Python benchmark
        start = time.perf_counter()
        for i in range(batch_size):
            python_decay_calculate(
                importance[i], hours_passed[i], access_count[i],
                connection_count[i], last_access_hours[i], memory_type[i]
            )
        python_time = time.perf_counter() - start

        print(f"\nBatch size: {batch_size}")
        print(f"  Python: {python_time*1000:.2f}ms")

        if HAS_NATIVE:
            config = native.decay_ops.DecayConfig()
            config.set_type_multipliers(1.0, 0.3, 0.5, 0.7)

            # Convert to proper dtypes
            imp_arr = importance.astype(np.float64)
            hrs_arr = hours_passed.astype(np.float64)
            acc_arr = access_count.astype(np.int32)
            conn_arr = connection_count.astype(np.int32)
            last_arr = last_access_hours.astype(np.float64)
            type_arr = memory_type.astype(np.int32)

            start = time.perf_counter()
            native.decay_ops.calculate_batch_numpy(
                imp_arr, hrs_arr, acc_arr, conn_arr, last_arr, type_arr, config
            )
            native_time = time.perf_counter() - start

            print(f"  Native: {native_time*1000:.2f}ms")
            print(f"  Speedup: {python_time/native_time:.1f}x")


def benchmark_cosine_similarity(dim: int = 768, n_vectors: int = 1000):
    """Benchmark cosine similarity batch calculation."""
    print(f"\n=== Cosine Similarity Batch (dim={dim}, n={n_vectors}) ===")

    np.random.seed(42)
    query = np.random.randn(dim).astype(np.float64)
    corpus = np.random.randn(n_vectors, dim).astype(np.float64)

    # Python (numpy) benchmark
    start = time.perf_counter()
    for i in range(n_vectors):
        python_cosine_similarity(query, corpus[i])
    python_time = time.perf_counter() - start
    print(f"Python (numpy): {python_time*1000:.2f}ms")

    if HAS_NATIVE:
        start = time.perf_counter()
        native.vector_ops.cosine_similarity_batch(query, corpus)
        native_time = time.perf_counter() - start
        print(f"Native: {native_time*1000:.2f}ms")
        print(f"Speedup: {python_time/native_time:.1f}x")


def benchmark_find_duplicates(n_embeddings: int = 500, dim: int = 768):
    """Benchmark duplicate finding."""
    print(f"\n=== Find Duplicates (n={n_embeddings}, dim={dim}) ===")

    np.random.seed(42)
    embeddings = np.random.randn(n_embeddings, dim).astype(np.float64)

    # Python O(N^2) benchmark
    start = time.perf_counter()
    threshold = 0.9
    duplicates = []
    for i in range(n_embeddings):
        for j in range(i + 1, n_embeddings):
            sim = python_cosine_similarity(embeddings[i], embeddings[j])
            if sim >= threshold:
                duplicates.append((i, j, sim))
    python_time = time.perf_counter() - start
    print(f"Python: {python_time*1000:.2f}ms (found {len(duplicates)} duplicates)")

    if HAS_NATIVE:
        start = time.perf_counter()
        native_dups = native.vector_ops.find_duplicates_by_embedding(embeddings, threshold)
        native_time = time.perf_counter() - start
        print(f"Native: {native_time*1000:.2f}ms (found {len(native_dups)} duplicates)")
        print(f"Speedup: {python_time/native_time:.1f}x")


def benchmark_string_similarity(n_strings: int = 100):
    """Benchmark string similarity operations."""
    print(f"\n=== String Similarity ({n_strings} strings) ===")

    import difflib

    # Generate random strings
    np.random.seed(42)
    strings = [
        ''.join(np.random.choice(list('abcdefghij'), 50))
        for _ in range(n_strings)
    ]

    # Python (difflib) benchmark
    start = time.perf_counter()
    threshold = 0.8
    duplicates = []
    for i in range(n_strings):
        for j in range(i + 1, n_strings):
            sim = difflib.SequenceMatcher(None, strings[i], strings[j]).ratio()
            if sim >= threshold:
                duplicates.append((i, j, sim))
    python_time = time.perf_counter() - start
    print(f"Python (difflib): {python_time*1000:.2f}ms (found {len(duplicates)} duplicates)")

    if HAS_NATIVE:
        start = time.perf_counter()
        native_dups = native.string_ops.find_string_duplicates(strings, threshold)
        native_time = time.perf_counter() - start
        print(f"Native: {native_time*1000:.2f}ms (found {len(native_dups)} duplicates)")
        print(f"Speedup: {python_time/native_time:.1f}x")


def main():
    """Run all benchmarks."""
    print("=" * 60)
    print("axnmihn_native Performance Benchmarks")
    print("=" * 60)

    benchmark_decay_single()
    benchmark_decay_batch()
    benchmark_cosine_similarity()
    benchmark_find_duplicates()
    benchmark_string_similarity()

    print("\n" + "=" * 60)
    print("Benchmarks complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
