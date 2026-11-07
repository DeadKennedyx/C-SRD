#pragma once
#include "csrd/ir.hpp"
#include "csrd/representation.hpp"
namespace csrd {
std::string emitBody(const Region &region, const Representation &representation,
                     unsigned originalNewlines);
}
