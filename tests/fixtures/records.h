#ifndef CSRD_RECORDS_H
#define CSRD_RECORDS_H
#include <stdint.h>
struct csrd_pair { uint32_t first; uint32_t second; };
union csrd_word { uint32_t value; uint32_t alternate; };
extern uint32_t csrd_counter;
extern struct csrd_pair csrd_state;
extern union csrd_word csrd_mode;
#endif
