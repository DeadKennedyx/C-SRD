#pragma once
#include "symbolic.hpp"
#include <stdexcept>

namespace csrd::verification_detail {
// Owned objects have independent storage and cannot escape. Object tokens are
// provenance identities, not numerical addresses. Only null tests are exposed.
class HeapState {
public:
  struct Pointer { z3::expr object, offset; };
  struct Event { std::string callee; z3::expr active, ordinal, count, object, offset, publicMemory; };
  static z3::expr outcome(z3::context &ctx, const z3::expr &ordinal) {
    return z3::select(ctx.constant("heap_outcomes",ctx.array_sort(ctx.int_sort(),ctx.bool_sort())),ordinal);
  }
private:
  struct Object { z3::expr capacity, memory, initialized, live, identity; };
  z3::context &ctx;
  std::map<std::string, Pointer> pointers;
  std::vector<Object> objects;
  z3::expr eventCount;
  z3::params normalization;
  z3::expr norm(const z3::expr &e) const { return e.simplify(normalization); }
  z3::expr zero() const { return ctx.bv_val(0,32); }
  z3::expr selected(const Pointer &p, unsigned i) const { return p.object == ctx.int_val(i+1); }
  z3::expr live(const Pointer &p) const {
    auto valid = p.object == ctx.int_val(0);
    for (unsigned i=0;i<objects.size();++i) valid = valid || (selected(p,i) && objects[i].live);
    return norm(valid);
  }
  z3::expr identity(const Pointer &p) const {
    auto result=ctx.int_val(0);
    for (unsigned i=0;i<objects.size();++i)
      result=z3::ite(selected(p,i),objects[i].identity,result);
    return norm(result);
  }
  void require(const z3::expr &active, const z3::expr &condition) {
    valid = norm(valid && z3::implies(active,condition));
  }
  void set(const std::string &name, const Pointer &p, const z3::expr &active, bool declare) {
    if (declare) pointers.insert_or_assign(name,p);
    else {
      const auto previous=pointers.at(name);
      pointers.insert_or_assign(name,Pointer{norm(z3::ite(active,p.object,previous.object)),
                                           norm(z3::ite(active,p.offset,previous.offset))});
    }
  }
  Pointer checked(const std::string &name, const z3::expr &active) {
    const auto p = name.empty() ? Pointer{ctx.int_val(0),zero()} : pointers.at(name);
    require(active,live(p)); return p;
  }
public:
  z3::expr valid;
  std::vector<Event> events;
  explicit HeapState(z3::context &c) : ctx(c), eventCount(c.int_val(0)), normalization(c), valid(c.bool_val(true)) {
    normalization.set("som",true); normalization.set("push_ite_bv",true);
    normalization.set("blast_select_store",true); normalization.set("bv_sort_ac",true);
  }
  z3::expr nonnull(const std::string &name, const z3::expr &active) {
    return checked(name,active).object != ctx.int_val(0);
  }
  void bind(const Statement &s, const z3::expr &step, const z3::expr &active) {
    auto p=checked(s.pointer,active);
    if (s.pointerArithmetic) {
      const auto offset=norm(p.offset+step);
      auto inObject=ctx.bool_val(false);
      for (unsigned i=0;i<objects.size();++i)
        inObject=inObject || (selected(p,i) && objects[i].live && z3::ule(offset,objects[i].capacity));
      require(active,inObject && z3::uge(offset,p.offset)); // Includes one-past formation.
      p.offset=offset;
    }
    set(s.name,p,active,s.declaresCallResult);
  }
  z3::expr load(const std::string &name, const z3::expr &index, const z3::expr &active) {
    const auto p=checked(name,active); const auto at=norm(p.offset+index);
    auto allowed=ctx.bool_val(false), result=zero();
    for (unsigned i=0;i<objects.size();++i) {
      const auto &o=objects[i];
      allowed=allowed || (selected(p,i) && o.live && z3::ult(at,o.capacity) && z3::select(o.initialized,at));
      result=z3::ite(selected(p,i),z3::select(o.memory,at),result);
    }
    require(active,allowed && z3::uge(at,p.offset)); return norm(result);
  }
  void store(const std::string &name, const z3::expr &index, const z3::expr &value, const z3::expr &active) {
    const auto p=checked(name,active); const auto at=norm(p.offset+index);
    auto allowed=ctx.bool_val(false);
    for (unsigned i=0;i<objects.size();++i) {
      auto &o=objects[i]; const auto write=norm(active && selected(p,i));
      allowed=allowed || (selected(p,i) && o.live && z3::ult(at,o.capacity));
      o.memory=norm(z3::ite(write,z3::store(o.memory,at,value),o.memory));
      o.initialized=norm(z3::ite(write,z3::store(o.initialized,at,ctx.bool_val(true)),o.initialized));
    }
    require(active,allowed && z3::uge(at,p.offset));
  }
  void allocation(const Statement &s, const z3::expr &count, const z3::expr &active,
                  const z3::expr &publicMemory) {
    if (events.size() >= 64) throw std::invalid_argument("heap model exceeds 64 expanded allocator events");
    const bool release=s.kind==Statement::Kind::Release, resize=s.callee=="realloc", zeroed=s.callee=="calloc";
    const auto p=release || resize ? checked(s.pointer,active) : Pointer{ctx.int_val(0),zero()};
    if (release || resize) require(active,p.offset==zero());
    if (!release) require(active,z3::ule(count,ctx.bv_val(32,32)));
    // C11 zero-size realloc has implementation-defined behavior; require a
    // positive request on every executed path instead of choosing a behavior.
    if (resize) require(active,count!=zero());
    const auto id=std::to_string(events.size());
    // Couple environment choices by executed event order, not by the number
    // of AST sites visited. Mutually exclusive branch copies may have different
    // static positions while denoting exactly the same allocator interaction.
    const auto ordinal=eventCount;
    events.push_back({s.callee+(s.callocSwapped ? ":swapped" : ""),active,ordinal,count,identity(p),p.offset,publicMemory});
    eventCount=norm(eventCount+z3::ite(active,ctx.int_val(1),ctx.int_val(0)));
    if (release) {
      for (unsigned i=0;i<objects.size();++i) objects[i].live=norm(objects[i].live && !(active && selected(p,i)));
      return;
    }
    const auto success=outcome(ctx,ordinal);
    const auto fresh=ctx.int_val(unsigned(objects.size()+1));
    auto contents=ctx.constant(("heap_uninitialized_"+id).c_str(),ctx.array_sort(ctx.bv_sort(32),ctx.bv_sort(32)));
    auto initialized=z3::const_array(ctx.bv_sort(32),ctx.bool_val(false));
    if (zeroed) {
      contents=z3::const_array(ctx.bv_sort(32),zero());
      initialized=z3::const_array(ctx.bv_sort(32),ctx.bool_val(true));
    }
    if (resize) for (unsigned i=0;i<objects.size();++i) {
      auto &o=objects[i];
      for (unsigned k=0;k<32;++k) {
        const auto at=ctx.bv_val(k,32), copy=norm(selected(p,i) && z3::ult(at,o.capacity));
        contents=norm(z3::store(contents,at,z3::ite(copy,z3::select(o.memory,at),z3::select(contents,at))));
        initialized=norm(z3::store(initialized,at,z3::ite(copy,z3::select(o.initialized,at),z3::select(initialized,at))));
      }
      o.live=norm(o.live && !(active && success && selected(p,i)));
    }
    objects.push_back({count,contents,initialized,norm(active && success),norm(ordinal+ctx.int_val(1))});
    set(s.name,Pointer{norm(z3::ite(success,fresh,ctx.int_val(0))),zero()},active,s.declaresCallResult);
  }
  void finish(const z3::expr &active) {
    // The first owned-heap contract requires complete cleanup on every return.
    // This detects source leaks too; it is not an assumption hiding a leak.
    for (const auto &o:objects) require(active,!o.live);
  }
};
}
