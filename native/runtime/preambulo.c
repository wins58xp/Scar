#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdarg.h>
#include <malloc.h>
#if defined(__SANITIZE_ADDRESS__)
static volatile size_t scar_san_sink;
static inline const char *scar_san_str(const char *s) {
    if (s) scar_san_sink = strlen(s);
    return s;
}
#define SCAR_SAN_STR(s) scar_san_str(s)
#else
#define SCAR_SAN_STR(s) (s)
#endif

