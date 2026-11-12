"""Mixin Tareas de Codegen (paso C6): tasks y canales inyectados. El soporte de
C de cada task (args, thread fn, cancelación), spawn, y la inyección y
aceptación de canales.
"""

from parser import FnDecl, FieldAccess
from types_ import TypeAnn, T_I32, T_VOID

from .comun import CHAN_MARK, CodegenError, literal_c, MAP_MARK, TASK_MARK, VEC_MARK


class Tareas:
    def _texto_task(self, ty: TypeAnn) -> str:
        """El literal de C de un handle impreso, "<task cuadrado>", como
        TaskHandle.__repr__ del intérprete (con el nombre del usuario)."""
        nombre = self.nombres.mostrar(ty.args[1].name) if len(ty.args) >= 2 else "?"
        return literal_c("<task " + nombre + ">")

    def _gen_spawn(self, expr: "SpawnExpr", env, out, pad) -> str:
        """`spawn tarea(args...)`: reserva en el heap un struct con los argumentos
        (tienen que sobrevivir a este frame), crea el TaskContext de la hija y lo
        registra como hija del contexto actual antes de arrancar el hilo (si no,
        la hija podría hacer panic antes de estar en la lista de su madre), y
        recién ahí la lanza (scar_tarea_lanzar: un hilo del sistema, o una fibra
        del planificador con SCAR_TAREAS=livianas) con el envoltorio de la tarea. El
        TaskHandle solo guarda el puntero al TaskContext; el tipo de retorno se
        recupera en .join()."""
        call = expr.call
        name = call.callee.name
        params, ret = self.task_sigs[name]
        decl = self.task_decls[name]
        arg_names = [p.name for p in decl.params]
        args_struct = self._task_args_struct_name(name)
        # con el tipo del parámetro, como en una llamada a fn: sin él,
        # `spawn t(vec_new())` armaba un Vec_i32 para un parámetro Vec<Cuenta>
        args_code = [
            self.gen_expr(a, env, out, pad, expected_ty=(params[i] if i < len(params) else None))
            for i, a in enumerate(call.args)
        ]
        # Antes de que _note_owner_transfer desmarque nada: por cada argumento
        # str, si su raíz es dueña acá. Es lo que decide si la hija recibe el str
        # como dueña (el flag oculto de gen_fn), y solo se sabe en este momento.
        str_owned = {}
        copiados = set()
        for j_arg, (p, arg_expr, arg_ty) in enumerate(zip(decl.params, call.args, params)):
            if arg_ty.name != "str":
                continue
            root_name = self._ident_root_name(arg_expr)
            if isinstance(arg_expr, FieldAccess) and self._campo_de_temporal(arg_expr, env) is not None:
                # un campo str sacado de un struct temporal (`spawn t(mk().s)`) ya es
                # fresco: pasa a la hija tal cual
                str_owned[p.name] = "true"
                continue
            if isinstance(arg_expr, FieldAccess):
                # un campo str (`spawn t(c.host)`): el struct sigue siendo su dueño, así
                # que la hija recibe una copia propia (si no, el padre podía liberarlo o
                # reasignarlo mientras la hija lo leía)
                self.needs_str_concat = True
                args_code[j_arg] = f"scar_str_concat({args_code[j_arg]}, \"\")"
                str_owned[p.name] = "true"
                copiados.add(j_arg)
                continue
            if (root_name is None
                    and self._let_creates_fresh_owner(arg_expr, None, env)
                    and args_code[j_arg] not in self.pending_expr_temps):
                # un str fresco escrito en el spawn (`spawn usa("n" + "m")`) no tiene
                # otra dueña: pasa a la hija
                str_owned[p.name] = "true"
            elif root_name is None or not self._is_owner(root_name):
                str_owned[p.name] = "false"
            else:
                # Si la raíz es un parámetro str de task (origen "cond:<flag>"), ser
                # dueña se decide en runtime: se reenvía su flag, no un `true` fijo (con
                # el `true`, una task que recibía un literal y lo reenviaba le hacía
                # liberar un literal a su hija).
                origin = self._owner_origin(root_name) or ""
                if origin.startswith("cond:") or origin == "plain":
                    # una variable str de quien lanza sigue siendo suya: la hija recibe una
                    # copia propia. Con el mismo puntero, `for ... { spawn t(x) }` hacía que
                    # cada hija se creyera dueña del mismo texto (double free). Un str es un
                    # valor: copiarlo no cambia lo que hace el programa.
                    self.needs_str_concat = True
                    args_code[j_arg] = f"scar_str_concat({args_code[j_arg]}, \"\")"
                    str_owned[p.name] = "true"
                    copiados.add(j_arg)
                else:
                    str_owned[p.name] = "false"
        # cada argumento cruza a la hija como en el checker (_move_if_needed): si
        # su raíz era dueña acá, deja de serlo
        self._capture_args_reading_moved_fields(call.args, params, args_code, env, out, pad)
        for j, (arg_expr, arg_ty) in enumerate(zip(call.args, params)):
            if j in copiados:
                continue
            if self._is_moved_container_type(arg_ty):
                args_code[j] = self._move_arg_out(arg_expr, arg_ty, args_code[j], env, out, pad)
            else:
                self._note_owner_transfer(arg_expr, arg_ty)
        # cada Chan que cruza es una copia más del puntero: incref (quien lanza
        # sigue siendo dueño de la suya; _note_owner_transfer no toca un Chan)
        for arg_expr, code, arg_ty in zip(call.args, args_code, params):
            if arg_ty.name == CHAN_MARK:
                inner = arg_ty.args[0] if arg_ty.args else T_I32
                out.append(f"{pad}scar_chan_incref_{self._mangled_name(inner)}({code});")
        tmp_args = self._new_tmp()
        out.append(f"{pad}{args_struct}* {tmp_args} = malloc(sizeof({args_struct}));")
        for p_name, code in zip(arg_names, args_code):
            out.append(f"{pad}{tmp_args}->{p_name} = {code};")
        for p_name, owned in str_owned.items():
            flag = self._str_owned_flag_name(p_name)
            out.append(f"{pad}{tmp_args}->{flag} = {owned};")
        tmp_ctx = self._new_tmp()
        out.append(
            f'{pad}TaskContext* {tmp_ctx} = scar_ctx_new("{self.nombres.mostrar(name)}", __scar_ctx);'
        )
        out.append(f"{pad}scar_ctx_add_child(__scar_ctx, {tmp_ctx});")
        if decl.accepts:
            # el struct InjectedSlots_<task> se reserva antes de lanzarla, en
            # cero (cada slot NULL): la hija puede llegar a accept_chan() enseguida
            out.append(
                f"{pad}{tmp_ctx}->injected_slots = "
                f"calloc(1, sizeof(InjectedSlots_{name}));"
            )
        # Cómo se libera __scar_result si nadie hace join (scar_cancel_children):
        # void no reserva nada; un struct, con {name}_free_erased; un valor con
        # datos propios (Vec, Map, str), con su liberador; el resto
        # (números, Option/Result), con free().
        if ret.name in self.structs:
            out.append(f"{pad}{tmp_ctx}->free_retval = {ret.name}_free_erased;")
        elif ret.name in (VEC_MARK, MAP_MARK, "str"):
            # con free() se liberaba solo la caja y se perdía el buffer del Vec, la
            # tabla del Map o el texto del str
            out.append(f"{pad}{tmp_ctx}->free_retval = {self._retval_free_fn(ret)};")
        elif ret.name != "void":
            out.append(f"{pad}{tmp_ctx}->free_retval = free;")
        out.append(f"{pad}{tmp_args}->__scar_ctx_hija = {tmp_ctx};")
        tmp_handle = self._new_tmp()
        out.append(f"{pad}TaskHandle {tmp_handle};")
        out.append(f"{pad}{tmp_handle}.ctx = {tmp_ctx};")
        out.append(f"{pad}/*SCAR_STRC*/")
        out.append(f"{pad}atomic_fetch_add(&scar_hilos_vivos, 1);")
        out.append(
            f"{pad}scar_tarea_lanzar({tmp_ctx}, "
            f"{self._task_thread_fn_name(name)}, {tmp_args});"
        )
        return tmp_handle

    def _gen_inject_chan(self, expr: "Call", args_code, env, out, pad) -> str:
        """inject_chan(handle, ch), como _inject_chan del intérprete: bajo
        injected_lock escribe el canal en el slot de su tipo en
        InjectedSlots_<task>. Tres caminos, en el mismo orden que el intérprete:

            (a) la task ya terminó -> Err;
            (b) la task no acepta ese tipo: el checker ya lo impide, así que se
                resuelve acá en Python (CodegenError si pasa) y en el C queda un
                `if (false)` con el mismo Err, para que la estructura sea la del
                intérprete;
            (c) ya hay una inyección de ese tipo sin consumir -> Err;
            si no, el canal va al slot y devuelve Ok(())."""
        handle_expr, chan_expr = expr.args
        handle_ty = self.infer(handle_expr, env)
        if handle_ty.name != TASK_MARK or len(handle_ty.args) < 2:
            # un spawn con un error previo devuelve el Task sin el nombre de la task:
            # el checker ya lo reportó, así que acá no se llega con un .scar real
            raise CodegenError(
                "'inject_chan': no se pudo resolver en tiempo de compilación "
                "la task destino de este TaskHandle (¿spawn con error previo, "
                "o backend de C invocado sin pasar por type_checker.py?)"
            )
        task_name = handle_ty.args[1].name
        chan_ty = self.infer(chan_expr, env)
        inner = chan_ty.args[0] if chan_ty.args else T_I32
        slot_map = self.task_accept_slots.get(task_name, {})
        type_accepted = self._mangled_name(inner) in slot_map
        if not type_accepted:
            # inalcanzable si el checker corrió: se corta acá en vez de generar un C
            # que castee a un campo que no existe
            raise CodegenError(
                f"'inject_chan': la task '{task_name}' no declaró aceptar "
                f"{chan_ty!r} por inyección -- type_checker.py debería haber "
                f"rechazado esto antes de llegar al backend de C"
            )
        field = slot_map[self._mangled_name(inner)]
        result_c = self.c_type(TypeAnn("Result", [T_VOID]))  # registra Result_void
        handle_code, chan_code = args_code[0], args_code[1]
        ctx_code = f"({handle_code}).ctx"
        tmp_result = self._new_tmp()
        tmp_slots = self._new_tmp()
        out.append(f"{pad}{result_c} {tmp_result};")
        out.append(f"{pad}if (atomic_load(&{ctx_code}->finished)) {{")
        out.append(
            f"{pad}    // (a) la task destino ya terminó\n"
            f'{pad}    {tmp_result} = {result_c}_Err("la task \'{self.nombres.mostrar(task_name)}\' '
            f'ya terminó, no se puede inyectar");'
        )
        out.append(f"{pad}}} else {{")
        out.append(f"{pad}    pthread_mutex_lock(&{ctx_code}->injected_lock);")
        # Se vuelve a mirar `finished` con el lock tomado: el envoltorio de la
        # task drena los slots y marca finished bajo este mismo lock, así que si
        # acá se ve terminada, escribir el slot dejaría un canal colgado para
        # siempre. El chequeo de afuera es el camino rápido sin lock.
        out.append(f"{pad}    if (atomic_load(&{ctx_code}->finished)) {{")
        out.append(
            f"{pad}        // (a2) la task terminó justo mientras se esperaba\n"
            f"{pad}        // el lock (recheck bajo el lock, ver el wrapper de la task)\n"
            f'{pad}        {tmp_result} = {result_c}_Err("la task \'{self.nombres.mostrar(task_name)}\' '
            f'ya terminó, no se puede inyectar");'
        )
        out.append(f"{pad}    }} else {{")
        out.append(
            f"{pad}    InjectedSlots_{task_name}* {tmp_slots} = "
            f"(InjectedSlots_{task_name}*){ctx_code}->injected_slots;"
        )
        out.append(
            f"{pad}    if (false) {{"
            f"  // (b) defensivo/inalcanzable, ver docstring de _gen_inject_chan"
        )
        out.append(
            f'{pad}        {tmp_result} = {result_c}_Err("la task \'{self.nombres.mostrar(task_name)}\' '
            f'no declaró aceptar {chan_ty!r} por inyección");'
        )
        out.append(f"{pad}    }} else if ({tmp_slots}->{field} != NULL) {{")
        out.append(
            f"{pad}        // (c) ya hay una inyección de ese tipo pendiente sin consumir\n"
            f'{pad}        {tmp_result} = {result_c}_Err("la task \'{self.nombres.mostrar(task_name)}\' '
            f'ya tiene una inyección de {chan_ty!r} pendiente sin consumir '
            f'(accept_chan())");'
        )
        out.append(f"{pad}    }} else {{")
        # Éxito: el slot es una referencia más al canal, así que incref (como en
        # spawn). Sin esto, el scope de quien inyecta lo liberaba antes de que la
        # task lo leyera (use-after-free, TSan/ASan en 73_). La task suelta la
        # suya al consumirlo con accept_chan(), o su envoltorio drena el slot si
        # termina antes. En los caminos de Err el canal sigue siendo de quien
        # llama.
        out.append(f"{pad}        scar_chan_incref_{self._mangled_name(inner)}({chan_code});")
        out.append(f"{pad}        {tmp_slots}->{field} = {chan_code};")
        out.append(f"{pad}        {tmp_result} = {result_c}_Ok(true);")
        out.append(f"{pad}    }}")
        out.append(f"{pad}    }}")  # cierra el 'else' del recheck de 'finished' bajo el lock
        out.append(f"{pad}    pthread_mutex_unlock(&{ctx_code}->injected_lock);")
        out.append(f"{pad}}}")
        return tmp_result

    def _gen_accept_chan(self, expr: "Call", declared_ty: "TypeAnn", env, out, pad) -> str:
        """accept_chan(), como _accept_chan del intérprete. Corre dentro de la
        propia task, así que su TaskContext es __scar_ctx y la task es
        self.cur_fn_name (el checker garantiza que solo aparece dentro de una
        task). Lo llama LetStmt, con la anotación del `let` (Option<Chan<T>>,
        con T en el `accepts` de la task, ya validado).

        No bloquea: bajo injected_lock, si el slot de T tiene un canal lo saca
        (deja NULL) y devuelve Some(chan); si no, None."""
        if (
            declared_ty is None
            or declared_ty.name != "Option"
            or not declared_ty.args
            or declared_ty.args[0].name != CHAN_MARK
        ):
            raise CodegenError(
                "'accept_chan': se esperaba una anotación 'Option<Chan<T>>' "
                "en el 'let' -- type_checker.py debería haber rechazado "
                "esto antes de llegar al backend de C"
            )
        chan_ty = declared_ty.args[0]
        inner = chan_ty.args[0] if chan_ty.args else T_I32
        task_name = self.cur_fn_name
        slot_map = self.task_accept_slots.get(task_name, {})
        if self._mangled_name(inner) not in slot_map:
            # el checker ya garantiza que T está en el `accepts` de la task
            raise CodegenError(
                f"'accept_chan': la task '{task_name}' no declaró aceptar "
                f"{chan_ty!r} -- type_checker.py debería haber rechazado "
                f"esto antes de llegar al backend de C"
            )
        field = slot_map[self._mangled_name(inner)]
        opt_c = self.c_type(TypeAnn("Option", [chan_ty]))  # fuerza Option_Chan_<T> (y, en cascada, Chan_<T>)
        tmp_result = self._new_tmp()
        tmp_slots = self._new_tmp()
        out.append(f"{pad}{opt_c} {tmp_result};")
        out.append(f"{pad}pthread_mutex_lock(&__scar_ctx->injected_lock);")
        out.append(
            f"{pad}InjectedSlots_{task_name}* {tmp_slots} = "
            f"(InjectedSlots_{task_name}*)__scar_ctx->injected_slots;"
        )
        out.append(f"{pad}if ({tmp_slots}->{field} != NULL) {{")
        out.append(f"{pad}    {tmp_result} = {opt_c}_Some({tmp_slots}->{field});")
        out.append(f"{pad}    {tmp_slots}->{field} = NULL;")
        out.append(f"{pad}}} else {{")
        out.append(f"{pad}    {tmp_result} = {opt_c}_None();")
        out.append(f"{pad}}}")
        out.append(f"{pad}pthread_mutex_unlock(&__scar_ctx->injected_lock);")
        return tmp_result

    # ---- nombres para el envoltorio de pthread de cada task ----
    def _task_args_struct_name(self, name: str) -> str:
        return f"__scar_args_{name}"

    def _task_thread_fn_name(self, name: str) -> str:
        return f"__scar_thread_{name}"

    def _task_str_params(self, decl, params):
        """Los parámetros str de una task."""
        if not decl.is_task:
            return []
        return [p for p, t in zip(decl.params, params) if t.name == "str"]

    def _task_c_param_list(self, decl, params) -> str:
        """Firma de C de una task: sus parámetros más un bool oculto por cada
        parámetro str (_str_owned_flag_name), al final. La usan gen_fn, el
        prototipo de la task y _gen_task_support: tienen que coincidir."""
        parts = [f"{self.c_type(t)} {p.name}" for p, t in zip(decl.params, params)]
        parts += [f"bool {self._str_owned_flag_name(p.name)}" for p in self._task_str_params(decl, params)]
        return ", ".join(parts) or "void"

    def _gen_injected_slots_struct(self, decl: FnDecl):
        """Para una task con `accepts`: el struct InjectedSlots_<task>, con un
        campo por tipo aceptado (por task, porque cada una acepta un conjunto
        distinto). None si no tiene `accepts` (no paga nada).

        Llena self.task_accept_slots[decl.name] = {T interno -> campo}, que
        usan inject_chan()/accept_chan() para saber qué campo escribir o leer
        (el TaskHandle.injected_slots del intérprete, como struct de campos
        fijos). Se emite junto con task_args_typedefs, antes de decls y
        bodies: _gen_spawn y las funciones de Chan<T> lo necesitan completo."""
        if not decl.accepts:
            return None
        struct_name = f"InjectedSlots_{decl.name}"
        slot_index = {}
        field_lines = []
        for i, acc_ty in enumerate(decl.accepts):
            inner = acc_ty.args[0] if acc_ty.args else T_I32
            field_name = f"slot_{i}"
            # El tipo C de Chan<T> ya existe (_chan_c_type): se reusa.
            c_type = self._chan_c_type(acc_ty)
            field_lines.append(f"    {c_type} {field_name};")
            # `accepts Chan<i32>, Chan<i32>` repetido: gana el último slot (el
            # checker no lo rechaza hoy).
            slot_index[self._mangled_name(inner)] = field_name
        self.task_accept_slots[decl.name] = slot_index
        return (
            f"typedef struct {{\n" + "\n".join(field_lines) + f"\n"
            f"}} {struct_name};"
        )

    def _gen_task_support(self, decl: FnDecl):
        """Para una task: el struct de argumentos (en el heap, porque tiene que
        sobrevivir al frame de quien hace spawn; incluye el TaskContext* que
        el padre ya registró como hijo, ver _gen_spawn) y el wrapper
        `void* (*)(void*)` de pthread_create.

        El wrapper es el nursery: `sigsetjmp` marca el punto al que
        vuelven un panic propio, uno propagado por un `.join()` y la
        cancelación (scar_cancel_check en un safepoint). En los tres casos, y
        en el retorno normal, cancela a las hijas sin join. Empaqueta el
        resultado para `.join()`."""
        params, ret, args_struct, str_params, typedef_args = self._task_struct_args(decl)
        chan_params, hoisted_decls, unpack_lines, run_body = self._task_desempaque(
            decl, params, ret, str_params)
        (cancel_decref_block, untaken_args_block, hoisted_block,
         finished_block) = self._task_limpieza_cancelacion(
            decl, params, str_params, chan_params, hoisted_decls)
        return self._task_envoltorio(
            decl, args_struct, typedef_args, unpack_lines, run_body, cancel_decref_block,
            untaken_args_block, hoisted_block, finished_block)

    def _task_struct_args(self, decl):
        """El struct de argumentos de la task y sus parámetros str (con su bool
        de dueño)."""
        params, ret = self.task_sigs[decl.name]
        args_struct = self._task_args_struct_name(decl.name)
        str_params = self._task_str_params(decl, params)
        if params:
            field_lines = "\n".join(
                f"    {self.c_type(t)} {p.name};" for p, t in zip(decl.params, params)
            )
        else:
            # Un struct vacío no es C estándar; igual hace falta un puntero no-NULL
            # que liberar.
            field_lines = "    int __scar_unused;"
        # Un bool oculto por cada parámetro str: si esa llamada movió un str
        # propio (lo calcula _gen_spawn, ver _str_owned_flag_name).
        if str_params:
            field_lines += "\n" + "\n".join(
                f"    bool {self._str_owned_flag_name(p.name)};" for p in str_params
            )
        typedef_args = (
            f"typedef struct {{\n"
            f"    TaskContext* __scar_ctx_hija;\n"
            f"{field_lines}\n"
            f"}} {args_struct};"
        )
        return params, ret, args_struct, str_params, typedef_args

    def _task_desempaque(self, decl, params, ret, str_params):
        """Los parámetros Chan declarados fuera del sigsetjmp, el desempaquetado
        de __scar_args y la llamada al cuerpo con su valor de retorno."""
        # (C8) se asignan solo en algunas ramas y la pasada las devuelve siempre
        run_body = None
        # Si la task se cancela, el siglongjmp salta el decref de sus
        # parámetros Chan que emite el cuerpo: se declaran acá, fuera del bloque
        # sigsetjmp, y se decrementan abajo solo si hubo salto (jmp_rc != 0).
        # Son `volatile`: se escriben entre sigsetjmp y siglongjmp, y sin
        # volatile su valor al volver es indeterminado (con -O2 volvía NULL y el
        # Chan no se liberaba).
        chan_params = [
            (p, t) for p, t in zip(decl.params, params) if t.name == CHAN_MARK
        ]
        chan_param_names = {p.name for p, _t in chan_params}
        hoisted_decls = "\n".join(
            f"    {self.c_type(t)} volatile {p.name} = NULL;" for p, t in chan_params
        )

        unpack_lines = "\n".join(
            (
                f"    {p.name} = __scar_args->{p.name};"
                if p.name in chan_param_names
                else f"    {self.c_type(t)} {p.name} = __scar_args->{p.name};"
            )
            for p, t in zip(decl.params, params)
        )
        if str_params:
            unpack_lines += "\n" + "\n".join(
                f"    bool {self._str_owned_flag_name(p.name)} = "
                f"__scar_args->{self._str_owned_flag_name(p.name)};"
                for p in str_params
            )
        call_args_list = [p.name for p in decl.params] + [
            self._str_owned_flag_name(p.name) for p in str_params
        ]
        call_args = ", ".join(call_args_list)
        if ret.name == "void":
            run_body = f"    {decl.name}({call_args});\n    __scar_result = NULL;"
        elif ret.name in self.structs:
            # El struct que devuelve la task puede tener bloques en su arena, que
            # se libera enseguida: {T}_moveout los pasa a malloc antes de
            # entregarlo a `.join()`.
            run_body = (
                f"    {ret.name}* __scar_struct_ret = {decl.name}({call_args});\n"
                f"    __scar_result = (void*){ret.name}_moveout(__scar_struct_ret);"
            )
        else:
            c_ret = self.c_type(ret)
            ret_expr = "__scar_ret_val"
            if ret.name == "str" and not self.fresh_str_fns.get(decl.name, False):
                # Una task `-> str` que no devuelve siempre un buffer fresco (`return
                # x` con x prestado) metía en la caja un puntero ajeno, que join() o el
                # reap de una fire-and-forget liberaban: se copia. Si devolvía uno
                # propio solo en algunas ramas, esas lo pierden (pérdida acotada, mejor
                # que un free inválido).
                self.needs_str_concat = True
                ret_expr = 'scar_str_concat(__scar_ret_val, "")'
            # Un Vec<S>/Map<K,S>/Option<S>/Result<S> que sale de la task puede
            # llevar bloques de su arena: se pasan a malloc antes de entregarlo
            detach = "".join(l + "\n" for l in self._detach_lines(ret, "__scar_ret_val", "    "))
            run_body = (
                f"    {c_ret} __scar_ret_val = {decl.name}({call_args});\n"
                f"{detach}"
                f"    {c_ret}* __scar_boxed = malloc(sizeof({c_ret}));\n"
                f"    *__scar_boxed = {ret_expr};\n"
                f"    __scar_result = (void*)__scar_boxed;"
            )
        return chan_params, hoisted_decls, unpack_lines, run_body

    def _task_limpieza_cancelacion(self, decl, params, str_params, chan_params,
                                   hoisted_decls):
        """Lo que se suelta si la task se cancela: el decref de sus Chan, los
        argumentos que el cuerpo no llegó a tomar y los slots de accept_chan."""
        # (C8) se asignan solo en algunas ramas y la pasada las devuelve siempre
        finished_block = None
        cancel_decref_block = ""
        if chan_params:
            cancel_decref_lines = "\n".join(
                f"        if ({p.name}) scar_chan_decref_"
                f"{self._mangled_name(t.args[0] if t.args else T_I32)}({p.name});"
                for p, t in chan_params
            )
            cancel_decref_block = (
                f"    if (__scar_jmp_rc != 0) {{\n"
                f"        // cancelacion/panic: el cuerpo nunca llego a su\n"
                f"        // propio decref (ver comentario mas arriba)\n"
                f"{cancel_decref_lines}\n"
                f"    }}\n"
            )
        # __scar_args es dueño de los argumentos hasta que el cuerpo los
        # recibe. El safepoint de prólogo va primero: si cancela antes, se
        # liberan desde __scar_args (antes se perdían, p. ej. en la
        # fire-and-forget que main cancela al salir).
        str_param_names = {p.name for p in str_params}
        untaken_lines = []
        for p, t in zip(decl.params, params):
            src = f"__scar_args->{p.name}"
            if t.name == VEC_MARK:
                inner = t.args[0] if t.args else T_I32
                untaken_lines.append(f"        scar_vec_free_{self._mangled_name(inner)}({src});")
            elif t.name == MAP_MARK:
                k_ty = t.args[0] if t.args else T_I32
                v_ty = t.args[1] if len(t.args) > 1 else T_I32
                untaken_lines.append(f"        scar_map_free_{k_ty.name}_{self._mangled_name(v_ty)}({src});")
            elif t.name == CHAN_MARK:
                inner = t.args[0] if t.args else T_I32
                untaken_lines.append(f"        if ({src}) scar_chan_decref_{self._mangled_name(inner)}({src});")
            elif t.name == "str" and p.name in str_param_names:
                flag = self._str_owned_flag_name(p.name)
                untaken_lines.append(f"        if (__scar_args->{flag}) scar_free((char*){src});")
            elif t.name in self.structs:
                untaken_lines.append(f"        {t.name}_free({src});")
            elif self._is_option_struct(t):
                untaken_lines.append(f"        {self._generic_c_type(t)}_free({src});")
        untaken_args_block = (
            f"    if (__scar_jmp_rc != 0 && !__scar_args_tomados) {{\n"
            f"        // cancelada antes de que el cuerpo tomara sus argumentos\n"
            + "".join(l + "\n" for l in untaken_lines)
            + f"        free(__scar_args);\n"
            f"    }}\n"
        )
        hoisted_block = f"{hoisted_decls}\n" if hoisted_decls else ""
        # Un inject_chan() que llegó a escribir un slot que la task nunca
        # consumió con accept_chan() deja una referencia extra: se drena acá,
        # en los tres finales (retorno, panic, cancelación). Drenar y marcar
        # `finished` van bajo el mismo injected_lock: inject_chan() lee
        # `finished` sin lock y lo vuelve a chequear con el lock tomado (ver
        # _gen_inject_chan), así no puede escribir un slot ya drenado.
        accept_slot_map = self.task_accept_slots.get(decl.name, {})
        if accept_slot_map:
            drain_lines = "\n".join(
                f"        if (__scar_slots->{field} != NULL) {{\n"
                f"            scar_chan_decref_{inner}(__scar_slots->{field});\n"
                f"            __scar_slots->{field} = NULL;\n"
                f"        }}"
                for inner, field in accept_slot_map.items()
            )
            finished_block = (
                f"    pthread_mutex_lock(&__scar_task_ctx->injected_lock);\n"
                f"    {{\n"
                f"        InjectedSlots_{decl.name}* __scar_slots =\n"
                f"            (InjectedSlots_{decl.name}*)__scar_task_ctx->injected_slots;\n"
                f"{drain_lines}\n"
                f"    }}\n"
                f"    atomic_store(&__scar_task_ctx->finished, 1);\n"
                f"    pthread_mutex_unlock(&__scar_task_ctx->injected_lock);\n"
                f"    scar_vivos_liberar_registro();\n"
                f"    atomic_fetch_sub(&scar_hilos_vivos, 1);\n"
                f"    scar_ctx_mark_done(__scar_task_ctx);\n"
            )
        else:
            finished_block = (
                "    atomic_store(&__scar_task_ctx->finished, 1);\n"
                "    scar_vivos_liberar_registro();\n"
                "    atomic_fetch_sub(&scar_hilos_vivos, 1);\n"
                "    scar_ctx_mark_done(__scar_task_ctx);\n"
            )
        return cancel_decref_block, untaken_args_block, hoisted_block, finished_block

    def _task_envoltorio(self, decl, args_struct, typedef_args, unpack_lines, run_body,
                         cancel_decref_block, untaken_args_block, hoisted_block,
                         finished_block):
        """El envoltorio del thread (sigsetjmp, safepoint, cuerpo, limpieza) y
        su prototipo."""
        thread_fn_name = self._task_thread_fn_name(decl.name)
        def_wrapper = (
            f"static void* {thread_fn_name}(void* __scar_arg) {{\n"
            f"    {args_struct}* __scar_args = ({args_struct}*)__scar_arg;\n"
            f"    TaskContext* __scar_task_ctx = __scar_args->__scar_ctx_hija;\n"
            f"    __scar_ctx = __scar_task_ctx;\n"
            f"{'    scar_pila_iniciar();' + chr(10) if getattr(self, '_fns_recursivas', None) else ''}"
            f"    SCAR_RAND_HILO(__scar_task_ctx->rand_semilla);\n"
            f"    void* __scar_result = NULL;\n"
            f"{hoisted_block}"
            f"    volatile int __scar_args_tomados = 0;\n"
            f"    int __scar_jmp_rc = sigsetjmp(__scar_task_ctx->panic_env, 1);\n"
            f"    if (__scar_jmp_rc == 0) {{\n"
            f"        scar_safepoint();  // safepoint de prologo\n"
            f"{unpack_lines}\n"
            f"        free(__scar_args);\n"
            f"        __scar_args_tomados = 1;\n"
            f"{run_body}\n"
            f"        atomic_store(&__scar_task_ctx->completed, 1);\n"
            f"    }}\n"
            f"{untaken_args_block}"
            f"{cancel_decref_block}"
            f"    // panic propio, panic propagado desde una hija via .join(), o\n"
            f"    // cancelacion: en los tres casos, cascada a hijos propios.\n"
            f"    scar_cancel_children(__scar_task_ctx);\n"
            f"    // punto unico de liberacion del arena de ESTA tarea:\n"
            f"    // return normal, panic y cancelacion pasan los tres por aca. Si\n"
            f"    // el retorno era un struct, ya se copio afuera de la arena arriba,\n"
            f"    // asi que esto nunca invalida __scar_result.\n"
            f"    scar_arena_free(&__scar_task_ctx->arena);\n"
            f"    // unico punto de salida del wrapper -- cubre las tres vias\n"
            f"    // (normal/panic/cancelacion) por igual, a diferencia de\n"
            f"    // 'completed' de arriba.\n"
            f"{finished_block}"
            f"{'    scar_pila_terminar();' + chr(10) if getattr(self, '_fns_recursivas', None) else ''}"
            f"    return __scar_result;\n"
            f"}}"
        )
        forward_decl_wrapper = f"static void* {thread_fn_name}(void* __scar_arg);"
        return forward_decl_wrapper, typedef_args, def_wrapper
