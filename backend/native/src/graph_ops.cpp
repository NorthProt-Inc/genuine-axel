#include "graph_ops.hpp"
#include <queue>

namespace axnmihn {
namespace graph_ops {

std::unordered_set<size_t> bfs_neighbors(
    const std::unordered_map<size_t, std::vector<size_t>>& adjacency,
    const std::vector<size_t>& start_nodes,
    int max_depth
) {
    std::unordered_set<size_t> visited;
    std::queue<std::pair<size_t, int>> frontier;

    // Initialize with start nodes at depth 0
    for (size_t node : start_nodes) {
        if (visited.find(node) == visited.end()) {
            visited.insert(node);
            frontier.push({node, 0});
        }
    }

    while (!frontier.empty()) {
        auto [current, depth] = frontier.front();
        frontier.pop();

        if (depth >= max_depth) {
            continue;
        }

        auto it = adjacency.find(current);
        if (it == adjacency.end()) {
            continue;
        }

        for (size_t neighbor : it->second) {
            if (visited.find(neighbor) == visited.end()) {
                visited.insert(neighbor);
                frontier.push({neighbor, depth + 1});
            }
        }
    }

    return visited;
}

std::vector<int> find_connected_components(
    const std::unordered_map<size_t, std::vector<size_t>>& adjacency,
    size_t n_nodes
) {
    std::vector<int> component_ids(n_nodes, -1);
    int current_component = 0;

    for (size_t node = 0; node < n_nodes; ++node) {
        if (component_ids[node] != -1) {
            continue;
        }

        // BFS from this node
        std::queue<size_t> q;
        q.push(node);
        component_ids[node] = current_component;

        while (!q.empty()) {
            size_t current = q.front();
            q.pop();

            auto it = adjacency.find(current);
            if (it == adjacency.end()) {
                continue;
            }

            for (size_t neighbor : it->second) {
                if (neighbor < n_nodes && component_ids[neighbor] == -1) {
                    component_ids[neighbor] = current_component;
                    q.push(neighbor);
                }
            }
        }

        ++current_component;
    }

    return component_ids;
}

}  // namespace graph_ops
}  // namespace axnmihn
