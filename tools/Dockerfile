FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    cmake ninja-build clang-18 llvm-18-dev libclang-18-dev libclang-cpp18-dev \
    libclang-rt-18-dev lld-18 gcc g++ python3 z3 libz3-dev gdb \
    && rm -rf /var/lib/apt/lists/*
ENV CC=clang-18 CXX=clang++-18 CSRD_TEST_COMPILERS=clang-18:gcc CSRD_REQUIRE_BOTH_COMPILERS=1
WORKDIR /work
