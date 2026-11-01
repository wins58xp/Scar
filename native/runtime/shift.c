static inline int32_t scar_shl(int32_t a, int64_t n) {
    if (n < 0 || n > 31) @@PANIC@@("corrimiento fuera de rango (%d << %lld)", a, (long long)n);
    return (int32_t)((uint32_t)a << n);
}
static inline int32_t scar_shr(int32_t a, int64_t n) {
    if (n < 0 || n > 31) @@PANIC@@("corrimiento fuera de rango (%d >> %lld)", a, (long long)n);
    return scar_sar_k(a, (int)n);
}

