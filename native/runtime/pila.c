/* La revisión de pila al entrar a cada fn de SCAR.

   Toda pila donde corre código de SCAR es de pilas.c: mide scar_pila_tam y
   empieza en un múltiplo de su tamaño, así que `sp & scar_pila_mascara` es lo
   que queda hasta el fondo, sin leer nada del hilo ni de la tarea (medido en el
   Ryzen: no se nota, ni en una fn chica recursiva). Si queda menos que
   SCAR_PILA_MARGEN, una recursión sin fin se convierte en un panic. El margen es
   para lo que corre sin revisión: el runtime en C, la libc y este mismo panic.
   Las llamadas a C de una extern fn corren en otra pila (pila_c.c).

   Las pilas no tienen página de guarda: la revisión la reemplaza, y así cada
   pila no parte su zona de memoria en dos (antes, 100.000 tareas pedían subir
   vm.max_map_count). */
#if defined(_WIN32) || (defined(SCAR_LIBRERIA) && !defined(SCAR_HAY_CAMBIO_PILA))
/* Windows: main y las tareas corren en las pilas del sistema (pilas.c no
   cambia de pila ahí). Una librería donde no se puede cambiar de pila: corre
   en la de quien llama. En los dos casos, sin revisión. */
#define SCAR_PILA_REVISAR() ((void)0)
#else
__attribute__((noinline, cold))
static void scar_pila_desborde(void) {
    @@PANIC@@("desbordamiento de pila: recursión demasiado profunda (¿falta un caso base?)");
    abort();
}
#define SCAR_PILA_MARGEN ((uintptr_t)64 << 10)
#if defined(__x86_64__)
#define SCAR_PILA_SP() ({ uintptr_t _sp; __asm__("mov %%rsp, %0" : "=r"(_sp)); _sp; })
#elif defined(__aarch64__)
#define SCAR_PILA_SP() ({ uintptr_t _sp; __asm__("mov %0, sp" : "=r"(_sp)); _sp; })
#else
#define SCAR_PILA_SP() ((uintptr_t)__builtin_frame_address(0))
#endif
#define SCAR_PILA_REVISAR() do { \
    if (__builtin_expect((SCAR_PILA_SP() & scar_pila_mascara) < SCAR_PILA_MARGEN, 0)) \
        scar_pila_desborde(); \
} while (0)
#endif
