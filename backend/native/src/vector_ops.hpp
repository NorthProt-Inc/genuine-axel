#pragma once

#include <vector>
#include <tuple>
#include <cstdint>

namespace axnmihn {
namespace vector_ops {

/**
 * Calculate cosine similarity between two vectors.
 *
 * Args:
 *     a: First vector
 *     b: Second vector
 *
 * Returns:
 *     Cosine similarity (-1 to 1)
 */
double cosine_similarity(const std::vector<double>& a, const std::vector<double>& b);

/**
 * Calculate cosine similarity between a query and a corpus of vectors.
 * Uses SIMD optimizations when available.
 *
 * Args:
 *     query: Query vector
 *     corpus: Matrix of vectors (row-major, n_vectors x dim)
 *     n_vectors: Number of vectors in corpus
 *     dim: Dimension of each vector
 *
 * Returns:
 *     Vector of cosine similarities
 */
std::vector<double> cosine_similarity_batch(
    const std::vector<double>& query,
    const double* corpus,
    size_t n_vectors,
    size_t dim
);

/**
 * Find duplicate pairs by embedding similarity.
 *
 * Args:
 *     embeddings: Matrix of embeddings (row-major, n x dim)
 *     n: Number of embeddings
 *     dim: Dimension of each embedding
 *     threshold: Similarity threshold for duplicates
 *
 * Returns:
 *     Vector of (i, j, similarity) tuples for duplicates
 */
std::vector<std::tuple<size_t, size_t, double>> find_duplicates_by_embedding(
    const double* embeddings,
    size_t n,
    size_t dim,
    double threshold
);

}  // namespace vector_ops
}  // namespace axnmihn
