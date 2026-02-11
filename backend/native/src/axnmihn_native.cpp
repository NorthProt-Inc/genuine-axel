#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/numpy.h>

#include "decay.hpp"
#include "vector_ops.hpp"
#include "graph_ops.hpp"
#include "string_ops.hpp"
#include "text_ops.hpp"

namespace py = pybind11;

// Helper to convert numpy array to raw pointer
template<typename T>
const T* get_array_ptr(py::array_t<T>& arr) {
    return arr.data();
}

PYBIND11_MODULE(axnmihn_native, m) {
    m.doc() = "C++ native optimizations for axnmihn";

    // ====================
    // Decay Operations
    // ====================
    py::module decay_m = m.def_submodule("decay_ops", "Memory decay calculations");

    py::class_<axnmihn::decay::DecayConfig>(decay_m, "DecayConfig")
        .def(py::init<>())
        .def_readwrite("base_decay_rate", &axnmihn::decay::DecayConfig::base_decay_rate)
        .def_readwrite("min_retention", &axnmihn::decay::DecayConfig::min_retention)
        .def_readwrite("access_stability_k", &axnmihn::decay::DecayConfig::access_stability_k)
        .def_readwrite("relation_resistance_k", &axnmihn::decay::DecayConfig::relation_resistance_k)
        .def_readwrite("channel_diversity_k", &axnmihn::decay::DecayConfig::channel_diversity_k)
        .def("set_type_multipliers", [](axnmihn::decay::DecayConfig& self,
                                        double conv, double fact, double pref, double insight) {
            self.type_multipliers[0] = conv;
            self.type_multipliers[1] = fact;
            self.type_multipliers[2] = pref;
            self.type_multipliers[3] = insight;
        });

    py::class_<axnmihn::decay::DecayInput>(decay_m, "DecayInput")
        .def(py::init<>())
        .def(py::init([](double importance, double hours_passed, int access_count,
                        int connection_count, double last_access_hours, int memory_type,
                        int channel_mentions) {
            return axnmihn::decay::DecayInput{
                importance, hours_passed, access_count,
                connection_count, last_access_hours, memory_type, channel_mentions
            };
        }), py::arg("importance"), py::arg("hours_passed"),
           py::arg("access_count") = 0, py::arg("connection_count") = 0,
           py::arg("last_access_hours") = -1.0, py::arg("memory_type") = 0,
           py::arg("channel_mentions") = 0)
        .def_readwrite("importance", &axnmihn::decay::DecayInput::importance)
        .def_readwrite("hours_passed", &axnmihn::decay::DecayInput::hours_passed)
        .def_readwrite("access_count", &axnmihn::decay::DecayInput::access_count)
        .def_readwrite("connection_count", &axnmihn::decay::DecayInput::connection_count)
        .def_readwrite("last_access_hours", &axnmihn::decay::DecayInput::last_access_hours)
        .def_readwrite("memory_type", &axnmihn::decay::DecayInput::memory_type)
        .def_readwrite("channel_mentions", &axnmihn::decay::DecayInput::channel_mentions);

    decay_m.def("calculate", &axnmihn::decay::calculate,
        "Calculate decayed importance for a single memory",
        py::arg("input"), py::arg("config"));

    decay_m.def("calculate_batch", &axnmihn::decay::calculate_batch,
        "Calculate decayed importance for a batch of memories",
        py::arg("inputs"), py::arg("config"));

    // NumPy array version for maximum efficiency
    decay_m.def("calculate_batch_numpy",
        [](py::array_t<double> importance,
           py::array_t<double> hours_passed,
           py::array_t<int> access_count,
           py::array_t<int> connection_count,
           py::array_t<double> last_access_hours,
           py::array_t<int> memory_type,
           py::array_t<int> channel_mentions,
           const axnmihn::decay::DecayConfig& config) {

            auto imp = importance.unchecked<1>();
            auto hrs = hours_passed.unchecked<1>();
            auto acc = access_count.unchecked<1>();
            auto conn = connection_count.unchecked<1>();
            auto last = last_access_hours.unchecked<1>();
            auto mtype = memory_type.unchecked<1>();
            auto chmnt = channel_mentions.unchecked<1>();

            size_t n = imp.size();

            // Create output array
            py::array_t<double> result(n);
            auto output = result.mutable_unchecked<1>();

            axnmihn::decay::calculate_batch_arrays(
                n,
                imp.data(0),
                hrs.data(0),
                acc.data(0),
                conn.data(0),
                last.data(0),
                mtype.data(0),
                chmnt.data(0),
                config,
                output.mutable_data(0)
            );

            return result;
        },
        "Calculate decayed importance for a batch using NumPy arrays",
        py::arg("importance"),
        py::arg("hours_passed"),
        py::arg("access_count"),
        py::arg("connection_count"),
        py::arg("last_access_hours"),
        py::arg("memory_type"),
        py::arg("channel_mentions"),
        py::arg("config"));

    // ====================
    // Vector Operations
    // ====================
    py::module vector_m = m.def_submodule("vector_ops", "Vector similarity calculations");

    vector_m.def("cosine_similarity", &axnmihn::vector_ops::cosine_similarity,
        "Calculate cosine similarity between two vectors",
        py::arg("a"), py::arg("b"));

    vector_m.def("cosine_similarity_batch",
        [](py::array_t<double> query, py::array_t<double, py::array::c_style | py::array::forcecast> corpus) {
            auto q = query.unchecked<1>();
            auto c = corpus.unchecked<2>();

            size_t n_vectors = c.shape(0);
            size_t dim = c.shape(1);

            std::vector<double> query_vec(q.data(0), q.data(0) + q.size());

            return axnmihn::vector_ops::cosine_similarity_batch(
                query_vec, c.data(0, 0), n_vectors, dim);
        },
        "Calculate cosine similarity between query and corpus",
        py::arg("query"), py::arg("corpus"));

    vector_m.def("find_duplicates_by_embedding",
        [](py::array_t<double, py::array::c_style | py::array::forcecast> embeddings, double threshold) {
            auto e = embeddings.unchecked<2>();
            size_t n = e.shape(0);
            size_t dim = e.shape(1);

            auto result = axnmihn::vector_ops::find_duplicates_by_embedding(
                e.data(0, 0), n, dim, threshold);

            // Convert to Python list of tuples
            py::list output;
            for (const auto& [i, j, sim] : result) {
                output.append(py::make_tuple(i, j, sim));
            }
            return output;
        },
        "Find duplicate pairs by embedding similarity",
        py::arg("embeddings"), py::arg("threshold"));

    // ====================
    // Graph Operations
    // ====================
    py::module graph_m = m.def_submodule("graph_ops", "Graph traversal operations");

    graph_m.def("bfs_neighbors",
        [](py::dict adjacency, py::list start_nodes, int max_depth) {
            // Convert Python dict to C++ map
            std::unordered_map<size_t, std::vector<size_t>> adj_map;
            for (auto item : adjacency) {
                size_t key = item.first.cast<size_t>();
                py::list neighbors = item.second.cast<py::list>();

                std::vector<size_t> neighbor_vec;
                for (auto n : neighbors) {
                    neighbor_vec.push_back(n.cast<size_t>());
                }
                adj_map[key] = neighbor_vec;
            }

            // Convert start nodes
            std::vector<size_t> starts;
            for (auto n : start_nodes) {
                starts.push_back(n.cast<size_t>());
            }

            auto result = axnmihn::graph_ops::bfs_neighbors(adj_map, starts, max_depth);

            // Convert to Python set
            py::set output;
            for (size_t node : result) {
                output.add(py::int_(node));
            }
            return output;
        },
        "Find all neighbors within max_depth using BFS",
        py::arg("adjacency"), py::arg("start_nodes"), py::arg("max_depth"));

    graph_m.def("find_connected_components",
        [](py::dict adjacency, size_t n_nodes) {
            std::unordered_map<size_t, std::vector<size_t>> adj_map;
            for (auto item : adjacency) {
                size_t key = item.first.cast<size_t>();
                py::list neighbors = item.second.cast<py::list>();

                std::vector<size_t> neighbor_vec;
                for (auto n : neighbors) {
                    neighbor_vec.push_back(n.cast<size_t>());
                }
                adj_map[key] = neighbor_vec;
            }

            return axnmihn::graph_ops::find_connected_components(adj_map, n_nodes);
        },
        "Find connected components in graph",
        py::arg("adjacency"), py::arg("n_nodes"));

    // ====================
    // String Operations
    // ====================
    py::module string_m = m.def_submodule("string_ops", "String similarity operations");

    string_m.def("levenshtein_distance", &axnmihn::string_ops::levenshtein_distance,
        "Calculate Levenshtein (edit) distance between two strings",
        py::arg("a"), py::arg("b"));

    string_m.def("string_similarity", &axnmihn::string_ops::string_similarity,
        "Calculate normalized string similarity (0-1)",
        py::arg("a"), py::arg("b"));

    string_m.def("find_string_duplicates", &axnmihn::string_ops::find_string_duplicates,
        "Find duplicate string pairs by similarity",
        py::arg("strings"), py::arg("threshold"));

    string_m.def("string_similarity_batch", &axnmihn::string_ops::string_similarity_batch,
        "Batch calculate string similarities",
        py::arg("query"), py::arg("targets"));

    // ====================
    // Text Operations
    // ====================
    py::module text_m = m.def_submodule("text_ops", "Korean text processing operations");

    text_m.def("fix_korean_spacing", &axnmihn::text_ops::fix_korean_spacing,
        "Fix Korean spacing around punctuation and bracket boundaries",
        py::arg("text"));

    text_m.def("fix_korean_spacing_batch", &axnmihn::text_ops::fix_korean_spacing_batch,
        "Batch fix Korean spacing",
        py::arg("texts"));

    // ====================
    // Module Info
    // ====================
    m.def("has_avx2", []() {
        #ifdef HAS_AVX2
        return true;
        #else
        return false;
        #endif
    }, "Check if AVX2 SIMD is available");

    m.def("has_neon", []() {
        #ifdef HAS_NEON
        return true;
        #else
        return false;
        #endif
    }, "Check if ARM NEON SIMD is available");

    m.attr("__version__") = "0.1.0";
}
