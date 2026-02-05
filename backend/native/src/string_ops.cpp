#include "string_ops.hpp"
#include <algorithm>
#include <cmath>

namespace axnmihn {
namespace string_ops {

int levenshtein_distance(const std::string& a, const std::string& b) {
    size_t m = a.size();
    size_t n = b.size();

    if (m == 0) return static_cast<int>(n);
    if (n == 0) return static_cast<int>(m);

    // Use only two rows for space efficiency
    std::vector<int> prev(n + 1);
    std::vector<int> curr(n + 1);

    // Initialize first row
    for (size_t j = 0; j <= n; ++j) {
        prev[j] = static_cast<int>(j);
    }

    for (size_t i = 1; i <= m; ++i) {
        curr[0] = static_cast<int>(i);

        for (size_t j = 1; j <= n; ++j) {
            int cost = (a[i - 1] == b[j - 1]) ? 0 : 1;

            curr[j] = std::min({
                prev[j] + 1,          // deletion
                curr[j - 1] + 1,      // insertion
                prev[j - 1] + cost    // substitution
            });
        }

        std::swap(prev, curr);
    }

    return prev[n];
}

double string_similarity(const std::string& a, const std::string& b) {
    if (a.empty() && b.empty()) {
        return 1.0;
    }

    size_t max_len = std::max(a.size(), b.size());
    if (max_len == 0) {
        return 1.0;
    }

    int dist = levenshtein_distance(a, b);
    return 1.0 - static_cast<double>(dist) / static_cast<double>(max_len);
}

std::vector<std::tuple<size_t, size_t, double>> find_string_duplicates(
    const std::vector<std::string>& strings,
    double threshold
) {
    std::vector<std::tuple<size_t, size_t, double>> duplicates;
    size_t n = strings.size();

    // O(N^2) pairwise comparison with early termination optimization
    for (size_t i = 0; i < n; ++i) {
        const std::string& a = strings[i];
        size_t len_a = a.size();

        for (size_t j = i + 1; j < n; ++j) {
            const std::string& b = strings[j];
            size_t len_b = b.size();

            // Early termination: if length difference is too large,
            // similarity cannot exceed threshold
            size_t max_len = std::max(len_a, len_b);
            size_t min_len = std::min(len_a, len_b);

            if (max_len > 0) {
                // Best possible similarity (if one is substring of other)
                double best_possible = static_cast<double>(min_len) / static_cast<double>(max_len);
                if (best_possible < threshold) {
                    continue;  // Skip this pair
                }
            }

            double sim = string_similarity(a, b);
            if (sim >= threshold) {
                duplicates.emplace_back(i, j, sim);
            }
        }
    }

    return duplicates;
}

std::vector<double> string_similarity_batch(
    const std::string& query,
    const std::vector<std::string>& targets
) {
    std::vector<double> results(targets.size());

    for (size_t i = 0; i < targets.size(); ++i) {
        results[i] = string_similarity(query, targets[i]);
    }

    return results;
}

}  // namespace string_ops
}  // namespace axnmihn
