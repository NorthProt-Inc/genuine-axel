#pragma once

#include <vector>
#include <string>
#include <tuple>

namespace axnmihn {
namespace string_ops {

/**
 * Calculate Levenshtein (edit) distance between two strings.
 *
 * Args:
 *     a: First string
 *     b: Second string
 *
 * Returns:
 *     Edit distance (number of insertions, deletions, substitutions)
 */
int levenshtein_distance(const std::string& a, const std::string& b);

/**
 * Calculate normalized string similarity (0-1).
 * similarity = 1 - (edit_distance / max(len(a), len(b)))
 *
 * Args:
 *     a: First string
 *     b: Second string
 *
 * Returns:
 *     Similarity score (0-1)
 */
double string_similarity(const std::string& a, const std::string& b);

/**
 * Find duplicate string pairs by similarity.
 *
 * Args:
 *     strings: Vector of strings to compare
 *     threshold: Similarity threshold for duplicates (0-1)
 *
 * Returns:
 *     Vector of (i, j, similarity) tuples for duplicates
 */
std::vector<std::tuple<size_t, size_t, double>> find_string_duplicates(
    const std::vector<std::string>& strings,
    double threshold
);

/**
 * Batch calculate string similarities.
 *
 * Args:
 *     query: Query string
 *     targets: Vector of target strings
 *
 * Returns:
 *     Vector of similarity scores
 */
std::vector<double> string_similarity_batch(
    const std::string& query,
    const std::vector<std::string>& targets
);

}  // namespace string_ops
}  // namespace axnmihn
