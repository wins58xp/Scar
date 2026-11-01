"""Mixin Programa de Codegen (paso C6): el programa entero. generate() y
_generar arman el .c (runtime, tipos, structs, fns, main), más los structs de
usuario, la detección de recursión y lo que necesita main.
"""

import os

from parser import FnDecl, Ident, Call, Node, hijos
from types_ import TypeAnn, T_I32, T_STR

from . import runtime as runtime_c
from .comun import (
    panic_c,
    _abs_min_max_helpers_c, _C_RESERVADOS_EXPORT, _chr_ord_helpers_c, CodegenError,
    FN_MARK, _i64_helpers_c, MAP_MARK, _marcas_strc, _PANIC_MAIN_C, _rand_runtime_c,
    _RE_USA_POOL, _shift_helpers_c, _STRC_C, _TEXTO_SIN_TOPE_C, _to_i32_helper_c,
    VEC_MARK, _vivos_runtime_c,
)


class Programa:
    def _resolve_result_str_value_origin(self):
        """Con el contrato único de str, toda fn/task que devuelve Result<str>
        entrega un str propio en su Ok: el `.value` de su resultado se libera
        siempre con scar_free."""
        self.result_str_value_origin = {}
        for item in self._concrete_fn_items():
            _params, ret = self.task_sigs[item.name] if item.is_task else self.fn_sigs[item.name]
            if ret.name == "Result" and ret.args and ret.args[0].name == "str":
                self.result_str_value_origin[item.name] = "plain"

    # ---- recursión infinita en el nativo (R14) ----
    #
    # Cada función que puede recursar compara, al entrar, el puntero de
    # pila con un límite del hilo (un margen antes del final de su pila); si
    # lo pasa, es un panic (antes: segfault mudo). Solo pagan el chequeo las
    # funciones de un ciclo de llamadas o que usan funciones como valor.
    def _calcular_recursivas(self, decls):
        nombres = {d.name for d in decls}
        plantillas = set(getattr(self, "generic_fns", {}) or {})
        llama = {d.name: set() for d in decls}
        sospechosas = set()
        for d in decls:
            pila = [d.body]
            while pila:
                n = pila.pop()
                if isinstance(n, Call):
                    cal = n.callee
                    if isinstance(cal, Ident):
                        if cal.name in nombres:
                            llama[d.name].add(cal.name)
                        elif cal.name in plantillas:
                            llama[d.name].update(x for x in nombres if x.startswith(cal.name + "_"))
                    else:
                        sospechosas.add(d.name)   # llamada a través de un valor
                    for h in n.args:
                        pila.append(h)
                    if not isinstance(cal, Ident):
                        pila.append(cal)
                    continue
                if isinstance(n, Ident) and n.name in nombres:
                    # una función usada como valor: puede volver a llamarse por un callback
                    # que no se ve acá
                    sospechosas.add(n.name)
                    sospechosas.add(d.name)
                if isinstance(n, (Node, list, tuple, dict)):
                    pila.extend(hijos(n))
        # además, cualquier función que llama a un valor función (variable)
        for d in decls:
            for p in getattr(d, "params", []):
                t = getattr(p, "type_ann", None)
                if t is not None and getattr(t, "name", None) == FN_MARK:
                    sospechosas.add(d.name)
        recursivas = set()
        for inicio in llama:
            vistos, pila = set(), list(llama[inicio])
            while pila:
                x = pila.pop()
                if x == inicio:
                    recursivas.add(inicio)
                    break
                if x in vistos:
                    continue
                vistos.add(x)
                pila.extend(llama.get(x, ()))
        return {n for n in (recursivas | sospechosas) if n in nombres and n != "main"}

    def _runtime_pila(self):
        panic = panic_c(self.has_tasks)
        return runtime_c.texto(
            "pila",
            PANIC=panic,
        )

    def gen_struct(self, name, fields):
        field_lines = "\n".join(f"    {self.c_type(fty)} {fname};" for fname, fty in fields.items())
        # El typedef lo pone struct_fwd_decls antes (generate()): acá se
        # completa el tag con sus campos, así el nombre sirve como puntero desde
        # Option<Struct>/Map<K,Struct> sin importar el orden.
        typedef = f"struct {name} {{\n{field_lines}\n}};"
        ctor_params = ", ".join(f"{self.c_type(fty)} {fname}" for fname, fty in fields.items())
        ctor_body = "\n".join(f"    self->{fname} = {fname};" for fname in fields)
        # Cada instancia es un bloque de heap que su dueña libera, con o sin
        # tasks (en la arena de la tarea, una tarea que crea
        # structs en un loop retenía todo hasta terminar).
        alloc_expr = f"({name}*)scar_blk_heap(sizeof({name}))"
        ctor = (
            f"static {name}* {name}_new({ctor_params}) {{\n"
            f"    {name}* self = {alloc_expr};\n"
            f"{ctor_body}\n"
            f"    return self;\n"
            f"}}"
        )
        # `deepcopy` es {name}_moveout + {name}_detach_fields (ver
        # gen_struct_deepcopy).
        deepcopy = self.gen_struct_deepcopy(name, fields)
        deepcopy_into = self.gen_struct_deepcopy_into(name, fields)
        # {name}_free: libera los campos que el struct posee (struct anidado,
        # str, Vec, Map; Option/Result/Chan abajo) y después el bloque con
        # scar_blk_release, que decide malloc o arena por el encabezado.
        # Todo campo str es dueño de su valor: la construcción y la asignación
        # copian lo que no es propio.
        nested_frees = [
            f"    {fty.name}_free(self->{fname});"
            for fname, fty in fields.items()
            if fty.name in self.structs
        ] + [
            f"    scar_free((char*)self->{fname});"
            for fname, fty in fields.items()
            if fty.name == "str"
        ] + [
            # Nombre mangleado: con T/V=Chan<U>, .name es "Chan" a secas y no
            # coincidiría con la definición de scar_vec_free_*/scar_map_free_*.
            f"    scar_vec_free_{self._mangled_name(fty.args[0] if fty.args else T_I32)}(self->{fname});"
            for fname, fty in fields.items()
            if fty.name == VEC_MARK
        ] + [
            f"    scar_map_free_{(fty.args[0].name if fty.args else T_I32.name)}_"
            f"{self._mangled_name(fty.args[1] if len(fty.args) > 1 else T_I32)}(self->{fname});"
            for fname, fty in fields.items()
            if fty.name == MAP_MARK
        ]
        # Campos Option/Result/Chan que el struct posee: las mismas líneas que
        # liberan una variable dueña de ese tipo.
        for fname, fty in fields.items():
            if self._campo_compuesto_con_dueno(fty):
                nested_frees += self._lineas_liberar_dueno(fty, f"self->{fname}")
        # {name}_free(NULL) es un no-op: así un campo struct se puede vaciar
        # con NULL (_try_neutralize_extracted_field).
        free_fn = (
            f"static void {name}_free({name}* self) {{\n"
            f"    if (self == NULL) return;\n"
            + ("\n".join(nested_frees) + "\n" if nested_frees else "")
            + f"    scar_blk_release(self);\n"
            f"}}\n"
            # {name}_free_erased: la firma void(*)(void*) que pide
            # TaskContext.free_retval, sin castear punteros a función (UB).
            f"static void {name}_free_erased(void* self) {{\n"
            f"    {name}_free(({name}*)self);\n"
            f"}}"
        )
        # {name}_free_fields: libera los campos pero no el bloque, para un
        # struct embebido por valor en otra memoria (un slot de un Vec). Sin
        # guard de NULL: siempre recibe la dirección de un slot.
        # {name}_free_heap_fields era la variante con tasks; desde B12
        # es igual y se conserva el nombre.
        heap_frees = nested_frees
        free_fields_fn = (
            f"static void {name}_free_fields({name}* self) {{\n"
            + ("\n".join(nested_frees) + "\n" if nested_frees else "")
            + f"}}\n"
            f"static void {name}_free_heap_fields({name}* self) {{\n"
            + ("\n".join(heap_frees) + "\n" if heap_frees else "")
            + f"}}"
        )
        return typedef, ctor, deepcopy, deepcopy_into, free_fn, free_fields_fn

    def gen_struct_deepcopy(self, name, fields):
        """{name}_moveout y {name}_detach_fields (el nombre de la función quedó
        de cuando generaba {name}_deepcopy, que ya no existe).

        {name}_moveout saca de la arena lo que sale de una task (su valor de
        retorno). Es un movimiento: el original no se vuelve a usar (la arena
        se libera enseguida). Se decide bloque por bloque por el encabezado
        (B12): uno de malloc se queda donde está, uno de la arena se pasa a
        malloc. str, Vec y Map nunca están en la arena y cambian de dueño tal
        cual. {name}_detach_fields hace lo mismo con lo que cuelga del struct
        (anidados, y los structs dentro de un Vec<S> o Map<K,S> campo).
        Quien copia usa {name}_clone (_struct_clone_def)."""
        moveout_fn = (
            f"static {name}* {name}_moveout({name}* src) {{\n"
            f"    {name}* dst = src;\n"
            f"    if (!scar_blk_is_heap(src)) {{\n"
            f"        dst = scar_blk_heap(sizeof({name}));\n"
            f"        *dst = *src;\n"
            f"    }}\n"
            f"    {name}_detach_fields(dst);\n"
            f"    return dst;\n"
            f"}}"
        )
        det = []
        for fname, fty in fields.items():
            det += self._detach_lines(fty, f"s->{fname}", "    ")
        detach_fn = (f"static void {name}_detach_fields({name}* s) {{\n"
                     + ("\n".join(det) + "\n" if det else "    (void)s;\n") + "}")
        return moveout_fn + "\n\n" + detach_fn

    def _detach_lines(self, ty, lv, pad):
        """Líneas de C que sacan de la arena todo bloque de struct alcanzable
        desde `lv` de tipo `ty` (ver {T}_moveout). Vacío si `ty` no puede
        contener structs."""
        sname = None
        if ty.name in self.structs:
            sname = ty.name
        elif ty.name in self.generic_structs:
            sname = self._ensure_generic_struct_instance(ty.name, ty.args)
        if sname is not None:
            return [f"{pad}if ({lv}) {lv} = {sname}_moveout({lv});"]
        if ty.name == VEC_MARK and ty.args:
            inner = ty.args[0]
            if inner.name in self.structs:
                i = self._new_tmp()
                return [f"{pad}for (int32_t {i} = 0; {i} < ({lv}).len; {i}++) "
                        f"{inner.name}_detach_fields(&({lv}).data[{i}]);"]
            return []
        if ty.name == MAP_MARK and len(ty.args) > 1:
            val = ty.args[1]
            if val.name in self.structs:
                i = self._new_tmp()
                e = f"({lv})->entries[{i}]"
                return [f"{pad}if ({lv}) for (int32_t {i} = 0; {i} < ({lv})->cap; {i}++) "
                        f"if ({e}.state == 1 && {e}.value) {e}.value = {val.name}_moveout({e}.value);"]
            return []
        if ty.name in ("Option", "Result") and ty.args:
            sub = self._detach_lines(ty.args[0], f"({lv}).value", pad + "    ")
            if sub:
                return [f"{pad}if (({lv}).tag == 1) {{"] + sub + [f"{pad}}}"]
        return []

    def gen_struct_deepcopy_into(self, name, fields):
        """Retirada: scar_chan_send_<T> mueve el struct al nodo, no lo
        copia."""
        return None

    def _programa_usa_builtin(self, nombre):
        """True si algún cuerpo llama al builtin `nombre` (una llamada que no es
        a una fn del usuario). Recorre el AST entero, sin depender del orden
        de generación."""
        # Pila explícita, no recursión: Python 3.12+ corta la recursión a través
        # de C a unos miles de niveles (50.000 sumandos, 3.000 else-if).
        vistos = set()
        pila = [self.program.items]
        while pila:
            n = pila.pop()
            if isinstance(n, Node):
                if id(n) in vistos:
                    continue
                vistos.add(id(n))
                if (isinstance(n, Call) and isinstance(n.callee, Ident)
                        and n.callee.name == nombre and nombre not in self.fn_sigs):
                    return True
            elif not isinstance(n, (list, tuple, dict)):
                continue
            pila.extend(hijos(n))  # también dicts
        return False

    # ---------- SCAR como librería ----------
    def _validar_libreria(self, fns):
        exportadas = [d for d in fns if getattr(d, "exportada", False)]
        if not exportadas:
            raise CodegenError("una librería necesita al menos una `export fn` (lo que se "
                               "puede llamar desde otro lenguaje)")
        if self._programa_usa_builtin("arg"):
            raise CodegenError("arg() no tiene sentido en una librería: no hay línea de "
                               "comandos; lo que haga falta va como parámetro de la export fn")
        vistos = set()
        for d in exportadas:
            nombre = self.nombres.originales.get(d.name, d.name)
            if (nombre in _C_RESERVADOS_EXPORT or nombre.startswith("scar_")
                    or nombre.startswith("_")):
                raise CodegenError(f"'{nombre}' no se puede exportar con ese nombre: es de C, "
                                   f"de la libc o del runtime de SCAR (scar_*); usa otro")
            vistos.add(nombre)

    def _main_sig(self):
        """`int main(void)` salvo que el programa use arg()."""
        return "int main(int argc, char** argv)" if self.usa_arg else "int main(void)"

    def _main_arg_init(self):
        """Primera línea de main() si el programa usa arg(): argv sin el nombre
        del programa (arg(0) es el primer argumento, como en el intérprete)."""
        if not self.usa_arg:
            return ""
        return "    scar_argc_prog = argc - 1; scar_argv_prog = argv + 1;\n"

    def _arg_helper_c(self):
        """arg(i). Los punteros de argv viven hasta el final y nadie
        los escribe: las tasks los leen sin lock ni copia. Validación UTF-8
        estricta, la del decode('utf-8') del intérprete; un argumento
        inválido es un panic."""
        panic = panic_c(self.has_tasks)
        opt = self.c_type(TypeAnn("Option", [T_STR]))
        return runtime_c.texto(
            "arg",
            OPT=str(opt),
            PANIC=str(panic),
        )

    def generate(self):
        try:
            return self._generar()
        except CodegenError as e:
            raise CodegenError(self.nombres.desproteger(str(e))) from None

    def _generar(self):
        """El archivo de C del programa, pasada por pasada: primero lo
        que decide qué hay que generar, después cada trozo de C, y al final el
        armado en el orden en que C los necesita."""
        fns, tasks = self._pasada_analisis()
        (struct_typedefs, struct_ctors, struct_deepcopies, struct_deepcopy_intos,
         struct_frees, struct_fwd_decls, struct_free_fwd_decls, struct_deepcopy_fwd_decls,
         struct_deepcopy_into_fwd_decls, struct_free_fields_fwd_decls, struct_free_fields,
         struct_clones) = self._pasada_structs()
        decls, extern_guarded_wrappers = self._pasada_declaraciones(fns, tasks)
        (task_args_typedefs, task_thread_defs, injected_slots_typedefs, bodies,
         extern_result_wrappers) = self._pasada_cuerpos(fns, tasks, decls)
        (fmt_f64_helper, repr_str_helper, map_hash_helpers, parse_int_core,
         builtin_int_helper, builtin_int64_helper) = self._runtime_formato()
        (pipe_struct_typedef, pipe_typedef, file_typedef, extern_type_typedefs,
         file_io_helpers, read_pipe_helper, net_io_typedefs,
         net_io_helpers) = self._runtime_es()
        (sleep_helper, arena_support, task_context_struct, task_context_helpers,
         idiv_helper, imod_helper, str_index_helper, extern_guard_helpers,
         ffi_worker_runtime) = self._runtime_tareas()
        (str_concat_helper, blk_runtime, preamble, needs_scar_malloc,
         scar_pool_allocator) = self._runtime_preambulo()
        parts, lugar_pool = self._armar_runtime(
            sleep_helper, arena_support, task_context_struct, task_context_helpers,
            idiv_helper, imod_helper, str_index_helper, extern_guard_helpers,
            ffi_worker_runtime, str_concat_helper, blk_runtime, preamble,
            needs_scar_malloc, scar_pool_allocator)
        self._armar_tipos(
            struct_typedefs, struct_ctors, struct_deepcopies, struct_deepcopy_intos,
            struct_frees, struct_fwd_decls, struct_free_fwd_decls,
            struct_deepcopy_fwd_decls, struct_deepcopy_into_fwd_decls,
            struct_free_fields_fwd_decls, struct_free_fields, struct_clones,
            map_hash_helpers, pipe_struct_typedef, file_typedef, extern_type_typedefs,
            net_io_typedefs, parts)
        return self._armar_funciones(
            fns, decls, extern_guarded_wrappers, task_args_typedefs, task_thread_defs,
            injected_slots_typedefs, bodies, extern_result_wrappers, fmt_f64_helper,
            repr_str_helper, parse_int_core, builtin_int_helper, builtin_int64_helper,
            pipe_typedef, file_io_helpers, read_pipe_helper, net_io_helpers,
            needs_scar_malloc, scar_pool_allocator, parts, lugar_pool)

    def _pasada_analisis(self):
        """Resuelve los genéricos, corre los análisis de funciones y arma la
        lista de fns y tasks a compilar (y cuáles pueden recursar)."""
        # Las instancias de structs y fn genéricas se resuelven primero, para
        # que los análisis de propiedad (fresh_str/fresh_owned/consumed) vean
        # también sus cuerpos.
        self._resolve_generic_struct_instances()
        self._resolve_generic_fn_instances()
        # La firma de main() depende de si el programa usa arg().
        self.usa_arg = self._programa_usa_builtin("arg")
        # Los análisis de funciones corren antes de cualquier gen_fn(): una fn
        # puede llamar a otra declarada más abajo.
        self._resolve_fresh_str_fns()
        self._resolve_fresh_owned_fns()
        self._resolve_consumed_params()
        self._resolve_result_str_value_origin()

        # La plantilla de una fn genérica no se compila (no tiene fn_sigs);
        # sus instancias se suman aparte, como fns comunes.
        fns = [
            item for item in self.program.items
            if isinstance(item, FnDecl) and not item.is_task and not item.type_params
        ]
        fns += [d for d in self.generic_fn_decls.values() if not d.is_task]
        tasks = [item for item in self.program.items
                 if isinstance(item, FnDecl) and item.is_task and not item.type_params]
        # las instancias de las tasks genéricas, como tasks comunes
        tasks += [d for d in self.generic_fn_decls.values() if d.is_task]
        if self.libreria:
            self._validar_libreria(fns)
            fns = [d for d in fns if d.name != "main"]  # una librería no tiene main
        # Qué funciones pueden recursar (R14).
        self._fns_recursivas = self._calcular_recursivas(fns + tasks)
        return fns, tasks

    def _pasada_structs(self):
        """Los trozos de C de cada struct: typedefs, prototipos, constructores,
        frees y clones."""
        struct_typedefs = []
        struct_ctors = []
        struct_deepcopies = []
        struct_deepcopy_intos = []
        struct_frees = []
        # `typedef struct Nombre Nombre;` (tipo incompleto) de todos los
        # structs, antes que nada: alcanza para un campo puntero (`Contador*
        # value` en Option<Contador>, Map<K,Contador>...) en el cluster
        # generic/chan/vec/map, que va antes de struct_typedefs.
        struct_fwd_decls = [f"typedef struct {name} {name};" for name in self.structs]
        # Prototipos de {Name}_free: el cluster de arriba (Map con V struct
        # ...) ya los llama antes de la definición. Para todos los structs:
        # un prototipo de más no cuesta nada.
        struct_free_fwd_decls = [f"static void {name}_free({name}* self);" for name in self.structs]
        # Prototipos de {Name}_moveout/_detach_fields/_clone, por el mismo
        # motivo (los usan las funciones de Vec/Chan/Map de structs).
        struct_deepcopy_fwd_decls = [
            f"static {name}* {name}_moveout({name}* src);\n"
            f"static void {name}_detach_fields({name}* s);"
            for name in self.structs
        ] + [
            # {T}_clone (copia profunda): la definición va al final
            # (clone_defs).
            f"static {name}* {name}_clone({name}* src);" for name in self.structs
        ]
        # vacía: {Name}_deepcopy_into se retiró
        struct_deepcopy_into_fwd_decls = []  # deepcopy_into retirada
        # Prototipos de {Name}_free_fields/_free_heap_fields: scar_vec_pop_<T>
        # los llama antes de la definición.
        struct_free_fields_fwd_decls = [
            f"static void {name}_free_fields({name}* self);" for name in self.structs
        ] + [
            f"static void {name}_free_heap_fields({name}* self);" for name in self.structs
        ]
        struct_free_fields = []
        struct_clones = []
        for name, fields in self.structs.items():
            typedef, ctor, deepcopy, deepcopy_into, free_fn, free_fields_fn = self.gen_struct(name, fields)
            struct_typedefs.append(typedef)
            struct_ctors.append(ctor)
            if deepcopy is not None:
                struct_deepcopies.append(deepcopy)
            if deepcopy_into is not None:
                struct_deepcopy_intos.append(deepcopy_into)
            if free_fn is not None:
                struct_frees.append(free_fn)
            if free_fields_fn is not None:
                struct_free_fields.append(free_fields_fn)
            struct_clones.append(self._struct_clone_def(name, fields))
        return (struct_typedefs, struct_ctors, struct_deepcopies, struct_deepcopy_intos,
                struct_frees, struct_fwd_decls, struct_free_fwd_decls,
                struct_deepcopy_fwd_decls, struct_deepcopy_into_fwd_decls,
                struct_free_fields_fwd_decls, struct_free_fields, struct_clones)

    def _pasada_declaraciones(self, fns, tasks):
        """Prototipos de fns y tasks, y el prototipo y el wrapper vigilado de
        cada extern fn."""
        # forward declarations, por si `main` no está al final
        decls = []
        for decl in fns:
            if decl.name == "main":
                decls.append(f"{self._main_sig()};")
                continue
            params, ret = self.fn_sigs[decl.name]
            param_list = ", ".join(self.c_type(t) for t in params) or "void"
            # `static` también acá: el prototipo y la definición tienen que
            # coincidir en linkage.
            decls.append(f"static {self.c_type(ret)} {decl.name}({param_list});")
        # Un prototipo `extern` por cada `extern fn`, haya o no header (si un
        # header ya lo declara con firma compatible, redeclarar es válido en
        # C11). Un retorno str se declara `char*` (sin const): es lo que
        # declara la libc (getenv, strerror) y "conflicting types" es error;
        # asignarlo a un const char* es seguro. Límite conocido: una librería
        # que declare `const char*` de retorno choca.
        #
        # Además, cada extern fn tiene un wrapper vigilado
        # (scar_extern_guarded_<nombre>) con la misma firma cruda: es el único
        # lugar que llama al símbolo; gen_expr y scar_extern_wrap_<nombre>
        # llaman al wrapper.
        extern_guarded_wrappers = []
        for name, (params, ret) in self.extern_sigs.items():
            param_list = ", ".join(
                f"{self._VEC_FFI_ELEM[t.args[0].name][0]}*, int64_t" if self._es_vec_ffi(t)
                else self._ffi_c_type(t, param=True) for t in params) or "void"
            # Con retorno Result<T>, el símbolo de C sigue devolviendo T crudo: lo
            # envuelve scar_extern_wrap_<nombre>.
            ret_for_decl = ret.args[0] if ret.name == "Result" else ret
            ret_c_type = self._ffi_c_type(ret_for_decl)

            library = self.extern_fn_library.get(name)
            isolated = library is not None and library in self.pipe_isolated_libs

            # Una librería aislada vive solo en el binario worker: su símbolo no
            # existe en este y no se declara.
            if not isolated:
                decls.append(f"extern {ret_c_type} {name}({param_list});")

            guard_param_list = ", ".join(
                f"{self._ffi_c_type(t, param=True)} __scar_gp{i}" for i, t in enumerate(params)
            ) or "void"
            guard_args_fwd = ", ".join(
                f"__scar_gp{i}.data, (int64_t)__scar_gp{i}.len" if self._es_vec_ffi(t) else f"__scar_gp{i}"
                for i, t in enumerate(params))

            if isolated:
                extern_guarded_wrappers.append(
                    self._gen_ffi_pipe_wrapper(
                        name, library, params, ret_for_decl, ret_c_type, guard_param_list
                    )
                )
                continue

            if ret_c_type == "void":
                call_line = f"    {name}({guard_args_fwd});\n"
                crash_ret = ""
                normal_ret = ""
            else:
                if ret_for_decl.name == "str":
                    # C sigue siendo dueño de lo que devolvió: el programa se queda con
                    # una copia (ver scar_ffi_str_propia)
                    call_line = f"    {ret_c_type} __scar_gr = scar_ffi_str_propia({name}({guard_args_fwd}));\n"
                else:
                    call_line = f"    {ret_c_type} __scar_gr = {name}({guard_args_fwd});\n"
                # Este return no se ejecuta (scar_extern_report_crash() termina o
                # salta), pero sin él gcc avisa "control reaches end". `(Tipo){0}`
                # sirve para escalares y para un struct por valor.
                crash_ret = f"        return ({ret_c_type}){{0}};\n"
                normal_ret = "    return __scar_gr;\n"
            extern_guarded_wrappers.append(
                f"static {ret_c_type} scar_extern_guarded_{name}({guard_param_list}) {{\n"
                f"    scar_extern_guard_fnname = \"{name}\";\n"
                f"    scar_extern_guard_active = 1;\n"
                f"    if (sigsetjmp(scar_extern_guard_env, 1) != 0) {{\n"
                f"        scar_extern_report_crash(\"{name}\", scar_extern_guard_signum);\n"
                f"{crash_ret}"
                f"    }}\n"
                f"{call_line}"
                f"    scar_extern_guard_active = 0;\n"
                f"{normal_ret}"
                f"}}"
            )

        # Un wrapper por cada extern fn con retorno Result<T> que el programa
        # llama: llama al símbolo (que devuelve T) y traduce NULL -> Err, valor
        # -> Ok. El checker de extern ya garantizó que T es str o un `extern
        # type`. Se arma después de `bodies`: extern_result_wrap_needed se
        # llena al generar los cuerpos.

        for decl in tasks:
            params, ret = self.task_sigs[decl.name]
            param_list = self._task_c_param_list(decl, params)
            # `static` como las fn: solo la llama su wrapper de pthread.
            decls.append(f"static {self.c_type(ret)} {decl.name}({param_list});")
        return decls, extern_guarded_wrappers

    def _pasada_cuerpos(self, fns, tasks, decls):
        """El soporte de cada task, el cuerpo de cada fn y task (gen_fn) y los
        wrappers Result de las extern fn que el programa llama."""
        task_args_typedefs = []
        task_thread_defs = []
        # InjectedSlots_<task> tiene que existir antes de que _gen_spawn lo
        # reserve y de que inject_chan()/accept_chan() lo usen; va con
        # task_args_typedefs.
        injected_slots_typedefs = []
        for decl in tasks:
            slots_struct = self._gen_injected_slots_struct(decl)
            if slots_struct is not None:
                injected_slots_typedefs.append(slots_struct)
        for decl in tasks:
            fwd, typedef_args, def_wrapper = self._gen_task_support(decl)
            decls.append(fwd)
            task_args_typedefs.append(typedef_args)
            task_thread_defs.append(def_wrapper)

        if self._fns_recursivas:
            decls.insert(0, self._runtime_pila())
        bodies = [self.gen_fn(decl) for decl in fns] + [self.gen_fn(decl) for decl in tasks]

        # Recién acá extern_result_wrap_needed está completo.
        extern_result_wrappers = []
        for name in sorted(self.extern_result_wrap_needed):
            params, ret = self.extern_sigs[name]
            inner = ret.args[0]
            result_c_name = self.c_type(ret)
            raw_ret_c_type = self._ffi_c_type(inner)
            param_list_typed = ", ".join(
                f"{self._ffi_c_type(t, param=True)} __scar_p{i}" for i, t in enumerate(params)
            ) or "void"
            args_fwd = ", ".join(f"__scar_p{i}" for i in range(len(params)))
            extern_result_wrappers.append(
                f"static {result_c_name} scar_extern_wrap_{name}({param_list_typed}) {{\n"
                # pasa por el wrapper vigilado, no por el símbolo crudo
                f"    {raw_ret_c_type} __scar_r = scar_extern_guarded_{name}({args_fwd});\n"
                f"    if (__scar_r == NULL) {{\n"
                f'        char* __scar_err = scar_aprintf("%s devolvió NULL", "{name}");\n'
                f"        return {result_c_name}_Err(__scar_err);\n"
                f"    }}\n"
                f"    return {result_c_name}_Ok(__scar_r);\n"
                f"}}"
            )
        return (task_args_typedefs, task_thread_defs, injected_slots_typedefs, bodies,
                extern_result_wrappers)

    def _runtime_formato(self):
        """Los helpers de formato y conversión: f64 como repr() de Python, repr
        de str, hash de Map, int() e int64()."""
        # f64 se formatea igual que repr() de Python: (1) los
        # dígitos son la representación decimal más corta que vuelve exacta al
        # mismo double, que calcula Ryu (native/ryu, amalgamado por
        # scripts/amalgamar_ryu.py; verificado contra repr() sobre 5 millones
        # de valores); (2) notación fija si -4 < decpt <= 16 (con ".0"
        # si es entero), científica si no ("1e+16", "1e-05"); nan/inf/-inf/-0.0
        # como Python.
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "native", "ryu", "scar_ryu_d2d.h"), encoding="utf-8") as _ryu:
            ryu_d2d = _ryu.read()
        fmt_f64_helper = runtime_c.texto(
            "fmt_f64",
            RYU_D2D=ryu_d2d,
        )
        # scar_repr_str(): el str dentro de Ok(...)/Err(...) en print(), con
        # repr() de Python: re-escapa \n, \t, \r, la comilla y '\' (el mismo
        # conjunto que el lexer y los literales de gen_expr).
        repr_str_helper = runtime_c.texto("repr_str")

        # scar_hash_{i32,f64,str,bool}, compartidas por todos los Map<K,V>.
        # i32: finalizer de murmur3 de 32 bits; f64: bits por memcpy + finalizer
        # de 64 bits; str: FNV-1a.
        map_hash_helpers = runtime_c.texto("map_hash")

        # int(s) / int64(s): la regla de _parse_int del intérprete: espacios
        # ASCII opcionales a los lados, signo opcional y dígitos ASCII. Fuera de
        # rango es Err.
        parse_int_core = runtime_c.texto("parse_int")
        builtin_int_helper = (
            "static Result_i32 scar_builtin_int(const char* s) {\n"
            "    int64_t v;\n"
            "    int rc = scar_parse_int(s, INT32_MIN, INT32_MAX, &v);\n"
            "    if (rc != 0) return Result_i32_Err(scar_parse_int_err(s, rc, \"i32\"));\n"
            "    return Result_i32_Ok((int32_t)v);\n"
            "}"
        )
        builtin_int64_helper = (
            "static Result_i64 scar_builtin_int64(const char* s) {\n"
            "    int64_t v;\n"
            "    int rc = scar_parse_int(s, INT64_MIN, INT64_MAX, &v);\n"
            "    if (rc != 0) return Result_i64_Err(scar_parse_int_err(s, rc, \"i64\"));\n"
            "    return Result_i64_Ok(v);\n"
            "}"
        )
        return (fmt_f64_helper, repr_str_helper, map_hash_helpers, parse_int_core,
                builtin_int_helper, builtin_int64_helper)

    def _runtime_es(self):
        """E/S: Pipe, File, read_pipe y red (Socket/Listener)."""
        # (C8) se asignan solo en algunas ramas y la pasada las devuelve siempre
        read_pipe_helper = None
        net_io_typedefs = None
        net_io_helpers = None
        # Pipe: struct por valor con sus dos fd (como ScarPipe del intérprete).
        # El typedef va antes de generic_defs (Option<Pipe>); la función, donde
        # estaba.
        pipe_struct_typedef = (
            "typedef struct {\n"
            "    int32_t read_fd;\n"
            "    int32_t write_fd;\n"
            "} ScarPipe;"
        )
        pipe_typedef = runtime_c.texto("pipe_tipo")

        # File: un handle (slot de la tabla + generación, handles_rt), no el
        # FILE* crudo: cerrar dos veces no hace nada y usar uno cerrado da Err,
        # también desde una copia. El typedef va antes de
        # generic_defs: Result<File> lo necesita.
        file_typedef = "typedef int64_t ScarFile;"

        # `extern type`: un typedef void* por handle opaco, antes de
        # generic_defs como file_typedef.
        extern_type_typedefs = "\n".join(
            f"typedef void* {name};" for name in self.extern_types
        )

        # scar_file_open() valida el modo antes de tocar el sistema de
        # archivos, con el mismo mensaje que el intérprete. Todo fallo de la
        # libc se reporta con strerror(errno). write() compara lo escrito
        # contra strlen(s) para detectar una escritura parcial.
        file_io_helpers = runtime_c.texto("file_io")

        # read_pipe(fd): sondea con select() en pasos de 20 ms en vez de
        # bloquearse en read(), con timeout SCAR_IO_TIMEOUT_SECONDS (7.5 s,
        # menor que el de join() para que el panic de E/S llegue primero). Con
        # tasks revisa la cancelación y el timeout es scar_panic(); sin tasks
        # termina el proceso.
        #
        # Un fd que no está abierto es un panic al instante (con FD_SET, un fd
        # negativo o >= FD_SETSIZE escribiría fuera del fd_set). EBADF dentro
        # del loop es otra task que cerró el fd; EINTR, seguir.
        def fd_invalido(panic):
            return (
                f'        {panic}("read_pipe: el fd=%d no está abierto (no se heredó al "\n'
                '            "arrancar ni viene de pipe_new())", fd);\n'
            )

        def chequeo_fd(panic):
            return (
                "    if (fd < 0 || fd >= FD_SETSIZE || fcntl(fd, F_GETFD) == -1) {\n"
                + fd_invalido(panic) +
                "    }\n"
            )

        def chequeo_select(panic):
            return (
                "        if (__scar_rc < 0 && errno == EBADF) {\n"
                "    " + fd_invalido(panic).replace("\n            ", "\n                ") +
                "        }\n"
            )

        if self.has_tasks:
            read_pipe_helper = runtime_c.texto(
                "read_pipe_tareas",
                CHEQUEO_FD=chequeo_fd('scar_panic'),
                CHEQUEO_SELECT=chequeo_select('scar_panic'),
            )
        else:
            read_pipe_helper = runtime_c.texto(
                "read_pipe_main",
                CHEQUEO_FD=chequeo_fd('scar_panic_main'),
                CHEQUEO_SELECT=chequeo_select('scar_panic_main'),
            )

        # E/S de red: Socket/Listener son typedefs de un fd. tcp_connect() es
        # un connect() bloqueante sin timeout propio (el intérprete sí lo
        # acota; diferencia aceptada). .read()/.accept() usan el mismo
        # select() en pasos que read_pipe(). Si read_pipe ya definió
        # __scar_io_monotonic_now, se reusa; el macro del timeout se repite
        # (redefinir un macro idéntico es válido).
        if self.needs_net_io:
            net_io_typedefs = (
                "typedef int64_t ScarSocket;\n"
                "typedef int64_t ScarListener;"
            )

            net_io_connect_listen = runtime_c.texto("net_connect_listen")

            # .read()/.accept(): el mismo sondeo que scar_read_pipe(), con las
            # dos variantes.
            if self.has_tasks:
                net_io_reads = runtime_c.texto("net_reads_tareas")
            else:
                clock_block = (
                    "" if self.needs_read_pipe else
                    "#define SCAR_IO_TIMEOUT_SECONDS 7.5\n"
                    "\n"
                    "static double __scar_io_monotonic_now(void) {\n"
                    "    struct timespec ts;\n"
                    "    clock_gettime(CLOCK_MONOTONIC, &ts);\n"
                    "    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;\n"
                    "}\n"
                    "\n"
                )
                net_io_reads = runtime_c.texto(
                    "net_reads_main",
                    CLOCK_BLOCK=clock_block,
                    IO_TIMEOUT='#define SCAR_IO_TIMEOUT_SECONDS 7.5\n\n' if self.needs_read_pipe else '',
                )

            net_io_helpers = net_io_connect_listen + "\n\n" + net_io_reads
        return (pipe_struct_typedef, pipe_typedef, file_typedef, extern_type_typedefs,
                file_io_helpers, read_pipe_helper, net_io_typedefs, net_io_helpers)

    def _runtime_tareas(self):
        """El runtime de tasks, el guard de las extern fn y el worker de FFI
        aislado."""
        # (C8) se asignan solo en algunas ramas y la pasada las devuelve siempre
        sleep_helper = None
        arena_support = None
        task_context_struct = None
        task_context_helpers = None
        idiv_helper = None
        imod_helper = None
        str_index_helper = None
        if self.has_tasks:
            # sleep() es un punto de cancelación: duerme en pasos cortos
            # revisando la bandera, como _interruptible_sleep() del intérprete.
            sleep_helper = runtime_c.texto("sleep")
            arena_support = runtime_c.texto("arena")
            task_context_struct = runtime_c.texto("task_context_struct")
            task_context_helpers = runtime_c.texto(
                "task_context",
                VIVOS_RUNTIME_C=_vivos_runtime_c('__thread '),
            )
            idiv_helper = runtime_c.texto(
                "idiv",
                PANIC='scar_panic',
            )
            imod_helper = runtime_c.texto(
                "imod",
                PANIC='scar_panic',
            )
            # s[i] es el i-ésimo carácter UTF-8, como en el intérprete.
            str_index_helper = runtime_c.texto(
                "str_index",
                PANIC='scar_panic',
            )
        else:
            sleep_helper = (
                "static void scar_sleep(double seconds) {\n"
                "    struct timespec ts;\n"
                "    ts.tv_sec = (time_t)seconds;\n"
                "    ts.tv_nsec = (long)((seconds - (double)ts.tv_sec) * 1e9);\n"
                "    nanosleep(&ts, NULL);\n"
                "}"
            )
            # Sin tasks no hay cascada: un panic termina el proceso.
            idiv_helper = runtime_c.texto(
                "idiv",
                PANIC='scar_panic_main',
            )
            imod_helper = runtime_c.texto(
                "imod",
                PANIC='scar_panic_main',
            )
            # s[i] es el i-ésimo carácter UTF-8, como en el intérprete.
            str_index_helper = runtime_c.texto(
                "str_index",
                PANIC='scar_panic_main',
            )

        # Un crash dentro de una `extern fn` es un panic con mensaje, no un
        # segfault mudo. Cada llamada pasa por
        # scar_extern_guarded_<nombre>, que arma un sigsetjmp antes del
        # símbolo. El manejador (scar_extern_install_guard(), al arrancar main)
        # atrapa SIGSEGV/SIGBUS/SIGILL/SIGFPE/SIGABRT solo mientras
        # scar_extern_guard_active, y salta de vuelta. Una señal fuera de una
        # llamada vigilada restaura el comportamiento por defecto y se
        # re-lanza.
        #
        # No repara la memoria si el C externo ya escribió fuera de sus límites:
        # solo garantiza un final reconocible (exit(1) o la cascada de panic).
        # Para seguir corriendo después del crash está el worker aislado
        # (abajo).
        guard_storage = "_Thread_local " if self.has_tasks else ""
        # El str que devuelve una extern fn es siempre una copia propia, como
        # por el worker aislado (si no, se liberaba un buffer estático o el
        # entorno de getenv).
        extern_guard_helpers = runtime_c.texto(
            "extern_guard",
            GUARD_STORAGE=str(guard_storage),
            FFI_STR_PROPIA=runtime_c.texto("ffi_str_propia") if self._extern_str_en_proceso() else '',
        )
        if self.has_tasks:
            extern_guard_helpers += runtime_c.texto("extern_crash_tareas")
        else:
            extern_guard_helpers += runtime_c.texto("extern_crash_main")

        # Aislamiento de proceso para las librerías elegibles
        # (pipe_isolated_libs): un worker persistente por librería, compilado
        # en build time (ffi_worker.build_worker_source) y lanzado con
        # fork()+exec() al arrancar main(), antes de cualquier otro código
        # (el mismo diseño de ffi_worker.py).
        ffi_worker_runtime = ""
        if self.pipe_isolated_libs:
            mutex_field = "    pthread_mutex_t mu;\n" if self.has_tasks else ""
            ffi_worker_runtime += runtime_c.texto(
                "ffi_worker",
                MUTEX_FIELD=str(mutex_field),
            )
            if self.has_tasks:
                ffi_worker_runtime += runtime_c.texto("ffi_worker_crash_tareas")
            else:
                ffi_worker_runtime += runtime_c.texto("ffi_worker_crash_main")
            for library in sorted(self.pipe_isolated_libs):
                lib_ident = self._ffi_lib_ident(library)
                mutex_init = ", PTHREAD_MUTEX_INITIALIZER" if self.has_tasks else ""
                ffi_worker_runtime += (
                    f"static ScarFfiWorkerHandle scar_ffi_worker_{lib_ident} = "
                    f"{{ -1, -1, -1, 0, \"\"{mutex_init} }};\n"
                )
            ffi_worker_runtime += (
                "\n"
                "static void scar_ffi_worker_start_all(void) {\n"
                "    int __scar_strict = scar_ffi_strict_mode();\n"
            )
            for library in sorted(self.pipe_isolated_libs):
                lib_ident = self._ffi_lib_ident(library)
                path = self.ffi_worker_paths[library]
                ffi_worker_runtime += (
                    f"    scar_ffi_worker_start_one(&scar_ffi_worker_{lib_ident}, "
                    f'"{library}", "{path}", __scar_strict);\n'
                )
            ffi_worker_runtime += "}\n"
        return (sleep_helper, arena_support, task_context_struct, task_context_helpers,
                idiv_helper, imod_helper, str_index_helper, extern_guard_helpers,
                ffi_worker_runtime)

    def _runtime_preambulo(self):
        """str_concat, los #define e #include del preámbulo, el bloque de struct
        (B12) y el pool de scar_malloc."""
        # scar_str_concat(): una sola versión, con o sin tasks.
        str_concat_helper = runtime_c.texto("str_concat")

        # pthread/time hacen falta para las tasks y para Chan<T> (mutex), que
        # un programa puede usar sin tasks.
        needs_pthread = self.has_tasks or self.uses_chan
        # _GNU_SOURCE, antes de todo #include: nanosleep, sigsetjmp,
        # clock_gettime (POSIX, que glibc no declara sin ella) y
        # pthread_tryjoin_np (GNU, scar_join_wait). La necesitan también
        # read_pipe/red y sleep sin tasks.
        needs_gnu_source = (
            needs_pthread or self.libreria or self.needs_read_pipe or self.needs_net_io
            or self.needs_now or self.needs_sleep or bool(self.extern_sigs)
            or bool(getattr(self, "_fns_recursivas", None))   # Sigaction/sigaltstack
        )
        # Cada bloque de struct lleva un encabezado de 8 bytes antes del
        # puntero que dice de dónde salió (malloc o la arena de una task); 8 y
        # no 16 porque ningún tipo de SCAR pide alineación mayor (con 16, un
        # struct chico en la arena ocupaba el doble). scar_blk_release() libera
        # solo si es de malloc. Los structs embebidos (slots de Vec<Struct>) no
        # son bloques: solo se les llama {T}_free_fields.
        # Hoy todo bloque es de malloc (nadie escribe SCAR_BLK_ARENA); el
        # encabezado sigue.
        blk_runtime = runtime_c.texto("blk")
        preamble = ""
        if needs_gnu_source:
            preamble += "#define _GNU_SOURCE\n"
        # mallopt() -- ver el mallopt() al arranque de main()
        # gcc convierte printf("%s\\n", x) en puts(x), y ASan no revisa el
        # argumento de puts ni de printf: bajo ASan cada str de print() se lee
        # antes con strlen(), que ASan sí revisa.
        preamble += runtime_c.texto("preambulo")
        if needs_pthread:
            preamble += (
                "#include <pthread.h>\n"
                "#include <time.h>\n"
            )
        elif self.needs_read_pipe or self.needs_net_io or self.needs_rand or self.needs_now or self.needs_sleep:
            # sin needs_pthread, <time.h> todavía no entró: lo necesitan
            # read_pipe/red (clock_gettime), rand() (srand(time(NULL))) y now()
            preamble += "#include <time.h>\n"
        if self.has_tasks or self.extern_sigs:
            # el wrapper vigilado de una `extern fn` usa sigsetjmp, haya o no
            # tasks
            preamble += "#include <setjmp.h>\n"
        if self.has_tasks:
            preamble += "#include <errno.h>\n"  # ETIMEDOUT de pthread_cond_timedwait en join()
        if self.extern_sigs:
            preamble += "#include <signal.h>\n"
        if self.has_tasks or self.uses_chan:
            # el refcount de Chan es _Atomic, también sin tasks
            preamble += "#include <stdatomic.h>\n"
        if self.uses_pipe or self.needs_read_pipe or self.pipe_isolated_libs:
            preamble += "#include <unistd.h>\n"  # pipe/read/fork/dup2/close/execl
        if self.needs_read_pipe:
            preamble += "#include <sys/select.h>\n"  # select()/fd_set/FD_*/struct timeval
            preamble += "#include <fcntl.h>\n"       # fcntl(F_GETFD): ¿el fd está abierto?
            preamble += "#include <errno.h>\n"       # EBADF de select()
        if self.pipe_isolated_libs:
            preamble += "#include <sys/wait.h>\n"  # waitpid y WIF*: scar_ffi_worker_crash_reason
        if self.needs_file_io:
            preamble += "#include <errno.h>\n"  # strerror(errno) en los 3 caminos de error
        if self.needs_net_io:
            preamble += (
                "#include <sys/types.h>\n"
                "#include <sys/socket.h>\n"
                "#include <netinet/in.h>\n"
                "#include <netdb.h>\n"
                "#include <errno.h>\n"
                "#include <unistd.h>\n"       # close() (repetir un include es inofensivo)
                "#include <sys/select.h>\n"   # select()/fd_set/FD_*/struct timeval
            )
        # scar_malloc()/scar_free(): pool thread-local para objetos chicos y
        # de vida corta. Se emite si algún sitio del C lo llama (concat/index de
        # str, formateo para print(), int(), los Err de E/S...); fmt_defs cubre
        # struct/Result/Option.
        needs_scar_malloc = (
            self.needs_str_index
            or self.needs_str_concat
            or self.needs_fmt_f64
            or self.needs_repr_str
            or bool(self.fmt_defs)
            or self.needs_builtin_int
            or self.needs_builtin_int64
            or self.needs_option_str_free
            or self.needs_file_io
            or self.needs_net_io
            or self.needs_read_pipe
            or self.needs_task_str_free
            or self._extern_str_en_proceso()  # scar_ffi_str_propia() copia con scar_malloc()
            or bool(self.pipe_isolated_libs)  # scar_ffi_read_str() usa scar_malloc()
        )
        # Con tasks, el freelist _Thread_local de un hilo que termina quedaba
        # huérfano (un programa que lanza muchas tareas lo acumula sin límite).
        # pthread no corre destructores de _Thread_local: se usa una key
        # centinela (pthread_key_create con destructor, creada con
        # pthread_once) que cada hilo marca al tocar el pool; su destructor
        # vacía el freelist de ese hilo. Sin pthread solo existe main.
        scar_pool_cleanup = (
            runtime_c.texto("pool_cleanup")
            if needs_pthread else ""
        )
        scar_pool_touch = "    scar_pool_touch_thread();\n" if needs_pthread else ""
        scar_pool_allocator = runtime_c.texto(
            "pool_allocator",
            SCAR_POOL_CLEANUP=str(scar_pool_cleanup),
            SCAR_POOL_TOUCH=str(scar_pool_touch),
            TEXTO_SIN_TOPE_C=_TEXTO_SIN_TOPE_C,
        )
        return (str_concat_helper, blk_runtime, preamble, needs_scar_malloc,
                scar_pool_allocator)

    def _armar_runtime(self, sleep_helper, arena_support, task_context_struct,
                       task_context_helpers, idiv_helper, imod_helper, str_index_helper,
                       extern_guard_helpers, ffi_worker_runtime, str_concat_helper,
                       blk_runtime, preamble, needs_scar_malloc, scar_pool_allocator):
        """El comienzo del archivo: el preámbulo y el runtime que el programa
        usa, en orden."""
        parts = [preamble]
        rand_rt = _rand_runtime_c(self.needs_rand, self.has_tasks)
        if rand_rt:
            parts.append(rand_rt)  # antes de scar_ctx_new, que lo usa
        if self.structs:
            parts.append(blk_runtime)
        # Si ningún flag lo pidió, el lugar queda reservado y al final se
        # decide por lo que el C de verdad llama (ver el return).
        lugar_pool = len(parts)
        parts.append(scar_pool_allocator if needs_scar_malloc else None)
        if self.has_tasks:
            parts.append(arena_support)
            parts.append(task_context_struct)
            parts.append(task_context_helpers)
        else:
            # Sin tasks, el mismo registro de dueñas vivas (global: un solo hilo)
            # y un único punto de panic que lo suelta antes de exit(1), gemelo de
            # scar_panic().
            parts.append(_vivos_runtime_c("") + _PANIC_MAIN_C)
        if self.needs_sleep:
            # sleep_helper ya está definido en la rama con o sin tasks: acá solo
            # se decide si el programa lo usa.
            parts.append(sleep_helper)
        if self.needs_iarith:
            parts.append(self._iarith_helper())
        if self.needs_idiv:
            parts.append(idiv_helper)
        if self.needs_to_i32:
            parts.append(_to_i32_helper_c(self.has_tasks))
        if self.needs_chr_ord:
            parts.append(_chr_ord_helpers_c(self.has_tasks))
        if self.needs_shift or self._usa_sar_k:
            parts.append(_shift_helpers_c(self.needs_shift, self.has_tasks))
        if self.needs_i64:
            parts.append(_i64_helpers_c(self.has_tasks))
        if self.needs_abs_min_max:
            parts.append(_abs_min_max_helpers_c(self.has_tasks))
        if self.needs_imod:
            parts.append(imod_helper)
        if self.needs_now:
            # now() tiene su propio reloj: no depende de scar_monotonic_now()
            # (solo con tasks) ni de __scar_io_monotonic_now() (solo con E/S sin
            # tasks), ni del orden de los flags.
            parts.append(
                "static inline double scar_now(void) {\n"
                "    struct timespec ts;\n"
                "    clock_gettime(CLOCK_MONOTONIC, &ts);\n"
                "    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;\n"
                "}"
            )
        if self.needs_str_index or self.needs_utf8_len:
            parts.append(
                runtime_c.texto("strc")
            )
        if self.needs_str_index:
            parts.append(str_index_helper)
        if self.needs_str_concat:
            parts.append(str_concat_helper)
        if self.needs_str_cmp:
            # Comparación de str por contenido; fa/fb dicen si el operando es un
            # buffer fresco, que se libera después de comparar.
            parts.append(
                "static inline int scar_str_cmp_own(const char* a, const char* b, int fa, int fb) {\n"
                "    int r = strcmp(a, b);\n"
                "    if (fa) scar_free((char*)a);\n"
                "    if (fb) scar_free((char*)b);\n"
                "    return r;\n"
                "}"
            )
        if self.extern_sigs:
            # Después de task_context_helpers: con tasks,
            # scar_extern_report_crash() llama a scar_panic().
            parts.append(extern_guard_helpers)
        if self.pipe_isolated_libs:
            # Después de extern_guard_helpers, por lo mismo.
            parts.append(ffi_worker_runtime)
        return parts, lugar_pool

    def _armar_tipos(self, struct_typedefs, struct_ctors, struct_deepcopies,
                     struct_deepcopy_intos, struct_frees, struct_fwd_decls,
                     struct_free_fwd_decls, struct_deepcopy_fwd_decls,
                     struct_deepcopy_into_fwd_decls, struct_free_fields_fwd_decls,
                     struct_free_fields, struct_clones, map_hash_helpers,
                     pipe_struct_typedef, file_typedef, extern_type_typedefs,
                     net_io_typedefs, parts):
        """Los tipos: typedefs y prototipos, Pipe/File/red, canales, Vec, Map,
        genéricos y structs, en el orden en que C los necesita."""
        # El cluster file/net typedefs, generic_defs, chan_defs, vec_defs,
        # map_defs va antes de struct_typedefs: un campo de struct puede ser
        # Vec<T>/Map<K,V> por valor, y su tipo tiene que existir antes. Lo que el cluster necesita de un struct es solo el tipo
        # incompleto (struct_fwd_decls) o un prototipo; lo que necesita el
        # struct completo (Chan<Struct>, Vec<Struct>) va después.
        if self.fn_typedefs:
            # Typedefs de puntero a función (Fn_i32_i32, ver _fn_c_type), antes
            # de todo: sus firmas solo nombran tipos (un struct como puntero
            # incompleto).
            parts.append("\n".join(self.fn_typedefs))
        if struct_fwd_decls:
            # Primero los tipos incompletos de los structs (ver struct_fwd_decls).
            parts.append("\n".join(struct_fwd_decls))
        if struct_free_fwd_decls:
            parts.append("\n".join(struct_free_fwd_decls))
        if struct_deepcopy_fwd_decls:
            parts.append("\n".join(struct_deepcopy_fwd_decls))
        if struct_deepcopy_into_fwd_decls:
            parts.append("\n".join(struct_deepcopy_into_fwd_decls))
        if struct_free_fields_fwd_decls:
            parts.append("\n".join(struct_free_fields_fwd_decls))
        if self.needs_file_io:
            # Antes de generic_defs: Result<File> necesita ScarFile.
            parts.append(file_typedef)
        if self.needs_net_io:
            # Lo mismo: Result<Socket>/Result<Listener>.
            parts.append(net_io_typedefs)
        if self.uses_pipe:
            parts.append(pipe_struct_typedef)
        if self.needs_file_io or self.needs_net_io:
            parts.append(self._handles_rt_c())
        if self.extern_types:
            parts.append(extern_type_typedefs)
        if self.chan_typedefs:
            # Antes de generic_defs: el typedef puntero Chan_<T> tiene que existir
            # cuando se arma Option_Chan_<T>. Las funciones de Chan<T> van después.
            parts.append("\n\n".join(self.chan_typedefs))
        if self.vec_typedefs:
            # Typedefs de Vec_<T> para todo T: después de chan_typedefs
            # (Vec<Chan<U>>) y de struct_fwd_decls (Vec<Struct>), antes de
            # generic_defs (Option<Vec<T>> lo embebe por valor) y de
            # struct_typedefs (campos Vec<T>).
            parts.append("\n".join(self.vec_typedefs))
        if self.map_typedefs:
            # Lo mismo para Map.
            parts.append("\n\n".join(self.map_typedefs))
        if self.vec_struct_free_fwd_decls:
            parts.append("\n".join(self.vec_struct_free_fwd_decls))
        if self.map_free_fwd_decls:
            parts.append("\n".join(self.map_free_fwd_decls))
        if self.generic_defs:
            parts.append("\n\n".join(self.generic_defs))
        if self.clone_protos:
            # Antes de las funciones de Vec, que las usan con Vec<Vec<T>> (get()
            # clona el Vec de adentro).
            parts.append("\n".join(self.clone_protos))
        if self.chan_defs:
            # Después de generic_defs: scar_chan_recv_*() usa
            # Option_<T>_Some()/_None().
            parts.append("\n\n".join(self.chan_defs))
        if self.vec_defs:
            # Lo mismo: get()/pop() de Vec usan Option_<T>.
            parts.append("\n\n".join(self.vec_defs))
        if self.needs_map_runtime:
            # Las funciones de hash, una sola vez para todos los Map.
            parts.append(map_hash_helpers)
        if self.map_defs:
            # Después de generic_defs (get()/remove() usan Option_<V>) y de
            # map_hash_helpers (find/grow llaman a scar_hash_*()).
            parts.append("\n\n".join(self.map_defs))
        if struct_typedefs:
            parts.append("\n".join(struct_typedefs))
        if struct_ctors:
            parts.append("\n\n".join(struct_ctors))
        if struct_deepcopies:
            parts.append("\n\n".join(struct_deepcopies))
        if struct_deepcopy_intos:
            parts.append("\n\n".join(struct_deepcopy_intos))
        if struct_frees:
            parts.append("\n\n".join(struct_frees))
        if struct_free_fields:
            parts.append("\n\n".join(struct_free_fields))
        if self.chan_struct_defs:
            # Chan<Struct> recién acá: el nodo embebe el struct por valor y
            # necesita su definición completa (struct_typedefs).
            parts.append("\n\n".join(self.chan_struct_defs))
        if self.vec_struct_defs:
            # Vec<Struct> recién acá, por lo mismo (sizeof del struct).
            parts.append("\n\n".join(self.vec_struct_defs))
        if self.retval_free_defs:
            parts.append("\n\n".join(self.retval_free_defs))
        if struct_clones:
            parts.append("\n\n".join(struct_clones))
        if self.clone_defs:
            parts.append("\n\n".join(self.clone_defs))

    def _armar_funciones(self, fns, decls, extern_guarded_wrappers, task_args_typedefs,
                         task_thread_defs, injected_slots_typedefs, bodies,
                         extern_result_wrappers, fmt_f64_helper, repr_str_helper,
                         parse_int_core, builtin_int_helper, builtin_int64_helper,
                         pipe_typedef, file_io_helpers, read_pipe_helper, net_io_helpers,
                         needs_scar_malloc, scar_pool_allocator, parts, lugar_pool):
        """Las funciones: helpers de E/S y de formato, prototipos, cuerpos,
        threads de task; y el archivo final."""
        if self.uses_pipe:
            parts.append(pipe_typedef)
        if self.needs_read_pipe:
            # Después de generic_defs: scar_read_pipe() usa Result_str.
            parts.append(read_pipe_helper)
        if self.needs_file_io:
            # Después de generic_defs: usa Result_File, Result_str y Result_i32.
            parts.append(file_io_helpers)
        if self.needs_net_io:
            # Después de generic_defs: usa Result_Socket, Result_Listener,
            # Result_str y Result_i32.
            parts.append(net_io_helpers)
        if self._read_bytes_usados:
            parts.append(self._read_bytes_helpers_c())
        if self.needs_fmt_f64:
            parts.append(fmt_f64_helper)
        if self.needs_repr_str:
            parts.append(repr_str_helper)
        if self._imprime_fns:
            # el nombre de una fn usada como valor (print de una fn o de un
            # Vec/Map de fns); la tabla va después de las decls
            parts.append("typedef void (*ScarFnCualquiera)(void);\n"
                         "static const char* scar_fn_nombre(ScarFnCualquiera f);")
        if self.fmt_defs:
            # prototipos primero (un struct con un Vec de sí mismo: se formatean
            # uno al otro)
            parts.append("\n".join(self.fmt_protos))
            parts.append("\n\n".join(self.fmt_defs))
        if self.needs_builtin_int or self.needs_builtin_int64:
            parts.append(parse_int_core)
        if self.needs_builtin_int:
            parts.append(builtin_int_helper)
        if self.needs_builtin_int64:
            parts.append(builtin_int64_helper)
        if self.needs_arg:
            # después de generic_defs/fmt_defs: usa Option_str_Some/_None
            parts.append(self._arg_helper_c())
        if injected_slots_typedefs:
            # InjectedSlots_<task> necesita Chan_<T> (chan_typedefs, ya emitido).
            parts.append("\n\n".join(injected_slots_typedefs))
        if task_args_typedefs:
            parts.append("\n\n".join(task_args_typedefs))
        parts.append("\n".join(decls))
        if self._envoltorios_fn:
            parts.append("\n\n".join(c for _, c, _ in self._envoltorios_fn.values()))
        if self._imprime_fns:
            parts.append(
                "static const char* scar_fn_nombre(ScarFnCualquiera f) {\n"
                + "".join(f"    if (f == (ScarFnCualquiera){c}) return \"{n}\";\n"
                          for c, n in sorted(self._fns_como_valor.items()))
                + "    return \"?\";\n}")
        if extern_guarded_wrappers:
            # Después de decls (llama al símbolo extern) y de extern_guard_helpers;
            # antes de extern_result_wrappers y bodies, que lo llaman.
            parts.append("\n\n".join(extern_guarded_wrappers))
        if extern_result_wrappers:
            # Después de decls: llama al wrapper vigilado.
            parts.append("\n\n".join(extern_result_wrappers))
        if self._vivos_drop_fwd:
            parts.append("\n".join(self._vivos_drop_fwd))
        parts.append("\n\n".join(bodies))
        if self.libreria:
            parts.append(self._exportadas_c(fns))
        if task_thread_defs:
            parts.append("\n\n".join(task_thread_defs))
        if self._vivos_drop_defs:
            parts.append("\n\n".join(self._vivos_drop_defs))
        if not needs_scar_malloc and _RE_USA_POOL.search("\n".join(p for p in parts if p is not None)):
            # Lo que decide si hace falta scar_malloc es lo que el C generado usa
            # (una lista de flags se quedaba corta).
            parts[lugar_pool] = scar_pool_allocator
        if self.needs_str_index or self.needs_utf8_len:
            parts.insert(1, _STRC_C)
        if self.libreria:
            # el panic no escribe en stderr (lo da scar_error())
            parts.insert(1, "#define SCAR_LIBRERIA 1")
        return _marcas_strc("\n\n".join(p for p in parts if p is not None) + "\n",
                            self.needs_str_index or self.needs_utf8_len)
