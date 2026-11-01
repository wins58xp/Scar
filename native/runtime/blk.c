#define SCAR_BLK_HDR 8
#define SCAR_BLK_HEAP 0x48454150u
#define SCAR_BLK_ARENA 0x4152454eu
static inline void* scar_blk_tag(void* b, uint32_t origen) {
    *(uint32_t*)b = origen;
    return (unsigned char*)b + SCAR_BLK_HDR;
}
static inline void* scar_blk_heap(size_t n) {
    return scar_blk_tag(malloc(SCAR_BLK_HDR + n), SCAR_BLK_HEAP);
}
static inline int scar_blk_is_heap(const void* p) {
    return *(const uint32_t*)((const unsigned char*)p - SCAR_BLK_HDR) == SCAR_BLK_HEAP;
}
static inline void scar_blk_release(void* p) {
    if (p && scar_blk_is_heap(p)) free((unsigned char*)p - SCAR_BLK_HDR);
}
