"""Mixin Frescura de Codegen (paso C6): si un valor es nuevo. Decide cuándo
un valor (un str concatenado, el resultado de una llamada, un pop, un recv, un
campo sacado de una temporal) ya es propio y se puede entregar sin copiar: el
contrato de str, qué parámetros consume una fn y las capturas de
argumentos frescos. Es análisis: no emite frees (eso es Propiedad).
"""

from parser import (marca_new_generico, elemento_de_pop,
    StrLit, Ident, BinOp, Call, FieldAccess, IndexExpr, StructLit, ArrayLit, TryExpr,
    OkExpr, ErrExpr, SomeExpr, NoneExpr, MethodCall,
)
from types_ import T_I32, T_STR
from fresh_owned import (
    resolve_consumed_option_params, resolve_consumed_params, resolve_fn_ownership,
)

from .comun import (
    CHAN_MARK, CodegenError, FILE_MARK, FN_MARK, LISTENER_MARK, MAP_MARK, SOCKET_MARK,
    TASK_MARK, VEC_MARK,
)


class Frescura:
    # Builtins que devuelven Result<T> cuyo `.err`, si existe, es siempre un
    # str propio (scar_malloc), nunca memoria estática.
    RESULT_FRESH_BUILTINS = frozenset({
        "int", "int64", "read_pipe", "file_open", "tcp_connect", "tcp_listen",
    })

    # ---- Contrato único de str ----
    #
    # Toda fn/task que devuelve `str` (o `Result<str>`) entrega un str propio:
    # quien llama es siempre dueño del resultado. En cada `return`, lo que ya es
    # propio se entrega tal cual y lo que no (un literal, un parámetro, un
    # campo, un parámetro de task de dueño condicional) se copia.

    def _is_fresh_str_concat_expr(self, expr, env) -> bool:
        """True si `expr` reserva un str nuevo: un `+` de str (scar_str_concat), un
        s[i] (scar_str_index) o un campo str sacado de un struct temporal. La
        misma condición que usa _let_creates_fresh_owner."""
        if isinstance(expr, IndexExpr):
            return True
        if isinstance(expr, FieldAccess):
            # un campo str sacado de un struct temporal
            info = self._campo_de_temporal(expr, env)
            return info is not None and info[2].name == "str"
        return isinstance(expr, BinOp) and expr.op == "+" and self.infer(expr, env).name == "str"

    def _is_fresh_result_producer(self, expr, env) -> bool:
        """True si `expr` produce un Result<T> nuevo, sin alias: un Ok(...)/Err(...)
        (el constructor arma el struct desde cero, y Err copia su texto), una
        llamada a un builtin de RESULT_FRESH_BUILTINS, o read_all/read/write/
        accept de File/Socket/Listener (funciones scar_* que siempre arman un
        Result nuevo). Sirve para saber que `.err` se puede liberar."""
        if isinstance(expr, (OkExpr, ErrExpr)):
            return True
        if isinstance(expr, Call) and isinstance(expr.callee, Ident):
            if expr.callee.name in self.RESULT_FRESH_BUILTINS:
                return True
        if isinstance(expr, MethodCall):
            try:
                obj_ty = self.infer(expr.obj, env)
            except CodegenError:
                return False
            if obj_ty.name == FILE_MARK and expr.method in ("read_all", "read_bytes", "write", "write_bytes"):
                return True
            if obj_ty.name == SOCKET_MARK and expr.method in ("read", "read_bytes", "write", "write_bytes"):
                return True
            if obj_ty.name == LISTENER_MARK and expr.method == "accept":
                return True
        return False

    def _is_fresh_try_value(self, expr, env) -> bool:
        """True si `expr` es un `algo?` cuyo `.value` es un valor nuevo, del que
        quien lo recibe pasa a ser dueño: read()/read_all()/read_pipe() (todos
        con scar_malloc), una llamada a una fn que _resolve_fresh_owned_fns marcó
        fresca, una extern fn con Result<str>, o Ok(x)? con x a su vez fresco
        (no basta con estar envuelto en Ok)."""
        if not isinstance(expr, TryExpr):
            return False
        inner = expr.expr
        if isinstance(inner, OkExpr):
            return self._let_creates_fresh_owner(inner.expr, None, env)
        if isinstance(inner, Call) and isinstance(inner.callee, Ident):
            # `f(x)?` con f una fn que fresh_owned_fns marcó siempre fresca
            if inner.callee.name == "read_pipe":
                return True
            if inner.callee.name in self.result_str_value_origin:
                return True  # Contrato único de str
            sig = self.extern_sigs.get(inner.callee.name)
            if (inner.callee.name not in self.fn_sigs and sig is not None
                    and sig[1].name == "Result" and sig[1].args[0].name == "str"):
                # una extern fn con Result<str>: su str es siempre una copia propia
                # (scar_ffi_str_propia, o la lectura del worker)
                return True
            if getattr(inner.callee, "es_valor_fn", False):
                return True  # contrato del tipo fn(...)
            return self.fresh_owned_fns.get(inner.callee.name, False)
        if isinstance(inner, MethodCall):
            try:
                obj_ty = self.infer(inner.obj, env)
            except CodegenError:
                return False
            if obj_ty.name == SOCKET_MARK and inner.method in ("read", "read_bytes"):
                return True
            if obj_ty.name == FILE_MARK and inner.method in ("read_all", "read_bytes"):
                return True
        return False

    def _is_fresh_str_call(self, expr) -> bool:
        """True si `expr` es una llamada que devuelve un str nuevo: una fn/task
        (contrato único de str), una extern fn con retorno str (siempre
        una copia), r.err() o una llamada a través de un valor fn. No
        necesita `env`: alcanza con mirar a quién se llama."""
        if isinstance(expr, MethodCall) and expr.method == "err" and not expr.args:
            # r.err(): el único método `err` es el de Result, y devuelve una copia
            # del mensaje
            return True
        if isinstance(expr, MethodCall) and expr.method == "replace":
            t = getattr(expr, "tipo_replace", None)
            if t is not None:
                return self._canon(t) == T_STR
            return bool(getattr(expr, "devuelve_str", False))
        if not (isinstance(expr, Call) and isinstance(expr.callee, Ident)):
            return False
        name = expr.callee.name
        if getattr(expr.callee, "es_valor_fn", False):
            # una llamada a través de un valor fn (`f(x)` con f: fn(f64) -> str):
            # también entrega un str propio (contrato único).
            ret = getattr(expr.callee, "retorno_valor_fn", None)
            return ret is not None and ret.name == "str"
        if name in ("chr", "a_texto") and name not in self.fn_sigs:
            return True  # builtin: siempre un buffer nuevo
        if self.fresh_str_fns.get(name, False):
            return True
        return (
            name in self.extern_sigs
            and self.extern_sigs[name][1].name == "str"
        )

    def _str_entregable(self, e, env) -> bool:
        """True si devolver `e` entrega un str propio sin copiarlo: una dueña
        incondicional ("plain") o una expresión que reserva uno nuevo."""
        if isinstance(e, Ident):
            return self._is_owner(e.name) and (self._owner_origin(e.name) or "plain") == "plain"
        if isinstance(e, StrLit):
            return False
        if isinstance(e, FieldAccess) and self._campo_de_temporal(e, env) is not None:
            # `mk().b` se saca del temporal y es propio. Copiarlo (`mk().b
            # + ""`) perdía esa extracción y el temporal no se liberaba.
            return True
        try:
            return bool(self._let_creates_fresh_owner(e, None, env))
        except CodegenError:
            return False

    @staticmethod
    def _copia_str(e):
        n = BinOp("+", e, StrLit(""))  # scar_str_concat(e, ""): un buffer propio
        n.line, n.col = e.line, e.col
        return n

    def _str_return_propio(self, expr, env):
        """El `expr` de un `return`, reescrito si hace falta para cumplir el
        contrato único de str."""
        ret = self.cur_ret_ty
        if ret is None:
            return expr
        if ret.name == "str":
            return expr if self._str_entregable(expr, env) else self._copia_str(expr)
        if ret.name == "Result" and ret.args and ret.args[0].name == "str" and isinstance(expr, OkExpr):
            if self._str_entregable(expr.expr, env):
                return expr
            n = OkExpr(self._copia_str(expr.expr))
            n.line, n.col = expr.line, expr.col
            return n
        return expr

    def _resolve_fresh_str_fns(self):
        """Con el contrato único de str, toda fn/task que devuelve str queda
        "fresca". El diccionario se conserva porque lo consultan varios sitios
        (_is_fresh_str_call, el envoltorio de una task, los campos str de un
        struct)."""
        self.fresh_str_fns = {}
        for item in self._concrete_fn_items():
            params, ret = self.task_sigs[item.name] if item.is_task else self.fn_sigs[item.name]
            if ret.name == "str":
                self.fresh_str_fns[item.name] = True

    def _is_fresh_owned_expr(self, expr, ret_ty, types_env) -> bool:
        """True si `expr` es una fuente terminal de un valor nuevo del tipo
        `ret_ty`: un struct literal, vec_new()/map_new(), .join() de una
        Task<Struct>, replace(), pop() o get() de un Vec<Struct>, un Ok/Err
        nuevo... Lo usa el análisis de flujo de fresh_owned.py, que se ocupa de
        las llamadas a otras fns. Tiene que coincidir con _let_creates_fresh_owner:
        si dos sitios no acuerdan quién es fresco, hay un double free o una
        pérdida."""
        if isinstance(expr, StructLit):
            return True
        if isinstance(expr, ArrayLit):
            return ret_ty.name == VEC_MARK  # [a, b]: un Vec nuevo
        new_mark = marca_new_generico(expr)
        if new_mark is not None and new_mark == ret_ty.name:
            return True
        if isinstance(expr, MethodCall) and expr.method == "join":
            try:
                obj_ty = self.infer(expr.obj, types_env)
            except CodegenError:
                return False
            return obj_ty.name == TASK_MARK
        if self._is_vec_replace(expr, types_env):
            # `return v.replace(i, x)` devuelve el viejo, propio
            try:
                return self.infer(expr, types_env) == ret_ty
            except CodegenError:
                return False
        if ret_ty.name == "Result" and self._is_fresh_result_producer(expr, types_env):
            return True
        if ret_ty.name == "Option" and isinstance(expr, MethodCall) and expr.method in ("pop", "get"):
            # `return v.pop()` (y get() de un Vec<Struct>, que copia) entrega un
            # Option nuevo: quien llama es su dueño
            try:
                if ((self._is_fresh_vec_pop(expr, types_env)
                     or self._is_fresh_vec_get_struct(expr, types_env))
                        and self.infer(expr, types_env) == ret_ty):
                    return True
            except CodegenError:
                return False
        if ret_ty.name == "str" and (self._is_fresh_str_concat_expr(expr, types_env)
                                     or self._is_fresh_str_call(expr)):
            # el str de un `Some(...)` que se devuelve
            return True
        # una llamada a otra fn/task la resuelve fresh_owned.py (con memoria y
        # detección de ciclos), no esta función
        return False

    def _resolve_fresh_owned_fns(self):
        """Para cada fn/task que devuelve un struct, Vec, Map, Result u
        Option<...> con dueño: True si siempre entrega un valor nuevo (nunca un
        alias de un parámetro o de un campo). Lo decide el análisis de flujo de
        fresh_owned.py sobre todo el cuerpo, que también entiende el patrón
        acumulador (`let mut r = P {..}; while ... { r = P {..} }; return r`) y
        propaga lo fresco a través de envoltorios (`fn leer(s) { return s.read()
        }`). Corre antes de generar cualquier fn (una puede llamar a otra
        declarada más abajo). Resultado en fresh_owned_fns."""
        owned_fn_decls = {}
        for item in self._concrete_fn_items():
            params, ret = self.task_sigs[item.name] if item.is_task else self.fn_sigs[item.name]
            if ret.name in self.structs or ret.name in (VEC_MARK, MAP_MARK, "Result"):
                owned_fn_decls[item.name] = (item, params, ret)
            elif ret.name == "Option" and ret.args and (
                    ret.args[0].name in (VEC_MARK, MAP_MARK, "str") or ret.args[0].name in self.structs):
                # Option<Vec>, Option<Map>, Option<str>, Option<Struct>: quien llama es
                # dueño del contenido si la fn devuelve siempre Some(fresco) o None
                owned_fn_decls[item.name] = (item, params, ret)

        # El recorrido (flujo, memoria, ciclos) vive en fresh_owned.py; acá solo
        # se aportan los criterios del codegen (el tipo de un `let`, qué expresión
        # es una fuente fresca terminal).
        def let_type(stmt, types_env):
            new_mark = marca_new_generico(stmt.expr)
            try:
                if stmt.declared_type is not None and new_mark is not None:
                    return stmt.declared_type
                return self.infer(stmt.expr, types_env, expected_ty=stmt.declared_type)
            except CodegenError:
                # no debería pasar (el programa ya pasó el checker): esa variable no se
                # sigue
                return None

        def infer(expr, types_env):
            try:
                return self.infer(expr, types_env)
            except CodegenError:
                return None

        self.fn_ownership = resolve_fn_ownership(
            owned_fn_decls, let_type, infer, self._is_fresh_owned_expr,
            is_struct=lambda t: t.name in self.structs,
        )
        self.fresh_owned_fns = {name: r.fresh for name, r in self.fn_ownership.items()}
        for item in self._concrete_fn_items():
            _params, ret = self.task_sigs[item.name] if item.is_task else self.fn_sigs[item.name]
            if self._ret_con_contrato(ret):
                # contrato único (ver _ret_con_contrato): el `return` copia lo que no es
                # propio, así que toda llamada entrega un valor nuevo
                self.fresh_owned_fns[item.name] = True

    def _ret_con_contrato(self, ty) -> bool:
        """Tipos de retorno con contrato único, como str: Option<str>,
        Option<Chan<T>> y los Option/Result anidados. Una fn los recibe siempre
        prestados, así que devolver un parámetro hacía que quien llama liberara
        dos veces lo mismo. El `return` entrega siempre un valor propio: lo que
        es de la fn tal cual, lo prestado como copia (_retorno_propio)."""
        if ty is None or ty.name != "Option" and ty.name != "Result":
            return False
        if self._es_anidado(ty):
            return True
        return ty.name == "Option" and bool(ty.args) and ty.args[0].name in ("str", CHAN_MARK)

    def _retorno_propio(self, expr, ty, env) -> bool:
        """True si `return expr` (de un tipo con contrato) ya entrega algo que es
        de la fn: una dueña (se transfiere), Some/Ok de una dueña o de algo
        fresco, None, Err, una llamada. Lo demás se copia."""
        if isinstance(expr, Ident):
            return self._is_owner(expr.name)
        if isinstance(expr, (SomeExpr, OkExpr)):
            payload = ty.args[0] if ty.args else T_I32
            if not self._necesita_clonar(payload):
                return True
            if isinstance(expr.expr, Ident):
                return self._is_owner(expr.expr.name)
            if payload.name in ("Option", "Result"):
                return self._retorno_propio(expr.expr, payload, env)
        return self._valor_compuesto_propio(expr, ty, env)

    def _resolve_consumed_params(self):
        """Qué parámetros struct consume cada fn (los guarda en un contenedor, los
        embebe, los envuelve, los pasa a un spawn o a otra fn que los consume).
        Lo calcula fresh_owned.resolve_consumed_params, la misma función que usa
        el checker para mover el argumento en quien llama: los dos lados no
        pueden desacordar. La fn es dueña del parámetro desde la entrada (gen_fn)
        y quien llama deja de serlo (Call)."""
        fns = {}
        for item in self._concrete_fn_items():
            if not item.is_task and item.name in self.fn_sigs:
                fns[item.name] = (item, self.fn_sigs[item.name][0])
        self.consumed_params = resolve_consumed_params(fns, lambda t: t.name in self.structs, self.structs)
        self.consumed_option_params = resolve_consumed_option_params(
            fns, lambda t: t.name == "Option" and bool(t.args) and t.args[0].name in self.structs)

    def _capture_fresh_option_arg(self, fn_name, index, expr, code, env, out, pad):
        """`f(v.get(0))` pasa una copia nueva (un Option<Struct> de
        get()/pop()/recv()) directo como argumento, sin variable que sea su
        dueña. Si f no se queda con el contenido de ese parámetro, la copia va a
        un temporal que se libera al terminar la sentencia. Si f es genérica, una
        task, una extern o la consume, o si es la condición de un if/while/for, se
        deja como está: en el peor caso una pérdida acotada, nunca un free
        inválido."""
        if not self._can_capture_arg_temps or fn_name is None:
            return code
        params = self.fn_sigs[fn_name][0] if fn_name in self.fn_sigs and fn_name not in self.task_sigs else None
        if (params is not None and index < len(params) and self._es_anidado(params[index])
                and not isinstance(expr, (Ident, FieldAccess, NoneExpr))
                and self._valor_compuesto_propio(expr, params[index], env)):
            # un Option/Result anidado fresco que la fn recibe prestado
            drop = self._vivo_drop_fn(params[index], "anidado")
            if drop is None:
                return code
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(params[index])} {tmp} = {code};")
            self.pending_expr_temps.append(f"dropfree:{drop}:{tmp}")
            return tmp
        if fn_name not in self.consumed_option_params:
            return code
        if index in self.consumed_option_params[fn_name]:
            return code
        try:
            ty = self.infer(expr, env)
        except CodegenError:
            return code
        if isinstance(expr, ErrExpr) and fn_name in self.fn_sigs:
            # un Err no dice su tipo: el del parámetro
            params = self.fn_sigs[fn_name][0]
            if index < len(params) and params[index] is not None:
                ty = params[index]
        if (ty.name == "Result" and ty.args and ty.args[0].name == "str"
                and fn_name in self.fn_sigs and fn_name not in self.task_sigs
                and isinstance(expr, (OkExpr, ErrExpr))):
            # `f(Err("x"))`, `f(Ok(a + b))` con un parámetro Result<str> prestado:
            # se sueltan el .err (siempre propio) y, si es fresco, el .value
            fresco = isinstance(expr, OkExpr) and self._let_creates_fresh_owner(
                expr.expr, marca_new_generico(expr.expr), env)
            drop = self._vivo_drop_fn(ty, "result_str:plain" if fresco else "plain")
            if drop is None:
                return code
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
            self.pending_expr_temps.append(f"dropfree:{drop}:{tmp}")
            return tmp
        if (ty.name == "Option" and ty.args and ty.args[0].name == "str"
                and fn_name in self.fn_sigs and fn_name not in self.task_sigs
                and self._option_str_fresca(expr, env)):
            # `f(Some("a" + b))` con un parámetro Option<str>, que una fn recibe
            # prestado (si lo guarda, se queda con una copia): el str se suelta al
            # terminar la sentencia
            drop = self._vivo_drop_fn(ty, "plain")
            if drop is None:
                return code
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
            self.pending_expr_temps.append(f"dropfree:{drop}:{tmp}")
            return tmp
        if not (self._option_payload_is_malloc(expr, ty, env) or self._option_struct_fresca(expr, ty, env)):
            return code
        tmp = self._new_tmp()
        out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
        self.pending_expr_temps.append(f"optfree:{ty.args[0].name}:{tmp}")
        return tmp

    # Tipos de campo que se pueden sacar de un struct temporal, dejando un
    # valor vacío que {T}_free tolera.
    def _campo_de_temporal(self, expr, env):
        """Si `expr` lee un campo con dueño (str, struct, Vec, Map) de un struct
        fresco que nadie más tiene (`mk().s`, `F { e: E {..} }.e`): (raíz,
        camino, tipo del campo, tipo de la raíz, free de la raíz). Si no, None."""
        if not isinstance(expr, FieldAccess):
            return None
        raiz, camino = expr, []
        while isinstance(raiz, FieldAccess):
            camino.append(raiz.field)
            raiz = raiz.obj
        if isinstance(raiz, Ident):
            return None
        try:
            campo_ty = self.infer(expr, env)
            raiz_ty = self.infer(raiz, env)
        except CodegenError:
            return None
        if not (campo_ty.name == "str" or campo_ty.name in self.structs
                or campo_ty.name in (VEC_MARK, MAP_MARK)
                or self._campo_compuesto_con_dueno(campo_ty)):
            return None
        free_fn = self._struct_free_fn(raiz_ty)
        if free_fn is None:
            return None
        if not self._let_creates_fresh_owner(raiz, marca_new_generico(raiz), env):
            return None
        return raiz, list(reversed(camino)), campo_ty, raiz_ty, free_fn

    def _sacar_campo_de_temporal(self, expr, env, out, pad):
        """`mk().s`, `F { e: E {..} }.e.s`: la raíz va a un temporal, el campo a
        otro, en la raíz queda un valor vacío (NULL, o {0} para Vec/Map) y la
        raíz se libera en el acto, con todo lo demás que colgaba de ella. El
        valor sacado es fresco: quien lo recibe es su dueña (también para el
        checker). Entre crear la raíz y liberarla no hay ninguna llamada: nada
        puede cancelar ni hacer panic ahí."""
        info = self._campo_de_temporal(expr, env)
        if info is None:
            return None
        raiz, camino, campo_ty, raiz_ty, free_fn = info
        raiz_code = self.gen_expr(raiz, env, out, pad)
        tr = self._new_tmp()
        out.append(f"{pad}{self.c_type(raiz_ty)} {tr} = {raiz_code};")
        ruta = tr + "".join(f"->{c}" for c in camino)
        tv = self._new_tmp()
        campo_c = self.c_type(campo_ty)
        if campo_ty.name == CHAN_MARK:
            # un Chan se comparte: el valor sacado cuenta su propia referencia y la
            # raíz suelta la suya (nunca queda un NULL para su decref)
            out.append(f"{pad}{campo_c} {tv} = {self._clone_value_expr(campo_ty, ruta)};")
            out.append(f"{pad}{free_fn}({tr});")
            return tv
        out.append(f"{pad}{campo_c} {tv} = {ruta};")
        # Vec/Map por valor y Option/Result: {0} es vacío (None, o un Err sin
        # mensaje); {S}_free no libera nada de eso
        vacio = (f"({campo_c}){{0}}" if campo_ty.name in (VEC_MARK, MAP_MARK, "Option", "Result")
                 else "NULL")
        out.append(f"{pad}{ruta} = {vacio};")
        out.append(f"{pad}{free_fn}({tr});")
        return tv

    def _capture_fresh_struct_temp(self, expr, code, env, out, pad):
        """Un struct fresco que se usa sin que nadie sea su dueña (`rect(...,
        color(1, 2, 3))`, `mk().campo`): va a un temporal que se libera al
        terminar la sentencia."""
        if not self._can_capture_arg_temps:
            return code
        try:
            ty = self.infer(expr, env)
        except CodegenError:
            return code
        free_fn = self._struct_free_fn(ty)
        if free_fn is None:
            return code
        if not self._let_creates_fresh_owner(expr, marca_new_generico(expr), env):
            return code
        tmp = self._new_tmp()
        out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
        self.pending_expr_temps.append(f"structfree:{free_fn}:{tmp}")
        return tmp

    def _capture_fresh_owned_arg(self, expr, code, env, out, pad):
        """Un Vec/Map/struct fresco pasado a algo que solo lo lee
        (`s.write_bytes(armar())`): temporal liberado al terminar la sentencia."""
        if not self._can_capture_arg_temps:
            return code
        try:
            ty = self.infer(expr, env)
        except CodegenError:
            return code
        if ty.name == "str" or not self._is_ownable_type(ty):
            return code
        if not self._let_creates_fresh_owner(expr, marca_new_generico(expr), env):
            return code
        # el mismo origen que tendría en un `let`: un Result<str> fresco
        # (`getenv(x).is_err()`) suelta también su `.value`
        origin = self._print_fresh_result_origin(expr, ty, env) or "plain"
        drop = self._vivo_drop_fn(ty, origin)
        if drop is None:
            return code
        tmp = self._new_tmp()
        out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
        self.pending_expr_temps.append(f"dropfree:{drop}:{tmp}")
        return tmp

    def _arg_transferible(self, arg, env) -> bool:
        """`let h = mayor(otro, Punto {..})`: el checker da a `otro` por movida al
        resultado (la fn puede devolverla), así que acá es un argumento fresco
        más: se suelta al terminar la sentencia si no es lo que volvió, y si lo
        es, es de `h`.

        Solo el caso simple: una dueña "plain" de un struct, que no es alias ni
        el contenido de un Option, declarada en el mismo bloque que el `let` (ni
        un loop ni una rama en el medio, que pedirían flags de runtime)."""
        if not isinstance(arg, Ident):
            return False
        name = arg.name
        if self._resolve_alias_root(name) != name or name in self._opt_payload_of:
            return False
        if name in self._consume_flags or self._owner_origin(name) != "plain":
            return False
        try:
            ty = self.infer(arg, env)
        except CodegenError:
            return False
        if not (ty.name in self.structs and self._struct_free_fn(ty) is not None):
            return False
        if self.owner_stack and self._decl_frame_of(name) == len(self.owner_stack) - 1 \
                and name in self.owner_stack[-1]:
            return "mismo"
        # declarada en un bloque de afuera (o antes de un loop): sigue siendo
        # dueña y la sentencia la deja en NULL, así el free de su alcance (o de su
        # reasignación) no hace nada
        return "anular"

    def _capture_fresh_struct_arg(self, fn_name, index, expr, code, env, out, pad):
        """Un struct fresco pasado a una fn que solo lo presta (ni lo consume ni
        puede devolverlo), o por valor a una extern fn (que copia los campos):
        nadie lo libera después de la llamada, así que va a un temporal."""
        if fn_name is None:
            return code
        if fn_name in self.extern_sigs:
            return self._capture_fresh_struct_temp(expr, code, env, out, pad)
        if fn_name in env and env[fn_name].name == FN_MARK and fn_name not in self.fn_sigs:
            # un valor fn presta los structs que recibe y nunca devuelve uno de
            # ellos (contrato): un struct fresco se suelta al terminar la sentencia
            return self._capture_fresh_struct_temp(expr, code, env, out, pad)
        if fn_name not in self.fn_sigs or fn_name in self.task_sigs:
            return code
        if index in self.consumed_params.get(fn_name, ()):
            return code
        ret_ty = self.fn_sigs[fn_name][1]
        if ret_ty is not None and self._struct_free_fn(ret_ty) is not None:
            # la fn devuelve un struct: si puede ser este mismo argumento, el
            # resultado es su dueño, no el temporal
            own = self.fn_ownership.get(fn_name)
            if own is None or own.ret_set is None or own.may_return_param(index):
                return code
        return self._capture_fresh_struct_temp(expr, code, env, out, pad)

    def _capture_fresh_str_concat_arg(self, expr, code, env, out, pad):
        """Un str fresco usado como argumento (de una llamada, un método o print)
        sin pasar por un `let`: un `+` (_is_fresh_str_concat_expr), una llamada
        que devuelve un str propio (_is_fresh_str_call) o un `algo?` que deja un
        str propio. Va a un temporal que _flush_pending_expr_temps libera al
        terminar la sentencia. Si no es fresco, devuelve `code` sin tocar."""
        if not (self._is_fresh_str_concat_expr(expr, env) or self._is_fresh_str_call(expr)):
            # un `algo?` que deja un str fresco pasado directo como argumento
            # (`f(leer(path)?)`): mismo criterio que `let x = algo?`
            origin = self._inline_try_str_origin(expr, env)
            if origin is None:
                return code
            tmp = self._new_tmp()
            out.append(f"{pad}const char* {tmp} = {code};")
            self.pending_expr_temps.append(tmp)
            return tmp
        tmp = self._new_tmp()
        out.append(f"{pad}const char* {tmp} = {code};")
        self.pending_expr_temps.append(tmp)
        return tmp

    def _inline_try_str_origin(self, expr, env):
        """"plain" si `expr` es un `algo?` usado como argumento que deja un str
        propio (como el `let x = algo?`), o None."""
        if not isinstance(expr, TryExpr):
            return None
        try:
            if self.infer(expr, env).name != "str":
                return None
        except CodegenError:
            return None
        return "plain" if self._is_fresh_try_value(expr, env) else None

    def _contenido_se_entrega(self, payload) -> bool:
        """Tipos de contenido que un Some/Ok recién armado se queda siempre como
        propios (struct, Vec, Map). Un str sigue su propia regla: lo prestado se
        copia donde se guarda."""
        return payload is not None and (
            payload.name in self.structs or payload.name in self.generic_structs
            or payload.name in (VEC_MARK, MAP_MARK))

    def _contenido_propio(self, wrapper, ty, code, env, out, pad):
        """`Some(x)` / `Ok(x)` con un struct, Vec o Map adentro es siempre dueño
        de su contenido (todo el backend supone que un Ok(...) es fresco; el
        checker lo trata como un movimiento). Según qué sea x:
          - algo fresco: tal cual;
          - una variable dueña: se le transfiere;
          - un campo de una dueña: se saca (queda vacío);
          - otra cosa (un parámetro prestado, un alias): se copia.
        La expresión entera de un `return` va por _returned_owner_names."""
        if wrapper is getattr(self, "_expr_de_return", None) or id(wrapper) in self._args_prestados:
            return code
        payload = ty.args[0] if ty.args else None
        if not self._contenido_se_entrega(payload):
            return code
        return self._valor_entregado(wrapper.expr, payload, code, env, out, pad)

    def _valor_entregado(self, inner, payload, code, env, out, pad):
        """El valor `inner` (struct, Vec o Map), ya generado como `code`,
        entregado a quien lo guarda como propio: fresco tal cual, de una dueña
        transferido, de un campo sacado, y lo prestado copiado."""
        if self._let_creates_fresh_owner(inner, marca_new_generico(inner), env):
            return code
        if isinstance(inner, Ident):
            raiz = inner.name
            if payload.name in self.structs:
                raiz = self._resolve_alias_root(raiz)
            if (raiz in self._opt_payload_of or self._is_owner(raiz)
                    or self._consume_flags.get(raiz) is not None):
                self._note_owner_transfer(inner, payload)
                return code
        elif isinstance(inner, FieldAccess):
            tomado = self._take_owned_field(inner, payload, code, env, out, pad)
            if tomado is not None:
                return tomado
        return self._clone_value_expr(payload, code)

    def _valor_compuesto_propio(self, expr, ty, env) -> bool:
        """True si `expr` (Option/Result/Chan) entrega algo ya propio que se puede
        guardar en un campo sin copiar: None, Some/Ok de algo fresco, Err (copia
        su mensaje), un Chan nuevo, o lo que en un `let` sería una dueña. Un
        literal adentro, una variable o un campo de otro struct se copian."""
        if isinstance(expr, NoneExpr) or isinstance(expr, ErrExpr):
            return True
        if isinstance(expr, (SomeExpr, OkExpr)):
            payload = ty.args[0] if ty.args else T_I32
            if not self._necesita_clonar(payload):
                return True
            if payload.name in ("Option", "Result", CHAN_MARK):
                return self._valor_compuesto_propio(expr.expr, payload, env)
            if self._contenido_se_entrega(payload):
                return True  # _contenido_propio ya lo deja propio
            if isinstance(expr.expr, Ident):
                return False
            return self._let_creates_fresh_owner(expr.expr, marca_new_generico(expr.expr), env)
        if isinstance(expr, (Ident, FieldAccess)):
            return False
        return self._let_creates_fresh_owner(expr, marca_new_generico(expr), env)

    def _option_str_fresca(self, expr, env) -> bool:
        """Un Option<str> recién armado que no es de nadie: `Some(<str fresco>)`,
        o una llamada/método que entrega uno nuevo (`v.get(i)` de un Vec<str>
        copia el texto)."""
        if isinstance(expr, SomeExpr):
            inner = expr.expr
            return self._let_creates_fresh_owner(inner, marca_new_generico(inner), env)
        if isinstance(expr, (Call, MethodCall)):
            return self._let_creates_fresh_owner(expr, marca_new_generico(expr), env)
        return False

    def _option_struct_fresca(self, expr, ty, env) -> bool:
        """Un Option<Struct> recién armado que no es de nadie: `Some(P {..})`,
        `Some(mk())` o una fn que siempre entrega uno nuevo. `Some(p)` con p una
        variable no cuenta: p sigue siendo de su dueña."""
        if not (ty.name == "Option" and ty.args and ty.args[0].name in self.structs):
            return False
        if isinstance(expr, SomeExpr):
            inner = expr.expr
            return self._let_creates_fresh_owner(inner, marca_new_generico(inner), env)
        if isinstance(expr, Call):
            return self._let_creates_fresh_owner(expr, marca_new_generico(expr), env)
        return False

    def _option_payload_is_malloc(self, expr, ty, env) -> bool:
        """True si `expr` es c.recv() de un Chan<Struct>, v.get(i)/v.pop() de un
        Vec<Struct> o m.get(k) de un Map<K,Struct>: un Option<Struct> cuyo
        contenido es una copia propia en un bloque de malloc. No incluye
        Map.remove()."""
        if not (ty.name == "Option" and ty.args and ty.args[0].name in self.structs):
            return False
        if not (isinstance(expr, MethodCall) and expr.method in ("recv", "try_recv", "get", "pop")):
            return False
        try:
            obj_ty = self.infer(expr.obj, env)
        except CodegenError:
            return False
        if expr.method in ("recv", "try_recv"):
            return obj_ty.name == CHAN_MARK
        if expr.method == "get" and obj_ty.name == MAP_MARK:
            return True  # Map.get() también clona
        return obj_ty.name == VEC_MARK

    def _let_creates_fresh_owner(self, expr, new_mark, env) -> bool:
        """True si `expr` (el lado derecho de un `let`) entrega un valor nuevo,
        del que la variable pasa a ser dueña: un struct literal, vec_new()/
        map_new(), .join() de una Task<Struct>, un `+` o un s[i] de str, una
        llamada a una fn/task que siempre entrega uno nuevo (fresh_str_fns,
        fresh_owned_fns, el contrato de un valor fn), una extern fn con retorno
        struct/str/Result, recv()/pop()/get()/replace(), `algo?` fresco, un
        Some/Ok de algo fresco... Lo demás (una variable, un campo, una llamada
        que puede devolver un alias) no es fresco: la variable no queda dueña
        (sin double free). Tiene que coincidir con el checker
        (_is_fresh_str_concat) sobre quién es dueño de qué."""
        if new_mark in (VEC_MARK, MAP_MARK, CHAN_MARK) or isinstance(expr, (StructLit, ArrayLit)):
            return True
        if isinstance(expr, FieldAccess) and self._campo_de_temporal(expr, env) is not None:
            return True  # campo sacado de un struct temporal
        if isinstance(expr, MethodCall) and expr.method == "join":
            obj_ty = self.infer(expr.obj, env)
            return obj_ty.name == TASK_MARK
        if self._is_fresh_str_call(expr):
            return True
        # una llamada directa a una fn/task que fresh_owned_fns marcó siempre
        # fresca
        if isinstance(expr, Call) and isinstance(expr.callee, Ident) and self.fresh_owned_fns.get(
            expr.callee.name, False
        ):
            return True
        if (isinstance(expr, Call) and isinstance(expr.callee, Ident)
                and getattr(expr.callee, "es_valor_fn", False)):
            # contrato del tipo fn(...): una llamada a través de un valor fn
            # devuelve siempre algo nuevo
            ret = getattr(expr.callee, "retorno_valor_fn", None)
            return ret is not None and self._is_ownable_type(ret)
        if isinstance(expr, Call) and isinstance(expr.callee, Ident):
            # una fn que devuelve siempre su parámetro k, llamada con un valor fresco
            # en k (`pasar(armar(4))`): el resultado es ese valor fresco
            own = self.fn_ownership.get(expr.callee.name)
            k = own.ret_param if own is not None else None
            if k is not None and k < len(expr.args) and \
                    self._let_creates_fresh_owner(expr.args[k], marca_new_generico(expr.args[k]), env):
                return True
            # puede devolver varias cosas, todas frescas
            if self._resultado_compuesto_fresco(expr, env):
                return True
        # una extern fn con retorno struct: siempre fresco (se arma con
        # {Name}_new a partir del struct por valor)
        if (
            isinstance(expr, Call)
            and isinstance(expr.callee, Ident)
            and expr.callee.name in self.extern_sigs
            and self.extern_sigs[expr.callee.name][1].name in self.structs
        ):
            return True
        # una extern fn con retorno str o Result<T>: siempre fresco (el str
        # llega copiado con scar_malloc; el Result se arma en la llamada)
        if (
            isinstance(expr, Call)
            and isinstance(expr.callee, Ident)
            and expr.callee.name in self.extern_sigs
            and self.extern_sigs[expr.callee.name][1].name in ("str", "Result")
        ):
            return True
        if self._is_fresh_map_remove(expr, env):
            return True
        if self._is_fresh_vec_pop(expr, env):
            return True
        if self._is_vec_replace(expr, env):
            return True  # el valor viejo sale del Vec, propio
        if self._is_fresh_vec_get_struct(expr, env):
            return True
        if isinstance(expr, MethodCall) and expr.method == "get":
            # Map.get() también devuelve una copia propia
            try:
                ty = self.infer(expr, env)
            except CodegenError:
                ty = None
            if ty is not None and self._option_payload_is_malloc(expr, ty, env):
                return True
        if self._is_fresh_result_producer(expr, env):
            return True
        # `let x = algo?`: ver _is_fresh_try_value
        if self._is_fresh_try_value(expr, env):
            return True
        # `let a = ch.recv()` de un Chan<str>/Chan<Struct>: siempre fresco, el
        # nodo trae su propia copia. La misma regla que
        # _while_let_binds_fresh_value.
        if isinstance(expr, MethodCall) and expr.method in ("recv", "try_recv"):
            obj_ty = self.infer(expr.obj, env)
            if obj_ty.name == CHAN_MARK:
                inner = obj_ty.args[0] if obj_ty.args else T_I32
                # el Vec/Map de un Chan<Vec<T>>/Chan<Map<K,V>> llega movido (también un
                # Option/Result con dueño)
                return (inner.name in self.structs or inner.name in ("str", VEC_MARK, MAP_MARK)
                        or (inner.name in ("Option", "Result") and self._campo_compuesto_con_dueno(inner)))
        if isinstance(expr, SomeExpr):
            # `Some("a" + "b")`, `Some(E {..})`, `Some(mk())`: un Option nuevo cuyo
            # contenido es fresco. No `Some("literal")` (nada que soltar)
            # ni `Some(x)` con x una variable (sigue siendo de x).
            try:
                ty = self.infer(expr, env)
            except CodegenError:
                return False
            payload = ty.args[0] if ty.args else None
            if self._contenido_se_entrega(payload):
                return True  # _contenido_propio ya lo deja propio
            if payload is None or payload.name != "str":
                return False
            return self._let_creates_fresh_owner(expr.expr, marca_new_generico(expr.expr), env)
        return self._is_fresh_str_concat_expr(expr, env)

    def _is_fresh_vec_pop(self, expr, env) -> bool:
        """True si `expr` es .pop() de un Vec cuyo elemento tiene dueño (struct,
        str, Vec, Option con dueño): pop() baja len antes de envolver el valor,
        así que el Vec deja de ser su dueño (free solo recorre [0, len)) y el
        Some(...) no tiene otra dueña que la variable que lo recibe."""
        inner_ty = elemento_de_pop(expr, lambda e: self.infer(e, env))
        if inner_ty is None:
            return False
        # Vec<Vec<T>> (el de adentro, movido) y Vec<Option<T>> con dueño
        return (inner_ty.name in self.structs or inner_ty.name in ("str", VEC_MARK, MAP_MARK)
                or (inner_ty.name in ("Option", "Result") and self._campo_compuesto_con_dueno(inner_ty)))

    def _is_vec_replace(self, expr, env) -> bool:
        """`v.replace(i, x)`: devuelve el elemento que estaba, que ya no es parte
        del Vec; quien lo recibe es su dueño."""
        if not (isinstance(expr, MethodCall) and expr.method == "replace"):
            return False
        try:
            return self.infer(expr.obj, env).name == VEC_MARK
        except CodegenError:
            return False

    def _is_fresh_vec_get_struct(self, expr, env) -> bool:
        """True si `expr` es .get() de un Vec<Struct> (o de un Vec/Map cuyo
        elemento se clona): get() devuelve una copia propia, sin alias con el
        contenedor (el slot no tiene una dirección estable: un push puede
        reallocar el buffer)."""
        if not (isinstance(expr, MethodCall) and expr.method == "get"):
            return False
        obj_ty = self.infer(expr.obj, env)
        if obj_ty.name == MAP_MARK:
            # Map<K,Vec<T>>.get() y Map<K,Map<..>>.get() clonan lo guardado (propio)
            val_ty = obj_ty.args[1] if len(obj_ty.args) > 1 else T_I32
            return val_ty.name in (VEC_MARK, MAP_MARK) or (
                val_ty.name in ("Option", "Result") and self._campo_compuesto_con_dueno(val_ty))
        if obj_ty.name != VEC_MARK:
            return False
        inner_ty = obj_ty.args[0] if obj_ty.args else T_I32
        # Vec<Vec<T>>.get() clona el de adentro; también Vec<Option<T>> con dueño
        return (inner_ty.name in self.structs or inner_ty.name in (VEC_MARK, MAP_MARK)
                or (inner_ty.name in ("Option", "Result") and self._campo_compuesto_con_dueno(inner_ty)))

    def _is_fresh_map_remove(self, expr, env) -> bool:
        """True si `expr` es .remove() de un Map cuyo valor tiene dueño (struct,
        str, Vec, Map): remove() deja una tumba en la entrada antes de devolver
        el valor, así que el Map deja de ser su dueño (free solo recorre las
        entradas ocupadas) y el Some(...) no tiene otra dueña. El Map siempre
        guarda un str propio (set() lo copia), así que un str sacado también es
        propio."""
        if not (isinstance(expr, MethodCall) and expr.method == "remove"):
            return False
        obj_ty = self.infer(expr.obj, env)
        if obj_ty.name != MAP_MARK:
            return False
        val_ty = obj_ty.args[1] if len(obj_ty.args) > 1 else T_I32
        # también Map<K,Vec<T>> (remove entrega el Vec guardado) y un Map
        return (val_ty.name in self.structs or val_ty.name in ("str", VEC_MARK, MAP_MARK)
                or (val_ty.name in ("Option", "Result") and self._campo_compuesto_con_dueno(val_ty)))

    def _is_fresh_chan_recv(self, expr, env) -> bool:
        """`c.recv()`/`c.try_recv()` entrega lo que llegó por el canal, sin otro
        dueño: un str (el nodo lo copió), un struct, un Vec/Map o un Option/
        Result con dueño."""
        if not (isinstance(expr, MethodCall) and expr.method in ("recv", "try_recv")):
            return False
        try:
            obj_ty = self.infer(expr.obj, env)
        except CodegenError:
            return False
        if obj_ty.name != CHAN_MARK:
            return False
        inner = obj_ty.args[0] if obj_ty.args else T_I32
        return (inner.name in self.structs or inner.name in ("str", VEC_MARK, MAP_MARK)
                or (inner.name in ("Option", "Result") and self._campo_compuesto_con_dueno(inner)))

    def _option_fresh_owned_kind(self, expr, env):
        """Si `expr` es un get()/pop()/remove() que entrega un Option fresco (ver
        las funciones de arriba), el nombre con el que se libera lo de adentro:
        'str' o el nombre de un struct. Si no, None. Sirve para un Option fresco
        usado directo, sin variable (`print(v.get(i))`)."""
        if (self._is_fresh_vec_get_struct(expr, env) or self._is_fresh_vec_pop(expr, env)
                or self._is_fresh_map_remove(expr, env) or self._is_fresh_chan_recv(expr, env)):
            # el tipo de lo que trae el Option (en un Map no es el primer argumento:
            # ese es la clave)
            opt_ty = self.infer(expr, env)
            return (opt_ty.args[0] if opt_ty.args else T_I32).name
        return None

    def _while_let_binds_fresh_value(self, expr, env) -> bool:
        """Como _let_creates_fresh_owner, para `while let Some(x) = expr`: True si
        x queda dueña de lo que trae. recv() de un Chan<str>/Chan<Struct> (el
        nodo trae un valor propio), pop()/get() frescos, una fn que siempre
        devuelve un Option nuevo, una llamada a través de un valor fn, y un
        Chan<Vec>/Chan<Map>."""
        if (isinstance(expr, Call) and isinstance(expr.callee, Ident)
                and getattr(expr.callee, "es_valor_fn", False)):
            # `while let Some(x) = f()` con f un valor fn: el Option que devuelve es
            # nuevo (contrato del tipo fn)
            ret = getattr(expr.callee, "retorno_valor_fn", None)
            return ret is not None and ret.name == "Option" and self._necesita_clonar(ret)
        if (isinstance(expr, Call) and isinstance(expr.callee, Ident)
                and not getattr(expr.callee, "es_valor_fn", False)
                and expr.callee.name in self.fn_sigs
                and self.fn_sigs[expr.callee.name][1].name == "Option"):
            # `while let Some(x) = f()` con una fn que siempre entrega un Option
            # nuevo (`return v.pop()`, `return Some(fresco)`): x es de la vuelta y se
            # libera al final
            return self.fresh_owned_fns.get(expr.callee.name, False)
        if isinstance(expr, MethodCall) and expr.method == "pop":
            # `while let Some(x) = v.pop()`
            return self._is_fresh_vec_pop(expr, env)
        if isinstance(expr, MethodCall) and expr.method == "get":
            # `while let Some(x) = v.get(i)` de un Vec<Struct> (una copia)
            return self._is_fresh_vec_get_struct(expr, env)
        if not (isinstance(expr, MethodCall) and expr.method in ("recv", "try_recv")):
            return False
        obj_ty = self.infer(expr.obj, env)
        if obj_ty.name != CHAN_MARK:
            return False
        inner = obj_ty.args[0] if obj_ty.args else T_I32
        # Chan<Vec<T>>/Chan<Map<K,V>>: el Vec/Map llegó movido (también un
        # Option/Result con dueño)
        return (inner.name in self.structs or inner.name in ("str", VEC_MARK, MAP_MARK)
                or (inner.name in ("Option", "Result") and self._campo_compuesto_con_dueno(inner)))
