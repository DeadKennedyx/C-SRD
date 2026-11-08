#include "csrd/metrics.hpp"
#include "csrd/frontend.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/AST/Expr.h"
#include "clang/Analysis/CFG.h"
#include <set>
#include <vector>

namespace csrd {
Metrics measure(clang::ASTContext &context, const clang::FunctionDecl &function) {
  Metrics result;
  std::string shape;
  auto visit = [&](auto &&self, const clang::Stmt *statement) -> void {
    if (!statement) { shape += "nil;"; return; }
    ++result.astNodes;
    if (llvm::isa<clang::Expr>(statement)) ++result.expressions;
    shape += statement->getStmtClassName(); shape += '(';
    if (const auto *binary = llvm::dyn_cast<clang::BinaryOperator>(statement)) {
      const auto op = binary->getOpcodeStr().str(); ++result.operators[op]; shape += op;
    }
    if (const auto *unary = llvm::dyn_cast<clang::UnaryOperator>(statement)) {
      const auto op = clang::UnaryOperator::getOpcodeStr(unary->getOpcode()).str(); ++result.operators[op]; shape += op;
    }
    if (llvm::isa<clang::IfStmt, clang::ConditionalOperator, clang::SwitchStmt>(statement)) ++result.branches;
    if (llvm::isa<clang::ForStmt, clang::WhileStmt, clang::DoStmt>(statement)) ++result.loops;
    for (const auto *child : statement->children()) self(self, child);
    shape += ')';
  };
  visit(visit, function.getBody());
  result.astShape = sha256(shape);
  auto cfg = clang::CFG::buildCFG(&function, const_cast<clang::Stmt *>(function.getBody()), &context, clang::CFG::BuildOptions());
  if (cfg) {
    std::set<unsigned> visited;
    std::vector<const clang::CFGBlock *> queue{&cfg->getEntry()};
    std::map<unsigned, std::set<unsigned>> edges;
    while (!queue.empty()) {
      const auto *block = queue.back(); queue.pop_back();
      if (!visited.insert(block->getBlockID()).second) continue;
      for (auto successor : block->succs()) if (const auto *next = successor.getReachableBlock()) {
        edges[block->getBlockID()].insert(next->getBlockID()); queue.push_back(next);
      }
    }
    result.cfgBlocks = unsigned(visited.size());
    std::string adjacency;
    for (auto block : visited) {
      adjacency += std::to_string(block) + ":";
      for (auto next : edges[block]) { ++result.cfgEdges; adjacency += std::to_string(next) + ","; }
      adjacency += ";";
    }
    result.cyclomatic = result.cfgEdges + 2 - result.cfgBlocks;
    result.cfgShape = sha256(adjacency);
  }
  return result;
}
}
