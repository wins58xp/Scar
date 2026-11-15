"""Mixin Plantillas de Codegen (paso C8): el texto de C de las funciones de
Chan, Vec y Map, por pieza (new, send/push, recv/get, free...). Cada pieza
devuelve su texto; _chan_c_type, _vec_c_type y _map_c_type (TiposC) las suman.
"""

from types_ import T_I32

from .comun import panic_c


class Plantillas:
    def _chan_c_new_send(self, c_name, suf, impl_name, send_cancel_line, inner_c,
                         node_name, inner_is_struct, node_value_stmt, send_wait_block):
        """scar_chan_new (cap = 0: sin límite) y scar_chan_send, que espera lugar
        si el canal está lleno."""
        return (
            # cap es un valor de runtime (cualquier i32); 0 = sin límite
            f"static {c_name} scar_chan_new_{suf}(int32_t cap) {{\n"
            f"    {c_name} c = malloc(sizeof({impl_name}));\n"
            f"    c->head = NULL;\n"
            f"    c->tail = NULL;\n"
            f"    c->closed = 0;\n"
            f"    c->cap = cap;\n"
            f"    c->count = 0;\n"
            f"    atomic_init(&c->giro, 10000);  // presupuesto de giro de recv(): 10 µs\n"
            f"    atomic_init(&c->giro_envio, 4000);  // el de send() a un canal lleno: 4 µs\n"
            f"    c->libres = NULL;\n"
            f"    c->n_libres = 0;\n"
            f"    atomic_init(&c->hay_libres, 0);\n"
            f"    atomic_init(&c->hay_mensajes, 0);\n"
            f"    atomic_init(&c->lleno, 0);\n"
            f"    pthread_mutex_init(&c->mu, NULL);\n"
            f"    scar_cond_init(&c->not_empty, 0);\n"
            f"    scar_cond_init(&c->not_full, 0);\n"
            f"    atomic_init(&c->refcount, 1);\n"
            f"    return c;\n"
            f"}}\n"
            f"\n"
            # Canal acotado lleno (cap > 0 y count >= cap): esperar en not_full hasta
            # que haya lugar o el canal se cierre. Cerrado es una condición más para
            # despertar: el valor se encola igual (como un send() a un canal cerrado
            # con lugar), en vez de descartarlo o esperar para siempre. Cada vuelta
            # revisa la cancelación (send_cancel_line, que suelta el nodo). signal() y
            # no broadcast(): cada mensaje encolado libera lugar para un solo send().
            "#ifndef SCAR_DEADLOCK_MSG\n"
            "#define SCAR_DEADLOCK_MSG \"deadlock: todas las tareas están esperando un canal o un join() \" \\\n"
            "    \"y ninguna puede seguir (un send() a un canal lleno o un recv() de uno vacío que nadie \" \\\n"
            "    \"va a llenar; ¿falta un ch.close() o una tarea que lea?)\"\n"
            "#endif\n"
            f"static void scar_chan_send_{suf}({c_name} c, {inner_c} value) {{\n"
            "    /*SCAR_STRC*/\n"
            + (f"    {node_name} *node = scar_blk_heap(sizeof({node_name}));\n"
               if inner_is_struct else
               # Canal de valores: el valor se arma en un nodo local y el nodo de
               # verdad se toma recién bajo el candado, de la lista de libres si
               # hay uno (el que dejó un recv anterior) o con malloc si no. Un
               # malloc y un free por mensaje costaban ~40 % del rendimiento de un
               # flujo (bench/canales/prototipos/envio.c).
               f"    {node_name} __scar_local;\n"
               f"    {node_name} *node = &__scar_local;\n"
               # sin nodos guardados (lo normal en una ida y vuelta): malloc acá,
               # fuera del candado, como siempre; con nodos guardados, se toma
               # uno bajo el candado
               f"    {node_name} *__scar_nodo = atomic_load_explicit(&c->hay_libres, memory_order_relaxed)\n"
               f"        ? NULL : malloc(sizeof({node_name}));\n")
            + ""
            f"{node_value_stmt}"
            f"    node->next = NULL;\n"
            + ("    ScarEspera __scar_espera = {~0UL, 0};\n    int __scar_giro = 0;\n" if self.has_tasks else "")
            + f"    for (;;) {{\n"
            f"{send_cancel_line}"
            f"        pthread_mutex_lock(&c->mu);\n"
            f"        if (c->cap > 0 && c->count >= c->cap && !c->closed) {{\n"
            f"{send_wait_block}"
            f"            pthread_mutex_unlock(&c->mu);\n"
            f"            continue;\n"
            f"        }}\n"
            + ("" if inner_is_struct else
               f"        if (!__scar_nodo) {{\n"
               f"            if (c->libres) {{\n"
               f"                __scar_nodo = c->libres;\n"
               f"                c->libres = __scar_nodo->next;\n"
               f"                if (--c->n_libres == 0)\n"
               f"                    atomic_store_explicit(&c->hay_libres, 0, memory_order_relaxed);\n"
               f"            }} else {{\n"
               # sin nodos libres: malloc fuera del candado, y otra vuelta (mientras
               # tanto el canal puede haberse llenado)
               f"                pthread_mutex_unlock(&c->mu);\n"
               f"                __scar_nodo = malloc(sizeof({node_name}));\n"
               f"                continue;\n"
               f"            }}\n"
               f"        }}\n"
               f"        *__scar_nodo = __scar_local;\n"
               f"        node = __scar_nodo;\n")
            + f"        if (c->tail) {{ c->tail->next = node; }} else {{ c->head = node; }}\n"
            f"        c->tail = node;\n"
            f"        c->count++;\n"
            # los avisos para el que gira, solo cuando cambian
            f"        if (c->head == node) atomic_store_explicit(&c->hay_mensajes, 1, memory_order_relaxed);\n"
            f"        if (c->cap > 0 && c->count == c->cap) atomic_store_explicit(&c->lleno, 1, memory_order_relaxed);\n"
            + ("        scar_avance();  // pasar un mensaje es progreso\n" if self.has_tasks else "")
            + f""
            f"        pthread_mutex_unlock(&c->mu);\n"
            f"        scar_cond_signal(&c->not_empty);\n"
            f"        return;\n"
            f"    }}\n"
            f"}}\n"
            f"\n"
            # Cerrar despierta a todos, en las dos direcciones: con esperas sin
            # timeout, un recv()/send() bloqueado se quedaría dormido para siempre.
        )

    def _chan_c_close_recv(self, suf, c_name, recv_wait_block, opt_c_name, cancel_line,
                           node_name, inner_is_struct, inner_c):
        """scar_chan_close y scar_chan_recv, que espera un mensaje o el cierre."""
        return (
            f"static void scar_chan_close_{suf}({c_name} c) {{\n"
            f"    pthread_mutex_lock(&c->mu);\n"
            f"    c->closed = 1;\n"
            # que el que gira pruebe el candado y vea `closed`
            f"    atomic_store_explicit(&c->hay_mensajes, 1, memory_order_relaxed);\n"
            f"    atomic_store_explicit(&c->lleno, 0, memory_order_relaxed);\n"
            f"    pthread_mutex_unlock(&c->mu);\n"
            f"    scar_cond_broadcast(&c->not_empty);\n"
            f"    scar_cond_broadcast(&c->not_full);\n"
            f"}}\n"
            f"\n"
            f"// Espera con pthread_cond_wait() sin timeout (ver recv_wait_block\n"
            f"// mas arriba): duerme de verdad, sin despertares periodicos. Por\n"
            f"// eso la cancelacion no puede depender de un sondeo:\n"
            f"// scar_cancel_notify() (TaskContext) despierta a este recv() a\n"
            f"// proposito en cuanto lo cancelan mientras esta dormido.\n"
            f"// Solo devuelve None cuando la cola esta vacia Y cerrada, leido de\n"
            f"// forma atomica bajo el mismo lock que .send().\n"
            f"//\n"
            f"// Espera en `not_empty` (no en un `cond` compartido con send()) y,\n"
            f"// al desencolar, usa pthread_cond_signal() sobre `not_full` -- no\n"
            f"// broadcast() -- porque liberar un lugar en la cola habilita como\n"
            f"// mucho a un solo send() bloqueado; con broadcast() los N workers\n"
            f"// de un pool que comparten el canal se despertarian TODOS en cada\n"
            f"// mensaje aunque solo uno lo fuera a consumir.\n"
            f"static {opt_c_name} scar_chan_recv_{suf}({c_name} c) {{\n"
            + ("    ScarEspera __scar_espera = {~0UL, 0};\n    int __scar_giro = 0;\n" if self.has_tasks else "")
            + f"    for (;;) {{\n"
            f"{cancel_line}"
            f"        pthread_mutex_lock(&c->mu);\n"
            f"        if (c->head) {{\n"
            f"            {node_name} *node = c->head;\n"
            f"            c->head = node->next;\n"
            f"            if (!c->head) c->tail = NULL;\n"
            f"            c->count--;\n"
            f"            if (!c->head && !c->closed) atomic_store_explicit(&c->hay_mensajes, 0, memory_order_relaxed);\n"
            f"            if (c->cap > 0 && c->count == c->cap - 1) atomic_store_explicit(&c->lleno, 0, memory_order_relaxed);\n"
            + ("            scar_avance();\n" if self.has_tasks else "")
            + ("" if inner_is_struct else
               # Canal de valores: el valor sale del nodo y el nodo vacío queda
               # para el próximo send() (hasta 256; los demás se liberan). Un
               # canal de structs no reusa: ahí el nodo ES el struct que recibe
               # el receptor, y pasa a ser suyo.
               f"            {inner_c} v = node->value;\n"
               # solo con cola: en una ida y vuelta la cola queda vacía, el nodo
               # se libera y el próximo send() pide uno con malloc, que le da
               # al hilo un nodo que acaba de tocar él (en su caché). Reusar ahí
               # traía el nodo del otro núcleo en cada mensaje (medido: la ida
               # y vuelta pasó de 0.30 a 0.40 us en 12 núcleos).
               f"            if (c->head != NULL && c->n_libres < 256) {{\n"
               f"                node->next = c->libres;\n"
               f"                c->libres = node;\n"
               f"                if (c->n_libres++ == 0)\n"
               f"                    atomic_store_explicit(&c->hay_libres, 1, memory_order_relaxed);\n"
               f"                node = NULL;\n"
               f"            }}\n")
            + f"            pthread_mutex_unlock(&c->mu);\n"
            f"            scar_cond_signal(&c->not_full);\n"
            + (
                # Struct: no se libera el nodo acá. node->value es su primer miembro, así
                # que el nodo es el struct, y se libera entero cuando el receptor llame a
                # {Struct}_free (misma dirección).
                f"            return {opt_c_name}_Some(({suf}*)node);\n"
                if inner_is_struct else
                f"            free(node);  // NULL si quedó para reusar\n"
                f"            return {opt_c_name}_Some(v);\n"
            )
            + f"        }}\n"
            f"        if (c->closed) {{\n"
            f"            pthread_mutex_unlock(&c->mu);\n"
            f"            return {opt_c_name}_None();\n"
            f"        }}\n"
            f"{recv_wait_block}"
            f"        pthread_mutex_unlock(&c->mu);\n"
            f"    }}\n"
            f"}}\n"
            f"\n"
            # try_recv() no espera: Some si hay un valor encolado ahora, None si no.
            # El valor se saca igual que en recv().
        )

    def _chan_c_try_recv(self, opt_c_name, c_name, suf, node_name, inner_is_struct,
                         inner_c):
        """scar_chan_try_recv: un mensaje si hay, sin esperar."""
        return (
            f"static {opt_c_name} scar_chan_try_recv_{suf}({c_name} c) {{\n"
            f"    pthread_mutex_lock(&c->mu);\n"
            f"    if (c->head) {{\n"
            f"        {node_name} *node = c->head;\n"
            f"        c->head = node->next;\n"
            f"        if (!c->head) c->tail = NULL;\n"
            f"        c->count--;\n"
            f"        if (!c->head && !c->closed) atomic_store_explicit(&c->hay_mensajes, 0, memory_order_relaxed);\n"
            f"        if (c->cap > 0 && c->count == c->cap - 1) atomic_store_explicit(&c->lleno, 0, memory_order_relaxed);\n"
            + ("        scar_avance();\n" if self.has_tasks else "")
            + ("" if inner_is_struct else
               # como en recv: el nodo vacío queda para reusar
               f"        {inner_c} v = node->value;\n"
               # solo con cola: en una ida y vuelta la cola queda vacía, el nodo
               # se libera y el próximo send() pide uno con malloc, que le da
               # al hilo un nodo que acaba de tocar él (en su caché). Reusar ahí
               # traía el nodo del otro núcleo en cada mensaje (medido: la ida
               # y vuelta pasó de 0.30 a 0.40 us en 12 núcleos).
               f"        if (c->head != NULL && c->n_libres < 256) {{\n"
               f"            node->next = c->libres;\n"
               f"            c->libres = node;\n"
               f"            if (c->n_libres++ == 0)\n"
               f"                atomic_store_explicit(&c->hay_libres, 1, memory_order_relaxed);\n"
               f"            node = NULL;\n"
               f"        }}\n")
            + f"        pthread_mutex_unlock(&c->mu);\n"
            f"        scar_cond_signal(&c->not_full);\n"
            + (
                f"        return {opt_c_name}_Some(({suf}*)node);\n"
                if inner_is_struct else
                f"        free(node);  // NULL si quedó para reusar\n"
                f"        return {opt_c_name}_Some(v);\n"
            )
            + f"    }}\n"
            f"    pthread_mutex_unlock(&c->mu);\n"
            f"    return {opt_c_name}_None();\n"
            f"}}\n"
            f"\n"
            # Libera la cola y cada nodo pendiente con su valor. Solo la llama
            # scar_chan_decref cuando el contador llega a 0. Sin guardia de tareas: el
            # valor de un nodo nunca está en una arena (send() lo sacó de ahí).
        )

    def _chan_c_refs(self, suf, c_name):
        """scar_chan_incref y scar_chan_decref (el canal se libera con la última
        referencia)."""
        return (
            f"static void scar_chan_incref_{suf}({c_name} c) {{\n"
            f"    atomic_fetch_add(&c->refcount, 1);\n"
            f"}}\n"
            f"\n"
            # Cada dueña (la variable del `let` y cada parámetro Chan<T> de una task)
            # resta uno al cerrar su scope. fetch_sub devuelve el valor de antes: la
            # llamada que lo bajó de 1 a 0 es la que libera.
            f"static void scar_chan_decref_{suf}({c_name} c) {{\n"
            f"    if (atomic_fetch_sub(&c->refcount, 1) == 1) {{\n"
            f"        scar_chan_free_{suf}(c);\n"
            f"    }}\n"
            f"}}"
        )

    def _vec_c_new_grow(self, c_name, name_part, inner_c):
        """scar_vec_new y scar_vec_grow (que duplica la capacidad, fuera de línea)."""
        return (
            f"static {c_name} scar_vec_new_{name_part}(int32_t cap) {{\n"
            f"    {c_name} v;\n"
            # el buffer sale del reciclador (scar_vbuf_pedir, pool_allocator.c) y
            # la capacidad es todo lo que entra en el bloque, al menos cap
            f"    if (cap > 0) {{\n"
            f"        size_t util;\n"
            f"        v.data = scar_vbuf_pedir(sizeof({inner_c}) * (size_t)cap, &util);\n"
            f"        v.cap = (int32_t)(util / sizeof({inner_c}));\n"
            f"    }} else {{\n"
            f"        v.data = NULL;\n"
            f"        v.cap = 0;\n"
            f"    }}\n"
            f"    v.len = 0;\n"
            f"    return v;\n"
            f"}}\n"
            f"\n"
            # push es inline y el realloc va aparte, en scar_vec_grow_<T> (noinline):
            # con el realloc adentro gcc nunca inlineaba push (visto en objdump). grow
            # corre O(log n) veces por Vec, al doblar la capacidad.
            f"static __attribute__((noinline)) void scar_vec_grow_{name_part}({c_name}* v) {{\n"
            f"    int32_t cap = v->cap ? v->cap * 2 : 4;\n"
            f"    size_t util;\n"
            f"    v->data = scar_vbuf_agrandar(v->data, sizeof({inner_c}) * (size_t)v->len,\n"
            f"                                 sizeof({inner_c}) * (size_t)cap, &util);\n"
            f"    v->cap = (int32_t)(util / sizeof({inner_c}));\n"
            f"}}\n"
            f"\n"
        )

    def _vec_c_push(self, name_part, c_name, inner_c, inner, inner_is_struct,
                    inner_is_chan, inner_vec_part, inner_is_vec, opt_con_dueno,
                    inner_is_map):
        """scar_vec_push: mueve el valor al Vec (y lo da de baja de las vivas si
        es un struct o un contenedor)."""
        return (
            f"static inline void scar_vec_push_{name_part}({c_name}* v, {inner_c} value) {{\n"
            f"    if (__builtin_expect(v->len == v->cap, 0)) {{\n"
            f"        scar_vec_grow_{name_part}(v);\n"
            f"    }}\n"
            f"    v->data[v->len++] = value;\n"
            f"}}\n"
            f"\n"
            # set(i, x): el índice tiene que existir (panic si no) y no cambia len.
            # Antes de pisar el slot se libera lo que había: un struct embebido, con
            # {T}_free_fields (sin tasks) o {T}_free_heap_fields (con tasks: lo de la
            # arena lo libera la arena); un str, con scar_free; un Chan, con decref.
            + (
                f"static inline void scar_vec_set_{name_part}({c_name}* v, int32_t index, {inner_c} value) {{\n"
                + self._vec_chequeo_indice()
                + (
                    f"    {inner.name}_{'free_heap_fields' if self.has_tasks else 'free_fields'}(&v->data[index]);\n"
                    if inner_is_struct else
                    f"    scar_free((char*)v->data[index]);\n"
                    if inner.name == "str" else
                    f"    scar_chan_decref_"
                    f"{self._mangled_name(inner.args[0] if inner.args else T_I32)}(v->data[index]);\n"
                    if inner_is_chan else
                    f"    scar_vec_free_{inner_vec_part}(v->data[index]);\n"
                    if inner_is_vec else
                    "".join(l + "\n" for l in self._lineas_liberar_dueno(inner, "v->data[index]", "    "))
                    if opt_con_dueno or inner_is_map else ""
                )
                + f"    v->data[index] = value;\n"
                f"}}\n"
                f"\n"
            )
            # replace(i, x): como set, pero el valor viejo no se libera: se devuelve
            # y es de quien llama. Un struct embebido se traslada a un bloque propio,
            # como en pop, sin copiar sus campos.
            + (
                f"static inline {(inner.name + '*') if inner_is_struct else inner_c} "
                f"scar_vec_replace_{name_part}({c_name}* v, int32_t index, {inner_c} value) {{\n"
                + self._vec_chequeo_indice()
                + (
                    f"    {inner.name}* __scar_viejo = scar_blk_heap(sizeof({inner.name}));\n"
                    f"    *__scar_viejo = v->data[index];\n"
                    if inner_is_struct else
                    f"    {inner_c} __scar_viejo = v->data[index];\n"
                )
                + f"    v->data[index] = value;\n"
                f"    return __scar_viejo;\n"
                f"}}\n"
                f"\n"
            )
        )

    def _vec_c_trozo(self, name_part, c_name):
        """v[a..b]: la vista del pedazo, que se lee y se escribe como
        un Vec cualquiera (suma y punto dan lo de un Vec con esos elementos).
        cap = 0: no es dueña de nada, nadie la libera."""
        pnc = panic_c(self.has_tasks)
        return (
            f"static inline __attribute__((unused)) {c_name} scar_vec_trozo_{name_part}({c_name} v, int32_t a, int32_t b) {{\n"
            f"    if (__builtin_expect(a < 0 || a > b || b > v.len, 0)) {{\n"
            f'        {pnc}("pedazo fuera de rango: [%d..%d] (longitud %d)", a, b, v.len);\n'
            f"    }}\n"
            f"    {c_name} r = v;\n"
            f"    r.data = v.data + a;\n"
            f"    r.len = b - a;\n"
            f"    r.cap = 0;\n"
            f"    return r;\n"
            f"}}\n\n"
        )

    def _vec_c_llenar(self, name_part, c_name, inner):
        """v.llenar(x): cada elemento queda en x. Un bucle
        sin chequeos por elemento, que el compilador hace con SIMD o memset. Sale
        solo si el programa lo usa."""
        t = self.c_type(inner)
        return (
            f"static __attribute__((unused)) void scar_vec_llenar_{name_part}({c_name} v, {t} x) {{\n"
            f"    for (int32_t i = 0; i < v.len; i++) v.data[i] = x;\n"
            f"}}\n\n"
        )

    def _vec_c_acumular_entero(self, name_part, c_name, inner):
        """a.acumular(b, k) con enteros: a[i] = a[i] + k * b[i], la cuenta exacta
        (en 64 bits para i32, en 128 para i64), y panic en el primer elemento que
        no cabe en el tipo. En orden, como el intérprete (si a y b se pisan, da
        lo mismo). Sale solo si el programa lo usa."""
        t = self.c_type(inner)
        pnc = panic_c(self.has_tasks)
        ancho, lo, hi = (("int64_t", "INT32_MIN", "INT32_MAX") if inner.name == "i32"
                         else ("__int128", "INT64_MIN", "INT64_MAX"))
        return (
            f"static __attribute__((unused)) void scar_vec_acumular_{name_part}({c_name} a, {c_name} b, {t} k) {{\n"
            f"    if (a.len != b.len) {{\n"
            f'        {pnc}("acumular: los Vec tienen largos distintos (%d y %d)", a.len, b.len);\n'
            f"    }}\n"
            f"    for (int32_t i = 0; i < a.len; i++) {{\n"
            f"        {ancho} r = ({ancho})a.data[i] + ({ancho})k * b.data[i];\n"
            f"        if (__builtin_expect(r < ({ancho}){lo} || r > ({ancho}){hi}, 0)) {{\n"
            f'            {pnc}("acumular: el resultado no cabe en {inner.name} (posición %d)", i);\n'
            f"        }}\n"
            f"        a.data[i] = ({t})r;\n"
            f"    }}\n"
            f"}}\n\n"
        )

    def _vec_c_suma_punto(self, name_part, c_name, inner):
        """v.suma() y a.punto(b) de un Vec de números. Decimales: el elemento i va al carril i % 16, cada carril
        suma en orden, y al final se juntan de a pares (k + 8, k + 4, k + 2, k + 1);
        cada cuenta se redondea al tipo, sin FMA (-ffp-contract=off). Los 16
        carriles son independientes, así que el compilador los hace con SIMD sin
        cambiar el resultado: el intérprete hace las mismas cuentas en el mismo
        orden. Enteros: la suma exacta en 128 bits y panic si no cabe en el tipo
        (el orden no importa); en i64.punto, también si una suma parcial pasa de
        128 bits. Mismos mensajes que el intérprete."""
        if inner.name not in ("i32", "i64", "f64", "f32"):
            return ""
        t = self.c_type(inner)
        pnc = panic_c(self.has_tasks)
        largos = (
            f"    if (a.len != b.len) {{\n"
            f'        {pnc}("punto: los Vec tienen largos distintos (%d y %d)", a.len, b.len);\n'
            f"    }}\n"
        )
        trozo = self._vec_c_trozo(name_part, c_name)
        if inner.name in ("f64", "f32"):
            def carriles(nombre, params, termino, previo=""):
                return (
                    f"static __attribute__((unused)) {t} scar_vec_{nombre}_{name_part}({params}) {{\n"
                    + previo
                    + f"    {t} s[16] = {{0}};\n"
                    f"    int32_t i = 0;\n"
                    f"    for (; i + 16 <= {termino[0]}; i += 16) {{\n"
                    f"        for (int k = 0; k < 16; k++) s[k] = s[k] + {termino[1].format(j="i + k")};\n"
                    f"    }}\n"
                    f"    for (int k = 0; i < {termino[0]}; i++, k++) s[k] = s[k] + {termino[1].format(j='i')};\n"
                    f"    for (int w = 8; w >= 1; w /= 2) {{\n"
                    f"        for (int k = 0; k < w; k++) s[k] = s[k] + s[k + w];\n"
                    f"    }}\n"
                    f"    return s[0];\n"
                    f"}}\n\n"
                )
            # a.acumular(b, k): a[i] = a[i] + k * b[i], cada cuenta
            # redondeada al tipo (sin FMA). Cada elemento es independiente: el
            # compilador lo hace con SIMD y da lo mismo. Si a y b se pisan (dos
            # pedazos del mismo Vec), el orden es el del bucle, como el intérprete.
            acumular = (
                f"static __attribute__((unused)) void scar_vec_acumular_{name_part}({c_name} a, {c_name} b, {t} k) {{\n"
                f"    if (a.len != b.len) {{\n"
                f'        {pnc}("acumular: los Vec tienen largos distintos (%d y %d)", a.len, b.len);\n'
                f"    }}\n"
                f"    for (int32_t i = 0; i < a.len; i++) a.data[i] = a.data[i] + k * b.data[i];\n"
                f"}}\n\n"
            )
            return (trozo + acumular + carriles("suma", f"{c_name} v", ("v.len", "v.data[{j}]"))
                    + carriles("punto", f"{c_name} a, {c_name} b", ("a.len", "a.data[{j}] * b.data[{j}]"), largos))
        lo, hi = ("INT32_MIN", "INT32_MAX") if inner.name == "i32" else ("INT64_MIN", "INT64_MAX")
        def cabe(nombre):
            return (
                f"    if (s < (__int128){lo} || s > (__int128){hi}) {{\n"
                f'        {pnc}("{nombre}: el resultado no cabe en {inner.name}");\n'
                f"    }}\n"
                f"    return ({t})s;\n"
            )
        suma = (
            f"static __attribute__((unused)) {t} scar_vec_suma_{name_part}({c_name} v) {{\n"
            f"    __int128 s = 0;\n"
            f"    for (int32_t i = 0; i < v.len; i++) s += v.data[i];\n"
            + cabe("suma") + f"}}\n\n"
        )
        if inner.name == "i32":
            cuerpo = f"    for (int32_t i = 0; i < a.len; i++) s += (int64_t)a.data[i] * b.data[i];\n"
        else:
            cuerpo = (
                f"    for (int32_t i = 0; i < a.len; i++) {{\n"
                f"        if (__builtin_add_overflow(s, (__int128)a.data[i] * b.data[i], &s)) {{\n"
                f'            {pnc}("punto: la suma no cabe en 128 bits");\n'
                f"        }}\n"
                f"    }}\n"
            )
        punto = (
            f"static __attribute__((unused)) {t} scar_vec_punto_{name_part}({c_name} a, {c_name} b) {{\n"
            + largos + f"    __int128 s = 0;\n" + cuerpo + cabe("punto") + f"}}\n\n"
        )
        return trozo + suma + punto

    def _vec_c_get_pop(self, opt_c_name, c_name, name_part, inner, inner_is_struct,
                       inner_is_vec, opt_con_dueno, inner_is_map):
        """scar_vec_get (una copia, o None fuera de rango) y scar_vec_pop."""
        return (
            # get() de un Vec<Struct> no puede devolver &v.data[i]: esa dirección
            # vive dentro del buffer, y un push() posterior que lo realloque la deja
            # colgando. Devuelve una copia independiente.
            # v[i] de un Vec de números o bool: el elemento, sin Option; panic fuera de rango, con el mismo
            # mensaje que set() y que el intérprete.
            (
                f"static inline {self.c_type(inner)} scar_vec_en_{name_part}({c_name} v, int32_t index) {{\n"
                f"    if (__builtin_expect(index < 0 || index >= v.len, 0)) {{\n"
                f'        {panic_c(self.has_tasks)}("índice fuera de rango: %d (longitud %d)", index, v.len);\n'
                f"    }}\n"
                f"    return v.data[index];\n"
                f"}}\n"
                f"\n"
                if inner.name in ("i32", "i64", "f64", "f32", "bool") else ""
            )
            # v[i] de un Vec de structs o de Vec: un lugar. La dirección del elemento dentro del buffer, con el mismo
            # chequeo de rango; vale mientras el Vec no crezca, y el checker solo deja
            # usarla dentro de una sentencia (v[i].campo, m[i][j], m[i].len()).
            + (
                f"static inline {inner.name if inner_is_struct else self.c_type(inner)}* "
                f"scar_vec_lugar_{name_part}({c_name} v, int32_t index) {{\n"
                f"    if (__builtin_expect(index < 0 || index >= v.len, 0)) {{\n"
                f'        {panic_c(self.has_tasks)}("índice fuera de rango: %d (longitud %d)", index, v.len);\n'
                f"    }}\n"
                f"    return &v.data[index];\n"
                f"}}\n"
                f"\n"
                if inner_is_struct or inner_is_vec else ""
            )
            + f"static {opt_c_name} scar_vec_get_{name_part}({c_name} v, int32_t index) {{\n"
            f"    if (index < 0 || index >= v.len) {{\n"
            f"        return {opt_c_name}_None();\n"
            f"    }}\n"
            + (
                # {T}_clone y no {T}_deepcopy: la copia necesita sus propios Vec/Map,
                # además de sus str.
                f"    return {opt_c_name}_Some({inner.name}_clone(&v.data[index]));\n"
                if inner_is_struct else
                f"    return {opt_c_name}_Some({self._clone_fn(inner)}(v.data[index]));\n"
                if inner_is_vec else
                f"    return {opt_c_name}_Some({self._clone_value_expr(inner, 'v.data[index]')});\n"
                if opt_con_dueno or inner_is_map else
                f"    return {opt_c_name}_Some(v.data[index]);\n"
            )
            + f"}}\n"
            f"\n"
            # pop() saca el valor del Vec: el slot deja de ser parte de él.
            f"static inline {opt_c_name} scar_vec_pop_{name_part}({c_name}* v) {{\n"
            f"    if (__builtin_expect(v->len == 0, 0)) {{\n"
            f"        return {opt_c_name}_None();\n"
            f"    }}\n"
            + (
                # pop() mueve el struct a un bloque propio, siempre de malloc (aun con
                # tasks: `while let Some(x) = v.pop()` lo libera con {T}_free), sin copiar
                # sus campos ni liberar el slot.
                f"    v->len--;\n"
                f"    {inner.name}* __scar_moved = scar_blk_heap(sizeof({inner.name}));\n"
                f"    *__scar_moved = v->data[v->len];\n"
                # los structs anidados conservan su propio bloque (malloc o arena), y
                # {T}_free decide por el encabezado
                + f"    return {opt_c_name}_Some(__scar_moved);\n"
                if inner_is_struct else
                f"    return {opt_c_name}_Some(v->data[--v->len]);\n"
            )
            + f"}}\n"
            f"\n"
        )

    def _vec_c_len_resto(self, name_part, c_name, inner, inner_is_struct, inner_is_chan,
                         inner_vec_part, inner_is_vec, opt_con_dueno, inner_is_map):
        """scar_vec_len, set, remove, insert y free (con lo que haya que soltar
        de cada elemento)."""
        return (
            f"static int32_t scar_vec_len_{name_part}({c_name} v) {{\n"
            f"    return v.len;\n"
            f"}}\n"
            f"\n"
            # free: el buffer de un Vec es siempre del reciclador (nunca de la arena). Antes
            # de liberarlo se suelta cada elemento con dueño: un str con scar_free, un
            # struct embebido con {T}_free_fields (sin tasks) o {T}_free_heap_fields
            # (con tasks). scar_vbuf_soltar(NULL) no hace nada (un Vec sin push).
            + (
                f"static void scar_vec_free_{name_part}({c_name} v) {{\n"
                f"    for (int32_t i = 0; i < v.len; i++) {{\n"
                f"        scar_free((char*)v.data[i]);\n"
                f"    }}\n"
                f"    scar_vbuf_soltar(v.data);\n"
                f"}}"
                if inner.name == "str" else
                f"static void scar_vec_free_{name_part}({c_name} v) {{\n"
                + (
                    f"    for (int32_t i = 0; i < v.len; i++) {{\n"
                    f"        {inner.name}_{'free_heap_fields' if self.has_tasks else 'free_fields'}(&v.data[i]);\n"
                    f"    }}\n"
                    if inner_is_struct else
                    # Chan<U>: el Vec sumó una referencia al guardarlo, así que la resta al
                    # liberarse (un Chan nunca está en una arena).
                    f"    for (int32_t i = 0; i < v.len; i++) {{\n"
                    f"        scar_chan_decref_"
                    f"{self._mangled_name(inner.args[0] if inner.args else T_I32)}(v.data[i]);\n"
                    f"    }}\n"
                    if inner_is_chan else
                    f"    for (int32_t i = 0; i < v.len; i++) {{\n"
                    f"        scar_vec_free_{inner_vec_part}(v.data[i]);\n"
                    f"    }}\n"
                    if inner_is_vec else
                    f"    for (int32_t i = 0; i < v.len; i++) {{\n"
                    + "".join(l + "\n" for l in self._lineas_liberar_dueno(inner, "v.data[i]", "        "))
                    + f"    }}\n"
                    if opt_con_dueno or inner_is_map else ""
                )
                + f"    scar_vbuf_soltar(v.data);\n"
                f"}}"
            )
        )

    def _map_c_new_find(self, c_name, suffix, impl_name, entry_name, key_c, hash_fn,
                        key_eq):
        """scar_map_new y scar_map_find (búsqueda lineal con sondeo)."""
        return (
            f"static {c_name} scar_map_new_{suffix}(void) {{\n"
            f"    {c_name} m = malloc(sizeof({impl_name}));\n"
            f"    m->cap = 8;\n"
            f"    m->entries = calloc((size_t)m->cap, sizeof({entry_name}));\n"
            f"    m->count = 0;\n"
            f"    m->tombstones = 0;\n"
            f"    m->siguiente = 0;\n"
            f"    return m;\n"
            f"}}\n"
            f"\n"
            f"// Busca 'key'. Si for_insert, devuelve el slot a usar para insertar\n"
            f"// (el slot existente si la key ya está, o el primer hueco/tumba\n"
            f"// disponible). Si no, devuelve -1 cuando la key no está presente --\n"
            f"// las tumbas se saltean sin contar como 'encontrado'.\n"
            f"static int32_t scar_map_find_{suffix}({c_name} m, {key_c} key, bool for_insert) {{\n"
            f"    uint64_t h = {hash_fn}(key);\n"
            f"    int32_t idx = (int32_t)(h % (uint64_t)m->cap);\n"
            f"    int32_t first_tombstone = -1;\n"
            f"    for (int32_t i = 0; i < m->cap; i++) {{\n"
            f"        int32_t slot = (idx + i) % m->cap;\n"
            f"        uint8_t st = m->entries[slot].state;\n"
            f"        if (st == 0) {{\n"
            f"            if (!for_insert) return -1;\n"
            f"            return first_tombstone >= 0 ? first_tombstone : slot;\n"
            f"        }}\n"
            f"        if (st == 2) {{\n"
            f"            if (for_insert && first_tombstone < 0) first_tombstone = slot;\n"
            f"            continue;\n"
            f"        }}\n"
            f"        if {key_eq} {{\n"
            f"            return slot;\n"
            f"        }}\n"
            f"    }}\n"
            f"    return (for_insert && first_tombstone >= 0) ? first_tombstone : -1;\n"
            f"}}\n"
            f"\n"
        )

    def _map_c_grow_set(self, suffix, c_name, entry_name, hash_fn, key_c, val_c,
                        free_old_value, free_redundant_key):
        """scar_map_grow y scar_map_set (que suelta el valor viejo de la clave)."""
        return (
            f"static void scar_map_grow_{suffix}({c_name} m) {{\n"
            f"    int32_t old_cap = m->cap;\n"
            f"    {entry_name} *old_entries = m->entries;\n"
            f"    int32_t new_cap = old_cap * 2;\n"
            f"    {entry_name} *new_entries = calloc((size_t)new_cap, sizeof({entry_name}));\n"
            f"    for (int32_t i = 0; i < old_cap; i++) {{\n"
            f"        if (old_entries[i].state != 1) continue;\n"
            f"        uint64_t h = {hash_fn}(old_entries[i].key);\n"
            f"        int32_t idx = (int32_t)(h % (uint64_t)new_cap);\n"
            f"        for (int32_t j = 0; j < new_cap; j++) {{\n"
            f"            int32_t slot = (idx + j) % new_cap;\n"
            f"            if (new_entries[slot].state == 0) {{\n"
            f"                new_entries[slot] = old_entries[i];\n"
            f"                break;\n"
            f"            }}\n"
            f"        }}\n"
            f"    }}\n"
            f"    free(old_entries);\n"
            f"    m->entries = new_entries;\n"
            f"    m->cap = new_cap;\n"
            f"    m->tombstones = 0;  // el array nuevo nace sin tumbas\n"
            f"}}\n"
            f"\n"
            f"static void scar_map_set_{suffix}({c_name} m, {key_c} key, {val_c} value) {{\n"
            f"    // load factor (ocupadas + tumbas) >= 0.75 -> crecer ANTES de\n"
            f"    // buscar el slot, para que el probe de abajo nunca corra sobre\n"
            f"    // una tabla casi llena.\n"
            f"    if ((m->count + m->tombstones) * 4 >= m->cap * 3) {{\n"
            f"        scar_map_grow_{suffix}(m);\n"
            f"    }}\n"
            f"    int32_t idx = scar_map_find_{suffix}(m, key, true);\n"
            f"    if (m->entries[idx].state == 1) {{\n"
            f"        // key ya existía: libera el value viejo si corresponde (ver\n"
            f"        // free_old_value en _map_c_type) y sobrescribe -- .len() no\n"
            f"        // cambia (mismo comportamiento que ScarMap.set() en el\n"
            f"        // intérprete).\n"
            f"{free_old_value}"
            f"{free_redundant_key}"
            f"        m->entries[idx].value = value;\n"
            f"        return;\n"
            f"    }}\n"
            f"    if (m->entries[idx].state == 2) m->tombstones--;\n"
            f"    m->entries[idx].key = key;\n"
            f"    m->entries[idx].value = value;\n"
            f"    m->entries[idx].state = 1;\n"
            f"    m->entries[idx].orden = m->siguiente++;\n"
            f"    m->count++;\n"
            f"}}\n"
            f"\n"
        )

    def _map_c_get_remove(self, opt_c_name, c_name, suffix, key_c, val_ty, val_is_vec,
                          val_is_map, val_opt_dueno, key_ty):
        """scar_map_get (una copia) y scar_map_remove (entrega el valor)."""
        return (
            f"static {opt_c_name} scar_map_get_{suffix}({c_name} m, {key_c} key) {{\n"
            f"    int32_t idx = scar_map_find_{suffix}(m, key, false);\n"
            f"    if (idx < 0) return {opt_c_name}_None();\n"
            # get() devuelve una copia, como Vec.get()
            + (f"    return {opt_c_name}_Some({val_ty.name}_clone(m->entries[idx].value));\n"
               if val_ty.name in self.structs else
               f"    return {opt_c_name}_Some({self._clone_fn(val_ty)}(m->entries[idx].value));\n"
               if val_is_vec or val_is_map else
               f"    return {opt_c_name}_Some({self._clone_value_expr(val_ty, 'm->entries[idx].value')});\n"
               if val_opt_dueno else
               f"    return {opt_c_name}_Some(m->entries[idx].value);\n")
            + f"}}\n"
            f"\n"
            f"static {opt_c_name} scar_map_remove_{suffix}({c_name} m, {key_c} key) {{\n"
            f"    int32_t idx = scar_map_find_{suffix}(m, key, false);\n"
            f"    if (idx < 0) return {opt_c_name}_None();\n"
            f"    {opt_c_name} result = {opt_c_name}_Some(m->entries[idx].value);\n"
            # La clave de la entrada que se borra no se devuelve a nadie: se libera
            # acá (free solo mira las entradas ocupadas).
            + (
                "    scar_free((char*)m->entries[idx].key);\n"
                if key_ty.name == "str" else ""
            ) +
            f"    m->entries[idx].state = 2;\n"
            f"    m->count--;\n"
            f"    m->tombstones++;\n"
            f"    return result;\n"
            f"}}\n"
            f"\n"
        )

    def _map_c_len_resto(self, suffix, c_name, val_ty, val_is_struct, val_is_chan,
                         val_vec_part, val_is_vec, val_is_map, val_opt_dueno, key_ty):
        """scar_map_len, has, keys y free (con lo que haya que soltar de cada
        clave y valor)."""
        return (
            f"static int32_t scar_map_len_{suffix}({c_name} m) {{\n"
            f"    return m->count;\n"
            f"}}\n"
            f"\n"
            # free: la tabla es siempre malloc. Antes de liberarla se suelta cada
            # entrada ocupada (state == 1; una tumba ya soltó lo suyo): el valor con
            # dueño y la clave str.
            + (lambda free_lines: (
                f"static void scar_map_free_{suffix}({c_name} m) {{\n"
                # NULL es el estado vacío de un campo Map ya extraído
                # (_try_neutralize_extracted_field), como {0} para un Vec
                f"    if (m == NULL) return;\n"
                f"    for (int32_t i = 0; i < m->cap; i++) {{\n"
                f"        if (m->entries[i].state == 1) {{\n"
                + "".join(free_lines) +
                f"        }}\n"
                f"    }}\n"
                f"    free(m->entries);\n"
                f"    free(m);\n"
                f"}}"
                if free_lines else
                f"static void scar_map_free_{suffix}({c_name} m) {{\n"
                f"    if (m == NULL) return;\n"
                f"    free(m->entries);\n"
                f"    free(m);\n"
                f"}}"
            ))(
                (
                    [f"            {val_ty.name}_free(m->entries[i].value);\n"]
                    if val_is_struct else []
                ) + (
                    ["            scar_free((char*)m->entries[i].value);\n"]
                    if val_ty.name == "str" else []
                ) + (
                    # Chan<V>: decref de los que quedan adentro
                    [
                        f"            scar_chan_decref_"
                        f"{self._mangled_name(val_ty.args[0] if val_ty.args else T_I32)}"
                        f"(m->entries[i].value);\n"
                    ]
                    if val_is_chan else []
                ) + (
                    [f"            scar_vec_free_{val_vec_part}(m->entries[i].value);\n"]
                    if val_is_vec else []
                ) + (
                    [l + "\n" for l in self._lineas_liberar_dueno(val_ty, "m->entries[i].value", "            ")]
                    if val_is_map or val_opt_dueno else []
                ) + (
                    ["            scar_free((char*)m->entries[i].key);\n"]
                    if key_ty.name == "str" else []
                )
            )
        )

    def _vec_chequeo_indice(self):
        """El chequeo de índice de set() y replace(): fuera de rango es un panic,
        con el mismo mensaje que el intérprete."""
        return (
            f"    if (index < 0 || index >= v->len) {{\n"
            f'        {panic_c(self.has_tasks)}("índice fuera de rango: %d (longitud %d)", index, v->len);\n'
            f"    }}\n"
        )
