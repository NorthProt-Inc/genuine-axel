#pragma once

#include <vector>
#include <cstdint>

namespace axnmihn {
namespace decay {

/**
 * Input parameters for decay calculation.
 */
struct DecayInput {
    double importance;       // Original importance (0-1)
    double hours_passed;     // Age in hours since creation
    int access_count;        // Number of times accessed
    int connection_count;    // Number of graph connections
    double last_access_hours;// Hours since last access (-1 if never)
    int memory_type;         // 0=conversation, 1=fact, 2=preference, 3=insight
};

/**
 * Configuration for decay calculation.
 */
struct DecayConfig {
    double base_decay_rate = 0.002;
    double min_retention = 0.1;
    double access_stability_k = 0.3;
    double relation_resistance_k = 0.1;

    // Memory type decay multipliers
    double type_multipliers[4] = {1.0, 0.3, 0.5, 0.7};  // conv, fact, pref, insight
};

/**
 * Calculate decayed importance for a single memory.
 *
 * Args:
 *     input: Decay calculation parameters
 *     config: Decay configuration
 *
 * Returns:
 *     Decayed importance score
 */
double calculate(const DecayInput& input, const DecayConfig& config);

/**
 * Calculate decayed importance for a batch of memories.
 * Uses SIMD optimizations when available.
 *
 * Args:
 *     inputs: Vector of decay calculation parameters
 *     config: Decay configuration
 *
 * Returns:
 *     Vector of decayed importance scores
 */
std::vector<double> calculate_batch(
    const std::vector<DecayInput>& inputs,
    const DecayConfig& config
);

/**
 * Calculate decayed importance for a batch using raw arrays.
 * More efficient for large batches from Python/NumPy.
 *
 * Args:
 *     n: Number of elements
 *     importance: Array of importance values
 *     hours_passed: Array of age in hours
 *     access_count: Array of access counts
 *     connection_count: Array of connection counts
 *     last_access_hours: Array of hours since last access (-1 if never)
 *     memory_type: Array of memory types (0-3)
 *     config: Decay configuration
 *     output: Output array for decayed importance scores
 */
void calculate_batch_arrays(
    size_t n,
    const double* importance,
    const double* hours_passed,
    const int* access_count,
    const int* connection_count,
    const double* last_access_hours,
    const int* memory_type,
    const DecayConfig& config,
    double* output
);

}  // namespace decay
}  // namespace axnmihn
