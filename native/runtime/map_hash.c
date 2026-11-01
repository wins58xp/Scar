static uint64_t scar_hash_i32(int32_t k) {
    uint64_t x = (uint64_t)(uint32_t)k;
    x ^= x >> 16; x *= 0x85ebca6bULL;
    x ^= x >> 13; x *= 0xc2b2ae35ULL;
    x ^= x >> 16;
    return x;
}

static uint64_t scar_hash_i64(int64_t k) {
    uint64_t x = (uint64_t)k;  // finalizador de splitmix64
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

static uint64_t scar_hash_f64(double k) {
    uint64_t x;
    memcpy(&x, &k, sizeof(x));
    x ^= x >> 33; x *= 0xff51afd7ed558ccdULL;
    x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ULL;
    x ^= x >> 33;
    return x;
}

static uint64_t scar_hash_bool(bool k) {
    return k ? 1u : 0u;
}

static uint64_t scar_hash_str(const char* k) {
    uint64_t h = 1469598103934665603ULL;  // FNV-1a offset basis
    for (; *k; k++) {
        h ^= (unsigned char)*k;
        h *= 1099511628211ULL;  // FNV-1a prime
    }
    return h;
}
