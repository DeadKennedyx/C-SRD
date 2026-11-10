#pragma once
#include "csrd/verification.hpp"
#include <z3++.h>
#include <map>

namespace csrd::verification_detail {
using Environment = std::map<std::string, z3::expr>;
z3::expr expression(z3::context &ctx, const Expr &e, const Environment &values);
Verification verifyDirect(const Region &original, const Region &candidate, unsigned timeoutMs);
}
