#include "csrd/verification.hpp"
#include <z3++.h>
#include <chrono>
#include <map>
#include <set>
#include <stdexcept>

namespace csrd {
namespace {
using Environment=std::map<std::string,z3::expr>;
using K=IntegerExpr::Kind;
struct Value { z3::expr bits, defined; };
Value evaluate(z3::context &c,const IntegerExpr &e,const Environment &env) {
  const auto n=e.type.bits;
  if(e.kind==K::Constant) return {c.bv_val(e.value,n),c.bool_val(true)};
  if(e.kind==K::Reference) {
    const auto v=env.at(e.name);
    if(v.get_sort().bv_size()!=n) throw std::invalid_argument("integer reference width mismatch");
    return {v,c.bool_val(true)};
  }
  const auto a=evaluate(c,*e.left,env);
  if(e.kind==K::Convert) {
    if(e.type.isBool) return {z3::ite(a.bits!=0,c.bv_val(1,1),c.bv_val(0,1)),a.defined};
    const auto from=e.left->type.bits;
    auto v=a.bits;
    if(n<from) v=v.extract(n-1,0);
    else if(n>from) v=e.left->type.isSigned ? z3::sext(v,n-from) : z3::zext(v,n-from);
    return {v,a.defined};
  }
  if(e.kind==K::Select) {
    const auto b=evaluate(c,*e.right,env), d=evaluate(c,*e.third,env);
    return {z3::ite(a.bits!=0,b.bits,d.bits),a.defined && z3::ite(a.bits!=0,b.defined,d.defined)};
  }
  if(e.kind==K::LogicalNot) return {z3::ite(a.bits==0,c.bv_val(1,n),c.bv_val(0,n)),a.defined};
  // The fixed-width complement is (2^n-1)-x. Polynomial form lets the
  // simplifier cancel the representable signed-restoration expression.
  if(e.kind==K::BitNot) return {c.bv_val(integerMask(n),n)-a.bits,a.defined};
  if(e.kind==K::Negate) return {-a.bits,a.defined && (!e.type.isSigned || a.bits!=c.bv_val(UINT64_C(1)<<(n-1),n))};
  if(e.kind==K::ShiftLeft || e.kind==K::ShiftRight) {
    if(e.value>=n) throw std::invalid_argument("integer shift count out of range");
    const auto shift=c.bv_val(e.value,n);
    const auto countDefined=e.right ? evaluate(c,*e.right,env).defined : c.bool_val(true);
    if(e.kind==K::ShiftRight) return {e.type.isSigned ? z3::ashr(a.bits,shift) : z3::lshr(a.bits,shift),a.defined && countDefined};
    auto defined=a.defined && countDefined;
    if(e.type.isSigned) defined=defined && a.bits>=0 &&
      z3::ule(z3::shl(z3::zext(a.bits,n),c.bv_val(e.value,2*n)),c.bv_val(integerMask(n-1),2*n));
    return {z3::shl(a.bits,shift),defined};
  }
  const auto b=e.kind==K::Scale && !e.right ? Value{c.bv_val(e.value,n),c.bool_val(true)} : evaluate(c,*e.right,env);
  auto defined=a.defined && b.defined;
  z3::expr v=c.bv_val(0,n);
  switch(e.kind) {
  case K::Add: v=a.bits+b.bits; break;
  case K::Subtract: v=a.bits-b.bits; break;
  case K::Scale: v=a.bits*b.bits; break;
  case K::BitAnd: v=a.bits&b.bits; break;
  case K::BitOr: v=a.bits|b.bits; break;
  case K::BitXor: v=a.bits^b.bits; break;
  case K::Equal: case K::NotEqual: case K::Less: case K::LessEqual: case K::Greater: case K::GreaterEqual: {
    auto relation=a.bits==b.bits;
    if(e.kind==K::NotEqual) relation=a.bits!=b.bits;
    if(e.kind==K::Less) relation=e.left->type.isSigned ? a.bits<b.bits : z3::ult(a.bits,b.bits);
    if(e.kind==K::LessEqual) relation=e.left->type.isSigned ? a.bits<=b.bits : z3::ule(a.bits,b.bits);
    if(e.kind==K::Greater) relation=e.left->type.isSigned ? a.bits>b.bits : z3::ugt(a.bits,b.bits);
    if(e.kind==K::GreaterEqual) relation=e.left->type.isSigned ? a.bits>=b.bits : z3::uge(a.bits,b.bits);
    v=z3::ite(relation,c.bv_val(1,n),c.bv_val(0,n)); break;
  }
  default: throw std::invalid_argument("unmodeled typed integer operation");
  }
  if(e.type.isSigned && (e.kind==K::Add || e.kind==K::Subtract || e.kind==K::Scale)) {
    const auto x=z3::sext(a.bits,n), y=z3::sext(b.bits,n);
    const auto wide=e.kind==K::Add ? x+y : e.kind==K::Subtract ? x-y : x*y;
    defined=defined && wide==z3::sext(v,n);
  }
  return {v,defined};
}
struct State { Environment values; z3::expr defined; };
State executeRange(z3::context &c,const IntegerRegion &r,Environment env,unsigned begin,unsigned end) {
  auto defined=c.bool_val(true);
  z3::params simplification(c); simplification.set("som",true);
  for(unsigned i=begin;i<end;++i) {
    const auto &s=r.statements.at(i);
    const auto v=evaluate(c,*s.expression,env);
    if(v.bits.get_sort().bv_size()!=s.type.bits) throw std::invalid_argument("missing assignment conversion");
    env.insert_or_assign(s.name,v.bits.simplify(simplification));
    defined=(defined && v.defined).simplify(simplification);
  }
  return {std::move(env),defined};
}
State execute(z3::context &c,const IntegerRegion &r,Environment env) {
  return executeRange(c,r,std::move(env),0,unsigned(r.statements.size()));
}

using Clock=std::chrono::steady_clock;
unsigned remaining(Clock::time_point deadline) {
  const auto ms=std::chrono::duration_cast<std::chrono::milliseconds>(deadline-Clock::now()).count();
  return ms>0 ? unsigned(ms) : 0;
}
Verification composed(const IntegerRegion &original,const IntegerRegion &candidate,
  const std::vector<std::pair<std::string,IntegerType>> &inputs,
  const std::vector<std::pair<std::string,IntegerType>> &outputs,
  const IntegerWitness &witness,Clock::time_point deadline) {
  Verification proof; proof.strategy="typed-integer-inductive-fragments";
  proof.integerComposition=std::make_shared<IntegerWitness>(witness);
  try {
    if(!(witness.multiplier&1) || witness.checkpoints.size()!=original.statements.size()+1)
      throw std::invalid_argument("invalid integer invariant multiplier/checkpoint count");
    z3::context c; Environment initial;
    std::map<std::string,IntegerType> originalTypes,candidateTypes;
    for(unsigned i=0;i<inputs.size();++i) {
      initial.emplace(inputs[i].first,c.bv_const(("input_"+std::to_string(i)).c_str(),inputs[i].second.bits));
      originalTypes.emplace(inputs[i]);candidateTypes.emplace(inputs[i]);
    }
    for(const auto &s:original.statements) originalTypes.insert_or_assign(s.name,s.type);
    for(const auto &s:candidate.statements) candidateTypes.insert_or_assign(s.name,s.type);
    const auto whole=execute(c,original,initial);
    proof.definedInputs=whole.defined.to_string();
    auto budget=remaining(deadline);
    if(!budget) { proof.status="inconclusive";proof.reason="shared integer proof budget exhausted";return proof; }
    z3::solver domain(c);domain.set("timeout",budget);domain.add(whole.defined);
    proof.definedDomainObligation=domain.to_smt2();const auto inhabited=domain.check();
    if(inhabited!=z3::sat) {
      proof.status=inhabited==z3::unsat ? "unsupported" : "inconclusive";
      proof.reason=inhabited==z3::unsat ? "original integer frame has no defined inputs" : domain.reason_unknown();return proof;
    }
    const auto check=[&](const z3::expr &failure,const std::string &label) {
      Verification step;step.label=label;step.strategy="simplify/blast-term-ite/simplify/smt";
      const auto ms=remaining(deadline);
      if(!ms) {step.status="inconclusive";step.reason="shared integer proof budget exhausted";}
      else {
        z3::params p(c);p.set("som",true);p.set("push_ite_bv",true);
        auto solver=(z3::with(z3::tactic(c,"simplify"),p)&z3::tactic(c,"blast-term-ite")&
                     z3::with(z3::tactic(c,"simplify"),p)&z3::tactic(c,"smt")).mk_solver();
        solver.set("timeout",ms);solver.add(failure);step.obligation=solver.to_smt2();
        const auto checkPosition=step.obligation.rfind("(check-sat)");
        if(checkPosition!=std::string::npos) step.obligation.replace(checkPosition,11,
          "(check-sat-using (then (using-params simplify :som true :push_ite_bv true) blast-term-ite (using-params simplify :som true :push_ite_bv true) smt))");
        const auto answer=solver.check();
        if(answer==z3::unsat) step.status="proved-under-model";
        else if(answer==z3::sat) {
          step.status="local-counterexample";
          step.reason="proposed invariant fails for an abstract state; not necessarily a reachable original input";
        } else {step.status="inconclusive";step.reason=solver.reason_unknown();}
      }
      const bool ok=step.status=="proved-under-model";
      if(!ok) {proof.status="inconclusive";proof.reason=label+": "+step.status+" "+step.reason;}
      proof.steps.push_back(std::move(step));return ok;
    };
    const auto encoded=[&](const z3::expr &value) {
      const auto n=value.get_sort().bv_size();
      auto v=value*c.bv_val(witness.multiplier,n)+c.bv_val(witness.offset,n);
      return n<64 ? z3::zext(v,64-n) : v;
    };
    State left{initial,c.bool_val(true)},right{initial,c.bool_val(true)};
    unsigned sourceBegin=0,candidateBegin=0;
    for(unsigned i=0;i<witness.checkpoints.size();++i) {
      const auto &point=witness.checkpoints[i];
      if(point.sourceEnd!=i || point.candidateEnd>candidate.statements.size() ||
         (i ? point.candidateEnd<=candidateBegin : point.candidateEnd<candidateBegin))
        throw std::invalid_argument("nonmonotonic integer checkpoint coverage");
      left=executeRange(c,original,std::move(left.values),sourceBegin,point.sourceEnd);
      right=executeRange(c,candidate,std::move(right.values),candidateBegin,point.candidateEnd);
      if(point.encoded.size()!=left.values.size()) throw std::invalid_argument("integer checkpoint omits a source value");
      std::set<std::string> unique;
      auto mismatch=!right.defined;
      for(const auto &[id,value]:left.values) {
        const auto &name=point.encoded.at(id);
        if(!unique.insert(name).second || !right.values.count(name) || name.rfind("temporary@",0)!=0 ||
           candidateTypes.at(name).bits!=64 || candidateTypes.at(name).isSigned || candidateTypes.at(name).isBool)
          throw std::invalid_argument("integer invariant needs distinct initialized unsigned-64 temporaries");
        mismatch=mismatch || right.values.at(name)!=encoded(value);
      }
      if(!check(left.defined && mismatch,i ? "source-statement-"+std::to_string(i) : "entry-invariant")) return proof;
      // Forget all correlations except the relation just proved. This is an
      // overapproximation, never an assumption that unchecked code is correct.
      for(auto &[id,value]:left.values)
        value=c.bv_const(("source_"+std::to_string(i)+"_"+id).c_str(),originalTypes.at(id).bits);
      for(auto &[id,value]:right.values)
        value=c.bv_const(("candidate_"+std::to_string(i)+"_"+id).c_str(),candidateTypes.at(id).bits);
      for(const auto &[id,name]:point.encoded) right.values.insert_or_assign(name,encoded(left.values.at(id)));
      sourceBegin=point.sourceEnd;candidateBegin=point.candidateEnd;
    }
    right=executeRange(c,candidate,std::move(right.values),candidateBegin,unsigned(candidate.statements.size()));
    auto mismatch=!right.defined;
    for(const auto &[id,type]:outputs) {
      if(left.values.at(id).get_sort().bv_size()!=type.bits || right.values.at(id).get_sort().bv_size()!=type.bits)
        throw std::invalid_argument("integer output width mismatch");
      mismatch=mismatch || left.values.at(id)!=right.values.at(id);
    }
    if(!check(mismatch,"output-restoration")) return proof;
    proof.status="proved-under-model";
  } catch(const z3::exception &e) {proof.status="inconclusive";proof.reason=e.msg();}
    catch(const std::exception &e) {proof.status="unsupported";proof.reason=e.what();}
  return proof;
}
}
static Verification verifyIntegerWhole(const IntegerRegion &original,const IntegerRegion &candidate,
  const std::vector<std::pair<std::string,IntegerType>> &inputs,
  const std::vector<std::pair<std::string,IntegerType>> &outputs,unsigned timeoutMs) {
  Verification proof; proof.strategy="typed-integer-frame/definedness/smt";
  try {
    z3::context c; Environment env;
    for(unsigned i=0;i<inputs.size();++i)
      env.emplace(inputs[i].first,c.bv_const(("input_"+std::to_string(i)).c_str(),inputs[i].second.bits));
    const auto left=execute(c,original,env), right=execute(c,candidate,env);
    proof.definedInputs=left.defined.simplify().to_string();
    z3::solver domain(c); domain.set("timeout",timeoutMs); domain.add(left.defined);
    proof.definedDomainObligation=domain.to_smt2();
    const auto inhabited=domain.check();
    if(inhabited!=z3::sat) {
      proof.status=inhabited==z3::unsat ? "unsupported" : "inconclusive";
      proof.reason=inhabited==z3::unsat ? "original integer frame has no defined inputs" : domain.reason_unknown();
      return proof;
    }
    auto mismatch=!right.defined;
    for(const auto &[id,type]:outputs) {
      if(left.values.at(id).get_sort().bv_size()!=type.bits || right.values.at(id).get_sort().bv_size()!=type.bits)
        throw std::invalid_argument("integer output width mismatch");
      mismatch=mismatch || left.values.at(id)!=right.values.at(id);
    }
    z3::params p(c); p.set("som",true);
    auto solver=(z3::with(z3::tactic(c,"simplify"),p)&z3::tactic(c,"smt")).mk_solver();
    solver.set("timeout",timeoutMs); solver.add(left.defined && mismatch);
    proof.obligation=solver.to_smt2(); const auto answer=solver.check();
    if(answer==z3::unsat) proof.status="proved-under-model";
    else if(answer==z3::unknown) { proof.status="inconclusive"; proof.reason=solver.reason_unknown(); }
    else {
      proof.status="counterexample"; const auto model=solver.get_model();
      auto bits=[&](const z3::expr &v) { return std::to_string(model.eval(v,true).get_numeral_uint64()); };
      proof.candidateDefined=model.eval(right.defined,true).is_true();
      for(const auto &[id,type]:inputs) proof.integerInputs.push_back({id,bits(env.at(id)),type});
      for(const auto &[id,type]:outputs) proof.integerOutputs.push_back({id,bits(left.values.at(id)),bits(right.values.at(id)),type});
      proof.reason=proof.candidateDefined ? "integer scalar outputs differ on defined original inputs" : "candidate has undefined arithmetic on defined original inputs";
    }
  } catch(const z3::exception &e) { proof.status="inconclusive"; proof.reason=e.msg(); }
    catch(const std::exception &e) { proof.status="unsupported"; proof.reason=e.what(); }
  return proof;
}
Verification verifyIntegerFrame(const IntegerRegion &original,const IntegerRegion &candidate,
  const std::vector<std::pair<std::string,IntegerType>> &inputs,
  const std::vector<std::pair<std::string,IntegerType>> &outputs,unsigned timeoutMs,const IntegerWitness *witness) {
  if(!witness) return verifyIntegerWhole(original,candidate,inputs,outputs,timeoutMs);
  const auto deadline=Clock::now()+std::chrono::milliseconds(timeoutMs);
  auto local=composed(original,candidate,inputs,outputs,*witness,deadline);
  if(local.status=="proved-under-model") return local;
  // A failed hint is not a program counterexample. A whole-frame fallback may
  // establish one (or prove the artifact despite an inaccurate hint).
  const auto budget=remaining(deadline);
  if(!budget) return local;
  auto whole=verifyIntegerWhole(original,candidate,inputs,outputs,budget);
  whole.priorAttempts.push_back(std::move(local));return whole;
}
} // namespace csrd
