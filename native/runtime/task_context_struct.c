typedef struct TaskContext {
    const char *name;
    atomic_int cancelled;
    atomic_int panicked;
    atomic_int joined;
    atomic_int completed;  // 1 solo si el cuerpo terminó SIN panic/cancelacion
    // Equivalente C de handle.thread.is_alive() del interprete
    // (_inject_chan, interpreter.py), que 'completed' NO cubre por si
    // solo -- 'completed' es 0 en panic/cancelacion aunque el thread ya
    // haya terminado. Se setea en el UNICO punto de salida del wrapper
    // (justo antes de 'return __scar_result', ver _gen_task_thread_wrapper),
    // asi que cubre las tres salidas (normal/panic/cancelacion) por igual.
    // inject_chan() lo lee bajo injected_lock.
    atomic_int finished;
    // Protege injected_slots para que dos
    // inject_chan() concurrentes, o un inject_chan() en carrera con el
    // 'finished' de arriba, no se pisen en silencio -- mismo criterio que
    // injected_lock ya usa el interprete (handle.injected_lock).
    pthread_mutex_t injected_lock;
    // Puntero type-erased a InjectedSlots_<task>
    // (struct generado por _gen_injected_slots_struct, uno por CADA
    // task con 'accepts' -- TaskContext es un unico tipo C compartido
    // por todas las tasks, así que no puede tener un campo tipado por
    // task). NULL para toda task sin 'accepts': no se reserva nada, costo
    // cero. _gen_spawn lo mallocea (calloc, todos
    // los slots arrancan NULL) solo para tasks con decl.accepts no
    // vacío; el cast de vuelta al tipo concreto lo hacen inject_chan()/
    // accept_chan(), que conocen la task destino en
    // el sitio de la llamada.
    void *injected_slots;
    char *panic_msg;  // en el heap, de este ctx; lo libera scar_ctx_free
    struct TaskContext *parent;
    struct TaskContext **children;
    int n_children;
    int cap_children;
    pthread_mutex_t children_mu;
    // Registro de en que condvar/mutex de Chan<T> esta bloqueado ESTE hilo ahora mismo,
    // si lo esta. NULL/NULL cuando no esta bloqueado en ningun chan. Lo
    // escribe el propio hilo (bajo `wait_lock`, ver scar_chan_send_*/recv_*)
    // justo antes de dormir en scar_cond_wait() SIN timeout -- no hay un
    // despertar periodico, asi que scar_cancel_notify() (mas abajo) necesita poder despertarlo a
    // proposito en cuanto lo cancelan, en vez de dejarlo dormido para
    // siempre. `wait_lock` es un mutex CHICO y propio de este ctx (no el
    // `mu` del canal): protege unicamente estos dos punteros contra la
    // carrera entre "el hilo se registra/desregistra" y "otro hilo lee el
    // puntero para despertarlo", sin necesidad de que quien cancela ya
    // sepa de antemano en que canal esta bloqueada su victima.
    pthread_mutex_t wait_lock;
    pthread_mutex_t *wait_mu;
    ScarCond *wait_cond;
    // Fin del hilo, para que join() espere en una condvar en vez de
    // sondear.
    // 'done' (bajo done_mu) pasa a 1 en el ultimo paso del wrapper
    // (scar_ctx_mark_done), despues de toda su limpieza.
    pthread_mutex_t done_mu;
    ScarCond done_cond;
    int done;
    // sleep() espera aca, interrumpible por scar_cancel_notify.
    pthread_mutex_t sleep_mu;
    ScarCond sleep_cond;
    pthread_t thread;
    sigjmp_buf panic_env;
    ScarArena arena;
    // Spawn sin join (fire-and-forget): como liberar __scar_result si nadie llama .join() sobre esta
    // tarea (ver scar_cancel_children, unico lugar que lo usa). NULL
    // para task 'void' (nada que liberar) o si nunca se asigna.
    void (*free_retval)(void*);
    uint64_t rand_semilla;  // semilla de rand() de esta task
    // Con tareas livianas (planificador.c) no hay pthread_t: el resultado lo
    // deja la fibra al terminar (scar_tarea_fibra_termino), y
    // 'fibra_terminada' dice que ya no corre (el gemelo de pthread_join).
    void *retval_fibra;
    atomic_int fibra_terminada;
} TaskContext;

typedef struct {
    TaskContext *ctx;
} TaskHandle;

// __scar_ctx: en ScarHilo (tls.c)
