#ifndef PROJECT_FACTOR
#error PROJECT_FACTOR must be supplied by the compile command
#endif
/* Freezing with a different compiler must not select a different branch. */
#ifdef __clang__
#define PROJECT_OFFSET 11u
#else
#define PROJECT_OFFSET 13u
#endif
