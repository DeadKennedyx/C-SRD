#include "csrd/integer.hpp"
#include <stdexcept>

namespace csrd {
uint64_t integerMask(unsigned bits) {
  if (!bits || bits > 64) throw std::invalid_argument("integer width must be 1..64");
  return bits == 64 ? UINT64_MAX : (UINT64_C(1) << bits)-1;
}
std::string integerLiteral(uint64_t n) { return std::to_string(n)+"ULL"; }
std::string integerTruncate(const std::string &x, unsigned bits) {
  return bits == 64 ? "("+x+")" : "(("+x+") & "+integerLiteral(integerMask(bits))+")";
}
IntegerCodec::IntegerCodec(uint64_t a, uint64_t b) : a_(a), b_(b), inverse_(1) {
  if (!(a & 1)) throw std::invalid_argument("integer affine multiplier must be odd");
  for (unsigned i=0;i<6;++i) inverse_ *= 2-a_*inverse_;
}
IntegerCodec IntegerCodec::fromSeed(uint64_t seed, const std::string &key) {
  uint64_t h=UINT64_C(14695981039346656037);
  for (unsigned char c:key) { h^=c; h*=UINT64_C(1099511628211); }
  uint64_t state=seed^h;
  auto next=[&]() {
    uint64_t z=(state+=UINT64_C(0x9e3779b97f4a7c15));
    z=(z^(z>>30))*UINT64_C(0xbf58476d1ce4e5b9);
    z=(z^(z>>27))*UINT64_C(0x94d049bb133111eb); return z^(z>>31);
  };
  auto a=next()|UINT64_C(1); if(a==1) a=3;
  return {a,next()};
}
uint64_t IntegerCodec::encode(uint64_t x,unsigned n) const { return (a_*x+b_)&integerMask(n); }
uint64_t IntegerCodec::decode(uint64_t x,unsigned n) const { return (inverse_*(x-b_))&integerMask(n); }
uint64_t IntegerCodec::add(uint64_t x,uint64_t y,unsigned n) const { return (x+y-b_)&integerMask(n); }
uint64_t IntegerCodec::subtract(uint64_t x,uint64_t y,unsigned n) const { return (x-y+b_)&integerMask(n); }
uint64_t IntegerCodec::scale(uint64_t x,uint64_t k,unsigned n) const { return (k*x+(1-k)*b_)&integerMask(n); }
std::string IntegerCodec::entry(const std::string &x,unsigned n) const {
  return !encoded() ? integerTruncate(x,n) : integerTruncate(integerLiteral(a_&integerMask(n))+"*("+x+")+"+integerLiteral(b_&integerMask(n)),n);
}
std::string IntegerCodec::exit(const std::string &x,unsigned n) const {
  return !encoded() ? integerTruncate(x,n) : integerTruncate(integerLiteral(inverse_&integerMask(n))+"*(("+x+")-"+integerLiteral(b_&integerMask(n))+")",n);
}
std::string IntegerCodec::binary(bool addition,const std::string &x,const std::string &y,unsigned n) const {
  return integerTruncate("("+x+")"+(addition?"+":"-")+"("+y+")"+(addition?"-":"+")+integerLiteral(b_&integerMask(n)),n);
}
std::string IntegerCodec::times(const std::string &x,uint64_t k,unsigned n) const {
  return integerTruncate(integerLiteral(k&integerMask(n))+"*("+x+")+"+integerLiteral(((1-k)*b_)&integerMask(n)),n);
}
std::string integerRestore(const std::string &raw,const IntegerType &t) {
  if (!t.isSigned) return "(("+t.spelling+")("+raw+"))";
  const auto sign=UINT64_C(1)<<(t.bits-1), max=sign-1;
  // In the negative branch mask-raw is in [0,max], so both casts are
  // representable. Under the declared two's-complement model, ~y == -1-y;
  // bitwise complement introduces no signed-overflow condition.
  return "(("+t.spelling+")(("+raw+")<="+integerLiteral(max)+" ? (long long)("+raw+") : "+
    "~(long long)("+integerLiteral(integerMask(t.bits))+"-("+raw+"))))";
}
} // namespace csrd
