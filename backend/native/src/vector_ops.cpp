#include "vector_ops.hpp"
#include <cmath>
#include <algorithm>

#ifdef HAS_AVX2
#include <immintrin.h>
#endif

namespace axnmihn {
namespace vector_ops {

double cosine_similarity(const std::vector<double>& a, const std::vector<double>& b) {
    if (a.size() != b.size() || a.empty()) {
        return 0.0;
    }

    double dot = 0.0, norm_a = 0.0, norm_b = 0.0;

#ifdef HAS_AVX2
    size_t n = a.size();
    size_t i = 0;

    __m256d sum_dot = _mm256_setzero_pd();
    __m256d sum_a = _mm256_setzero_pd();
    __m256d sum_b = _mm256_setzero_pd();

    for (; i + 4 <= n; i += 4) {
        __m256d va = _mm256_loadu_pd(&a[i]);
        __m256d vb = _mm256_loadu_pd(&b[i]);

        sum_dot = _mm256_fmadd_pd(va, vb, sum_dot);
        sum_a = _mm256_fmadd_pd(va, va, sum_a);
        sum_b = _mm256_fmadd_pd(vb, vb, sum_b);
    }

    // Horizontal sum
    double tmp[4];
    _mm256_storeu_pd(tmp, sum_dot);
    dot = tmp[0] + tmp[1] + tmp[2] + tmp[3];

    _mm256_storeu_pd(tmp, sum_a);
    norm_a = tmp[0] + tmp[1] + tmp[2] + tmp[3];

    _mm256_storeu_pd(tmp, sum_b);
    norm_b = tmp[0] + tmp[1] + tmp[2] + tmp[3];

    // Handle remaining elements
    for (; i < n; ++i) {
        dot += a[i] * b[i];
        norm_a += a[i] * a[i];
        norm_b += b[i] * b[i];
    }
#else
    for (size_t i = 0; i < a.size(); ++i) {
        dot += a[i] * b[i];
        norm_a += a[i] * a[i];
        norm_b += b[i] * b[i];
    }
#endif

    double denom = std::sqrt(norm_a) * std::sqrt(norm_b);
    if (denom < 1e-10) {
        return 0.0;
    }
    return dot / denom;
}

std::vector<double> cosine_similarity_batch(
    const std::vector<double>& query,
    const double* corpus,
    size_t n_vectors,
    size_t dim
) {
    std::vector<double> results(n_vectors);

    if (query.size() != dim) {
        return results;
    }

    // Pre-compute query norm
    double query_norm_sq = 0.0;
    for (size_t i = 0; i < dim; ++i) {
        query_norm_sq += query[i] * query[i];
    }
    double query_norm = std::sqrt(query_norm_sq);

    if (query_norm < 1e-10) {
        return results;
    }

    for (size_t v = 0; v < n_vectors; ++v) {
        const double* vec = corpus + v * dim;

        double dot = 0.0;
        double vec_norm_sq = 0.0;

#ifdef HAS_AVX2
        size_t i = 0;
        __m256d sum_dot = _mm256_setzero_pd();
        __m256d sum_norm = _mm256_setzero_pd();

        for (; i + 4 <= dim; i += 4) {
            __m256d vq = _mm256_loadu_pd(&query[i]);
            __m256d vv = _mm256_loadu_pd(&vec[i]);

            sum_dot = _mm256_fmadd_pd(vq, vv, sum_dot);
            sum_norm = _mm256_fmadd_pd(vv, vv, sum_norm);
        }

        double tmp[4];
        _mm256_storeu_pd(tmp, sum_dot);
        dot = tmp[0] + tmp[1] + tmp[2] + tmp[3];

        _mm256_storeu_pd(tmp, sum_norm);
        vec_norm_sq = tmp[0] + tmp[1] + tmp[2] + tmp[3];

        for (; i < dim; ++i) {
            dot += query[i] * vec[i];
            vec_norm_sq += vec[i] * vec[i];
        }
#else
        for (size_t i = 0; i < dim; ++i) {
            dot += query[i] * vec[i];
            vec_norm_sq += vec[i] * vec[i];
        }
#endif

        double vec_norm = std::sqrt(vec_norm_sq);
        if (vec_norm < 1e-10) {
            results[v] = 0.0;
        } else {
            results[v] = dot / (query_norm * vec_norm);
        }
    }

    return results;
}

std::vector<std::tuple<size_t, size_t, double>> find_duplicates_by_embedding(
    const double* embeddings,
    size_t n,
    size_t dim,
    double threshold
) {
    std::vector<std::tuple<size_t, size_t, double>> duplicates;

    // Pre-compute all norms
    std::vector<double> norms(n);
    for (size_t i = 0; i < n; ++i) {
        double norm_sq = 0.0;
        const double* vec = embeddings + i * dim;
        for (size_t d = 0; d < dim; ++d) {
            norm_sq += vec[d] * vec[d];
        }
        norms[i] = std::sqrt(norm_sq);
    }

    // O(N^2) pairwise comparison
    for (size_t i = 0; i < n; ++i) {
        if (norms[i] < 1e-10) continue;

        const double* vec_i = embeddings + i * dim;

        for (size_t j = i + 1; j < n; ++j) {
            if (norms[j] < 1e-10) continue;

            const double* vec_j = embeddings + j * dim;

            double dot = 0.0;
#ifdef HAS_AVX2
            size_t d = 0;
            __m256d sum = _mm256_setzero_pd();

            for (; d + 4 <= dim; d += 4) {
                __m256d vi = _mm256_loadu_pd(&vec_i[d]);
                __m256d vj = _mm256_loadu_pd(&vec_j[d]);
                sum = _mm256_fmadd_pd(vi, vj, sum);
            }

            double tmp[4];
            _mm256_storeu_pd(tmp, sum);
            dot = tmp[0] + tmp[1] + tmp[2] + tmp[3];

            for (; d < dim; ++d) {
                dot += vec_i[d] * vec_j[d];
            }
#else
            for (size_t d = 0; d < dim; ++d) {
                dot += vec_i[d] * vec_j[d];
            }
#endif

            double similarity = dot / (norms[i] * norms[j]);

            if (similarity >= threshold) {
                duplicates.emplace_back(i, j, similarity);
            }
        }
    }

    return duplicates;
}

}  // namespace vector_ops
}  // namespace axnmihn
