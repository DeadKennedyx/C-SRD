#include <stdint.h>

uint32_t calculate(uint32_t x, uint32_t y)
{ unsigned int csrd_value_0 = ((1789947473u * (x)) + 1549411197u); unsigned int csrd_value_1 = ((1789947473u * (y)) + 1549411197u); unsigned int csrd_value_2 = (((csrd_value_0) + (csrd_value_1)) - 1549411197u); unsigned int csrd_value_3 = ((3u * (csrd_value_2)) + 1196144902u); unsigned int csrd_value_4 = (((csrd_value_3) + (4058964216u)) - 1549411197u); unsigned int csrd_value_5 = (846699185u * ((csrd_value_4) - 1549411197u)); return csrd_value_5;


}
