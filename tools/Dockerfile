FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates cmake ninja-build clang-18 llvm-18-dev libclang-18-dev \
    libclang-cpp18-dev libclang-rt-18-dev gcc g++ python3 z3 && rm -rf /var/lib/apt/lists/*
ENV CC=clang-18 CXX=clang++-18 CSRD_TEST_COMPILERS=clang-18:gcc CSRD_REQUIRE_BOTH_COMPILERS=1
WORKDIR /work
