#pragma once
#include "csrd/ir.hpp"
#include "clang/Basic/SourceLocation.h"
#include <optional>
namespace clang { class ASTContext; class FunctionDecl; }
namespace csrd {
struct Analysis {
  std::optional<Region> region;
  std::string reason;
  clang::SourceLocation location;
};
Analysis analyze(clang::ASTContext &context, const clang::FunctionDecl &function);
}
