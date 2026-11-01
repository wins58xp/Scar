// arena de Region: lista enlazada de bloques con un
// puntero de asignacion tipo "bump" dentro de cada bloque. Una por
// TaskContext -- solo el thread dueño asigna y solo el thread dueño
// libera, en su propio cleanup, asi que no hace falta locking.
typedef struct ScarArenaBlock {
    struct ScarArenaBlock *next;
    size_t size;
    size_t used;
    unsigned char data[];
} ScarArenaBlock;

typedef struct {
    ScarArenaBlock *head;
} ScarArena;

static ScarArenaBlock* scar_arena_block_new(size_t min_size) {
    size_t size = min_size < 4096 ? 4096 : min_size;
    ScarArenaBlock *b = malloc(sizeof(ScarArenaBlock) + size);
    b->next = NULL;
    b->size = size;
    b->used = 0;
    return b;
}

static void scar_arena_init(ScarArena *arena) {
    arena->head = scar_arena_block_new(4096);
}

static void* scar_arena_alloc(ScarArena *arena, size_t n) {
    // alineado a 8 bytes: ningún tipo de SCAR pide más.
    size_t aligned = (n + 7) & ~((size_t)7);
    ScarArenaBlock *b = arena->head;
    if (b->used + aligned > b->size) {
        size_t new_size = b->size * 2;
        if (new_size < aligned) new_size = aligned;
        ScarArenaBlock *nb = scar_arena_block_new(new_size);
        nb->next = b;
        arena->head = nb;
        b = nb;
    }
    void *ptr = b->data + b->used;
    b->used += aligned;
    return ptr;
}

// libera TODOS los bloques de una sola pasada -- el reemplazo real
// de N free() puntuales por una liberacion en bloque.
static void scar_arena_free(ScarArena *arena) {
    ScarArenaBlock *b = arena->head;
    while (b) {
        ScarArenaBlock *next = b->next;
        free(b);
        b = next;
    }
    arena->head = NULL;
}
