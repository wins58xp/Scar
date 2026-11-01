"""Mixin Expresiones de Codegen (paso C6): gen_expr e infer. Cada expresión
de SCAR a una expresión de C (con las sentencias previas en out cuando hace
falta, como en ?) y su tipo.
"""

from parser import (marca_new_generico, 
    NumLit, StrLit, BoolLit, Ident, BinOp, UnaryOp, Call, FieldAccess, IndexExpr,
    StructLit, ArrayLit, TryExpr, OkExpr, ErrExpr, SomeExpr, NoneExpr, SpawnExpr,
    MethodCall,
)
from types_ import (
    TypeAnn, T_I32, T_I64, T_F64, T_STR, T_BOOL, T_VOID, int_literal_type,
    numeric_result,
)

from . import runtime as runtime_c
from .comun import (
    panic_c,
    _SIGUE,
    BIN_OPS, BITS_OPS, BOOL_OPS, BUILTIN_SIGS, C_BOOL_OP, CHAN_MARK, CodegenError,
    COMPARISON_OPS, FILE_MARK, FN_MARK, _LIBM_C, LISTENER_MARK, literal_c, MAP_MARK,
    PIPE_MARK, SOCKET_MARK, TASK_MARK, VEC_MARK,
)


class Expresiones:
    def _args_devueltos_frescos(self, fn_name, expr, env):
        """Los índices de los argumentos frescos que `fn_name` puede devolver como
        el mismo objeto, cuando puede devolver más de uno (`fn mayor(a: Punto,
        b: Punto) -> Punto`). None si no aplica. Cada uno va a un temporal, el
        resultado a otro, y al terminar la sentencia se suelta cada temporal que
        no es el resultado (como el envoltorio de una export fn)."""
        if (fn_name is None or fn_name not in self.fn_sigs or fn_name in self.task_sigs
                or fn_name in self.generic_fns or fn_name in self.extern_sigs):
            return None
        ret_ty = self.fn_sigs[fn_name][1]
        if ret_ty is None or self._struct_free_fn(ret_ty) is None:
            return None
        own = self.fn_ownership.get(fn_name)
        if own is None or own.ret_set is None or len(own.ret_set) < 2:
            return None
        consumidos = self.consumed_params.get(fn_name, ())
        idx = []
        for atom in own.ret_set:
            if isinstance(atom, tuple):
                k = atom[1]
                if k < len(expr.args) and k not in consumidos and (
                        k in self._transferidos.get(id(expr), ())
                        or self._let_creates_fresh_owner(expr.args[k], marca_new_generico(expr.args[k]), env)):
                    idx.append(k)
        return sorted(idx) or None

    def _resultado_compuesto_fresco(self, expr, env) -> bool:
        """`f(...)` puede devolver varias cosas y todas son frescas (un valor
        nuevo o un argumento fresco): el resultado, sea cuál sea, no tiene otra
        dueña."""
        if not (isinstance(expr, Call) and isinstance(expr.callee, Ident)):
            return False
        idx = self._args_devueltos_frescos(expr.callee.name, expr, env)
        if idx is None:
            return False
        own = self.fn_ownership[expr.callee.name]
        return all(atom == "F" or (isinstance(atom, tuple) and atom[1] in idx) for atom in own.ret_set)

    # ---- inferencia de tipos local ----
    def infer(self, expr, env, expected_ty=None):
        # todo tipo que sale de acá está en forma canónica. Mientras
        # se genera una expresión, el tipo de un BinOp no cambia: se guarda, si
        # no a + b + c + ... sería cuadrático (50.000 sumandos no terminarían).
        cache = self._infer_cache
        if cache is not None and isinstance(expr, BinOp):
            # la entrada guarda expr y env: mientras están en la caché sus id() no
            # se pueden reusar para otro nodo o entorno
            clave = (id(expr), id(env), repr(expected_ty))
            r = cache.get(clave)
            if r is None or r[0] is not expr or r[1] is not env:
                r = cache[clave] = (expr, env, self._canon(self._infer_impl(expr, env, expected_ty)))
            return r[2]
        return self._canon(self._infer_impl(expr, env, expected_ty))

    @staticmethod
    def _adentro_esperado(expected_ty, marca):
        """El T de un Option<T>/Result<T> esperado, para lo de adentro de un
        Some/Ok; None si no se espera ese envoltorio."""
        if expected_ty is not None and expected_ty.name == marca and expected_ty.args:
            return expected_ty.args[0]
        return None

    # _infer_impl: tipo de nodo -> el método que lo genera. Ningún nodo
    # hereda de otro, así que buscar type(expr) equivale a la cadena de
    # isinstance que había.
    _DESPACHO_INFER = {
        NumLit: "_infer_num_lit",
        StrLit: "_infer_str_lit",
        BoolLit: "_infer_bool_lit",
        Ident: "_infer_ident",
        NoneExpr: "_infer_none_expr",
        SomeExpr: "_infer_some_expr",
        OkExpr: "_infer_ok_expr",
        ErrExpr: "_infer_err_expr",
        TryExpr: "_infer_try_expr",
        UnaryOp: "_infer_unary_op",
        BinOp: "_infer_bin_op",
        Call: "_infer_call",
        ArrayLit: "_infer_array_lit",
        StructLit: "_infer_struct_lit",
        FieldAccess: "_infer_field_access",
        IndexExpr: "_infer_index_expr",
        SpawnExpr: "_infer_spawn_expr",
        MethodCall: "_infer_method_call",
    }

    def _infer_impl(self, expr, env, expected_ty=None):
        metodo = self._DESPACHO_INFER.get(type(expr))
        if metodo is None:
            raise CodegenError(f"expresión no soportada por el backend de C: {type(expr).__name__}")
        return getattr(self, metodo)(expr, env, expected_ty)

    def _infer_num_lit(self, expr, env, expected_ty):
        if isinstance(expr.value, float):
            return T_F64
        return int_literal_type(expr.value) or T_I64

    def _infer_str_lit(self, expr, env, expected_ty):
        return T_STR

    def _infer_bool_lit(self, expr, env, expected_ty):
        return T_BOOL

    def _infer_ident(self, expr, env, expected_ty):
        if expr.name not in env:
            # una fn top-level usada como valor ('let h = duplicar'): su tipo es el
            # FN_MARK que le da el checker, params + [retorno]
            if expr.name in self.fn_sigs:
                params, ret = self.fn_sigs[expr.name]
                return TypeAnn(FN_MARK, list(params) + [ret])
            raise CodegenError(f"variable no declarada: {expr.name}")
        return env[expr.name]

    def _infer_none_expr(self, expr, env, expected_ty):
        # None no trae un valor del que inferir T: se usa el tipo esperado (el de
        # un `let` anotado, el retorno de la fn, el parámetro de la llamada) si es
        # un Option<T> concreto; si no, Option<i32>, como en el checker.
        if expected_ty is not None and expected_ty.name == "Option" and expected_ty.args:
            return expected_ty
        return TypeAnn("Option", [T_I32])

    def _infer_some_expr(self, expr, env, expected_ty):
        # lo de adentro toma el T del Option esperado (Some(Err("x")) donde va un
        # Option<Result<str>>), como en el checker
        return TypeAnn("Option", [self._tipo_en_su_lugar(
            expr.expr, env, self._adentro_esperado(expected_ty, "Option"))])

    def _infer_ok_expr(self, expr, env, expected_ty):
        return TypeAnn("Result", [self._tipo_en_su_lugar(
            expr.expr, env, self._adentro_esperado(expected_ty, "Result"))])

    def _infer_err_expr(self, expr, env, expected_ty):
        self.infer(expr.expr, env)  # se evalúa; el payload de error es str fijo
        # el tipo esperado manda, con el mismo criterio que el checker
        if expected_ty is not None and expected_ty.name == "Result" and expected_ty.args:
            return expected_ty
        if self.cur_ret_ty is not None and self.cur_ret_ty.name == "Result":
            return TypeAnn("Result", self.cur_ret_ty.args)
        return TypeAnn("Result", [T_I32])

    def _infer_try_expr(self, expr, env, expected_ty):
        inner_ty = self.infer(expr.expr, env)
        if inner_ty.name != "Result":
            raise CodegenError(f"'?' requiere un Result, se dio {inner_ty!r}")
        return inner_ty.args[0] if inner_ty.args else T_I32

    def _infer_unary_op(self, expr, env, expected_ty):
        if expr.literal_plegado is not None:
            return int_literal_type(expr.literal_plegado) or T_I64
        ty = self.infer(expr.expr, env)
        if expr.op == "not":
            return T_BOOL
        return ty  # "-"

    def _infer_bin_op(self, expr, env, expected_ty):
        if expr.op in BOOL_OPS:
            return T_BOOL
        if expr.op not in BIN_OPS:
            raise CodegenError(f"operador no soportado por el backend de C: {expr.op}")
        if expr.op in COMPARISON_OPS:
            return T_BOOL
        # Aritmética: f64 si cualquiera de los dos lados es f64; un `+` de str
        # sale del izquierdo. Tomar solo el tipo del izquierdo hacía que `n / d`
        # con n: i32 y d: f64 usara la división entera. Copia de la regla del
        # checker.
        left_ty = self.infer(expr.left, env)
        if expr.op == "+" and left_ty == T_STR:
            return T_STR
        if expr.op in ("<<", ">>"):
            return left_ty  # el tipo de la izquierda
        right_ty = self.infer(expr.right, env)
        # la misma regla que el checker (types_.numeric_result)
        if left_ty.is_numeric() and right_ty.is_numeric():
            return numeric_result(left_ty, right_ty) or T_I64
        return T_F64 if (left_ty == T_F64 or right_ty == T_F64) else T_I32

    def _infer_call(self, expr, env, expected_ty):
        # una llamada a través de una variable o parámetro que guarda un valor fn
        # ('h(3)' tras 'let h = duplicar'). Va primero: un parámetro 'duplicar:
        # fn(...)' tapa a la fn top-level del mismo nombre, como en C.
        if isinstance(expr.callee, Ident) and expr.callee.name in env:
            local_ty = env[expr.callee.name]
            if local_ty.name == FN_MARK and local_ty.args:
                return local_ty.args[-1]
        if isinstance(expr.callee, Ident) and expr.callee.name in ("abs", "min", "max") \
                and expr.callee.name not in env:
            # abs es del tipo de su argumento; min/max siguen la regla de una suma
            # (types_.numeric_result)
            tys = [self.infer(a, env) for a in expr.args]
            if expr.callee.name == "abs":
                return tys[0]
            return numeric_result(tys[0], tys[1]) or T_F64
        if isinstance(expr.callee, Ident) and expr.callee.name in BUILTIN_SIGS:
            return BUILTIN_SIGS[expr.callee.name][1]
        if isinstance(expr.callee, Ident) and expr.callee.name in self.extern_sigs:
            return self.extern_sigs[expr.callee.name][1]
        if isinstance(expr.callee, Ident) and expr.callee.name in self.generic_fns:
            # fn genérica: el tipo de retorno de la instancia de esta llamada (la
            # genera o la reusa)
            concrete_args = self._generic_fn_concrete_args(expr, env)
            mangled = self._ensure_generic_fn_instance(expr.callee.name, concrete_args)
            return self.fn_sigs[mangled][1]
        if not isinstance(expr.callee, Ident) or expr.callee.name not in self.fn_sigs:
            raise CodegenError(f"llamada no soportada por el backend de C: {expr.callee}")
        return self.fn_sigs[expr.callee.name][1]

    def _infer_array_lit(self, expr, env, expected_ty):
        return TypeAnn(VEC_MARK, [expr.tipo_elem])

    def _infer_struct_lit(self, expr, env, expected_ty):
        if expr.name in self.generic_structs:
            # StructLit genérico: TypeAnn(nombre, args concretos), como en el checker,
            # así `let c = Caja{valor: 42}` deja a c con su T resuelto
            return TypeAnn(expr.name, self._generic_struct_concrete_args(expr, env, expected_ty))
        if expr.name not in self.structs:
            raise CodegenError(f"struct no definido: {expr.name}")
        return TypeAnn(expr.name)

    def _infer_field_access(self, expr, env, expected_ty):
        obj_ty = self.infer(expr.obj, env)
        if obj_ty.name in self.generic_structs:
            # campo de un struct genérico: el tipo declarado del campo con los T
            # sustituidos por los args de obj_ty, como en el checker
            decl = self.generic_structs[obj_ty.name]
            if expr.field not in decl["fields"]:
                raise CodegenError(f"'{obj_ty.name}' no tiene campo '{expr.field}'")
            return self._substitute_generic_field_type(
                decl["fields"][expr.field], decl["type_params"], obj_ty.args
            )
        if obj_ty.name not in self.structs:
            raise CodegenError(
                f"'.{expr.field}' sobre un valor de tipo {obj_ty!r}, que no es struct"
            )
        fields = self.structs[obj_ty.name]
        if expr.field not in fields:
            raise CodegenError(f"'{obj_ty.name}' no tiene campo '{expr.field}'")
        return fields[expr.field]

    def _infer_index_expr(self, expr, env, expected_ty):
        obj_ty = self.infer(expr.obj, env)
        if obj_ty != T_STR:
            raise CodegenError(
                f"'[...]' sobre un valor de tipo {obj_ty!r}, que no es str"
            )
        return T_STR

    def _infer_spawn_expr(self, expr, env, expected_ty):
        call = expr.call
        if not isinstance(call, Call) or not isinstance(call.callee, Ident):
            raise CodegenError("'spawn' requiere una llamada directa a una task")
        name = call.callee.name
        if name not in self.task_sigs:
            raise CodegenError(f"'spawn' requiere una 'task', '{name}' no lo es")
        _, ret = self.task_sigs[name]
        # spawn: TypeAnn(TASK_MARK, [retorno, TypeAnn(nombre de la task)]), como
        # en el checker. El segundo elemento no es un tipo: lleva el nombre de la
        # task, que inject_chan() necesita para elegir el slot. Se propaga solo por
        # el env (let h = spawn Tarea(...)).
        return TypeAnn(TASK_MARK, [ret, TypeAnn(name)])

    def _infer_method_call(self, expr, env, expected_ty):
        obj_ty = self.infer(expr.obj, env)
        if obj_ty.name == TASK_MARK:
            if expr.method != "join":
                raise CodegenError(f"Task no tiene método '.{expr.method}()' en el backend de C")
            return obj_ty.args[0] if obj_ty.args else T_VOID
        if obj_ty.name == CHAN_MARK:
            inner = obj_ty.args[0] if obj_ty.args else T_I32
            if expr.method == "send":
                return T_VOID
            if expr.method in ("recv", "try_recv"):
                return TypeAnn("Option", [inner])
            if expr.method == "close":
                return T_VOID
            if expr.method in ("sender", "receiver"):
                return obj_ty
            raise CodegenError(f"Chan no tiene método '.{expr.method}()' en el backend de C")
        if obj_ty.name == PIPE_MARK:
            if expr.method not in ("read_fd", "write_fd"):
                raise CodegenError(f"Pipe no tiene método '.{expr.method}()' en el backend de C")
            return T_I32
        if obj_ty.name == FILE_MARK:
            if expr.method == "read_all":
                return TypeAnn("Result", [T_STR])
            if expr.method == "read_bytes":
                return TypeAnn("Result", [TypeAnn(VEC_MARK, [T_I32])])
            if expr.method in ("write", "write_bytes"):
                return TypeAnn("Result", [T_I32])
            if expr.method == "close":
                return T_VOID
            raise CodegenError(f"File no tiene método '.{expr.method}()' en el backend de C")
        if obj_ty.name == SOCKET_MARK:
            if expr.method == "read":
                return TypeAnn("Result", [T_STR])
            if expr.method == "read_bytes":
                return TypeAnn("Result", [TypeAnn(VEC_MARK, [T_I32])])
            if expr.method in ("write", "write_bytes"):
                return TypeAnn("Result", [T_I32])
            if expr.method == "close":
                return T_VOID
            raise CodegenError(f"Socket no tiene método '.{expr.method}()' en el backend de C")
        if obj_ty.name == LISTENER_MARK:
            if expr.method == "accept":
                return TypeAnn("Result", [TypeAnn(SOCKET_MARK)])
            if expr.method == "close":
                return T_VOID
            raise CodegenError(f"Listener no tiene método '.{expr.method}()' en el backend de C")
        if obj_ty.name in ("Result", "Option"):
            if expr.method in ("is_ok", "is_err", "is_some", "is_none"):
                return T_BOOL
            if expr.method == "err":
                return T_STR
            if expr.method == "unwrap_or":
                return obj_ty.args[0] if obj_ty.args else T_I32
            raise CodegenError(f"{obj_ty.name} no tiene método '.{expr.method}()' en el backend de C")
        if obj_ty.name == VEC_MARK:
            inner = obj_ty.args[0] if obj_ty.args else T_I32
            if expr.method == "push":
                return T_VOID
            if expr.method in ("get", "pop"):
                return TypeAnn("Option", [inner])
            if expr.method == "replace":
                return inner
            if expr.method == "len":
                return T_I32
            raise CodegenError(f"Vec no tiene método '.{expr.method}()' en el backend de C")
        if obj_ty.name == MAP_MARK:
            key_ty = obj_ty.args[0] if obj_ty.args else T_I32
            val_ty = obj_ty.args[1] if len(obj_ty.args) > 1 else T_I32
            if expr.method == "set":
                return T_VOID
            if expr.method in ("get", "remove"):
                return TypeAnn("Option", [val_ty])
            if expr.method == "len":
                return T_I32
            raise CodegenError(f"Map no tiene método '.{expr.method}()' en el backend de C")
        if obj_ty.name == "str":
            if expr.method == "len":
                return T_I32
            if expr.method in ("contains", "starts_with", "ends_with"):
                return T_BOOL
            raise CodegenError(f"str no tiene método '.{expr.method}()' en el backend de C")
        raise CodegenError(
            f"'.{expr.method}()' sobre {obj_ty!r} todavía no soportado por el "
            "backend de C."
        )

    def _tipo_en_su_lugar(self, expr, env, expected_ty=None):
        """El tipo de lo de adentro de un Some/Ok recién armado, contando la
        ampliación que marcó el checker (i32 -> i64 o f64): `Some(5)` donde se
        espera Option<i64> arma un Option_i64. Solo elige el tipo del envoltorio:
        la expresión de adentro se genera con su propio tipo."""
        if expr.promover_i64:
            return T_I64
        if expr.promover_f64:
            return T_F64
        return self.infer(expr, env, expected_ty=expected_ty)

    def _literal_entero_c(self, v):
        """Un literal entero de C con el tipo de SCAR (i32 si cabe, si no i64). Los
        mínimos se escriben con la macro: `-2147483648` en C es el long
        2147483648 negado."""
        if v == -2147483648:
            return "INT32_MIN"
        if v == -9223372036854775808:
            return "INT64_MIN"
        if int_literal_type(v) == T_I32:
            return repr(v)
        return f"INT64_C({v})"

    def _gen_bits_i64(self, expr, l, r):
        """Operadores de bits con resultado i64, como _gen_bits con 64 bits: & | ^
        con un lado i32 lo amplían; un corrimiento fuera de 0..63 es un panic;
        `<<` sobre uint64_t."""
        self.needs_i64 = True
        if expr.op in ("&", "|", "^"):
            return f"((int64_t)({l}) {expr.op} (int64_t)({r}))"
        k = expr.right.value if isinstance(expr.right, NumLit) else None
        if isinstance(k, int) and not isinstance(k, bool) and 0 <= k <= 63:
            if expr.op == "<<":
                return f"((int64_t)((uint64_t)({l}) << {k}))"
            return f"scar_lsar_k({l}, {k})"
        return f"{'scar_lshl' if expr.op == '<<' else 'scar_lshr'}({l}, {r})"

    def _gen_bits(self, expr, l, r):
        """Operadores de bits sobre i32, como el intérprete (_bits): 32 bits en
        complemento a dos; `<<` sobre uint32_t (correr un negativo a la izquierda
        es comportamiento indefinido en C); `>>` aritmético sin depender del
        compilador; un corrimiento fuera de 0..31 es un panic. Con un literal
        0..31 no hay chequeo."""
        if expr.op in ("&", "|", "^"):
            return f"({l} {expr.op} {r})"
        k = expr.right.value if isinstance(expr.right, NumLit) else None
        if isinstance(k, int) and not isinstance(k, bool) and 0 <= k <= 31:
            if expr.op == "<<":
                return f"((int32_t)((uint32_t)({l}) << {k}))"
            self._usa_sar_k = True
            return f"scar_sar_k({l}, {k})"
        self.needs_shift = True
        return f"{'scar_shl' if expr.op == '<<' else 'scar_shr'}({l}, {r})"

    # ---- expresiones ----
    # out/pad: las sentencias que una expresión necesita emitir antes de su
    # punto de uso (un `?`, un temporal), ver el docstring del módulo.
    def _gen_new_con_tipo(self, expr, ty, env, out, pad):
        """vec_new()/map_new()/chan_new() con el tipo del lugar donde van (como
        _infer del checker); None si no aplica."""
        marca = marca_new_generico(expr)
        if marca is None or ty is None or ty.name != marca or not ty.args:
            return None
        self.c_type(ty)
        if marca == MAP_MARK:
            if len(ty.args) < 2:
                return None
            return f"scar_map_new_{ty.args[0].name}_{self._mangled_name(ty.args[1])}()"
        cap = self.gen_expr(expr.args[0], env, out, pad, expected_ty=T_I32) if expr.args else "0"
        prefijo = "scar_chan_new_" if marca == CHAN_MARK else "scar_vec_new_"
        return f"{prefijo}{self._mangled_name(ty.args[0])}({cap})"

    def gen_expr(self, expr, env, out, pad, expected_ty=None):
        # las bajas del registro de vivas (una dueña que se mueve dentro de esta
        # expresión, ver _unmark_owner) se escriben en el `out` de la expresión,
        # antes de la línea que la usa
        if expected_ty is not None and isinstance(expr, Call):
            code = self._gen_new_con_tipo(expr, expected_ty, env, out, pad)
            if code is not None:
                return code
        prev = getattr(self, "_vivos_out", None)
        self._vivos_out = (out, pad)
        afuera = self._infer_cache is None
        if afuera:
            self._infer_cache = {}
        try:
            return self._gen_expr_impl(expr, env, out, pad, expected_ty)
        finally:
            self._vivos_out = prev
            if afuera:
                self._infer_cache = None

    # _gen_expr_impl: tipo de nodo -> el método que lo genera. Ningún nodo
    # hereda de otro, así que buscar type(expr) equivale a la cadena de
    # isinstance que había.
    _DESPACHO_EXPRESION = {
        NumLit: "_gen_num_lit",
        StrLit: "_gen_str_lit",
        BoolLit: "_gen_bool_lit",
        Ident: "_gen_ident",
        NoneExpr: "_gen_none_expr",
        SomeExpr: "_gen_some_expr",
        OkExpr: "_gen_ok_expr",
        ErrExpr: "_gen_err_expr",
        TryExpr: "_gen_try_expr",
        UnaryOp: "_gen_unary_op",
        BinOp: "_gen_bin_op",
        Call: "_gen_call",
        FieldAccess: "_gen_field_access",
        IndexExpr: "_gen_index_expr",
        ArrayLit: "_gen_array_lit_expr",
        StructLit: "_gen_struct_lit",
        SpawnExpr: "_gen_spawn_expr",
        MethodCall: "_gen_method_call_expr",
    }

    def _gen_expr_impl(self, expr, env, out, pad, expected_ty=None):
        metodo = self._DESPACHO_EXPRESION.get(type(expr))
        if metodo is None:
            raise CodegenError(f"expresión no soportada por el backend de C: {type(expr).__name__}")
        return getattr(self, metodo)(expr, env, out, pad, expected_ty)

    def _gen_num_lit(self, expr, env, out, pad, expected_ty):
        return self._literal_entero_c(expr.value) if not isinstance(expr.value, float) else repr(expr.value)

    def _gen_str_lit(self, expr, env, out, pad, expected_ty):
        return literal_c(expr.value)

    def _gen_bool_lit(self, expr, env, out, pad, expected_ty):
        return "true" if expr.value else "false"

    def _gen_ident(self, expr, env, out, pad, expected_ty):
        if expr.verificar_movida:
            self._verificar_movida(expr, out, pad)
        # lado derecho de un `let` que sombrea a `expr.name`: en C, dentro de
        # `T x = <rhs>;` la x ya es la nueva (sin inicializar), así que el valor
        # viejo se lee de su temporal
        if expr.name in self._shadow_rhs:
            return self._shadow_rhs[expr.name]
        if expr.name in self.fn_sigs and expr.name not in env and expr.name not in self.task_sigs:
            # una fn usada como valor: entra en la tabla de nombres (print)
            c_fn = self._envoltorio_fn_valor(expr.name)
            self._fns_como_valor[c_fn] = self.nombres.mostrar(expr.name)
            return c_fn
        return expr.name

    def _gen_none_expr(self, expr, env, out, pad, expected_ty):
        ty = self.infer(expr, env, expected_ty=expected_ty)
        return f"{self.c_type(ty)}_None()"

    def _gen_some_expr(self, expr, env, out, pad, expected_ty):
        return self._gen_envuelto(expr, env, out, pad, expected_ty, "Some")

    def _gen_ok_expr(self, expr, env, out, pad, expected_ty):
        return self._gen_envuelto(expr, env, out, pad, expected_ty, "Ok")

    def _gen_envuelto(self, expr, env, out, pad, expected_ty, ctor):
        """Some(x) / Ok(x): el contenido con el tipo que espera el envoltorio, y
        propio (_contenido_propio)."""
        ty = self.infer(expr, env, expected_ty)
        c_name = self.c_type(ty)
        inner_code = self.gen_expr(expr.expr, env, out, pad, ty.args[0])
        inner_code = self._contenido_propio(expr, ty, inner_code, env, out, pad)
        return f"{c_name}_{ctor}({inner_code})"

    def _gen_err_expr(self, expr, env, out, pad, expected_ty):
        # Err(...): el .err es siempre un str propio (nunca un literal ni un alias
        # de otra variable), porque al liberar un Result se libera su .err. Se
        # copia con scar_str_concat(inner, "").
        ty = self.infer(expr, env, expected_ty)
        c_name = self.c_type(ty)
        inner_code = self.gen_expr(expr.expr, env, out, pad)
        self.needs_str_concat = True
        if self._is_fresh_str_concat_expr(expr.expr, env) or self._is_fresh_str_call(expr.expr):
            # ya es un str nuevo sin otra dueña: se entrega tal cual (copiarlo perdía
            # el original: `Err(r + ": " + x)`)
            return f"{c_name}_Err({inner_code})"
        return f'{c_name}_Err(scar_str_concat({inner_code}, ""))'

    def _gen_try_expr(self, expr, env, out, pad, expected_ty):
        inner_ty = self.infer(expr.expr, env)
        if inner_ty.name != "Result":
            raise CodegenError(f"'?' requiere un Result, se dio {inner_ty!r}")
        c_name = self.c_type(inner_ty)
        inner_code = self.gen_expr(expr.expr, env, out, pad)
        tmp = self._new_tmp()
        out.append(f"{pad}{c_name} {tmp} = {inner_code};")
        out.append(f"{pad}if ({tmp}.tag != 1) {{")
        err_c_name = self.c_type(self.cur_ret_ty)
        # El `?` es un `return` anticipado: como cualquier return, libera lo que
        # sigue vivo en los scopes abiertos, salvo el Result que se desenvuelve,
        # cuyo .err pasa al Err que se devuelve.
        exclude = {expr.expr.name} if isinstance(expr.expr, Ident) else set()
        live = self._live_owners_at_return(exclude)
        if live:
            self._emit_owner_frees(live, env, out, pad + "    ")
        # también los temporales de la sentencia que ya se crearon (en
        # `f(g(x) + "a")?`, el str de g y la concatenación): el camino normal los
        # libera al terminar la sentencia, y el Err no llega ahí
        if self.pending_expr_temps:
            self._emit_pending_temp_frees(list(self.pending_expr_temps), out, pad + "    ")
        out.append(f"{pad}    return {err_c_name}_Err({tmp}.err);")
        out.append(f"{pad}}}")
        return f"{tmp}.value"

    def _gen_unary_op(self, expr, env, out, pad, expected_ty):
        if expr.literal_plegado is not None:
            # `-N` con N literal es un literal negativo con su tipo, como en el
            # checker. INT32_MIN/INT64_MIN se escriben con la macro: en C,
            # `-2147483648` es el long 2147483648 negado.
            return f"({self._literal_entero_c(expr.literal_plegado)})"
        code = self.gen_expr(expr.expr, env, out, pad)
        if expr.op == "-" and not isinstance(expr.expr, NumLit):
            neg_ty = self.infer(expr.expr, env).name
            if neg_ty in ("i32", "i64"):
                # -INT32_MIN no entra en un i32 (UB en C), ni -INT64_MIN en un i64: panic
                if neg_ty == "i64":
                    self.needs_i64 = True
                    return f"scar_lneg({code})"
                self.needs_iarith = True
                return f"scar_ineg({code})"
        c_op = "!" if expr.op == "not" else expr.op
        return f"({c_op}{code})"

    def _gen_bin_op_logico(self, expr, env, out, pad, expected_ty):
        # Cortocircuito: el lado derecho se evalúa solo si hace falta. Si deja
        # sentencias previas (un temporal), van dentro de un if: `i < n and
        # ord(s[i]) > 0` no puede evaluar s[i] si i < n es falso.
        l = self.gen_expr(expr.left, env, out, pad)
        marca = len(self.pending_expr_temps)
        # lo que el lado derecho le transfiere a otro (`c and f(v)` con f que se
        # queda con v) solo pasa si se evalúa; si no, la dueña sigue acá y se
        # libera en el else
        duenas_antes = [(f, n, o) for f in self.owner_stack for n, o in f.items()]
        flags_antes, takes_antes = len(self._pending_flag_clears), len(self._pending_takes)
        r_out = []
        r = self.gen_expr(expr.right, env, r_out, pad + "    ")
        nuevos = self.pending_expr_temps[marca:]
        transferidas = {n: o for f, n, o in duenas_antes if n not in f}
        flags_r = self._pending_flag_clears[flags_antes:]
        takes_r = self._pending_takes[takes_antes:]
        if not r_out and not nuevos and not transferidas and not flags_r and not takes_r:
            return f"({l} {C_BOOL_OP[expr.op]} {r})"
        del self.pending_expr_temps[marca:]
        del self._pending_flag_clears[flags_antes:]
        del self._pending_takes[takes_antes:]
        t = self._new_tmp()
        out.append(f"{pad}bool {t} = ({l});")
        out.append(f"{pad}if ({t if expr.op == 'and' else '!' + t}) {{")
        out.extend(r_out)
        out.append(f"{pad}    {t} = ({r});")
        guardados = self.pending_expr_temps
        self.pending_expr_temps = nuevos
        self._flush_pending_expr_temps(out, pad + "    ")
        self.pending_expr_temps = guardados
        for flag in dict.fromkeys(flags_r):
            out.append(f"{pad}    {flag} = false;")
        for o in dict.fromkeys(takes_r):
            self._emit_take(o, out, pad + "    ")
        if transferidas:
            out.append(f"{pad}}} else {{")
            for n in sorted(transferidas):
                c = self._vivo_c_name(n)
                if self._vivos_activo() and c is not None:
                    out.append(f"{pad}    scar_vivo_baja(&{c}, __scar_vbase);")
            self._emit_owner_frees(transferidas, env, out, pad + "    ")
        out.append(f"{pad}}}")
        return t

    def _gen_bin_op(self, expr, env, out, pad, expected_ty):
        # and/or antes que los demás operadores (en la cadena de isinstance
        # de _gen_expr_impl iba primero)
        if expr.op in ("and", "or"):
            return self._gen_bin_op_logico(expr, env, out, pad, expected_ty)
        l = self.gen_expr(expr.left, env, out, pad)
        # el lado derecho en su propio buffer: si deja sentencias previas, el
        # izquierdo (escrito en línea) se evaluaría después
        r_out = []
        r = self.gen_expr(expr.right, env, r_out, pad)
        if (expr.op not in ("and", "or") and self._es_lugar(expr.left)
                and self._alcanza_lugar(expr.right, expr.left)):
            # el campo, antes de una llamada que lo puede reasignar
            l = self._fijar_lugar(expr.left, l, env, out, pad)
        elif (expr.op not in ("and", "or") and not self._expr_simple(expr.left)
                and (r_out or not self._expr_simple(expr.right)
                     # `sube(c) + c.n`: la llamada antes que el campo
                     or (self._es_lugar(expr.right) and self._alcanza_lugar(expr.left, expr.right)))
                and not self._RE_C_IDENT.fullmatch(l)):
            # el izquierdo se evalúa antes que el derecho, como en el intérprete (C
            # no fija el orden de los operandos). También si el derecho es un campo
            # que el izquierdo puede reasignar.
            t_l = self._new_tmp()
            out.append(f"{pad}{self.c_type(self.infer(expr.left, env))} {t_l} = {l};")
            l = t_l
        out.extend(r_out)
        if expr.op in BITS_OPS:
            if self.infer(expr, env).name == "i64":
                return self._gen_bits_i64(expr, l, r)
            return self._gen_bits(expr, l, r)
        if expr.op == "+" and self.infer(expr, env).name == "str":
            # `+` de str: scar_str_concat() reserva un texto nuevo (en C, l + r
            # sumaría punteros). El resultado es propio: lo recibe una dueña (let,
            # campo, return) o, si queda suelto, un temporal. Si un operando es a su
            # vez un str fresco (otro `+`, un s[i], una llamada que devuelve str), va
            # antes a un temporal que se libera al terminar la sentencia: sin eso,
            # `a + b + c` dejaba el `a + b` intermedio sin nadie que lo liberara.
            if self._is_fresh_str_concat_expr(expr.left, env) or self._is_fresh_str_call(expr.left):
                tmp = self._new_tmp()
                out.append(f"{pad}const char* {tmp} = {l};")
                self.pending_expr_temps.append(tmp)
                l = tmp
            if self._is_fresh_str_concat_expr(expr.right, env) or self._is_fresh_str_call(expr.right):
                tmp = self._new_tmp()
                out.append(f"{pad}const char* {tmp} = {r};")
                self.pending_expr_temps.append(tmp)
                r = tmp
            self.needs_str_concat = True
            return f"scar_str_concat({l}, {r})"
        int_kind = self.infer(expr, env).name if expr.op in ("+", "-", "*", "/", "%") else None
        if int_kind == "i64":
            # las reglas de i32 con 64 bits (panic al desbordar o al dividir por
            # cero); un operando i32 se amplía solo
            self.needs_i64 = True
            fn = {"+": "scar_ladd", "-": "scar_lsub", "*": "scar_lmul",
                  "/": "scar_ldiv", "%": "scar_lmod"}[expr.op]
            return f"{fn}({l}, {r})"
        if expr.op in ("+", "-", "*") and int_kind == "i32":
            # el overflow de i32 es un panic en los dos backends; en C sería
            # comportamiento indefinido
            self.needs_iarith = True
            fn = {"+": "scar_iadd", "-": "scar_isub", "*": "scar_imul"}[expr.op]
            return f"{fn}({l}, {r})"
        if expr.op == "/" and self.infer(expr, env).name == "i32":
            # dividir por cero es UB en C: scar_idiv lo vuelve un panic, como el
            # intérprete
            self.needs_idiv = True
            return f"scar_idiv({l}, {r})"
        if expr.op == "%" and self.infer(expr, env).name == "i32":
            # lo mismo con %: el % de C ya trunca hacia cero (el signo del
            # dividendo), como _scar_mod del intérprete; solo falta el panic por cero
            self.needs_imod = True
            return f"scar_imod({l}, {r})"
        if expr.op == "%" and self.infer(expr, env).name == "f64":
            # f64 % f64: fmod(), como math.fmod del intérprete (el % de C no acepta
            # double)
            return f"fmod({l}, {r})"
        if (
            expr.op in ("==", "!=")
            and self.infer(expr.left, env).name == "str"
            and self.infer(expr.right, env).name == "str"
        ):
            # `==` de str compara el contenido (strcmp), no los punteros.
            # scar_str_cmp_own() además libera en el acto los operandos frescos (s[i],
            # una concatenación, una llamada): sigue siendo una expresión pura, que
            # sirve dentro de la condición de un while.
            fa = 1 if (self._is_fresh_str_concat_expr(expr.left, env) or self._is_fresh_str_call(expr.left)) else 0
            fb = 1 if (self._is_fresh_str_concat_expr(expr.right, env) or self._is_fresh_str_call(expr.right)) else 0
            self.needs_str_concat = True  # garantiza scar_malloc/scar_free/string.h
            self.needs_str_cmp = True
            return f"(scar_str_cmp_own({l}, {r}, {fa}, {fb}) {expr.op} 0)"
        c_op = C_BOOL_OP.get(expr.op, expr.op)
        return f"({l} {c_op} {r})"

    def _gen_call(self, expr, env, out, pad, expected_ty):
        """Una llamada: a un builtin, a una extern fn o a una fn del usuario (
        partida en sus pasos; los builtins y la extern fn la terminan con
        return, ver _SIGUE)."""
        (name, param_tys, mangled_call_name, args_code, bufs, modos, devueltos,
         transferidos, prestados_idx) = self._call_preparar(
            expr, env)
        args_code, temps_prestados, temps_devueltos, tmp = self._call_argumentos(
            expr, env, out, pad, name, param_tys, args_code, bufs, modos, devueltos,
            transferidos, prestados_idx)
        _r = self._call_builtin_numerico(expr, env, name, args_code)
        if _r is not _SIGUE:
            return _r
        _r = self._call_builtin_runtime(expr, env, out, pad, name, args_code)
        if _r is not _SIGUE:
            return _r
        _r = self._call_extern(out, pad, name, args_code, tmp)
        if _r is not _SIGUE:
            return _r
        return self._call_fn_usuario(
            expr, env, out, pad, name, param_tys, mangled_call_name, args_code,
            temps_prestados, temps_devueltos)

    def _call_preparar(self, expr, env):
        """El nombre de la llamada, la instancia de una fn genérica o un valor fn,
        y qué argumentos frescos se pueden capturar."""
        name = expr.callee.name if isinstance(expr.callee, Ident) else None
        # el tipo esperado de cada argumento sale del tipo del parámetro, así un
        # `None` como argumento toma el Option<T> real. Sin una firma conocida (una
        # llamada a través de una expresión) no hay tipo esperado.
        param_tys = None
        # una fn genérica no está en fn_sigs: mangled_call_name guarda el nombre
        # de C de la instancia de esta llamada (se calcula abajo)
        mangled_call_name = None
        if (name is not None and getattr(expr.callee, "es_valor_fn", False)
                and name in env and env[name].name == FN_MARK and env[name].args):
            # una llamada a través de un valor fn tiene los tipos de su firma: un
            # Vec/Map que recibe es suyo (se mueve) y un struct se presta (contrato del
            # tipo fn)
            param_tys = env[name].args[:-1]
        elif name is not None:
            if name in ("abs", "min", "max") and len(expr.args) in (1, 2):
                # abs/min/max son del tipo de sus argumentos, no del f64 de
                # BUILTIN_SIGS: con un f64, el temporal de un argumento i64 que se
                # adelanta perdía dígitos (fuzzer)
                param_tys = [self.infer(expr, env)] * len(expr.args)
            elif name in BUILTIN_SIGS:
                param_tys = BUILTIN_SIGS[name][0]
            elif name in self.generic_fns:
                concrete_args = self._generic_fn_concrete_args(expr, env)
                mangled_call_name = self._ensure_generic_fn_instance(name, concrete_args)
                param_tys = self.fn_sigs[mangled_call_name][0]
            elif name in self.fn_sigs:
                param_tys = self.fn_sigs[name][0]
            elif name in self.task_sigs:
                param_tys = self.task_sigs[name][0]
            elif name in self.extern_sigs:
                param_tys = self.extern_sigs[name][0]
        # un Some/Ok pasado a una fn que solo lo presta (ver
        # _arg_envuelto_prestado) no se queda con su contenido
        for i, a in enumerate(expr.args):
            if self._arg_envuelto_prestado(name, i, a, param_tys):
                self._args_prestados.add(id(a))
        # cada argumento se genera en su propio buffer (_secuenciar): sus
        # sentencias previas no se adelantan a las de los argumentos de antes
        args_code, bufs = [], []
        # en el lado derecho directo de un `let`, una variable que la fn puede
        # devolver pasa al resultado (_arg_transferible). Solo si así todo lo que
        # puede volver queda sin otra dueña.
        if (self._can_capture_arg_temps and expr is self._rhs_let_call
                and id(expr) not in self._transferidos):
            own = self.fn_ownership.get(name) if name is not None else None
            cand = set()
            if own is not None and own.ret_set is not None and len(own.ret_set) >= 2:
                cand = {k for k, a in enumerate(expr.args)
                        if own.may_return_param(k) and self._arg_transferible(a, env)}
            modos = {}
            for k in cand:
                modos[k] = self._arg_transferible(expr.args[k], env)
            if cand:
                self._transferidos[id(expr)] = cand
                self._modo_transfer[id(expr)] = modos
                if not self._resultado_compuesto_fresco(expr, env) and not self._rhs_cond_ok:
                    # sin dueña condicional posible: nada cambia
                    self._transferidos[id(expr)] = set()
        # ver _args_devueltos_frescos
        devueltos = (self._args_devueltos_frescos(name, expr, env)
                     if self._can_capture_arg_temps else None)
        transferidos = self._transferidos.get(id(expr), set())
        modos = self._modo_transfer.get(id(expr), {})
        # lo que puede volver y no es fresco ni transferido (un parámetro
        # prestado, un alias, un campo): si el resto del bloque solo lee el
        # resultado, éste es dueño solo cuando no es ninguna de esas cosas (dueña
        # condicional, ver LetStmt).
        prestados_idx = set()
        return (name, param_tys, mangled_call_name, args_code, bufs, modos, devueltos,
                transferidos, prestados_idx)

    def _call_argumentos(self, expr, env, out, pad, name, param_tys, args_code, bufs,
                         modos, devueltos, transferidos, prestados_idx):
        """El C de cada argumento, con sus temporales prestados o devueltos, y la
        conversión de los argumentos de una extern fn."""
        # (C8) se asignan solo en algunas ramas y la pasada las devuelve siempre
        tmp = None
        if (self._can_capture_arg_temps and self._rhs_cond_ok and expr is self._rhs_let_call
                and name is not None and name in self.fn_sigs and name not in self.task_sigs
                and name not in self.generic_fns and name not in self.extern_sigs
                and self.fn_sigs[name][1] is not None
                and self.fn_sigs[name][1].name in self.structs):
            own_c = self.fn_ownership.get(name)
            if own_c is not None and own_c.ret_set is not None and len(own_c.ret_set) >= 2:
                frescos = set(devueltos or ())
                for atom in own_c.ret_set:
                    if isinstance(atom, tuple) and atom[1] < len(expr.args) and atom[1] not in frescos:
                        prestados_idx.add(atom[1])
                    elif not isinstance(atom, tuple) and atom != "F":
                        prestados_idx = set()
                        break
                if not (frescos or "F" in own_c.ret_set):
                    prestados_idx = set()  # todo lo que vuelve es prestado: como antes
        temps_prestados = []
        temps_devueltos = []
        for i, a in enumerate(expr.args):
            b = []
            args_code.append(self._capture_fresh_struct_arg(
                name, i, a,
                self._capture_fresh_option_arg(
                    name, i, a,
                    self._capture_fresh_str_concat_arg(
                        a,
                        self.gen_expr(
                            a, env, b, pad,
                            expected_ty=(param_tys[i] if param_tys and i < len(param_tys) else None),
                        ),
                        env, b, pad,
                    ),
                    env, b, pad,
                ),
                env, b, pad,
            ))
            if devueltos and i in devueltos:
                free_fn = self._struct_free_fn(self.infer(a, env))
                anular = None
                if free_fn is not None and i in transferidos:
                    if modos.get(i) == "anular":
                        # sigue siendo dueña; queda en NULL
                        anular = args_code[-1]
                    else:
                        # la variable deja de ser dueña acá; la suelta el fin de la sentencia si
                        # no volvió
                        self._unmark_owner(a.name)
                if free_fn is not None:
                    tmp = self._new_tmp()
                    b.append(f"{pad}{self.c_type(self.infer(a, env))} {tmp} = {args_code[-1]};")
                    temps_devueltos.append((free_fn, tmp, anular))
                    args_code[-1] = tmp
            elif i in prestados_idx:
                tmp = self._new_tmp()
                b.append(f"{pad}{self.c_type(self.infer(a, env))} {tmp} = {args_code[-1]};")
                temps_prestados.append(tmp)
                args_code[-1] = tmp
            bufs.append(b)
        if name not in self.extern_sigs or all(
                t.name in ("i32", "i64", "f64", "bool", "str") for t in self.extern_sigs[name][0]):
            # el tipo del temporal es el del parámetro (un `None` o un literal no
            # dicen el suyo: `f(None, None)` con Option<str>)
            args_code = self._secuenciar(expr.args, args_code, env, out, pad,
                                         tys=list(param_tys) if param_tys else None, bufs=bufs)
        else:
            for b in bufs:
                out.extend(b)
        return args_code, temps_prestados, temps_devueltos, tmp

    def _call_builtin_numerico(self, expr, env, name, args_code):
        """Los builtins de números y conversión: abs/min/max, sqrt y libm,
        a_texto, chr/ord, to_i32/to_i64/to_f64, rand, seed, now, arg, len,
        int e int64."""
        if name in ("abs", "min", "max"):
            # exactos para enteros: ver _abs_min_max_helpers_c
            ty = self.infer(expr, env).name
            if name == "abs" and ty == "f64":
                return f"fabs((double)({args_code[0]}))"
            self.needs_abs_min_max = True
            if name == "abs":
                return f"scar_abs_{ty}({args_code[0]})"
            return f"scar_{name}_{ty}({args_code[0]}, {args_code[1]})"
        if name == "sqrt":
            return f"sqrt({args_code[0]})"
        if name in _LIBM_C:
            # (double) explícito por si el código del argumento es un int de C
            return f"{_LIBM_C[name]}(" + ", ".join(f"(double)({a})" for a in args_code) + ")"
        if name == "a_texto":
            # el mismo texto que imprime print, en un str propio
            t = self.infer(expr.args[0], env).name
            if t == "f64":
                self.needs_fmt_f64 = True
                return f"scar_fmt_f64({args_code[0]})"
            self.needs_str_concat = True
            if t == "i32":
                return f'scar_aprintf("%d", (int)({args_code[0]}))'
            if t == "i64":
                return f'scar_aprintf("%lld", (long long)({args_code[0]}))'
            if t == "bool":
                return f'scar_str_concat(({args_code[0]}) ? "true" : "false", "")'
            return f'scar_str_concat({args_code[0]}, "")'
        if name == "chr":
            self.needs_chr_ord = True
            return f"scar_chr({args_code[0]})"
        if name == "ord":
            self.needs_chr_ord = True
            return f"scar_ord({args_code[0]})"
        if name in ("to_i32", "to_i64"):
            # según de qué número viene: un entero que no cabe, o un f64 NaN o fuera
            # de rango, es un panic
            origen = self.infer(expr.args[0], env).name
            if name == "to_i32":
                if origen == "i32":
                    return f"({args_code[0]})"
                if origen == "i64":
                    self.needs_i64 = True
                    return f"scar_i32_desde_i64({args_code[0]})"
                self.needs_to_i32 = True
                return f"scar_to_i32({args_code[0]})"
            if origen in ("i32", "i64"):
                return f"((int64_t)({args_code[0]}))"
            self.needs_i64 = True
            return f"scar_to_i64({args_code[0]})"
        if name == "to_f64":
            return f"((double)({args_code[0]}))"
        if name == "rand":
            self.needs_rand = True
            return "scar_rand()"
        if name == "seed":
            self.needs_rand = True
            return f"scar_rand_init((uint64_t)(int64_t)({args_code[0]}))"
        if name == "now":
            self.needs_now = True
            return "scar_now()"
        if name == "arg":
            # Option<str> con un puntero a argv, sin malloc: como Some("literal"),
            # nada que liberar
            self.c_type(TypeAnn("Option", [T_STR]))  # registra Option_str
            self.needs_arg = True
            return f"scar_arg({args_code[0]})"
        if name == "len":
            self.needs_utf8_len = True
            return f"scar_utf8_len({args_code[0]})"
        if name == "int":
            self.c_type(TypeAnn("Result", [T_I32]))  # registra Result_i32
            self.needs_builtin_int = True
            return f"scar_builtin_int({args_code[0]})"
        if name == "int64":
            self.c_type(TypeAnn("Result", [T_I64]))  # registra Result_i64
            self.needs_builtin_int64 = True
            return f"scar_builtin_int64({args_code[0]})"
        return _SIGUE

    def _call_builtin_runtime(self, expr, env, out, pad, name, args_code):
        """Los builtins del runtime: panic, sleep, chan_new, vec_new, map_new,
        pipe_new, read_pipe, file_open, tcp_connect, tcp_listen e inject_chan."""
        if name == "panic":
            # El mensaje se copia al heap y el panic se queda con él
            # (scar_panic_propio / scar_panic_main_propio); el temporal, si era fresco,
            # se libera antes, porque el panic no vuelve y el fin de la sentencia no
            # llega. Mismo runtime que cualquier panic (suelta las vivas, cascada entre
            # tareas). Sin tope de largo, y no en la pila: un texto muy largo la
            # desbordaba.
            buf = self._new_tmp()
            msg = self._new_tmp()
            out.append(f"{pad}const char *{msg} = SCAR_SAN_STR({args_code[0]});")
            out.append(f"{pad}char *{buf} = malloc(strlen({msg}) + 1);")
            out.append(f'{pad}if (!{buf}) {{ fputs("[PANIC] sin memoria para el mensaje\\n", stderr); exit(1); }}')
            out.append(f"{pad}memcpy({buf}, {msg}, strlen({msg}) + 1);")
            self._flush_pending_expr_temps(out, pad)
            fn_panic = panic_c(self.has_tasks, propio=True)
            out.append(f'{pad}{fn_panic}({buf});')
            out.append(f"{pad}__builtin_unreachable();")
            return "((void)0)"
        if name == "sleep":
            # no emitir `sleep(...)` a secas: choca con sleep(unsigned int) de
            # <unistd.h>, que trunca los segundos; scar_sleep usa nanosleep
            self.needs_sleep = True
            return f"scar_sleep({args_code[0]})"
        if name in ("chan_new", "vec_new"):
            # Sin anotación en el `let`: Chan<i32> / Vec<i32>. Con anotación lo
            # resuelve LetStmt (marca_new_generico). La capacidad (args_code[0], o 0
            # = sin límite) no se puede descartar: chan_new(4) compilaba como
            # chan_new().
            ty = self.infer(expr, env)
            inner = ty.args[0] if ty.args else T_I32
            self.c_type(ty)  # fuerza la monomorfización de Chan_<T> / Vec_<T>
            cap_arg = args_code[0] if args_code else "0"
            return f"scar_{name}_{self._mangled_name(inner)}({cap_arg})"
        if name == "map_new":
            # Sin anotación en el `let`: Map<i32,i32>. Con anotación lo resuelve
            # LetStmt.
            ty = self.infer(expr, env)
            key_ty = ty.args[0] if ty.args else T_I32
            val_ty = ty.args[1] if len(ty.args) > 1 else T_I32
            self.c_type(ty)  # fuerza la monomorfización de Map_<K>_<V>
            return f"scar_map_new_{key_ty.name}_{self._mangled_name(val_ty)}()"
        if name == "pipe_new":
            self.c_type(TypeAnn(PIPE_MARK))  # fuerza el typedef de ScarPipe
            return "scar_pipe_new()"
        if name == "read_pipe":
            self.c_type(TypeAnn("Result", [T_STR]))  # registra Result_str
            self.needs_read_pipe = True
            return f"scar_read_pipe({args_code[0]})"
        if name == "file_open":
            # registra Result_File (y con él el typedef de ScarFile)
            self.c_type(TypeAnn("Result", [TypeAnn(FILE_MARK)]))
            self.needs_file_io = True
            return f"scar_file_open({args_code[0]}, {args_code[1]})"
        if name == "tcp_connect":
            # registra Result_Socket (y con él el typedef de ScarSocket)
            self.c_type(TypeAnn("Result", [TypeAnn(SOCKET_MARK)]))
            self.needs_net_io = True
            return f"scar_tcp_connect({args_code[0]}, {args_code[1]})"
        if name == "tcp_listen":
            self.c_type(TypeAnn("Result", [TypeAnn(LISTENER_MARK)]))
            self.needs_net_io = True
            return f"scar_tcp_listen({args_code[0]})"
        if name == "inject_chan":
            return self._gen_inject_chan(expr, args_code, env, out, pad)
        return _SIGUE

    def _call_extern(self, out, pad, name, args_code, tmp):
        """La llamada a una extern fn: por el wrapper vigilado, por el worker de
        FFI aislado o con la conversión de Result."""
        if name is not None and name in self.extern_sigs:
            # un struct de usuario se pasa por valor a la extern fn (_ffi_c_type):
            # acá se desreferencia el puntero interno
            extern_params = self.extern_sigs[name][0]
            ffi_args_code = [
                f"(*({code}))" if p_ty.name in self.structs else code
                for code, p_ty in zip(args_code, extern_params)
            ]
            if self.extern_sigs[name][1].name == "Result":
                # una extern fn con retorno Result<T> se llama por
                # scar_extern_wrap_<nombre>, que vuelve un NULL de C Err y lo demás Ok (el
                # símbolo de C devuelve T sin envolver). T es siempre un puntero (str o un
                # `extern type`).
                self.c_type(self.extern_sigs[name][1])
                self.extern_result_wrap_needed.add(name)
                return f"scar_extern_wrap_{name}({', '.join(ffi_args_code)})"
            # una extern fn sin Result<T>: siempre por el envoltorio vigilado
            # (scar_extern_guarded_<nombre>), nunca el símbolo crudo
            call_code = f"scar_extern_guarded_{name}({', '.join(ffi_args_code)})"
            ret_ty = self.extern_sigs[name][1]
            if ret_ty.name in self.structs:
                # un struct devuelto por valor se envuelve en un puntero nuevo con el
                # mismo {name}_new de siempre, pasándole sus campos
                tmp = self._new_tmp()
                out.append(f"{pad}{ret_ty.name} {tmp} = {call_code};")
                field_args = ", ".join(
                    f"{tmp}.{fname}" for fname in self.structs[ret_ty.name]
                )
                return f"{ret_ty.name}_new({field_args})"
            return call_code
        return _SIGUE

    def _call_fn_usuario(self, expr, env, out, pad, name, param_tys, mangled_call_name,
                         args_code, temps_prestados, temps_devueltos):
        """La llamada a una fn del usuario: los parámetros que consume, y los
        temporales que hay que soltar después de la llamada."""
        # un Vec/Map pasado a una fn o task común se mueve: quien llama deja de
        # ser su dueño y la fn lo libera al cerrar su scope (gen_fn)
        if param_tys is not None:
            consumed = self.consumed_params.get(name, ())
            self._capture_args_reading_moved_fields(expr.args, param_tys, args_code, env, out, pad)
            for j, (arg_expr, p_ty) in enumerate(zip(expr.args, param_tys)):
                if p_ty is not None and self._is_moved_container_type(p_ty):
                    args_code[j] = self._move_arg_out(arg_expr, p_ty, args_code[j], env, out, pad)
                elif (p_ty is not None and self._is_option_struct(p_ty)
                        and j in self.consumed_option_params.get(name, ())):
                    # la fn se queda con este Option<Struct> (ver gen_fn): una dueña se
                    # transfiere, un valor fresco pasa tal cual, lo demás pasa como copia
                    # (nunca dos dueños del mismo contenido).
                    if isinstance(arg_expr, Ident) and self._is_owner(arg_expr.name):
                        self._note_owner_transfer(arg_expr, p_ty)
                    elif not (self._option_payload_is_malloc(arg_expr, p_ty, env)
                              or self._let_creates_fresh_owner(arg_expr, None, env)):
                        args_code[j] = self._clone_value_expr(p_ty, args_code[j])
                elif p_ty is not None and j in consumed and p_ty.name in self.structs:
                    # la fn se queda con este struct (_resolve_consumed_params): una variable
                    # deja de ser dueña acá (el checker ya la movió), un valor fresco pasa tal
                    # cual, y cualquier otra cosa (un campo, un alias devuelto) pasa como copia
                    # completa
                    if isinstance(arg_expr, Ident):
                        self._note_owner_transfer(arg_expr, p_ty)
                    elif not self._let_creates_fresh_owner(arg_expr, marca_new_generico(arg_expr), env):
                        # copia completa con _clone: deepcopy compartía Vec/Map con el original
                        args_code[j] = f"{p_ty.name}_clone({args_code[j]})"
        # una fn genérica se llama por el nombre de su instancia
        call_code = f"{mangled_call_name or name}({', '.join(args_code)})"
        if temps_devueltos or temps_prestados:
            # el resultado a un temporal; al terminar la sentencia se suelta cada
            # argumento fresco que no volvió
            res = self._new_tmp()
            out.append(f"{pad}{self.c_type(self.fn_sigs[name][1])} {res} = {call_code};")
            for free_fn, tmp, anular in temps_devueltos:
                self.pending_expr_temps.append(f"structfree_si_no:{free_fn}:{tmp}:{res}")
                if anular is not None:
                    self.pending_expr_temps.append(f"anular:{anular}")
            if temps_prestados:
                self._cond_resultado[id(expr)] = temps_prestados
            return res
        return call_code

    def _gen_field_access(self, expr, env, out, pad, expected_ty):
        # Un struct de usuario es un puntero: el acceso es `->`, también
        # encadenado. Una cadena sobre un struct fresco que termina en un escalar
        # (`mkf().e.v`, `F { e: E {..} }.e.v`) guarda la raíz en un temporal que se
        # libera entera al terminar la sentencia, y lee la cadena desde ahí.
        tomado = self._sacar_campo_de_temporal(expr, env, out, pad)
        if tomado is not None:
            return tomado
        if isinstance(expr.obj, FieldAccess):
            raiz, camino = expr, []
            while isinstance(raiz, FieldAccess):
                camino.append(raiz.field)
                raiz = raiz.obj
            if not isinstance(raiz, Ident):
                try:
                    campo_ty = self.infer(expr, env)
                except CodegenError:
                    campo_ty = None
                if campo_ty is not None and campo_ty.name in ("i32", "i64", "f64", "bool"):
                    raiz_code = self.gen_expr(raiz, env, out, pad)
                    raiz_code = self._capture_fresh_struct_temp(raiz, raiz_code, env, out, pad)
                    return raiz_code + "".join(f"->{c}" for c in reversed(camino))
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if not isinstance(expr.obj, (Ident, FieldAccess)):
            # `mk().campo`: el struct fresco se libera al terminar la sentencia. Solo
            # si el campo es escalar: uno str/Vec/struct quedaría apuntando a memoria
            # liberada (esos se sacan con _sacar_campo_de_temporal).
            try:
                campo_ty = self.infer(expr, env)
            except CodegenError:
                campo_ty = None
            if campo_ty is not None and campo_ty.name in ("i32", "i64", "f64", "bool"):
                obj_code = self._capture_fresh_struct_temp(expr.obj, obj_code, env, out, pad)
        return f"{obj_code}->{expr.field}"

    def _gen_index_expr(self, expr, env, out, pad, expected_ty):
        # s[i] -> scar_str_index(obj, i): un str nuevo de un carácter, panic fuera
        # de rango. Si el objeto es a su vez un str fresco (`(a + b)[0]`), va antes
        # a un temporal.
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if self._is_fresh_str_concat_expr(expr.obj, env):
            tmp_o = self._new_tmp()
            out.append(f"{pad}const char* {tmp_o} = {obj_code};")
            self.pending_expr_temps.append(tmp_o)
            obj_code = tmp_o
        idx_code = self.gen_expr(expr.index, env, out, pad)
        self.needs_str_index = True
        return f"scar_str_index({obj_code}, {idx_code})"

    def _gen_array_lit_expr(self, expr, env, out, pad, expected_ty):
        return self._gen_array_lit(expr, env, out, pad)

    def _gen_struct_lit(self, expr, env, out, pad, expected_ty):
        # struct genérico: el nombre de C sale de su instancia (ya resuelta por
        # _resolve_generic_struct_instances; acá se reusa del cache)
        ctor_name = expr.name
        if expr.name in self.generic_structs:
            concrete_args = self._generic_struct_concrete_args(expr, env, expected_ty)
            ctor_name = self._ensure_generic_struct_instance(expr.name, concrete_args)
        elif expr.name not in self.structs:
            raise CodegenError(f"struct no definido: {expr.name}")
        field_names = self.structs[ctor_name]

        # Todo campo str de un struct es dueño de su valor y {Struct}_free lo
        # libera. Lo propio (una dueña "plain", algo recién reservado) se
        # entrega; lo demás (un literal, un parámetro, un campo de otro struct, un
        # parámetro de task de dueño condicional) se copia.
        str_copiados = set()
        tomados = set()

        def _struct_field_arg_code(f_name, f_ty, out):
            f_expr = expr.fields[f_name]
            if self._campo_compuesto_con_dueno(f_ty):
                # Option/Result/Chan: lo propio se entrega; lo prestado (un literal
                # adentro, una variable, un campo de otro struct, arg(i)) se copia. La
                # variable de origen sigue siendo de quien era (str_copiados).
                code = self.gen_expr(f_expr, env, out, pad, expected_ty=f_ty)
                str_copiados.add(f_name)
                if self._valor_compuesto_propio(f_expr, f_ty, env):
                    return code
                return self._clone_value_expr(f_ty, code)
            if f_ty.name == "str" and not (self._str_entregable(f_expr, env)
                                           and getattr(f_expr, "se_mueve", True)):
                # si el checker no lo movió (se sigue usando después), el campo recibe
                # una copia
                str_copiados.add(f_name)
                f_expr = self._copia_str(f_expr)
            code = self.gen_expr(f_expr, env, out, pad, expected_ty=f_ty)
            tomado = self._take_owned_field(f_expr, f_ty, code, env, out, pad)
            if tomado is not None:
                tomados.add(f_name)
                return tomado
            return code

        # los campos se evalúan en el orden en que están escritos (como el
        # intérprete) y se pasan en el orden de la declaración
        orden_fuente = [f for f in expr.fields if f in field_names]
        bufs = [[] for _ in orden_fuente]
        codigos = [_struct_field_arg_code(f, field_names[f], b) for f, b in zip(orden_fuente, bufs)]
        codigos = self._secuenciar([expr.fields[f] for f in orden_fuente], codigos, env, out, pad,
                                   tys=[field_names[f] for f in orden_fuente], bufs=bufs)
        por_campo = dict(zip(orden_fuente, codigos))
        args = ", ".join(por_campo[f] for f in field_names if f in por_campo)
        # Mover una variable dueña a un campo del literal (`Outer { inner: i }`,
        # `Caja { items: v }`): la variable deja de ser dueña (_note_owner_transfer),
        # si no se liberaba dos veces, por la variable y por el struct.
        for f_name, f_ty in field_names.items():
            if f_name in expr.fields and f_name not in str_copiados and f_name not in tomados:
                self._note_owner_transfer(expr.fields[f_name], f_ty)
        return f"{ctor_name}_new({args})"

    def _gen_spawn_expr(self, expr, env, out, pad, expected_ty):
        return self._gen_spawn(expr, env, out, pad)

    def _gen_method_call_expr(self, expr, env, out, pad, expected_ty):
        return self._gen_method_call(expr, env, out, pad)

    def _gen_array_lit(self, expr, env, out, pad) -> str:
        """[a, b, c]: un Vec nuevo en un temporal y un push por elemento, por el
        mismo camino que v.push(x). El temporal queda sin dueña, como el de
        vec_new(): quien lo use lo trata como fresco."""
        ty = TypeAnn(VEC_MARK, [expr.tipo_elem])
        c_ty = self.c_type(ty)
        tmp = self._new_tmp()
        nombre = self._mangled_name(expr.tipo_elem)
        out.append(f"{pad}{c_ty} {tmp} = scar_vec_new_{nombre}({len(expr.elems)});")
        if not expr.elems:
            return tmp
        env[tmp] = ty
        for e in expr.elems:
            push = MethodCall(Ident(tmp).at(expr), "push", [e]).at(expr)
            code = self.gen_expr(push, env, out, pad)
            if code not in ("((void)0)", ""):
                out.append(f"{pad}{code};")
        return tmp

    def _arg_envuelto_prestado(self, name, i, a, param_tys) -> bool:
        """True si el argumento i, un Some(...)/Ok(...), va a una fn que lo recibe
        prestado (un Result, o un Option que la fn no consume): la fn solo lo
        lee y el dueño del contenido sigue siendo el mismo. Un Option<Vec/Map>
        o un Option<Struct> que la fn consume sí se entregan."""
        if not isinstance(a, (SomeExpr, OkExpr)) or name is None:
            return False
        if name not in self.fn_sigs or name in self.task_sigs or not param_tys or i >= len(param_tys):
            return False
        p = param_tys[i]
        if p.name not in ("Option", "Result") or self._is_moved_container_type(p):
            return False
        return i not in self.consumed_option_params.get(name, ())

    def _iarith_helper(self) -> str:
        """+, -, * y negación de i32 con panic por overflow, como el intérprete
        (_check_i32). Usa __builtin_*_overflow; el panic vive en una función
        aparte marcada cold. Con tasks, scar_panic() (cascada); sin tasks,
        mensaje y exit(1)."""
        if self.has_tasks:
            cuerpo = '    scar_panic("desbordamiento de i32: %d %s %d", a, op, b);\n'
        else:
            cuerpo = '    scar_panic_main("desbordamiento de i32: %d %s %d", a, op, b);\n'
        return runtime_c.texto(
            "i32_aritmetica",
            CUERPO=cuerpo,
        )
