#include <stdint.h>
/* Population count of the low byte; higher input bits are irrelevant. */
uint32_t popcount8(uint32_t x) { unsigned int csrd_value_0 = ((x) ^ 4134625211u); unsigned int csrd_value_1 = (((csrd_value_0) & (4134625092u)) ^ (((csrd_value_0) ^ (4134625092u)) & 4134625211u)); unsigned int csrd_value_2 = (((csrd_value_1) >> 1u) ^ 2370433126u); unsigned int csrd_value_3 = (((csrd_value_2) & (4134625262u)) ^ (((csrd_value_2) ^ (4134625262u)) & 4134625211u)); unsigned int csrd_value_4 = ((csrd_value_1) ^ 4134625211u); unsigned int csrd_value_5 = ((csrd_value_3) ^ 4134625211u); unsigned int csrd_value_6 = ((csrd_value_4) - (csrd_value_5)); unsigned int csrd_value_7 = ((csrd_value_6) ^ 4134625211u); unsigned int csrd_value_8 = (((csrd_value_7) & (4134625160u)) ^ (((csrd_value_7) ^ (4134625160u)) & 4134625211u)); unsigned int csrd_value_9 = (((csrd_value_7) >> 2u) ^ 3421309013u); unsigned int csrd_value_10 = (((csrd_value_9) & (4134625160u)) ^ (((csrd_value_9) ^ (4134625160u)) & 4134625211u)); unsigned int csrd_value_11 = ((csrd_value_8) ^ 4134625211u); unsigned int csrd_value_12 = ((csrd_value_10) ^ 4134625211u); unsigned int csrd_value_13 = ((csrd_value_11) + (csrd_value_12)); unsigned int csrd_value_14 = ((csrd_value_13) >> (4u)); unsigned int csrd_value_15 = ((csrd_value_13) + (csrd_value_14)); unsigned int csrd_value_16 = ((csrd_value_15) & (15u)); return csrd_value_16;







}
