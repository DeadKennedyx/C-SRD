#include <stdint.h>
/* Population count of the low byte; higher input bits are irrelevant. */
uint32_t popcount8(uint32_t x) { unsigned int csrd_value_0 = ((x) & (255u)); unsigned int csrd_value_1 = ((csrd_value_0) >> (1u)); unsigned int csrd_value_2 = ((csrd_value_1) & (85u)); unsigned int csrd_value_3 = ((csrd_value_0) - (csrd_value_2)); unsigned int csrd_value_4 = ((csrd_value_3) & (51u)); unsigned int csrd_value_5 = ((csrd_value_3) >> (2u)); unsigned int csrd_value_6 = ((csrd_value_5) & (51u)); unsigned int csrd_value_7 = ((csrd_value_4) + (csrd_value_6)); unsigned int csrd_value_8 = ((csrd_value_7) >> (4u)); unsigned int csrd_value_9 = ((csrd_value_7) + (csrd_value_8)); unsigned int csrd_value_10 = ((csrd_value_9) & (15u)); return csrd_value_10;







}
