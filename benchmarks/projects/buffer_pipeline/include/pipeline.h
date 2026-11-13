#ifndef PIPELINE_H
#define PIPELINE_H
#include <stddef.h>
#include <stdint.h>
uint32_t adjust(uint32_t value);
void map_values(uint32_t *values, size_t count);
uint32_t reduce_values(const uint32_t *values, size_t count);
#endif
