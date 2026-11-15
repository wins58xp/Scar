#define SCAR_BLK_HDR 8
#define SCAR_BLK_HEAP 0x48454150u
#define SCAR_BLK_ARENA 0x4152454eu
// El encabezado: de dónde salió el bloque (4 bytes) y, para los del heap, su
// clase en el reciclador por hilo (pool_allocator.c), o -1 si es de malloc()
// directo (más grande que la clase máxima, o el pool apagado bajo ASan/TSan).
static inline void* scar_blk_tag(void* b, uint32_t origen, int clase) {
    ((uint32_t*)b)[0] = origen;
    ((int32_t*)b)[1] = (int32_t)clase;
    return (unsigned char*)b + SCAR_BLK_HDR;
}
// Un struct se pide y se suelta como un str: de la lista de libres de este
// hilo, sin ir al sistema. Quién lo suelta y cuándo
// no cambia: scar_blk_release() se llama en los mismos lugares.
static inline void* scar_blk_heap(size_t n) {
    size_t total = SCAR_BLK_HDR + n;
    int clase = scar_pool_clase(total);
    return scar_blk_tag(clase < 0 ? malloc(total) : scar_pool_tomar(clase), SCAR_BLK_HEAP, clase);
}
static inline int scar_blk_is_heap(const void* p) {
    return *(const uint32_t*)((const unsigned char*)p - SCAR_BLK_HDR) == SCAR_BLK_HEAP;
}
static inline void scar_blk_release(void* p) {
    if (p == NULL || !scar_blk_is_heap(p)) return;
    unsigned char *b = (unsigned char*)p - SCAR_BLK_HDR;
    int clase = (int)((int32_t*)b)[1];
    if (clase < 0) free(b);
    else scar_pool_dejar(b, clase);
}
