"""Mixin Estado de Codegen (paso C6): el constructor. _iniciar crea todo el
estado de self que los demás mixins leen y escriben, cada atributo con su
comentario de qué es.
"""

from parser import FnDecl, ExternFnDecl, ExternTypeDecl, ExternLibDecl, StructDecl
from types_ import T_I32, T_VOID, ffi_tipo_ok
import nombres_c

from .comun import _SIGUE, CodegenError, FFI_SUPPORTED_TYPES


class Estado:
    def __init__(self, program, libreria=False):
        # El codegen trabaja sobre una copia con los nombres del usuario
        # protegidos (nombres_c.py); un error los muestra como el
        # usuario los escribió.
        program, self.nombres = nombres_c.proteger(program)
        self.libreria = libreria  # cli.py build --lib (una .so con las export fn)
        try:
            self._iniciar(program)
        except CodegenError as e:
            raise CodegenError(self.nombres.desproteger(str(e))) from None

    def _iniciar(self, program):
        self._iniciar_tipos(program)
        self._iniciar_emision()
        self._iniciar_propiedad()
        return self._iniciar_analisis_y_registro(program)

    def _iniciar_tipos(self, program):
        """El programa, los structs y enums, los genéricos (plantillas e
        instancias) y las fn como valor."""
        self.program = program
        self._reasignaciones = None   # ver _alcanza_lugar
        self.structs = {}       # nombre -> {campo: TypeAnn}, en orden de declaración
        self.enums = {}         # nombre de C del struct -> [(variante, n datos)]
        # Struct genérico ('struct Caja<T>'): acá va la plantilla cruda, con T sin
        # sustituir. self.structs solo tiene structs concretos ('Caja_i32'): cada
        # instancia se monomorfiza al primer uso (_ensure_generic_struct_instance).
        self.generic_structs = {}  # nombre -> {"type_params": [str,...], "fields": {campo: TypeAnn}}
        # (nombre, tuple(args concretos)) -> nombre de C ya generado ('Caja_i32')
        self.generic_struct_instances = {}
        # Un struct genérico concreto es SIEMPRE su struct monomorfizado (Nodo<f64>
        # es Nodo_f64), así Vec, campos, firmas y Chan lo tratan como a cualquier
        # struct. _generic_origin dice de qué plantilla salió cada uno;
        # _tbind, los T de la instancia de fn genérica que se está generando.
        self._generic_origin = {}
        self._tbind = None
        self.generic_fn_bindings = {}
        # Fn genérica ('fn bar<T>'): la firma cruda más el FnDecl. No entra en
        # fn_sigs (que solo tiene tipos concretos): cada instancia se genera al
        # llamarla con tipos concretos (_ensure_generic_fn_instance).
        self.generic_fns = {}  # nombre -> {"type_params": [...], "params": [...], "ret": TypeAnn, "decl": FnDecl}
        # (nombre, tuple(args concretos)) -> nombre de C de la instancia
        self.generic_fn_instances = {}
        # nombre de C de la instancia -> FnDecl clon (mismo cuerpo, otro nombre);
        # generate() los compila como a cualquier fn
        self.generic_fn_decls = {}
        self.fn_sigs = {}       # nombre -> (param_types: list[TypeAnn], ret: TypeAnn)
        self.generic_types = {}  # (nombre, TypeAnn interno) -> nombre de tipo C (ej. "Result_i32")
        self.generic_defs = []   # typedefs + constructores, en orden de primer uso
        self.fmt_protos = []     # sus prototipos, antes de todas las definiciones
        # fn usadas como valor: nombre de C -> nombre a imprimir ("<fn x>")
        self._fns_como_valor = {}
        self._imprime_fns = False  # la tabla solo se emite si algo imprime una fn
        # envoltorios de las fn usadas como valor cuyo retorno con dueño puede no
        # ser nuevo: copian el resultado, para cumplir el contrato de retorno
        self._envoltorios_fn = {}
        self.fmt_defs = []       # formateadores de print() para tipos genéricos
        self.fmt_registered = set()
        self.struct_fmt_registered = set()  # nombres de struct con scar_fmt_<Name> ya emitido
        self.needs_builtin_int = False
        self.needs_builtin_int64 = False
        self.needs_arg = False  # arg(i) -> scar_arg(), main(argc, argv)
        self.needs_option_str_free = False  # Option_str_free usa scar_free
        self.needs_rand = False  # rand(): scar_rand() y la siembra de main
        self.needs_now = False   # now(): scar_now(), propio (no depende de si hay tasks)
        self.needs_fmt_f64 = False   # %g de C no agrega ".0"; Python sí (str(5.0) == "5.0")
        self.needs_repr_str = False  # repr() de Python: comillas simples o dobles según el texto
        self.tmp_counter = 0
        self.cur_ret_ty = None   # tipo de retorno de la fn que se está generando
        self._if_simple = None  # Ver IfStmt (else if plano)
        self.cur_fn_name = None  # nombre de la fn/task que se está generando (ver ReturnStmt, copia de StrLit fresca)
        self.task_sigs = {}     # como fn_sigs; una task solo se llama con spawn
        self.task_decls = {}    # nombre -> FnDecl, para emitir su wrapper de pthread

    def _iniciar_emision(self):
        """Lo que el programa usa (tasks, canales, builtins: los needs_*) y lo que
        se va emitiendo (typedefs y funciones de Chan, Vec, Map, clones, vivas)."""
        # task -> {T interno del Chan<T> -> campo} de su struct InjectedSlots_<task>
        # (solo tasks con `accepts`). Lo llena _gen_injected_slots_struct y lo leen
        # inject_chan()/accept_chan().
        self.task_accept_slots = {}
        # has_tasks decide si se emiten TaskContext, arena y setjmp. Una librería
        # usa siempre el runtime con tareas: su estado es por hilo y se
        # puede llamar en paralelo desde varios hilos.
        self.has_tasks = self.libreria
        self.needs_sleep = False  # se llamó sleep(): emitir scar_sleep() aunque no haya tasks
        self.needs_idiv = False  # división i32/i32: necesita scar_idiv() con panic real
        self.needs_to_i32 = False  # to_i32(x): scar_to_i32 con chequeo de rango
        self.needs_chr_ord = False  # chr()/ord(): scar_chr/scar_ord
        self.needs_shift = False  # << / >> con corrimiento no constante: scar_shl/scar_shr
        self._usa_sar_k = False   # >> con corrimiento literal: scar_sar_k
        self._read_bytes_usados = set()  # read_bytes() usado en "file"/"socket"
        self.needs_imod = False  # módulo i32/i32: necesita scar_imod() con panic real
        self.needs_iarith = False  # +,-,* y negación de i32 con panic por overflow
        self.needs_i64 = False  # aritmética, bits y conversiones de i64 (_i64_helpers_c)
        self.needs_abs_min_max = False  # abs/min/max (_abs_min_max_helpers_c)
        self.needs_str_concat = False  # str + str: necesita scar_str_concat() (malloc)
        self.needs_str_cmp = False  # str == str: necesita scar_str_cmp_own()
        self.needs_str_index = False  # s[i]: necesita scar_str_index() (malloc + panic en rango)
        self.needs_utf8_len = False  # len(s)/s.len(): caracteres, no bytes (scar_utf8_len)
        # Alguna task recibe un str: gen_fn emite un scar_free() condicional para
        # él, y hace falta el pool allocator aunque nada más lo use.
        self.needs_task_str_free = False
        # True mientras se genera el cuerpo de main en un programa con tasks: cada
        # `return` (a cualquier profundidad) emite antes el epílogo de la raíz, que
        # si no quedaría inalcanzable.
        self.in_main_root_scope = False
        self._vivos_drop_cache = {}  # (tipo, origen) -> scar_drop_N
        self._vivos_drop_defs = []
        self._vivos_drop_fwd = []
        self._vivos_out = None
        self._vivos_fn_on = False
        # tipos de los BinOp mientras se genera una expresión (ver infer y gen_expr)
        self._infer_cache = None
        self._vivos_pub = {}
        self._vivos_hist = {}
        self._vivos_excluir = set()
        self.pending_expr_temps = []  # temporales de la sentencia en curso (ver _flush_pending_expr_temps)
        self.chan_types = {}     # (Chan, T) -> nombre de tipo C (ej. "Chan_i32")
        self.chan_defs = []      # funciones de Chan<T> (primitivo/str), en orden de primer uso
        # Typedefs de Chan_<T> (solo el puntero), separados de sus funciones:
        # Option<Chan<T>> los necesita antes de generic_defs, y las funciones de
        # Chan<T> van después, porque usan Option_<T>.
        self.chan_typedefs = []
        # Chan<Struct>: el nodo de la cola guarda el struct por valor, así que sus
        # funciones van después de struct_typedefs (necesitan el struct completo).
        self.chan_struct_defs = []
        # Un typedef de puntero a función por cada firma 'fn(...) -> U' distinta
        # (ver _fn_c_type).
        self.fn_types = {}   # tuple(TypeAnn de params+retorno) -> nombre de tipo C
        self.fn_typedefs = []
        self.uses_chan = False   # con has_tasks: pthread y -lpthread (un canal usa mutex)
        self.uses_pipe = False       # ScarPipe, scar_pipe_new() y <unistd.h>
        self.needs_read_pipe = False  # scar_read_pipe() y <sys/select.h>
        self.needs_file_io = False   # ScarFile, scar_file_*() y <errno.h>
        self.needs_net_io = False    # ScarSocket, ScarListener, scar_tcp_*() y los #include de red
        self.vec_types = {}      # (Vec, T) -> nombre de tipo C (ej. "Vec_i32")
        self.vec_defs = []       # typedefs + funciones de Vec<T> (primitivo/str/Chan<U>), en orden de primer uso
        # Funciones de Vec<Struct>: el arreglo guarda los structs por valor, así
        # que van después de struct_typedefs (sizeof y copia necesitan el struct
        # completo). El typedef de Vec_<Struct> va antes, en vec_typedefs.
        self.vec_struct_defs = []
        # Prototipos de scar_vec_free_<Struct>: {Struct}_free los llama para un
        # campo Vec<Struct>, y la definición recién viene en vec_struct_defs.
        self.vec_struct_free_fwd_decls = []
        # Typedefs de Vec_<T> ({data, len, cap}) de todo T. Van después de
        # chan_typedefs (un Vec<Chan<U>> los usa) y antes de generic_defs (un
        # Option<Vec<T>> o Result<Vec<T>> guarda el Vec por valor).
        self.vec_typedefs = []
        # Lo mismo para Map<K,V>
        self.map_typedefs = []
        self.map_free_fwd_decls = []
        self.map_types = {}      # (Map, K, V) -> nombre de tipo C (ej. "Map_str_i32")
        self.map_defs = []       # typedefs + funciones de Map<K,V>, en orden de primer uso
        # Liberadores (void(*)(void*)) del valor que devuelve una task sin join
        # cuando ese valor tiene datos propios (Vec, Map, str), uno por tipo.
        # Van después de vec_struct_defs.
        self.retval_free_defs = []
        self._retval_free_names = {}
        # Clones profundos de Vec<T>/Map<K,V> que usa {T}_clone; van al
        # final, con sus prototipos.
        self.clone_defs = []
        self.clone_protos = []
        self._clone_names = {}
        self.needs_map_runtime = False  # scar_hash_*(), una vez para todos los Map

    def _iniciar_propiedad(self):
        """El estado de propiedad: dueñas por scope, alias, shadowing, loops
        abiertos."""
        # ---- Propiedad: quién libera cada valor ----
        # Un frame por función/task y por cada bloque anidado, con las variables
        # de ese bloque que son dueñas de un valor del heap (struct, Vec, Map, str
        # propio...), con su origen. Al cerrar el bloque se liberan.
        self.owner_stack = []

        # nombre -> índice del frame de owner_stack donde nació la dueña (ver
        # _mark_owner, _decl_frame_of). Se reinicia en cada gen_fn.
        self._decl_frame = {}
        self._str_mut_promovidas = set()
        self._desmarcadas = set()   # ver _unmark_owner

        # Alias de structs: `let b = a` de un struct que no es dueño -> la raíz
        # real de la que b toma prestado. Solo se consulta en un
        # `return` que devuelve el alias (_returned_owner_names). Se reinicia en
        # cada gen_fn.
        self._alias_root = {}
        # Mientras se genera el lado derecho de un `let` que sombrea a una
        # variable del mismo bloque: nombre -> temporal de C con el valor viejo
        # (_gen_stmts_shadow_safe).
        self._shadow_rhs = {}
        # Shadowing entre bloques (un `let r` dentro de un if que tapa a una r de
        # afuera): (frame de la vieja, nombre) -> (temporal con su valor, frame que
        # la sombrea). Lo usa _live_owners_at_return; caduca al cerrar ese frame.
        self._shadow_free_alias = {}

        # Loops abiertos: {idx, pad, out, flags}. El cuerpo de un loop se genera
        # una vez y corre N veces: una variable de afuera que el cuerpo mueve lleva
        # un flag de C, declarado antes del loop. Se reinicia en gen_fn.
        self._loop_frames = []

    def _iniciar_analisis_y_registro(self, program):
        """Los análisis previos (fresh_str, fresh_owned, consumidos), las
        temporales por sentencia, las extern fn, y el registro de cada
        declaración del programa con sus workers de FFI aislado."""
        # Análisis previos a generar (generate() los corre antes que cualquier fn,
        # porque una fn puede llamar a otra declarada más abajo). Ausencia =
        # "no se sabe" = no se libera.
        # fresh_str_fns: fn/task -> True si su str devuelto es siempre nuevo.
        self.fresh_str_fns = {}

        # fresh_owned_fns: lo mismo para struct/Vec/Map.
        self.fresh_owned_fns = {}
        self.fn_ownership = {}  # nombre -> fresh_owned.FnOwnership
        self.consumed_params = {}  # nombre -> índices de params struct consumidos
        # nombre -> índices de params Option<Struct> cuyo contenido la fn puede
        # quedarse (fresh_owned.resolve_consumed_option_params)
        self.consumed_option_params = {}
        self._args_prestados = set()  # id() de Some/Ok pasados prestados
        # True solo mientras se genera una sentencia que libera sus temporales al
        # terminar (let, asignación, return, expresión suelta). Nunca en la
        # condición de un if/while ni en los límites de un for: lo que se emite
        # ahí queda antes del `while (...)` y se evaluaría una sola vez.
        self._can_capture_arg_temps = False
        # La llamada que es el lado derecho directo del `let` en curso, y por cada
        # llamada generada, los argumentos cuya propiedad pasó al resultado
        # (_arg_transferible).
        self._rhs_let_call = None
        self._transferidos = {}
        # Modo de cada transferencia ("mismo": la variable deja de ser dueña;
        # "anular": sigue siéndolo y queda en NULL), si el resto del bloque solo
        # lee el resultado del `let`, y los temporales contra los que se compara
        # un resultado que puede ser prestado (_rhs_cond_ok).
        self._modo_transfer = {}
        self._rhs_cond_ok = False
        self._cond_resultado = {}
        # Parámetro consumido -> flag de C "todavía es mío" (ver gen_fn), y flags
        # a apagar al terminar la sentencia que lo transfirió.
        self._consume_flags = {}
        self._pending_flag_clears = []
        # En `while let Some(p) = o` (o dueña de un Option<Struct>), p es el
        # contenido de o: mover p lo saca de o (o.tag = 0, como Option::take).
        self._opt_payload_of = {}
        self._take_result = set()  # dueñas Result<Struct> cuyo Ok(x) se puede mover
        self.map_nombres = {}  # c_name de un Map -> (entrada, sufijo, K, V)
        self._pending_takes = []
        # Dueña Option -> slot diferido, para los while let cuyo cuerpo reasigna
        # la fuente (_while_let_slot_diferido).
        self._wl_diferido = {}

        # fn/task que devuelve Result<str> -> "plain": el .value de su Ok es
        # siempre propio y se libera con scar_free (contrato único de str).
        self.result_str_value_origin = {}

        # ---- FFI ----
        self.extern_sigs = {}   # nombre -> (param_types: list[TypeAnn], ret: TypeAnn)
        self.extern_libs = set()  # nombres de librería para -l<lib> al linkear (from "...")
        # extern fn -> su librería (None si no declara `from`, como la libc), para
        # mandar cada llamada al worker aislado que le toca.
        self.extern_fn_library = {}
        # Librería -> sus extern fn en orden de aparición. Ese orden es el índice
        # del protocolo de pipe: tiene que ser el mismo que usa el worker
        # (ffi_worker.py). Una función sin `from` no tiene worker.
        self.extern_fns_by_library = {}
        # Librerías que corren en un worker aislado: todas salvo las declaradas
        # `en_proceso`. Se llena al final de _iniciar (hace falta haber visto
        # todas las extern fn).
        self.pipe_isolated_libs = set()
        self.en_proceso_libs = set()  # declaradas con `extern lib "x" en_proceso`
        # Lo llena compile_file() antes de generate(): librería -> ruta del binario
        # del worker, que generate() pega en scar_ffi_worker_start_all().
        self.ffi_worker_paths = {}
        # extern fn con retorno Result<T> que el programa llama: solo esas
        # necesitan su scar_extern_wrap_<nombre>.
        self.extern_result_wrap_needed = set()
        self.extern_types = {}  # nombre -> ExternTypeDecl (typedef void* Nombre;)

        # Primero los `extern type`, después los struct (cada grupo en el orden
        # del fuente) y después lo demás: el C declara todos los struct antes que
        # las fns, así que una fn puede recibir un struct declarado más abajo
        # Entre struct se respeta el orden: un campo struct va antes.
        def _orden_de_registro(it):
            if isinstance(it, ExternTypeDecl):
                return 0
            if isinstance(it, StructDecl):
                return 1
            return 2
        for item in sorted(program.items, key=_orden_de_registro):
            self._registrar_item(item)

        # Cada librería va al worker aislado salvo que se declare `extern lib
        # "x" en_proceso`. Si no se puede aislar (callback, struct por valor) y no
        # se declaró, el checker ya lo rechazó; esto es la red de seguridad.
        for lib, decls_ in self.extern_fns_by_library.items():
            if lib in self.en_proceso_libs:
                continue
            if not self._library_pipe_eligible(decls_):
                raise CodegenError(
                    f"la librería \"{lib}\" no puede correr aislada (recibe un callback "
                    f"o un struct por valor): declárala con extern lib \"{lib}\" en_proceso")
            self.pipe_isolated_libs.add(lib)
        # Índice de cada función dentro de su librería: el mismo que usa
        # ffi_worker.build_worker_source para el switch del worker.
        self.ffi_worker_index_of = {
            lib: {d.name: i for i, d in enumerate(decls_)}
            for lib, decls_ in self.extern_fns_by_library.items()
            if lib in self.pipe_isolated_libs
        }

    def _registrar_item(self, item):
        """Registra una declaración del programa: un struct (o su plantilla genérica),
        una librería o un tipo extern, una fn (o su plantilla genérica) o una
        extern fn."""
        _r = self._registrar_struct(item)
        if _r is not _SIGUE:
            return _r
        _r = self._registrar_extern_lib_tipo(item)
        if _r is not _SIGUE:
            return _r
        return self._registrar_fn(item)

    def _registrar_struct(self, item):
        """Un struct: su plantilla si es genérico, o sus campos (con el chequeo de
        tipos soportados) y, si viene de un enum, sus variantes."""
        if isinstance(item, StructDecl):
            if item.type_params:
                # Un campo cuyo tipo es un T (o lleva un T adentro, como Vec<T>) se
                # valida con _type_supported_generic_field: T recién es un tipo real en
                # cada instancia.
                fields = {}
                for f_name, f_ty in item.fields:
                    if not self._type_supported_generic_field(f_ty, item.type_params):
                        raise CodegenError(
                            f"struct genérico '{item.name}': el campo '{f_name}' "
                            f"tiene tipo {f_ty!r}, todavía no soportado por el "
                            "backend de C para structs genéricos."
                        )
                    fields[f_name] = f_ty
                self.generic_structs[item.name] = {
                    "type_params": list(item.type_params),
                    "fields": fields,
                }
                return
            fields = {}
            for f_name, f_ty in item.fields:
                f_ty = self._canon(f_ty)  # Tape<f64> -> Tape_f64
                if not self._type_supported(f_ty):
                    raise CodegenError(
                        f"struct '{item.name}': el campo '{f_name}' tiene tipo "
                        f"{f_ty!r}, todavía no soportado por el backend de C "
                        "(o es un struct que todavía no fue declarado más "
                        "arriba en el archivo — los struct deben declararse "
                        "en el orden en que se usan como campo)."
                    )
                fields[f_name] = f_ty
            self.structs[item.name] = fields
            if getattr(item, "enum_variantes", None):
                # Un enum, bajado a struct con tag (enum_match.py): el print muestra la
                # variante, como el intérprete.
                self.enums[item.name] = item.enum_variantes
            return
        return _SIGUE

    def _registrar_extern_lib_tipo(self, item):
        """Una librería declarada con `extern lib` o un `extern type` (un handle
        opaco)."""
        if isinstance(item, ExternLibDecl):
            # `extern lib "x" en_proceso`: sin worker aislado
            self.en_proceso_libs.add(item.library)
            return
        if isinstance(item, ExternTypeDecl):
            # el checker ya validó los choques de nombre; el backend solo lo registra
            # para c_type() y el typedef
            self.extern_types[item.name] = item
            return
        return _SIGUE

    def _registrar_fn(self, item):
        """Una fn (o su plantilla genérica) con su firma, o una extern fn con sus
        chequeos de frontera."""
        if isinstance(item, FnDecl):
            if item.type_params:
                # Fn genérica: los tipos con T se validan con
                # _type_supported_generic_field y la fn no entra en fn_sigs (cada
                # instancia sí, al generarse).
                raw_params = [p.type_ann or T_I32 for p in item.params]
                raw_ret = item.return_type or T_VOID
                for p_name, p_ty in zip((p.name for p in item.params), raw_params):
                    if not self._type_supported_generic_field(p_ty, item.type_params):
                        raise CodegenError(
                            f"fn genérica '{item.name}': el parámetro '{p_name}' "
                            f"tiene tipo {p_ty!r}, todavía no soportado por el "
                            "backend de C para funciones genéricas."
                        )
                if not self._type_supported_generic_field(raw_ret, item.type_params):
                    raise CodegenError(
                        f"fn genérica '{item.name}': el tipo de retorno "
                        f"{raw_ret!r} todavía no soportado por el backend de C "
                        "para funciones genéricas."
                    )
                if item.is_task:
                    # Task genérica: cada spawn con tipos concretos genera una instancia que
                    # es una task común.
                    self.has_tasks = True
                self.generic_fns[item.name] = {
                    "type_params": list(item.type_params),
                    "params": raw_params,
                    "ret": raw_ret,
                    "decl": item,
                    "is_task": bool(item.is_task),
                }
                return
            params = [self._canon(p.type_ann or T_I32) for p in item.params]
            ret = self._canon(item.return_type or T_VOID)
            for p_name, p_ty in zip((p.name for p in item.params), params):
                if not self._type_supported(p_ty):
                    raise CodegenError(
                        f"'{item.name}': el parámetro '{p_name}' tiene tipo "
                        f"{p_ty!r}, todavía no soportado por el backend de C."
                    )
            if not self._type_supported(ret):
                raise CodegenError(
                    f"'{item.name}': el tipo de retorno {ret!r} todavía no "
                    "soportado por el backend de C."
                )
            if item.is_task:
                self.task_sigs[item.name] = (params, ret)
                self.task_decls[item.name] = item
                self.has_tasks = True
            else:
                self.fn_sigs[item.name] = (params, ret)
        elif isinstance(item, ExternFnDecl):
            # El backend vuelve a validar la frontera FFI, que es más chica que lo
            # que soporta en general (FFI_SUPPORTED_TYPES, o un `extern type`).
            if item.abi != "C":
                raise CodegenError(
                    f"extern '{item.name}': ABI {item.abi!r} no soportada "
                    "por el backend de C, solo \"C\"."
                )
            params = []
            for p in item.params:
                ffi_ok = p.type_ann is not None and (ffi_tipo_ok(p.type_ann, self.structs, self.extern_types)
                                                     or self._es_vec_ffi(p.type_ann))
                if not ffi_ok:
                    raise CodegenError(
                        f"extern '{item.name}': el parámetro '{p.name}' tiene "
                        f"tipo {p.type_ann!r}, no soportado en la frontera FFI "
                        f"(soportados: {sorted(FFI_SUPPORTED_TYPES)}, o un tipo "
                        f"declarado con 'extern type')."
                    )
                params.append(p.type_ann)
            ret = item.return_type or T_VOID
            if ret.name == "Result":
                # Result<T> como retorno de una extern fn: un NULL de C se vuelve Err.
                # Solo vale si T es un puntero en C (str o un `extern type`): un
                # Result<i32> no tiene un valor que distinga el error de un 0 legítimo.
                inner = ret.args[0] if ret.args else None
                inner_ptr_ok = inner is not None and (
                    inner.name == "str"
                    or (inner.name in self.extern_types and not inner.args)
                )
                if not inner_ptr_ok:
                    raise CodegenError(
                        f"extern '{item.name}': Result<{inner!r}> no soportado "
                        f"por el backend de C -- el chequeo automático de NULL "
                        f"solo aplica a T representable como puntero "
                        f"('str' o un tipo declarado con 'extern type')."
                    )
            else:
                ret_ffi_ok = ret.name == "void" or ffi_tipo_ok(ret, self.structs, self.extern_types)
                if not ret_ffi_ok:
                    raise CodegenError(
                        f"extern '{item.name}': el tipo de retorno {ret!r} no "
                        f"soportado en la frontera FFI (soportados: "
                        f"{sorted(FFI_SUPPORTED_TYPES)}, un tipo declarado con "
                        f"'extern type', Result<T> de uno de esos tipos, o "
                        f"vacío para 'void')."
                    )
            self.extern_sigs[item.name] = (params, ret)
            self.extern_fn_library[item.name] = item.library
            if item.library:
                self.extern_libs.add(item.library)
                self.extern_fns_by_library.setdefault(item.library, []).append(item)
