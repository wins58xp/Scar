"""Análisis COMPARTIDO de ownership interprocedural (lo usan el checker y
el codegen).

La pregunta es qué devuelve una fn/task: un valor fresco que pasa a ser del
caller, algo que ya era de otro, o UNO DE SUS PARÁMETROS (`fn paso(m: Modelo,
x: f64) -> Modelo { m.w = ...; return m }`, `fn pasar(v: Vec<i32>) ->
Vec<i32> { let copia = v; return copia }`). Sin saber lo último, el call site
no tiene forma de distinguir "el resultado es el MISMO objeto que le pasé" de
"es otro objeto que no es mío", y las dos respuestas conservadoras fallan:

  - `m = paso(m, x)`: liberar el `m` viejo antes de reasignar sería un
    use-after-free, porque el valor nuevo ES el `m` viejo.
  - `let w = pasar(v)` con `Vec`: `v` se movió a la llamada; si `w` no se
    registra como dueña, se pierde.

Este módulo resuelve, para cada fn/task cuyo tipo de retorno es "ownable"
(lo decide el llamador), la PROCEDENCIA de su valor de retorno, como un
CONJUNTO de orígenes posibles (`ret_set`):

  - "F" (FRESH): un valor recién reservado que pasa a ser del caller (struct
    literal, vec_new()/map_new(), .join(), un productor de Result).
  - ("P", k): el parámetro k mismo, o un alias puro de él (`let copia = v`,
    `w = v`).
  - None en lugar de un conjunto: desconocido (conservador).

Ejemplos: `paso(m) { m.w = ...; return m }` -> {P0}; una función que
arranca con `let mut m = m0` y lo reasigna con valores frescos dentro de un
loop -> {F, P0} (con 0 vueltas devuelve m0 mismo). En una llamada, cada Pk se
reemplaza por la procedencia del argumento k: así `m = paso(m)` deja a `m`
con la misma procedencia que tenía, y una función que solo hace eso sobre
un `m` fresco sigue devolviendo algo fresco.

`fresh` (el booleano de siempre, `codegen.fresh_owned_fns`) es
`ret_set <= {F}`; `ret_param` es k si `ret_set == {Pk}`.

El recorrido de control de flujo es el mismo de `_flow_fresh_block` (if/else
sobre copias del estado fusionadas con `join`; while/while-let/for a punto
fijo contra el estado de antes del loop, y una pasada final con el invariante
para evaluar los `return` de adentro). Lo que cada lado decide con SUS
criterios va inyectado, igual que en `fresh_result_str.py`:

  - `let_type(stmt, types_env)`: el tipo de un `let` (None si no se puede
    inferir: esa variable no se trackea).
  - `infer(expr, types_env)`: tipo de una expresión (None si falla).
  - `is_fresh_source(expr, ret_ty, types_env)`: True si `expr` es una fuente
    terminal de un valor nuevo (todo lo que no es una llamada a una fn de
    usuario: de eso se encarga este módulo, con memoria y detección de
    ciclos)."""

from parser import (
    AssignStmt, BreakStmt, Call, ErrExpr, FieldAccess, ForStmt, Ident, IfStmt, LetStmt, MethodCall, NoneExpr, OkExpr,
    ReturnStmt, SomeExpr, SpawnExpr, StructLit, ArrayLit, WhileLetStmt, WhileStmt, hijos, Node,
)

FRESH = "F"
# El `x` de `while let Some(x) = v.pop()` (también .get() y
# .recv()) es un valor fresco propio. Hasta B12 se distinguía "FM" (fresco
# de malloc) de "F" (fresco de la arena) para que el llamador supiera cómo
# liberar el bloque; con el origen en el encabezado de cada bloque ya no hace
# falta: los dos son simplemente frescos.
_FRESH_ATOMS = frozenset([FRESH])
_MALLOC_SCRUTINEE_METHODS = ("pop", "get", "recv", "try_recv")


def param(k):
    return ("P", k)


def _option_payload(ty):
    """U si `ty` es Option<U> (el único envoltorio cuyo contenido
    sigue este análisis: `return Some(v)` / `return None`), si no None."""
    if getattr(ty, "name", None) == "Option" and getattr(ty, "args", None):
        return ty.args[0]
    return None


def _es_contenedor_movido(ty):
    """Vec<T>, Map<K,V> u Option de ellos. Una fn los
    recibe siempre MOVIDOS (es su dueña), así que todo valor de estos tipos
    que la fn puede nombrar es suyo, y devolver cualquiera -- un parámetro,
    un local, un alias de otro (`let mut w = v`) -- entrega la propiedad al
    llamador (también `let mut w = v; if c { w = otra }; return w`)."""
    nombre = getattr(ty, "name", None)
    if nombre in ("Vec", "Map"):
        return True
    args = getattr(ty, "args", None)
    return nombre == "Option" and bool(args) and args[0].name in ("Vec", "Map")


def _alias_atom(nombre):
    """Punto 3: procedencia "alias de la variable local fresca `nombre`"
    (`let b = identidad(a)` con `a` fresca). Vale como fresco al devolverse
    solo si, hasta el `return`, ni el alias ni su raíz se usaron de una forma
    que pueda moverlos (ver _Analyzer._invalidar_alias)."""
    return ("A", nombre)


def _es_alias_atom(atom):
    return isinstance(atom, tuple) and atom[0] == "A"


def _menciones_que_mueven(node, nombres, dentro_de_campo=False):
    """True si `node` usa alguno de `nombres` en una posición que podría
    moverlo o crearle otro alias: cualquier uso que no sea leer o escribir
    uno de sus campos (`b.w`, `b.w = ...`)."""
    if isinstance(node, Ident):
        return node.name in nombres and not dentro_de_campo
    if isinstance(node, FieldAccess):
        return _menciones_que_mueven(node.obj, nombres, True)
    return any(_menciones_que_mueven(h, nombres) for h in hijos(node))


def _tracked(ty, ret_ty):
    """Tipos cuya procedencia se sigue en el cuerpo: el de retorno y, si es
    Option<U>, también U (lo que puede ir adentro de un `Some`)."""
    return ty == ret_ty or (ty is not None and ty == _option_payload(ret_ty))


def _join(a, b):
    """Unión de conjuntos de orígenes; desconocido (None) absorbe."""
    if a is None or b is None:
        return None
    return a | b


class FnOwnership:
    """Resultado por fn/task: `fresh` (bool, el de siempre) y `ret_param`
    (índice del parámetro que devuelve siempre, o None)."""

    __slots__ = ("ret_set",)

    def __init__(self, ret_set):
        self.ret_set = ret_set  # frozenset de orígenes, o None (desconocido)

    @property
    def fresh(self):
        return self.ret_set is not None and self.ret_set <= _FRESH_ATOMS

    @property
    def ret_param(self):
        if self.ret_set is not None and len(self.ret_set) == 1:
            (atom,) = self.ret_set
            if isinstance(atom, tuple):
                return atom[1]
        return None

    def may_return_param(self, k):
        return self.ret_set is not None and param(k) in self.ret_set

    def __repr__(self):
        return f"FnOwnership({set(self.ret_set) if self.ret_set is not None else None})"


class _Analyzer:
    def __init__(self, fns, let_type, infer, is_fresh_source, is_struct=None):
        self.fns = fns  # nombre -> (decl, tipos de params, tipo de retorno)
        # por cada loop abierto, el estado en cada `break` (ver _block)
        self._salidas = []
        self.let_type = let_type
        self.infer = infer
        self.is_fresh_source = is_fresh_source
        self.is_struct = is_struct  # ver _opt_fuente
        self.result = {}
        self.visiting = set()

    # ---- resolución con memoria y ciclos ----
    def resolve(self, name):
        if name in self.result:
            return self.result[name]
        if name not in self.fns or name in self.visiting:
            return None
        self.visiting.add(name)
        decl, param_types, ret_ty = self.fns[name]
        types_env = {p.name: t for p, t in zip(decl.params, param_types)}
        state = {
            # Un Vec/Map recibido es de la fn (llegó movido): devolverlo
            # entrega la propiedad, igual que un valor fresco.
            p.name: frozenset([FRESH]) if _es_contenedor_movido(t) else frozenset([param(i)])
            for i, (p, t) in enumerate(zip(decl.params, param_types))
            if _tracked(t, ret_ty)
        }
        rets = []
        self._block(decl.body, ret_ty, types_env, state, rets)
        self.visiting.discard(name)
        ret_set = frozenset()
        for r in rets:
            ret_set = _join(ret_set, r)
        res = FnOwnership(ret_set)
        self.result[name] = res
        return res

    # ---- procedencia de una expresión ----
    def _expr_prov(self, expr, ret_ty, types_env, state, at_return, self_name=None):
        """Conjunto de orígenes de `expr` como valor de tipo `ret_ty` (None si
        no se sabe).

        Un `Ident` propaga sus orígenes, pero si incluye FRESH solo cuando es
        el valor de un `return` o se reasigna sobre sí mismo (`m = paso(m)`):
        `let b = a` con `a` fresca deja DOS nombres para el mismo objeto, y
        el codegen libera `a` al salir -- tratar `b` como fresca habría sido
        el mismo criterio que ya rechazaba `_is_fresh_owned_expr` (un alias
        nunca es fresco)."""
        if self.is_fresh_source(expr, ret_ty, types_env):
            return frozenset([FRESH])
        payload_ty = _option_payload(ret_ty)
        if payload_ty is not None:
            # `None` no lleva nada propio (vacuamente fresco); `Some(e)`
            # es tan fresco como `e` visto como U.
            if isinstance(expr, NoneExpr):
                return frozenset([FRESH])
            if isinstance(expr, SomeExpr):
                return self._expr_prov(expr.expr, payload_ty, types_env, state,
                                       at_return, self_name)
        if isinstance(expr, Call) and isinstance(expr.callee, Ident):
            if getattr(expr.callee, "es_valor_fn", False):
                # contrato del tipo fn(...): lo que devuelve una
                # llamada a través de un valor fn es siempre nuevo
                return frozenset([FRESH])
            r = self.resolve(expr.callee.name)
            if r is None or r.ret_set is None:
                return None
            out = frozenset()
            for atom in r.ret_set:
                if atom in _FRESH_ATOMS:
                    out = out | {atom}
                    continue
                k = atom[1]
                if k >= len(expr.args):
                    return None
                sub = self._expr_prov(expr.args[k], ret_ty, types_env, state, at_return, self_name)
                if sub is None:
                    return None
                out = out | sub
            return out
        if isinstance(expr, Ident):
            p = state.get(expr.name)
            if p is None:
                return None
            if at_return and any(_es_alias_atom(a) for a in p):
                # el alias sigue válido (si no, _invalidar_alias lo habría
                # borrado): devolverlo entrega el objeto fresco de su raíz
                p = frozenset(FRESH if _es_alias_atom(a) else a for a in p)
            if _es_contenedor_movido(ret_ty):
                return p  # ver _es_contenedor_movido: todo Vec/Map nombrable es propio
            if (p & _FRESH_ATOMS) and not (at_return or expr.name == self_name):
                # `let b = a` con `a` fresca: dos nombres para el mismo objeto.
                # Solo `a` es fresca; `b` queda como su alias (ver _alias_atom).
                if p <= _FRESH_ATOMS:
                    return frozenset([_alias_atom(expr.name)])
                return None
            return p
        if (type(expr).__name__ == "FieldAccess" and isinstance(expr.obj, Ident)
                and ret_ty is not None and ret_ty.name not in ("str", "i32", "f64", "bool")):
            # No solo en el `return`: `let x = a.campo` también saca
            # el campo de la dueña local (Codegen._try_neutralize_extracted_field),
            # así que `x` queda propia.
            # `return a.campo` con `a` una dueña local fresca: el codegen saca
            # el campo y libera `a` entera (Codegen._take_owned_field), así
            # que lo devuelto es propio de quien llama.
            p = state.get(("local", expr.obj.name))
            if p is not None and p and p <= _FRESH_ATOMS:
                return frozenset([FRESH])
        if (type(expr).__name__ == "FieldAccess"
                and ret_ty is not None and ret_ty.name not in ("i32", "i64", "f64", "bool")):
            # El campo de un temporal fresco
            # (`mk().dato`, `F { .. }.e`) lo saca el codegen del temporal
            # (Codegen._sacar_campo_de_temporal): es propio.
            raiz = expr
            while type(raiz).__name__ == "FieldAccess":
                raiz = raiz.obj
            if type(raiz).__name__ == "StructLit":
                return frozenset([FRESH])
            if isinstance(raiz, Call) and isinstance(raiz.callee, Ident):
                r = self.resolve(raiz.callee.name)
                if r is not None and r.ret_set is not None and r.ret_set and r.ret_set <= _FRESH_ATOMS:
                    return frozenset([FRESH])
        return None

    def _bind_while_let(self, stmt, ret_ty, types_env, state):
        """`while let Some(x) = v.pop()` (o .get()/.recv()): en cada vuelta `x`
        es una copia propia -> {FRESH}. Cualquier
        otro `while let` deja a `x` sin procedencia conocida (como antes). El
        patrón se vuelve a ligar en cada pasada: no arrastra estado entre
        vueltas."""
        if not isinstance(stmt, WhileLetStmt):
            return
        name = stmt.pattern
        opt_ty = self.infer(stmt.expr, types_env)
        inner = opt_ty.args[0] if (opt_ty is not None and getattr(opt_ty, "args", None)) else None
        if inner is not None:
            types_env[name] = inner
        if (inner is not None and inner == ret_ty
                and isinstance(stmt.expr, MethodCall)
                and stmt.expr.method in _MALLOC_SCRUTINEE_METHODS):
            state[name] = frozenset([FRESH])
        elif (inner is not None and inner == ret_ty and isinstance(stmt.expr, Ident)
                and state.get(("opt", stmt.expr.name)) == _FRESH_ATOMS):
            # `let mut o = t.get(0)` ... `while let Some(x) = o`:
            # mismo valor propio que `while let Some(x) = t.get(0)`, a
            # través de una variable que solo recibió valores frescos.
            # Devolver `x` lo saca de `o` (Codegen._emit_take).
            state[name] = frozenset([FRESH])
        elif inner is not None and inner == ret_ty and getattr(stmt, "copia_ligada", False):
            # Un Vec/Map prestado por un while let que el cuerpo
            # mueve (devolverlo es moverlo) se liga como copia propia (lo
            # marca el checker): devolverlo entrega algo nuevo.
            state[name] = frozenset([FRESH])
        else:
            state.pop(name, None)

    def _opt_fuente(self, ty, ret_ty):
        """Option<S> o Result<S> con S el struct que devuelve la fn: el único
        caso donde el codegen saca el contenido al devolver la ligada de un
        while-let (solo para struct). Result entra por el `match` sobre un
        Result (`Ok(r) => { return r }`), que enum_match baja a un while let
        con el patrón Ok sobre una variable oculta: un Result tiene la forma
        de un Option."""
        payload = _option_payload(ty)
        if payload is None and getattr(ty, "name", None) == "Result" and getattr(ty, "args", None):
            payload = ty.args[0]
        return (self.is_struct is not None and ret_ty is not None
                and payload == ret_ty and self.is_struct(ret_ty))

    def _opt_fresca(self, expr, ty, types_env):
        if isinstance(expr, NoneExpr):
            return True
        if isinstance(expr, MethodCall) and expr.method in _MALLOC_SCRUTINEE_METHODS:
            return True
        if (getattr(ty, "name", None) == "Result" and isinstance(expr, Call)
                and isinstance(expr.callee, Ident) and not getattr(expr.callee, "es_valor_fn", False)):
            # un Result<S> que entrega una fn que siempre lo arma nuevo (su
            # propio análisis lo dice: `return Ok(nuevo)`, `return otra()?`):
            # la variable que lo recibe es su dueña, y el contenido también
            r = self.resolve(expr.callee.name)
            if r is not None and r.fresh:
                return True
        return bool(self.is_fresh_source(expr, ty, types_env))

    def _marcar_opt(self, nombre, expr, ty, ret_ty, types_env, state):
        if self._opt_fuente(ty, ret_ty) and self._opt_fresca(expr, ty, types_env):
            state[("opt", nombre)] = _FRESH_ATOMS
        else:
            state.pop(("opt", nombre), None)

    # ---- recorrido ----
    def _invalidar_alias(self, stmt, state):
        """Punto 3: borra la procedencia de todo alias (_alias_atom) cuyo
        nombre o raíz este statement use de una forma que pueda moverlo. Un
        `return` del alias mismo no lo invalida (es justo el caso que se
        quiere reconocer)."""
        if isinstance(stmt, ReturnStmt) and isinstance(stmt.expr, Ident):
            return
        for nombre, p in list(state.items()):
            if p is None:
                continue
            raices = {a[1] for a in p if _es_alias_atom(a)}
            if raices and _menciones_que_mueven(stmt, raices | {nombre}):
                state.pop(nombre, None)

    def _block(self, block, ret_ty, types_env, state, rets):
        for stmt in block.stmts:
            self._invalidar_alias(stmt, state)
            if isinstance(stmt, LetStmt):
                ty = self.let_type(stmt, types_env)
                if ty is None:
                    continue
                types_env[stmt.name] = ty
                if _tracked(ty, ret_ty):
                    p = self._expr_prov(stmt.expr, ty, types_env, state, False)
                    if p is None:
                        state.pop(stmt.name, None)
                    else:
                        state[stmt.name] = p
                else:
                    state.pop(stmt.name, None)
                # dueña local de otro tipo construida acá mismo: un `return
                # nombre.campo` entrega ese campo (ver _expr_prov/FieldAccess)
                if isinstance(stmt.expr, StructLit):
                    state[("local", stmt.name)] = frozenset([FRESH])
                elif self.is_struct is not None and self.is_struct(ty):
                    # También una dueña local que sale de una fn que
                    # siempre devuelve un struct nuevo (`let h = mk()`).
                    pl = self._expr_prov(stmt.expr, ty, types_env, state, False)
                    if pl and pl <= _FRESH_ATOMS:
                        state[("local", stmt.name)] = frozenset([FRESH])
                    else:
                        state.pop(("local", stmt.name), None)
                else:
                    state.pop(("local", stmt.name), None)
                self._marcar_opt(stmt.name, stmt.expr, ty, ret_ty, types_env, state)
            elif isinstance(stmt, AssignStmt):
                if isinstance(stmt.target, Ident):
                    state.pop(("local", stmt.target.name), None)
                    self._marcar_opt(stmt.target.name, stmt.expr, types_env.get(stmt.target.name),
                                     ret_ty, types_env, state)
                if isinstance(stmt.target, Ident) and _tracked(types_env.get(stmt.target.name), ret_ty):
                    nm = stmt.target.name
                    p = self._expr_prov(stmt.expr, types_env[nm], types_env, state, False, self_name=nm)
                    if p is None:
                        state.pop(nm, None)
                    else:
                        state[nm] = p
            elif isinstance(stmt, ReturnStmt):
                if stmt.expr is None:
                    continue
                rets.append(self._expr_prov(stmt.expr, ret_ty, types_env, state, True))
            elif isinstance(stmt, BreakStmt):
                # Con este estado se llega a lo que sigue al loop.
                # (Lo que viene después en este bloque es código muerto; si se
                # sigue recorriendo, solo agrega estados posibles: del lado
                # conservador.)
                if self._salidas:
                    self._salidas[-1].append(dict(state))
            elif isinstance(stmt, IfStmt):
                then_types, then_state = dict(types_env), dict(state)
                self._block(stmt.then_block, ret_ty, then_types, then_state, rets)
                if stmt.else_block is not None:
                    else_types, else_state = dict(types_env), dict(state)
                    self._block(stmt.else_block, ret_ty, else_types, else_state, rets)
                else:
                    else_types, else_state = dict(types_env), dict(state)
                types_env.update(then_types)
                types_env.update(else_types)
                for nm in set(then_state) | set(else_state):
                    state[nm] = _join(then_state.get(nm), else_state.get(nm))
            elif isinstance(stmt, (WhileStmt, WhileLetStmt, ForStmt)):
                base = dict(state)
                fp = dict(state)
                for _ in range(len(fp) + 4):
                    probe_types, probe_state = dict(types_env), dict(fp)
                    self._bind_while_let(stmt, ret_ty, probe_types, probe_state)
                    self._salidas.append([])
                    try:
                        self._block(stmt.body, ret_ty, probe_types, probe_state, [])
                    finally:
                        self._salidas.pop()
                    merged = {nm: _join(base.get(nm), probe_state.get(nm))
                              for nm in set(base) | set(probe_state)}
                    if merged == fp:
                        break
                    fp = merged
                else:
                    # Tope defensivo (no debería alcanzarse): lado conservador.
                    fp = {nm: None for nm in fp}
                final_types, final_state = dict(types_env), dict(fp)
                self._bind_while_let(stmt, ret_ty, final_types, final_state)
                self._salidas.append([])
                try:
                    self._block(stmt.body, ret_ty, final_types, final_state, rets)
                finally:
                    salidas = self._salidas.pop()
                types_env.update(final_types)
                # A lo que sigue al loop se llega sin vueltas (base),
                # al terminar una vuelta (final_state) o por cada `break`. Antes
                # de `break` solo existían las dos primeras: `if x { r = alias;
                # break } r = fresco` dejaba r "siempre fresca" aunque el loop
                # podía salir con el alias.
                for est in [final_state] + salidas:
                    base = {nm: _join(base.get(nm), est.get(nm)) for nm in set(base) | set(est)}
                state.update(base)


def resolve_fn_ownership(fns, let_type, infer, is_fresh_source, is_struct=None):
    """`fns`: nombre -> (decl, tipos de los parámetros, tipo de retorno), solo
    las fn/task cuyo retorno el llamador considera ownable. Devuelve nombre ->
    FnOwnership para todas ellas. `is_struct(ty)`: si el tipo es un struct de
    usuario (sin él, ese caso queda como antes)."""
    a = _Analyzer(fns, let_type, infer, is_fresh_source, is_struct)
    for name in fns:
        a.resolve(name)
    return a.result


# ---------------------------------------------------------------------------
# Parámetros consumidos (etapa C)
# ---------------------------------------------------------------------------
#
# Un struct de usuario se recibe PRESTADO en una fn normal (16_structs.scar
# depende de eso): el llamador lo sigue teniendo y lo libera al salir. Pero
# nada impedía que la fn lo CONSUMIERA -- meterlo en un Vec/Map, embeberlo en
# otro struct, envolverlo en Some/Ok/Err o pasarlo a un spawn --, y entonces
# el mismo objeto quedaba con dos dueños: el llamador y el contenedor
# (use-after-free/double-free en el nativo; en el intérprete no se nota
# porque todo es alias). Y si la fn lo consumía solo en ALGUNAS ramas y el
# llamador le pasaba un temporal (`f(c, crear(i))`), en las otras ramas nadie
# lo liberaba.
#
# Esta tabla dice, para cada fn, qué parámetros struct consume en algún
# camino. La consultan los DOS lados, así que no pueden desacordar:
#   - type_checker.py: en el llamador, el argumento queda MOVIDO (igual que
#     ya pasaba con Vec<T>/Map<K,V>): usarlo después es error de compilación.
#   - el codegen: el callee es dueño del parámetro desde la entrada (lo
#     libera en los caminos donde no lo consumió); el llamador deja de serlo.
#
# `chan.send()` NO cuenta: el canal copia el struct (deepcopy_into), el
# emisor sigue siendo dueño de su valor (ver codegen._gen_chan_method).

# send() también consume (mueve el struct al canal).
_CONSUMING_METHODS_LAST_ARG = {"push": 0, "set": -1, "insert": -1, "send": 0, "replace": -1}


class _ConsumeFinder:
    def __init__(self, fns, is_struct_type, option_payload=False, struct_fields=None):
        self.fns = fns  # nombre -> (decl, tipos de params)
        self.is_struct_type = is_struct_type
        # nombre de struct -> {campo: TypeAnn}. Con esto, mover un campo
        # no-Copy de un parámetro ('let s = p.serie', push(p.serie), return
        # p.serie...) cuenta como consumir p: la fn se queda con una parte
        # de p, así que el llamador ya no puede liberarlo entero. Sin la
        # tabla (None) no se detecta (comportamiento anterior).
        self.struct_fields = struct_fields
        self.param_types = {}
        # Modo "contenido de un Option<Struct>" (ver
        # resolve_consumed_option_params): el `x` de `while let Some(x) = p`
        # es alias de p, y devolverlo también cuenta como consumirlo.
        self.option_payload = option_payload
        self.result = {name: frozenset() for name in fns}
        # Por qué la fn se queda con cada parámetro (el primer
        # motivo que se encontró, con su línea), para el mensaje de error del
        # llamador. nombre -> {índice: texto}.
        self.motivos = {name: {} for name in fns}
        self._actual = None
        self._nombres = {}
        # El campo al que se le asigna el resultado de la sentencia que se está mirando
        # (`p.v = f(p.v)` saca p.v y lo vuelve a poner: no se lleva nada)
        self._repone = None

    def run(self):
        changed = True
        while changed:
            changed = False
            for name, (decl, param_types) in self.fns.items():
                idx = {p.name: i for i, (p, t) in enumerate(zip(decl.params, param_types))
                       if self.is_struct_type(t)}
                if not idx:
                    continue
                found = set()
                self.param_types = {i: t for i, t in enumerate(param_types)}
                self._vars_fn = _variables_de_fn(decl, self.fns)
                self._actual = name
                self._nombres = {i: p.name for p, i in ((p, i) for i, p in enumerate(decl.params))}
                self._block(decl.body, dict(idx), found)
                fs = frozenset(found)
                if fs != self.result[name]:
                    self.result[name] = fs
                    changed = True
        return self.result

    def _consume(self, found, k, nodo, que):
        """`k` se consume en algún camino (`que`: cómo, para el mensaje)."""
        found.add(k)
        linea = getattr(nodo, "line", None)
        donde = f" (línea {linea})" if linea else ""
        self.motivos[self._actual].setdefault(k, f"{que}{donde}")

    def _param_of(self, expr, alias):
        if isinstance(expr, Ident):
            return alias.get(expr.name)
        return None

    def _param_field_moved(self, expr, alias):
        """si `expr` es `p.c1.c2...` con `p` alias de un parámetro y el
        campo final no es Copy, devuelve el índice de p (moverlo consume p)."""
        if self.struct_fields is None or not isinstance(expr, FieldAccess):
            return None
        campos = []
        e = expr
        while isinstance(e, FieldAccess):
            campos.append(e.field)
            e = e.obj
        k = self._param_of(e, alias)
        if k is None:
            return None
        ty = self.param_types.get(k)
        for c in reversed(campos):
            if ty is None:
                return None
            ty = self.struct_fields.get(ty.name, {}).get(c)
        if ty is None or ty.is_copy():
            return None
        return k

    def _campo_contenedor_de_param(self, expr, alias):
        """Como _param_field_moved, pero solo si el campo es un Vec/Map (u
        Option de ellos): el índice del parámetro, o None."""
        if self.struct_fields is None or not isinstance(expr, FieldAccess):
            return None
        campos = []
        e = expr
        while isinstance(e, FieldAccess):
            campos.append(e.field)
            e = e.obj
        k = self._param_of(e, alias)
        if k is None:
            return None
        ty = self.param_types.get(k)
        for c in reversed(campos):
            if ty is None:
                return None
            ty = self.struct_fields.get(ty.name, {}).get(c)
        if ty is None or not _es_contenedor_movido(ty):
            return None
        return k

    def _consumed_of(self, expr, alias):
        k = self._param_of(expr, alias)
        if k is None:
            k = self._param_field_moved(expr, alias)
        return k

    def _block(self, block, alias, found):
        for stmt in block.stmts:
            self._stmt(stmt, alias, found)

    def _stmt(self, stmt, alias, found):
        if isinstance(stmt, LetStmt):
            self._expr(stmt.expr, alias, found)
            kc = self._param_field_moved(stmt.expr, alias)
            if kc is not None:
                # `let s = p.campo` mueve una parte de p
                self._consume(found, kc, stmt, f"`let {stmt.name} = {_texto_campo(stmt.expr)}` se lleva un campo de '{self._nombres.get(kc)}'")
            k = self._param_of(stmt.expr, alias)
            if k is not None:
                alias[stmt.name] = k  # `let x = p`: x es p
            else:
                alias.pop(stmt.name, None)
        elif isinstance(stmt, AssignStmt):
            self._repone = _texto_campo(stmt.target) if isinstance(stmt.target, FieldAccess) else None
            self._expr(stmt.expr, alias, found)
            self._repone = None
            kc = self._param_field_moved(stmt.expr, alias)
            if kc is not None:
                self._consume(found, kc, stmt, f"asigna {_texto_campo(stmt.expr)} a otro lado: se lleva un campo de '{self._nombres.get(kc)}'")
            k = self._param_of(stmt.expr, alias)
            if isinstance(stmt.target, Ident):
                # Sobre-aproximación a propósito: si `x` alguna vez fue p,
                # sigue contando como p (consumir `x` después consume p en
                # algún camino).
                if k is not None:
                    alias[stmt.target.name] = k
            elif k is not None:
                # `obj.campo = p`: p queda embebido en obj
                self._consume(found, k, stmt, f"guarda '{self._nombres.get(k)}' en el campo de otro struct")
            else:
                self._expr(stmt.target, alias, found)
        elif isinstance(stmt, IfStmt):
            self._expr(stmt.cond, alias, found)
            self._block(stmt.then_block, dict(alias), found)
            if stmt.else_block is not None:
                self._block(stmt.else_block, dict(alias), found)
        elif isinstance(stmt, (WhileStmt, WhileLetStmt, ForStmt)):
            for attr in ("cond", "expr", "start", "end"):
                if hasattr(stmt, attr):
                    self._expr(getattr(stmt, attr), alias, found)
            body_alias = dict(alias)
            if self.option_payload and isinstance(stmt, WhileLetStmt):
                k = self._param_of(stmt.expr, alias)
                if k is not None:
                    body_alias[stmt.pattern] = k
                else:
                    body_alias.pop(stmt.pattern, None)
            self._block(stmt.body, body_alias, found)
        elif self.option_payload and isinstance(stmt, ReturnStmt):
            k = self._param_of(stmt.expr, alias)
            if k is not None:
                self._consume(found, k, stmt, f"devuelve el contenido de '{self._nombres.get(k)}'")
            self._expr(stmt.expr, alias, found)
        elif isinstance(stmt, ReturnStmt):
            kc = self._param_field_moved(stmt.expr, alias)
            if kc is not None:
                # `return p.campo` saca una parte de p
                self._consume(found, kc, stmt, f"devuelve {_texto_campo(stmt.expr)}, un campo de '{self._nombres.get(kc)}'")
            self._expr(stmt.expr, alias, found)
        else:
            for v in vars(stmt).values():
                self._expr(v, alias, found)

    def _expr(self, expr, alias, found):
        if expr is None or isinstance(expr, (str, int, float, bool)):
            return
        if isinstance(expr, (list, tuple, dict)):
            for e in hijos(expr):  # también los campos de un struct literal
                self._expr(e, alias, found)
            return
        if isinstance(expr, MethodCall):
            pos = _CONSUMING_METHODS_LAST_ARG.get(expr.method)
            if pos is not None and expr.args:
                k = self._consumed_of(expr.args[pos], alias)
                if k is not None:
                    self._consume(found, k, expr, f"guarda '{self._nombres.get(k)}' con .{expr.method}()")
        elif isinstance(expr, StructLit):
            for v in expr.fields.values():
                k = self._consumed_of(v, alias)
                if k is not None:
                    self._consume(found, k, expr, f"pone '{self._nombres.get(k)}' adentro de un {expr.name} nuevo")
        elif isinstance(expr, ArrayLit):
            # [a, b]: cada elemento se empuja al Vec nuevo (como .push)
            for v in expr.elems:
                k = self._consumed_of(v, alias)
                if k is not None:
                    self._consume(found, k, expr, f"pone '{self._nombres.get(k)}' adentro de un arreglo [..]")
        elif isinstance(expr, (SomeExpr, OkExpr, ErrExpr)):
            k = self._consumed_of(expr.expr, alias)
            if k is not None:
                envoltura = {"SomeExpr": "Some", "OkExpr": "Ok", "ErrExpr": "Err"}[type(expr).__name__]
                self._consume(found, k, expr, f"envuelve '{self._nombres.get(k)}' en {envoltura}(...)")
        elif isinstance(expr, SpawnExpr):
            call = expr.call
            for a in getattr(call, "args", ()):
                k = self._consumed_of(a, alias)
                if k is not None:
                    self._consume(found, k, expr, f"le pasa '{self._nombres.get(k)}' a una task")
        elif isinstance(expr, Call) and isinstance(expr.callee, Ident):
            consumed = self.result.get(expr.callee.name, frozenset())
            destino = self.fns.get(expr.callee.name)
            tipos = destino[1] if destino is not None else ()
            for j, a in enumerate(expr.args):
                if j in consumed:
                    k = self._consumed_of(a, alias)
                    if k is not None:
                        self._consume(found, k, expr, f"le pasa '{self._nombres.get(k)}' a {expr.callee.name}(), que se queda con él")
                elif (destino is None and expr.callee.name in getattr(self, "_vars_fn", ())
                        and self._campo_contenedor_de_param(a, alias) is not None):
                    # una llamada a través de un valor fn (`g(p.lista)`)
                    # se queda con un Vec/Map que recibe, como cualquier fn: si es
                    # un campo de un parámetro, consume ese parámetro (el gemelo
                    # del caso de abajo, que mira la firma de una fn conocida).
                    kc = self._campo_contenedor_de_param(a, alias)
                    self._consume(found, kc, expr, f"le pasa {_texto_campo(a)}, un campo de '{self._nombres.get(kc)}', "
                                                   f"a {expr.callee.name}() (una función guardada en una variable), "
                                                   f"que se queda con él")
                elif j < len(tipos) and _es_contenedor_movido(tipos[j]):
                    # Un Vec/Map (u Option de ellos) que se pasa a una fn normal es de
                    # esa fn (lo libera al terminar). Si el argumento es un campo de un
                    # parámetro, `f(p.lista)`, la fn se lleva una parte de p: igual que
                    # `let s = p.lista`, consume p. Antes no se veía, y quien había prestado p
                    # lo seguía usando y lo liberaba entero: uso después de liberar y double
                    # free en el nativo (el intérprete no lo notaba).
                    kc = self._param_field_moved(a, alias)
                    # `p.v = f(p.v)`: el campo vuelve a su lugar en la misma sentencia (lib/imagen)
                    if kc is not None and _texto_campo(a) != self._repone:
                        self._consume(found, kc, expr, f"le pasa {_texto_campo(a)}, un campo de '{self._nombres.get(kc)}', a {expr.callee.name}(), que se queda con él")
        for v in hijos(expr):
            self._expr(v, alias, found)


def _variables_de_fn(decl, fns):
    """los nombres que en `decl` guardan una función (un valor fn):
    los parámetros de tipo `fn(...)` y los `let` anotados así o que reciben el
    nombre de una fn (`let g = doble`) u otra de estas variables. Una llamada
    `g(...)` con uno de estos nombres es una llamada a través de un valor fn.
    Sobre-aproxima (no mira el alcance de cada let): en el peor caso, una
    llamada cuenta como por valor fn y mueve un campo Vec/Map de más."""
    nombres = {p.name for p in decl.params
               if p.type_ann is not None and p.type_ann.name == "__Fn"}

    vistos = set()

    def visitar(n):
        if id(n) in vistos or not isinstance(n, Node):
            return
        vistos.add(id(n))
        if isinstance(n, LetStmt):
            ann = getattr(n, "declared_type", None)
            if ((ann is not None and ann.name == "__Fn")
                    or (isinstance(n.expr, Ident) and (n.expr.name in fns or n.expr.name in nombres))):
                nombres.add(n.name)
        for v in vars(n).values():
            if isinstance(v, list):
                for x in v:
                    visitar(x)
            else:
                visitar(v)

    visitar(decl.body)
    return nombres


def es_compuesto_de_struct(t, structs):
    """Option<Struct> o Result<Struct>: un Result tiene la forma de un Option,
    así que la fn puede quedarse con su contenido de la misma manera
    (`match r { Ok(p) => v.push(p) ... }`). El checker y el codegen usan esta
    misma regla para saber qué parámetros se consumen: no pueden desacordar."""
    return t.name in ("Option", "Result") and bool(t.args) and t.args[0].name in structs


def resolve_consumed_option_params(fns, is_option_struct_type):
    """Como resolve_consumed_params, pero para parámetros
    Option<Struct>: qué parámetros pueden terminar con su CONTENIDO guardado
    en otro lado (empujado, embebido, devuelto...) a través del `x` de un
    `while let Some(x) = p`. El codegen lo usa para decidir si puede liberar
    una copia temporal (`f(v.get(0))`) después de la llamada: si la fn la
    consume, no la libera (leak acotado, nunca un double-free). No cambia la
    semántica de mover de la etapa C, que sigue siendo solo para structs."""
    return _ConsumeFinder(fns, is_option_struct_type, option_payload=True).run()


def resolve_consumed_params(fns, is_struct_type, struct_fields=None, motivos=None):
    """`fns`: nombre -> (decl, tipos de los parámetros) de las fn normales
    (no task, no genéricas). Devuelve nombre -> frozenset de índices de los
    parámetros struct que la fn consume en algún camino. Si se pasa
    `motivos` (un dict), se llena con nombre -> {índice: por qué} (
    para el mensaje de error del llamador)."""
    f = _ConsumeFinder(fns, is_struct_type, struct_fields=struct_fields)
    r = f.run()
    if motivos is not None:
        motivos.update(f.motivos)
    return r


def _texto_campo(expr):
    """`p.mundo.n` como texto (para un mensaje)."""
    partes = []
    while isinstance(expr, FieldAccess):
        partes.append(expr.field)
        expr = expr.obj
    raiz = getattr(expr, "name", "?")
    return ".".join([raiz] + list(reversed(partes)))


# ---------------------------------------------------------------------------
# Parámetros devueltos
# ---------------------------------------------------------------------------
#
# Un struct se recibe PRESTADO en una fn normal. Si la fn lo devuelve
# (`fn identidad(m: M) -> M { return m }`), `let b = identidad(a)` deja dos
# nombres para el MISMO objeto. Después, `xs.push(a)` movía `a` al Vec y el
# bloque se soltaba, pero `b` seguía apuntándolo: use-after-free en el nativo
# (el checker no sabía que `b` era `a`). Con semántica de valor, una variable
# y un elemento de un contenedor nunca son el mismo objeto: guardar ese
# resultado mueve el argumento, igual que `let b = a`. Esta tabla dice, para
# cada fn, qué parámetros struct puede devolver como el mismo objeto
# (directo, por un alias local o por otra fn que a su vez lo devuelve). La
# usa type_checker.py (_move_if_needed).

def resolve_returned_params(fns, is_struct_type):
    """`fns`: nombre -> (decl, tipos de los parámetros). Devuelve nombre ->
    frozenset de índices de parámetros struct que la fn puede devolver."""
    result = {name: frozenset() for name in fns}

    def fuente(expr, alias):
        if isinstance(expr, Ident):
            return set(alias.get(expr.name, ()))
        if type(expr).__name__ == "TryExpr":
            return fuente(expr.expr, alias)
        if isinstance(expr, Call) and isinstance(expr.callee, Ident):
            out = set()
            for k in result.get(expr.callee.name, ()):
                if k < len(expr.args):
                    out |= fuente(expr.args[k], alias)
            return out
        return set()

    def recorrer(block, alias, found):
        for stmt in block.stmts:
            if isinstance(stmt, LetStmt):
                src = fuente(stmt.expr, alias)
                if src:
                    alias[stmt.name] = src
                else:
                    alias.pop(stmt.name, None)
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, Ident):
                src = fuente(stmt.expr, alias)
                if src:  # sobre-aproximación: si alguna vez fue p, sigue contando
                    alias[stmt.target.name] = set(alias.get(stmt.target.name, ())) | src
            elif isinstance(stmt, ReturnStmt):
                if stmt.expr is not None:
                    found |= fuente(stmt.expr, alias)
            elif isinstance(stmt, IfStmt):
                recorrer(stmt.then_block, dict(alias), found)
                if stmt.else_block is not None:
                    recorrer(stmt.else_block, dict(alias), found)
            elif isinstance(stmt, (WhileStmt, WhileLetStmt, ForStmt)):
                interno = dict(alias)
                recorrer(stmt.body, interno, found)
                recorrer(stmt.body, interno, found)  # segunda vuelta: alias del cuerpo

    changed = True
    while changed:
        changed = False
        for name, (decl, param_types) in fns.items():
            idx = {p.name: {i} for i, (p, t) in enumerate(zip(decl.params, param_types))
                   if is_struct_type(t)}
            if not idx:
                continue
            found = set()
            recorrer(decl.body, dict(idx), found)
            fs = frozenset(found)
            if fs != result[name]:
                result[name] = fs
                changed = True
    return result
