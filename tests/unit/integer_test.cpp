#include "csrd/integer.hpp"
#include <array>
#include <iostream>
#include <stdexcept>

static void require(bool condition, const char *message) {
  if (!condition) throw std::runtime_error(message);
}
int main() {
  try {
    for (const auto seed : {UINT64_C(0), UINT64_C(42), UINT64_MAX}) {
      const auto codec=csrd::IntegerCodec::fromSeed(seed,"integer-unit");
      require(codec.multiplier()*codec.inverse()==1, "64-bit inverse invariant");
      for (unsigned bits : {1u,8u,16u,32u,64u}) {
        const auto mask=csrd::integerMask(bits);
        const std::array<uint64_t,8> values={0,1,mask,mask-1,mask>>1,(mask>>1)+1,UINT64_C(0x123456789abcdef0)&mask,UINT64_C(0xfedcba9876543210)&mask};
        for (auto x:values) for (auto y:values) {
          auto ex=codec.encode(x,bits),ey=codec.encode(y,bits);
          require(codec.decode(ex,bits)==x,"round trip");
          require(codec.decode(codec.add(ex,ey,bits),bits)==((x+y)&mask),"encoded sum");
          require(codec.decode(codec.subtract(ex,ey,bits),bits)==((x-y)&mask),"encoded difference");
          for(auto k:values) require(codec.decode(codec.scale(ex,k,bits),bits)==((k*x)&mask),"encoded scale");
          for(unsigned narrower:{1u,8u,16u,32u}) if(narrower<bits)
            require((ex&csrd::integerMask(narrower))==codec.encode(x,narrower),"direct encoded narrowing");
        }
      }
      // Exhaust every byte pair, including all wraparound points; this is an
      // exhaustive finite check for these selected codecs, not an all-codec proof.
      for(uint64_t x=0;x<256;++x) for(uint64_t y=0;y<256;++y) {
        auto ex=codec.encode(x,8),ey=codec.encode(y,8);
        require(codec.decode(codec.add(ex,ey,8),8)==((x+y)&255),"exhaustive byte sum");
        require(codec.decode(codec.subtract(ex,ey,8),8)==((x-y)&255),"exhaustive byte difference");
        require(codec.decode(codec.scale(ex,y,8),8)==((x*y)&255),"exhaustive byte scaling");
      }
    }
    bool rejected=false;try{csrd::IntegerCodec invalid(2,0);}catch(const std::invalid_argument&){rejected=true;}
    require(rejected,"even multiplier accepted");
    std::cout<<"PASS integer codec widths, inverse, encoded narrowing and 196608 exhaustive byte pairs\n";
  } catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 1;}
}
