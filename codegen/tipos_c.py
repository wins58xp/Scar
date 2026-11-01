"""Mixin TiposC de Codegen (paso C6): los tipos de SCAR en C. c_type, las
plantillas por tipo (Vec, Map, Chan, Option/Result, fn), los genéricos
monomorfizados y qué tipo soporta el backend.
"""

import copy

from parser import (
    FnDecl, LetStmt, ReturnStmt, ExprStmt, IfStmt, Ident, BinOp, UnaryOp, Call,
    PrintExpr, WhileStmt, WhileLetStmt, ForStmt, AssignStmt, FieldAccess, IndexExpr,
    StructLit, ArrayLit, TryExpr, OkExpr, ErrExpr, SomeExpr, SpawnExpr, MethodCall,
)
from types_ import TypeAnn, T_I32, T_STR

from . import runtime as runtime_c
from .comun import (
    _SIGUE,
    C_TYPE, CHAN_MARK, CodegenError, FILE_MARK, FN_MARK, GENERIC_NAMES, LISTENER_MARK,
    MAP_MARK, PIPE_MARK, SOCKET_MARK, TASK_MARK, VEC_MARK,
)


class TiposC:
    # ---- soporte de tipos ----
    def _canon(self, ty):
        """Tipo canónico: sustituye los T de la instancia actual (_tbind) y
        cambia todo struct genérico concreto por su monomorfización, a cualquier
        profundidad (Vec<Nodo<f64>> -> Vec<Nodo_f64>)."""
        if ty is None:
            return None
        b = self._tbind
        if b and not ty.args and ty.name in b:
            return b[ty.name]
        if ty.name in self.generic_structs:
            args = [self._canon(a) for a in (ty.args or [T_I32])]
            return TypeAnn(self._ensure_generic_struct_instance(ty.name, args))
        if ty.args:
            return TypeAnn(ty.name, [self._canon(a) for a in ty.args])
        return ty

    def _menciona_param(self, ty: TypeAnn, type_params) -> bool:
        if ty.name in type_params and not ty.args:
            return True
        return any(self._menciona_param(a, type_params) for a in ty.args)

    def _type_supported_generic_field(self, ty: TypeAnn, type_params) -> bool:
        """Como _type_supported, para el tipo de un campo o parámetro de un struct
        o fn genérico: acepta un T suelto o anidado en un contenedor (Vec<T>, el V
        de Map<K,T>, Option<T>...). El T recién es un tipo real en cada instancia
        (y ahí se valida de verdad), así que esto solo descarta combinaciones que
        el backend nunca podría generar. Un tipo sin ningún T va a
        _type_supported."""
        if ty.name in type_params and not ty.args:
            return True
        if (ty.name in GENERIC_NAMES or ty.name == FN_MARK) and any(
                self._menciona_param(a, type_params) for a in ty.args):
            # Option<T> / Result<T> / fn(T, T) -> bool: se valida al monomorfizar
            return all(self._type_supported_generic_field(a, type_params) for a in ty.args)
        if ty.name in self.generic_structs:
            # otro struct genérico (Nodo<T>) como campo o elemento
            return all(self._type_supported_generic_field(a, type_params) for a in ty.args)
        if ty.name == VEC_MARK:
            inner = ty.args[0] if ty.args else T_I32
            if inner.name in type_params and not inner.args:
                return True
            if inner.name in self.generic_structs or self._menciona_param(inner, type_params):
                # también anidado (Vec<Option<T>>, Vec<Vec<T>>, Vec<Map<str, T>>...)
                return self._type_supported_generic_field(inner, type_params)
            return self._type_supported(ty)
        if ty.name == MAP_MARK:
            key_ty = ty.args[0] if ty.args else T_I32
            val_ty = ty.args[1] if len(ty.args) > 1 else T_I32
            if key_ty.name in type_params:
                return False
            if val_ty.name in type_params and not val_ty.args:
                return key_ty.name in C_TYPE
            if self._menciona_param(val_ty, type_params):
                # Map<K, Vec<T>>, Map<K, Option<T>>...
                return key_ty.name in C_TYPE and self._type_supported_generic_field(val_ty, type_params)
            return self._type_supported(ty)
        if ty.name == CHAN_MARK and ty.args and self._menciona_param(ty.args[0], type_params):
            # Chan<T>, Chan<Vec<T>>... (se valida al monomorfizar)
            inner = ty.args[0]
            return (inner.name in type_params and not inner.args) or \
                self._type_supported_generic_field(inner, type_params)
        return self._type_supported(ty)

    def _type_supported(self, ty: TypeAnn) -> bool:
        if ty.name in C_TYPE or ty.name in self.structs:
            return True
        if ty.name in (FILE_MARK, SOCKET_MARK, LISTENER_MARK, PIPE_MARK):
            # File/Socket/Listener/Pipe como parámetro: un descriptor que la fn usa
            # prestado; pasarlo por valor no cambia quién lo cierra.
            return True
        if ty.name in GENERIC_NAMES:
            # El T de un Option/Result: lo mismo que acepta _generic_c_type, a
            # cualquier profundidad (Option<Result<Option<T>>>...).
            inner = ty.args[0] if ty.args else T_I32
            if inner.name in C_TYPE or inner.name in self.structs:
                return True
            if inner.name in (FILE_MARK, SOCKET_MARK, LISTENER_MARK, PIPE_MARK):
                # Option<Pipe>
                return True
            if inner.name in GENERIC_NAMES:
                return self._type_supported(inner)
            if inner.name == CHAN_MARK:
                # Option<Chan<T>>
                return self._type_supported(inner)
            if inner.name == FN_MARK:
                # Option<fn(..)>, lo que da get() sobre un Vec/Map de fns
                return self._type_supported(inner)
            if inner.name == TASK_MARK:
                # Option<Task<T, t>>: el handle apunta al contexto de la tarea, que es
                # de la región madre: el Option no es dueño de nada.
                return len(inner.args) >= 2
            if inner.name in (VEC_MARK, MAP_MARK):
                # Option<Vec<T>>, Result<Map<K,V>>...: el Vec/Map interno se valida con
                # las mismas reglas que uno suelto.
                return self._type_supported(inner)
            return False
        if ty.name == CHAN_MARK:
            # Chan<T>: T primitivo o struct de usuario
            inner = ty.args[0] if ty.args else T_I32
            if inner.name in (VEC_MARK, MAP_MARK, "Option", "Result", FN_MARK, CHAN_MARK):
                # Chan<Vec<T>>, Chan<Map<K,V>>, Option, Result, fn y Chan
                return self._type_supported(inner)
            if inner.name == PIPE_MARK:
                return True  # Chan<Pipe>
            return inner.name in C_TYPE or inner.name in self.structs
        if ty.name == VEC_MARK:
            # Vec<T>: T primitivo, str, struct de usuario o Chan (lo que acepte
            # _chan_c_type). Un Chan es una referencia compartida: el Vec no lo libera.
            inner = ty.args[0] if ty.args else T_I32
            return (
                inner.name in C_TYPE
                or inner.name in self.structs
                or (inner.name == CHAN_MARK and self._type_supported(inner))
                # un Vec de handles (File/Socket/Listener/Pipe)
                or inner.name in (FILE_MARK, SOCKET_MARK, LISTENER_MARK, PIPE_MARK)
                or (inner.name == FN_MARK and self._type_supported(inner))
                # Vec<Task<T, t>> (los handles de varias tareas)
                or (inner.name == TASK_MARK and len(inner.args) >= 2)
                # Vec<Vec<T>>, a cualquier profundidad
                or (inner.name == VEC_MARK and self._type_supported(inner))
                # Vec<Option<T>> y Vec<Map<K,V>>
                or (inner.name in ("Option", "Result", MAP_MARK) and self._type_supported(inner))
            )
        if ty.name == MAP_MARK:
            # Map<K,V>: K primitivo (hace falta un scar_hash_<K>), V primitivo,
            # struct de usuario o Chan.
            key_ty = ty.args[0] if ty.args else T_I32
            val_ty = ty.args[1] if len(ty.args) > 1 else T_I32
            val_ok = (
                val_ty.name in C_TYPE
                or val_ty.name in self.structs
                or (val_ty.name == CHAN_MARK and self._type_supported(val_ty))
                # Map<K, Vec<T>>, Map<K, Map<K2,V2>>, Map<K, Option<T>>, Map<K, fn(..)>,
                # Map<K, Pipe>
                or (val_ty.name in (VEC_MARK, MAP_MARK, "Option", "Result", FN_MARK) and self._type_supported(val_ty))
                or val_ty.name == PIPE_MARK
                or (val_ty.name == TASK_MARK and len(val_ty.args) >= 2)  # Map<K, Task<T, t>>
            )
            return key_ty.name in C_TYPE and val_ok
        if ty.name == FN_MARK:
            # fn(...) -> U: las mismas reglas que _fn_c_type, sin generar nada. No se
            # llama a _fn_c_type porque esto corre al recorrer las declaraciones, antes
            # de saber si hay tasks, y monomorfizar ahí emitía el panic equivocado.
            return all(t.name in C_TYPE or t.name in self.structs or self._type_supported(t)
                       for t in ty.args)
        # lo demás no tiene representación en C
        return False

    def c_type(self, ty: TypeAnn) -> str:
        """Tipo de C para un tipo de SCAR. Un struct de usuario es siempre
        puntero; Option/Result, siempre struct por valor (ver el docstring del
        módulo)."""
        if ty.name in C_TYPE:
            return C_TYPE[ty.name]
        if ty.name in self.generic_structs:
            # struct genérico: c_type() solo ve su instancia concreta ('Caja_i32'),
            # que es un puntero como cualquier struct
            concrete_args = ty.args if ty.args else [T_I32]
            mangled = self._ensure_generic_struct_instance(ty.name, concrete_args)
            return f"{mangled}*"
        if ty.name in self.structs:
            return f"{ty.name}*"
        if ty.name in self.extern_types:
            # `extern type Nombre`: `typedef void* Nombre;` en el preámbulo, así que
            # en C se llama igual que en SCAR
            return ty.name
        if ty.name in GENERIC_NAMES:
            return self._generic_c_type(ty)
        if ty.name == FN_MARK:
            return self._fn_c_type(ty)
        if ty.name == TASK_MARK:
            # TaskHandle no se monomorfiza: el tipo interno solo importa en .join(),
            # al castear el void* de vuelta
            return "TaskHandle"
        if ty.name == CHAN_MARK:
            return self._chan_c_type(ty)
        if ty.name == PIPE_MARK:
            return self._pipe_c_type()
        if ty.name == FILE_MARK:
            return self._file_c_type()
        if ty.name == SOCKET_MARK:
            return self._socket_c_type()
        if ty.name == LISTENER_MARK:
            return self._listener_c_type()
        if ty.name == VEC_MARK:
            return self._vec_c_type(ty)
        if ty.name == MAP_MARK:
            return self._map_c_type(ty)
        raise CodegenError(f"tipo no soportado por el backend de C: {ty!r}")

    def _mangled_name(self, ty: TypeAnn) -> str:
        """El fragmento de nombre de un tipo dentro del nombre de una
        monomorfización. Para un tipo simple es su nombre; para un tipo con
        argumentos baja recursivamente, así Option<Option<i32>> y
        Option<Option<f64>> no comparten nombre de C."""
        if ty.name in GENERIC_NAMES:
            inner = ty.args[0] if ty.args else T_I32
            return f"{ty.name}_{self._mangled_name(inner)}"
        if ty.name == CHAN_MARK:
            # Chan<T> se llama "Chan" sea cual sea su T: sin esto, Vec<Chan<i32>> y
            # Vec<Chan<f64>> tendrían el mismo nombre de C
            inner = ty.args[0] if ty.args else T_I32
            return f"{ty.name}_{self._mangled_name(inner)}"
        if ty.name == VEC_MARK:
            # lo mismo con Vec: Option<Vec<A>> y Option<Vec<B>> no pueden compartir
            # nombre
            inner = ty.args[0] if ty.args else T_I32
            return f"{ty.name}_{self._mangled_name(inner)}"
        if ty.name == MAP_MARK:
            # Map<K,V> -> "Map_<K>_<V>", el mismo sufijo que arma _map_c_type
            key_ty = ty.args[0] if ty.args else T_I32
            val_ty = ty.args[1] if len(ty.args) > 1 else T_I32
            return f"{ty.name}_{key_ty.name}_{self._mangled_name(val_ty)}"
        if ty.name == FN_MARK:
            # por su firma (Fn_i32_i32), como el typedef de _fn_c_type
            return self._fn_c_type(ty)
        if ty.name == TASK_MARK and len(ty.args) >= 2:
            # Task<T, t>: dos tareas distintas son dos tipos distintos (el checker no
            # mezcla Task<i32, a> con Task<i32, b>), así que el nombre lleva la tarea
            return f"Task_{ty.args[1].name}"
        return ty.name

    def _generic_c_type(self, ty: TypeAnn) -> str:
        inner = ty.args[0] if ty.args else T_I32
        # El T de un Option/Result puede ser: primitivo, str, File/Socket/
        # Listener, un `extern type`, un struct de usuario, otro Option/Result
        # (a cualquier profundidad), Chan, Vec o Map. Todos se guardan por valor en
        # el campo `value`; el typedef interno se genera antes que el externo
        # (c_type(inner) lo agrega a generic_defs primero).
        _SIMPLE_MARKS = (FILE_MARK, SOCKET_MARK, LISTENER_MARK, PIPE_MARK)
        # Con Chan<U> adentro, el Option no libera nada (un Chan es una
        # referencia compartida). Con Vec/Map, struct o str adentro, ver
        # {c_name}_free más abajo.
        if (
            inner.name not in C_TYPE
            and inner.name not in _SIMPLE_MARKS
            and inner.name not in self.structs
            and inner.name not in GENERIC_NAMES
            and inner.name not in self.extern_types
            and inner.name != CHAN_MARK
            and inner.name != VEC_MARK
            and inner.name != MAP_MARK
            and inner.name != FN_MARK  # Option<fn(..)> (el get de un Vec/Map de fns)
            and inner.name != TASK_MARK  # Option<Task<T, t>> (una tarea lanzada más tarde)
        ):
            raise CodegenError(
                f"{ty!r}: el backend de C solo soporta {ty.name}<T> con T "
                f"primitivo (i32/i64/f64/str/bool), File, Socket, Listener, "
                f"struct de usuario, Chan<U>, Vec<U>, Map<K,V>, un tipo "
                f"declarado con 'extern type', u otro Option/Result, se dio {inner!r}"
            )
        # La clave es el TypeAnn interno completo, no solo su nombre:
        # Option<Option<i32>> y Option<Option<f64>> tienen el mismo inner.name.
        key = (ty.name, inner)
        if key in self.generic_types:
            return self.generic_types[key]
        c_name = f"{ty.name}_{self._mangled_name(inner)}"
        self.generic_types[key] = c_name
        # Result<()>: C no deja declarar un campo `void`, así que `value` es un
        # bool que nadie lee (inject_chan() devuelve Result<()>).
        if ty.name == "Result" and inner.name == "void":
            inner_c = "bool"
        else:
            inner_c = (
                self.c_type(inner)
                if inner.name in _SIMPLE_MARKS or inner.name in self.structs
                or inner.name in GENERIC_NAMES or inner.name in self.extern_types
                or inner.name == CHAN_MARK
                # Vec/Map: c_type() despacha a _vec_c_type/_map_c_type
                or inner.name == VEC_MARK or inner.name == MAP_MARK
                or inner.name == FN_MARK or inner.name == TASK_MARK
                else C_TYPE[inner.name]
            )
        # _None()/_Err() inicializan `value` con un compound literal
        # `({inner_c}){0}`: cero para cualquier tipo de C (escalar, puntero o un
        # struct por valor como un Option anidado, que queda con tag = 0, igual
        # que su _None()).
        zero_value = f"({inner_c}){{0}}"
        if ty.name == "Result":
            self.generic_defs.append(
                f"typedef struct {{\n"
                f"    int tag;\n"
                f"    {inner_c} value;\n"
                f"    const char* err;\n"
                f"}} {c_name};"
            )
            self.generic_defs.append(
                f"static {c_name} {c_name}_Ok({inner_c} value) {{\n"
                f"    {c_name} r; r.tag = 1; r.value = value; r.err = NULL; return r;\n"
                f"}}"
            )
            self.generic_defs.append(
                f"static {c_name} {c_name}_Err(const char* err) {{\n"
                f"    {c_name} r; r.tag = 0; r.value = {zero_value}; r.err = err; return r;\n"
                f"}}"
            )
        else:  # Option
            self.generic_defs.append(
                f"typedef struct {{\n"
                f"    int tag;\n"
                f"    {inner_c} value;\n"
                f"}} {c_name};"
            )
            self.generic_defs.append(
                f"static {c_name} {c_name}_Some({inner_c} value) {{\n"
                f"    {c_name} o; o.tag = 1; o.value = value; return o;\n"
                f"}}"
            )
            self.generic_defs.append(
                f"static {c_name} {c_name}_None(void) {{\n"
                f"    {c_name} o; o.tag = 0; o.value = {zero_value}; return o;\n"
                f"}}"
            )
            # {c_name}_free: libera el contenido si el Option/Result es su dueño
            # (tag == 1). Se emite siempre que T tenga algo que liberar, aunque nada
            # lo llame. {T}_free ya tiene su prototipo antes (struct_free_fwd_decls).
            if inner.name in self.structs:
                # {T}_free sabe si el bloque salió de la arena o de malloc
                self.generic_defs.append(
                    f"static void {c_name}_free({c_name} v) {{\n"
                    f"    if (v.tag == 1) {{\n"
                    f"        {inner.name}_free(v.value);\n"
                    f"    }}\n"
                    f"}}"
                )
            elif inner.name in (VEC_MARK, MAP_MARK):
                # Vec/Map: su contenido es siempre malloc (nunca de la arena)
                if inner.name == VEC_MARK:
                    elem = inner.args[0] if inner.args else T_I32
                    free_call = f"scar_vec_free_{self._mangled_name(elem)}(v.value)"
                else:
                    k_ty = inner.args[0] if inner.args else T_I32
                    v_ty = inner.args[1] if len(inner.args) > 1 else T_I32
                    free_call = f"scar_map_free_{k_ty.name}_{self._mangled_name(v_ty)}(v.value)"
                self.generic_defs.append(
                    f"static void {c_name}_free({c_name} v) {{\n"
                    f"    if (v.tag == 1) {{\n"
                    f"        {free_call};\n"
                    f"    }}\n"
                    f"}}"
                )
            elif inner.name == "str":
                # str: un str dentro de un Option dueño es siempre propio (scar_free).
                # Por eso esta función exige el alocador aunque nada más lo use.
                self.needs_option_str_free = True
                self.generic_defs.append(
                    f"static void {c_name}_free({c_name} v) {{\n"
                    f"    if (v.tag == 1) {{\n"
                    f"        scar_free((char*)v.value);\n"
                    f"    }}\n"
                    f"}}"
                )
        return c_name

    def _fn_c_type(self, ty: TypeAnn) -> str:
        """fn(T1, T2) -> U -> un typedef de puntero a función de C, uno por firma
        (self.fn_types). Se devuelve un nombre de tipo simple, nunca la sintaxis
        de C (`int32_t (*f)(int32_t)`, con el nombre de la variable en el medio),
        así el resto del backend sigue usando `f"{self.c_type(t)} {name}"`."""
        param_tys, ret_ty = ty.args[:-1], ty.args[-1]
        # Primitivos, str, structs (prestados), Vec/Map/Option/Result/Chan en la
        # firma y un struct de retorno: por el contrato del tipo fn
        # (type_checker._chequear_contrato_fn_valor) una llamada a través de él es
        # como cualquier otra: un Vec/Map que recibe es suyo y lo que devuelve es
        # nuevo.
        for t in ty.args:
            if t.name in C_TYPE or t.name in self.structs:
                continue
            if not self._type_supported(t):
                raise CodegenError(
                    f"{ty!r}: el backend de C no soporta {t!r} en la firma de una "
                    f"función usada como valor"
                )
        key = tuple(ty.args)
        if key in self.fn_types:
            return self.fn_types[key]
        # nombre legible y único: 'Fn_i32_i32' para 'fn(i32) -> i32',
        # 'Fn_str_bool_void' para 'fn(str, bool)'
        c_name = "Fn_" + "_".join(self._mangled_name(t) for t in ty.args)
        self.fn_types[key] = c_name
        param_c = ", ".join(C_TYPE[t.name] if t.name in C_TYPE else self.c_type(t)
                            for t in param_tys) if param_tys else "void"
        ret_c = C_TYPE[ret_ty.name] if ret_ty.name in C_TYPE else self.c_type(ret_ty)
        # Con un Vec/Map/Option... en la firma, su typedef va después de
        # fn_typedefs: este typedef va en generic_defs, detrás de ellos.
        tardio = self._fn_tardio(ty)
        destino = self.generic_defs if tardio else self.fn_typedefs
        for t in ty.args:
            if t.name in self.structs:
                # el typedef de los structs va después; C11 deja repetirlo
                destino.append(f"typedef struct {t.name} {t.name};")
        destino.append(f"typedef {ret_c} (*{c_name})({param_c});")
        return c_name

    def _chan_c_type(self, ty: TypeAnn) -> str:
        """Chan<T> -> puntero a una cola enlazada con mutex, monomorfizada por T.
        Un canal es una referencia compartida (como ScarChan en el intérprete):
        chan_new() reserva una vez, y pasar el Chan a una task copia el puntero,
        no la cola. Su vida la lleva un contador de referencias atómico.

        send() mueve el valor al nodo de la cola (el checker ya lo da por movido),
        y recv() se lo entrega al receptor, que queda como su dueño. Un struct
        viaja por valor dentro del nodo, y lo que tenga en la arena del emisor
        pasa a malloc: el nodo cruza de tarea y esa arena puede liberarse antes
        de que el receptor lo lea."""
        (inner, inner_is_struct, inner_is_cont, inner_es_valor, suf,
         key) = self._chan_elemento(
            ty)
        _r = self._chan_ya_generado(key)
        if _r is not _SIGUE:
            return _r
        c_name, inner_c, cont_free, node_name, impl_name, opt_c_name = self._chan_nodo(
            inner, inner_is_struct, inner_is_cont, inner_es_valor, suf, key)
        (cancel_line, send_cancel_line, send_wait_block,
         recv_wait_block) = self._chan_esperas(
            inner, inner_is_struct, inner_is_cont, inner_es_valor, suf, cont_free)
        return self._chan_armado(
            inner, inner_is_struct, inner_is_cont, inner_es_valor, suf, c_name, inner_c,
            cont_free, node_name, impl_name, opt_c_name, cancel_line, send_cancel_line,
            send_wait_block, recv_wait_block)

    def _chan_elemento(self, ty):
        """El tipo del elemento (struct, contenedor, valor), su sufijo y los
        chequeos de lo que el backend soporta."""
        inner = ty.args[0] if ty.args else T_I32
        inner_is_struct = inner.name in self.structs
        # Chan<Vec<T>>/Chan<Map<K,V>>: el handle viaja por valor en el nodo, send()
        # lo mueve (sacando de la arena del emisor los structs que contenga) y
        # recv() lo entrega entero.
        inner_is_cont = inner.name in (VEC_MARK, MAP_MARK) and self._type_supported(inner)
        # Option/Result, fn, Pipe y otro Chan también viajan por valor en el nodo.
        # Si el canal se libera con mensajes sin leer, un Option/Result con dueño
        # se suelta (_lineas_liberar_dueno) y un Chan descuenta su referencia.
        inner_es_valor = (inner.name in ("Option", "Result", FN_MARK, CHAN_MARK) and self._type_supported(inner)) \
            or inner.name == PIPE_MARK
        if inner_es_valor:
            inner_is_cont = True
        suf = self._mangled_name(inner)
        if inner.name not in C_TYPE and not inner_is_struct and not inner_is_cont:
            raise CodegenError(
                f"{ty!r}: el backend de C solo soporta Chan<T> con T primitivo "
                f"(i32/i64/f64/str/bool), struct de usuario, Vec, Map, Option, Result o "
                f"una fn, se dio {inner!r}"
            )
        if inner_is_struct and not self.has_tasks:
            # Chan<Struct> sin ninguna task en el programa no tiene con quién
            # comunicarse: se rechaza.
            raise CodegenError(
                f"{ty!r}: Chan<{suf}> requiere que el programa tenga "
                f"al menos una 'task' (un Chan<T> sin ninguna task no "
                f"tiene con quién comunicarse del otro lado -- ver "
                f"_chan_c_type)"
            )
        self.uses_chan = True
        key = (CHAN_MARK, suf)
        return inner, inner_is_struct, inner_is_cont, inner_es_valor, suf, key

    def _chan_ya_generado(self, key):
        """Si el Chan de este tipo ya se generó, su nombre."""
        if key in self.chan_types:
            return self.chan_types[key]
        return _SIGUE

    def _chan_nodo(self, inner, inner_is_struct, inner_is_cont, inner_es_valor, suf, key):
        """El nombre del Chan, el tipo de su valor, el nodo de la cola y su
        liberación (para un elemento struct o contenedor, las funciones de
        apoyo)."""
        # (C8) se asignan solo en algunas ramas y la pasada las devuelve siempre
        cont_free = None
        c_name = f"Chan_{suf}"
        self.chan_types[key] = c_name
        inner_c = self.c_type(inner) if (inner_is_struct or inner_is_cont) else C_TYPE[inner.name]
        # Con T struct, el nodo guarda el struct por valor y como primer miembro:
        # &node->value == (void*)node (C11 6.7.2.1p15). recv() devuelve el nodo
        # como el struct, y el {Struct}_free del receptor libera el bloque entero.
        # Un malloc por mensaje en vez de dos.
        node_value_c = suf if inner_is_struct else inner_c
        if inner_es_valor:
            cont_free = None
        elif inner_is_cont:
            if inner.name == VEC_MARK:
                cont_free = f"scar_vec_free_{self._mangled_name(inner.args[0] if inner.args else T_I32)}"
            else:
                k_t = inner.args[0] if inner.args else T_I32
                v_t = inner.args[1] if len(inner.args) > 1 else T_I32
                cont_free = f"scar_map_free_{k_t.name}_{self._mangled_name(v_t)}"
        node_name = f"ScarChanNode_{suf}"
        impl_name = f"ScarChanImpl_{suf}"
        # recv() devuelve Option<T>: Option_<T> tiene que existir antes
        opt_c_name = self._generic_c_type(TypeAnn("Option", [inner]))
        # Chan<Struct>: el struct opaco y su typedef de puntero van temprano, en
        # chan_typedefs (un puntero a un tipo incompleto no necesita su tamaño), y
        # la definición completa, en chan_struct_defs, después de struct_typedefs:
        # Option<Chan<Struct>> y Map<K, Chan<Struct>> necesitan el typedef antes.
        if inner_is_struct or inner_is_cont:
            # Prototipos tempranos de incref/decref: los usan funciones de Vec/Map que
            # se emiten antes de struct_typedefs, y sin prototipo gcc los declararía
            # implícitos y chocarían con la definición.
            self.chan_typedefs.append(
                f"struct {impl_name};\n"
                f"typedef struct {impl_name} {impl_name};\n"
                f"typedef {impl_name}* {c_name};\n"
                f"static void scar_chan_incref_{suf}({c_name} c);\n"
                f"static void scar_chan_decref_{suf}({c_name} c);"
            )
            self.chan_struct_defs.append(
                f"typedef struct {node_name} {{\n"
                f"    {node_value_c} value;\n"
                f"    struct {node_name} *next;\n"
                f"}} {node_name};\n"
                f"\n"
                f"struct {impl_name} {{\n"
                f"    {node_name} *head;\n"
                f"    {node_name} *tail;\n"
                f"    int closed;\n"
                f"    pthread_mutex_t mu;\n"
                # Dos condvars, una por dirección: recv() espera en not_empty y send(), en
                # un canal acotado, en not_full. Así el camino normal usa
                # pthread_cond_signal() y despierta a un solo hilo; close() usa broadcast()
                # en las dos. Con una sola condvar despertaban todos los workers por cada
                # mensaje (medido: +36% de ciclos).
                f"    pthread_cond_t not_empty;\n"
                f"    pthread_cond_t not_full;\n"
                f"    _Atomic int refcount;\n"
                f"    int32_t cap;\n"
                f"    int32_t count;\n"
                f"}};"
            )
        else:
            # T primitivo o str: el bloque entero (typedef y funciones) va junto a
            # chan_typedefs
            self.chan_typedefs.append(
                f"typedef struct {node_name} {{\n"
                f"    {node_value_c} value;\n"
                f"    struct {node_name} *next;\n"
                f"}} {node_name};\n"
                f"\n"
                f"typedef struct {{\n"
                f"    {node_name} *head;\n"
                f"    {node_name} *tail;\n"
                f"    int closed;\n"
                f"    pthread_mutex_t mu;\n"
                # Contador de referencias atómico: incref ocurre en el hilo que hace
                # spawn, pero decref puede ocurrir en varios hilos que terminan a la vez.
                # No usa `mu`, que protege la cola, un dato distinto de la vida del canal.
                f"    _Atomic int refcount;\n"
                # cap (0 = sin límite) y count (nodos encolados): se tocan siempre bajo
                # `mu`, como la cola.
                f"    int32_t cap;\n"
                f"    int32_t count;\n"
                # dos condvars, ver la rama de struct de arriba
                f"    pthread_cond_t not_empty;\n"
                f"    pthread_cond_t not_full;\n"
                f"}} {impl_name};\n"
                f"\n"
                f"typedef {impl_name}* {c_name};"
            )
        return c_name, inner_c, cont_free, node_name, impl_name, opt_c_name

    def _chan_esperas(self, inner, inner_is_struct, inner_is_cont, inner_es_valor, suf,
                      cont_free):
        """Las esperas de send y recv, con el chequeo de cancelación de la task, y
        cómo se suelta un nodo."""
        # el chequeo de cancelación solo existe si el programa tiene tasks
        cancel_line = "        scar_cancel_check();\n" if self.has_tasks else ""
        # send() reserva el nodo antes de esperar lugar, así que si lo cancelan
        # mientras espera tiene que soltarlo antes de desenrollar:
        # scar_cancel_check() salta sin pasar por ninguna limpieza. Se suelta como
        # en scar_chan_free_*: {T}_free para un struct (que lleva el encabezado de
        # B12 y los campos movidos), el str copiado y el nodo para str,
        # free(node) para el resto.
        node_drop = (
            f"{suf}_free(({suf}*)node);" if inner_is_struct
            else ("".join(l.strip() + " " for l in self._lineas_liberar_dueno(inner, "node->value", ""))
                  + "free(node);") if inner_es_valor
            else f"{cont_free}(node->value); free(node);" if inner_is_cont
            else "scar_free((char*)node->value); free(node);" if inner.name == "str"
            else "free(node);"
        )
        send_cancel_line = (
            "        if (__scar_ctx && atomic_load(&__scar_ctx->cancelled)) { " + node_drop + " scar_cancel_unwind(); }\n"
            if self.has_tasks else ""
        )
        # Espera sin timeout (pthread_cond_wait). Quien cancela a esta tarea la
        # despierta a propósito (scar_cancel_notify), así que antes de dormir el
        # hilo se registra en su ctx->wait_mu/wait_cond, todavía bajo c->mu, y se
        # vuelve a mirar `cancelled`: una cancelación puesta entre el chequeo del
        # principio del bucle y el wait se perdería, nadie volvería a señalizar.
        # Solo con tasks: sin ellas no hay TaskContext.
        send_wait_block = (
            "            if (__scar_ctx && atomic_load(&__scar_ctx->cancelled)) {\n"
            "                pthread_mutex_unlock(&c->mu);\n"
            "                " + node_drop + "\n"
            "                scar_cancel_unwind();\n"
            "            }\n"
            "            if (__scar_ctx) {\n"
            "                pthread_mutex_lock(&__scar_ctx->wait_lock);\n"
            "                __scar_ctx->wait_mu = &c->mu;\n"
            "                __scar_ctx->wait_cond = &c->not_full;\n"
            "                pthread_mutex_unlock(&__scar_ctx->wait_lock);\n"
            "            }\n"
            "            int __scar_trabado = scar_esperar_cond(&c->not_full, &c->mu, &__scar_espera);\n"
            "            if (__scar_ctx) {\n"
            "                pthread_mutex_lock(&__scar_ctx->wait_lock);\n"
            "                __scar_ctx->wait_mu = NULL;\n"
            "                __scar_ctx->wait_cond = NULL;\n"
            "                pthread_mutex_unlock(&__scar_ctx->wait_lock);\n"
            "            }\n"
            "            if (__scar_trabado) {\n"
            "                pthread_mutex_unlock(&c->mu);\n"
            "                " + node_drop + "\n"
            "                scar_panic(\"%s\", SCAR_DEADLOCK_MSG);\n"
            "            }\n"
            if self.has_tasks else
            # sin tasks nadie más puede vaciar el canal: esperar sería colgarse
            # para siempre
            "            pthread_mutex_unlock(&c->mu);\n"
            "            " + node_drop + "\n"
            "            scar_panic_main(\"%s\", SCAR_DEADLOCK_MSG);\n"
        )
        recv_wait_block = (
            "        if (__scar_ctx && atomic_load(&__scar_ctx->cancelled)) {\n"
            "            pthread_mutex_unlock(&c->mu);\n"
            "            scar_cancel_unwind();\n"
            "        }\n"
            "        if (__scar_ctx) {\n"
            "            pthread_mutex_lock(&__scar_ctx->wait_lock);\n"
            "            __scar_ctx->wait_mu = &c->mu;\n"
            "            __scar_ctx->wait_cond = &c->not_empty;\n"
            "            pthread_mutex_unlock(&__scar_ctx->wait_lock);\n"
            "        }\n"
            "        int __scar_trabado = scar_esperar_cond(&c->not_empty, &c->mu, &__scar_espera);\n"
            "        if (__scar_ctx) {\n"
            "            pthread_mutex_lock(&__scar_ctx->wait_lock);\n"
            "            __scar_ctx->wait_mu = NULL;\n"
            "            __scar_ctx->wait_cond = NULL;\n"
            "            pthread_mutex_unlock(&__scar_ctx->wait_lock);\n"
            "        }\n"
            "        if (__scar_trabado) {\n"
            "            pthread_mutex_unlock(&c->mu);\n"
            "            scar_panic(\"%s\", SCAR_DEADLOCK_MSG);\n"
            "        }\n"
            if self.has_tasks else
            "        pthread_mutex_unlock(&c->mu);\n"
            "        scar_panic_main(\"%s\", SCAR_DEADLOCK_MSG);\n"
        )
        return cancel_line, send_cancel_line, send_wait_block, recv_wait_block

    def _chan_armado(self, inner, inner_is_struct, inner_is_cont, inner_es_valor, suf,
                     c_name, inner_c, cont_free, node_name, impl_name, opt_c_name,
                     cancel_line, send_cancel_line, send_wait_block, recv_wait_block):
        """Cómo entra un valor al nodo, y el texto de C de todas las funciones del
        Chan (por pieza)."""
        # Un str se copia al encolarlo (scar_str_concat(value, "")): el receptor
        # es siempre dueño único de un texto propio, venga de un literal o del heap.
        if inner.name == "str":
            self.needs_str_concat = True
        # Struct: ver la rama de abajo
        node_value_stmt = (
            # send() mueve el struct al nodo: lo anidado que estaba en la arena del
            # emisor pasa a malloc, y el bloque del original se suelta (no-op si era de
            # la arena). Copiarlo compartía los Vec/Map con el emisor.
            f"    node->value = *value;\n"
            f"    {suf}_detach_fields(&node->value);\n"
            f"    scar_blk_release(value);\n" if inner_is_struct
            else ("    node->value = value;\n"
                  + "".join(l + "\n" for l in self._detach_lines(inner, "node->value", "    ")))
            if inner_is_cont
            else '    node->value = scar_str_concat(value, "");\n' if inner.name == "str"
            else "    node->value = value;\n"
        )
        # Las funciones de Chan<T> (new/send/recv...). T struct va con su typedef
        # en chan_struct_defs; T primitivo/str, a chan_defs. Option_<T> ya tiene que
        # existir.
        _chan_target = self.chan_struct_defs if (inner_is_struct or inner_is_cont) else self.chan_defs
        _chan_target.append(
            self._chan_c_new_send(c_name, suf, impl_name, send_cancel_line, inner_c,
                                  node_name, inner_is_struct, node_value_stmt,
                                  send_wait_block)
            + self._chan_c_close_recv(suf, c_name, recv_wait_block, opt_c_name,
                                      cancel_line, node_name, inner_is_struct, inner_c)
            + self._chan_c_try_recv(opt_c_name, c_name, suf, node_name, inner_is_struct,
                                    inner_c)
            + f"static void scar_chan_free_{suf}({c_name} c) {{\n"
            f"    {node_name} *node = c->head;\n"
            f"    while (node) {{\n"
            f"        {node_name} *next = node->next;\n"
            + (
                # Struct: {T}_free libera los campos y el bloque, que es el nodo entero
                # (value es su primer miembro). Un free(node) aparte sería un double free.
                f"        {suf}_free(({suf}*)node);\n"
                if inner_is_struct else
                "".join(l + "\n" for l in self._lineas_liberar_dueno(inner, "node->value", "        "))
                + f"        free(node);\n"
                if inner_es_valor else
                f"        {cont_free}(node->value);\n"
                f"        free(node);\n"
                if inner_is_cont else
                f"        scar_free((char*)node->value);\n"
                f"        free(node);\n"
                if inner.name == "str" else
                f"        free(node);\n"
            )
            + f"        node = next;\n"
            f"    }}\n"
            f"    pthread_mutex_destroy(&c->mu);\n"
            f"    pthread_cond_destroy(&c->not_empty);\n"
            f"    pthread_cond_destroy(&c->not_full);\n"
            f"    free(c);\n"
            f"}}\n"
            f"\n"
            # scar_chan_new deja refcount = 1 (el `let` que lo crea). Cada copia del
            # puntero (cada argumento Chan<T> de un spawn) suma uno antes de que la
            # task arranque, siempre desde el hilo padre.
            + self._chan_c_refs(suf, c_name)
        )
        return c_name

    def _vec_c_type(self, ty: TypeAnn) -> str:
        """Vec<T> -> struct por valor {data, len, cap} (16 bytes), monomorfizado por
        T. Vive donde viva su dueño (stack, campo de struct, argumentos de una
        task): sin bloque de control en el heap (medido: ~15% más rápido que con
        un puntero opaco). vec_new() no reserva nada ({NULL, 0, 0});
        vec_new(cap) reserva cap de entrada, como reserve() de C++.

        Las funciones que mutan (push, pop, set, grow) reciben `Vec_<T>*`; las de
        solo lectura (get, len) y free, el struct por valor. Sin mutex: un Vec no
        se comparte entre tareas (el checker lo mueve)."""
        inner = ty.args[0] if ty.args else T_I32
        inner_is_struct = inner.name in self.structs
        # Chan<T>: un handle compartido (con refcount), guardado por copia
        inner_is_chan = inner.name == CHAN_MARK
        if inner_is_chan:
            self._chan_c_type(inner)  # fuerza la monomorfización de Chan_<U>
        # File/Socket/Listener (un número de la tabla de handles), una fn
        # o un Pipe: valores sin nada que liberar; el Vec no los cierra.
        inner_is_handle = inner.name in (FILE_MARK, SOCKET_MARK, LISTENER_MARK, PIPE_MARK, FN_MARK)
        # Task<T, t>: el handle apunta al contexto de la tarea, que libera la
        # región madre (con o sin join)
        if inner.name == TASK_MARK and len(inner.args) >= 2:
            inner_is_handle = True
        # Vec<Vec<T>>: el de adentro va por valor en el arreglo y el de afuera es
        # su dueño (free lo libera, get() lo clona, pop()/replace() lo entregan,
        # set() libera el viejo). c_type(inner) genera el de adentro primero.
        inner_is_vec = inner.name == VEC_MARK
        # Vec<Option<T>>: el Option va por valor, como un campo de struct. Si lo
        # de adentro tiene dueño, el Vec es su dueño: get() lo copia, set() libera
        # el viejo y free los libera.
        inner_is_opt = inner.name in ("Option", "Result")  # también Result
        if inner_is_opt and not self._type_supported(inner):
            raise CodegenError(f"{ty!r}: el backend de C no soporta {inner!r} adentro de un Vec")
        opt_con_dueno = inner_is_opt and self._campo_compuesto_con_dueno(inner)
        # Vec<Map<K,V>>: un Map es un puntero a su tabla; el Vec es su dueño (set
        # libera el viejo, get lo clona, free los libera).
        inner_is_map = inner.name == MAP_MARK
        if inner_is_map and not self._type_supported(inner):
            raise CodegenError(f"{ty!r}: el backend de C no soporta {inner!r} adentro de un Vec")
        if (inner.name not in C_TYPE and not inner_is_struct and not inner_is_chan and not inner_is_handle
                and not inner_is_vec and not inner_is_opt and not inner_is_map):
            raise CodegenError(
                f"{ty!r}: el backend de C solo soporta Vec<T> con T primitivo "
                f"(i32/i64/f64/str/bool), struct de usuario, Vec<U>, Map<K,V>, Option<U>, Chan<U> o "
                f"File/Socket/Listener, se dio {inner!r}"
            )
        # _mangled_name y no inner.name: Chan<i32> y Chan<f64> tendrían el mismo
        # nombre de C
        name_part = self._mangled_name(inner)
        key = (VEC_MARK, name_part)
        if key in self.vec_types:
            return self.vec_types[key]
        c_name = f"Vec_{name_part}"
        self.vec_types[key] = c_name
        # Con T struct, el arreglo guarda los structs por valor (inner_c sin '*').
        # Con T Chan<U>, el puntero del handle.
        inner_c = (
            inner.name if inner_is_struct
            else self.c_type(inner) if inner_is_chan or inner_is_handle or inner_is_vec or inner_is_opt or inner_is_map
            else C_TYPE[inner.name]
        )
        inner_vec_part = self._mangled_name(inner.args[0] if inner.args else T_I32) if inner_is_vec else None
        # get()/pop() devuelven Option<T>, que tiene que existir antes. Con T
        # struct, el Option guarda un puntero ({Struct}*), no el struct por valor
        # del arreglo.
        opt_c_name = self._generic_c_type(TypeAnn("Option", [inner]))
        # El typedef va a vec_typedefs (o a generic_defs si el Vec lleva un
        # Option adentro, a cualquier profundidad). Las funciones de Vec<Struct>
        # van a vec_struct_defs: hacen sizeof del struct, que tiene que estar
        # completo.
        _tras_genericos = self._vec_con_option(inner)
        (self.generic_defs if _tras_genericos else self.vec_typedefs).append(
            f"typedef struct {{\n"
            f"    {inner_c} *data;\n"
            f"    int32_t len;\n"
            f"    int32_t cap;\n"
            f"}} {c_name};"
        )
        # Prototipo de free: {Struct}_free (un campo Vec<Struct>) y
        # Option_Vec_<T>_free lo llaman antes de la definición.
        (self.generic_defs if _tras_genericos else self.vec_struct_free_fwd_decls).append(
            f"static void scar_vec_free_{name_part}({c_name} v);"
        )
        _vec_target = self.vec_struct_defs if (inner_is_struct or self._vec_con_struct(inner)) else self.vec_defs
        _vec_target.append(
            self._vec_c_new_grow(c_name, name_part, inner_c)
            + self._vec_c_push(name_part, c_name, inner_c, inner, inner_is_struct,
                               inner_is_chan, inner_vec_part, inner_is_vec, opt_con_dueno,
                               inner_is_map)
            + self._vec_c_get_pop(opt_c_name, c_name, name_part, inner, inner_is_struct,
                                  inner_is_vec, opt_con_dueno, inner_is_map)
            + self._vec_c_len_resto(name_part, c_name, inner, inner_is_struct,
                                    inner_is_chan, inner_vec_part, inner_is_vec,
                                    opt_con_dueno, inner_is_map)
        )
        return c_name

    def _envoltorio_fn_valor(self, nombre) -> str:
        """El nombre de C de la fn `nombre` usada como valor. El contrato del tipo
        fn(...) dice que lo que devuelve es nuevo; si el retorno tiene dueño y
        fresh_owned no puede asegurarlo, se usa un envoltorio que devuelve una
        copia (en el peor caso, una pérdida acotada; nunca que quien llama libere
        algo que no es suyo)."""
        params, ret = self.fn_sigs[nombre]
        if (ret is None or ret.name == "str" or not self._necesita_clonar(ret)
                or self._ret_con_contrato(ret) or self.fresh_owned_fns.get(nombre, False)):
            return nombre
        if nombre in self._envoltorios_fn:
            return self._envoltorios_fn[nombre][0]
        envoltorio = f"scar_fnv_{nombre}"
        c_params = [C_TYPE[t.name] if t.name in C_TYPE else self.c_type(t) for t in params]
        firma = ", ".join(f"{c} __a{i}" for i, c in enumerate(c_params)) or "void"
        args = ", ".join(f"__a{i}" for i in range(len(c_params)))
        c_ret = self.c_type(ret)
        cuerpo = (f"static {c_ret} {envoltorio}({firma}) {{\n"
                  f"    {c_ret} __r = {nombre}({args});\n"
                  f"    return {self._clone_value_expr(ret, '__r')};\n"
                  f"}}")
        self._envoltorios_fn[nombre] = (envoltorio, cuerpo, f"static {c_ret} {envoltorio}({firma});")
        return envoltorio

    def _fn_tardio(self, ty) -> bool:
        """Una fn(...) con algo en la firma que no es primitivo ni struct (un Vec,
        Map, Option...): su typedef va en generic_defs."""
        return ty.name == FN_MARK and any(
            t.name not in C_TYPE and t.name not in self.structs for t in ty.args)

    def _map_tras_genericos(self, val_ty) -> bool:
        """El typedef de un Map con valor `val_ty` va en generic_defs (después de
        los Option) si el valor es un Option, o un Vec/Map cuyo typedef también
        fue ahí."""
        if val_ty.name in ("Option", "Result") or self._fn_tardio(val_ty):
            return True
        if val_ty.name == VEC_MARK:
            return self._vec_con_option(val_ty.args[0] if val_ty.args else T_I32)
        if val_ty.name == MAP_MARK:
            return self._map_tras_genericos(val_ty.args[1] if len(val_ty.args) > 1 else T_I32)
        return False

    def _vec_con_option(self, ty) -> bool:
        """Vec<Option<..>>, Vec<Vec<Option<..>>>...: el elemento (o el de un Vec de
        adentro) es un Option o un Map, cuyos typedefs van después de
        vec_typedefs."""
        while ty.name == VEC_MARK and ty.args:
            ty = ty.args[0]
        return ty.name in ("Option", "Result", MAP_MARK) or self._fn_tardio(ty)

    def _vec_con_struct(self, ty) -> bool:
        """Vec<Vec<..<Struct>>>: las funciones del de afuera usan las del de
        adentro, que van en vec_struct_defs (después de los structs), así que las
        suyas también."""
        while ty.name in (VEC_MARK, "Option", "Result") and ty.args:
            ty = ty.args[0]
        return ty.name in self.structs

    def _map_c_type(self, ty: TypeAnn) -> str:
        """Map<K,V> -> puntero a una tabla de direccionamiento abierto (linear
        probing, con tumbas para .remove()), monomorfizada por (K,V). K es
        primitivo: hace falta un scar_hash_<K> (emitidos una vez para todos los
        Map). Sin mutex: un Map no se comparte entre tareas.

        El Map es dueño de lo que guarda: set() sobre una clave que ya estaba
        libera el valor viejo (y la clave nueva, si es un str repetido), remove()
        entrega el valor y libera la clave, y free libera cada entrada ocupada."""
        key_ty = ty.args[0] if ty.args else T_I32
        val_ty = ty.args[1] if len(ty.args) > 1 else T_I32
        if key_ty.name not in C_TYPE:
            raise CodegenError(
                f"{ty!r}: el backend de C solo soporta Map<K,V> con K primitivo "
                f"(i32/i64/f64/str/bool), se dio {key_ty!r}"
            )
        val_is_struct = val_ty.name in self.structs
        # Map<K,Chan<V>>: un Chan es un handle compartido, guardado por copia
        val_is_chan = val_ty.name == CHAN_MARK
        # Map<K,Vec<T>>: el Vec va por valor en la entrada, y el Map es su dueño
        # (set libera el viejo, get lo clona, remove lo entrega, free los libera).
        val_is_vec = val_ty.name == VEC_MARK
        # Map<K, Map<K2,V2>>: el de adentro es un puntero a su tabla; el de
        # afuera es su dueño
        val_is_map = val_ty.name == MAP_MARK
        # Map<K, Option<T>>: el Option va por valor en la entrada; si lo de
        # adentro tiene dueño, el Map lo guarda propio
        val_is_opt = val_ty.name in ("Option", "Result")  # también Result
        if val_is_opt and not self._type_supported(val_ty):
            raise CodegenError(f"{ty!r}: el backend de C no soporta {val_ty!r} como valor de un Map")
        val_opt_dueno = val_is_opt and self._campo_compuesto_con_dueno(val_ty)
        # una fn o un Pipe como valor (nada que liberar)
        val_es_handle = val_ty.name in (FN_MARK, PIPE_MARK) or (
            val_ty.name == TASK_MARK and len(val_ty.args) >= 2)  # Map<K, Task<T, t>>
        if (val_ty.name not in C_TYPE and not val_is_struct and not val_is_chan and not val_is_vec
                and not val_is_map and not val_is_opt and not val_es_handle):
            raise CodegenError(
                f"{ty!r}: el backend de C solo soporta Map<K,V> con V primitivo, "
                f"struct de usuario, Vec<U>, Map<K2,V2>, Option<U> o Chan<U>, se dio {val_ty!r}"
            )
        val_vec_part = self._mangled_name(val_ty.args[0] if val_ty.args else T_I32) if val_is_vec else None
        # _mangled_name y no val_ty.name: Chan<i32> y Chan<f64> tendrían el
        # mismo nombre de C
        val_name_part = self._mangled_name(val_ty)
        key = (MAP_MARK, key_ty.name, val_name_part)
        if key in self.map_types:
            return self.map_types[key]
        self.needs_map_runtime = True
        suffix = f"{key_ty.name}_{val_name_part}"
        c_name = f"Map_{suffix}"
        self.map_types[key] = c_name
        key_c = C_TYPE[key_ty.name]
        val_c = self.c_type(val_ty)
        entry_name = f"ScarMapEntry_{suffix}"
        impl_name = f"ScarMapImpl_{suffix}"
        self.map_nombres[c_name] = (entry_name, suffix, key_ty, val_ty)
        # get()/remove() devuelven Option<V>, que tiene que existir antes
        opt_c_name = self._generic_c_type(TypeAnn("Option", [val_ty]))
        hash_fn = {
            "i32": "scar_hash_i32",
            "i64": "scar_hash_i64",
            "f64": "scar_hash_f64",
            "str": "scar_hash_str",
            "bool": "scar_hash_bool",
        }[key_ty.name]
        key_eq = (
            "(strcmp(m->entries[slot].key, key) == 0)"
            if key_ty.name == "str"
            else "(m->entries[slot].key == key)"
        )
        # Libera el valor de una entrada ocupada antes de pisarla o descartarla:
        # un struct con {V}_free, un str con scar_free, un Chan con decref; nada si
        # V es un número.
        free_old_value = (
            # con o sin tasks: {T}_free decide por el encabezado
            f"        {val_ty.name}_free(m->entries[idx].value);\n"
            if val_is_struct else
            f"        scar_free((char*)m->entries[idx].value);\n"
            if val_ty.name == "str" else
            # un Chan que ya estaba en esa clave: decref antes de pisarlo
            f"        scar_chan_decref_"
            f"{self._mangled_name(val_ty.args[0] if val_ty.args else T_I32)}"
            f"(m->entries[idx].value);\n"
            if val_is_chan else
            f"        scar_vec_free_{val_vec_part}(m->entries[idx].value);\n"
            if val_is_vec else
            "".join(l + "\n" for l in self._lineas_liberar_dueno(val_ty, "m->entries[idx].value", "        "))
            if val_is_map or val_opt_dueno else ""
        )
        # La clave str: si la clave ya estaba (mismo texto), la entrante sobra y
        # se libera acá; si no, el Map se queda con ella. Solo str tiene dueño
        # entre los K posibles.
        free_redundant_key = (
            "        scar_free((char*)key);\n"
            if key_ty.name == "str" else ""
        )
        # El typedef va a map_typedefs, antes de generic_defs: un
        # Option<Map<K,V>> lo guarda por valor. Si la entrada lleva un
        # Option (o un Vec/Map cuyo typedef fue a generic_defs), va a generic_defs,
        # detrás. Las funciones van a map_defs.
        _map_tras = self._map_tras_genericos(val_ty)
        (self.generic_defs if _map_tras else self.map_typedefs).append(
            f"typedef struct {{\n"
            f"    {key_c} key;\n"
            f"    {val_c} value;\n"
            f"    uint8_t state;  // 0 = vacio, 1 = ocupado, 2 = tumba (tras .remove())\n"
            f"    int64_t orden;  // cuándo entró la clave (print en orden de inserción)\n"
            f"}} {entry_name};\n"
            f"\n"
            f"typedef struct {{\n"
            f"    {entry_name} *entries;\n"
            f"    int32_t cap;\n"
            f"    int32_t count;       // entradas ocupadas (esto es .len())\n"
            f"    int32_t tombstones;  // entradas borradas -- cuentan para el load factor\n"
            f"    int64_t siguiente;   // el orden de la próxima clave nueva\n"
            f"}} {impl_name};\n"
            f"\n"
            f"typedef {impl_name}* {c_name};"
        )
        # el prototipo, después del typedef que nombra (los dos en la misma lista)
        (self.generic_defs if _map_tras else self.map_free_fwd_decls).append(
            f"static void scar_map_free_{suffix}({c_name} m);")
        self.map_defs.append(
            self._map_c_new_find(c_name, suffix, impl_name, entry_name, key_c, hash_fn,
                                 key_eq)
            + self._map_c_grow_set(suffix, c_name, entry_name, hash_fn, key_c, val_c,
                                   free_old_value, free_redundant_key)
            + self._map_c_get_remove(opt_c_name, c_name, suffix, key_c, val_ty, val_is_vec,
                                     val_is_map, val_opt_dueno, key_ty)
            + self._map_c_len_resto(suffix, c_name, val_ty, val_is_struct, val_is_chan,
                                    val_vec_part, val_is_vec, val_is_map, val_opt_dueno,
                                    key_ty)
        )
        return c_name

    def _pipe_c_type(self) -> str:
        """Pipe -> ScarPipe, struct por valor con sus dos descriptores. No es
        genérico: nada que monomorfizar."""
        self.uses_pipe = True
        return "ScarPipe"

    def _file_c_type(self) -> str:
        """File -> ScarFile. Puede ser el T de Result<File> (file_open), así que su
        typedef va antes de generic_defs."""
        self.needs_file_io = True
        self._registrar_results_de_io()
        self._registrar_result_de_archivo()
        return "ScarFile"

    def _handles_rt_c(self) -> str:
        """La tabla de handles de File, Socket y Listener. Un handle es
        (generación << 32) | (slot + 1); 0 nunca es válido (el valor de un
        Option vacío). Cerrar suelta el slot y sube su generación, así una copia
        vieja del handle (prestada a una fn que lo cerró, o sacada con get()) se
        ve cerrada y nunca toca un FILE* liberado ni un fd que el sistema ya le
        dio a otro. La tabla es global y vive todo el programa; crece hasta la
        mayor cantidad de handles abiertos a la vez. Con tareas, un mutex la
        protege."""
        if self.has_tasks:
            mu = "static pthread_mutex_t scar_h_mu = PTHREAD_MUTEX_INITIALIZER;\n"
            lock, unlock = "    pthread_mutex_lock(&scar_h_mu);\n", "    pthread_mutex_unlock(&scar_h_mu);\n"
        else:
            mu = lock = unlock = ""
        return runtime_c.texto(
            "handles",
            MU=mu,
            LOCK=lock,
            UNLOCK=unlock,
        )

    def _registrar_result_de_archivo(self):
        """El runtime de archivos se emite entero, y scar_file_open devuelve
        Result<File>: hay que registrarlo aunque el programa nombre File sin abrir
        ninguno."""
        if getattr(self, "_result_archivo_ok", False):
            return
        self._result_archivo_ok = True
        self.c_type(TypeAnn("Result", [TypeAnn(FILE_MARK)]))

    def _registrar_results_de_io(self):
        """El runtime de archivos y de red usa Result<str> y Result<i32>: se
        registran aunque el programa use un solo método."""
        if getattr(self, "_results_io_ok", False):
            return
        self._results_io_ok = True
        self.c_type(TypeAnn("Result", [T_STR]))
        self.c_type(TypeAnn("Result", [T_I32]))

    def _registrar_results_de_red(self):
        """El runtime de red se emite entero: necesita Result<Socket> y
        Result<Listener> aunque el programa use uno solo."""
        if getattr(self, "_results_red_ok", False):
            return
        self._results_red_ok = True
        self.c_type(TypeAnn("Result", [TypeAnn(SOCKET_MARK)]))
        self.c_type(TypeAnn("Result", [TypeAnn(LISTENER_MARK)]))

    def _socket_c_type(self) -> str:
        """Socket -> ScarSocket (un handle de la tabla). Puede ser el T de
        Result<Socket> (tcp_connect, accept)."""
        self.needs_net_io = True
        self._registrar_results_de_io()
        self._registrar_results_de_red()
        return "ScarSocket"

    def _listener_c_type(self) -> str:
        """Listener -> ScarListener (un handle de la tabla), como Socket."""
        self.needs_net_io = True
        self._registrar_results_de_io()
        self._registrar_results_de_red()
        return "ScarListener"

    def _expr_subexprs(self, expr):
        """Los hijos directos de `expr` (sin bajar a sentencias). Alimenta
        _iter_struct_lits_in_expr y _iter_calls_in_expr: si el AST gana un nodo
        de expresión con hijos, hay que sumarlo acá o ese caso queda invisible.
        Las hojas devuelven []."""
        if isinstance(expr, BinOp):
            return [expr.left, expr.right]
        if isinstance(expr, UnaryOp):
            return [expr.expr]
        if isinstance(expr, Call):
            return list(expr.args)
        if isinstance(expr, MethodCall):
            return [expr.obj] + list(expr.args)
        if isinstance(expr, FieldAccess):
            return [expr.obj]
        if isinstance(expr, IndexExpr):
            return [expr.obj, expr.index]
        if isinstance(expr, StructLit):
            return list(expr.fields.values())
        if isinstance(expr, ArrayLit):
            return list(expr.elems)
        if isinstance(expr, SpawnExpr):
            return [expr.call]
        if isinstance(expr, (TryExpr, OkExpr, ErrExpr, SomeExpr)):
            return [expr.expr]
        if isinstance(expr, PrintExpr):
            return list(expr.args)
        return []

    def _iter_struct_lits_in_expr(self, expr):
        """Cada StructLit de `expr` y de todo lo que cuelga de ella (también uno
        dentro de otro)."""
        if isinstance(expr, StructLit):
            yield expr
        for sub in self._expr_subexprs(expr):
            yield from self._iter_struct_lits_in_expr(sub)

    def _substitute_generic_field_type(self, ty, type_params, concrete_args):
        """Sustituye los type_params de `ty` por sus argumentos, recursivamente.
        Copia de _substitute_type_params de type_checker.py (paso C9)."""
        if ty.name in type_params and not ty.args:
            return concrete_args[type_params.index(ty.name)]
        if ty.args:
            return TypeAnn(
                ty.name,
                [self._substitute_generic_field_type(a, type_params, concrete_args) for a in ty.args],
            )
        return ty

    def _ensure_generic_struct_instance(self, struct_name, concrete_args):
        """Genera, si no existe, el struct monomorfizado de una combinación
        ('Caja' + [i32] -> 'Caja_i32') y lo registra en self.structs: desde ahí
        se trata como cualquier otro struct. Cacheado por combinación."""
        key = (struct_name, tuple(concrete_args))
        cached = self.generic_struct_instances.get(key)
        if cached is not None:
            return cached
        type_params = self.generic_structs[struct_name]["type_params"]
        raw_fields = self.generic_structs[struct_name]["fields"]
        mangled = struct_name + "".join(f"_{self._mangled_name(a)}" for a in concrete_args)
        self.generic_struct_instances[key] = mangled
        self._generic_origin[mangled] = (struct_name, list(concrete_args))
        prev_b, self._tbind = self._tbind, None
        try:
            fields = {
                fname: self._canon(self._substitute_generic_field_type(fty, type_params, concrete_args))
                for fname, fty in raw_fields.items()
            }
        finally:
            self._tbind = prev_b
        self.structs[mangled] = fields
        return mangled

    def _bind_generic_struct_type_params(self, fty, actual, type_params, bindings):
        """Unifica el tipo declarado `fty` (puede mencionar type_params) contra el
        tipo real `actual`, recorriendo los args en paralelo, para fijar cada T.
        No revalida inconsistencias: ya lo hizo el checker. Copia de
        _bind_type_params de type_checker.py (paso C9)."""
        if fty.name in type_params and not fty.args:
            bindings.setdefault(fty.name, actual)
            return
        origen = self._generic_origin.get(actual.name)
        if origen is not None and fty.name == origen[0] and len(fty.args) == len(origen[1]):
            # `actual` es la forma canónica (Tape_f64) de Tape<f64>
            for fa, aa in zip(fty.args, origen[1]):
                self._bind_generic_struct_type_params(fa, aa, type_params, bindings)
            return
        if fty.args and actual.args and fty.name == actual.name and len(fty.args) == len(actual.args):
            for fa, aa in zip(fty.args, actual.args):
                self._bind_generic_struct_type_params(fa, aa, type_params, bindings)

    def _generic_struct_concrete_args(self, expr, env, expected_ty=None):
        """Los T de un StructLit genérico, con el mismo criterio que el checker
        (que ya validó inconsistencias y campos faltantes)."""
        type_params = self.generic_structs[expr.name]["type_params"]
        decl_fields = self.generic_structs[expr.name]["fields"]
        bindings = {}
        for fname, fty in decl_fields.items():
            if fname in expr.fields:
                self._bind_generic_struct_type_params(
                    fty, self.infer(expr.fields[fname], env), type_params, bindings
                )
        if expected_ty is not None and len(bindings) < len(type_params):
            # un T que ningún campo fija (Grad<T> { idx }) sale del tipo esperado
            # (retorno de la fn, anotación del let)
            exp = self._canon(expected_ty)
            origen = self._generic_origin.get(exp.name)
            if origen is not None and origen[0] == expr.name:
                for tp, a in zip(type_params, origen[1]):
                    bindings.setdefault(tp, a)
        return [bindings.get(tp, T_I32) for tp in type_params]

    def _ensure_generic_fn_instance(self, fn_name, concrete_args):
        """Como _ensure_generic_struct_instance, para una fn genérica: genera, si
        no existe, la instancia ('identidad_i32'), registra su firma sustituida
        en fn_sigs y arma un FnDecl clon en generic_fn_decls; desde ahí gen_fn la
        trata como a cualquier fn. Cacheado por combinación."""
        key = (fn_name, tuple(concrete_args))
        cached = self.generic_fn_instances.get(key)
        if cached is not None:
            return cached
        info = self.generic_fns[fn_name]
        type_params = info["type_params"]
        mangled = fn_name + "".join(f"_{self._mangled_name(a)}" for a in concrete_args)
        self.generic_fn_instances[key] = mangled
        self.generic_fn_bindings[mangled] = dict(zip(type_params, concrete_args))
        prev_b, self._tbind = self._tbind, None
        try:
            params = [
                self._canon(self._substitute_generic_field_type(p, type_params, concrete_args))
                for p in info["params"]
            ]
            ret = self._canon(self._substitute_generic_field_type(info["ret"], type_params, concrete_args))
        finally:
            self._tbind = prev_b
        for p_name, p_ty in zip((p.name for p in info["decl"].params), params):
            if not self._type_supported(p_ty):
                raise CodegenError(
                    f"'{fn_name}<{', '.join(self._mangled_name(a) for a in concrete_args)}>': "
                    f"el parámetro '{p_name}' quedaría con tipo {p_ty!r}, no "
                    "soportado por el backend de C para esta combinación de tipos."
                )
        if not self._type_supported(ret):
            raise CodegenError(
                f"'{fn_name}<{', '.join(self._mangled_name(a) for a in concrete_args)}>': "
                f"el retorno quedaría con tipo {ret!r}, no soportado por el "
                "backend de C para esta combinación de tipos."
            )
        es_task = info.get("is_task", False)
        if es_task:
            self.task_sigs[mangled] = (params, ret)
        else:
            self.fn_sigs[mangled] = (params, ret)
        decl = info["decl"]
        # cada instancia lleva su propia copia del cuerpo, con los T de los `let`
        # anotados ya sustituidos: los análisis de propiedad y el codegen ven
        # código concreto
        body = copy.deepcopy(decl.body)
        prev_b, self._tbind = self._tbind, self.generic_fn_bindings[mangled]
        try:
            self._canon_declared_types(body, asignar=True)
        finally:
            self._tbind = prev_b
        mangled_decl = FnDecl(
            mangled, decl.params, body,
            is_task=es_task, return_type=None,
            accepts=getattr(decl, "accepts", None) if es_task else None, type_params=[],
        )
        self.generic_fn_decls[mangled] = mangled_decl
        if es_task:
            self.task_decls[mangled] = mangled_decl
        return mangled

    def _generic_fn_concrete_args(self, call_expr, env):
        """Los T de una llamada a una fn genérica: unifica cada parámetro declarado
        contra el tipo ya inferido de su argumento en esta llamada."""
        info = self.generic_fns[call_expr.callee.name]
        type_params = info["type_params"]
        decl_params = info["params"]
        bindings = {}
        for p_ty, arg_expr in zip(decl_params, call_expr.args):
            self._bind_generic_struct_type_params(
                p_ty, self.infer(arg_expr, env), type_params, bindings
            )
        return [bindings.get(tp, T_I32) for tp in type_params]

    def _iter_calls_in_expr(self, expr):
        """Cada Call de `expr` y de todo lo que cuelga de ella."""
        if isinstance(expr, Call):
            yield expr
        for sub in self._expr_subexprs(expr):
            yield from self._iter_calls_in_expr(sub)

    def _iter_calls_with_env(self, block, env, finder=None):
        """Recorre las llamadas de un bloque y va armando `env` con cada `let` en
        orden (tipo anotado, o inferido con lo que ya hay en env); entrega (call,
        env). Así se resuelve también una llamada genérica que recibe una variable
        `let`. Un `let` que no se puede inferir acá se salta: esto solo busca
        instancias, gen_fn valida de verdad."""
        env = dict(env)
        for stmt in block.stmts:
            exprs = []
            if isinstance(stmt, LetStmt):
                exprs = [stmt.expr]
            elif isinstance(stmt, (ReturnStmt, ExprStmt)):
                exprs = [stmt.expr] if stmt.expr is not None else []
            elif isinstance(stmt, AssignStmt):
                exprs = [stmt.target, stmt.expr]
            elif isinstance(stmt, (IfStmt, WhileStmt)):
                exprs = [stmt.cond]
            elif isinstance(stmt, WhileLetStmt):
                exprs = [stmt.expr]
            elif isinstance(stmt, ForStmt):
                exprs = [stmt.start, stmt.end]
            for e in exprs:
                for call in (finder or self._iter_calls_in_expr)(e):
                    yield call, env
            if isinstance(stmt, LetStmt):
                ty = self._canon(getattr(stmt, "declared_type", None))
                if ty is None:
                    try:
                        ty = self.infer(stmt.expr, env)
                    except CodegenError:
                        ty = None
                if ty is not None:
                    env[stmt.name] = ty
            elif isinstance(stmt, IfStmt):
                yield from self._iter_calls_with_env(stmt.then_block, env, finder)
                if stmt.else_block is not None:
                    yield from self._iter_calls_with_env(stmt.else_block, env, finder)
            elif isinstance(stmt, WhileStmt):
                yield from self._iter_calls_with_env(stmt.body, env, finder)
            elif isinstance(stmt, WhileLetStmt):
                inner = dict(env)
                try:
                    opt = self.infer(stmt.expr, env)
                    if opt.args:
                        inner[stmt.pattern] = opt.args[0]
                except CodegenError:
                    pass
                yield from self._iter_calls_with_env(stmt.body, inner, finder)
            elif isinstance(stmt, ForStmt):
                inner = dict(env)
                inner[stmt.var] = T_I32
                yield from self._iter_calls_with_env(stmt.body, inner, finder)

    def _resolve_generic_fn_instances(self):
        """Pre-pase: busca en todo el programa cada llamada a una fn genérica y
        registra su instancia. Tiene que correr antes de que generate() arme las
        declaraciones a partir de fn_sigs."""
        if not self.generic_fns:
            return
        for item in self.program.items:
            if not isinstance(item, FnDecl) or item.type_params:
                continue
            params, _ret = self.task_sigs[item.name] if item.is_task else self.fn_sigs[item.name]
            env = {p.name: t for p, t in zip(item.params, params)}
            for call, call_env in self._iter_calls_with_env(item.body, env):
                if not isinstance(call.callee, Ident) or call.callee.name not in self.generic_fns:
                    continue
                # la llamada pasa a nombrar su instancia (`tape_get` -> `tape_get_f64`),
                # así los análisis de propiedad la ven como a cualquier fn concreta
                call.callee.name = self._ensure_generic_fn_instance(
                    call.callee.name, self._generic_fn_concrete_args(call, call_env)
                )
        # Cierre transitivo: una fn genérica que llama a otra reenviando su T
        # recién tiene tipos concretos dentro de cada instancia. Se recorre el
        # cuerpo de cada instancia nueva hasta que no aparezcan más.
        scanned = set()
        while True:
            pending = [m for m in list(self.generic_fn_decls) if m not in scanned]
            if not pending:
                break
            for mangled in pending:
                scanned.add(mangled)
                decl = self.generic_fn_decls[mangled]
                params, _ret = (self.task_sigs if decl.is_task else self.fn_sigs)[mangled]
                env = {p.name: t for p, t in zip(decl.params, params)}
                prev_b, self._tbind = self._tbind, self.generic_fn_bindings.get(mangled)
                try:
                    for call, call_env in self._iter_calls_with_env(decl.body, env):
                        if not isinstance(call.callee, Ident) or call.callee.name not in self.generic_fns:
                            continue
                        call.callee.name = self._ensure_generic_fn_instance(
                            call.callee.name, self._generic_fn_concrete_args(call, call_env)
                        )
                    self._canon_declared_types(decl.body)
                finally:
                    self._tbind = prev_b
        # un `let` anotado puede nombrar un struct genérico concreto que ninguna
        # firma menciona; su instancia tiene que existir antes de emitir los
        # structs
        for item in self.program.items:
            if isinstance(item, FnDecl) and not item.type_params:
                self._canon_declared_types(item.body)

    def _canon_declared_types(self, block, asignar=False):
        """Canoniza (y así monomorfiza) todo tipo anotado en un `let` de `block` y
        sus bloques anidados. Con `asignar`, además lo reemplaza en el AST (la
        copia propia de una instancia de fn genérica)."""
        for stmt in block.stmts:
            if isinstance(stmt, LetStmt) and getattr(stmt, "declared_type", None) is not None:
                c = self._canon(stmt.declared_type)
                if asignar:
                    stmt.declared_type = c
            for attr in ("then_block", "else_block", "body"):
                sub = getattr(stmt, attr, None)
                if sub is not None and hasattr(sub, "stmts"):
                    self._canon_declared_types(sub, asignar)

    def _concrete_fn_items(self):
        """Las fn/task concretas del programa más las instancias de las fn
        genéricas (con su cuerpo ya monomorfizado), para los análisis de
        propiedad."""
        for item in self.program.items:
            if isinstance(item, FnDecl) and not item.type_params:
                yield item
        yield from self.generic_fn_decls.values()

    def _resolve_generic_struct_instances(self):
        """Pre-pase: busca cada StructLit de un struct genérico y registra su
        instancia. Tiene que correr antes de que generate() arme los typedefs a
        partir de self.structs (si se resolviera al generar los cuerpos, la
        instancia llegaría tarde)."""
        if not self.generic_structs:
            return
        for item in self.program.items:
            if not isinstance(item, FnDecl) or item.type_params:
                continue
            params, _ret = self.task_sigs[item.name] if item.is_task else self.fn_sigs[item.name]
            env = {p.name: t for p, t in zip(item.params, params)}
            # con el env de los `let`
            for lit, lit_env in self._iter_calls_with_env(item.body, env, self._iter_struct_lits_in_expr):
                if lit.name not in self.generic_structs:
                    continue
                try:
                    args = self._generic_struct_concrete_args(lit, lit_env)
                except CodegenError:
                    continue  # gen_fn lo resuelve (o reporta) con el env completo
                self._ensure_generic_struct_instance(lit.name, args)

    def _is_option_struct(self, ty) -> bool:
        return (ty is not None and ty.name == "Option" and bool(ty.args)
                and ty.args[0].name in self.structs)
