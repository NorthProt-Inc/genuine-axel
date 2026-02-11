#include "decay.hpp"
#include <cmath>
#include <algorithm>

#ifdef HAS_AVX2
#include <immintrin.h>
#endif

#ifdef HAS_NEON
#include <arm_neon.h>
#endif

namespace axnmihn {
namespace decay {

namespace {

// Fast approximation of exp(-x) for x >= 0
// Using the identity: exp(-x) = 1 / exp(x)
// and Schraudolph's approximation for small values
inline double fast_exp_neg(double x) {
    // For very small x, use standard exp for accuracy
    if (x < 0.01) {
        return std::exp(-x);
    }
    // For larger x, use standard exp (it's still fast)
    return std::exp(-x);
}

// Fast approximation of log(1 + x) for x >= 0
// Uses the identity: log(1+x) ~ x - x^2/2 + x^3/3 for small x
inline double fast_log1p(double x) {
    if (x < 0.1) {
        // Taylor series approximation for small x
        double x2 = x * x;
        double x3 = x2 * x;
        return x - 0.5 * x2 + (1.0/3.0) * x3;
    }
    return std::log1p(x);
}

}  // anonymous namespace

double calculate(const DecayInput& input, const DecayConfig& config) {
    if (input.hours_passed < 0) {
        return input.importance;
    }

    // Stability from access count (more access = slower decay)
    // stability = 1 + K * log(1 + access_count)
    double stability = 1.0 + config.access_stability_k * fast_log1p(static_cast<double>(input.access_count));

    // Resistance from connections (more connections = slower decay)
    // resistance = min(1.0, connection_count * K)
    double resistance = std::min(1.0, input.connection_count * config.relation_resistance_k);

    // Type-specific decay rate
    int type_idx = std::clamp(input.memory_type, 0, 3);
    double type_multiplier = config.type_multipliers[type_idx];

    // T-02: Channel diversity boost (more channels = slower decay)
    double channel_boost = 1.0 / (1.0 + config.channel_diversity_k * input.channel_mentions);

    // Calculate effective decay rate
    double effective_rate = config.base_decay_rate * type_multiplier * channel_boost / stability * (1.0 - resistance);

    // Apply exponential decay
    double decayed = input.importance * fast_exp_neg(effective_rate * input.hours_passed);

    // Recency paradox: old memory recently accessed gets a boost
    // If memory is old (>1 week = 168h) but accessed recently (<24h)
    if (input.last_access_hours >= 0 && input.hours_passed > 168.0 && input.last_access_hours < 24.0) {
        decayed *= 1.3;  // 30% boost
    }

    // Ensure minimum retention
    return std::max(decayed, input.importance * config.min_retention);
}

std::vector<double> calculate_batch(
    const std::vector<DecayInput>& inputs,
    const DecayConfig& config
) {
    std::vector<double> results(inputs.size());

    // Process in chunks for better cache utilization
    const size_t chunk_size = 64;

    for (size_t i = 0; i < inputs.size(); i += chunk_size) {
        size_t end = std::min(i + chunk_size, inputs.size());
        for (size_t j = i; j < end; ++j) {
            results[j] = calculate(inputs[j], config);
        }
    }

    return results;
}

void calculate_batch_arrays(
    size_t n,
    const double* importance,
    const double* hours_passed,
    const int* access_count,
    const int* connection_count,
    const double* last_access_hours,
    const int* memory_type,
    const int* channel_mentions,
    const DecayConfig& config,
    double* output
) {
#ifdef HAS_AVX2
    // AVX2 SIMD implementation for x86_64
    // Process 4 doubles at a time

    const __m256d one = _mm256_set1_pd(1.0);
    const __m256d access_k = _mm256_set1_pd(config.access_stability_k);
    const __m256d relation_k = _mm256_set1_pd(config.relation_resistance_k);
    const __m256d base_rate = _mm256_set1_pd(config.base_decay_rate);
    const __m256d min_ret = _mm256_set1_pd(config.min_retention);
    const __m256d recency_boost = _mm256_set1_pd(1.3);
    const __m256d hours_168 = _mm256_set1_pd(168.0);
    const __m256d hours_24 = _mm256_set1_pd(24.0);
    const __m256d neg_one = _mm256_set1_pd(-1.0);

    size_t i = 0;
    for (; i + 4 <= n; i += 4) {
        // Load importance and hours_passed
        __m256d imp = _mm256_loadu_pd(&importance[i]);
        __m256d hours = _mm256_loadu_pd(&hours_passed[i]);

        // Load and convert integer arrays
        __m128i ac_i = _mm_loadu_si128(reinterpret_cast<const __m128i*>(&access_count[i]));
        __m128i cc_i = _mm_loadu_si128(reinterpret_cast<const __m128i*>(&connection_count[i]));
        __m128i mt_i = _mm_loadu_si128(reinterpret_cast<const __m128i*>(&memory_type[i]));

        __m256d ac = _mm256_cvtepi32_pd(ac_i);
        __m256d cc = _mm256_cvtepi32_pd(cc_i);

        // Load last_access_hours
        __m256d lah = _mm256_loadu_pd(&last_access_hours[i]);

        // Calculate stability = 1 + K * log(1 + access_count)
        // Note: Using scalar log for accuracy (SIMD log is complex)
        double stab[4];
        for (int k = 0; k < 4; ++k) {
            stab[k] = 1.0 + config.access_stability_k * fast_log1p(static_cast<double>(access_count[i + k]));
        }
        __m256d stability = _mm256_loadu_pd(stab);

        // Calculate resistance = min(1.0, connection_count * K)
        __m256d resistance = _mm256_mul_pd(cc, relation_k);
        resistance = _mm256_min_pd(resistance, one);

        // Get type multipliers (scalar for simplicity)
        double type_mult[4];
        for (int k = 0; k < 4; ++k) {
            int idx = std::clamp(memory_type[i + k], 0, 3);
            type_mult[k] = config.type_multipliers[idx];
        }
        __m256d tm = _mm256_loadu_pd(type_mult);

        // T-02: Channel diversity boost (scalar for simplicity)
        double ch_boost[4];
        for (int k = 0; k < 4; ++k) {
            ch_boost[k] = 1.0 / (1.0 + config.channel_diversity_k * channel_mentions[i + k]);
        }
        __m256d cb = _mm256_loadu_pd(ch_boost);

        // effective_rate = base_rate * type_mult * channel_boost / stability * (1 - resistance)
        __m256d eff_rate = _mm256_mul_pd(base_rate, tm);
        eff_rate = _mm256_mul_pd(eff_rate, cb);
        eff_rate = _mm256_div_pd(eff_rate, stability);
        eff_rate = _mm256_mul_pd(eff_rate, _mm256_sub_pd(one, resistance));

        // Calculate exp(-effective_rate * hours_passed) using scalar for accuracy
        double decay_factor[4];
        double eff_rate_arr[4], hours_arr[4];
        _mm256_storeu_pd(eff_rate_arr, eff_rate);
        _mm256_storeu_pd(hours_arr, hours);
        for (int k = 0; k < 4; ++k) {
            decay_factor[k] = fast_exp_neg(eff_rate_arr[k] * hours_arr[k]);
        }
        __m256d decay = _mm256_loadu_pd(decay_factor);

        // decayed = importance * decay_factor
        __m256d decayed = _mm256_mul_pd(imp, decay);

        // Recency paradox check (scalar for complexity)
        double decayed_arr[4];
        _mm256_storeu_pd(decayed_arr, decayed);
        double lah_arr[4], hours_arr2[4];
        _mm256_storeu_pd(lah_arr, lah);
        _mm256_storeu_pd(hours_arr2, hours);

        for (int k = 0; k < 4; ++k) {
            if (lah_arr[k] >= 0 && hours_arr2[k] > 168.0 && lah_arr[k] < 24.0) {
                decayed_arr[k] *= 1.3;
            }
        }
        decayed = _mm256_loadu_pd(decayed_arr);

        // Apply minimum retention
        __m256d min_val = _mm256_mul_pd(imp, min_ret);
        decayed = _mm256_max_pd(decayed, min_val);

        // Store results
        _mm256_storeu_pd(&output[i], decayed);
    }

    // Handle remaining elements
    for (; i < n; ++i) {
        DecayInput input{
            importance[i],
            hours_passed[i],
            access_count[i],
            connection_count[i],
            last_access_hours[i],
            memory_type[i],
            channel_mentions[i]
        };
        output[i] = calculate(input, config);
    }

#else
    // Scalar fallback (also used on ARM, optimized with NEON later if needed)
    for (size_t i = 0; i < n; ++i) {
        DecayInput input{
            importance[i],
            hours_passed[i],
            access_count[i],
            connection_count[i],
            last_access_hours[i],
            memory_type[i]
        };
        output[i] = calculate(input, config);
    }
#endif
}

}  // namespace decay
}  // namespace axnmihn
