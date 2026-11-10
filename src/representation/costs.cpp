#include "csrd/planner.hpp"

namespace csrd {
const char *encodingName(Encoding e) {
  if (e == Encoding::Limbs16) return "limbs16-u32";
  return e == Encoding::Affine ? "affine-u32" : e == Encoding::Xor ? "xor-u32" : "identity-u32";
}
std::vector<Encoding> allowed(const Node &node) {
  if (isArithmetic(node.kind)) return {Encoding::Identity, Encoding::Affine};
  if (isBitwise(node.kind)) return {Encoding::Identity, Encoding::Xor};
  if (node.kind == Expr::Kind::Select || node.kind == Expr::Kind::Table)
    return {Encoding::Identity, Encoding::Affine, Encoding::Xor};
  return {Encoding::Identity};
}
unsigned conversionCost(Encoding from, Encoding to) {
  if (from == to) return 0;
  return (from == Encoding::Affine ? 2u : from == Encoding::Xor ? 1u : 0u) +
         (to == Encoding::Affine ? 2u : to == Encoding::Xor ? 1u : 0u);
}
Encoding inputEncoding(const Node &node, unsigned operand, Encoding output) {
  if (isComparison(node.kind) || node.kind == Expr::Kind::Table || (node.kind == Expr::Kind::Select && operand == 0)) return Encoding::Identity;
  return output;
}
unsigned operationCost(const Node &n, Encoding e) {
  if (n.kind == Expr::Kind::Constant || n.kind == Expr::Kind::Reference) return 0;
  if (n.kind == Expr::Kind::Table) return unsigned(2 * (n.table.size() - 1));
  if (e == Encoding::Affine && isArithmetic(n.kind)) return 2;
  if (e == Encoding::Xor && isBitwise(n.kind)) {
    if (n.kind == Expr::Kind::BitAnd || n.kind == Expr::Kind::BitOr) return 4;
    return n.kind == Expr::Kind::BitNot ? 1 : 2;
  }
  return 1;
}
}
