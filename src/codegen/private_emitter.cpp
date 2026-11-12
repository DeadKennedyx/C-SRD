#include "csrd/private_regions.hpp"
#include <algorithm>
#include <functional>
#include <map>
#include <stdexcept>

namespace csrd {
Emission emitPrivateFrame(PrivateFrame &frame,const IntegerCodec &rep,const std::set<std::string> &reserved) {
  Emission out; frame.emittedDeclarations.clear();
  frame.witness={rep.multiplier(),rep.offset(),{}};
  auto names=reserved; unsigned serial=0;
  std::map<std::string,std::string> values;
  auto fresh=[&]() {
    std::string n;
    do { n="csrd_frame_"+std::to_string(frame.begin)+"_"+std::to_string(serial++); } while(!names.insert(n).second);
    return n;
  };
  auto append=[&](const std::string &s) { if(!out.body.empty()) out.body+=" "; out.body+=s; };
  auto temporary=[&](const std::string &value) {
    const auto n=fresh();append("unsigned long long "+n+" = "+value+"; (void)"+n+";");++out.temporaries;return n;
  };
  auto encode=[&](const std::string &value,unsigned bits,bool boundary) {
    if(rep.encoded()) { ++out.encodings; if(boundary) ++out.boundaryConversions;else ++out.internalConversions; }
    return rep.entry(value,bits);
  };
  auto decode=[&](const std::string &value,unsigned bits,bool boundary) {
    if(rep.encoded()) { ++out.decodings; if(boundary) ++out.boundaryConversions;else ++out.internalConversions; }
    return temporary(rep.exit(value,bits));
  };
  std::function<std::string(const IntegerExpr &)> expression=[&](const IntegerExpr &e)->std::string {
    using K=IntegerExpr::Kind;
    const auto n=e.type.bits;
    if(e.kind==K::Constant) return integerLiteral(rep.encode(e.value,n));
    if(e.kind==K::Reference) return values.at(e.name);
    const auto left=expression(*e.left);
    if(e.kind==K::Convert) {
      if(!e.type.isBool && n<=e.left->type.bits) return n==e.left->type.bits ? left : temporary(integerTruncate(left,n));
      auto raw=decode(left,e.left->type.bits,false);
      if(e.type.isBool) raw="("+raw+" != 0ULL)";
      else if(e.left->type.isSigned && n>e.left->type.bits) {
        raw="(unsigned long long)"+integerRestore(raw,e.left->type);
      }
      return temporary(encode(raw,n,false));
    }
    ++out.operations;
    if(e.kind==K::Add || e.kind==K::Subtract || e.kind==K::Scale || e.kind==K::Negate) {
      if(rep.encoded()) ++out.encodedOperations;else ++out.ordinaryIntermediates;
      out.estimatedOperations+=2;
      if(e.kind==K::Scale || e.kind==K::Negate) return temporary(rep.times(left,e.kind==K::Negate ? UINT64_MAX : e.value,n));
      const auto right=expression(*e.right);
      return temporary(rep.binary(e.kind==K::Add,left,right,n));
    }
    if(e.kind==K::Select) {
      // Generated branch arithmetic is total and unsigned, so eager evaluation
      // is safe. The original model retains conditional definedness.
      const auto condition=decode(left,e.left->type.bits,false);
      const auto yes=expression(*e.right), no=expression(*e.third);
      ++out.ordinaryIntermediates;
      return temporary("("+condition+" ? "+yes+" : "+no+")");
    }
    const auto a=decode(left,e.left->type.bits,false);
    ++out.ordinaryIntermediates;
    std::string ordinary;
    if(e.kind==K::BitNot) ordinary="~("+a+")";
    else if(e.kind==K::LogicalNot) ordinary="!("+a+")";
    else if(e.kind==K::ShiftLeft) ordinary="("+a+" << "+std::to_string(e.value)+"u)";
    else if(e.kind==K::ShiftRight) {
      ordinary="("+a+" >> "+std::to_string(e.value)+"u)";
      if(e.type.isSigned && e.value) {
        ordinary="((unsigned long long)("+integerRestore(a,e.type)+" >> "+std::to_string(e.value)+"u))";
      }
    } else {
      const auto b=decode(expression(*e.right),e.right->type.bits,false);
      std::string symbol;
      switch(e.kind) {
      case K::BitAnd:symbol="&";break;case K::BitOr:symbol="|";break;case K::BitXor:symbol="^";break;
      case K::Equal:symbol="==";break;case K::NotEqual:symbol="!=";break;
      case K::Less:symbol="<";break;case K::LessEqual:symbol="<=";break;
      case K::Greater:symbol=">";break;case K::GreaterEqual:symbol=">=";break;
      default:throw std::invalid_argument("unmodeled private integer emission");
      }
      const bool ordered=e.kind==K::Less || e.kind==K::LessEqual || e.kind==K::Greater || e.kind==K::GreaterEqual;
      if(ordered && e.left->type.isSigned) {
        const auto sign=integerLiteral(UINT64_C(1)<<(e.left->type.bits-1));
        ordinary="(("+a+" ^ "+sign+") "+symbol+" ("+b+" ^ "+sign+"))";
      } else ordinary="("+a+" "+symbol+" "+b+")";
    }
    return temporary(encode(ordinary,n,false));
  };
  const std::set<std::string> declarations(frame.declarations.begin(),frame.declarations.end());
  out.body=declarations.empty() ? "{" : "";
  append("_Static_assert((unsigned char)~0u == 255u && ~0 == -1 && ~0L == -1L && ~0LL == -1LL && (-1 >> 1) == -1 && sizeof(short)==2 && sizeof(int)==4 && sizeof(long)=="+
    std::to_string(frame.longBits/8)+" && sizeof(long long)==8 && (((char)-1 < 0)=="+
    std::to_string(frame.plainCharSigned ? 1 : 0)+"), \"C-SRD integer data model mismatch\");");
  std::string anchor;
  for(const auto &id:frame.inputs) {
    const auto &b=frame.bindings.at(id);
    anchor=temporary(encode("(unsigned long long)("+b.name+")",b.type.bits,true));
    values.emplace(id,anchor);
  }
  frame.witness.checkpoints.push_back({0,0,anchor,values});
  unsigned sourceEnd=0;
  for(const auto &s:frame.original->statements) {
    // A unique copy gives every source step an unambiguous actual-C cut,
    // including constant/reference-only assignments. Optimizers may remove it.
    const auto value=temporary(expression(*s.expression));
    values.insert_or_assign(s.name,value);
    frame.witness.checkpoints.push_back({++sourceEnd,0,value,values});
  }
  std::map<std::string,std::string> restored;
  for(const auto &id:frame.outputs) {
    const auto &b=frame.bindings.at(id);
    const auto raw=decode(values.at(id),b.type.bits,true);
    restored.emplace(id,integerRestore(raw,b.type));
  }
  for(const auto &id:frame.outputs) if(!declarations.count(id)) append(frame.bindings.at(id).name+" = "+restored.at(id)+";");
  for(const auto &id:frame.declarations) {
    const auto &b=frame.bindings.at(id);
    append((b.registerStorage ? "register " : "")+b.type.spelling+" ");
    frame.emittedDeclarations.emplace(id,unsigned(out.body.size()));
    out.body+=b.name+" = "+restored.at(id)+"; (void)"+b.name+";";
  }
  const auto lines=std::count(frame.originalText.begin(),frame.originalText.end(),'\n');
  if(declarations.empty()) out.body+=std::string(lines,'\n')+"}";
  else out.body.insert(out.body.size()-1,std::string(lines,'\n'));
  return out;
}
} // namespace csrd
