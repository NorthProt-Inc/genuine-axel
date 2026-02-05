#pragma once

#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <string>

namespace axnmihn {
namespace graph_ops {

/**
 * Fast BFS for finding neighbors within a given depth.
 *
 * Args:
 *     adjacency: Adjacency list (node_id -> list of neighbor ids)
 *     start_nodes: Starting node IDs
 *     max_depth: Maximum BFS depth
 *
 * Returns:
 *     Set of all reachable node IDs within max_depth
 */
std::unordered_set<size_t> bfs_neighbors(
    const std::unordered_map<size_t, std::vector<size_t>>& adjacency,
    const std::vector<size_t>& start_nodes,
    int max_depth
);

/**
 * Find connected components in an undirected graph.
 *
 * Args:
 *     adjacency: Adjacency list
 *     n_nodes: Total number of nodes
 *
 * Returns:
 *     Vector of component IDs for each node
 */
std::vector<int> find_connected_components(
    const std::unordered_map<size_t, std::vector<size_t>>& adjacency,
    size_t n_nodes
);

}  // namespace graph_ops
}  // namespace axnmihn
