cmake_minimum_required(VERSION 3.18)
project(axnmihn_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Optimization flags
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG")

# Architecture-specific SIMD flags
include(CheckCXXCompilerFlag)

# Check for AVX2 support (x86_64)
check_cxx_compiler_flag("-mavx2" COMPILER_SUPPORTS_AVX2)
if(COMPILER_SUPPORTS_AVX2)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -mavx2 -mfma")
    add_compile_definitions(HAS_AVX2)
endif()

# Check for NEON support (ARM)
check_cxx_compiler_flag("-march=armv8-a+simd" COMPILER_SUPPORTS_NEON)
if(COMPILER_SUPPORTS_NEON AND NOT COMPILER_SUPPORTS_AVX2)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -march=armv8-a+simd")
    add_compile_definitions(HAS_NEON)
endif()

# Find pybind11
find_package(pybind11 CONFIG REQUIRED)

# Source files
set(SOURCES
    src/axnmihn_native.cpp
    src/decay.cpp
    src/vector_ops.cpp
    src/graph_ops.cpp
    src/string_ops.cpp
)

# Create the Python module
pybind11_add_module(axnmihn_native ${SOURCES})

# Include directories
target_include_directories(axnmihn_native PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

# Link libraries (math for exp, log, etc.)
target_link_libraries(axnmihn_native PRIVATE)

# Install target
install(TARGETS axnmihn_native LIBRARY DESTINATION .)
