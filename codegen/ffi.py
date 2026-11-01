"""Mixin FFI de Codegen (paso C6): la frontera con C de afuera. Qué tipos cruzan
un extern fn, qué librerías van aisladas en un worker por pipe y el wrapper
que habla con él, y las export fn de una librería (modo --lib).
"""

from types_ import TypeAnn, T_VOID

from .comun import (
    _raiz_fin_c, _raiz_inicio_c, SCAR_RAND_SEED_LINE,
    VEC_MARK,
)


class FFI:
    # cómo cruza cada elemento de un Vec escalar la frontera (tipo de C, bytes)
    _VEC_FFI_ELEM = {"i32": ("int32_t", 4), "i64": ("int64_t", 8), "f64": ("double", 8), "bool": ("bool", 1)}

    def _pipe_type_ok(self, ty: TypeAnn) -> bool:
        """Tipos que el protocolo de pipe del worker aislado sabe serializar
        (ffi_worker.py: _param_kind/_ret_kind). Más angosto que types_.ffi_tipo_ok:
        sin struct por valor ni fn como valor. Esa diferencia decide si una
        librería puede aislarse (_library_pipe_eligible)."""
        if ty.name in ("i32", "i64", "f64", "bool", "str"):
            return True
        if self._es_vec_ffi(ty):
            return True  # el largo y los elementos, ida y vuelta
        return ty.name in self.extern_types and not ty.args

    def _es_vec_ffi(self, ty) -> bool:
        """Un Vec de i32/i64/f64/bool como parámetro de una extern fn: en C son
        dos parámetros, `T*` y `int64_t` (el largo). C lo recibe prestado durante
        la llamada y lo que cambie en los elementos queda en el Vec (con el
        worker aislado, los elementos vuelven por el pipe)."""
        return (ty is not None and ty.name == VEC_MARK and bool(ty.args)
                and ty.args[0].name in self._VEC_FFI_ELEM)

    def _library_pipe_eligible(self, decls) -> bool:
        """Todo o nada por librería: si una sola función usa un tipo que el pipe
        no sabe representar, ninguna pasa por el worker aislado."""
        for decl in decls:
            for p in decl.params:
                if p.type_ann is None or not self._pipe_type_ok(p.type_ann):
                    return False
            ret = decl.return_type or T_VOID
            ret_inner = ret.args[0] if ret.name == "Result" else ret
            if ret_inner.name != "void" and not self._pipe_type_ok(ret_inner):
                return False
        return True

    @staticmethod
    def _ffi_lib_ident(library: str) -> str:
        """Nombre de librería -> fragmento de identificador de C (todo lo que no
        es alfanumérico pasa a '_')."""
        return "".join(c if c.isalnum() else "_" for c in library)

    def _pipe_kind(self, ty: TypeAnn) -> str:
        """'i32'|'f64'|'bool'|'str'|'ptr' para el protocolo de pipe; _pipe_type_ok
        ya garantizó que ty es uno de estos."""
        if ty.name in ("i32", "i64", "f64", "bool", "str"):
            return ty.name
        if self._es_vec_ffi(ty):
            return "vec_" + ty.args[0].name
        return "ptr"

    def _gen_ffi_pipe_wrapper(self, name, library, params, ret_for_decl, ret_c_type, guard_param_list):
        """Cuerpo de scar_extern_guarded_<name> para una función de una librería
        aislada: escribe el pedido en el pipe del worker de esa librería (lanzado
        una vez al arrancar main, en scar_ffi_worker_start_all) y lee la
        respuesta, con el protocolo de ffi_worker.py.

        `ret_for_decl` es el T crudo (no Result<T>), para saber cómo leer la
        respuesta; `ret_c_type`, el tipo de C ya resuelto, para la firma y el
        cast final."""
        lib_ident = self._ffi_lib_ident(library)
        handle = f"scar_ffi_worker_{lib_ident}"
        idx = self.ffi_worker_index_of[library][name]
        lock = f"    pthread_mutex_lock(&{handle}.mu);\n" if self.has_tasks else ""
        unlock = f"    pthread_mutex_unlock(&{handle}.mu);\n" if self.has_tasks else ""
        is_void = ret_c_type == "void"

        lines = [f"static {ret_c_type} scar_extern_guarded_{name}({guard_param_list}) {{\n"]
        lines.append(f"    ScarFfiWorkerHandle *__scar_h = &{handle};\n")
        lines.append(lock)
        lines.append("    if (__scar_h->dead) {\n")
        lines.append(unlock)
        lines.append(
            f'        scar_ffi_worker_report_crash("{name}", "{library}", __scar_h->dead_reason);\n'
        )
        if not is_void:
            lines.append(f"        return ({ret_c_type}){{0}};\n")
        lines.append("    }\n")
        lines.append("    int __scar_ok = 1;\n")
        lines.append(f"    uint32_t __scar_idx = {idx}u;\n")
        lines.append("    if (!scar_ffi_write_exact(__scar_h->wfd, &__scar_idx, 4)) __scar_ok = 0;\n")
        for i, ty in enumerate(params):
            kind = self._pipe_kind(ty)
            arg = f"__scar_gp{i}"
            if kind == "i32":
                lines.append(f"    if (__scar_ok && !scar_ffi_write_i32(__scar_h->wfd, {arg})) __scar_ok = 0;\n")
            elif kind == "i64":
                lines.append(f"    if (__scar_ok && !scar_ffi_write_i64(__scar_h->wfd, {arg})) __scar_ok = 0;\n")
            elif kind == "f64":
                lines.append(f"    if (__scar_ok && !scar_ffi_write_f64(__scar_h->wfd, {arg})) __scar_ok = 0;\n")
            elif kind == "bool":
                lines.append(f"    if (__scar_ok && !scar_ffi_write_bool(__scar_h->wfd, (uint8_t){arg})) __scar_ok = 0;\n")
            elif kind == "str":
                lines.append(f"    if (__scar_ok && !scar_ffi_write_str(__scar_h->wfd, {arg})) __scar_ok = 0;\n")
            elif kind.startswith("vec_"):
                size = self._VEC_FFI_ELEM[kind[4:]][1]
                lines.append(f"    if (__scar_ok && !scar_ffi_write_i64(__scar_h->wfd, (int64_t){arg}.len)) __scar_ok = 0;\n")
                lines.append(f"    if (__scar_ok && {arg}.len > 0 && !scar_ffi_write_exact(__scar_h->wfd, {arg}.data, "
                             f"(size_t){arg}.len * {size})) __scar_ok = 0;\n")
            else:  # ptr (extern type)
                lines.append(
                    f"    if (__scar_ok && !scar_ffi_write_ptr(__scar_h->wfd, (uint64_t)(uintptr_t){arg})) __scar_ok = 0;\n"
                )

        if not is_void:
            ret_kind = self._pipe_kind(ret_for_decl)
            if ret_kind == "str":
                lines.append("    char *__scar_gr = NULL;\n")
                lines.append("    uint8_t __scar_gr_is_null = 1;\n")
                lines.append(
                    "    if (__scar_ok && !scar_ffi_read_str(__scar_h->rfd, &__scar_gr, &__scar_gr_is_null)) __scar_ok = 0;\n"
                )
            elif ret_kind == "ptr":
                lines.append("    uint64_t __scar_gr_raw = 0;\n")
                lines.append(
                    "    if (__scar_ok && !scar_ffi_read_ptr(__scar_h->rfd, &__scar_gr_raw)) __scar_ok = 0;\n"
                )
            elif ret_kind == "i32":
                lines.append("    int32_t __scar_gr = 0;\n")
                lines.append(
                    "    if (__scar_ok && !scar_ffi_read_i32(__scar_h->rfd, &__scar_gr)) __scar_ok = 0;\n"
                )
            elif ret_kind == "i64":
                lines.append("    int64_t __scar_gr = 0;\n")
                lines.append(
                    "    if (__scar_ok && !scar_ffi_read_i64(__scar_h->rfd, &__scar_gr)) __scar_ok = 0;\n"
                )
            elif ret_kind == "f64":
                lines.append("    double __scar_gr = 0;\n")
                lines.append(
                    "    if (__scar_ok && !scar_ffi_read_f64(__scar_h->rfd, &__scar_gr)) __scar_ok = 0;\n"
                )
            else:  # bool
                lines.append("    uint8_t __scar_gr = 0;\n")
                lines.append(
                    "    if (__scar_ok && !scar_ffi_read_bool(__scar_h->rfd, &__scar_gr)) __scar_ok = 0;\n"
                )

        # detrás del retorno, los elementos de cada Vec (C pudo cambiarlos)
        # vuelven a su lugar
        for i, ty in enumerate(params):
            kind = self._pipe_kind(ty)
            if kind.startswith("vec_"):
                size = self._VEC_FFI_ELEM[kind[4:]][1]
                arg = f"__scar_gp{i}"
                lines.append(f"    if (__scar_ok && {arg}.len > 0 && !scar_ffi_read_exact(__scar_h->rfd, {arg}.data, "
                             f"(size_t){arg}.len * {size})) __scar_ok = 0;\n")
        lines.append("    if (!__scar_ok) {\n")
        lines.append("        const char *__scar_reason = scar_ffi_worker_crash_reason(__scar_h->pid);\n")
        lines.append("        scar_ffi_worker_mark_dead(__scar_h, __scar_reason);\n")
        lines.append(unlock)
        lines.append(
            f'        scar_ffi_worker_report_crash("{name}", "{library}", __scar_reason);\n'
        )
        if not is_void:
            lines.append(f"        return ({ret_c_type}){{0}};\n")
        lines.append("    }\n")
        lines.append(unlock)
        if not is_void:
            if ret_kind == "ptr":
                lines.append(f"    return ({ret_c_type})(uintptr_t)__scar_gr_raw;\n")
            elif ret_kind == "bool":
                lines.append("    return (bool)__scar_gr;\n")
            else:
                lines.append("    return __scar_gr;\n")
        lines.append("}")
        return "".join(lines)

    def _ffi_c_type(self, ty: TypeAnn, param: bool = False) -> str:
        """Tipo de C en la firma de una extern fn. Difiere de c_type() en dos
        casos: str (const char* como parámetro, char* como retorno) y un struct
        de usuario, que cruza por valor (`struct X`, sin el '*' de uso interno)."""
        if ty.name == "str":
            # Como parámetro, `const char*`: C no debe modificar un str de SCAR, y es
            # la convención de la libc (strcmp, getenv), así redeclarar uno de esos
            # símbolos no choca con su header. Como retorno sigue `char*`.
            return "const char*" if param else "char*"
        if ty.name in self.structs:
            return ty.name
        return self.c_type(ty)

    def _extern_str_en_proceso(self) -> bool:
        """True si alguna extern fn corre dentro del proceso y devuelve str (o
        Result<str>): su retorno se copia con scar_ffi_str_propia()."""
        for name, (params, ret) in self.extern_sigs.items():
            base = ret.args[0] if ret.name == "Result" else ret
            library = self.extern_fn_library.get(name)
            isolated = library is not None and library in self.pipe_isolated_libs
            if base.name == "str" and not isolated:
                return True
        return False

    def _exportadas_c(self, fns):
        """Por cada `export fn`, una función de C con el nombre que escribió el
        usuario (sin `static`) que llama a la de SCAR. Cada llamada es un
        main chico en el hilo que llama: arma su contexto raíz (las tareas
        que lance son sus hijas), atrapa el panic (devuelve 0/NULL y
        scar_error() da el mensaje) y al volver cancela y espera a las tareas
        sin join(). El estado del runtime es por hilo (o tiene su lock): varias
        llamadas pueden correr a la vez desde hilos distintos."""
        out, vecs_c, tipo_frontera = self._exportadas_inicio()
        cuerpos = self._exportadas_funciones(fns, tipo_frontera)
        return self._exportadas_vecs(out, vecs_c, cuerpos)

    def _exportadas_inicio(self):
        """Los tipos de C de la frontera, el encabezado del bloque exportado y
        tipo_frontera (que va anotando los Vec escalares que cruzan)."""
        tipos_c = {"i32": "int32_t", "i64": "int64_t", "f64": "double", "bool": "bool",
                   "str": "char*", "void": "void"}
        out = [
            "// ---- lo que exporta la librería ----",
            "// el mensaje del último panic de este hilo (NULL si su última llamada",
            "// terminó bien): cada hilo que llama ve el error de su propia llamada.",
            "// Vive en una clave de pthread para que se libere cuando el hilo termina.",
            "static pthread_key_t scar_lib_error_clave;",
            "static pthread_once_t scar_lib_error_una = PTHREAD_ONCE_INIT;",
            "static void scar_lib_error_crear(void) { pthread_key_create(&scar_lib_error_clave, free); }",
            "static void scar_lib_poner_error(char* m) {",
            "    pthread_once(&scar_lib_error_una, scar_lib_error_crear);",
            "    free(pthread_getspecific(scar_lib_error_clave));",
            "    pthread_setspecific(scar_lib_error_clave, m);",
            "}",
            "const char* scar_error(void) {",
            "    pthread_once(&scar_lib_error_una, scar_lib_error_crear);",
            "    return pthread_getspecific(scar_lib_error_clave);",
            "}",
            "// un str que devolvió una export fn es de quien llamó: se suelta con esta",
            "void scar_liberar_str(char* s) { scar_free(s); }",
            "__attribute__((constructor)) static void scar_lib_iniciar(void) {",
        ]
        if self.needs_rand:
            out.append(SCAR_RAND_SEED_LINE.rstrip("\n"))
        out.append("}")
        vecs_c = {}  # sufijo -> tipo C del elemento, de los Vec en las firmas

        def tipo_frontera(t, param=False):
            if t is None or t.name == "void":
                return "void"
            if t.name == "str":
                return "const char*" if param else "char*"
            if t.name == VEC_MARK:
                suf = self.c_type(t)[len("Vec_"):]
                vecs_c[suf] = self.c_type(t.args[0])
                return f"ScarVecC_{suf}"
            if t.name in self.structs:
                return t.name  # por valor, como en una extern fn
            return tipos_c[t.name]
        return out, vecs_c, tipo_frontera

    def _exportadas_funciones(self, fns, tipo_frontera):
        """Una función de C por cada export fn: convierte los argumentos, llama
        a la fn de SCAR dentro de su raíz y entrega el resultado."""
        cuerpos = []
        for d in fns:
            if not getattr(d, "exportada", False):
                continue
            nombre = self.nombres.originales.get(d.name, d.name)
            params, ret = self.fn_sigs[d.name]
            ret_c = tipo_frontera(ret)
            ps = [f"{tipo_frontera(t, param=True)} a{i}" for i, t in enumerate(params)]
            consumidos = self.consumed_params.get(d.name, ())
            own = self.fn_ownership.get(d.name)
            ret_struct = ret is not None and ret.name in self.structs
            pre, armar, args, soltar, volvio = [], [], [], [], []
            for i, t in enumerate(params):
                if t.name in self.structs:
                    # el struct que llega por valor pasa a ser uno de SCAR (un puntero
                    # propio); si la fn solo lo presta, lo suelta el wrapper, también si la
                    # fn hace panic
                    campos = ", ".join(f"a{i}.{c}" for c in self.structs[t.name])
                    puede_volver = ret_struct and (own is None or own.ret_set is None
                                                   or own.may_return_param(i))
                    if i in consumidos:
                        armar.append(f"        {t.name}* p{i} = {t.name}_new({campos});")
                    else:
                        pre.append(f"    {t.name}* volatile p{i} = NULL;")
                        armar.append(f"        p{i} = {t.name}_new({campos});")
                        soltar.append(f"    if (p{i}) {self._struct_free_fn(t)}(p{i});")
                        if puede_volver:
                            # la fn puede devolver este mismo struct: si lo hizo, se suelta como el
                            # resultado; si no, como prestado
                            volvio.append(f"        if (p{i} == rs) p{i} = NULL;")
                    args.append(f"p{i}")
                elif t.name == VEC_MARK:
                    # un Vec que entra se copia y es de la fn (como en SCAR)
                    suf = self.c_type(t)[len("Vec_"):]
                    armar.append(f"        Vec_{suf} v{i} = scar_vec_de_c_{suf}(a{i});")
                    args.append(f"v{i}")
                else:
                    args.append(f"a{i}")
            llamada = f"{d.name}({', '.join(args)})"
            cuerpo = [f"{ret_c} {nombre}({', '.join(ps) or 'void'}) {{",
                      "    TaskContext *__scar_previo = __scar_ctx;",
                      "    /*SCAR_STRC*/",
                      "    scar_lib_poner_error(NULL);"]
            compuesto = ret is not None and (ret_struct or ret.name == VEC_MARK)
            if ret_c != "void":
                if compuesto:
                    cuerpo.append(f"    {ret_c} r;")
                    cuerpo.append("    memset(&r, 0, sizeof r);")
                else:
                    cero = "NULL" if ret_c == "char*" else "0"
                    cuerpo.append(f"    {ret_c} volatile r = {cero};")
            cuerpo += pre
            cuerpo.append(_raiz_inicio_c(nombre).rstrip("\n"))
            cuerpo.append("    if (sigsetjmp(__scar_root.panic_env, 1) == 0) {")
            cuerpo += armar
            if ret_c == "void":
                cuerpo.append(f"        {llamada};")
            elif ret_struct:
                # el struct que devuelve sale por valor; el de SCAR se suelta
                cuerpo.append(f"        {ret.name}* rs = {llamada};")
                cuerpo += volvio
                cuerpo.append("        r = *rs;")
                cuerpo.append(f"        {self._struct_free_fn(ret)}(rs);")
            elif ret.name == VEC_MARK:
                # el buffer del Vec pasa a quien llama (scar_liberar_vec)
                cuerpo.append(f"        {self.c_type(ret)} rv = {llamada};")
                cuerpo.append("        r.datos = rv.data;")
                cuerpo.append("        r.n = rv.len;")
            elif ret_c == "char*":
                cuerpo.append(f"        r = (char*){llamada};")
            else:
                cuerpo.append(f"        r = {llamada};")
            cuerpo.append("    } else {")
            if compuesto:
                cuerpo.append("        memset(&r, 0, sizeof r);")
            cuerpo.append("        scar_lib_poner_error(strdup(__scar_root.panic_msg ? __scar_root.panic_msg : \"panic\"));")
            cuerpo.append("    }")
            cuerpo += soltar
            cuerpo.append(_raiz_fin_c().rstrip("\n"))
            # el registro de dueñas del hilo: el hilo es de quien llama y puede
            # terminar sin avisar; entre llamadas no hay nada vivo
            cuerpo.append("    scar_vivos_liberar_registro();")
            cuerpo.append("    __scar_ctx = __scar_previo;")
            # lo que imprimió la librería sale ya, en orden con lo del que llama
            cuerpo.append("    fflush(stdout);")
            if ret_c != "void":
                cuerpo.append("    return r;")
            cuerpo.append("}")
            cuerpos.append("\n".join(cuerpo))
        return cuerpos

    def _exportadas_vecs(self, out, vecs_c, cuerpos):
        """Las funciones de C para liberar los Vec que la librería entrega, y el
        bloque entero como texto."""
        if vecs_c:
            out.append("// Un Vec cruza la frontera como {datos, n}. El que devuelve")
            out.append("// una export fn es de quien llama: lo suelta con scar_liberar_vec(datos).")
            out.append("void scar_liberar_vec(void* datos) { free(datos); }")
        for suf, elem in vecs_c.items():
            out.append(f"typedef struct {{ {elem}* datos; int64_t n; }} ScarVecC_{suf};")
            out.append(f"static Vec_{suf} scar_vec_de_c_{suf}(ScarVecC_{suf} c) {{")
            out.append("    if (c.n < 0 || c.n > INT32_MAX || (c.n > 0 && c.datos == NULL)) {")
            out.append("        scar_panic(\"Vec inválido desde quien llama: n=%lld%s\", (long long)c.n,")
            out.append("                   c.n > 0 && c.datos == NULL ? \" con datos NULL\" : \"\");")
            out.append("    }")
            out.append(f"    Vec_{suf} v = scar_vec_new_{suf}((int32_t)c.n);")
            out.append(f"    if (c.n > 0) memcpy(v.data, c.datos, (size_t)c.n * sizeof({elem}));")
            out.append("    v.len = (int32_t)c.n;")
            out.append("    return v;")
            out.append("}")
        out += cuerpos
        return "\n".join(out)
