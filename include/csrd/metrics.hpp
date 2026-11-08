#pragma once
#include <map>
#include <string>
namespace clang { class ASTContext; class FunctionDecl; }
namespace csrd {
struct Metrics {
  unsigned astNodes = 0, expressions = 0, branches = 0, loops = 0,
           cfgBlocks = 0, cfgEdges = 0, cyclomatic = 0;
  std::string astShape, cfgShape;
  std::map<std::string, unsigned> operators;
};
Metrics measure(clang::ASTContext &context, const clang::FunctionDecl &function);
}
