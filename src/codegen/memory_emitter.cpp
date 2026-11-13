#include "csrd/graph_emitter.hpp"
#include <map>
#include <stdexcept>

namespace csrd {
namespace {
class MemoryEmitter {
  const Representation &rep;
  const bool encoded;
  std::set<std::string> reserved;
  std::map<std::string, std::string> values;
  const Region *region = nullptr;
  Emission result;
  unsigned sequence = 0;

  std::string fresh() {
    std::string name;
    do { name = "csrd_mem_" + std::to_string(sequence++); } while (!reserved.insert(name).second);
    return name;
  }
  std::string encode(const std::string &value, bool internal = false) {
    if (encoded) { ++result.encodings; ++(internal ? result.internalConversions : result.boundaryConversions); result.estimatedOperations += 2; }
    return rep.entry(value);
  }
  std::string decode(const std::string &value, bool internal = false) {
    if (encoded) { ++result.decodings; ++(internal ? result.internalConversions : result.boundaryConversions); result.estimatedOperations += 2; }
    return rep.exit(value);
  }
  std::string temporary(const std::string &value) {
    const auto name = fresh();
    result.body += " unsigned int " + name + " = " + value + "; (void)" + name + ";";
    ++result.temporaries; return name;
  }
  std::string index(const Expr *e, uint32_t bound) {
    if (!e) return literal(bound);
    const auto value = temporary(decode(expression(*e)));
    // The source range analysis established this bound. Reparse the guard and
    // validate its no-op property against the source; never trust emitter hints.
    return "(" + value + " <= " + literal(bound) + " ? " + value + " : " + literal(bound) + ")";
  }
  std::string location(const std::string &name, const std::string &member, const Expr *offset, uint32_t bound) {
    const auto &buffer = region->buffers.at(name);
    auto value = buffer.persistent ? name : name + "[" + index(offset, bound) + "]";
    if (buffer.recordBytes) value += "." + member;
    return value;
  }
  std::string expression(const Expr &e) {
    if (e.kind == Expr::Kind::Constant) return rep.constant(e.value);
    if (e.kind == Expr::Kind::Reference) return values.at(e.name);
    if (e.kind == Expr::Kind::PointerNonNull)
      return encode("((unsigned int)(" + e.name + " != 0))",true);
    if (e.kind == Expr::Kind::Load) {
      auto load = location(e.name, e.member, e.left.get(), e.value);
      if (region->buffers.at(e.name).elementBits == 8) load = "((unsigned int)(" + load + "))";
      if (region->buffers.at(e.name).heap) return load;
      return encode(load);
    }
    const auto left = e.left ? expression(*e.left) : "";
    const auto right = e.right ? expression(*e.right) : "";
    if (e.kind == Expr::Kind::ByteCast)
      return encode("((unsigned int)((" + std::string(e.value ? "signed char" : "unsigned char") + ")(" +
                    decode(left, true) + ")))", true);
    ++result.operations;
    if (encoded && (e.kind == Expr::Kind::Add || e.kind == Expr::Kind::Subtract || e.kind == Expr::Kind::Scale))
      ++result.encodedOperations;
    else ++result.ordinaryIntermediates;
    switch (e.kind) {
    case Expr::Kind::Add:
      result.estimatedOperations += rep.cost(Operation::Add);
      return rep.binary(Operation::Add, left, right);
    case Expr::Kind::Subtract:
      result.estimatedOperations += rep.cost(Operation::Subtract);
      return rep.binary(Operation::Subtract, left, right);
    case Expr::Kind::Scale:
      result.estimatedOperations += rep.cost(Operation::Scale);
      return rep.times(left, e.value);
    default: break;
    }
    ++result.estimatedOperations;
    if (e.kind == Expr::Kind::Select) {
      const auto other = expression(*e.third);
      return "(" + decode(left, true) + " ? " + right + " : " + other + ")";
    }
    const auto a = decode(left, true);
    if (e.kind == Expr::Kind::BitNot) return encode("(~(" + a + "))", true);
    if (e.kind == Expr::Kind::ShiftLeft || e.kind == Expr::Kind::ShiftRight)
      return encode("((" + a + ") " + (e.kind == Expr::Kind::ShiftLeft ? "<<" : ">>") + " " + literal(e.value) + ")", true);
    const char *op = nullptr;
    switch (e.kind) {
    case Expr::Kind::BitAnd: op = "&"; break;
    case Expr::Kind::BitOr: op = "|"; break;
    case Expr::Kind::BitXor: op = "^"; break;
    case Expr::Kind::Equal: op = "=="; break;
    case Expr::Kind::NotEqual: op = "!="; break;
    case Expr::Kind::Less: op = "<"; break;
    case Expr::Kind::LessEqual: op = "<="; break;
    case Expr::Kind::Greater: op = ">"; break;
    case Expr::Kind::GreaterEqual: op = ">="; break;
    default: throw std::invalid_argument("unmodeled operation in ordered memory emission");
    }
    // Comparisons have type int in C; make the representation boundary explicit.
    return encode("((unsigned int)((" + a + ") " + op + " (" + decode(right, true) + ")))", true);
  }
  void declare(const std::string &source, const std::string &value) {
    const auto name = temporary(value);
    values.insert_or_assign(source, name);
  }
  void call(const Statement &s) {
    std::string invocation = s.callee + "(";
    for (unsigned i = 0; i < s.arguments.size(); ++i) {
      if (i) invocation += ", ";
      const auto &arg = s.arguments[i];
      if (arg.buffer.empty()) invocation += decode(expression(*arg.value));
      else if (arg.value->kind == Expr::Kind::Constant && arg.value->value == 0) invocation += arg.buffer;
      else invocation += "(" + arg.buffer + " + " + index(arg.value.get(), arg.bound) + ")";
    }
    invocation += ")";
    if (s.name.empty()) result.body += " " + invocation + ";";
    else {
      // The call itself is a full expression and executes once. Its ordinary
      // result crosses the ABI boundary before subsequent encoded arithmetic.
      const auto ordinary = temporary(invocation);
      const auto value = encode(ordinary);
      if (s.declaresCallResult) declare(s.name, value);
      else result.body += " " + values.at(s.name) + " = " + value + ";";
    }
  }
  std::string condition(const Expr &e) {
    // Pointer validity is an ordinary boundary predicate. Keep its C spelling
    // explicit so compiler lifetime diagnostics can recognize failure paths.
    if (e.kind==Expr::Kind::PointerNonNull) return e.name+" != 0";
    if ((e.kind==Expr::Kind::Equal || e.kind==Expr::Kind::NotEqual) &&
        e.left->kind==Expr::Kind::PointerNonNull && e.right->kind==Expr::Kind::Constant && e.right->value<=1) {
      const bool null=(e.kind==Expr::Kind::Equal)==(e.right->value==0);
      return e.left->name+(null ? " == 0" : " != 0");
    }
    return "("+decode(expression(e),true)+") != 0u";
  }
  void statements(const std::vector<Statement> &body) {
    for (const auto &s : body) {
      if (s.kind == Statement::Kind::Allocate || s.kind == Statement::Kind::Release || s.kind == Statement::Kind::PointerBind) {
        const auto pointer=s.pointer.empty() ? "0" : s.pointer;
        if (s.kind==Statement::Kind::Release) { result.body+=" free("+pointer+");"; continue; }
        std::string value, count;
        if (s.kind==Statement::Kind::PointerBind)
          value=s.pointerArithmetic ? "("+pointer+" + "+index(s.expression.get(),s.index)+")" : pointer;
        else {
          count=s.expression->kind==Expr::Kind::Constant ? literal(s.expression->value) : index(s.expression.get(),s.index);
          if (s.callee=="calloc") value=s.callocSwapped ? "calloc(4u, "+count+")" : "calloc("+count+", sizeof(unsigned int))";
          else value=s.callee+"("+(s.callee=="realloc" ? pointer+", " : "")+count+" * sizeof(unsigned int))";
        }
        result.body+=" "+std::string(s.declaresCallResult ? "unsigned int *" : "")+s.name+" = "+value+";";
        if (s.kind==Statement::Kind::Allocate && s.callee=="calloc" && encoded) {
          // calloc initializes ordinary zero. Initialize the private storage to
          // E(0) before any read; realloc subsequently copies encoded words.
          const auto induction=fresh();
          result.body+=" if ("+s.name+" != 0) { for (unsigned int "+induction+" = 0u; "+induction+" < "+count+"; ++"+induction+") { "+s.name+"["+induction+"] = "+rep.constant(0)+"; } }";
        }
        continue;
      }
      if (s.kind == Statement::Kind::Call) { call(s); continue; }
      if (s.kind == Statement::Kind::If) {
        const auto predicate = condition(*s.expression);
        const auto outer = values;
        result.body += " if (" + predicate + ") {";
        statements(s.thenBranch); values = outer;
        result.body += "} else {";
        statements(s.elseBranch); values = outer;
        result.body += "}"; continue;
      }
      if (s.kind == Statement::Kind::Repeat) {
        // The analyzer permits only loop-invariant scalar limits. Capture the
        // ordinary bound once; translation validation checks the bound guard.
        const auto limit = temporary(decode(expression(*s.expression), true));
        const auto induction = fresh();
        const auto outer = values;
        values.insert_or_assign(s.name, encode(induction, true));
        result.body += " for (unsigned int " + induction + " = 0u; " + induction + " < (" +
          limit + " <= " + literal(s.repetitions) + " ? " + limit + " : " + literal(s.repetitions) +
          "); ++" + induction + ") {";
        statements(s.thenBranch); values = outer;
        result.body += "}"; continue;
      }
      if (!s.expression) throw std::invalid_argument("unmodeled memory statement");
      const auto value = expression(*s.expression);
      switch (s.kind) {
      case Statement::Kind::Declare: declare(s.name, value); break;
      case Statement::Kind::Assign: result.body += " " + values.at(s.name) + " = " + value + ";"; break;
      case Statement::Kind::Store: {
        const auto target = location(s.name, s.member, s.dynamicIndex.get(), s.index);
        result.body += " " + target + " = " + (region->buffers.at(s.name).heap ? value : decode(value)) + ";"; break;
      }
      case Statement::Kind::Return: result.body += " return " + decode(value) + ";"; break;
      default: throw std::invalid_argument("unmodeled control flow in ordered memory emission");
      }
    }
  }
public:
  MemoryEmitter(const Representation &r, const std::set<std::string> &names)
      : rep(r), encoded(std::string(r.name()) != "identity-u32"), reserved(names) {}
  Emission run(const Region &input, unsigned newlines) {
    region = &input;
    if (!region->ordered()) throw std::invalid_argument("ordered emission requires memory or calls");
    result.body = "{";
    for (const auto &name : region->parameters) {
      if (region->buffers.count(name)) result.body += " (void)" + name + ";";
      else declare(name, encode(name));
    }
    statements(region->statements);
    result.body += std::string(newlines, '\n') + "}";
    return result;
  }
};
}
Emission emitMemory(const Region &region, const Representation &representation,
                    unsigned originalNewlines, const std::set<std::string> &reserved) {
  return MemoryEmitter(representation, reserved).run(region, originalNewlines);
}
}
