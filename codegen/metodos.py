"""Mixin Metodos de Codegen (paso C6): los métodos de los tipos del lenguaje
(Vec, Map, Chan, Pipe, File, Socket, Listener, str, Option/Result): obj.m(...)
de SCAR a C.
"""

from parser import (marca_new_generico, 
    NumLit, StrLit, BoolLit, Ident, Call, FieldAccess, ArrayLit, MethodCall,
)
from types_ import TypeAnn, T_I32, T_STR, T_VOID

from . import runtime as runtime_c
from .comun import (
    panic_c,
    CHAN_MARK, CodegenError, FILE_MARK, LISTENER_MARK, MAP_MARK, PIPE_MARK,
    SOCKET_MARK, TASK_MARK, VEC_MARK,
)


class Metodos:
    def _gen_method_call(self, expr: "MethodCall", env, out, pad) -> str:
        obj_ty = self.infer(expr.obj, env)
        if obj_ty.name == CHAN_MARK:
            return self._gen_chan_method(expr, obj_ty, env, out, pad)
        if obj_ty.name == PIPE_MARK:
            return self._gen_pipe_method(expr, env, out, pad)
        if obj_ty.name == FILE_MARK:
            return self._gen_file_method(expr, env, out, pad)
        if obj_ty.name == SOCKET_MARK:
            return self._gen_socket_method(expr, env, out, pad)
        if obj_ty.name == LISTENER_MARK:
            return self._gen_listener_method(expr, env, out, pad)
        if obj_ty.name in (VEC_MARK, MAP_MARK):
            # un Vec/Map fresco que nadie guarda (`f().len()`, `mk().vals.len()`):
            # el método se llama sobre un temporal que se libera al terminar la
            # sentencia
            receptor_fresco = isinstance(expr.obj, (Call, ArrayLit)) or (
                isinstance(expr.obj, FieldAccess) and self._campo_de_temporal(expr.obj, env) is not None)
            if (self._can_capture_arg_temps and receptor_fresco
                    and self._let_creates_fresh_owner(expr.obj, marca_new_generico(expr.obj), env)):
                drop = self._vivo_drop_fn(obj_ty, "plain")
                if drop is not None:
                    tmp = self._new_tmp()
                    out.append(f"{pad}{self.c_type(obj_ty)} {tmp} = {self.gen_expr(expr.obj, env, out, pad)};")
                    self.pending_expr_temps.append(f"dropfree:{drop}:{tmp}")
                    env = dict(env)
                    env[tmp] = obj_ty
                    expr = MethodCall(Ident(tmp), expr.method, expr.args)
        if obj_ty.name == VEC_MARK:
            return self._gen_vec_method(expr, obj_ty, env, out, pad)
        if obj_ty.name == MAP_MARK:
            return self._gen_map_method(expr, obj_ty, env, out, pad)
        if obj_ty.name == "str":
            return self._gen_str_method(expr, env, out, pad)
        if obj_ty.name in ("Result", "Option"):
            return self._gen_result_option_method(expr, obj_ty, env, out, pad)
        if obj_ty.name != TASK_MARK:
            raise CodegenError(
                f"'.{expr.method}()' sobre {obj_ty!r} todavía no soportado por el "
                "backend de C."
            )
        if expr.method != "join":
            raise CodegenError(f"Task no tiene método '.{expr.method}()' en el backend de C")
        inner_ty = obj_ty.args[0] if obj_ty.args else T_VOID
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        # scar_join_wait() espera en la condvar de la tarea; si a quien hace join
        # lo cancelan, sale, y si la tarea joineada hizo panic, lo re-lanza acá
        # (no vuelve)
        if inner_ty.name == "void":
            out.append(f"{pad}scar_join_wait({obj_code}.ctx);")
            return "((void)0)"
        tmp_void = self._new_tmp()
        out.append(f"{pad}void* {tmp_void} = scar_join_wait({obj_code}.ctx);")
        c_inner = self.c_type(inner_ty)
        if inner_ty.name in self.structs:
            # un struct de usuario ya es un puntero: el void* del join es ese puntero
            return f"(({c_inner}){tmp_void})"
        tmp_val = self._new_tmp()
        out.append(f"{pad}{c_inner} {tmp_val} = *({c_inner}*){tmp_void};")
        out.append(f"{pad}free({tmp_void});")
        return tmp_val

    def _gen_chan_method(self, expr: "MethodCall", obj_ty, env, out, pad) -> str:
        """.send()/.recv()/.close()/.sender()/.receiver() de Chan<T> ->
        scar_chan_*_<T>(). .sender()/.receiver() devuelven el mismo puntero (un
        canal es una referencia compartida), como el intérprete."""
        inner = obj_ty.args[0] if obj_ty.args else T_I32
        self.c_type(obj_ty)  # fuerza la monomorfización de Chan_<T> si aún no ocurrió
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if expr.method == "send":
            if inner.name in ("Option", "Result"):
                # `c.send(None)` necesita saber de qué Option es
                arg_code = self.gen_expr(expr.args[0], env, out, pad, expected_ty=inner)
            else:
                arg_code = self.gen_expr(expr.args[0], env, out, pad)
            # Qué pasa con el valor que se manda: un str se copia al nodo, así que el
            # del emisor sigue siendo suyo (y lo libera su scope); un struct se mueve
            # al nodo, y _struct_moved_into decide si va tal cual o como
            # copia; Vec/Map, Option/Result: la dueña deja de serlo. El checker lo da
            # por movido en todos los casos, así que no se puede usar después.
            if inner.name in self.structs:
                arg_code = self._struct_moved_into(expr.args[0], inner, arg_code, env, out, pad)
            elif inner.name == CHAN_MARK:
                # Chan<Chan<T>>: el canal de adentro viaja con su propia referencia (como
                # al guardarlo en un Vec)
                arg_code = self._chan_para_contenedor(
                    expr.args[0], inner.args[0] if inner.args else T_I32, arg_code, env, out, pad)
            elif inner.name in ("Option", "Result"):
                # como en Vec<Option<T>>: lo propio se entrega, lo prestado se copia (la
                # variable de origen sigue siendo de quien era)
                if (self._campo_compuesto_con_dueno(inner)
                        and not self._valor_compuesto_propio(expr.args[0], inner, env)):
                    arg_code = self._clone_value_expr(inner, arg_code)
            elif inner.name != "str":
                self._note_owner_transfer(expr.args[0], inner)
            if inner.name == "str":
                # scar_chan_send_str copia el valor al nodo: un str fresco pasado directo
                # (concatenación, s[i], llamada, `algo?`) va a un temporal que se libera al
                # terminar la sentencia
                arg_code = self._capture_fresh_str_concat_arg(expr.args[0], arg_code, env, out, pad)
            out.append(f"{pad}scar_chan_send_{self._mangled_name(inner)}({obj_code}, {arg_code});")
            return "((void)0)"
        if expr.method == "recv":
            return f"scar_chan_recv_{self._mangled_name(inner)}({obj_code})"
        if expr.method == "try_recv":
            return f"scar_chan_try_recv_{self._mangled_name(inner)}({obj_code})"
        if expr.method == "close":
            out.append(f"{pad}scar_chan_close_{self._mangled_name(inner)}({obj_code});")
            return "((void)0)"
        if expr.method in ("sender", "receiver"):
            return obj_code
        raise CodegenError(f"Chan no tiene método '.{expr.method}()' en el backend de C")

    def _chan_para_contenedor(self, arg_expr, chan_inner, code, env, out, pad):
        """Un Chan que se guarda en un Vec o un Map: el contenedor necesita su
        propia referencia. Si el canal es de alguien (una variable, un campo),
        incref; si es nuevo (`v.push(chan_new())`), esa única referencia pasa al
        contenedor. El C de la expresión se evalúa una sola vez."""
        if self._let_creates_fresh_owner(arg_expr, marca_new_generico(arg_expr), env):
            return code
        if not self._RE_C_IDENT.fullmatch(code) and not self._expr_simple(arg_expr):
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(TypeAnn(CHAN_MARK, [chan_inner]))} {tmp} = {code};")
            code = tmp
        out.append(f"{pad}scar_chan_incref_{self._mangled_name(chan_inner)}({code});")
        return code

    def _gen_pipe_method(self, expr: "MethodCall", env, out, pad) -> str:
        """.read_fd()/.write_fd() de Pipe: los campos de ScarPipe, como en el
        intérprete."""
        if expr.method not in ("read_fd", "write_fd"):
            raise CodegenError(f"Pipe no tiene método '.{expr.method}()' en el backend de C")
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        return f"{obj_code}.{expr.method}"

    def _gen_file_method(self, expr: "MethodCall", env, out, pad) -> str:
        """.read_all()/.write()/.close() de File -> scar_file_*(), como ScarFile
        en el intérprete."""
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if expr.method == "read_all":
            self.c_type(TypeAnn("Result", [T_STR]))  # registra Result_str
            self.needs_file_io = True
            return f"scar_file_read_all({obj_code})"
        hecho = self._metodo_de_bytes(expr, obj_code, env, out, pad, "file", "needs_file_io")
        if hecho is not None:
            return hecho
        if expr.method == "close":
            self.needs_file_io = True
            out.append(f"{pad}scar_file_close({obj_code});")
            return "((void)0)"
        raise CodegenError(f"File no tiene método '.{expr.method}()' en el backend de C")

    def _metodo_de_bytes(self, expr, obj_code, env, out, pad, tipo, flag):
        """.read_bytes(n), .write(s) y .write_bytes(v) de un File o un Socket
        (`tipo` "file" o "socket"; `flag`, el needs_* de su runtime, que se emite
        entero y también usa Result_str/_i32). None si es otro método. El str
        armado de un write (`f.write(a + b)`) y el Vec de un write_bytes van a un
        temporal."""
        if expr.method == "read_bytes":
            n_code = self.gen_expr(expr.args[0], env, out, pad)
            setattr(self, flag, True)
            self._read_bytes_usados.add(tipo)
            self.c_type(TypeAnn("Result", [TypeAnn(VEC_MARK, [T_I32])]))  # registra Vec_i32/Result
            self.c_type(TypeAnn("Result", [T_STR]))
            self.c_type(TypeAnn("Result", [T_I32]))
            return f"scar_{tipo}_read_bytes({obj_code}, {n_code})"
        if expr.method == "write":
            arg_code = self.gen_expr(expr.args[0], env, out, pad)
            arg_code = self._capture_fresh_str_concat_arg(expr.args[0], arg_code, env, out, pad)
            self.c_type(TypeAnn("Result", [T_I32]))  # registra Result_i32
            setattr(self, flag, True)
            return f"scar_{tipo}_write({obj_code}, {arg_code})"
        if expr.method == "write_bytes":
            arg_code = self.gen_expr(expr.args[0], env, out, pad)
            arg_code = self._capture_fresh_owned_arg(expr.args[0], arg_code, env, out, pad)
            setattr(self, flag, True)
            self._read_bytes_usados.add(tipo + "_w")
            self.c_type(TypeAnn("Result", [TypeAnn(VEC_MARK, [T_I32])]))
            self.c_type(TypeAnn("Result", [T_STR]))
            self.c_type(TypeAnn("Result", [T_I32]))
            return f"scar_{tipo}_write_bytes({obj_code}, {arg_code})"
        return None

    def _gen_socket_method(self, expr: "MethodCall", env, out, pad) -> str:
        """.read()/.write()/.close() de Socket -> scar_socket_*(), como ScarSocket
        en el intérprete. .read() espera con select(), timeout y cancelación."""
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if expr.method == "read":
            self.c_type(TypeAnn("Result", [T_STR]))  # registra Result_str
            self.needs_net_io = True
            return f"scar_socket_read({obj_code})"
        hecho = self._metodo_de_bytes(expr, obj_code, env, out, pad, "socket", "needs_net_io")
        if hecho is not None:
            return hecho
        if expr.method == "close":
            self.needs_net_io = True
            out.append(f"{pad}scar_socket_close({obj_code});")
            return "((void)0)"
        raise CodegenError(f"Socket no tiene método '.{expr.method}()' en el backend de C")

    def _read_bytes_helpers_c(self):
        """Lectura binaria a un Vec<i32> de bytes 0..255, con el contrato del
        intérprete (read_bytes). Mientras junta bytes, el Vec está en el registro
        de dueñas vivas, para que una cancelación o un panic en la espera lo
        suelte."""
        vec = self.c_type(TypeAnn(VEC_MARK, [T_I32]))
        res = self.c_type(TypeAnn("Result", [TypeAnn(VEC_MARK, [T_I32])]))
        panic = panic_c(self.has_tasks)
        ahora = "scar_monotonic_now()" if self.has_tasks else "__scar_io_monotonic_now()"
        cancel = "        scar_cancel_check();\n" if self.has_tasks else ""
        c = (
            f"static void scar_drop_bytes_tmp(void *slot) {{ scar_vec_free_i32(*({vec}*)slot); }}\n"
            f"static {res} scar_bytes_err(const char *msg) {{\n"
            f"    size_t n = strlen(msg);\n"
            f"    char *e = scar_malloc(n + 1);\n"
            f"    memcpy(e, msg, n + 1);\n"
            f"    return {res}_Err(e);\n"
            f"}}\n"
        )
        if "file_w" in self._read_bytes_usados or "socket_w" in self._read_bytes_usados:
            c += runtime_c.texto(
                "read_bytes_vec",
                VEC=str(vec),
                PANIC=str(panic),
            )
        if "file_w" in self._read_bytes_usados:
            c += runtime_c.texto(
                "file_write_bytes",
                VEC=str(vec),
            )
        if "socket_w" in self._read_bytes_usados:
            c += runtime_c.texto(
                "socket_write_bytes",
                VEC=str(vec),
            )
        if "file" in self._read_bytes_usados:
            c += runtime_c.texto(
                "file_read_bytes",
                RES=str(res),
                PANIC=str(panic),
                VEC=str(vec),
            )
        if "socket" in self._read_bytes_usados:
            c += runtime_c.texto(
                "socket_read_bytes",
                RES=str(res),
                PANIC=str(panic),
                VEC=str(vec),
                AHORA=str(ahora),
                CANCEL=str(cancel),
            )
        return c

    def _gen_listener_method(self, expr: "MethodCall", env, out, pad) -> str:
        """.accept()/.close() de Listener -> scar_listener_*(). .accept() espera
        con select(), timeout y cancelación, como scar_socket_read()."""
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if expr.method == "accept":
            self.c_type(TypeAnn("Result", [TypeAnn(SOCKET_MARK)]))  # registra Result_Socket
            self.needs_net_io = True
            return f"scar_listener_accept({obj_code})"
        if expr.method == "close":
            self.needs_net_io = True
            out.append(f"{pad}scar_listener_close({obj_code});")
            return "((void)0)"
        raise CodegenError(f"Listener no tiene método '.{expr.method}()' en el backend de C")

    def _gen_vec_method(self, expr: "MethodCall", obj_ty, env, out, pad) -> str:
        """.push()/.get()/.pop()/.set()/.replace()/.len() de Vec<T> ->
        scar_vec_*_<T>(). Las que mutan reciben la dirección del struct Vec del
        que llama, así que obj_code tiene que ser una lvalue de C (una variable,
        un campo, un índice): se valida acá con un mensaje claro en vez de dejar
        que gcc falle con `&` de un rvalue."""
        inner = obj_ty.args[0] if obj_ty.args else T_I32
        self.c_type(obj_ty)  # fuerza la monomorfización de Vec_<T> si aún no ocurrió
        # _mangled_name y no inner.name, y el mismo nombre que las definiciones de
        # _vec_c_type, o el C no linkea
        name_part = self._mangled_name(inner)
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if expr.method in ("push", "pop", "set", "replace"):
            if not self._is_c_lvalue(obj_code):
                raise CodegenError(
                    f"'.{expr.method}()' sobre Vec requiere una variable o campo "
                    f"real (no una expresión intermedia); asignalo a una variable "
                    f"con 'let' primero."
                )
        if expr.method in ("push", "set", "replace"):
            # replace toma el valor como set; además devuelve el viejo
            value_arg = expr.args[1] if expr.method in ("set", "replace") else expr.args[0]
            idx_pre = None
            if expr.method in ("set", "replace"):
                # el índice se evalúa antes que el valor, como en el intérprete
                idx_pre = self.gen_expr(expr.args[0], env, out, pad)
                if not self._expr_simple(expr.args[0]):
                    t_idx = self._new_tmp()
                    out.append(f"{pad}int32_t {t_idx} = {idx_pre};")
                    idx_pre = t_idx
            if inner.name in ("Option", "Result"):
                # `v.push(None)` necesita saber de qué Option es
                arg_code = self.gen_expr(value_arg, env, out, pad, expected_ty=inner)
            else:
                arg_code = self.gen_expr(value_arg, env, out, pad)
            # set() transfiere el valor que entra igual que push(); además libera el
            # viejo (scar_vec_set). Con T struct, el bloque de donde se copiaron los
            # campos (shell_free_var) se suelta después de emitir la llamada.
            shell_free_var = None
            if inner.name == "str":
                # str: el Vec es dueño de un texto propio. Un str fresco sin otra dueña
                # (concatenación, s[i], una llamada) se mueve tal cual; lo demás (un
                # literal, una variable, que sigue siendo de quien era) se copia con
                # scar_str_concat(x, "").
                if not (self._is_fresh_str_concat_expr(value_arg, env) or self._is_fresh_str_call(value_arg)):
                    arg_code = self._capture_fresh_str_concat_arg(value_arg, arg_code, env, out, pad)
                    arg_code = f'scar_str_concat({arg_code}, "")'
                    self.needs_str_concat = True
            elif inner.name in self.structs:
                # struct: scar_vec_push_<T> recibe el struct por valor y lo copia al slot;
                # esa copia mueve todos sus campos con dueño al Vec. El bloque de donde
                # salió (shell) queda vacío y se suelta sin liberar sus campos (con
                # {T}_free serían double free). arg_code puede ser una llamada (X_new(...)):
                # va a un temporal para evaluarla una sola vez. La variable de origen deja
                # de ser dueña (_note_owner_transfer). `v.push(c.dato)` con c viva saca el
                # campo a un temporal y c se libera entera al salir.
                tomado = None
                if isinstance(value_arg, FieldAccess):
                    tomado = self._take_owned_field(value_arg, inner, arg_code, env, out, pad)
                if tomado is not None:
                    arg_code = f"*{tomado}"
                    shell_free_var = tomado
                    if expr.method == "push":
                        out.append(f"{pad}scar_vec_push_{name_part}(&{obj_code}, {arg_code});")
                    elif expr.method == "replace":
                        viejo = self._new_tmp()
                        out.append(f"{pad}{inner.name}* {viejo} = scar_vec_replace_{name_part}(&{obj_code}, {idx_pre}, {arg_code});")
                        out.append(f"{pad}scar_blk_release({shell_free_var});")
                        return viejo
                    else:
                        out.append(f"{pad}scar_vec_set_{name_part}(&{obj_code}, {idx_pre}, {arg_code});")
                    out.append(f"{pad}scar_blk_release({shell_free_var});")
                    return "((void)0)"
                tmp = self._new_tmp()
                out.append(f"{pad}{inner.name}* {tmp} = {arg_code};")
                arg_code = f"*{tmp}"
                # el origen de la variable se consulta antes de _note_owner_transfer, que
                # la desmarca
                shell_is_plain_malloc = (
                    isinstance(value_arg, Ident)
                    and self._owner_origin(value_arg.name) == "plain"
                )
                self._note_owner_transfer(value_arg, inner)
                # el shell vacío se suelta siempre: si era de la arena, scar_blk_release
                # no hace nada
                shell_free_var = tmp
            elif inner.name in ("Option", "Result"):
                # Vec<Option<T>>: como un campo Option de un struct: lo propio
                # se entrega, lo prestado se copia; un Option de números va tal cual
                if (self._campo_compuesto_con_dueno(inner)
                        and not self._valor_compuesto_propio(value_arg, inner, env)):
                    arg_code = self._clone_value_expr(inner, arg_code)
            elif inner.name in (VEC_MARK, MAP_MARK):
                # Vec<Vec<T>> / Vec<Map<K,V>>: el de afuera se queda con el de adentro
                # (_valor_entregado: uno fresco tal cual, una dueña transferida, un campo
                # sacado, uno prestado copiado)
                arg_code = self._valor_entregado(value_arg, inner, arg_code, env, out, pad)
            elif inner.name == CHAN_MARK:
                # Chan<T>: el Vec guarda una referencia más (incref). Quien lo pushea
                # sigue siendo dueño de la suya, y el Vec puede sobrevivir a su scope.
                chan_inner = inner.args[0] if inner.args else T_I32
                arg_code = self._chan_para_contenedor(expr.args[0], chan_inner, arg_code, env, out, pad)
            if expr.method == "replace":
                viejo = self._new_tmp()
                ret_c = f"{inner.name}*" if inner.name in self.structs else self.c_type(inner)
                out.append(f"{pad}{ret_c} {viejo} = scar_vec_replace_{name_part}(&{obj_code}, {idx_pre}, {arg_code});")
                if shell_free_var is not None:
                    out.append(f"{pad}scar_blk_release({shell_free_var});")
                return viejo
            if expr.method == "push":
                out.append(f"{pad}scar_vec_push_{name_part}(&{obj_code}, {arg_code});")
            else:
                out.append(f"{pad}scar_vec_set_{name_part}(&{obj_code}, {idx_pre}, {arg_code});")
            if shell_free_var is not None:
                out.append(f"{pad}scar_blk_release({shell_free_var});")
            return "((void)0)"
        if expr.method == "get":
            idx_code = self.gen_expr(expr.args[0], env, out, pad)
            return f"scar_vec_get_{name_part}({obj_code}, {idx_code})"
        if expr.method == "pop":
            return f"scar_vec_pop_{name_part}(&{obj_code})"
        if expr.method == "len":
            return f"scar_vec_len_{name_part}({obj_code})"
        raise CodegenError(f"Vec no tiene método '.{expr.method}()' en el backend de C")

    @staticmethod
    def _is_c_lvalue(code: str) -> bool:
        """True si `code` (C ya generado) es una lvalue con dirección propia: un
        identificador, o una cadena de `.campo`/`->campo`/`[índice]` sobre uno.
        Un paréntesis delata una llamada u otra expresión intermedia."""
        return "(" not in code and ")" not in code

    def _gen_map_method(self, expr: "MethodCall", obj_ty, env, out, pad) -> str:
        """.set()/.get()/.remove()/.len() de Map<K,V> -> scar_map_*_<K>_<V>()."""
        key_ty = obj_ty.args[0] if obj_ty.args else T_I32
        val_ty = obj_ty.args[1] if len(obj_ty.args) > 1 else T_I32
        self.c_type(obj_ty)  # fuerza la monomorfización de Map_<K>_<V> si aún no ocurrió
        # _mangled_name y no val_ty.name, y el mismo nombre que las definiciones
        # de _map_c_type, o el C no linkea
        suffix = f"{key_ty.name}_{self._mangled_name(val_ty)}"
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if expr.method == "set":
            key_code = self.gen_expr(expr.args[0], env, out, pad)
            if not self._expr_simple(expr.args[0]) and not self._expr_simple(expr.args[1]):
                # la clave se evalúa antes que el valor (ver _secuenciar)
                t_key = self._new_tmp()
                out.append(f"{pad}{self.c_type(self.infer(expr.args[0], env))} {t_key} = {key_code};")
                key_code = t_key
            if val_ty.name in ("Option", "Result"):
                # `m.set(k, None)` necesita saber de qué Option es
                val_code = self.gen_expr(expr.args[1], env, out, pad, expected_ty=val_ty)
            else:
                val_code = self.gen_expr(expr.args[1], env, out, pad)
            # Clave o valor str: el Map es dueño de un texto propio. Un str fresco
            # (concatenación, s[i], una llamada) se mueve; lo demás (un literal, una
            # variable que sigue siendo de quien era) se copia con scar_str_concat(x,
            # "").
            if key_ty.name == "str":
                if not (self._is_fresh_str_concat_expr(expr.args[0], env) or self._is_fresh_str_call(expr.args[0])):
                    key_code = self._capture_fresh_str_concat_arg(expr.args[0], key_code, env, out, pad)
                    key_code = f'scar_str_concat({key_code}, "")'
                    self.needs_str_concat = True
            if val_ty.name == "str":
                if not (self._is_fresh_str_concat_expr(expr.args[1], env) or self._is_fresh_str_call(expr.args[1])):
                    val_code = self._capture_fresh_str_concat_arg(expr.args[1], val_code, env, out, pad)
                    val_code = f'scar_str_concat({val_code}, "")'
                    self.needs_str_concat = True
            else:
                # V struct: set() transfiere el puntero (la raíz deja de ser dueña, como
                # en el checker). `m.set(k, c.dato)` con c viva saca el campo a un
                # temporal, y c se libera entera al salir.
                tomado = None
                if val_ty.name in ("Option", "Result"):
                    # Map<K, Option<T>>: como Vec<Option<T>>
                    if (self._campo_compuesto_con_dueno(val_ty)
                            and not self._valor_compuesto_propio(expr.args[1], val_ty, env)):
                        val_code = self._clone_value_expr(val_ty, val_code)
                elif val_ty.name in (VEC_MARK, MAP_MARK):
                    # Map<K,Vec<T>> / Map<K,Map<..>>: la misma regla que el push de
                    # Vec<Vec<T>>
                    val_code = self._valor_entregado(expr.args[1], val_ty, val_code, env, out, pad)
                elif isinstance(expr.args[1], FieldAccess):
                    tomado = self._take_owned_field(expr.args[1], val_ty, val_code, env, out, pad)
                if val_ty.name in (VEC_MARK, MAP_MARK, "Option", "Result"):
                    pass
                elif tomado is not None:
                    val_code = tomado
                else:
                    self._note_owner_transfer(expr.args[1], val_ty)
                if val_ty.name == CHAN_MARK:
                    # Chan<T>: el Map guarda una referencia más (incref), como el push de
                    # Vec
                    chan_inner = val_ty.args[0] if val_ty.args else T_I32
                    val_code = self._chan_para_contenedor(expr.args[1], chan_inner, val_code, env, out, pad)
            out.append(f"{pad}scar_map_set_{suffix}({obj_code}, {key_code}, {val_code});")
            return "((void)0)"
        if expr.method == "get":
            key_code = self.gen_expr(expr.args[0], env, out, pad)
            return f"scar_map_get_{suffix}({obj_code}, {key_code})"
        if expr.method == "remove":
            key_code = self.gen_expr(expr.args[0], env, out, pad)
            return f"scar_map_remove_{suffix}({obj_code}, {key_code})"
        if expr.method == "len":
            return f"scar_map_len_{suffix}({obj_code})"
        raise CodegenError(f"Map no tiene método '.{expr.method}()' en el backend de C")

    def _gen_result_option_method(self, expr, obj_ty, env, out, pad) -> str:
        """is_ok/is_err/err/is_some/is_none/unwrap_or. El Result/Option se evalúa
        una vez; si es un valor fresco que nadie guarda, se libera al terminar la
        sentencia."""
        code = self.gen_expr(expr.obj, env, out, pad)
        code = self._capture_fresh_owned_arg(expr.obj, code, env, out, pad)
        if not self._RE_C_IDENT.fullmatch(code) and not self._expr_simple(expr.obj):
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(obj_ty)} {tmp} = {code};")
            code = tmp
        m = expr.method
        if m in ("is_ok", "is_some"):
            return f"({code}.tag == 1)"
        if m in ("is_err", "is_none"):
            return f"({code}.tag != 1)"
        if m == "err":
            self.needs_str_concat = True
            return f'scar_str_concat(({code}.tag == 1 || {code}.err == NULL) ? "" : {code}.err, "")'
        if m == "unwrap_or":
            def_code = self.gen_expr(expr.args[0], env, out, pad, expected_ty=obj_ty.args[0])
            return f"({code}.tag == 1 ? {code}.value : ({def_code}))"
        raise CodegenError(f"{obj_ty.name} no tiene método '.{m}()' en el backend de C")

    def _gen_str_method(self, expr: "MethodCall", env, out, pad) -> str:
        """Métodos de solo lectura de str -> funciones de <string.h> (o una
        expresión corta cuando no hay una directa). obj y arg van siempre a
        temporales: el código de C podría tener efectos (scar_str_concat) y
        sustituirlo más de una vez lo evaluaría más de una vez."""
        tmp_o = self._new_tmp()
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if (self._es_lugar(expr.obj) and expr.args
                and self._alcanza_lugar(expr.args[0], expr.obj)):
            # Un receptor leído del campo de una variable, con un argumento que
            # llama a una fn que puede reasignar ese campo (`p.b.contains(f(p).b)`):
            # se usa una copia (el intérprete ve el valor de ese momento), liberada al
            # terminar la sentencia. El campo de un temporal (`f().b`) ya es propio.
            self.needs_str_concat = True
            out.append(f'{pad}const char* {tmp_o} = scar_str_concat({obj_code}, "");')
            self.pending_expr_temps.append(tmp_o)
            obj_code = None
        else:
            out.append(f"{pad}const char* {tmp_o} = {obj_code};")
        # si el receptor era un str fresco (`(a + b).len()`), tmp_o es el único
        # nombre de ese texto: va a pending_expr_temps
        if obj_code is not None and (
                self._is_fresh_str_concat_expr(expr.obj, env) or self._is_fresh_str_call(expr.obj)):
            # también un str fresco de una llamada, `f().len()`
            self.pending_expr_temps.append(tmp_o)
        if expr.method == "len":
            self.needs_utf8_len = True
            return f"scar_utf8_len({tmp_o})"
        if expr.method in ("contains", "starts_with", "ends_with"):
            tmp_a = self._new_tmp()
            arg_code = self.gen_expr(expr.args[0], env, out, pad)
            out.append(f"{pad}const char* {tmp_a} = {arg_code};")
            if self._is_fresh_str_concat_expr(expr.args[0], env) or self._is_fresh_str_call(expr.args[0]):
                self.pending_expr_temps.append(tmp_a)
            if expr.method == "contains":
                return f"(strstr({tmp_o}, {tmp_a}) != NULL)"
            if expr.method == "starts_with":
                return f"(strncmp({tmp_o}, {tmp_a}, strlen({tmp_a})) == 0)"
            # ends_with: el && corta antes del strcmp si tmp_o es más corto que
            # tmp_a, así nunca se calcula un puntero antes del principio
            return (
                f"(strlen({tmp_o}) >= strlen({tmp_a}) && "
                f"strcmp({tmp_o} + strlen({tmp_o}) - strlen({tmp_a}), {tmp_a}) == 0)"
            )
        raise CodegenError(f"str no tiene método '.{expr.method}()' en el backend de C")

    @staticmethod
    def _expr_simple(e) -> bool:
        """Sin efectos ni panics al evaluarse: un literal, una variable o una
        cadena de campos de una variable."""
        while isinstance(e, FieldAccess):
            e = e.obj
        return isinstance(e, (Ident, NumLit, StrLit, BoolLit))
