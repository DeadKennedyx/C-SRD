#include <stdint.h>
/* Population count of the low byte; higher input bits are irrelevant. */
uint32_t popcount8(uint32_t x) { unsigned int csrd_value_0 = ((x) & (255u)); unsigned int csrd_value_1 = ((csrd_value_0) >> (0u)); unsigned int csrd_value_2 = ((csrd_value_1) & (1u)); unsigned int csrd_value_3 = ((0u) + (csrd_value_2)); unsigned int csrd_value_4 = ((csrd_value_0) >> (1u)); unsigned int csrd_value_5 = ((csrd_value_4) & (1u)); unsigned int csrd_value_6 = ((csrd_value_3) + (csrd_value_5)); unsigned int csrd_value_7 = ((csrd_value_0) >> (2u)); unsigned int csrd_value_8 = ((csrd_value_7) & (1u)); unsigned int csrd_value_9 = ((csrd_value_6) + (csrd_value_8)); unsigned int csrd_value_10 = ((csrd_value_0) >> (3u)); unsigned int csrd_value_11 = ((csrd_value_10) & (1u)); unsigned int csrd_value_12 = ((csrd_value_9) + (csrd_value_11)); unsigned int csrd_value_13 = ((csrd_value_0) >> (4u)); unsigned int csrd_value_14 = ((csrd_value_13) & (1u)); unsigned int csrd_value_15 = ((csrd_value_12) + (csrd_value_14)); unsigned int csrd_value_16 = ((csrd_value_0) >> (5u)); unsigned int csrd_value_17 = ((csrd_value_16) & (1u)); unsigned int csrd_value_18 = ((csrd_value_15) + (csrd_value_17)); unsigned int csrd_value_19 = ((csrd_value_0) >> (6u)); unsigned int csrd_value_20 = ((csrd_value_19) & (1u)); unsigned int csrd_value_21 = ((csrd_value_18) + (csrd_value_20)); unsigned int csrd_value_22 = ((csrd_value_0) >> (7u)); unsigned int csrd_value_23 = ((csrd_value_22) & (1u)); unsigned int csrd_value_24 = ((csrd_value_21) + (csrd_value_23)); return csrd_value_24;







}
