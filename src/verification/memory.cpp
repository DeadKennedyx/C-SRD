#include "symbolic.hpp"
#include "heap.hpp"
#include <algorithm>
#include <chrono>
#include <set>
#include <stdexcept>

namespace csrd {
namespace {
using verification_detail::Environment;
class ExpandedReads {
  struct Entry { z3::expr memory, address, value; };
  // Retain the keyed ASTs too: Z3 may reuse IDs after an AST is released.
  std::map<std::pair<unsigned,unsigned>,Entry> cache;
public:
  z3::expr select(const z3::expr &memory, const z3::expr &at) {
    const auto key=std::make_pair(memory.id(),at.id());
    const auto found=cache.find(key); if (found!=cache.end()) return found->second.value;
    auto value=z3::select(memory,at);
    if (memory.is_app() && memory.decl().decl_kind()==Z3_OP_ITE)
      value=z3::ite(memory.arg(0),select(memory.arg(1),at),select(memory.arg(2),at));
    else if (memory.is_app() && memory.decl().decl_kind()==Z3_OP_STORE)
      value=z3::ite(at==memory.arg(1),memory.arg(2),select(memory.arg(0),at));
    cache.emplace(key,Entry{memory,at,value}); return value;
  }
};
struct CallEvent {
  std::string callee;
  bool indirect;
  z3::expr active, ordinal, target, memory;
  std::vector<z3::expr> arguments;
};
bool sameCallSignature(const CallContract &a,const CallContract &b) {
  if (a.returnsVoid!=b.returnsVoid || a.returnsSigned!=b.returnsSigned || a.standardStream!=b.standardStream ||
      a.parameters.size()!=b.parameters.size()) return false;
  for (unsigned i=0;i<a.parameters.size();++i) {
    const auto &x=a.parameters[i], &y=b.parameters[i];
    if (x.kind!=y.kind || x.readOnly!=y.readOnly || x.minimumElements!=y.minimumElements) return false;
  }
  return true;
}
z3::expr callResult(z3::context &ctx,const z3::expr &ordinal) {
  return z3::select(ctx.constant("call_results",ctx.array_sort(ctx.int_sort(),ctx.bv_sort(32))),ordinal);
}
struct Execution {
  z3::expr first, second;
  z3::expr bounds;
  std::vector<CallEvent> events;
  std::vector<z3::expr> writes;
  std::vector<z3::expr> conditions;
  std::vector<verification_detail::HeapState::Event> heapEvents;
};
class MemoryModel {
  z3::context &ctx;
  bool bytes, littleEndian, enumerate, control, expandRecursion, outsideRecursionRange;
  mutable z3::expr ranges;
  mutable ExpandedReads reads;
  bool proveRangeSelects;
  mutable unsigned selectProofAttempts=0;
  mutable std::map<unsigned,z3::expr> provedSelects;
  mutable std::vector<Verification> selectProofs;
  z3::params normalization;
  z3::expr normalize(const z3::expr &value) const { return value.simplify(normalization); }
public:
  MemoryModel(z3::context &c, bool b, bool little, bool finite, bool guarded, bool recurse, bool outside, bool rangeSelects) : ctx(c), bytes(b), littleEndian(little), enumerate(finite), control(guarded), expandRecursion(recurse), outsideRecursionRange(outside), ranges(c.bool_val(true)), proveRangeSelects(rangeSelects), normalization(c) {
    if (control) {
      normalization.set("som",true); normalization.set("push_ite_bv",true);
      normalization.set("blast_select_store",true);
      normalization.set("bv_sort_ac",true);
      normalization.set("bv_extract_prop",true);
    }
  }
  const std::vector<Verification> &rangeSelectProofs() const { return selectProofs; }
  bool provedTrue(const z3::expr &condition) const {
    if (condition.is_true()) return true;
    if (!proveRangeSelects || condition.is_false()) return false;
    if (provedSelects.count(condition.id())) return true;
    if (selectProofAttempts>=32) return false;
    // Only cheap closed scalar facts: no stream results, memory or path
    // assumptions enter this auxiliary proof. Unknown leaves the select intact.
    std::set<unsigned> seen;std::vector<z3::expr> pending{condition};
    while (!pending.empty()) {
      const auto item=pending.back();pending.pop_back();
      if (!seen.insert(item.id()).second) continue;
      if (!item.is_app() || item.decl().decl_kind()==Z3_OP_SELECT) return false;
      for (unsigned i=0;i<item.num_args();++i) pending.push_back(item.arg(i));
    }
    ++selectProofAttempts;
    // A 5 ms budget was below ordinary solver-startup/scheduling jitter on
    // Linux and caused harmless range facts to disappear under CI contention.
    // The cap remains bounded; an unknown result still changes no semantics.
    z3::solver solver(ctx);solver.set("timeout",50u);solver.add(!condition);
    if (solver.check()!=z3::unsat) return false;
    Verification proof;proof.status="proved-under-model";proof.strategy="unconditional-scalar-select-guard";
    proof.obligation=solver.to_smt2();selectProofs.push_back(std::move(proof));
    provedSelects.emplace(condition.id(),condition);return true;
  }
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
    auto select = [&](const z3::expr &address) { return control ? reads.select(memory,address) : z3::select(memory,address); };
    if (!bytes) return select(at);
    auto result = select(at);
    for (unsigned i = 1; i < bits / 8; ++i) {
      auto next = select(at + ctx.int_val(i));
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
                 const Environment &bases, const z3::expr &memory, const z3::expr &active,
                 verification_detail::HeapState &heap) const {
  auto eval = [&](const Expr &x) { return value(r, x, scalars, bases, memory, active, heap); };
  auto boolean = [&](const z3::expr &x) { return z3::ite(x, ctx.bv_val(1,32), ctx.bv_val(0,32)); };
  switch (e.kind) {
  case Expr::Kind::Constant: return ctx.bv_val(e.value, 32);
  case Expr::Kind::Reference: return scalars.at(e.name);
  case Expr::Kind::PointerNonNull: return boolean(heap.nonnull(e.name,active));
  case Expr::Kind::Load: {
    const auto &buffer = r.buffers.at(e.name);
    const auto index = e.left ? eval(*e.left) : ctx.bv_val(e.value, 32);
    if (e.left) ranges = ranges && z3::implies(active, z3::ule(index, ctx.bv_val(e.value,32)));
    if (buffer.heap) return heap.load(e.name,index,active);
    auto read = [&](const z3::expr &i) { return load(memory, location(buffer, bases.at(e.name), i, e.member), buffer.elementBits, buffer.elementSigned); };
    if (enumerate && e.left && e.value <= 16) {
      // The range is a proof obligation, never an assumed clamp. Enumerating
      // small indices avoids mixed integer/bit-vector address reasoning.
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
  case Expr::Kind::Select: {
    const auto condition = normalize(eval(*e.left) != ctx.bv_val(0,32));
    if (provedTrue(condition)) return eval(*e.right);
    const auto yes = value(r, *e.right, scalars, bases, memory, active && condition, heap);
    const auto no = value(r, *e.third, scalars, bases, memory, active && !condition, heap);
    return z3::ite(condition, yes, no);
  }
  default: throw std::invalid_argument("unmodeled expression in buffer verification");
  }
  }
  struct State {
    Environment scalars, entryScalars;
    z3::expr memory, active, output, callOrdinal;
    std::vector<CallEvent> events;
    std::vector<z3::expr> writes;
    std::vector<z3::expr> conditions;
    unsigned visits = 0;
    verification_detail::HeapState heap;
    unsigned recursionDepth = 0;
  };
  void statements(const Region &r, const std::vector<Statement> &body, const Environment &bases,
                  State &state, const z3::expr &guard) const {
  auto &scalars = state.scalars;
  auto &memory = state.memory;
  auto &events = state.events;
  for (const auto &s : body) {
    if (++state.visits > 4096) throw std::invalid_argument("memory verification exceeds 4096 unrolled statement visits");
    const auto active = normalize(guard && state.active);
    // A syntactically simplified false guard is a proof of unreachability.
    // Do not expand loads or arithmetic from such paths; no runtime behavior
    // or object lifetime can depend on their statements.
    if (active.is_false()) continue;
    auto eval = [&](const Expr &e) { return normalize(value(r, e, scalars, bases, memory, active, state.heap)); };
    if (s.kind == Statement::Kind::Allocate || s.kind == Statement::Kind::Release) {
      state.heap.allocation(s,s.expression ? eval(*s.expression) : ctx.bv_val(0,32),active,memory);
      if (s.kind == Statement::Kind::Allocate)
        state.conditions.push_back(verification_detail::HeapState::outcome(ctx,state.heap.events.back().ordinal));
      continue;
    }
    if (s.kind == Statement::Kind::PointerBind) {
      state.heap.bind(s,eval(*s.expression),active); continue;
    }
    if (s.kind == Statement::Kind::If) {
      const auto condition = normalize(eval(*s.expression) != ctx.bv_val(0,32));
      state.conditions.push_back(condition);
      statements(r, s.thenBranch, bases, state, active && condition);
      statements(r, s.elseBranch, bases, state, active && !condition);
      continue;
    }
    if (s.kind == Statement::Kind::Repeat) {
      if (s.repetitions > 32) throw std::invalid_argument("memory loop exceeds 32-iteration verification limit");
      auto running = active;
      for (unsigned i = 0; i < s.repetitions; ++i) {
        scalars.insert_or_assign(s.name, ctx.bv_val(i,32));
        if (s.expression) {
          const auto limit = normalize(value(r, *s.expression, scalars, bases, memory, running && state.active, state.heap));
          const auto condition = normalize(z3::ult(ctx.bv_val(i,32), limit));
          state.conditions.push_back(condition);
          running = normalize(running && condition);
        }
        statements(r, s.thenBranch, bases, state, running);
        running = normalize(running && state.active);
      }
      if (s.expression) {
        scalars.insert_or_assign(s.name, ctx.bv_val(s.repetitions,32));
        const auto limit = value(r, *s.expression, scalars, bases, memory, running && state.active, state.heap);
        // A finite unroll is sound only when every remaining path exits here.
        ranges = ranges && !(running && state.active && z3::ult(ctx.bv_val(s.repetitions,32), limit));
      }
      scalars.erase(s.name);
      continue;
    }
    if (s.kind == Statement::Kind::Call) {
      if (!active.is_true() && !r.guardedCalls) throw std::invalid_argument("conditional calls require guarded-v2 contracts");
      if (events.size()>=64) throw std::invalid_argument("call model exceeds 64 expanded events");
      const auto &contract = r.calls.at(s.callee);
      if (s.arguments.size() != contract.parameters.size()) throw std::invalid_argument("call IR arity mismatch");
      const auto ordinal=state.callOrdinal;
      CallEvent event{s.callee,!s.indirectTarget.empty(),active,ordinal,
        s.indirectTarget.empty() ? ctx.int_val(0) : bases.at(s.indirectTarget),memory,{}};
      for (const auto &arg : s.arguments) {
        if (!arg.stream.empty()) { event.arguments.push_back(bases.at(arg.stream));continue; }
        const auto v = eval(*arg.value);
        if (arg.nonnegativeInt) ranges=ranges && z3::implies(active,z3::ule(v,ctx.bv_val(INT32_MAX,32)));
        if (!arg.buffer.empty()) ranges=ranges && z3::implies(active,z3::ule(v,ctx.bv_val(arg.bound,32)));
        event.arguments.push_back(arg.buffer.empty() ? v :
          address(bases.at(arg.buffer), v, r.buffers.at(arg.buffer).elementBits));
      }
      if (s.recursiveCall) {
        if (!contract.recursive || !s.indirectTarget.empty() || s.callee!=r.name || contract.rankParameter>=r.parameters.size())
          throw std::invalid_argument("invalid recursive rank contract");
        const auto incoming=state.entryScalars.at(r.parameters[contract.rankParameter]);
        ranges=ranges && z3::implies(active,z3::ule(incoming,ctx.bv_val(contract.maximumRank,32)) &&
          z3::ult(event.arguments.at(contract.rankParameter),incoming));
        if (expandRecursion) {
          auto result=ctx.bv_val(0,32);
          if (state.recursionDepth>=contract.maximumRank) {
            // A checked exit obligation, never silent truncation. If this call
            // can execute the proof fails, regardless of its discarded result.
            ranges=ranges && !active;
          } else {
            Environment arguments,childBases=bases;
            for (unsigned i=0;i<r.parameters.size();++i) {
              if (contract.parameters[i].kind=="uint32") arguments.emplace(r.parameters[i],event.arguments[i]);
              else childBases.insert_or_assign(r.parameters[i],event.arguments[i]);
            }
            State child{arguments,arguments,memory,active,ctx.bv_val(0,32),ordinal,{}, {}, {},state.visits,verification_detail::HeapState(ctx)};
            child.recursionDepth=state.recursionDepth+1;
            statements(r,r.statements,childBases,child,active);
            ranges=ranges && !child.active && child.heap.valid;
            state.visits=child.visits;memory=child.memory;result=child.output;state.callOrdinal=child.callOrdinal;
            events.insert(events.end(),child.events.begin(),child.events.end());
            if (events.size()>64) throw std::invalid_argument("expanded recursion exceeds 64 external call events");
            state.writes.insert(state.writes.end(),child.writes.begin(),child.writes.end());
            state.conditions.insert(state.conditions.end(),child.conditions.begin(),child.conditions.end());
          }
          if (!s.name.empty()) scalars.insert_or_assign(s.name,s.declaresCallResult ? result : normalize(z3::ite(active,result,scalars.at(s.name))));
          continue;
        }
      }
      events.push_back(std::move(event));
      state.callOrdinal=normalize(ordinal+z3::ite(active,ctx.int_val(1),ctx.int_val(0)));
      // Couple only executed event ordinals. Inactive branch sites consume no
      // environment choice and cannot change memory or an existing local.
      if (!contract.standardStream) {
        const auto environment=ctx.constant("call_memories",ctx.array_sort(ctx.int_sort(),memory.get_sort()));
        memory=normalize(z3::ite(active,z3::select(environment,ordinal),memory));
      }
      // The stdio contract keeps ALL library-managed storage (including errno,
      // FILE internals and setvbuf buffers) disjoint from admitted user storage.
      // It also excludes callbacks.
      // Only its opaque external state changes, coupled by the call sequence.
      if (!s.name.empty()) {
        if (contract.returnsVoid) throw std::invalid_argument("void call used as a value");
        const auto value=callResult(ctx,ordinal);
        scalars.insert_or_assign(s.name,s.declaresCallResult ? value : normalize(z3::ite(active,value,scalars.at(s.name))));
      }
      continue;
    }
    if (!s.expression) throw std::invalid_argument("unmodeled memory statement");
    const auto result = eval(*s.expression);
    switch (s.kind) {
    case Statement::Kind::Declare: scalars.insert_or_assign(s.name, result); break;
    case Statement::Kind::Assign:
      scalars.insert_or_assign(s.name, normalize(z3::ite(active, result, scalars.at(s.name)))); break;
    case Statement::Kind::Store: {
      const auto bits = r.buffers.at(s.name).elementBits;
      const auto index = s.dynamicIndex ? eval(*s.dynamicIndex) : ctx.bv_val(s.index,32);
      if (s.dynamicIndex) ranges = ranges && z3::implies(active, z3::ule(index,ctx.bv_val(s.index,32)));
      if (r.buffers.at(s.name).heap) { state.heap.store(s.name,index,result,active); break; }
      const auto at = location(r.buffers.at(s.name), bases.at(s.name), index, s.member);
      for (unsigned i = 0; i < (bytes ? bits / 8 : 1); ++i) state.writes.push_back(normalize(at + ctx.int_val(i)));
      auto write = [&](const z3::expr &i) { return store(memory, location(r.buffers.at(s.name), bases.at(s.name), i, s.member), result, bits); };
      auto next = write(index);
      if (enumerate && s.dynamicIndex && s.index <= 16) {
        next = write(ctx.bv_val(s.index,32));
        for (unsigned i = 0; i < s.index; ++i) next = z3::ite(index == ctx.bv_val(i,32),write(ctx.bv_val(i,32)),next);
      }
      memory = normalize(z3::ite(active, next, memory));
      break;
    }
    case Statement::Kind::Return:
      state.heap.finish(active);
      state.output = normalize(z3::ite(active, result, state.output));
      state.active = normalize(state.active && !active); break;
    default: throw std::invalid_argument("unmodeled control flow in buffer verification");
    }
  }
  }
  Execution execute(const Region &r, Environment scalars,
                    const Environment &bases, z3::expr memory) const {
    ranges = ctx.bool_val(true);
    State state{scalars,scalars,memory,ctx.bool_val(true),ctx.bv_val(0,32),ctx.int_val(0),{}, {}, {}, 0, verification_detail::HeapState(ctx)};
    // The outside partition must contain no self-call by the rank contract.
    // Reuse the checked expansion exit to prove that fact without expanding.
    if (outsideRecursionRange) state.recursionDepth=32;
    statements(r, r.statements, bases, state, ctx.bool_val(true));
    return {state.output, state.memory, ranges && state.heap.valid && !state.active, std::move(state.events),
            std::move(state.writes), std::move(state.conditions), std::move(state.heap.events)};
  }
};
}
static Verification verifyMemoryCase(const Region &original, const Region &candidate, unsigned timeoutMs,
                          bool successfulPrivateAllocations, bool expandRecursion,
                          int rankParameter=-1,int fixedRank=-1,unsigned maximumRank=0,
                          bool alignedCallSites=false) {
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
  const bool wordProjection = (hasRecords(original) || hasRecords(candidate) || original.memoryControl || candidate.memoryControl ||
    ((!original.orderedCalls && !candidate.orderedCalls) && (original.extendedMemory || candidate.extendedMemory))) && wordOnly(original) && wordOnly(candidate);
  const bool bytes = !wordProjection && (original.extendedMemory || candidate.extendedMemory);
  proof.strategy = std::string(bytes ? "shared-byte-memory" : "shared-word-memory") +
                   (wordProjection ? "/aligned-word-projection/blast-select-store/bv-sort-ac" : "") +
                   (original.orderedCalls || candidate.orderedCalls ? "/ordered-opaque-calls" : "") +
                   (!original.recursiveContract.empty() || !candidate.recursiveContract.empty() ?
                     (expandRecursion ? "/bounded-self-recursion/checked-body-expansion/exclude-self-call-events" : "/bounded-self-recursion/induction-on-entry-rank") : "") +
                   (original.ownedHeap || candidate.ownedHeap ? "/owned-heap-lifetime-initialization/coupled-allocation-outcomes" : "") +
                   (original.memoryControl || candidate.memoryControl ? "/guarded-effects/checked-loop-exits/expanded-memory-reads/bv-extract-prop/ctx-simplify" : "") +
                   (alignedCallSites ? "/lazy-smt" : "/simplify/blast-term-ite/simplify/smt");
  if (successfulPrivateAllocations) proof.strategy += "/assume-successful-private-allocations/exclude-allocator-events";
  proof.memoryAddressUnit = bytes ? "byte" : "word32";
  try {
    if (original.parameters.size() != candidate.parameters.size()) throw std::invalid_argument("parameter arity mismatch");
    if (original.littleEndian != candidate.littleEndian) throw std::invalid_argument("target endianness mismatch");
    z3::context ctx;
    Environment leftScalars, rightScalars, leftBases, rightBases;
    std::vector<z3::expr> inputs;
    std::vector<std::pair<std::string,z3::expr>> functionTargets;
    std::vector<std::pair<std::string,z3::expr>> streamTargets;
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
      if (original.streams.count(left)!=candidate.streams.count(right))
        throw std::invalid_argument("stream parameter kind mismatch");
      if (original.streams.count(left)) {
        const auto target=ctx.int_const(("stream_target_"+std::to_string(i)).c_str());
        leftBases.emplace(left,target);rightBases.emplace(right,target);streamTargets.emplace_back(left,target);continue;
      }
      const auto af=original.functionPointers.find(left), bf=candidate.functionPointers.find(right);
      if ((af==original.functionPointers.end())!=(bf==candidate.functionPointers.end()))
        throw std::invalid_argument("function-pointer parameter kind mismatch");
      if (af!=original.functionPointers.end()) {
        if (!sameCallSignature(original.calls.at(af->second),candidate.calls.at(bf->second)))
          throw std::invalid_argument("function-pointer contracts differ");
        const auto target=ctx.int_const(("function_target_"+std::to_string(i)).c_str());
        leftBases.emplace(left,target);rightBases.emplace(right,target);functionTargets.emplace_back(left,target);continue;
      }
      const auto a = original.buffers.find(left), b = candidate.buffers.find(right);
      if ((a == original.buffers.end()) != (b == candidate.buffers.end()))
        throw std::invalid_argument("scalar/pointer parameter kind mismatch");
      if (a == original.buffers.end()) {
        const auto input = ctx.bv_const(("input_" + std::to_string(i)).c_str(), 32);
        const auto value=int(i)==rankParameter && fixedRank>=0 ? ctx.bv_val(unsigned(fixedRank),32) : input;
        leftScalars.emplace(left, value); rightScalars.emplace(right, value); inputs.push_back(input);
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
    const MemoryModel model(ctx, bytes, original.littleEndian, wordProjection, original.memoryControl || candidate.memoryControl, expandRecursion,rankParameter>=0 && fixedRank<0,
      !original.streams.empty() && !candidate.streams.empty());
    const auto left = model.execute(original, leftScalars, leftBases, memory);
    const auto right = model.execute(candidate, rightScalars, rightBases, memory);
    proof.steps.insert(proof.steps.end(),model.rangeSelectProofs().begin(),model.rangeSelectProofs().end());
    if (alignedCallSites && left.events.size()!=right.events.size()) {
      proof.status="unsupported";proof.reason="static call-site counts differ";return proof;
    }
    if (alignedCallSites) proof.strategy+="/sufficient-static-call-site-correspondence";
    z3::params params(ctx); params.set("som", true); params.set("push_ite_bv", true);
    if (wordProjection) { params.set("blast_select_store", true); params.set("bv_sort_ac", true); }
    if (original.memoryControl || candidate.memoryControl) params.set("bv_extract_prop",true);
    const auto simplify = z3::with(z3::tactic(ctx, "simplify"), params);
    auto middle = z3::tactic(ctx, original.memoryControl || candidate.memoryControl ? "ctx-simplify" : "skip");
    // Keep ordinal-indexed stream results lazy in the sufficient site proof.
    // Eager ite blasting can multiply equivalent guarded array selections.
    auto solver = alignedCallSites ? z3::solver(ctx) :
      (simplify & z3::tactic(ctx, "blast-term-ite") & middle & simplify & z3::tactic(ctx, "smt")).mk_solver();
    solver.set("timeout", timeoutMs);
    if (rankParameter>=0) {
      const auto rank=ctx.bv_const(("input_"+std::to_string(rankParameter)).c_str(),32);
      solver.add(fixedRank>=0 ? rank==ctx.bv_val(unsigned(fixedRank),32) : z3::ugt(rank,ctx.bv_val(maximumRank,32)));
    }
    // Only equality of code identities is observable. N labels represent every
    // equality pattern among N valid function pointers, including aliases.
    for (const auto &[name,target]:functionTargets)
      solver.add(target>=ctx.int_val(1) && target<=ctx.int_val(unsigned(functionTargets.size())));
    for (const auto &[name,target]:streamTargets)
      solver.add(target>=ctx.int_val(1) && target<=ctx.int_val(unsigned(streamTargets.size())));
    if (successfulPrivateAllocations) for (unsigned i=0;i<std::max(left.heapEvents.size(),right.heapEvents.size());++i)
      solver.add(verification_detail::HeapState::outcome(ctx,ctx.int_val(i)));
    if (bytes) for (const auto &[name, buffer] : original.buffers)
      if (buffer.elementBits == 32 && !buffer.heap) solver.add(leftBases.at(name) % ctx.int_val(4) == 0);
    // File-scope definitions denote separate complete objects. A pointer to a
    // flat record may designate that same complete record, but cannot start at
    // its second field. Ordinary uint32 pointers still alias record members.
    // This is an object-layout condition, not a restrict/no-alias assumption.
    const unsigned unit = bytes ? 1 : 4;
    for (auto a = original.buffers.begin(); a != original.buffers.end(); ++a) {
      const auto &x = a->second;
      if (!x.minimumElements || x.heap) continue;
      for (auto b = std::next(a); b != original.buffers.end(); ++b) {
        const auto &y = b->second;
        if (!y.minimumElements || y.heap || (!x.persistent && !y.persistent)) continue;
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
    auto memoryMismatch = left.second != right.second;
    const auto storesOnly=[](const Region &r) {
      return std::all_of(r.calls.begin(),r.calls.end(),[](const auto &entry){return entry.second.standardStream;});
    };
    if ((original.memoryControl || candidate.memoryControl) && storesOnly(original) && storesOnly(candidate)) {
      // Both executions start with the same array and only guarded stores can
      // change it. Checking the union of all store addresses is therefore exact
      // whole-memory equality, not a sample of the caller's memory.
      memoryMismatch = ctx.bool_val(false);
      ExpandedReads reads;
      for (const auto *writes : {&left.writes, &right.writes})
        for (const auto &at : *writes)
          memoryMismatch = memoryMismatch || reads.select(left.second, at) != reads.select(right.second, at);
    }
    auto mismatch = !left.bounds || !right.bounds || left.first != right.first || memoryMismatch;
    auto count = [&](const auto &events) {
      auto total=ctx.int_val(0);
      for (const auto &event:events) total=total+z3::ite(event.active,ctx.int_val(1),ctx.int_val(0));
      return total;
    };
    if (!successfulPrivateAllocations) {
      mismatch=mismatch || count(left.heapEvents)!=count(right.heapEvents);
      // Active ordinals are unique and contiguous in each execution. Equal
      // lengths plus pairwise agreement at equal ordinals is exact sequence
      // equality even when a branch duplicates or moves an allocator site.
      for (const auto &a:left.heapEvents) for (const auto &b:right.heapEvents) {
        const auto aligned=(a.active && b.active && a.ordinal==b.ordinal).simplify(params);
        if (aligned.is_false()) continue;
        mismatch=mismatch || (aligned && (ctx.bool_val(a.callee!=b.callee) ||
          a.count!=b.count || a.object!=b.object || a.offset!=b.offset || a.publicMemory!=b.publicMemory));
      }
    }
    if (!alignedCallSites) mismatch=mismatch || count(left.events)!=count(right.events);
    for (unsigned i=0;i<left.events.size();++i) for (unsigned j=0;j<right.events.size();++j) {
      if (alignedCallSites && i!=j) continue;
      const auto &a=left.events[i], &b=right.events[j];
      if (alignedCallSites) mismatch=mismatch || a.active!=b.active || (a.active && a.ordinal!=b.ordinal);
      const auto aligned=(alignedCallSites ? a.active : a.active && b.active && a.ordinal==b.ordinal).simplify(params);
      if (aligned.is_false()) continue;
      const auto &ac = original.calls.at(a.callee), &bc = candidate.calls.at(b.callee);
      if (a.indirect!=b.indirect || (!a.indirect && a.callee!=b.callee) ||
          ac.recursive!=bc.recursive || !sameCallSignature(ac,bc) || a.arguments.size()!=b.arguments.size()) {
        mismatch=mismatch || aligned;continue;
      }
      auto different=a.target!=b.target || a.memory!=b.memory;
      for (unsigned j=0;j<a.arguments.size();++j) different=different || a.arguments[j]!=b.arguments[j];
      mismatch=mismatch || (aligned && different);
    }
    const auto domain = solver.assertions();
    solver.add(alignedCallSites ? mismatch.simplify(params) : mismatch);
    proof.obligation = solver.to_smt2();
    auto answer = z3::unknown;
    std::vector<z3::expr> predicates;
    if (original.memoryControl || candidate.memoryControl) for (const auto &condition : left.conditions) {
      // The simplifier canonicalizes ite(!p,a,b) as ite(p,b,a), so split its
      // underlying atom rather than a negated spelling that can disappear.
      const auto atom = condition.is_not() ? condition.arg(0) : condition;
      if (!atom.is_true() && !atom.is_false() && predicates.size() < 8 &&
          std::none_of(predicates.begin(),predicates.end(),[&](const auto &p) { return z3::eq(p,atom); }))
        predicates.push_back(atom);
    }
    if (predicates.empty() || alignedCallSites) answer = solver.check();
    else {
      // Exhaustive Boolean partitioning does not assume a branch outcome. Each
      // leaf retains its original path constraints, and substitution of that
      // path's predicates lets modular arithmetic normalize before bit blasting.
      // Splitting at most eight predicates bounds work; unsplit predicates stay
      // symbolic. All leaves must be UNSAT under one shared time budget.
      proof.strategy += "/exhaustive-predicate-partitions";
      struct Case { z3::expr path, mismatch; unsigned next; std::vector<z3::expr> predicates; };
      std::vector<Case> pending{{ctx.bool_val(true),mismatch,0,predicates}};
      const auto started = std::chrono::steady_clock::now();
      answer = z3::unsat;
      while (!pending.empty()) {
        const auto item = pending.back(); pending.pop_back();
        const auto remaining = item.mismatch.simplify(params);
        if (item.next < item.predicates.size() && !remaining.is_false() && !item.path.is_false()) {
          auto predicate=item.predicates[item.next].simplify(params);
          if (predicate.is_not()) predicate=predicate.arg(0);
          if (predicate.is_true() || predicate.is_false()) {
            pending.push_back({item.path,remaining,item.next+1,item.predicates});continue;
          }
          for (bool yes : {false,true}) {
            z3::expr_vector from(ctx),to(ctx); from.push_back(predicate); to.push_back(ctx.bool_val(yes));
            auto expression = remaining;
            const auto path = (item.path && (yes ? predicate : !predicate)).simplify(params);
            auto future=item.predicates;
            for (unsigned i=item.next+1;i<future.size();++i) future[i]=future[i].substitute(from,to).simplify(params);
            pending.push_back({path,expression.substitute(from,to),item.next+1,std::move(future)});
          }
          continue;
        }
        auto used = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-started).count();
        if (used >= timeoutMs) { answer = z3::unknown; proof.reason = "predicate partition budget exhausted"; break; }
        if (!item.path.is_true() && !remaining.is_false()) {
          // Reject an impossible partition before expanding its unrelated
          // arithmetic. A timeout here merely skips this optional pruning.
          z3::solver feasible(ctx); feasible.add(domain); feasible.add(item.path);
          feasible.set("timeout",std::min(100u,unsigned(timeoutMs-used)));
          if (feasible.check()==z3::unsat) {
            Verification step;step.strategy="unreachable-predicate-partition";
            step.obligation=feasible.to_smt2();step.status="proved-under-model";
            proof.steps.push_back(std::move(step));continue;
          }
        }
        used = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-started).count();
        if (used >= timeoutMs) { answer = z3::unknown; proof.reason = "predicate partition budget exhausted"; break; }
        solver.reset(); solver.add(domain); solver.add(item.path); solver.add(remaining);
        solver.set("timeout", unsigned(timeoutMs-used));
        Verification step; step.strategy = "exhaustive-Boolean-partition"; step.obligation = solver.to_smt2();
        const auto checked = solver.check();
        step.status = checked == z3::unsat ? "proved-under-model" : checked == z3::sat ? "counterexample" : "inconclusive";
        if (checked == z3::unknown) step.reason = solver.reason_unknown();
        proof.steps.push_back(std::move(step));
        if (checked != z3::unsat) { answer = checked; break; }
      }
    }
    if (answer == z3::unsat) proof.status = "proved-under-model";
    else if (answer == z3::unknown) { proof.status = "inconclusive"; if (proof.reason.empty()) proof.reason = solver.reason_unknown(); }
    else {
      proof.status = "counterexample";
      const auto model = solver.get_model();
      auto word = [&](const z3::expr &e) { return uint32_t(model.eval(e, true).get_numeral_uint64()); };
      for (const auto &input : inputs) proof.inputs.push_back(word(input));
      for (const auto &[name,target]:functionTargets)
        proof.localValues.emplace_back("function_target:"+name,uint32_t(model.eval(target,true).get_numeral_uint64()));
      for (const auto &[name,target]:streamTargets)
        proof.localValues.emplace_back("stream_target:"+name,uint32_t(model.eval(target,true).get_numeral_uint64()));
      proof.originalOutput = word(left.first); proof.candidateOutput = word(right.first);
      if (original.ownedHeap || candidate.ownedHeap) {
        proof.reason = "heap safety/initialization/cleanup, return, public memory or allocator trace obligation failed";
        for (unsigned i=0;i<std::max(left.heapEvents.size(),right.heapEvents.size());++i) {
          const auto name="heap_success_"+std::to_string(i);
          proof.localValues.emplace_back(name,model.eval(verification_detail::HeapState::outcome(ctx,ctx.int_val(i)),true).is_true() ? 1u : 0u);
        }
      }
      if (!left.events.empty() || !right.events.empty()) {
        proof.reason = "call footprint/recursion bound, return, final memory or ordered call trace obligation failed under shared environment choices";
        for (unsigned i = 0; i < std::max(left.events.size(), right.events.size()); ++i) {
          const auto name = "call_result_" + std::to_string(i);
          proof.localValues.emplace_back(name, word(callResult(ctx,ctx.int_val(i))));
        }
      }
      std::set<std::string> seen;
      for (const auto &[name, buffer] : original.buffers) {
        if (buffer.heap) continue;
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
Verification verifyMemory(const Region &original,const Region &candidate,unsigned timeoutMs,
                          bool successfulPrivateAllocations,bool expandRecursion) {
  if (!original.streams.empty() && !candidate.streams.empty() && timeoutMs>=4) {
    // Source transformations usually keep each static call site. Proving equal
    // guards and equal active calls at each index is sufficient for equal
    // executed traces, and avoids a quadratic ordinal-matching formula. It is
    // stronger than the contract: failure must fall back, never become a false
    // counterexample to the weaker executed-event comparison.
    const auto begin=std::chrono::steady_clock::now();
    auto fast=verifyMemoryCase(original,candidate,std::min(2000u,timeoutMs/3),successfulPrivateAllocations,false,-1,-1,0,true);
    fast.label="sufficient static-call-site correspondence";
    if (fast.status=="proved-under-model") return fast;
    const auto elapsed=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-begin).count();
    if (elapsed>=timeoutMs) {
      Verification result;result.status="inconclusive";result.reason="stream verification budget exhausted";
      result.priorAttempts.push_back(std::move(fast));return result;
    }
    auto complete=verifyMemoryCase(original,candidate,timeoutMs-unsigned(elapsed),successfulPrivateAllocations,false);
    complete.priorAttempts.push_back(std::move(fast));return complete;
  }
  if (!expandRecursion || (original.recursiveContract.empty() && candidate.recursiveContract.empty()))
    return verifyMemoryCase(original,candidate,timeoutMs,successfulPrivateAllocations,expandRecursion);
  const auto &r=original.recursiveContract.empty() ? candidate : original;
  const auto &contract=r.calls.at(r.recursiveContract);
  Verification result;
  result.strategy="complete-ranked-body-expansion/exhaustive-entry-rank-partitions/external-call-trace";
  // Keep this optional observer comparison small. The transformation proof
  // still supports ranked induction through 32; body expansion stops honestly.
  if (contract.maximumRank>8) {
    result.status="unsupported";result.reason="bounded-body comparison currently requires maximum_rank <= 8";return result;
  }
  for (const auto *region:{&original,&candidate}) if (!region->recursiveContract.empty()) {
    const auto &other=region->calls.at(region->recursiveContract);
    if (other.rankParameter!=contract.rankParameter || other.maximumRank!=contract.maximumRank) {
      result.status="unsupported";result.reason="recursive rank contracts differ";return result;
    }
  }
  const auto begin=std::chrono::steady_clock::now();
  auto stronger=verifyMemoryCase(original,candidate,timeoutMs,successfulPrivateAllocations,false);
  stronger.label="stronger inductive self-call-event comparison";
  if (stronger.status=="proved-under-model") {
    // Matching self-call events plus proved rank descent is an inductive proof
    // of the weaker body-observable contract too. Do not expand it needlessly.
    stronger.strategy+="/stronger-inductive-contract-implies-body-observations";
    stronger.reason="ranked induction proves the stronger self-call-event contract; complete body expansion is unnecessary";
    return stronger;
  }
  result.priorAttempts.push_back(stronger);
  for (unsigned i=0;i<=contract.maximumRank+1;++i) {
    const auto elapsed=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-begin).count();
    if (elapsed>=timeoutMs) { result.status="inconclusive";result.reason="rank partition verification budget exhausted";return result; }
    const bool outside=i>contract.maximumRank;
    auto proof=verifyMemoryCase(original,candidate,timeoutMs-unsigned(elapsed),successfulPrivateAllocations,true,
      int(contract.rankParameter),outside ? -1 : int(i),contract.maximumRank);
    proof.label=outside ? "entry rank above maximum" : "entry rank = "+std::to_string(i);
    if (proof.status!="proved-under-model") {
      proof.steps.insert(proof.steps.begin(),result.steps.begin(),result.steps.end());proof.priorAttempts.push_back(stronger);return proof;
    }
    result.steps.push_back(std::move(proof));
  }
  result.status="proved-under-model";
  result.reason="all entry ranks covered; complete self-call bodies compared; expansion exits, memory and external events checked";
  return result;
}
}
