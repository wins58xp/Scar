"""Mixin Sentencias de Codegen (paso C6): gen_stmt, gen_block y gen_fn. Cada
sentencia de SCAR a C, el cuerpo de cada fn, y las preguntas sobre un bloque
(si siempre retorna, si es recto, qué reasigna).
"""

import copy

from parser import (marca_new_generico, 
    FnDecl, LetStmt, ReturnStmt, ExprStmt, IfStmt, StrLit, Ident, Call, PrintExpr,
    WhileStmt, WhileLetStmt, ForStmt, AssignStmt, FieldAccess, TryExpr, OkExpr,
    ErrExpr, SomeExpr, NoneExpr, MethodCall, Node, hijos, block_always_returns,
    BreakStmt, block_never_falls_through,
)
from types_ import T_I32, numeric_result

from .comun import (
    CHAN_MARK, CodegenError, _expr_mentions_name, MAP_MARK, _raiz_fin_c,
    _raiz_inicio_c, SCAR_MALLOPT_PROLOGUE, SCAR_RAND_SEED_LINE, _ShadowSubBlock,
    VEC_MARK, _vivos_truncar_returns,
)


class Sentencias:
    def _solo_lecturas(self, name, stmts) -> bool:
        """True si en `stmts` (lo que sigue al `let name = ...`) `name` solo se
        lee: un campo, un argumento de print, o un argumento que una fn solo
        presta. Nada de moverlo, reasignarlo, devolverlo ni sombrearlo: así el
        resultado puede ser una dueña condicional (ver _rhs_cond_ok)."""
        def ok_padre(padre, nodo):
            if isinstance(padre, FieldAccess) and padre.obj is nodo:
                return True
            if isinstance(padre, PrintExpr):
                return True
            if isinstance(padre, Call) and isinstance(padre.callee, Ident):
                fn = padre.callee.name
                if fn not in self.fn_sigs or fn in self.task_sigs or fn in self.generic_fns \
                        or fn in self.extern_sigs:
                    return False
                own = self.fn_ownership.get(fn)
                ret = self.fn_sigs[fn][1]
                # una fn que no devuelve un struct no puede devolver el argumento
                devuelve_struct = ret is not None and ret.name in self.structs
                for k, a in enumerate(padre.args):
                    if a is nodo:
                        if k in self.consumed_params.get(fn, ()):
                            return False
                        if devuelve_struct and (own is None or own.ret_set is None or own.may_return_param(k)):
                            return False
                return True
            return False

        def recorrer(nodo, padre):
            if isinstance(nodo, Ident):
                return nodo.name != name or ok_padre(padre, nodo)
            if isinstance(nodo, Node):
                for k, v in getattr(nodo, "__dict__", {}).items():
                    if isinstance(v, str) and v == name and k != "field":
                        return False  # otro binding con su nombre (let, for, while let...)
            for h in hijos(nodo):
                if isinstance(h, (Node, list, tuple, dict)) and not recorrer(h, nodo if isinstance(nodo, Node) else padre):
                    return False
            return True

        return recorrer(list(stmts), None)

    # ---- lvalues (destino de asignación): variable o campo encadenado ----
    def _assign_root(self, target):
        node = target
        while isinstance(node, FieldAccess):
            node = node.obj
        if not isinstance(node, Ident):
            raise CodegenError(
                f"destino de asignación no soportado por el backend de C: "
                f"{type(target).__name__}"
            )
        return node

    def _block_reassigns_via_concat(self, name: str, stmts) -> bool:
        """True si en `stmts` (también en sus bloques anidados) hay una asignación
        a `name` cuyo valor es un str nuevo (o cualquier cosa que no sea un
        literal). LetStmt lo usa para que un `let mut s: str` reasignado nazca
        dueño de una copia propia. Sobre-aproximar es seguro: en el peor caso
        reserva un str que no hacía falta."""
        for s in stmts:
            if isinstance(s, AssignStmt):
                root = self._assign_root(s.target)
                # cualquier valor que no sea un literal: un str nuevo (s[i], r.err(), una
                # fn), o `a = b` con otra variable, un campo o una llamada, que la deja
                # con su propia copia (si no, `primera = linea` la dejaba apuntando al
                # texto de `linea`, liberado en la reasignación siguiente)
                if root.name == name and not isinstance(s.expr, StrLit):
                    return True
            elif isinstance(s, IfStmt):
                if self._block_reassigns_via_concat(name, s.then_block.stmts):
                    return True
                if s.else_block is not None and self._block_reassigns_via_concat(name, s.else_block.stmts):
                    return True
            elif isinstance(s, (WhileStmt, WhileLetStmt, ForStmt)):
                if self._block_reassigns_via_concat(name, s.body.stmts):
                    return True
        return False

    def _ident_root_name(self, expr):
        """El nombre de la variable de la que parte `expr` (o.inner.valor -> 'o'),
        o None si es una llamada, un literal o un temporal. Como
        _lvalue_root_name del checker."""
        node = expr
        while isinstance(node, FieldAccess):
            node = node.obj
        if isinstance(node, Ident):
            return node.name
        return None

    # ---- liberar al cerrar un scope ----
    def _block_is_straight_line(self, block) -> bool:
        """True si se pueden emitir los free de las dueñas de este bloque en su
        llave de cierre. Un return, un break, un if o un loop anidados no lo
        impiden: el return y el break liberan ellos mismos lo que dejan atrás
        (_emit_return_frees, _gen_break), y todo camino que no pasa por ellos
        llega al cierre. Un panic o una cancelación pueden saltar desde
        cualquier sentencia: eso lo cubre el registro de dueñas vivas, no este
        análisis.

        Solo depende del árbol: se guarda por bloque (una cadena de else-if lo
        volvía a recorrer entero en cada eslabón)."""
        cache = self.__dict__.setdefault("_straight_cache", {})
        r = cache.get(id(block))
        if r is None:
            r = cache[id(block)] = (block, self._block_is_straight_line_calc(block))
        return r[1]

    def _block_is_straight_line_calc(self, block) -> bool:
        for stmt in block.stmts:
            if isinstance(stmt, IfStmt):
                if not self._block_is_straight_line(stmt.then_block):
                    return False
                if stmt.else_block is not None and not self._block_is_straight_line(stmt.else_block):
                    return False
            if isinstance(stmt, (WhileStmt, WhileLetStmt, ForStmt)):
                if not self._block_is_straight_line(stmt.body):
                    return False
        return True

    def _block_always_returns(self, block) -> bool:
        """True si toda ejecución que entra a este bloque sale por un `return`:
        los free del cierre serían código muerto. La regla es
        parser.block_always_returns, la misma que usa el checker."""
        return block_always_returns(block)

    def _emit_main_root_epilogue(self, out, pad):
        """Las líneas que cierran el TaskContext __scar_root de main: cancelar a
        las hijas sin join, destruir el mutex de children, liberar el arreglo
        children y la arena raíz. Las emite cada `return` de main (con
        in_main_root_scope) y el final del cuerpo, para el camino que no
        retorna."""
        out.append(f"{pad}scar_cancel_children(&__scar_root);")
        out.append(f"{pad}pthread_mutex_destroy(&__scar_root.children_mu);")
        out.append(f"{pad}pthread_mutex_destroy(&__scar_root.wait_lock);")
        out.append(f"{pad}free(__scar_root.children);")
        out.append(f"{pad}free(__scar_root.panic_msg);")
        out.append(f"{pad}scar_arena_free(&__scar_root.arena);")

    # ---- statements ----
    def gen_stmt(self, stmt, env, out, indent, rest=None):
        # Los flags de propiedad que este statement apagó (_note_owner_transfer)
        # se escriben después de él, cuando la transferencia ya ocurrió. Cada
        # statement anidado escribe los suyos.
        prev_clears = self._pending_flag_clears
        self._pending_flag_clears = []
        prev_takes = self._pending_takes
        self._pending_takes = []
        prev_vo = self._vivos_out
        self._vivos_out = (out, "    " * indent)
        # El AST de una fn genérica es compartido por todas sus instancias: el
        # tipo anotado de un `let` se canoniza para esta.
        decl_ty = getattr(stmt, "declared_type", None) if isinstance(stmt, LetStmt) else None
        if decl_ty is not None:
            stmt.declared_type = self._canon(decl_ty)
        try:
            self._gen_stmt_body(stmt, env, out, indent, rest)
        finally:
            self._vivos_out = prev_vo
            if decl_ty is not None:
                stmt.declared_type = decl_ty
            for flag in dict.fromkeys(self._pending_flag_clears):
                out.append(f"{'    ' * indent}{flag} = false;")
            self._pending_flag_clears = prev_clears
            for o in dict.fromkeys(self._pending_takes):
                self._emit_take(o, out, '    ' * indent)
            self._pending_takes = prev_takes
        self._vivos_sync(env, out, "    " * indent)

    # _gen_stmt_body: tipo de nodo -> el método que lo genera. Ningún nodo
    # hereda de otro, así que buscar type(stmt) equivale a la cadena de
    # isinstance que había.
    _DESPACHO_SENTENCIA = {
        LetStmt: "_gen_let_stmt",
        BreakStmt: "_gen_break_stmt",
        ReturnStmt: "_gen_return_stmt",
        ExprStmt: "_gen_expr_stmt",
        IfStmt: "_gen_if_stmt",
        AssignStmt: "_gen_assign_stmt",
        WhileStmt: "_gen_while_stmt",
        WhileLetStmt: "_gen_while_let_stmt",
        ForStmt: "_gen_for_stmt",
    }

    def _gen_stmt_body(self, stmt, env, out, indent, rest=None):
        pad = "    " * indent
        # Temporales por statement: los de uno anterior nunca pasan a este (ver
        # pending_expr_temps en __init__).
        self.pending_expr_temps = []
        self._can_capture_arg_temps = isinstance(stmt, (LetStmt, AssignStmt, ReturnStmt, ExprStmt))
        self._rhs_let_call = stmt.expr if isinstance(stmt, LetStmt) and isinstance(stmt.expr, Call) else None
        self._rhs_cond_ok = (self._rhs_let_call is not None and rest is not None
                             and self._solo_lecturas(stmt.name, rest))
        metodo = self._DESPACHO_SENTENCIA.get(type(stmt))
        if metodo is None:
            raise CodegenError(f"statement no soportado por el backend de C: {type(stmt).__name__}")
        return getattr(self, metodo)(stmt, env, out, indent, rest, pad)

    def _gen_let_stmt(self, stmt, env, out, indent, rest, pad):
        new_mark, ty, code = self._let_tipo(stmt, env, out, pad)
        return self._let_propiedad(stmt, env, out, rest, pad, new_mark, ty, code)

    def _let_tipo(self, stmt, env, out, pad):
        """El tipo de la variable: el declarado, el de un Vec/Map/Chan nuevo según
        su marca genérica, o el que se infiere; y el código de la expresión."""
        # (C8) se asignan solo en algunas ramas y la pasada las devuelve siempre
        ty = None
        code = None
        new_mark = marca_new_generico(stmt.expr)
        if stmt.declared_type is not None and new_mark is not None:
            # chan_new()/vec_new()/map_new() no dicen su T: sale de la anotación
            # del let (sin esto quedaría el T=i32 de BUILTIN_SIGS). Misma regla que
            # marca_new_generico de parser.py.
            ty = stmt.declared_type
            if ty.name != new_mark or not ty.args:
                raise CodegenError(
                    f"'{stmt.name}': la anotación de {stmt.expr.callee.name}() "
                    f"debe ser {new_mark}<T>, se dio {ty!r}"
                )
            self.c_type(ty)  # fuerza la monomorfización de Chan_<T>/Vec_<T>/Map_<K>_<V>
            if new_mark == MAP_MARK:
                if len(ty.args) < 2:
                    raise CodegenError(
                        f"'{stmt.name}': la anotación de map_new() debe ser "
                        f"Map<K,V>, se dio {ty!r}"
                    )
                key_ty, val_ty = ty.args[0], ty.args[1]
                code = f"scar_map_new_{key_ty.name}_{self._mangled_name(val_ty)}()"
            else:
                inner = ty.args[0]
                fn_prefix = "scar_chan_new_" if new_mark == CHAN_MARK else "scar_vec_new_"
                inner_part = self._mangled_name(inner)
                if new_mark in (CHAN_MARK, VEC_MARK):
                    # La capacidad de chan_new(cap)/vec_new(cap) se pasa; sin ella, 0.
                    cap_arg = (
                        self.gen_expr(stmt.expr.args[0], env, out, pad, expected_ty=T_I32)
                        if stmt.expr.args else "0"
                    )
                    code = f"{fn_prefix}{inner_part}({cap_arg})"
                else:
                    code = f"{fn_prefix}{inner_part}()"
        elif (
            stmt.declared_type is not None
            and isinstance(stmt.expr, Call)
            and isinstance(stmt.expr.callee, Ident)
            and stmt.expr.callee.name == "accept_chan"
        ):
            # accept_chan() tampoco dice su T: sale de la anotación, que el checker
            # ya validó (Option<Chan<T>> con T en el `accepts` de la task).
            ty = stmt.declared_type
            code = self._gen_accept_chan(stmt.expr, ty, env, out, pad)
            # Se recuerda la variable para que un `while let Some(x) = <ella>` la
            # trate como dueña de la referencia (ver _while_let_binds_chan_owner).
            self._accept_chan_vars.add(stmt.name)
        else:
            # declared_type es el tipo esperado de un None sin anotación propia
            # (`let x: Option<str> = None`).
            ty = self.infer(stmt.expr, env, expected_ty=stmt.declared_type)
            code = self.gen_expr(stmt.expr, env, out, pad, expected_ty=stmt.declared_type)
            if stmt.declared_type is not None:
                # Con anotación manda la anotación: `let z: f64 = 7` es f64 aunque el
                # valor sea i32 (el checker ya validó la compatibilidad). Lo usa la
                # promoción de cada BinOp que lea z.
                ty = stmt.declared_type
        env[stmt.name] = ty
        return new_mark, ty, code

    def _let_propiedad(self, stmt, env, out, rest, pad, new_mark, ty, code):
        """Quién es dueño del valor nuevo y cómo se declara en C: str que se va a
        concatenar, tipos anidados, str prestado, valor fresco u otra dueña."""
        # Un `let mut x: str` que más adelante (en este bloque o anidado) se
        # reasigna con concatenación es dueña desde el arranque, con una copia
        # del valor inicial. Así la marca queda en el frame de este let y no en
        # el de un loop anidado, y cada reasignación solo libera lo viejo.
        str_mut_will_concat = (
            ty.name == "str"
            and stmt.mutable
            and rest is not None
            and self._block_reassigns_via_concat(stmt.name, rest)
        )
        if str_mut_will_concat and not self._let_creates_fresh_owner(stmt.expr, new_mark, env):
            return self._let_str_concatenable(stmt, out, pad, ty, code)
        # `let mut t: Option<str> = None`: un None no posee nada, así que t es
        # dueña desde el arranque y una reasignación posterior libera lo
        # anterior, como con `let mut t = Some(...)`.
        empieza_none = isinstance(stmt.expr, NoneExpr) and ty.name == "Option"
        if self._es_anidado(ty) and not (
                isinstance(stmt.expr, Ident)
                and self._is_owner(stmt.expr.name)):
            return self._let_anidado(stmt, env, out, pad, ty, code)
        prestados = self._cond_resultado.pop(id(stmt.expr), None) if ty.name in self.structs else None
        if prestados:
            return self._let_prestado_condicional(stmt, out, pad, ty, code, prestados)
        if self._is_ownable_type(ty) and (
                empieza_none or self._let_creates_fresh_owner(stmt.expr, new_mark, env)):
            code = self._let_valor_fresco(stmt, env, ty, code)
        elif ty.name == CHAN_MARK and self._let_creates_fresh_owner(stmt.expr, new_mark, env):
            # Chan no está en _is_ownable_type (es refcount): solo `chan_new()`
            # crea una referencia propia (refcount=1). Un `let ch2 = ch1` no
            # incrementa, así que tampoco decrementa.
            self._mark_owner(stmt.name, "chan")
        elif self._is_ownable_type(ty) and self._let_from_param_returning_call(stmt, ty):
            # `let r = f(..., a, ...)` con f que devuelve siempre su parámetro k:
            # r es el objeto a (lo resuelve el helper).
            pass
        elif ty.name == "str" and (
            isinstance(stmt.expr, Ident)
            or (isinstance(stmt.expr, FieldAccess) and self._campo_de_temporal(stmt.expr, env) is None)
        ):
            # `let s = t` / `let s = d.b` con str: s es un valor propio, no un
            # puntero al texto de otro (si ese otro se liberaba, use-after-free).
            # Si el checker movió t, la propiedad pasa a s; si no (un
            # campo, o una variable no dueña), s recibe una copia.
            fuente = stmt.expr.name if isinstance(stmt.expr, Ident) else None
            if (fuente is not None and getattr(stmt.expr, "se_mueve", False)
                    and self._is_owner(fuente)):
                origen = self._owner_origin(fuente) or "plain"
                out.append(f"{pad}{self.c_type(ty)} {stmt.name} = {code};")
                self._flush_pending_expr_temps(out, pad)
                self._apagar_flag_de_loop(fuente, ty)
                self._unmark_owner(fuente)
                self._mark_owner(stmt.name, origen)
            else:
                self.needs_str_concat = True
                out.append(f"{pad}{self.c_type(ty)} {stmt.name} = scar_str_concat({code}, \"\");")
                self._flush_pending_expr_temps(out, pad)
                self._mark_owner(stmt.name, "plain")
            if self.owner_stack:
                self._decl_frame[stmt.name] = len(self.owner_stack) - 1
            return
        elif self._is_ownable_type(ty) and isinstance(stmt.expr, FieldAccess):
            # `let a = r.campo` con campo Vec/Map/struct/Result y r dueña: el
            # campo se mueve a `a` y en r queda vacío (_try_neutralize_extracted_field),
            # así {R}_free no lo libera dos veces. La declaración va
            # antes de vaciar, o `a` leería el campo ya vacío. Si no aplica (r no
            # es dueña, o el campo es str), `a` es un alias.
            out.append(f"{pad}{self.c_type(ty)} {stmt.name} = {code};")
            self._flush_pending_expr_temps(out, pad)
            if self._try_neutralize_extracted_field(stmt.expr, ty, env, out, pad):
                # El Result<str> que el struct poseía trae su .value propio.
                if ty.name == "Result" and ty.args and ty.args[0].name == "str":
                    self._mark_owner(stmt.name, "result_str:plain")
                else:
                    self._mark_owner(stmt.name, "plain")
            else:
                root_name = self._ident_root_name(stmt.expr)
                if root_name is not None:
                    self._alias_root[stmt.name] = self._resolve_alias_root(root_name)
            if self.owner_stack:
                self._decl_frame[stmt.name] = len(self.owner_stack) - 1
            return
        elif (
            self._is_ownable_type(ty)
            and ty.name != "str"
            and isinstance(stmt.expr, Ident)
            and self._is_owner(stmt.expr.name)
        ):
            # `let b = a` mueve: el checker garantiza que a no se vuelve
            # a leer sin reasignarse, así que la propiedad pasa entera a b con el
            # mismo origen.
            origen = self._owner_origin(stmt.expr.name) or "plain"
            out.append(f"{pad}{self.c_type(ty)} {stmt.name} = {code};")
            self._flush_pending_expr_temps(out, pad)
            self._apagar_flag_de_loop(stmt.expr.name, ty)
            self._unmark_owner(stmt.expr.name)
            self._mark_owner(stmt.name, origen)
            if self.owner_stack:
                self._decl_frame[stmt.name] = len(self.owner_stack) - 1
            return
        else:
            # Alias de algo que no es dueño (un parámetro, un campo): b no se
            # marca dueña. Se anota su raíz (_alias_root, resuelta por cadenas)
            # para que un `return b` sepa qué entrega (_returned_owner_names).
            root_name = self._ident_root_name(stmt.expr)
            if root_name is not None:
                self._alias_root[stmt.name] = self._resolve_alias_root(root_name)
            # Frame de nacimiento del alias, aunque no sea dueño: si después se le
            # asigna un valor fresco, AssignStmt lo marca dueño en este frame
            # (_decl_frame_of).
            if self._is_ownable_type(ty) and self.owner_stack:
                self._decl_frame[stmt.name] = len(self.owner_stack) - 1
        out.append(f"{pad}{self.c_type(ty)} {stmt.name} = {code};")
        self._flush_pending_expr_temps(out, pad)
        return

    def _let_str_concatenable(self, stmt, out, pad, ty, code):
        """Un str mutable que después se reasigna con +: nace en el heap aunque
        el valor sea un literal, así la concatenación puede liberarlo."""
        # scar_str_concat(x, "") copia a heap sin depender de strdup (POSIX,
        # no C11: _GNU_SOURCE solo se define con tasks/canales/red).
        self.needs_str_concat = True
        code = f"scar_str_concat({code}, \"\")"
        self._mark_owner(stmt.name, "plain")
        self._str_mut_promovidas.add(stmt.name)
        out.append(f"{pad}{self.c_type(ty)} {stmt.name} = {code};")
        self._flush_pending_expr_temps(out, pad)
        return

    def _let_anidado(self, stmt, env, out, pad, ty, code):
        """Un tipo con dueños anidados (Option<Vec<str>>, Vec<Struct>...) que no
        viene de una dueña: se clona para que la variable tenga el suyo."""
        # Un Option/Result anidado (Option<Result<str>>...) posee todo lo de
        # adentro, como un campo de ese tipo: lo propio se toma, lo
        # prestado se copia entero y se libera recursivamente (origen
        # "anidado"). El campo de una dueña se saca (queda None); el de otro
        # struct, se copia. `let b = a` con a dueña va por la rama de mover.
        if isinstance(stmt.expr, FieldAccess):
            out.append(f"{pad}{self.c_type(ty)} {stmt.name} = {code};")
            self._flush_pending_expr_temps(out, pad)
            if not self._try_neutralize_extracted_field(stmt.expr, ty, env, out, pad):
                out.append(f"{pad}{stmt.name} = {self._clone_value_expr(ty, stmt.name)};")
        else:
            if not self._valor_compuesto_propio(stmt.expr, ty, env):
                code = self._clone_value_expr(ty, code)
            out.append(f"{pad}{self.c_type(ty)} {stmt.name} = {code};")
            self._flush_pending_expr_temps(out, pad)
        self._mark_owner(stmt.name, "anidado")
        if self.owner_stack:
            self._decl_frame[stmt.name] = len(self.owner_stack) - 1
        return

    def _let_prestado_condicional(self, stmt, out, pad, ty, code, prestados):
        """Un str que la llamada a veces presta y a veces entrega: se copia con un
        flag que dice si hay que liberarlo."""
        # El resultado puede ser prestado (un parámetro, un alias, un campo) o
        # propio: es dueño solo si no es ninguno de los prestados, y lo dice un
        # flag (origen "cond:", que respetan los free de fin de scope, de
        # return/break y el registro de vivas). Requiere que el resto del bloque
        # solo lo lea (_solo_lecturas).
        out.append(f"{pad}{self.c_type(ty)} {stmt.name} = {code};")
        self._flush_pending_expr_temps(out, pad)
        flag = self._new_tmp()
        cond = " && ".join(f"{stmt.name} != {t}" for t in prestados)
        out.append(f"{pad}bool {flag} = ({cond});")
        self._mark_owner(stmt.name, f"cond:{flag}")
        return

    def _let_valor_fresco(self, stmt, env, ty, code):
        """El valor de una variable que nace dueña de un valor fresco: el código de
        C de la expresión, con el caso de un Result<str> que viene de una
        temporal, y su origen de propiedad."""
        # Dueña solo si el lado derecho es un valor nuevo en el heap
        # (_let_creates_fresh_owner) o un None que empieza vacío. Un `let x`
        # que redeclara otra x del mismo scope deja la anterior sin liberar
        # (límite conocido). El origen solo distingue cómo liberar lo de
        # adentro: struct, Vec, Map y str son "plain" ({T}_free decide
        # malloc o arena por el encabezado; un str fresco siempre es de
        # scar_malloc).
        if (
            ty.name == "Result" and ty.args and ty.args[0].name == "str"
            and isinstance(stmt.expr, Call) and isinstance(stmt.expr.callee, Ident)
            and stmt.expr.callee.name in self.result_str_value_origin
        ):
            # Una fn/task que siempre devuelve Ok(x) con x de origen conocido
            # (_resolve_result_str_value_origin): el .value también es propio y el
            # origen lo dice.
            origin = f"result_str:{self.result_str_value_origin[stmt.expr.callee.name]}"
        elif (
            ty.name == "Result" and ty.args and ty.args[0].name == "str"
            and isinstance(stmt.expr, Call) and isinstance(stmt.expr.callee, Ident)
            and stmt.expr.callee.name in self.extern_sigs
        ):
            # Una extern fn: scar_ffi_read_str arma el .value con scar_malloc, así
            # que siempre es propio.
            origin = "result_str:plain"
        elif (
            ty.name == "Result" and ty.args and ty.args[0].name == "str"
            and isinstance(stmt.expr, MethodCall)
            and self._is_fresh_result_producer(stmt.expr, env)
        ):
            # `f.read_all()`, `s.read()`: el .value es un str propio.
            origin = "result_str:plain"
        elif (
            ty.name == "Result" and ty.args and ty.args[0].name == "str"
            and isinstance(stmt.expr, FieldAccess)
            and self._campo_de_temporal(stmt.expr, env) is not None
        ):
            # `let r = mk().r`: el Result que el struct poseía trae su .value propio
            origin = "result_str:plain"
        elif (
            ty.name == "Result" and ty.args and ty.args[0].name == "str"
            and isinstance(stmt.expr, (OkExpr, ErrExpr))
        ):
            # `let r = Ok(...)`: el Result es dueño de su .value; lo fresco se
            # toma, lo demás se copia, un Err lo deja NULL.
            if isinstance(stmt.expr, OkExpr) and not self._let_creates_fresh_owner(
                    stmt.expr.expr, marca_new_generico(stmt.expr.expr), env):
                code = self._clone_value_expr(ty, code)
            origin = "result_str:plain"
        elif self._option_payload_is_malloc(stmt.expr, ty, env):
            # `let o = c.recv()` / `v.get(i)` / `v.pop()` con Option<Struct>: el
            # contenido es una copia propia en un bloque malloc.
            origin = "opt_malloc"
        else:
            origin = "plain"
        self._mark_owner(stmt.name, origin)
        return code

    def _gen_break_stmt(self, stmt, env, out, indent, rest, pad):
        self._gen_break(env, out, pad)
        return

    def _gen_return_stmt(self, stmt, env, out, indent, rest, pad):
        # El Some/Ok que es la expresión entera del return sigue el camino de
        # _returned_owner_names (ver _contenido_propio).
        self._expr_de_return = stmt.expr
        # Un `return` libera en su punto todo lo vivo en todos los scopes
        # abiertos (_live_owners_at_return), salvo lo que entrega.
        if stmt.expr is None:
            self._emit_owner_frees(self._live_owners_at_return(None), env, out, pad)
            if self.in_main_root_scope:
                self._emit_main_root_epilogue(out, pad)
            # main de SCAR es void pero en C es `int main`: un `return` sin valor
            # es `return 0;` (clang rechaza `return;` en una fn int).
            if self.cur_fn_name == "main":
                out.append(f"{pad}return 0;")
            else:
                out.append(f"{pad}return;")
            return
        # Contrato único de str: ver _str_return_propio.
        nuevo = self._str_return_propio(stmt.expr, env)
        if nuevo is not stmt.expr:
            stmt = ReturnStmt(nuevo)
        envuelto = stmt.expr
        capas = []
        while isinstance(envuelto, (SomeExpr, OkExpr)):
            capas.append(envuelto)
            envuelto = envuelto.expr
        if capas and isinstance(envuelto, FieldAccess):
            # `return Ok(c.campo)` / `Some(c.campo)` con c dueña: el campo se saca
            # a un temporal dueño y el return lo entrega envuelto; c se libera
            # entera (antes se devolvía lo liberado; lo encontró lib/zlib).
            try:
                f_ty = self.infer(envuelto, env)
            except CodegenError:
                f_ty = None
            if self._puede_tomar_campo(envuelto, f_ty):
                code = self.gen_expr(envuelto, env, out, pad)
                tomado = self._take_owned_field(envuelto, f_ty, code, env, out, pad)
                if tomado is not None:
                    env[tomado] = f_ty
                    self._mark_owner(tomado, "plain")
                    nuevo = Ident(tomado).at(envuelto) if envuelto.line is not None else Ident(tomado)
                    for capa in reversed(capas):
                        copia = copy.copy(capa)
                        copia.expr = nuevo
                        nuevo = copia
                    stmt = ReturnStmt(nuevo)
                    self._expr_de_return = stmt.expr
        if isinstance(stmt.expr, FieldAccess):
            # `return c.campo` con c dueña: el campo se saca y c se libera entera
            # (ver _take_owned_field).
            try:
                f_ty = self.infer(stmt.expr, env)
            except CodegenError:
                f_ty = None
            if self._puede_tomar_campo(stmt.expr, f_ty):
                code = self.gen_expr(stmt.expr, env, out, pad, expected_ty=self.cur_ret_ty)
                tomado = self._take_owned_field(stmt.expr, f_ty, code, env, out, pad)
                self._flush_pending_expr_temps(out, pad)
                self._emit_owner_frees(self._live_owners_at_return(set()), env, out, pad)
                if self.in_main_root_scope:
                    self._emit_main_root_epilogue(out, pad)
                out.append(f"{pad}return {tomado};")
                return
        if self._ret_con_contrato(self.cur_ret_ty) and not self._retorno_propio(
                stmt.expr, self.cur_ret_ty, env):
            # Contrato único (_ret_con_contrato): lo prestado sale como copia
            # completa y todas las dueñas de la fn se liberan.
            code = self.gen_expr(stmt.expr, env, out, pad, expected_ty=self.cur_ret_ty)
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(self.cur_ret_ty)} {tmp} = "
                       f"{self._clone_value_expr(self.cur_ret_ty, code)};")
            self._flush_pending_expr_temps(out, pad)
            self._emit_owner_frees(self._live_owners_at_return(set()), env, out, pad)
            if self.in_main_root_scope:
                self._emit_main_root_epilogue(out, pad)
            out.append(f"{pad}return {tmp};")
            return
        # Una dueña devuelta tal cual, o envuelta en Ok()/Some() (que no
        # copian), se transfiere a quien llama: no se libera.
        exclude_name = self._returned_owner_name(stmt.expr)
        # `live` excluye toda transferencia directa (_returned_owner_names),
        # salvo la raíz de un alias devuelto (`let mut m = m0; ...
        # m = f(m) ...; return Ok(m)`): si m se reasignó ya no es m0, así que
        # se decide en runtime (_emit_alias_return_guards).
        alias_guards = self._alias_return_guards(stmt.expr, env)
        live = self._live_owners_at_return(
            self._returned_owner_names(stmt.expr, env) - set(alias_guards)
        )
        # Devolver el contenido de una dueña Option<Struct> (`p` de un
        # `while let Some(p) = o`) lo saca de o antes de liberarla.
        takes = [self._opt_payload_of[n] for n in self._returned_owner_names(stmt.expr, env)
                 if n in self._opt_payload_of]
        guarded = {r: live.pop(r) for r in list(alias_guards) if r in live}
        if not live and not guarded:
            # Nada vivo que liberar: el return queda directo.
            code = self.gen_expr(stmt.expr, env, out, pad, expected_ty=self.cur_ret_ty)
            if self.pending_expr_temps:
                # `code` lee un temporal pendiente: se evalúa en una variable, recién
                # ahí se liberan los temporales y se devuelve la variable.
                cap = self._new_tmp()
                out.append(f"{pad}{self.c_type(self.cur_ret_ty)} {cap} = {code};")
                self._flush_pending_expr_temps(out, pad)
                code = cap
            if self.in_main_root_scope:
                self._emit_main_root_epilogue(out, pad)
            out.append(f"{pad}return {code};")
            return
        code = self.gen_expr(stmt.expr, env, out, pad, expected_ty=self.cur_ret_ty)
        live = self._transferencias_del_return(
            live, self._returned_owner_names(stmt.expr, env) - set(alias_guards), out, pad)
        if exclude_name is not None:
            # `code` es la dueña excluida: liberar las otras no la toca.
            for o in takes:
                self._emit_take(o, out, pad)
            self._emit_owner_frees(live, env, out, pad)
            self._emit_alias_return_guards(guarded, alias_guards, env, out, pad)
            if self.in_main_root_scope:
                self._emit_main_root_epilogue(out, pad)
            out.append(f"{pad}return {code};")
            return
        # El valor puede leer memoria que se va a liberar (`return
        # externa.valor` con externa dueña): se evalúa en una variable antes de
        # liberar nada.
        tmp = self._new_tmp()
        out.append(f"{pad}{self.c_type(self.cur_ret_ty)} {tmp} = {code};")
        self._flush_pending_expr_temps(out, pad)
        for o in takes:
            self._emit_take(o, out, pad)
        self._emit_owner_frees(live, env, out, pad)
        self._emit_alias_return_guards(guarded, alias_guards, env, out, pad)
        if self.in_main_root_scope:
            self._emit_main_root_epilogue(out, pad)
        out.append(f"{pad}return {tmp};")
        return

    def _gen_expr_stmt(self, stmt, env, out, indent, rest, pad):
        if isinstance(stmt.expr, PrintExpr):
            self.gen_print(stmt.expr, env, out, pad)
            # gen_print ya usó cada argumento: sus temporales se pueden liberar.
            self._flush_pending_expr_temps(out, pad)
            return
        code = self.gen_expr(stmt.expr, env, out, pad)
        # Una llamada suelta que devuelve un str fresco: se captura para
        # liberarlo (nadie más tiene el puntero).
        code = self._capture_fresh_str_concat_arg(stmt.expr, code, env, out, pad)
        # (void) explícito: evita -Wunused-value de un `f.write(...)?` suelto.
        # Un valor fresco que no es str (de .pop()/.get()/.join(), una llamada
        # fresca...) descartado se captura en un temporal y se libera en el
        # acto, con la misma pregunta que haría un let.
        try:
            disc_ty = self.infer(stmt.expr, env)
        except CodegenError:
            disc_ty = None
        # Métodos cuyo valor es fresco, y una llamada a fn que devuelve un
        # valor fresco ({T}_free decide malloc o arena por el encabezado).
        if (
            disc_ty is not None
            and disc_ty.name != "str"
            and (
                (isinstance(stmt.expr, MethodCall)
                 and stmt.expr.method in ("pop", "remove", "get", "recv", "try_recv", "join", "replace"))
                or (isinstance(stmt.expr, (Call, TryExpr))
                    and disc_ty.name != "Result")
            )
            and self._is_ownable_type(disc_ty)
            and self._let_creates_fresh_owner(stmt.expr, marca_new_generico(stmt.expr), env)
        ):
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(disc_ty)} {tmp} = {code};")
            self._flush_pending_expr_temps(out, pad)
            tmp_env = dict(env)
            tmp_env[tmp] = disc_ty
            self._emit_owner_frees({tmp: "plain"}, tmp_env, out, pad)
            return
        out.append(f"{pad}(void)({code});")
        self._flush_pending_expr_temps(out, pad)
        return

    def _gen_if_stmt(self, stmt, env, out, indent, rest, pad):
        """La sentencia if: condición, cada rama en su scope, lo que consume una
        sola rama, y el armado en C (partida en sus pasos)."""
        inicio_if, cond_code = self._if_condicion(stmt, env, out, pad)
        (outer_before, owner_snapshot, vivos_before, then_ret, else_ret, idx_if,
         duenas_antes, flags_antes, then_env, then_out, then_straight, consumed_by_then,
         vivos_then, flags_de_then, cond_de_then) = self._if_rama_then(
            stmt, env, out, indent, pad, cond_code)
        else_out, else_straight, consumed_by_else, else_env = self._if_rama_else(
            stmt, env, indent, pad, outer_before, owner_snapshot, vivos_before, then_ret,
            else_ret, then_env, consumed_by_then, cond_de_then)
        synthetic_else_frees, after_if_frees = self._if_consumos(
            stmt, out, pad, outer_before, then_ret, else_ret, idx_if, duenas_antes,
            flags_antes, then_env, then_out, then_straight, consumed_by_then,
            flags_de_then, else_out, else_straight, consumed_by_else, else_env)
        return self._if_cierre(
            stmt, env, out, pad, inicio_if, cond_code, vivos_before, then_ret, else_ret,
            then_out, vivos_then, else_out, synthetic_else_frees, after_if_frees)

    def _if_condicion(self, stmt, env, out, pad):
        """La condición, evaluada una sola vez, con sus temporales liberados
        apenas se calcula."""
        inicio_if = len(out)
        # La condición se evalúa una sola vez: sus temporales (copias de
        # get(), str frescos) se liberan apenas se calculó el bool.
        self._can_capture_arg_temps = True
        cond_code = self.gen_expr(stmt.cond, env, out, pad)
        self._can_capture_arg_temps = False
        if self.pending_expr_temps:
            c_tmp = self._new_tmp()
            out.append(f"{pad}bool {c_tmp} = ({cond_code});")
            self._flush_pending_expr_temps(out, pad)
            cond_code = c_tmp
        return inicio_if, cond_code

    def _if_rama_then(self, stmt, env, out, indent, pad, cond_code):
        """La rama then en su scope, con lo que mueve de afuera y los flags que
        nacen en ella."""
        # Una dueña de un scope exterior que una sola rama consume (`if c {
        # push(m) } else { push(x) }`) sigue viva en la otra: se le inyecta el
        # free al final de esa otra rama, si llega a su cierre (si retorna,
        # su return ya la libera). Lo encontró
        # 83_buffer_memoria_fifo_reservoir.scar.
        outer_before = self._live_owners_at_return(None)
        owner_snapshot = [dict(f) for f in self.owner_stack]
        vivos_before = dict(self._vivos_pub)
        # Una rama que siempre retorna, o que sale con `break`, no llega al
        # código de después del if (lo que movió cuenta después del loop, ver
        # _fin_de_loop).
        then_ret = block_never_falls_through(stmt.then_block)
        else_ret = stmt.else_block is not None and block_never_falls_through(stmt.else_block)
        # Flags de loop que nazcan adentro de una rama (ver abajo).
        idx_if = len(out)
        duenas_antes = self._duenas_ahora()
        flags_antes = set(self._flags_de_fn)
        out.append(f"{pad}if ({cond_code}) {{")
        then_env = dict(env)
        then_out = []
        self._push_owner_scope()  # then_block es su propio scope léxico
        self.gen_block(stmt.then_block, then_env, then_out, indent + 1)
        then_owners = self._pop_owner_scope()
        then_straight = self._block_is_straight_line(stmt.then_block) and not self._block_always_returns(stmt.then_block)
        outer_after_then = self._live_owners_at_return(None)
        consumed_by_then = {n for n in outer_before if n not in outer_after_then}
        if then_straight:
            # Dueñas locales al then que siguen vivas en su cierre.
            self._emit_owner_frees(then_owners, then_env, then_out, pad + "    ")
        self._vivos_cerrar(then_owners, then_out, pad + "    ")
        vivos_then = dict(self._vivos_pub)
        flags_de_then = set(self._flags_de_fn) - flags_antes
        # Una variable de afuera que un `break` en esta rama pudo dejar movida
        # pasa a origen "cond:flag" (_fin_de_loop). El else empieza de la foto
        # de antes del if: no puede pisar ese origen.
        cond_de_then = {}
        for frame, copia in zip(self.owner_stack, owner_snapshot):
            for n, o in frame.items():
                if o.startswith("cond:") and copia.get(n) != o:
                    cond_de_then[n] = o
        return (outer_before, owner_snapshot, vivos_before, then_ret, else_ret, idx_if,
                duenas_antes, flags_antes, then_env, then_out, then_straight,
                consumed_by_then, vivos_then, flags_de_then, cond_de_then)

    def _if_rama_else(self, stmt, env, indent, pad, outer_before, owner_snapshot,
                      vivos_before, then_ret, else_ret, then_env, consumed_by_then,
                      cond_de_then):
        """La rama else (si hay) en su scope, igual que la then."""
        else_out = []
        else_owners = {}
        else_straight = False
        consumed_by_else = set()
        else_env = then_env
        if stmt.else_block is not None:
            else_env = dict(env)
            # El else ve la propiedad como estaba antes del if, no como la dejó el
            # then: si then movió `l2`, en runtime else no corrió eso y `l2` sigue
            # siendo suya. Se restauran los frames exteriores (los mismos dicts) y
            # al terminar else se reaplican las bajas de then; la rama que no
            # consumió recibe su free sintético más abajo.
            for frame, copia in zip(self.owner_stack, owner_snapshot):
                frame.clear()
                frame.update(copia)
            self._vivos_pub = dict(vivos_before)  # Idem para el registro
            self._push_owner_scope()  # else_block, scope propio y separado
            self.gen_block(stmt.else_block, else_env, else_out, indent + 1)
            else_owners = self._pop_owner_scope()
            else_straight = self._block_is_straight_line(stmt.else_block) and not self._block_always_returns(stmt.else_block)
            outer_after_else = self._live_owners_at_return(None)
            consumed_by_else = {n for n in outer_before if n not in outer_after_else}
            if else_straight:
                self._emit_owner_frees(else_owners, else_env, else_out, pad + "    ")
            self._vivos_cerrar(else_owners, else_out, pad + "    ")
            if else_ret and not then_ret:
                # solo el camino then sigue después del if
                self._restaurar_duenas(consumed_by_else, owner_snapshot)
            if not then_ret:
                for n in consumed_by_then:
                    self._unmark_owner(n, emitir=False)
                # El flag nació (o se encendió) antes del if: en el camino else vale lo
                # que la variable era, así que el origen condicional sirve para los dos.
                for n, o in cond_de_then.items():
                    frame = next((f for f in reversed(self.owner_stack) if n in f), None)
                    if frame is None:
                        continue
                    actual = frame[n]
                    if actual.startswith("cond:") and actual != o and not else_ret:
                        # cada rama tiene su flag: al final de else, el de then toma su valor
                        # y desde ahí manda uno solo
                        else_out.append(f"{pad}    {o[len('cond:'):]} = {actual[len('cond:'):]};")
                    frame[n] = o
        elif then_ret:
            # sin else: si then siempre retorna, después del if solo se llega por el
            # camino falso, donde lo que then consumió sigue siendo de esta fn
            self._restaurar_duenas(consumed_by_then, owner_snapshot)
        return else_out, else_straight, consumed_by_else, else_env

    def _if_consumos(self, stmt, out, pad, outer_before, then_ret, else_ret, idx_if,
                     duenas_antes, flags_antes, then_env, then_out, then_straight,
                     consumed_by_then, flags_de_then, else_out, else_straight,
                     consumed_by_else, else_env):
        """Lo que consume una sola rama: los flags de loop que nacieron adentro y
        los frees que van en la otra rama o después del if."""
        # Un loop dentro de una rama que mueve y reasigna una variable de afuera
        # le crea un flag que decide su free final. Si la rama no
        # corre, el flag quedaba en false y el valor no se liberaba: antes del
        # if el flag toma lo que la variable era, y una rama que la movió sin
        # loop lo apaga al terminar.
        for flag in [f for f in self._flags_de_fn if f not in flags_antes]:
            n = self._flag_var.get(flag)
            if n is None or n not in outer_before:
                continue
            valor = "true" if n in duenas_antes else "false"
            out.insert(idx_if, f"{pad}{flag} = {valor};")
            ramas = [(then_out, consumed_by_then, then_ret, flag in flags_de_then)]
            if stmt.else_block is not None:
                ramas.append((else_out, consumed_by_else, else_ret, flag not in flags_de_then))
            for rama_out, consumidos, retorna, la_creo in ramas:
                if n in consumidos and not retorna and not la_creo:
                    rama_out.append(f"{pad}    {flag} = false;")
        only_then = consumed_by_then - consumed_by_else
        only_else = consumed_by_else - consumed_by_then
        synthetic_else_frees = {}
        after_if_frees = {}
        if only_else and then_straight and not else_ret:
            self._emit_owner_frees({n: outer_before[n] for n in only_else}, then_env, then_out, pad + "    ")
            self._apagar_flags(only_else, then_out, pad + "    ")
        if only_then and not then_ret:
            if stmt.else_block is not None and else_straight:
                self._emit_owner_frees({n: outer_before[n] for n in only_then}, else_env, else_out, pad + "    ")
                self._apagar_flags(only_then, else_out, pad + "    ")
            elif stmt.else_block is None:
                # Sin else escrito: si then siempre retorna, se libera después del if
                # sin condición; si no, en un else sintético con solo el free (después
                # del if sería double free cuando then sí la consumió).
                if self._block_always_returns(stmt.then_block):
                    after_if_frees = {n: outer_before[n] for n in only_then}
                else:
                    synthetic_else_frees = {n: outer_before[n] for n in only_then}
        return synthetic_else_frees, after_if_frees

    def _if_cierre(self, stmt, env, out, pad, inicio_if, cond_code, vivos_before, then_ret,
                   else_ret, then_out, vivos_then, else_out, synthetic_else_frees,
                   after_if_frees):
        """Las vivas y el armado del if en C, con su else y los frees de
        después; y si quedó como una sola sentencia, la marca para un else-if
        plano."""
        # Después del if el registro de vivas puede tener las entradas de
        # cualquiera de los caminos: la reconciliación del statement los iguala
        if then_ret and not else_ret:
            vivos_fin = dict(self._vivos_pub if stmt.else_block is not None else vivos_before)
        elif else_ret and not then_ret:
            vivos_fin = dict(vivos_then)
        else:
            vivos_fin = dict(vivos_then)
            vivos_fin.update(self._vivos_pub if stmt.else_block is not None else vivos_before)
        self._vivos_pub = vivos_fin
        out.extend(then_out)
        out.append(f"{pad}}}")
        if stmt.else_block is not None:
            simple = self._if_simple
            if simple is not None and simple[0] is else_out and simple[1:] == (0, len(else_out)):
                # `else if` plano: con `else { if ... }` cada eslabón de una cadena
                # anidaba llaves y clang se caía con unos cientos.
                out.append(f"{pad}else")
                out.extend(else_out)
            else:
                out.append(f"{pad}else {{")
                out.extend(else_out)
                out.append(f"{pad}}}")
        elif synthetic_else_frees:
            out.append(f"{pad}else {{")
            self._emit_owner_frees(synthetic_else_frees, env, out, pad + "    ")
            self._apagar_flags(synthetic_else_frees, out, pad + "    ")
            out.append(f"{pad}}}")
        if after_if_frees:
            self._emit_owner_frees(after_if_frees, env, out, pad)
            self._apagar_flags(after_if_frees, out, pad)
        # Este if quedó como una sola sentencia de C (nada antes de su `if (`
        # ni después de su cierre): el if de afuera puede ponerlo como `else if`
        # plano.
        if out[inicio_if:inicio_if + 1] == [f"{pad}if ({cond_code}) {{"] and not after_if_frees:
            # la lista misma, no su id(): un id() liberado se reusa
            self._if_simple = (out, inicio_if, len(out))
        else:
            self._if_simple = None
        return

    def _asignar_a_chan_duena(self, stmt, ty, target_code, expr_code, env, out, pad):
        """`ch = otro` con ch dueña de su referencia a un Chan. El valor nuevo
        pasa a ser una referencia propia: uno nuevo (`chan_new()`) se toma tal
        cual y uno de alguien (otra variable, la ligada de un `get()`, un
        parámetro, un campo) se incrementa. Recién después se suelta la
        referencia vieja, así `ch = ch` no libera nada."""
        inner = ty.args[0] if ty.args else T_I32
        code = self._chan_para_contenedor(stmt.expr, inner, expr_code, env, out, pad)
        tmp = self._new_tmp()
        out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
        self._flush_pending_expr_temps(out, pad)
        out.append(f"{pad}scar_chan_decref_{self._mangled_name(inner)}({target_code});")
        out.append(f"{pad}{target_code} = {tmp};")

    def _gen_assign_stmt(self, stmt, env, out, indent, rest, pad):
        root = self._assign_root(stmt.target)
        if root.name not in env:
            raise CodegenError(f"variable no declarada: {root.name}")
        target_code = self.gen_expr(stmt.target, env, out, pad)
        # El tipo del destino se pasa como esperado: `c = None` con
        # c: Option<Chan<i32>> tiene que ser Option_Chan_i32_None(), no el
        # Option<i32> por defecto.
        root_for_expected = self._assign_root(stmt.target)
        expected_ty_for_expr = env.get(root_for_expected.name) if isinstance(stmt.target, Ident) else None
        if isinstance(stmt.target, FieldAccess):
            # también un campo: `l.items = vec_new()` es Vec<str> si el campo lo
            # es
            expected_ty_for_expr = self.infer(stmt.target, env)
        expr_code = self.gen_expr(stmt.expr, env, out, pad, expected_ty=expected_ty_for_expr)
        # Un str dueño de su valor actual: el valor viejo se libera antes de
        # pisarlo, pero después de evaluar el nuevo (`linea = linea + "]"`
        # todavía lo lee), así que el valor nuevo va primero a un temporal. No
        # se vuelve a marcar: la entrada ya está en el frame del let, y
        # marcarla acá la ataría al frame de un loop/if anidado.
        root_ty = env.get(root.name)
        if (
            isinstance(stmt.target, Ident)
            and root_ty is not None
            and root_ty.name == CHAN_MARK
            and self._owner_origin(root.name) == "chan"
        ):
            return self._asignar_a_chan_duena(stmt, root_ty, target_code, expr_code, env, out, pad)
        if (
            isinstance(stmt.target, Ident)
            and root_ty is not None
            and root_ty.name == "str"
            and not self._is_owner(root.name)
            and (root.name in self._str_mut_promovidas or root.name in self._desmarcadas)
            and self._decl_frame_of(root.name) is not None
            and self._decl_frame_of(root.name) < len(self.owner_stack)
        ):
            # Un str que es o fue dueña (y se movió a un struct, un Vec, una
            # task...): asignarle algo la vuelve dueña en el frame donde nació,
            # copiando si el valor no es nuevo. Si no, quedaba apuntando
            # a un literal o a un str ajeno, y el free de la otra rama de un if lo
            # liberaba.
            if not self._let_creates_fresh_owner(stmt.expr, marca_new_generico(stmt.expr), env):
                self.needs_str_concat = True
                expr_code = f'scar_str_concat({expr_code}, "")'
            out.append(f"{pad}{target_code} = {expr_code};")
            self._flush_pending_expr_temps(out, pad)
            self.owner_stack[self._decl_frame_of(root.name)][root.name] = "plain"
            return
        if (
            isinstance(stmt.target, Ident)
            and root_ty is not None
            and root_ty.name == "str"
            and self._is_owner(root.name)
        ):
            # Un valor que no es nuevo (un literal, otra variable) se copia: la
            # variable tiene que ser dueña de lo que apunta, o su próximo free
            # libera un literal o un buffer ajeno.
            if not self._let_creates_fresh_owner(stmt.expr, marca_new_generico(stmt.expr), env):
                self.needs_str_concat = True
                expr_code = f'scar_str_concat({expr_code}, "")'
            tmp = self._new_tmp()
            out.append(f"{pad}const char* {tmp} = {expr_code};")
            self._flush_pending_expr_temps(out, pad)
            origen = self._owner_origin(root.name) or "plain"
            if origen.startswith("cond:"):
                # dueña solo si su flag lo dice (un break pudo haberla movido); el
                # valor nuevo sí es suyo
                flag = origen[len("cond:"):]
                out.append(f"{pad}if ({flag}) {{ scar_free((char*){target_code}); }}")
                out.append(f"{pad}{target_code} = {tmp};")
                out.append(f"{pad}{flag} = true;")
                return
            out.append(f"{pad}scar_free((char*){target_code});")
            out.append(f"{pad}{target_code} = {tmp};")
            return
        # `a = b` con Vec/Map/struct: se libera el valor viejo de `a` (después
        # de evaluar el nuevo, que puede leerlo: `cuerpo = f(cuerpo)`) y, si b
        # es dueña, la propiedad pasa a `a` (_note_owner_transfer). Si no, las
        # dos liberaban el mismo buffer y el viejo de `a` se perdía.
        if (
            isinstance(stmt.target, Ident)
            and root_ty is not None
            and root_ty.name != "str"
            and self._is_ownable_type(root_ty)
        ):
            return self._asignar_a_duena(
                stmt, env, out, pad, root, target_code, expr_code, root_ty)
        if isinstance(stmt.target, FieldAccess):
            if self._gen_field_assign_move(stmt, target_code, expr_code, env, out, pad):
                return
        out.append(f"{pad}{target_code} = {expr_code};")
        self._flush_pending_expr_temps(out, pad)
        return

    def _asignar_a_duena(self, stmt, env, out, pad, root, target_code, expr_code, root_ty):
        """Asignar a una variable dueña (str, struct, Vec, Map, Option...): soltar
        el valor viejo, tomar el nuevo y dejar el registro de propiedad al día."""
        if self._is_owner(root.name):
            origin = self._owner_origin(root.name)
            assert origin is not None, f"'{root.name}' es dueña sin origen"
            c_ty = self.c_type(root_ty)
            if root_ty.name in ("Option", "Result") and not self._valor_transferible(stmt.expr, env, origin):
                # `t = p` con un Option y p un valor que no es de nadie acá (un
                # parámetro): t recibe una copia propia, como un str.
                expr_code = self._clone_value_expr(root_ty, expr_code)
            tmp = self._new_tmp()
            out.append(f"{pad}{c_ty} {tmp} = {expr_code};")
            self._flush_pending_expr_temps(out, pad)
            # `m = paso(m, x)` con una fn que devuelve su parámetro: el valor nuevo
            # es el mismo objeto que el viejo y no se libera. Se compara en runtime
            same = self._same_object_cond(root_ty, target_code, tmp)
            dif = self._wl_diferido.get(root.name)
            if dif is not None:
                # La primera reasignación de la vuelta guarda el valor viejo (el que ve
                # la ligada del while-let) en el slot; las siguientes ya no las ve nadie
                n = dif["nombre"]
                distinto = f"!({same})" if same is not None else "1"
                out.append(f"{pad}if ({distinto} && {n}.tag == 0) {{")
                out.append(f"{pad}    {n} = {target_code};")
                out.append(f"{pad}}} else if ({distinto}) {{")
                self._emit_owner_frees({root.name: origin}, env, out, pad + "    ")
                out.append(f"{pad}}}")
            elif same is not None:
                out.append(f"{pad}if (!({same})) {{")
                self._emit_owner_frees({root.name: origin}, env, out, pad + "    ")
                out.append(f"{pad}}}")
            else:
                self._emit_owner_frees({root.name: origin}, env, out, pad)
            out.append(f"{pad}{target_code} = {tmp};")
            if origin and origin.startswith("cond:"):
                # El valor nuevo es de esta fn; con un flag de break, lo mismo (ver
                # _fin_de_loop).
                out.append(f"{pad}{origin[len('cond:'):]} = true;")
        else:
            # El destino no es dueño ahora (se movió antes, p. ej. como argumento)
            # y esto lo trae de vuelta (`cuerpo = chequeo.cuerpo`): no hay valor
            # viejo que liberar.
            #
            # Salvo dentro de un loop: el cuerpo se genera una vez y corre N
            # vueltas, así que desde la segunda sí hay un valor viejo (el de la
            # vuelta anterior). Un flag de loop, que solo runtime conoce, lo
            # distingue: falso en la primera vuelta, verdadero después (
            # también para Vec/Map: `v = duplicar(v)`).
            loop_frame = self._loop_frames[-1] if self._loop_frames else None
            # Salvo que el valor viejo sea un argumento Vec/Map de la propia
            # llamada (`v = f(..., v, ...)`): la fn ya lo liberó al cerrar su
            # scope, y liberarlo acá sería double free.
            vecmap_already_freed_by_callee = root_ty.name in (VEC_MARK, MAP_MARK) and (
                self._is_vecmap_consumed_by_call(stmt.expr, root.name)
            )
            use_loop_flag = (
                loop_frame is not None
                and (root_ty.name in self.structs or root_ty.name in (VEC_MARK, MAP_MARK))
                and self._decl_frame_of(root.name) is not None
                and not vecmap_already_freed_by_callee
            )
            if use_loop_flag:
                # un solo flag por variable en loops anidados
                flag = self._flag_de_loop(root.name) or loop_frame["flags"].get(root.name)
                if flag is None:
                    flag = self._new_tmp()
                    loop_frame["flags"][root.name] = flag
                    # Se declara antes del loop, en el `out` de afuera del cuerpo, en
                    # false: todavía no corrió ninguna vuelta.
                    loop_frame["out"].insert(
                        loop_frame["idx"],
                        f'{loop_frame["pad"]}bool {flag} = false;',
                    )
                # El valor nuevo va a un temporal antes de tocar el destino: puede
                # leer el viejo (`m = entrenar(m, ...)?`).
                c_ty = self.c_type(root_ty)
                tmp = self._new_tmp()
                out.append(f"{pad}{c_ty} {tmp} = {expr_code};")
                self._flush_pending_expr_temps(out, pad)
                if root_ty.name in (VEC_MARK, MAP_MARK):
                    # Una fn que muta in-place y devuelve el mismo Vec/Map (`v.set(...);
                    # return v`) deja el mismo buffer de los dos lados: se libera solo si
                    # cambió. Vec es por valor (se compara .data); Map es un puntero.
                    if root_ty.name == VEC_MARK:
                        out.append(
                            f"{pad}if ({flag} && (void*){target_code}.data != (void*){tmp}.data) {{"
                        )
                    else:
                        out.append(f"{pad}if ({flag} && (void*){target_code} != (void*){tmp}) {{")
                else:
                    # Lo mismo para un struct: `m = paso(m, x)` con una fn que devuelve su
                    # parámetro.
                    same = self._same_object_cond(root_ty, target_code, tmp)
                    if same is not None:
                        out.append(f"{pad}if ({flag} && !({same})) {{")
                    else:
                        out.append(f"{pad}if ({flag}) {{")
                self._emit_owner_frees({root.name: "plain"}, env, out, pad + "    ")
                out.append(f"{pad}}}")
                out.append(f"{pad}{target_code} = {tmp};")
                out.append(f"{pad}{flag} = true;")
                # Origen "cond:<flag>": el mismo flag protege el free final del scope
                # (o de un return). Si el loop no corrió, la variable sigue siendo el
                # alias original y no se libera.
                frame = self._decl_frame_of(root.name)
                self.owner_stack[frame][root.name] = f"cond:{flag}"
                if not self._try_neutralize_extracted_field(stmt.expr, root_ty, env, out, pad):
                    self._note_owner_transfer(stmt.expr, root_ty)
                return
            out.append(f"{pad}{target_code} = {expr_code};")
            self._flush_pending_expr_temps(out, pad)
            # El valor recién adquirido es fresco: el destino vuelve a ser dueño en
            # el frame donde nació (_decl_frame_of), nunca en el más interno (un
            # alias reasignado en un if dentro de un loop se liberaría en cada
            # vuelta). Struct, Vec y Map son "plain" ({T}_free decide malloc
            # o arena por el encabezado).
            if root_ty.name in (VEC_MARK, MAP_MARK):
                frame = self._decl_frame_of(root.name)
                if frame is not None:
                    self.owner_stack[frame][root.name] = "plain"
            elif root_ty.name in self.structs:
                frame = self._decl_frame_of(root.name)
                if frame is not None:
                    self.owner_stack[frame][root.name] = "plain"
        # En los dos casos: si el valor nuevo es otra dueña viva (`cuerpo =
        # recortado`) o un campo de una (`cuerpo = chequeo.cuerpo`), se le saca
        # la propiedad, o su free libera lo que el destino acaba de heredar. Un
        # campo se vacía en su struct (_try_neutralize_extracted_field), que
        # sigue liberando el resto.
        if not self._try_neutralize_extracted_field(stmt.expr, root_ty, env, out, pad):
            self._note_owner_transfer(stmt.expr, root_ty)
        return

    def _gen_while_stmt(self, stmt, env, out, indent, rest, pad):
        # El safepoint de cancelación de la task está en el back-edge. Sin
        # tasks no se emite. Se revisa cada 256 vueltas, no en cada una: el
        # atomic_load por vuelta impedía que gcc desenrollara el loop, y la cancelación ya es "pronto", no "ya". El contador es un
        # temporal por loop.
        #
        # El frame de loop se empuja antes de emitir nada: `idx` es dónde, en
        # el `out` de afuera, se declaran los flags de las reasignaciones del
        # cuerpo. Se saca al final aunque no tenga flags.
        self._loop_frames.append({"idx": len(out), "pad": pad, "out": out, "flags": {},
                                 "depth": len(self.owner_stack), "duenas": self._duenas_ahora()})
        self._duenas_con_flag(stmt)
        sp_tmp = self._new_tmp() if self.has_tasks else None
        if self.has_tasks:
            out.append(f"{pad}uint32_t {sp_tmp} = 0;")
        # La condición se genera aparte. Si necesita sentencias previas
        # (temporales de get(), str frescos...), no pueden ir antes del
        # `while (...)` (correrían una vez): el bucle pasa a `while (1) {
        # previas; bool c = cond; liberar; if (!c) break; ... }`, y `continue`
        # recalcula la condición.
        cond_pre = []
        self._can_capture_arg_temps = True
        cond_code = self.gen_expr(stmt.cond, env, cond_pre, pad + "    ")
        self._can_capture_arg_temps = False
        if cond_pre or self.pending_expr_temps:
            out.append(f"{pad}while (1) {{")
            out.extend(cond_pre)
            c_tmp = self._new_tmp()
            out.append(f"{pad}    bool {c_tmp} = ({cond_code});")
            self._flush_pending_expr_temps(out, pad + "    ")
            out.append(f"{pad}    if (!{c_tmp}) break;")
        else:
            out.append(f"{pad}while ({cond_code}) {{")
        body_out = []
        if self.has_tasks:
            body_out.append(
                f"{pad}    if (({sp_tmp}++ & 0xFFu) == 0) scar_safepoint();"
            )
        body_env = dict(env)
        self._cuerpo_de_loop(stmt.body, body_env, body_out, indent, pad)
        out.extend(body_out)
        out.append(f"{pad}}}")
        self._fin_de_loop(self._loop_frames.pop())
        return

    def _gen_while_let_stmt(self, stmt, env, out, indent, rest, pad):
        val_ty = self.infer(stmt.expr, env)
        # el match sobre un Result se baja a un while let Ok(x): Result_T y
        # Option_T tienen la misma forma (tag 1 y value)
        if getattr(stmt, "patron", "Some") == "Ok" and val_ty.name == "Result":
            pass
        elif val_ty.name != "Option":
            raise CodegenError(
                f"'while let Some(...)' requiere un Option, se dio {val_ty!r}"
            )
        inner_ty = val_ty.args[0] if val_ty.args else T_I32
        c_name = self.c_type(val_ty)
        inner_pad = pad + "    "
        diferido = self._while_let_slot_diferido(stmt, val_ty, env, out, pad)
        tmp = self._new_tmp()
        # Mismo frame de loop que WhileStmt.
        self._loop_frames.append({"idx": len(out), "pad": pad, "out": out, "flags": {},
                                 "depth": len(self.owner_stack), "duenas": self._duenas_ahora()})
        self._duenas_con_flag(stmt)
        sp_tmp = self._new_tmp() if self.has_tasks else None
        if self.has_tasks:
            out.append(f"{pad}uint32_t {sp_tmp} = 0;")
        out.append(f"{pad}while (1) {{")
        if diferido is not None:
            # el valor viejo de la vuelta anterior: su ligada ya murió
            self._liberar_slot_diferido(diferido, env, out, inner_pad)
        # stmt.expr se reevalúa en cada vuelta, como en el intérprete: lo que
        # necesite un ? anidado se inyecta acá adentro, antes del tag.
        expr_code = self.gen_expr(stmt.expr, env, out, inner_pad)
        out.append(f"{inner_pad}{c_name} {tmp} = {expr_code};")
        out.append(f"{inner_pad}if ({tmp}.tag != 1) break;")
        inner_env = dict(env)
        inner_env[stmt.pattern] = inner_ty
        out.append(f"{inner_pad}{self.c_type(inner_ty)} {stmt.pattern} = {tmp}.value;")
        prev_payload = self._opt_payload_of
        self._opt_payload_of = dict(prev_payload)
        if (isinstance(stmt.expr, Ident)
                and (self._is_option_struct(val_ty)
                     # lo mismo para el Ok(x) de un match sobre un Result<Struct> (un Err
                     # tiene .err NULL: liberarlo no hace nada)
                     or (val_ty.name == "Result" and bool(val_ty.args)
                         and val_ty.args[0].name in self.structs))
                and self._is_owner(stmt.expr.name)):
            self._opt_payload_of[stmt.pattern] = stmt.expr.name
            if val_ty.name == "Result":
                self._take_result.add(stmt.expr.name)
        else:
            self._opt_payload_of.pop(stmt.pattern, None)
        # Mismo safepoint que WhileStmt (cada 256 vueltas).
        self._push_owner_scope()  # Cuerpo del while-let, scope propio
        # Si la ligada queda dueña de lo que trae (recv() de Chan<str>/
        # Chan<Struct>, pop()/get() frescos..., ver
        # _while_let_binds_fresh_value), se registra con el scope del cuerpo
        # ya abierto: se libera al cerrar cada vuelta.
        if self._is_ownable_type(inner_ty) and self._while_let_binds_fresh_value(stmt.expr, env):
            self._mark_owner(stmt.pattern, "plain")
        elif getattr(stmt, "copia_ligada", False) and stmt.pattern not in self._opt_payload_of:
            # `while let Ok(b) = r` (y el match sobre r) presta el Vec/Map de r: la
            # ligada es una copia propia, porque si el cuerpo la mueve r seguiría
            # liberando el mismo buffer.
            out.append(f"{inner_pad}{stmt.pattern} = {self._clone_value_expr(inner_ty, stmt.pattern)};")
            self._mark_owner(stmt.pattern, "plain")
        elif inner_ty.name == CHAN_MARK and self._while_let_binds_chan_owner(stmt.expr, env):
            # Chan no está en _is_ownable_type: origen "chan" para que se
            # decremente en vez de liberar (_while_let_binds_chan_owner).
            self._mark_owner(stmt.pattern, "chan")
        # la ligada se registra antes del safepoint de la vuelta
        self._vivos_sync(inner_env, out, inner_pad)
        if self.has_tasks:
            out.append(
                f"{inner_pad}if (({sp_tmp}++ & 0xFFu) == 0) scar_safepoint();"
            )
        # La ligada se declara en el mismo bloque de C que el cuerpo, como los
        # parámetros de una fn: un `let x` en el cuerpo va por el camino de
        # sombreado del mismo bloque, o el C redeclara `x`.
        self._gen_stmts_shadow_safe(stmt.body.stmts, inner_env, out, indent + 1,
                                    declared_init={stmt.pattern})
        body_owners = self._pop_owner_scope()
        if (self._block_is_straight_line(stmt.body)
                and not self._block_always_returns(stmt.body)):
            # Como en WhileStmt, mueren en cada vuelta.
            self._emit_owner_frees(body_owners, inner_env, out, inner_pad)
        self._vivos_cerrar(body_owners, out, inner_pad)
        self._opt_payload_of = prev_payload
        out.append(f"{pad}}}")
        self._fin_de_loop(self._loop_frames.pop())
        if diferido is not None:
            # salida por break: el de la última vuelta
            self._wl_diferido = diferido["prev"]
            self._liberar_slot_diferido(diferido, env, out, pad)
        return

    def _gen_for_stmt(self, stmt, env, out, indent, rest, pad):
        start_ty = self.infer(stmt.start, env)
        end_ty = self.infer(stmt.end, env)
        if not (start_ty.is_integer() and end_ty.is_integer()):
            raise CodegenError(
                f"el rango de 'for' debe ser de enteros, se dio "
                f"{start_ty}..{end_ty}"
            )
        # i32..i32 da una variable i32; con un extremo i64, i64.
        var_ty = numeric_result(start_ty, end_ty)
        var_c = self.c_type(var_ty)
        var = stmt.var
        # Mismo frame de loop que WhileStmt.
        self._loop_frames.append({"idx": len(out), "pad": pad, "out": out, "flags": {},
                                 "depth": len(self.owner_stack), "duenas": self._duenas_ahora()})
        self._duenas_con_flag(stmt)
        # El rango se evalúa una vez, como `range(start, end)` del intérprete:
        # `for i in 0..v.len()` con un cuerpo que empuja en v no puede cambiar
        # las vueltas.
        self._can_capture_arg_temps = True
        start_code = self.gen_expr(stmt.start, env, out, pad)
        end_code = self.gen_expr(stmt.end, env, out, pad)
        self._can_capture_arg_temps = False
        bound_tmp = self._new_tmp()
        out.append(f"{pad}{var_c} {bound_tmp}_ini = {start_code};")
        out.append(f"{pad}{var_c} {bound_tmp}_fin = {end_code};")
        self._flush_pending_expr_temps(out, pad)
        start_code, end_code = f"{bound_tmp}_ini", f"{bound_tmp}_fin"
        # Mismo safepoint que WhileStmt, con `var` como contador (el AND sobre
        # un int32_t negativo está definido; la fase no importa).
        out.append(
            f"{pad}for ({var_c} {var} = {start_code}; {var} < {end_code}; "
            f"{var}++) {{"
        )
        inner_env = dict(env)
        inner_env[var] = var_ty
        body_out = []
        if self.has_tasks:
            body_out.append(
                f"{pad}    if (({var} & 0xFF) == 0) scar_safepoint();"
            )
        self._cuerpo_de_loop(stmt.body, inner_env, body_out, indent, pad)
        out.extend(body_out)
        out.append(f"{pad}}}")
        self._fin_de_loop(self._loop_frames.pop())
        return

    def _cuerpo_de_loop(self, body, body_env, body_out, indent, pad):
        """El cuerpo de un while o un for en su propio scope. Las dueñas locales
        al cuerpo mueren en cada vuelta, antes de volver a evaluar la condición
        (si el cuerpo siempre retorna, cada return ya liberó)."""
        self._push_owner_scope()
        self.gen_block(body, body_env, body_out, indent + 1)
        body_owners = self._pop_owner_scope()
        if (self._block_is_straight_line(body)
                and not self._block_always_returns(body)):
            self._emit_owner_frees(body_owners, body_env, body_out, pad + "    ")
        self._vivos_cerrar(body_owners, body_out, pad + "    ")

    def gen_block(self, block, env, out, indent):
        self._gen_stmts_shadow_safe(block.stmts, env, out, indent)

    def _let_from_param_returning_call(self, stmt, ty) -> bool:
        """`let r = f(..., a, ...)` donde f devuelve siempre su parámetro k
        (fresh_owned.py) y el argumento k es una variable o un campo. r es el
        mismo objeto que a:
          - struct (se recibe prestado): r es un alias de a, anotado en
            _alias_root para que un `return r` no libere a;
          - Vec/Map (se mueven a la llamada): el buffer vuelve, y r es su
            dueña.
        True si aplicó (el llamador no hace nada más)."""
        expr = stmt.expr
        if not (isinstance(expr, Call) and isinstance(expr.callee, Ident)):
            return False
        own = self.fn_ownership.get(expr.callee.name)
        k = own.ret_param if own is not None else None
        if k is None or k >= len(expr.args):
            return False
        if ty.name in (VEC_MARK, MAP_MARK):
            self._mark_owner(stmt.name, "plain")
            return True
        if ty.name in self.structs:
            root_name = self._ident_root_name(expr.args[k])
            if root_name is None:
                return False
            self._alias_root[stmt.name] = self._resolve_alias_root(root_name)
            return True
        return False

    def _gen_stmts_shadow_safe(self, stmts, env, out, indent, declared_init=None):
        """Genera un bloque recto donde un `let` puede redeclarar un nombre del
        mismo bloque (el checker y el intérprete lo aceptan; en C sería
        "redefinition"). No se renombran variables: desde el `let` que
        redeclara, el resto del bloque va en un `{}` propio (con su frame de
        owner_stack y sus free antes de cerrar), y el sombreado de C hace el
        resto. Cada nueva redeclaración anida otro `{}`.

        Límite conocido: los análisis por nombre sobre `rest`
        (_block_reassigns_via_concat) no saben que un `let` posterior
        sombrea; ningún programa del repo lo ejercita."""
        pad = "    " * indent
        declared = set(declared_init or ())
        n = len(stmts)
        self._vivos_sync(env, out, pad)  # Nacidas al abrir el bloque (while let, for)
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, LetStmt) and stmt.name in declared:
                sub_stmts = stmts[i:]
                sub_block = _ShadowSubBlock(sub_stmts)
                name = stmt.name
                # El valor viejo de `name` se copia a un temporal antes de abrir el
                # scope nuevo:
                #  1. `let x = x + 1`: dentro de `T x = <rhs>;` la `x` de C ya es la
                #     nueva, sin inicializar; el lado derecho lee el temporal
                #     (self._shadow_rhs).
                #  2. La dueña vieja pasa a llamarse como el temporal, visible desde
                #     los scopes hijos: un `return` de adentro junta los frames por
                #     nombre y si no la perdía.
                old_ty = env.get(name)
                rhs_uses_old = _expr_mentions_name(stmt.expr, name)
                old_is_owner = any(name in frame for frame in self.owner_stack)
                shadow_tmp = None
                if old_ty is not None and (rhs_uses_old or old_is_owner):
                    shadow_tmp = f"__scar_shadow_{name}_{self._new_tmp()[len('__scar_tmp'):]}"
                    c_old = name
                    out.append(f"{pad}{self.c_type(old_ty)} {shadow_tmp} = {c_old};")
                    env[shadow_tmp] = old_ty
                    if old_is_owner:
                        # La dueña vieja pasa al temporal (_handoff_shadowed_owner): su
                        # entrada del registro apuntaba a la variable vieja, que desde el `{` de
                        # abajo queda tapada.
                        for frame in reversed(self.owner_stack):
                            if name in frame:
                                prev_vo = self._vivos_out
                                self._vivos_out = (out, pad)
                                self._vivo_baja_inmediata(frame, name)
                                self._vivos_out = prev_vo
                                break
                inner_env = dict(env)
                out.append(f"{pad}{{")
                self._push_owner_scope()
                # El `let` que redeclara va primero y aparte: su lado derecho todavía
                # ve el valor viejo, registrado con su nombre (la nueva se registra
                # después), así que si lo consume (`let v = pasar(v)`) la transferencia
                # lo encuentra y el temporal no hereda nada.
                if shadow_tmp is not None and rhs_uses_old:
                    self._shadow_rhs[name] = shadow_tmp
                try:
                    self.gen_stmt(stmt, inner_env, out, indent + 1, rest=sub_stmts[1:])
                finally:
                    self._shadow_rhs.pop(name, None)
                if shadow_tmp is not None:
                    self._handoff_shadowed_owner(name, shadow_tmp)
                self._gen_stmts_shadow_safe(sub_stmts[1:], inner_env, out, indent + 1,
                                            declared_init={name})
                sub_owners = self._pop_owner_scope()
                if (self._block_is_straight_line(sub_block)
                        and not self._block_always_returns(sub_block)):
                    # Si todo camino de este `{}` termina en un `return`, ese return ya
                    # liberó: el free acá sería código muerto.
                    self._emit_owner_frees(sub_owners, inner_env, out, pad + "    ")
                self._vivos_cerrar(sub_owners, out, pad + "    ")
                out.append(f"{pad}}}")
                return
            if isinstance(stmt, LetStmt) and stmt.name in env:
                # Sombreado entre bloques: el nombre viene de un bloque de afuera (C lo
                # permite sin `{}` propio), con los mismos dos problemas.
                declared.add(stmt.name)
                self._gen_cross_block_shadow_let(stmt, env, out, indent, rest=stmts[i + 1:])
                continue
            if isinstance(stmt, LetStmt):
                declared.add(stmt.name)
            self.gen_stmt(stmt, env, out, indent, rest=stmts[i + 1:])

    def _gen_cross_block_shadow_let(self, stmt, env, out, indent, rest):
        """`let x = ...` dentro de un bloque cuando hay una `x` visible de un
        bloque de afuera:
          - si el lado derecho lee la `x` vieja, se copia antes a un temporal
            y el lado derecho lee de ahí;
          - si la `x` vieja es dueña en un frame de afuera, un `return` desde
            adentro la libera a través del temporal (_shadow_free_alias). A
            diferencia del mismo bloque, la dueña no se renombra: al cerrar
            el bloque la `x` de afuera vuelve a ser visible."""
        pad = "    " * indent
        name = stmt.name
        old_ty = env.get(name)
        rhs_uses_old = _expr_mentions_name(stmt.expr, name)
        cur = len(self.owner_stack) - 1
        owner_idx = None
        for idx in range(cur - 1, -1, -1):
            if name in self.owner_stack[idx]:
                owner_idx = idx
                break
        if old_ty is None or (not rhs_uses_old and owner_idx is None):
            self.gen_stmt(stmt, env, out, indent, rest=rest)
            return
        shadow_tmp = f"__scar_shadow_{name}_{self._new_tmp()[len('__scar_tmp'):]}"
        c_old = name
        out.append(f"{pad}{self.c_type(old_ty)} {shadow_tmp} = {c_old};")
        env[shadow_tmp] = old_ty
        if rhs_uses_old:
            self._shadow_rhs[name] = shadow_tmp
        try:
            self.gen_stmt(stmt, env, out, indent, rest=rest)
        finally:
            self._shadow_rhs.pop(name, None)
        # Solo si la dueña vieja sigue viva (el lado derecho pudo consumirla).
        if owner_idx is not None and name in self.owner_stack[owner_idx]:
            self._shadow_free_alias[(owner_idx, name)] = (shadow_tmp, cur)

    # ---- funciones y programa ----
    def gen_fn(self, decl: FnDecl):
        (params, ret, env, param_list, out, prev_tbind, prev_ret_ty, prev_tmp,
         prev_fn_name, prev_vivos, vivos_usados) = self._fn_inicio(
            decl)
        body_env = self._fn_parametros(decl, params, env, out)
        out = self._fn_cuerpo(
            decl, out, prev_tbind, prev_ret_ty, prev_tmp, prev_fn_name, prev_vivos,
            vivos_usados, body_env)
        return self._fn_cierre(decl, ret, param_list, out)

    def _fn_inicio(self, decl):
        """La firma, el entorno de los parámetros y el estado por función que
        gen_fn guarda para restaurar al final."""
        # (C8) se asignan solo en algunas ramas y la pasada las devuelve siempre
        param_list = None
        # Una task se compila igual que una fn; además se envuelve en un
        # wrapper de pthread (_gen_task_support), y solo se llama por spawn.
        params, ret = self.task_sigs[decl.name] if decl.is_task else self.fn_sigs[decl.name]
        env = {p.name: t for p, t in zip(decl.params, params)}
        if decl.is_task:
            param_list = self._task_c_param_list(decl, params)
        else:
            param_list = ", ".join(f"{self.c_type(t)} {p.name}" for p, t in zip(decl.params, params))
        out = []
        prev_tbind = self._tbind
        self._tbind = self.generic_fn_bindings.get(decl.name)
        prev_ret_ty, prev_tmp, prev_fn_name = self.cur_ret_ty, self.tmp_counter, self.cur_fn_name
        self.cur_ret_ty = ret
        self.cur_fn_name = decl.name
        self.tmp_counter = 0
        self._alias_root = {}  # no se arrastra entre funciones
        self._shadow_rhs = {}  # idem
        self._shadow_free_alias = {}  # idem
        self._consume_flags = {}  # idem
        self._opt_payload_of = {}  # idem
        self._take_result = set()  # idem
        self._pending_takes = []
        self._wl_diferido = {}  # idem
        self._pending_flag_clears = []
        self._decl_frame = {}  # idem, ver constructor
        self._str_mut_promovidas = set()  # ver LetStmt (str_mut_will_concat) y AssignStmt
        self._desmarcadas = set()  # ver _unmark_owner
        self._loop_frames = []  # idem, ver constructor
        self._flags_de_fn = []  # flags de loop, declarados al principio
        self._flag_var = {}     # flag -> variable de la que dice si es dueña
        self._cond_base = {}    # flag -> origen que tenía la variable antes del break
        self._accept_chan_vars = set()  # leak accept_chan(): idem, no arrastrar entre funciones
        # Registro de vivas, por función. Los Chan parámetro de una task no se
        # registran: su wrapper ya los decrementa al cancelar.
        prev_vivos = (self._vivos_fn_on, self._vivos_pub, self._vivos_hist, self._vivos_excluir)
        self._vivos_fn_on = True  # también sin tasks (panic de main)
        self._vivos_pub = {}
        self._vivos_hist = {}
        self._vivos_excluir = (
            {p.name for p, t in zip(decl.params, params) if t.name == CHAN_MARK}
            if decl.is_task else set()
        )
        vivos_usados = False
        self._push_owner_scope()  # Scope raíz de la función/task
        return (params, ret, env, param_list, out, prev_tbind, prev_ret_ty, prev_tmp,
                prev_fn_name, prev_vivos, vivos_usados)

    def _fn_parametros(self, decl, params, env, out):
        """Qué parámetros recibe la fn como dueña, y el safepoint de prólogo."""
        # Qué parámetros recibe esta fn como dueña:
        #   - Vec, Map y Option de ellos: siempre (fn o task); quien llama los
        #     movió (_is_moved_container_type).
        #   - En una task: str (dueña si la llamada movió un str propio, flag
        #     oculto de _gen_spawn), Chan (la referencia que _gen_spawn
        #     incrementó), struct y Option<Struct> (movidos por spawn).
        #   - En una fn: el struct u Option<Struct> que consume en algún camino
        #     (lo recibe por valor).
        # Un struct que una fn no consume se recibe prestado: quien llama lo
        # sigue usando y liberando.
        for p, t in zip(decl.params, params):
            if self._is_moved_container_type(t):
                # Si este callee no se queda con el Vec/Map, nadie lo libera: quien
                # llama ya soltó la propiedad (_note_owner_transfer).
                self._mark_owner(p.name, "plain")
            elif decl.is_task and t.name == "str":
                self._mark_owner(p.name, f"cond:{self._str_owned_flag_name(p.name)}")
                self.needs_task_str_free = True
            elif decl.is_task and t.name == CHAN_MARK:
                # _gen_spawn ya incrementó el refcount: este parámetro decrementa una
                # vez al cerrar (origen "chan").
                self._mark_owner(p.name, "chan")
            elif decl.is_task and (t.name in self.structs or self._is_option_struct(t)):
                # Un struct (o un Option<Struct>) que llega por spawn llegó movido: la
                # task es su dueña.
                self._mark_owner(p.name, "plain")
            elif (not decl.is_task and self._is_option_struct(t)
                    and decl.params.index(p) in self.consumed_option_params.get(decl.name, ())):
                # Un Option<Struct> cuyo contenido la fn puede quedarse (un `while let
                # Some(x) = p` que mueve x): lo recibe por valor y es su dueña. Donde lo
                # consume, el take de _note_owner_transfer lo deja en None; al salir se
                # libera lo que quede.
                self._mark_owner(p.name, "plain")
            elif (not decl.is_task and t.name in self.structs
                    and decl.params.index(p) in self.consumed_params.get(decl.name, ())):
                # Un struct que la fn consume en algún camino se recibe por valor: la
                # fn es su dueña y lo libera donde no lo consumió. Como
                # puede consumirlo solo en algunos caminos (un loop dentro de un `else
                # if`), la propiedad se sigue en runtime con un flag que cada
                # transferencia apaga (origen "cond:<flag>").
                flag = f"__scar_own_{p.name}"
                out.append(f"    bool {flag} = true;")
                self._consume_flags[p.name] = flag
                self._mark_owner(p.name, f"cond:{flag}")
        body_env = dict(env)
        # Safepoint de prólogo también en una fn (una task ya trae el suyo en
        # el wrapper): sin él, una recursión sin loops no veía la cancelación.
        # Uno por llamada, sin máscara: el costo de la llamada ya domina.
        # Los parámetros que esta fn posee se registran antes del safepoint
        # (cancelar ahí también tiene que soltarlos).
        self._vivos_sync(body_env, out, "    ")
        if self.has_tasks and not decl.is_task:
            out.append("    scar_safepoint();  // safepoint de prologo de fn\n")
        return body_env

    def _fn_cuerpo(self, decl, out, prev_tbind, prev_ret_ty, prev_tmp, prev_fn_name,
                   prev_vivos, vivos_usados, body_env):
        """El cuerpo (con la raíz de main si hay tasks), los flags de loop y el
        registro de vivas."""
        # Solo main, y solo con tasks: el __scar_root que cerrar (ver
        # in_main_root_scope en __init__).
        is_main_root = decl.name == "main" and self.has_tasks
        if is_main_root:
            self.in_main_root_scope = True
        try:
            # En C los parámetros comparten scope con el bloque de afuera del
            # cuerpo: se cuentan como ya declarados, así `let x = x * 2` sobre un
            # parámetro abre su `{}` propio.
            self._gen_stmts_shadow_safe(decl.body.stmts, body_env, out, 1,
                                        declared_init={p.name for p in decl.params})
        finally:
            if is_main_root:
                self.in_main_root_scope = False
            fn_owners = self._pop_owner_scope()
            if (self._block_is_straight_line(decl.body)
                    and not self._block_always_returns(decl.body)):
                # Las dueñas vivas al llegar al cierre de la fn (locales y parámetros
                # que posee) se liberan antes de la llave. Si el cuerpo siempre
                # retorna, cada return ya liberó.
                self._emit_owner_frees(fn_owners, body_env, out, "    ")
            self._vivos_cerrar(fn_owners, out, "    ")
            vivos_usados = self._vivos_fn_on and any("scar_vivo_" in ln for ln in out)
            (self._vivos_fn_on, self._vivos_pub, self._vivos_hist, self._vivos_excluir) = prev_vivos
            self._tbind = prev_tbind
            self.cur_ret_ty, self.tmp_counter, self.cur_fn_name = prev_ret_ty, prev_tmp, prev_fn_name
        out = [f"    bool {f} = false;" for f in self._flags_de_fn] + out
        if vivos_usados:
            # El registro arranca donde estaba al entrar y cada return lo deja así
            # (lo devuelto lo registra quien llamó).
            out = ["    int __scar_vbase = scar_nvivos;"] + [_vivos_truncar_returns(ln) for ln in out]
        else:
            out = [ln for ln in out if "scar_vivo_" not in ln]
        return out

    def _fn_cierre(self, decl, ret, param_list, out):
        """El final de main, la lista de parámetros de C y la función entera como
        texto."""
        # main de SCAR devuelve void; en C, int.
        if decl.name == "main":
            if self.has_tasks:
                # main es una task más para la concurrencia estructurada (como
                # run_main() del intérprete): TaskContext raíz sin padre y su propio
                # sigsetjmp, al que llega un panic de main o uno propagado por un
                # .join(). Antes de salir cancela a las hijas sin join.
                body = "\n".join(out)
                # Si el cuerpo siempre termina en un `return`, cada uno ya emitió el
                # epílogo: esta copia es para el main que cae al final.
                tail = (
                    ""
                    if self._block_always_returns(decl.body)
                    else _raiz_fin_c() + "    return 0;\n"
                )
                return (
                    f"{self._main_sig()} {{\n"
                    # scar_ffi_worker_start_all() va antes que todo, incluso
                    # SCAR_MALLOPT_PROLOGUE: su fork() tiene que ver el proceso todavía
                    # single-thread.
                    f"{'    scar_ffi_worker_start_all();' + chr(10) if self.pipe_isolated_libs else ''}"
                    f"{SCAR_MALLOPT_PROLOGUE}"
                    f"{self._main_arg_init()}"
                    f"{SCAR_RAND_SEED_LINE if self.needs_rand else ''}"
                    f"{'    scar_extern_install_guard();' + chr(10) if self.extern_sigs else ''}"
                    f"{'    scar_pila_iniciar();' + chr(10) if self._fns_recursivas else ''}"
                    f"{_raiz_inicio_c('main')}"
                    "    if (sigsetjmp(__scar_root.panic_env, 1) != 0) {\n"
                    f"{_raiz_fin_c('        ')}"
                    "        return 1;\n"
                    "    }\n"
                    f"{body}\n"
                    f"{tail}"
                    "}"
                )
            out.append("    return 0;")
            return (
                f"{self._main_sig()} {{\n"
                # Igual que con tasks: antes que nada.
                + ("    scar_ffi_worker_start_all();\n" if self.pipe_isolated_libs else "")
                + SCAR_MALLOPT_PROLOGUE
                + self._main_arg_init()
                + (SCAR_RAND_SEED_LINE if self.needs_rand else "")
                + ("    scar_extern_install_guard();\n" if self.extern_sigs else "")
                + ("    scar_pila_iniciar();\n" if self._fns_recursivas else "")
                + "\n".join(out)
                + "\n}"
            )
        body = "\n".join(out)
        # `static` (salvo main): el programa es un único .c, así que ninguna fn
        # se llama desde otra unidad, y gcc puede fusionarla en su único
        # llamador (medido: ~4-5% en 53_sensor_red_avanzada). Si algún día se
        # compila en varios .c, hay que revisar esto.
        static_kw = "" if decl.name == "main" else "static "
        return f"{static_kw}{self.c_type(ret)} {decl.name}({param_list}) {{\n{body}\n}}"
