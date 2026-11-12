#include "symbolic.hpp"
#include <algorithm>
#include <set>
#include <stdexcept>

namespace csrd {
namespace {
using verification_detail::Environment;
struct CallEvent {
  std::string callee;
  z3::expr memory;
  std::vector<z3::expr> arguments;
};
struct Execution {
  z3::expr first, second;
  z3::expr bounds;
  std::vector<CallEvent> events;
};
class MemoryModel {
  z3::context &ctx;
  bool bytes, littleEndian, enumerate;
  mutable z3::expr ranges;
public:
  MemoryModel(z3::context &c, bool b, bool little, bool finite) : ctx(c), bytes(b), littleEndian(little), enumerate(finite), ranges(c.bool_val(true)) {}
  z3::expr address(const z3::expr &base, const z3::expr &index, unsigned bits) const {
    return base + z3::bv2int(index, false) * ctx.int_val(bytes ? bits / 8 : 1);
  }
  z3::expr location(const Region::Buffer &buffer, const z3::expr &base, const z3::expr &index,
                    const std::string &member) const {
    if (!buffer.recordBytes) return address(base, index, buffer.elementBits);
    const unsigned unit = bytes ? 1 : 4;
    return base + z3::bv2int(index, false) * ctx.int_val(buffer.recordBytes / unit) +
           ctx.int_val(buffer.fields.at(member) / unit);
  }
  z3::expr load(const z3::expr &memory, const z3::expr &at, unsigned bits, bool sign) const {
    if (!bytes) return z3::select(memory, at);
    auto result = z3::select(memory, at);
    for (unsigned i = 1; i < bits / 8; ++i) {
      auto next = z3::select(memory, at + ctx.int_val(i));
      result = littleEndian ? z3::concat(next, result) : z3::concat(result, next);
    }
    return bits == 32 ? result : sign ? z3::sext(result, 32 - bits) : z3::zext(result, 32 - bits);
  }
  z3::expr store(z3::expr memory, const z3::expr &at, const z3::expr &word, unsigned bits) const {
    if (!bytes) return z3::store(memory, at, word);
    for (unsigned i = 0; i < bits / 8; ++i) {
      const unsigned bit = (littleEndian ? i : bits / 8 - i - 1) * 8;
      memory = z3::store(memory, at + ctx.int_val(i), word.extract(bit + 7, bit));
    }
    return memory;
  }
  z3::expr value(const Region &r, const Expr &e, const Environment &scalars,
                 const Environment &bases, const z3::expr &memory) const {
  auto eval = [&](const Expr &x) { return value(r, x, scalars, bases, memory); };
  auto boolean = [&](const z3::expr &x) { return z3::ite(x, ctx.bv_val(1,32), ctx.bv_val(0,32)); };
  switch (e.kind) {
  case Expr::Kind::Constant: return ctx.bv_val(e.value, 32);
  case Expr::Kind::Reference: return scalars.at(e.name);
  case Expr::Kind::Load: {
    const auto &buffer = r.buffers.at(e.name);
    const auto index = e.left ? eval(*e.left) : ctx.bv_val(e.value, 32);
    auto read = [&](const z3::expr &i) { return load(memory, location(buffer, bases.at(e.name), i, e.member), buffer.elementBits, buffer.elementSigned); };
    if (enumerate && e.left && e.value <= 16) {
      // The range is a proof obligation, never an assumed clamp. Enumerating
      // small indices avoids mixed integer/bit-vector address reasoning.
      ranges = ranges && z3::ule(index, ctx.bv_val(e.value,32));
      auto result = read(ctx.bv_val(e.value,32));
      for (unsigned i = 0; i < e.value; ++i) result = z3::ite(index == ctx.bv_val(i,32),read(ctx.bv_val(i,32)),result);
      return result;
    }
    return read(index);
  }
  case Expr::Kind::ByteCast: {
    const auto low = eval(*e.left).extract(7,0);
    return e.value ? z3::sext(low,24) : z3::zext(low,24);
  }
  case Expr::Kind::Add: return eval(*e.left) + eval(*e.right);
  case Expr::Kind::Subtract: return eval(*e.left) - eval(*e.right);
  case Expr::Kind::Scale: return eval(*e.left) * ctx.bv_val(e.value, 32);
  case Expr::Kind::BitAnd: return eval(*e.left) & eval(*e.right);
  case Expr::Kind::BitOr: return eval(*e.left) | eval(*e.right);
  case Expr::Kind::BitXor: return eval(*e.left) ^ eval(*e.right);
  case Expr::Kind::BitNot: return ~eval(*e.left);
  case Expr::Kind::ShiftLeft: return z3::shl(eval(*e.left), ctx.bv_val(e.value,32));
  case Expr::Kind::ShiftRight: return z3::lshr(eval(*e.left), ctx.bv_val(e.value,32));
  case Expr::Kind::Equal: return boolean(eval(*e.left) == eval(*e.right));
  case Expr::Kind::NotEqual: return boolean(eval(*e.left) != eval(*e.right));
  case Expr::Kind::Less: return boolean(z3::ult(eval(*e.left), eval(*e.right)));
  case Expr::Kind::LessEqual: return boolean(z3::ule(eval(*e.left), eval(*e.right)));
  case Expr::Kind::Greater: return boolean(z3::ugt(eval(*e.left), eval(*e.right)));
  case Expr::Kind::GreaterEqual: return boolean(z3::uge(eval(*e.left), eval(*e.right)));
  case Expr::Kind::Select: return z3::ite(eval(*e.left) != ctx.bv_val(0,32), eval(*e.right), eval(*e.third));
  default: throw std::invalid_argument("unmodeled expression in buffer verification");
  }
  }
  Execution execute(const Region &r, Environment scalars,
                                     const Environment &bases, z3::expr memory) const {
  std::vector<CallEvent> events;
  ranges = ctx.bool_val(true);
  for (const auto &s : r.statements) {
    if (s.kind == Statement::Kind::Call) {
      const auto &contract = r.calls.at(s.callee);
      if (s.arguments.size() != contract.parameters.size()) throw std::invalid_argument("call IR arity mismatch");
      CallEvent event{s.callee, memory, {}};
      for (const auto &arg : s.arguments) {
        const auto v = value(r, *arg.value, scalars, bases, memory);
        event.arguments.push_back(arg.buffer.empty() ? v :
          address(bases.at(arg.buffer), v, r.buffers.at(arg.buffer).elementBits));
      }
      const auto id = std::to_string(events.size());
      events.push_back(std::move(event));
      // Couple the environment choices at the same event number. Equivalence
      // also requires equal event prefixes, arguments and pre-call memory.
      // Havoc is deliberately broader than a callee's actual write footprint.
      memory = ctx.constant(("call_memory_" + id).c_str(), memory.get_sort());
      if (!s.name.empty()) {
        if (contract.returnsVoid) throw std::invalid_argument("void call used as a value");
        scalars.insert_or_assign(s.name, ctx.bv_const(("call_result_" + id).c_str(), 32));
      }
      continue;
    }
    if (!s.expression) throw std::invalid_argument("unmodeled memory statement");
    const auto result = value(r, *s.expression, scalars, bases, memory);
    switch (s.kind) {
    case Statement::Kind::Declare:
    case Statement::Kind::Assign: scalars.insert_or_assign(s.name, result); break;
    case Statement::Kind::Store: {
      const auto bits = r.buffers.at(s.name).elementBits;
      const auto index = s.dynamicIndex ? value(r,*s.dynamicIndex,scalars,bases,memory) : ctx.bv_val(s.index,32);
      auto write = [&](const z3::expr &i) { return store(memory, location(r.buffers.at(s.name), bases.at(s.name), i, s.member), result, bits); };
      if (enumerate && s.dynamicIndex && s.index <= 16) {
        ranges = ranges && z3::ule(index,ctx.bv_val(s.index,32));
        auto next = write(ctx.bv_val(s.index,32));
        for (unsigned i = 0; i < s.index; ++i) next = z3::ite(index == ctx.bv_val(i,32),write(ctx.bv_val(i,32)),next);
        memory = next;
      } else memory = write(index);
      break;
    }
    case Statement::Kind::Return: return {result, memory, ranges, std::move(events)};
    default: throw std::invalid_argument("unmodeled control flow in buffer verification");
    }
  }
  throw std::invalid_argument("buffer region lacks final return");
  }
};
}
Verification verifyMemory(const Region &original, const Region &candidate, unsigned timeoutMs) {
  Verification proof;
  const auto hasRecords = [](const Region &r) {
    return std::any_of(r.buffers.begin(), r.buffers.end(), [](const auto &entry) {
      return entry.second.recordBytes || entry.second.persistent;
    });
  };
  const auto wordOnly = [](const Region &r) {
    return std::all_of(r.buffers.begin(), r.buffers.end(), [](const auto &entry) { return entry.second.elementBits == 32; });
  };
  // Padding-free, aligned uint32 accesses partition shared bytes into words.
  // Equality of every word is equality of every byte. This exact projection
  // avoids asking the solver to rediscover alignment across byte-store chains.
  const bool recordWords = (hasRecords(original) || hasRecords(candidate)) && wordOnly(original) && wordOnly(candidate);
  const bool bytes = !recordWords && (original.extendedMemory || candidate.extendedMemory);
  proof.strategy = std::string(bytes ? "shared-byte-memory" : "shared-word-memory") +
                   (recordWords ? "/aligned-record-projection/blast-select-store/bv-sort-ac" : "") +
                   (original.orderedCalls || candidate.orderedCalls ? "/ordered-opaque-calls" : "") +
                   "/simplify/blast-term-ite/simplify/smt";
  proof.memoryAddressUnit = bytes ? "byte" : "word32";
  try {
    if (original.parameters.size() != candidate.parameters.size()) throw std::invalid_argument("parameter arity mismatch");
    if (original.littleEndian != candidate.littleEndian) throw std::invalid_argument("target endianness mismatch");
    z3::context ctx;
    Environment leftScalars, rightScalars, leftBases, rightBases;
    std::vector<z3::expr> inputs;
    auto compatible = [](const Region::Buffer &a, const Region::Buffer &b) {
      if (a.persistent != b.persistent || a.recordTag != b.recordTag || a.isUnion != b.isUnion ||
          a.recordBytes != b.recordBytes || a.recordAlignment != b.recordAlignment || a.fields != b.fields)
        throw std::invalid_argument("record layout or persistent object kind mismatch");
      if (a.readOnly != b.readOnly) throw std::invalid_argument("pointer constness mismatch");
      if (a.elementBits != b.elementBits || a.elementSigned != b.elementSigned || a.elementType != b.elementType)
        throw std::invalid_argument("pointer element type mismatch");
      if (b.minimumElements > a.minimumElements)
        throw std::invalid_argument("candidate requires a larger buffer footprint than the original contract");
    };
    for (unsigned i = 0; i < original.parameters.size(); ++i) {
      const auto &left = original.parameters[i], &right = candidate.parameters[i];
      const auto a = original.buffers.find(left), b = candidate.buffers.find(right);
      if ((a == original.buffers.end()) != (b == candidate.buffers.end()))
        throw std::invalid_argument("scalar/pointer parameter kind mismatch");
      if (a == original.buffers.end()) {
        const auto input = ctx.bv_const(("input_" + std::to_string(i)).c_str(), 32);
        leftScalars.emplace(left, input); rightScalars.emplace(right, input); inputs.push_back(input);
      } else {
        compatible(a->second, b->second);
        const auto base = ctx.int_const(("base_" + std::to_string(i)).c_str());
        leftBases.emplace(left, base); rightBases.emplace(right, base);
      }
    }
    // File-scope identities are shared across calls and across both programs.
    // Public pointers may alias these objects; do not invent disjointness.
    for (const auto &[name, buffer] : original.buffers) if (buffer.persistent) {
      const auto found = candidate.buffers.find(name);
      if (found == candidate.buffers.end() || !found->second.persistent)
        throw std::invalid_argument("persistent object set mismatch");
      compatible(buffer, found->second);
      const auto base = ctx.int_const(("global_" + name).c_str());
      leftBases.emplace(name, base); rightBases.emplace(name, base);
    }
    for (const auto &[name, buffer] : candidate.buffers) if (buffer.persistent && !leftBases.count(name))
      throw std::invalid_argument("candidate introduces a persistent object");
    const auto memory = ctx.constant("initial_memory", ctx.array_sort(ctx.int_sort(), ctx.bv_sort(bytes ? 8 : 32)));
    const MemoryModel model(ctx, bytes, original.littleEndian, recordWords);
    const auto left = model.execute(original, leftScalars, leftBases, memory);
    const auto right = model.execute(candidate, rightScalars, rightBases, memory);
    z3::params params(ctx); params.set("som", true); params.set("push_ite_bv", true);
    if (recordWords) { params.set("blast_select_store", true); params.set("bv_sort_ac", true); }
    const auto simplify = z3::with(z3::tactic(ctx, "simplify"), params);
    auto solver = (simplify & z3::tactic(ctx, "blast-term-ite") & simplify & z3::tactic(ctx, "smt")).mk_solver();
    solver.set("timeout", timeoutMs);
    if (bytes) for (const auto &[name, buffer] : original.buffers)
      if (buffer.elementBits == 32) solver.add(leftBases.at(name) % ctx.int_val(4) == 0);
    // File-scope definitions denote separate complete objects. A pointer to a
    // flat record may designate that same complete record, but cannot start at
    // its second field. Ordinary uint32 pointers still alias record members.
    // This is an object-layout condition, not a restrict/no-alias assumption.
    const unsigned unit = bytes ? 1 : 4;
    for (auto a = original.buffers.begin(); a != original.buffers.end(); ++a) {
      const auto &x = a->second;
      if (!x.minimumElements) continue;
      for (auto b = std::next(a); b != original.buffers.end(); ++b) {
        const auto &y = b->second;
        if (!y.minimumElements || (!x.persistent && !y.persistent)) continue;
        const auto xb = leftBases.at(a->first), yb = leftBases.at(b->first);
        const auto disjoint = xb + ctx.int_val(x.minimumElements * x.stride() / unit) <= yb ||
                              yb + ctx.int_val(y.minimumElements * y.stride() / unit) <= xb;
        if (x.persistent && y.persistent) solver.add(disjoint);
        else {
          const auto &pointer = x.persistent ? y : x, &global = x.persistent ? x : y;
          if (pointer.recordBytes) {
            const bool same = pointer.recordTag == global.recordTag && pointer.isUnion == global.isUnion &&
                              pointer.recordBytes == global.recordBytes && pointer.minimumElements == 1;
            solver.add(disjoint || (ctx.bool_val(same) && xb == yb));
          } else if (pointer.elementBits == 32 && pointer.minimumElements > 1) solver.add(disjoint);
        }
      }
    }
    auto mismatch = !left.bounds || !right.bounds || left.first != right.first || left.second != right.second ||
                    ctx.bool_val(left.events.size() != right.events.size());
    for (unsigned i = 0; i < std::min(left.events.size(), right.events.size()); ++i) {
      const auto &a = left.events[i], &b = right.events[i];
      if (a.callee != b.callee || a.arguments.size() != b.arguments.size()) {
        mismatch = ctx.bool_val(true); continue;
      }
      const auto &ac = original.calls.at(a.callee), &bc = candidate.calls.at(b.callee);
      if (ac.returnsVoid != bc.returnsVoid || ac.parameters.size() != bc.parameters.size())
        throw std::invalid_argument("call contracts differ");
      for (unsigned j = 0; j < ac.parameters.size(); ++j) {
        const auto &ap = ac.parameters[j], &bp = bc.parameters[j];
        if (ap.kind != bp.kind || ap.readOnly != bp.readOnly || ap.minimumElements != bp.minimumElements)
          throw std::invalid_argument("call parameter contracts differ");
        mismatch = mismatch || a.arguments[j] != b.arguments[j];
      }
      mismatch = mismatch || a.memory != b.memory;
    }
    solver.add(mismatch);
    proof.obligation = solver.to_smt2();
    const auto answer = solver.check();
    if (answer == z3::unsat) proof.status = "proved-under-model";
    else if (answer == z3::unknown) { proof.status = "inconclusive"; proof.reason = solver.reason_unknown(); }
    else {
      proof.status = "counterexample";
      const auto model = solver.get_model();
      auto word = [&](const z3::expr &e) { return uint32_t(model.eval(e, true).get_numeral_uint64()); };
      for (const auto &input : inputs) proof.inputs.push_back(word(input));
      proof.originalOutput = word(left.first); proof.candidateOutput = word(right.first);
      if (!left.events.empty() || !right.events.empty()) {
        proof.reason = "return, final memory or ordered call trace differs under shared environment choices";
        for (unsigned i = 0; i < std::max(left.events.size(), right.events.size()); ++i) {
          const auto name = "call_result_" + std::to_string(i);
          proof.localValues.emplace_back(name, word(ctx.bv_const(name.c_str(), 32)));
        }
      }
      std::set<std::string> seen;
      for (const auto &[name, buffer] : original.buffers) {
        proof.pointerBases.emplace_back(name, model.eval(leftBases.at(name), true).to_string());
        const unsigned cells = buffer.minimumElements * (bytes ? buffer.stride() : buffer.stride() / 4);
        for (unsigned i = 0; i < cells; ++i) {
          const auto address = model.eval(leftBases.at(name) + ctx.int_val(i), true);
          if (seen.insert(address.to_string()).second)
            proof.memoryCells.push_back({address.to_string(), word(z3::select(memory, address)),
              word(z3::select(left.second, address)), word(z3::select(right.second, address))});
        }
      }
    }
  } catch (const z3::exception &e) { proof.status = "inconclusive"; proof.reason = e.msg(); }
    catch (const std::exception &e) { proof.status = "unsupported"; proof.reason = e.what(); }
  return proof;
}
}
