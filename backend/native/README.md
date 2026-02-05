# axnmihn-native

C++ native optimizations for axnmihn memory system.

## Features

- **Decay Operations**: SIMD-optimized memory decay calculations
- **Vector Operations**: Fast cosine similarity with AVX2/NEON
- **Graph Operations**: Efficient BFS traversal
- **String Operations**: Fast Levenshtein distance

## Building

### Requirements

- CMake >= 3.18
- C++17 compiler (GCC 8+, Clang 10+)
- pybind11 >= 2.11
- Python >= 3.10

### Install

```bash
cd backend/native
pip install .
```

### Development Install

```bash
pip install -e ".[dev]"
```

## Usage

```python
import axnmihn_native as native

# Check SIMD support
print(f"AVX2: {native.has_avx2()}, NEON: {native.has_neon()}")

# Decay calculation
config = native.decay_ops.DecayConfig()
inp = native.decay_ops.DecayInput(
    importance=0.8,
    hours_passed=100.0,
    access_count=5,
)
result = native.decay_ops.calculate(inp, config)

# Batch with NumPy
import numpy as np
importance = np.array([0.5, 0.8, 0.9], dtype=np.float64)
hours = np.array([100.0, 200.0, 50.0], dtype=np.float64)
# ... other arrays ...
results = native.decay_ops.calculate_batch_numpy(
    importance, hours, access, conn, last, types, config
)

# Vector operations
sim = native.vector_ops.cosine_similarity([1, 2, 3], [1, 2, 4])
batch_sims = native.vector_ops.cosine_similarity_batch(query, corpus)

# String operations
dist = native.string_ops.levenshtein_distance("hello", "hallo")
sim = native.string_ops.string_similarity("hello", "hallo")
```

## Testing

```bash
pytest backend/native/tests/ -v
```

## Benchmarking

```bash
python backend/native/tests/bench_native.py
```

## Performance

Typical speedups over pure Python:

| Operation | Speedup |
|-----------|---------|
| Decay (single) | 20-50x |
| Decay (batch) | 50-100x |
| Cosine similarity | 100-200x |
| String similarity | 20-40x |
