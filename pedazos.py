"""La vida de un pedazo guardado en una variable (`let p = v[a..b]`).

Un pedazo es una vista del buffer de otro Vec: no es dueño de nada. Para que
nunca quede mirando memoria suelta, el checker pide dos cosas, y las dos se
revisan acá, sobre el AST:

  1. El pedazo mismo no cambia de largo ni sale de su bloque: se le puede leer
     y escribir (`p[i]`, `p[i] = x`, `len`, `get`, `set`, `replace`, `suma`,
     `punto`, `acumular`), imprimirlo, tomarle otro pedazo y pasarlo a una fn
     que no le cambia el largo. No se le hace `push` ni `pop`, no se reasigna,
     no se devuelve, no se guarda en otro lado.
  2. Mientras el pedazo se usa, el Vec de origen no cambia de largo ni se va:
     desde el `let` hasta la última sentencia de ese bloque que nombra al
     pedazo (su zona), al Vec de origen (y a lo que lo contiene: `c` y
     `c.pesos` para un pedazo de `c.pesos`) se le aplican las mismas reglas.
     Después de la zona el Vec vuelve a ser libre.

Es una lista blanca: lo que este análisis no reconoce, se rechaza. Un error
acá rechaza un programa; nunca deja pasar uno que agrande o suelte un buffer
que un pedazo está mirando.

También está acá `resolve_vistas`: qué parámetros de cada fn terminan mirados
por un pedazo (la fn les toma uno, o se los pasa a otra que lo hace). El
checker lo usa en cada llamada: el mismo Vec no puede llegar además por otro
parámetro que le cambie el largo.
"""
from parser import (
    AssignStmt, BinOp, Block, Call, ExprStmt, FieldAccess, FnDecl, ForStmt, Ident, IfStmt,
    IndexExpr, LetStmt, MethodCall, Node, NumLit, PrintExpr, ReturnStmt, SliceExpr, UnaryOp,
    WhileLetStmt, WhileStmt, hijos, ArrayLit, StructLit, ExprStmt, IfExpr,
)
from types_ import ESCALARES  # familias de tipos (types_.py)

# lo que se le puede hacer a un Vec sin cambiarle el largo (la misma lista que
# fresh_owned._METODOS_FIJOS)
METODOS_FIJOS = frozenset(["len", "get", "set", "replace", "suma", "punto", "acumular", "llenar"])
# lo que solo lee: lo único que vale sobre lo que contiene al Vec de origen
METODOS_QUE_LEEN = frozenset(["len", "get", "suma", "punto"])

IDX = "[]"


def camino(expr):
    """El camino de un lugar: ('c', ('.', 'pesos'), ('[]', None)) para
    `c.pesos[i]`, y ('m', ('[]', 0)) para `m[0]` (un índice escrito como número
    se recuerda: `m[0]` y `m[1]` no son el mismo elemento). None si no es una
    variable, un campo o un elemento."""
    if isinstance(expr, Ident):
        return (expr.name,)
    if isinstance(expr, FieldAccess):
        c = camino(expr.obj)
        return None if c is None else c + ((".", expr.field),)
    if isinstance(expr, IndexExpr):
        c = camino(expr.obj)
        if c is None:
            return None
        return c + (_tramo_indice(expr.index),)
    return None


def raiz_de(expr):
    """El Ident del comienzo de un lugar (`m` en `m[i].pesos`), o None."""
    while isinstance(expr, (FieldAccess, IndexExpr)):
        expr = expr.obj
    return expr if isinstance(expr, Ident) else None


def reales(cam, ped):
    """El camino `cam`, que empieza en el pedazo guardado `ped`, dicho desde cada
    Vec que el pedazo puede mirar (uno, o varios si se le reasignó otro pedazo:
    `let mut p = v[a..b]` y `p = w[c..d]`, tarea 2.5a): `p` es ese Vec y `p[i]` es
    uno de sus elementos (el `i + desde`, si los dos son números escritos; si no,
    cualquiera)."""
    out = []
    for fuente, desde in ped.fuentes:
        resto = cam[1:]
        if resto and resto[0][0] == IDX:
            i = resto[0][1]
            resto = ((IDX, i + desde if i is not None and desde is not None else None),) + resto[1:]
        c = fuente + resto
        if c not in out:
            out.append(c)
    return out


def _resolver(cam, sobre, prof=0):
    """`cam` dicho desde lo que de verdad mira: si su raíz es un portador (una
    variable que guarda pedazos, 2.5c) y el camino entra por uno de esos pedazos,
    es el Vec que el pedazo mira."""
    port = sobre.get(cam[0]) if sobre else None
    if port is None or prof > 8:
        return [cam]
    return reales_port(cam, port, prof + 1)


def reales_port(cam, port, prof=0):
    """El camino `cam`, que empieza en el portador `port`, dicho desde los Vec que
    miran los pedazos que guarda: con `let c = Capa { w: params[0..4] }`, `c.w` es
    `params` y `c.w[i]` uno de sus elementos. Lo que no pasa por un pedazo guardado
    (`c.sesgo`, `c` mismo) queda igual: es del portador."""
    g, gg, out, hubo = cam[1:], _sufijo(cam), [], False
    for ruta, fuente, _, quien in port.rutas():
        if len(gg) >= len(ruta) and gg[:len(ruta)] == ruta:
            hubo = True
            resto = g[len(ruta):]
            if resto and resto[0][0] == IDX:
                resto = ((IDX, None),) + resto[1:]
            for base in _resolver(fuente, quien.sobre, prof + 1):
                if base + resto not in out:
                    out.append(base + resto)
    # (el lugar mismo también: antes de guardar un pedazo ahí, `c.w` era un Vec
    # propio de `c`, y un pedazo tomado entonces mira ese)
    return [cam] + out if hubo else [cam]


def _campo_con_pedazo(node, cam):
    """Si `node` es justo un lugar donde se guarda un pedazo (`c.w`, `red[i].w`,
    dicho directo o por un pedazo guardado de `red`), ese lugar por su camino
    propio; si no, None. Asignarle (`c.w = ...`) cambia lo que el campo guarda,
    no el Vec que el pedazo miraba."""
    r = raiz_de(node)
    ped = getattr(r, "_vista", None)
    if ped is not None:
        bases = [(c, ped.sobre.get(c[0])) for c in reales(cam, ped)]
    else:
        bases = [(cam, getattr(r, "_lleva", None))]
    for c, port in bases:
        if port is None or _sufijo(c) not in {rt for rt, _, _, _ in port.rutas()}:
            return None
    return [c for c, _ in bases]


def caminos_reales(expr, cam=None):
    """Como camino(), pero si el lugar empieza en un pedazo guardado (`p[0].pesos`
    con `let p = red[2..5]`) da los caminos desde los Vec de origen
    (`red[2].pesos`): dos nombres para el mismo lugar dan el mismo camino. Lo
    mismo si pasa por un pedazo guardado adentro de un struct o de un Vec (un
    portador, 2.5c). Una lista: un pedazo reasignado puede ser cualquiera de sus
    orígenes, y toda regla se cumple para todos. [] si no es un lugar. Revisor
    deja en cada Ident que nombra un pedazo guardado su `_vista`, y en cada uno
    que nombra una variable que puede guardar pedazos su `_lleva`."""
    if cam is None:
        cam = camino(expr)
    if cam is None:
        return []
    r = raiz_de(expr)
    ped = getattr(r, "_vista", None) if r is not None else None
    if ped is not None:
        out = []
        for c in reales(cam, ped):
            for x in _resolver(c, ped.sobre):
                if x not in out:
                    out.append(x)
        return out
    port = getattr(r, "_lleva", None) if r is not None else None
    return reales_port(cam, port) if port is not None else [cam]


def camino_real(expr, cam=None):
    """El primero de caminos_reales (o None): para lo que solo necesita un nombre
    del lugar, como un mensaje. Una regla usa caminos_reales."""
    cs = caminos_reales(expr, cam)
    return cs[0] if cs else None


def _tramo_indice(i):
    fijo = i.value if isinstance(i, NumLit) and isinstance(i.value, int) and not isinstance(i.value, bool) else None
    return (IDX, fijo)


def tiene_indice(c):
    return any(seg[0] == IDX for seg in c[1:])


def texto_camino(c):
    out = c[0]
    for seg in c[1:]:
        if seg[0] == IDX:
            out += "[i]" if seg[1] is None else f"[{seg[1]}]"
        else:
            out += "." + seg[1]
    return out


def _texto_uso(node, cam):
    """Cómo se escribió el lugar de un error: el camino real (`red[i].pesos`),
    salvo que pase por el elemento de un `for x in red`, que se escribió `x`
    (`x.pesos`)."""
    def tiene_x(n):
        while isinstance(n, (FieldAccess, IndexExpr)):
            if getattr(n, "_x_for", None):
                return True
            n = n.obj
        # (o una variable que guarda pedazos: `c.w` se escribió así, aunque mire `params`)
        return getattr(n, "_lleva", None) is not None and n.name != cam[0]

    def texto(n):
        if isinstance(n, IndexExpr) and getattr(n, "_x_for", None):
            return n._x_for
        if isinstance(n, Ident):
            return n.name
        if isinstance(n, FieldAccess):
            return f"{texto(n.obj)}.{n.field}"
        if isinstance(n, IndexExpr):
            i = n.index
            return f"{texto(n.obj)}[{i.name if isinstance(i, Ident) else i.value if isinstance(i, NumLit) else 'i'}]"
        return "?"

    return texto(node) if tiene_x(node) else texto_camino(cam)


def _mismo(a, b):
    """Dos tramos de un camino pueden ser el mismo lugar. Un índice que no es un
    número escrito vale por cualquiera: no se sabe si `m[i]` y `m[j]` son el
    mismo elemento."""
    if a == b:
        return True
    return a[0] == IDX and b[0] == IDX and (a[1] is None or b[1] is None)


def es_prefijo(corto, largo):
    """`corto` es el comienzo de `largo` (o el mismo)."""
    return len(corto) <= len(largo) and corto[0] == largo[0] and \
        all(_mismo(a, b) for a, b in zip(corto[1:], largo[1:]))


def menciona(node, nombre):
    if isinstance(node, Ident):
        return node.name == nombre
    if isinstance(node, (Node, list, tuple, dict)):
        return any(menciona(h, nombre) for h in hijos(node))
    return False


def _declara(node, nombre):
    """True si adentro de `node` se declara una variable `nombre` (un let, la
    variable de un for, lo que liga un while let)."""
    if isinstance(node, LetStmt) and node.name == nombre:
        return True
    if isinstance(node, ForStmt) and node.var == nombre:
        return True
    if isinstance(node, WhileLetStmt) and node.pattern == nombre:
        return True
    if isinstance(node, (Node, list, tuple, dict)):
        return any(_declara(h, nombre) for h in hijos(node))
    return False


class _Pedazo:
    __slots__ = ("nombre", "linea", "fuentes", "por_for", "texto", "mutable", "resto", "sobre", "por_llamada")

    def __init__(self, nombre, linea, fuentes, por_for=None, mutable=False):
        self.por_for = por_for  # (x, v) si es el pedazo de un `for x in v`
        self.texto = None       # cómo se escribió el Vec de origen, si no es su camino real
        self.nombre = nombre    # la variable
        self.linea = linea      # la línea de su let
        # lo que puede mirar: (camino del Vec de más afuera, dónde empieza en él si
        # es un número escrito). Uno, o más si es `let mut` y se le reasigna otro
        # pedazo (2.5a): las reglas valen para todos, todo el tiempo que se lo usa
        self.fuentes = fuentes
        self.mutable = mutable
        self.resto = ()         # las sentencias de su bloque después de su let
        self.sobre = {}         # raíz de una fuente -> el portador que es (2.5c)
        self.por_llamada = None  # la fn, si es el resultado de `mitad(w)` usado directo

    def fuentes_reales(self):
        out = []
        for f, _ in self.fuentes:
            for c in _resolver(f, self.sobre):
                if c not in out:
                    out.append(c)
        return out

    @property
    def fuente(self):
        """El primer Vec que mira (el de su let): para los mensajes."""
        return self.fuentes[0][0]


# contextos de un lugar
_LEE = ("lee",)


class _Recorrido:
    """Recorre sentencias y avisa de cada lugar (variable, campo, elemento) con
    lo que se hace con él: `uso(nodo, camino, contexto)`. Los contextos:
    ("lee",), ("metodo", llamada), ("arg_metodo", llamada, j), ("arg_fn",
    llamada, j), ("pedazo", nodo, contexto del pedazo), ("destino", sentencia),
    ("devuelve", sentencia) y ("valor", padre) para todo lo demás."""
    raiz = None  # si se sigue una sola variable: otra con su nombre corta el recorrido

    def uso(self, node, cam, ctx):
        raise NotImplementedError

    tapada = 0   # > 0: adentro de un bloque donde otra variable tapa a la raíz
    sigue_tapada = False  # seguir mirando igual (por los otros nombres del mismo lugar)

    def sentencias(self, stmts):
        tapo = False
        for stmt in stmts:
            self.ver(stmt, _LEE)
            if self.raiz is not None and isinstance(stmt, LetStmt) and stmt.name == self.raiz:
                # otra variable con ese nombre: lo que sigue ya no es esta
                if not self.sigue_tapada:
                    return
                if not tapo:
                    tapo = True
                    self.tapada += 1
        if tapo:
            self.tapada -= 1

    def _indices(self, node):
        """Las expresiones de los índices de un lugar (`i` en `m[i].pesos`)."""
        while not isinstance(node, Ident):
            if isinstance(node, IndexExpr):
                self.ver(node.index, _LEE)
            node = node.obj

    def ver(self, node, ctx):
        if node is None or isinstance(node, (str, int, float, bool)):
            return
        if isinstance(node, (list, tuple, dict)):
            for h in hijos(node):
                self.ver(h, ctx)
            return
        cam = camino(node)
        if cam is not None:
            self.uso(node, cam, ctx)
            self._indices(node)
            return
        if isinstance(node, Block):
            self.sentencias(node.stmts)
            return
        if isinstance(node, LetStmt):
            self.ver(node.expr, ("valor", node))
            return
        if isinstance(node, AssignStmt):
            self.ver(node.target, ("destino", node))
            self.ver(node.expr, ("valor", node))
            return
        if isinstance(node, ReturnStmt):
            self.ver(node.expr, ("devuelve", node))
            return
        if isinstance(node, ExprStmt):
            self.ver(node.expr, _LEE)
            return
        if isinstance(node, (IfStmt, WhileStmt)):
            self.ver(node.cond, _LEE)
            for h in hijos(node):
                if isinstance(h, Block):
                    self.ver(h, _LEE)
            return
        if isinstance(node, ForStmt):
            self.ver(node.start, _LEE)
            self.ver(node.end, _LEE)
            if self.raiz is None or node.var != self.raiz:
                self.ver(node.body, _LEE)
            elif self.sigue_tapada:
                self.tapada += 1
                self.ver(node.body, _LEE)
                self.tapada -= 1
            return
        if isinstance(node, SliceExpr):
            self.ver(node.obj, ("pedazo", node, ctx))
            self.ver(node.desde, _LEE)
            self.ver(node.hasta, _LEE)
            return
        if isinstance(node, MethodCall):
            cam = camino(node.obj) if node.method in ("set", "replace") and node.args else None
            if cam is not None:
                # `x.set(i, valor)` (y `x[i] = valor`) es asignarle al lugar x[i]
                self.uso(node.obj, cam + (_tramo_indice(node.args[0]),), ("destino", node))
                self._indices(node.obj)
            else:
                self.ver(node.obj, ("metodo", node))
            for j, a in enumerate(node.args):
                self.ver(a, ("arg_metodo", node, j))
            return
        if isinstance(node, Call):
            if not isinstance(node.callee, Ident):
                self.ver(node.callee, ("valor", node))
            for j, a in enumerate(node.args):
                self.ver(a, ("arg_fn", node, j))
            return
        if isinstance(node, (PrintExpr, BinOp, UnaryOp)):
            for h in hijos(node):
                self.ver(h, _LEE)
            return
        if not isinstance(node, Node):
            return
        for h in hijos(node):
            # un bloque adentro (una rama de un match, de un if que da valor) no
            # es un valor: sus sentencias se miran como cualquiera
            self.ver(h, _LEE if isinstance(h, Block) else ("valor", node))


class _SoloFijo(_Recorrido):
    """¿`nombre` (un Vec) se usa solo de formas que no le cambian el largo ni lo
    mueven? (leerlo, sus elementos, los métodos fijos, una fn que no lo agranda)."""

    def __init__(self, nombre, vec_fijos):
        self.nombre = nombre
        self.vec_fijos = vec_fijos
        self.fijo = True

    def uso(self, node, cam, ctx):
        if cam[0] != self.nombre or len(cam) > 1:
            return
        que = ctx[0]
        if que in ("lee", "pedazo"):
            return
        if que == "metodo" and ctx[1].method in METODOS_FIJOS:
            return
        if que == "arg_metodo" and ctx[1].method in ("punto", "acumular") and ctx[2] == 0:
            return
        if que == "arg_fn" and isinstance(ctx[1].callee, Ident) \
                and not getattr(ctx[1], "_callee_local", False) \
                and ctx[2] in self.vec_fijos.get(ctx[1].callee.name, ()):
            return
        self.fijo = False


def ligada_fija(nombre, stmts, vec_fijos):
    r = _SoloFijo(nombre, vec_fijos)
    r.sentencias(stmts)
    return r.fijo


class _Portador:
    """Una variable (un struct, un Vec) que guarda pedazos adentro (2.5c): `let c
    = Capa { w: params[0..4] }`, `red.push(c)`. `directas`: (ruta adentro de la
    variable, camino del Vec que mira, nodo); `incluye`: (ruta, otro portador que
    se movió ahí, nodo). Toda variable de un let lo es en potencia; cuenta si
    `rutas()` da algo. Como en un pedazo reasignado, las reglas valen para todo
    lo que guardó o va a guardar, todo el tiempo que se usa."""
    __slots__ = ("nombre", "linea", "resto", "directas", "incluye", "alias", "sobre",
                 "por_for", "texto", "mutable", "por_llamada")
    es_portador = True

    def __init__(self, nombre, linea, resto):
        self.nombre = nombre
        self.linea = linea
        self.resto = resto
        self.directas = []
        self.incluye = []
        self.alias = set()      # pedazos guardados que miran adentro de ella
        self.por_llamada = None  # la fn, si es lo que devuelve `armar(p)` usado directo
        self.sobre = {}
        self.por_for = None
        self.texto = None
        self.mutable = False

    def rutas(self, _cadena=()):
        """[(ruta, camino del Vec mirado, nodo, portador donde se guardó)]"""
        if id(self) in _cadena:
            return []
        out = [(r, f, n, self) for r, f, n in self.directas]
        for pref, otro, nodo in self.incluye:
            out += [(pref + r, f, nodo, q) for r, f, _, q in otro.rutas(_cadena + (id(self),))]
        return out

    def fuentes_reales(self):
        out = []
        for _, f, _, q in self.rutas():
            for c in _resolver(f, q.sobre):
                if c not in out:
                    out.append(c)
        return out

    @property
    def fuentes(self):
        return [(c, None) for c in self.fuentes_reales()]

    @property
    def fuente(self):
        return self.fuentes_reales()[0]


def _ped(vistas, nombre):
    v = vistas.get(nombre)
    return v if isinstance(v, _Pedazo) else None


def _port(vistas, nombre):
    v = vistas.get(nombre)
    return v if isinstance(v, _Portador) else None


class _Llevado(_Recorrido):
    """Lo que no se le puede hacer a una variable que guarda pedazos (o a lo que,
    adentro de ella, contiene uno): sacarla de la fn o del hilo, o pasarla a
    quien podría cambiar algo adentro. Lo que se le hace al pedazo mismo (`c.w`)
    ya lo miran las reglas del Vec de origen, por su camino real."""

    def __init__(self, rev, port):
        self.rev = rev
        self.p = port
        self.rutas = {r for r, _, _, _ in port.rutas()}

    def uso(self, node, cam, ctx):
        r = raiz_de(node)
        if getattr(r, "_lleva", None) is self.p:
            cams = [cam]
        elif getattr(r, "_vista", None) is not None:
            ped = r._vista
            cams = [c for c in reales(cam, ped) if ped.sobre.get(c[0]) is self.p]
        else:
            return
        for c in cams:
            g = _sufijo(c)
            if any(len(rt) > len(g) and rt[:len(g)] == g for rt in self.rutas):
                return self._regla(node, cam, ctx)

    def _regla(self, node, cam, ctx):
        que = ctx[0]
        if que == "pedazo" and ctx[2][0] == "arg_fn":
            ctx = ctx[2]    # `f(red[0..2])`: como pasarle red
            que = "arg_fn"
        if que in ("lee", "pedazo"):
            return
        if que == "destino":
            if isinstance(ctx[1], MethodCall) and ctx[1].method == "replace":
                return self.error(node, cam, "con .replace() saldría de ahí uno de los que guardan un pedazo")
            return
        if que == "metodo":
            m = ctx[1].method
            if m in ("len", "push", "get"):
                return
            return self.error(node, cam, f"no se le hace .{m}()")
        if que == "arg_fn":
            llamada, j = ctx[1], ctx[2]
            fname = llamada.callee.name if isinstance(llamada.callee, Ident) else None
            if fname is not None and not self.rev.es_variable(fname, llamada) \
                    and j in self.rev.quietos.get(fname, ()):
                return
            porque = self.rev.quietos_motivos.get(fname, {}).get(j)
            return self.error(node, cam, f"no se le pasa a {fname or 'esa función'}(), que podría cambiarle el "
                              f"largo a algo de adentro o quedarse con él" + (f" ({porque})" if porque else ""))
        if que in ("valor", "arg_metodo", "devuelve") and getattr(node, "_mueve_ok", False):
            # se mueve a otra variable de la fn, que pasa a guardar lo mismo; o se
            # devuelve entera, y quien llama la recibe sabiendo qué guarda
            return
        if que == "devuelve":
            return self.error(node, cam, "se devuelve entera ('return c'), no una parte")
        return self.error(node, cam, "no se manda a una tarea ni por un canal, ni se guarda en algo que no "
                          "sea una variable de esta fn")

    def error(self, node, cam, que):
        p = self.p
        quien = _texto_uso(node, cam)
        de = "', '".join(texto_camino(c) for c in p.fuentes_reales()[:3])
        if p.por_llamada:
            sujeto = f"lo que devuelve {p.por_llamada}() guarda pedazos de '{de}' (línea {p.linea})"
        else:
            sujeto = (f"'{quien}' guarda pedazos de '{de}'"
                      + (f" ('{p.nombre}', línea {p.linea})" if quien != p.nombre else f" (línea {p.linea})"))
        self.rev.fallar(sujeto
                        + f": {que}. Lo que guarda un pedazo se usa en la fn que lo arma, y se presta a "
                        f"funciones que solo leen o escriben sus números", node)


class _Congelado(_Recorrido):
    """Busca usos de `camino_s` (o de lo que lo contiene) que le cambien el
    largo, lo suelten o lo muevan."""

    def __init__(self, rev, ped, camino_s, es_pedazo):
        self.rev = rev
        self.ped = ped
        self.s = camino_s
        self.es_pedazo = es_pedazo
        self.raiz = camino_s[0]
        self.sigue_tapada = not es_pedazo

    # -- un uso ------------------------------------------------------------
    def uso(self, node, cam, ctx):
        if not self.es_pedazo:
            # otro pedazo guardado puede ser otro nombre del mismo lugar:
            # `p[0]` con `let p = m[0..2]` es una fila de `m`
            r = raiz_de(node)
            if self.tapada and getattr(r, "_vista", None) is None and getattr(r, "_lleva", None) is None:
                return  # otra variable, que tapa a la del Vec de origen
            vista = getattr(r, "_vista", None)
            if (vista is not None and len(cam) == 1 and ctx[0] in ("destino", "valor")
                    and isinstance(ctx[1], AssignStmt) and getattr(ctx[1], "_reasigna_pedazo", False)):
                return  # `p = q` / `p = w[..]`: cambia qué mira p, no toca el Vec (2.5a)
            if vista is not None and len(cam) == 1 and all(len(f) == len(self.s) for f, _ in vista.fuentes):
                return  # un pedazo de este mismo Vec, entero: ya lo miran sus propias reglas
            # de los caminos posibles, los que llegan a este Vec; si hay varios, el
            # más corto (lo que lo contiene pide más que el Vec mismo)
            posibles = None
            if ctx[0] == "destino" and isinstance(ctx[1], AssignStmt) and ctx[1].target is node:
                posibles = _campo_con_pedazo(node, cam)
            if posibles is None:
                posibles = caminos_reales(node, cam)
            tocan = [c for c in posibles if es_prefijo(c, self.s)]
            if not tocan:
                return
            cam = min(tocan, key=len)
        if not es_prefijo(cam, self.s):
            return
        igual = len(cam) == len(self.s)
        que = ctx[0]
        if que == "lee":
            return
        if que == "metodo":
            m = ctx[1].method
            if m in (METODOS_FIJOS if igual else METODOS_QUE_LEEN):
                return
            return self.error(node, ("metodo", m, igual, cam))
        if que == "arg_metodo":
            if ctx[1].method in ("punto", "acumular") and ctx[2] == 0:
                return  # el otro lado de punto/acumular solo se lee
            return self.error(node, ("valor", cam))
        if que == "arg_fn":
            llamada, j = ctx[1], ctx[2]
            fname = llamada.callee.name if isinstance(llamada.callee, Ident) else None
            if fname is not None and not self.rev.es_variable(fname, llamada):
                if igual and j in self.rev.vec_fijos.get(fname, ()):
                    return
                if not self.es_pedazo and j in self.rev.quietos.get(fname, ()):
                    return  # la fn no le cambia el largo a nada de lo que recibe ahí
            return self.error(node, ("arg_fn", fname, j, igual, cam))
        if que == "pedazo":
            if igual:
                return  # otro pedazo del mismo Vec no le cambia el largo
            if getattr(ctx[1], "_de_for", None) and not self.es_pedazo:
                # `for x in m` con un pedazo de `m[0]` a la vista: el pedazo del for
                # no tiene nombre, y cada `x` es `m[cualquiera]` por su camino real,
                # así que lo que el cuerpo le haga a `x` se revisa acá mismo, uso
                # por uso (`x.push(1)` choca; `x.len()` no)
                return
            return self.error(node, ("pedazo", ctx[1], cam))
        if que == "devuelve" and not self.es_pedazo:
            r = raiz_de(node)
            if r is not None and r.name == self.s[0] and getattr(r, "_vista", None) is None:
                return  # devolver el Vec mismo termina la fn: el pedazo ya no se usa
            # (por otro nombre no: `return c.w`, con `c.w` un pedazo guardado de este
            # Vec, devolvería una vista como si fuera un Vec propio)
            return self.error(node, ("valor", cam))
        if que == "devuelve" and self.rev.devuelve_vista and len(cam) == 1:
            return  # `return p` en una fn que devuelve pedazos de sus parámetros (2.5b)
        if (que == "valor" and self.es_pedazo and len(cam) == 1 and isinstance(ctx[1], AssignStmt)
                and getattr(ctx[1], "_reasigna_pedazo", False) and ctx[1].expr is node):
            return  # `p = q`: p mira lo mismo que q, y sus reglas valen para eso (2.5a)
        if que == "destino":
            if (self.es_pedazo and self.ped.mutable and isinstance(ctx[1], AssignStmt)
                    and getattr(ctx[1], "_reasigna_pedazo", False) and len(cam) == 1):
                return  # `p = w[c..d]` con `let mut p`: otro pedazo (2.5a)
            if (self.es_pedazo and not self.ped.mutable and isinstance(ctx[1], AssignStmt)
                    and len(cam) == 1 and self._fuentes_rhs(ctx[1]) is not None):
                return  # `p = w[c..d]` sin `mut`: el checker ya dice "declárala con 'let mut'"
            return self.error(node, ("destino", isinstance(ctx[1], MethodCall), cam))
        return self.error(node, ("valor", cam))

    def _fuentes_rhs(self, asignacion):
        """Lo que mira el lado derecho de `p = ...`, si es un pedazo (o None)."""
        e = asignacion.expr
        if isinstance(e, Ident) and getattr(e, "_vista", None) is not None:
            return e._vista.fuentes
        if isinstance(e, SliceExpr) and camino(e.obj) is not None:
            return []
        return None

    def error(self, node, motivo):
        p = self.ped
        clase = motivo[0]
        if self.es_pedazo:
            base = f"'{p.nombre}' es un pedazo de '{texto_camino(p.fuente)}' (línea {p.linea})"
            if getattr(p, "por_llamada", None):
                base = (f"lo que devuelve {p.por_llamada}() es un pedazo de '{texto_camino(p.fuente)}' "
                        f"(línea {p.linea})")
            if clase == "metodo":
                msg = (f"{base}, y un pedazo no se agranda ni se achica: no se le puede hacer "
                       f".{motivo[1]}()")
            elif clase == "arg_fn":
                msg = self.rev.motivo_arg(motivo[1], motivo[2], es_pedazo=True) or \
                    f"{base}: no se le puede pasar a {motivo[1] or 'esa función'}()"
            elif clase == "destino":
                msg = (f"{base}: se le asigna otro pedazo solo si se declaró con 'let mut {p.nombre} = ...', "
                       f"y lo que se le asigna tiene que ser un pedazo ('{p.nombre} = w[a..b]')"
                       if not p.mutable else
                       f"{base}: a un pedazo solo se le asigna otro pedazo ('{p.nombre} = w[a..b]'); un Vec "
                       f"propio no, porque nadie lo soltaría")
            else:
                msg = (f"{base}: es una vista de ese Vec, no un Vec propio, así que no se puede "
                       f"devolver, guardar en otro lado ni mover. Para una copia, arma un Vec nuevo con push")
        else:
            cam = motivo[-1]
            de = p.texto if p.texto and self.s == p.fuente else texto_camino(self.s)
            if p.por_for:
                base = (f"'{de}' no puede cambiar de largo mientras se recorre con "
                        f"'for {p.por_for[0]} in {p.por_for[1]}' (línea {p.linea})")
            elif getattr(p, "por_llamada", None):
                base = (f"'{de}' no puede cambiar de largo mientras se usa lo que devuelve "
                        f"{p.por_llamada}(), que mira adentro de él (línea {p.linea})")
            elif getattr(p, "es_portador", False):
                base = (f"'{de}' no puede cambiar de largo mientras se usa '{p.nombre}', que guarda un "
                        f"pedazo de él (línea {p.linea})")
            else:
                base = (f"'{de}' no puede cambiar de largo mientras se usa el pedazo '{p.nombre}' "
                        f"(línea {p.linea})")
            aca = f"'{_texto_uso(node, cam)}'" if len(cam) != len(self.s) or clase == "destino" and motivo[1] else "se"
            if clase == "metodo":
                msg = (f"{base}: acá se le hace .{motivo[1]}()" if motivo[2] and _texto_uso(node, cam) == texto_camino(cam) else
                       f"{base}: acá a '{_texto_uso(node, cam)}' se le hace .{motivo[1]}()")
            elif clase == "arg_fn":
                fname = motivo[1] or "una función"
                porque = self.rev.motivo_arg(motivo[1], motivo[2], es_pedazo=False) if motivo[3] else None
                if porque:
                    msg = f"{base}: acá se le pasa a {fname}(), que {porque}"
                elif motivo[3]:
                    msg = f"{base}: acá se le pasa a {fname}(), que puede cambiarle el largo"
                else:
                    porque = self.rev.quietos_motivos.get(motivo[1], {}).get(motivo[2])
                    msg = (f"{base}: acá '{_texto_uso(node, cam)}' se le pasa a {fname}(), que podría cambiarlo"
                           + (f" ({porque})" if porque else ""))
            elif clase == "pedazo" and getattr(motivo[1], "_de_for", None):
                x, texto = motivo[1]._de_for
                msg = (f"{base}: acá se recorre '{texto}' con 'for {x} in {texto}', y por '{x}' se lo "
                       f"podría cambiar")
            elif clase == "pedazo":
                msg = (f"{base}: acá se toma un pedazo de '{texto_camino(cam)}', que lo contiene, y por ese "
                       f"pedazo se lo podría cambiar")
            elif clase == "destino" and motivo[1]:
                msg = f"{base}: acá se cambia el elemento {aca}, y eso suelta el que había"
            elif clase == "destino":
                msg = (f"{base}: acá se le asigna otro valor" if aca == "se" else
                       f"{base}: acá a {aca} se le asigna otro valor")
            else:
                msg = (f"{base}: acá se mueve o se guarda en otro lado" if aca == "se" else
                       f"{base}: acá {aca} se mueve o se guarda en otro lado")
            if getattr(p, "por_llamada", None):
                pass
            elif p.por_for:
                msg += (f". Hazlo después del for, o recorre los índices ('for i in 0..{p.por_for[1]}.len()')")
            else:
                msg += (f". Usa '{p.nombre}' solo antes de esta línea" if getattr(p, "es_portador", False) else
                        f". Usa '{p.nombre}' solo antes de esta línea, o toma el pedazo de nuevo después")
        self.rev.fallar(msg, node)


class Revisor:
    """Revisa los `let p = v[a..b]` de una fn. `fallar(msg, nodo)` registra un
    error. Marca cada pedazo guardado (`_pedazo_ok`) para que el checker lo
    deje pasar."""

    def __init__(self, funciones, vec_fijos, fijos_motivos, prestados, quietos, quietos_motivos, fallar,
                 devueltas=None, llevadas=None):
        self.devueltas = devueltas or {}    # nombre -> de qué parámetros devuelve un pedazo (2.5b)
        self.devuelve_vista = False         # la fn que se revisa devuelve pedazos
        # nombre -> (ruta, parámetro, camino): lo que devuelve la fn guarda, en esa
        # ruta, un pedazo de ese parámetro (`fn capa(p: Vec<f64>) -> Capa { return
        # Capa { w: p[0..4] } }` da {((".", "w"),), 0, ())})
        self.llevadas = llevadas or {}
        self._retornos = []
        self.funciones = funciones          # nombre -> FnDecl
        self.vec_fijos = vec_fijos
        self.fijos_motivos = fijos_motivos
        self.prestados = prestados
        self.quietos = quietos
        self.quietos_motivos = quietos_motivos
        self._fallar = fallar
        self._vistos = set()
        self._locales = [set()]

    def fallar(self, msg, node):
        clave = (id(node), msg)
        if clave not in self._vistos:
            self._vistos.add(clave)
            self._fallar(msg, node)

    def es_variable(self, nombre, llamada):
        """True si `nombre(...)` llama a un valor fn guardado en una variable (o a
        algo que no es una fn del programa): no se sabe qué hace con el Vec."""
        return getattr(llamada, "_callee_local", False) or nombre not in self.funciones \
            or bool(self.funciones[nombre].type_params) or self.funciones[nombre].is_task

    def motivo_arg(self, fname, j, es_pedazo):
        """Por qué el parámetro j de fname no puede recibir un pedazo (o un Vec que
        un pedazo mira)."""
        decl = self.funciones.get(fname)
        if decl is None or j >= len(decl.params):
            return None
        p = decl.params[j]
        if j in self.prestados.get(fname, ()):
            porque = self.fijos_motivos.get(fname, {}).get(j)
            if es_pedazo:
                return (f"a {fname}() no se le puede pasar un pedazo en '{p.name}': puede cambiarle el largo"
                        + (f" ({porque})" if porque else "") + ", y un pedazo no se agranda ni se achica")
            return "puede cambiarle el largo" + (f" ({porque})" if porque else "")
        if es_pedazo:
            return (f"a {fname}() no se le puede pasar un pedazo en '{p.name}': se queda con ese Vec "
                    f"(lo recibe movido), y un pedazo es una vista de otro Vec, no un Vec propio")
        return "se queda con él (lo recibe movido)"

    # -- la fn ---------------------------------------------------------------
    def llama_a_vista(self, expr):
        """`f(...)` con f una fn del programa que devuelve un pedazo de un parámetro."""
        return (isinstance(expr, Call) and isinstance(expr.callee, Ident)
                and bool(self.devueltas.get(expr.callee.name)) and not self.es_variable(expr.callee.name, expr))

    def llama_a_lleva(self, expr):
        """`f(...)` con f una fn del programa que devuelve algo que guarda un pedazo
        de un parámetro."""
        return (isinstance(expr, Call) and isinstance(expr.callee, Ident)
                and bool(self.llevadas.get(expr.callee.name)) and not self.es_variable(expr.callee.name, expr))

    def recolectar(self, decl):
        """Solo la primera pasada (sin reglas ni errores): qué guarda, y de qué
        parámetros, lo que devuelve cada `return` de la fn. [(sentencia, {(ruta,
        índice de parámetro o None, camino)})]"""
        self._marcar_llamadas_a_variables(decl)
        self.devuelve_vista = bool(self.devueltas.get(decl.name))
        self._pendientes = []
        self._portadores = []
        self._retornos = []
        self._sobre_acc = {}
        self._bloque(decl.body.stmts, {})
        params = {p.name: i for i, p in enumerate(decl.params)}
        out = []
        for nodo, port, locales in self._retornos:
            entradas = set()
            for ruta, f, _, q in port.rutas():
                for c in _resolver(f, q.sobre):
                    if c[0] in locales or c[0] not in params or len(c) > 7:
                        entradas.add((ruta, None, ()))
                    else:
                        entradas.add((ruta, params[c[0]], _sufijo(c)))
            out.append((nodo, entradas))
        return out

    def revisar_fn(self, decl):
        self._marcar_llamadas_a_variables(decl)
        self.devuelve_vista = bool(self.devueltas.get(decl.name))
        self._retornos = []
        # primero, qué pedazos hay y a qué nombra cada nombre (un pedazo guardado
        # es otro nombre de un trozo de su Vec); después, las reglas de cada uno
        self._pendientes = []
        self._portadores = []
        self._sobre_acc = {}
        self._bloque(decl.body.stmts, {})
        for ped, es_pedazo, cam, stmts in self._pendientes:
            if ped is None:
                self.fallar(es_pedazo, cam)  # un error del let mismo: (None, mensaje, nodo, None)
            elif es_pedazo:
                _Congelado(self, ped, cam, True).sentencias(stmts)
            else:
                # cada Vec que el pedazo puede mirar (ya están todos: las
                # reasignaciones se juntaron en la primera pasada)
                for fuente in ped.fuentes_reales():
                    if fuente[0] != ped.nombre:
                        _Congelado(self, ped, fuente, False).sentencias(stmts)
        for port in self._portadores:
            self._reglas_portador(port)

    def _reglas_portador(self, port):
        """Una variable que guarda pedazos (2.5c): lo que mira existe desde antes
        que ella y no cambia de largo mientras ella (o un pedazo de ella) se usa,
        y ella no sale de la fn."""
        rutas = port.rutas()
        if not rutas:
            return
        mal = False
        for _, f, nodo, q in rutas:
            for c in _resolver(f, q.sobre):
                if _declara(port.resto, c[0]):
                    mal = True
                    self.fallar(f"'{port.nombre}' (línea {port.linea}) pasa a guardar un pedazo de '{c[0]}', "
                                f"que se declara después que '{port.nombre}': podría dejar de existir "
                                f"mientras '{port.nombre}' todavía lo mira. Declara '{c[0]}' antes que "
                                f"'{port.nombre}'", nodo)
        if mal:
            return
        nombres = {port.nombre} | port.alias
        ultima = -1
        for k, st in enumerate(port.resto):
            if any(menciona(st, n) for n in nombres):
                ultima = k
        zona = port.resto[:ultima + 1]
        for fuente in port.fuentes_reales():
            if fuente[0] != port.nombre:
                _Congelado(self, port, fuente, False).sentencias(zona)
        _Llevado(self, port).sentencias(port.resto)

    def _marcar_llamadas_a_variables(self, decl):
        """Marca las llamadas `f(...)` donde f es un parámetro o una variable (un
        valor fn), no una fn del programa."""
        locales = {p.name for p in decl.params}

        def juntar(n):
            if isinstance(n, LetStmt):
                locales.add(n.name)
            if isinstance(n, (Node, list, tuple, dict)):
                for h in hijos(n):
                    juntar(h)
        juntar(decl.body)

        def marcar(n):
            if isinstance(n, Call) and isinstance(n.callee, Ident) and n.callee.name in locales:
                n._callee_local = True
            if isinstance(n, (Node, list, tuple, dict)):
                for h in hijos(n):
                    marcar(h)
        marcar(decl.body)

    def _bloque(self, stmts, pedazos):
        """`pedazos`: nombre -> _Pedazo de los que están a la vista."""
        pedazos = dict(pedazos)
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, LetStmt) and (isinstance(stmt.expr, SliceExpr) or self.llama_a_vista(stmt.expr)):
                self._let_pedazo(stmt, stmts[i + 1:], pedazos)
                continue
            if isinstance(stmt, LetStmt):
                # otra variable con ese nombre. Toda variable puede llegar a guardar
                # pedazos adentro (2.5c): `let c = Capa { w: v[0..4] }`, o más
                # adelante `red.push(c)`, `c.w = v[a..b]`
                self._bajar(stmt.expr, pedazos)
                port = _Portador(stmt.name, getattr(stmt, "line", None), stmts[i + 1:])
                port.por_llamada = getattr(stmt, "de_llamada", None)
                self._portadores.append(port)
                if stmt.expr is not None:
                    self._guardar(port, (), self._carga(stmt.expr, pedazos), pedazos)
                pedazos[stmt.name] = port
                continue
            self._bajar(stmt, pedazos)

    def _bajar(self, node, pedazos):
        if isinstance(node, Ident):
            node._vista = _ped(pedazos, node.name)
            node._lleva = _port(pedazos, node.name)
        elif isinstance(node, MethodCall) and node.method == "push" and len(node.args) == 1 \
                and camino(node.obj) is not None:
            # `red.push(Capa { w: v[0..4] })`, `red.push(c)`: red pasa a guardar eso
            self._bajar(node.obj, pedazos)
            self._bajar(node.args[0], pedazos)
            self._insertar(camino(node.obj), ((IDX, None),), node.args[0], pedazos)
        elif isinstance(node, AssignStmt) and _ped(pedazos, getattr(node.target, "name", None)) is None \
                and camino(node.target) is not None \
                and not (isinstance(node.target, Ident)
                         and (isinstance(node.expr, SliceExpr) or self.llama_a_vista(node.expr))):
            # `c.w = v[a..b]`, `red[i] = Capa { ... }`, `c = otra`
            self._bajar(node.target, pedazos)
            self._bajar(node.expr, pedazos)
            self._insertar(camino(node.target), (), node.expr, pedazos)
        elif isinstance(node, ReturnStmt) and not self.devuelve_vista and node.expr is not None:
            # `return c`, `return Capa { w: p[a..b] }`, `return armar(p)`: lo devuelto
            # puede guardar pedazos de los parámetros (resolve_llevadas revisa que no
            # sean de algo local); quien llama lo recibe como una variable que los guarda
            self._bajar(node.expr, pedazos)
            self._sobre_acc = {}
            carga = self._carga(node.expr, pedazos)
            if carga:
                port = _Portador("lo devuelto", getattr(node, "line", None), ())
                self._guardar(port, (), carga, pedazos)
                self._retornos.append((node, port, set(pedazos)))
        elif isinstance(node, ReturnStmt) and self.devuelve_vista:
            # `return v[a..b]`, `return p`, `return otra(v)`: la fn devuelve pedazos
            # de sus parámetros (resolve_devueltas ya revisó que todos lo sean)
            self._bajar(node.expr, pedazos)
            self._fuentes_de(node.expr, pedazos)
        elif (isinstance(node, AssignStmt) and isinstance(node.target, Ident) and _ped(pedazos, node.target.name)
              and not pedazos[node.target.name].mutable and isinstance(node.expr, SliceExpr)):
            # `p = w[c..d]` sin `mut`: el error es del checker ("declárala con 'let
            # mut'"); el pedazo de la derecha no suma otro error
            node.target._vista = pedazos[node.target.name]
            self._bajar(node.expr, pedazos)
            if camino(node.expr.obj) is not None:
                node.expr._pedazo_ok = True
        elif (isinstance(node, AssignStmt) and isinstance(node.target, Ident)
              and _ped(pedazos, node.target.name) and pedazos[node.target.name].mutable):
            # `p = w[c..d]` con `let mut p = v[a..b]`: p puede mirar también w
            ped = pedazos[node.target.name]
            node.target._vista = ped
            self._bajar(node.expr, pedazos)
            self._sobre_acc = {}
            nuevas = self._fuentes_de(node.expr, pedazos)
            if nuevas is None:
                return  # no es un pedazo: lo dice la regla del pedazo mismo (destino)
            node._reasigna_pedazo = True
            self._anotar_sobre(ped)
            for f in nuevas:
                if _declara(ped.resto, f[0][0]):
                    # un Vec declarado después que el pedazo puede dejar de existir
                    # antes (el de un bloque de adentro, seguro): el pedazo quedaría
                    # mirando memoria suelta. Lo que mira un pedazo existe desde antes
                    self._pendientes.append((None, (
                        f"a '{ped.nombre}' (línea {ped.linea}) se le asigna un pedazo de '{f[0][0]}', que se "
                        f"declara después que '{ped.nombre}': podría dejar de existir mientras "
                        f"'{ped.nombre}' todavía lo mira. Declara '{f[0][0]}' antes que '{ped.nombre}'"),
                        node, None))
                elif f not in ped.fuentes:
                    ped.fuentes.append(f)
        elif isinstance(node, Block):
            self._bloque(node.stmts, pedazos)
        elif isinstance(node, ForStmt):
            self._bajar(node.start, pedazos)
            self._bajar(node.end, pedazos)
            adentro = dict(pedazos)
            adentro.pop(node.var, None)
            self._bloque(node.body.stmts, adentro)
        elif isinstance(node, (Node, list, tuple, dict)):
            for h in hijos(node):
                self._bajar(h, pedazos)

    def _anotar_sobre(self, quien):
        """Lo que `_fuentes_de` acaba de ver que es de un portador: `quien` (un
        pedazo o un portador) mira adentro de él."""
        for nombre, port in self._sobre_acc.items():
            if quien.sobre.get(nombre, port) is not port:
                # dos variables distintas con el mismo nombre (una tapa a la otra)
                # y `quien` mira adentro de las dos: no se sigue cuál es cuál
                self._pendientes.append((None, (
                    f"'{quien.nombre}' mira adentro de dos variables distintas que se llaman '{nombre}': "
                    f"ponle otro nombre a una de las dos"), port.resto[0] if port.resto else None, None))
                continue
            quien.sobre[nombre] = port
            if isinstance(quien, _Pedazo):
                port.alias.add(quien.nombre)
            else:
                port.alias.add(quien.nombre)
                port.alias |= quien.alias

    def _carga(self, expr, pedazos):
        """Los pedazos que `expr` lleva adentro: [(ruta, camino del Vec mirado o
        None, portador que se mueve o None, nodo)]. Un pedazo o una fn que
        devuelve uno, un struct o un `[...]` que los tiene, o una variable que ya
        guarda alguno. Marca los pedazos para que el checker los deje pasar."""
        if isinstance(expr, StructLit):
            return [(((".", campo),) + r, f, q, n)
                    for campo, e in expr.fields.items() for r, f, q, n in self._carga(e, pedazos)]
        if isinstance(expr, ArrayLit):
            return [(((IDX, None),) + r, f, q, n) for e in expr.elems for r, f, q, n in self._carga(e, pedazos)]
        if isinstance(expr, Ident):
            port = _port(pedazos, expr.name)
            return [((), None, port, expr)] if port is not None else []
        if isinstance(expr, SliceExpr) or self.llama_a_vista(expr):
            fuentes = self._fuentes_de(expr, pedazos)
            return [((), f, None, expr) for f, _ in fuentes or ()]
        if self.llama_a_lleva(expr):
            # `armar(params)`: lo que devuelve guarda pedazos de lo que se le pasó
            expr._lleva_ok = True
            out = []
            for ruta, k, suf in sorted(self.llevadas[expr.callee.name], key=repr):
                if k is None or k >= len(expr.args):
                    continue
                a = expr.args[k]
                if self.llama_a_vista(a):
                    bases = [b for b, _ in self._fuentes_de(a, pedazos) or ()]
                else:
                    cam = camino(a.obj if isinstance(a, SliceExpr) else a)
                    if cam is None:
                        self._pendientes.append((None, (
                            f"lo que devuelve {expr.callee.name}() guarda un pedazo de lo que recibe, y acá "
                            f"recibe un Vec que no está en ninguna variable: nadie lo soltaría. Guarda "
                            f"primero el Vec ('let v = ...') y pásale 'v'"), a, None))
                        continue
                    previo = _ped(pedazos, cam[0])
                    if previo is not None:
                        self._sobre_acc.update(previo.sobre)
                    elif _port(pedazos, cam[0]):
                        self._sobre_acc[cam[0]] = pedazos[cam[0]]
                    bases = reales(cam, previo) if previo is not None else [cam]
                out += [(ruta, b + suf, None, expr) for b in bases]
            return out
        return []

    def _destinos(self, cam, pedazos):
        """A qué variables de la fn (portadores) pertenece el lugar `cam`, y por qué
        camino adentro de cada una: [(portador, ruta)]. [] si no es de una variable
        de un let de esta fn (un parámetro, la variable de un bucle)."""
        port = _port(pedazos, cam[0])
        if port is not None:
            return [(port, _sufijo(cam))]
        ped = _ped(pedazos, cam[0])
        if ped is None:
            return []
        out = []
        for c in reales(cam, ped):
            port = ped.sobre.get(c[0])
            if port is None:
                return []
            out.append((port, _sufijo(c)))
        return out

    def _insertar(self, cam, extra, expr, pedazos):
        self._sobre_acc = {}
        carga = self._carga(expr, pedazos)
        if not carga:
            return
        destinos = self._destinos(cam, pedazos)
        if not destinos:
            for _, f, _, nodo in carga:
                if f is not None:
                    self._pendientes.append((None, (
                        f"un pedazo se guarda solo adentro de una variable de esta fn (un 'let'): "
                        f"'{texto_camino(cam)}' viene de afuera (un parámetro, la variable de un bucle), y "
                        f"el pedazo podría seguir ahí cuando el Vec que mira ya no exista"), nodo, None))
            return  # (una variable que guarda pedazos: lo dice su regla, _Llevado)
        for port, ruta in destinos:
            self._guardar(port, ruta + extra, carga, pedazos, anotar=False)
        for port, _ in destinos:
            self._anotar_sobre(port)

    def _guardar(self, port, ruta, carga, pedazos, anotar=True):
        for r, f, otro, nodo in carga:
            if otro is not None:
                if otro is not port:
                    port.incluye.append((ruta + r, otro, nodo))
                nodo._mueve_ok = True
            else:
                port.directas.append((ruta + r, f, nodo))
        if anotar:
            self._anotar_sobre(port)

    def _fuentes_de(self, expr, pedazos):
        """Lo que mira el pedazo `expr` (un `v[a..b]`, o el nombre de otro pedazo
        guardado): la lista de (camino del Vec de más afuera, desde). None si
        `expr` no es un pedazo de un lugar."""
        if isinstance(expr, Ident) and _ped(pedazos, expr.name):
            self._sobre_acc.update(pedazos[expr.name].sobre)
            return list(pedazos[expr.name].fuentes)
        if self.llama_a_vista(expr):
            # `mitad(w)`: un pedazo de lo que se le pasó en los parámetros de los
            # que la fn devuelve un pedazo (2.5b)
            expr._vista_ok = True
            out = []
            for k, suf in sorted(self.devueltas[expr.callee.name], key=repr):
                if k is None or k >= len(expr.args):
                    continue
                a = expr.args[k]
                if self.llama_a_vista(a):
                    # `mitad(mitad(w))`: un pedazo de lo que mira el de adentro
                    for base, _ in self._fuentes_de(a, pedazos) or ():
                        if (base + suf, None) not in out:
                            out.append((base + suf, None))
                    continue
                cam = camino(a.obj if isinstance(a, SliceExpr) else a)
                if cam is None:
                    self._pendientes.append((None, (
                        f"{expr.callee.name}() devuelve un pedazo de lo que recibe, y acá recibe un Vec que no "
                        f"está en ninguna variable: nadie lo soltaría, y el pedazo quedaría mirando memoria "
                        f"suelta. Guarda primero el Vec ('let v = ...') y pásale 'v'"), a, None))
                    continue
                previo = _ped(pedazos, cam[0])
                if previo is not None:
                    self._sobre_acc.update(previo.sobre)
                elif _port(pedazos, cam[0]):
                    self._sobre_acc[cam[0]] = pedazos[cam[0]]
                for base in (reales(cam, previo) if previo is not None else [cam]):
                    if (base + suf, None) not in out:
                        out.append((base + suf, None))
            return out or None
        if not isinstance(expr, SliceExpr):
            return None
        cam = camino(expr.obj)
        if cam is None:
            return None
        expr._pedazo_ok = True
        d = expr.desde
        desde = d.value if isinstance(d, NumLit) and isinstance(d.value, int) and not isinstance(d.value, bool) else None
        previo = _ped(pedazos, cam[0])
        if previo is None:
            if _port(pedazos, cam[0]):
                self._sobre_acc[cam[0]] = pedazos[cam[0]]
            return [(cam, desde)]
        self._sobre_acc.update(previo.sobre)
        # un pedazo de un pedazo (o de algo de adentro de uno: `p[0][a..b]`) mira
        # el Vec de más afuera
        out = []
        for f in previo.fuentes:
            c = reales(cam, _Pedazo(previo.nombre, None, [f]))[0]
            d0 = f[1]
            dd = desde + d0 if len(cam) == 1 and desde is not None and d0 is not None else None
            if (c, dd) not in out:
                out.append((c, dd))
        return out

    def _let_pedazo(self, stmt, resto, pedazos):
        self._bajar(stmt.expr, pedazos)
        self._sobre_acc = {}
        fuentes = self._fuentes_de(stmt.expr, pedazos)
        if fuentes is None:
            return  # no es un lugar: el checker ya lo dice
        ped = _Pedazo(stmt.name, getattr(stmt, "line", None), fuentes, getattr(stmt, "de_for", None),
                      mutable=stmt.mutable)
        ped.resto = resto
        ped.por_llamada = getattr(stmt, "de_llamada", None)
        self._anotar_sobre(ped)
        fuente = ped.fuente
        if isinstance(stmt.expr, SliceExpr):
            ped.texto = _texto_uso(stmt.expr.obj, fuente)
        # 1. el pedazo mismo, hasta el final del bloque
        self._pendientes.append((ped, True, (stmt.name,), resto))
        # 2. el Vec de origen, mientras el pedazo se usa
        ultima = -1
        for k, s in enumerate(resto):
            if menciona(s, stmt.name):
                ultima = k
            if isinstance(s, LetStmt) and s.name == stmt.name:
                break  # otra variable con ese nombre: lo que sigue ya no es este pedazo
        self._pendientes.append((ped, False, None, resto[:ultima + 1]))
        pedazos[stmt.name] = ped


# ---------------------------------------------------------------------------
# Fns que devuelven un pedazo de un parámetro (2.5b)
# ---------------------------------------------------------------------------

LOCAL = (None, ())   # un pedazo de algo que no es de un parámetro


def _sufijo(cam):
    """Los tramos de un camino después de su raíz, con cualquier índice."""
    return tuple((IDX, None) if seg[0] == IDX else seg for seg in cam[1:])


def _tope(fuentes):
    """Un camino que no para de crecer (una fn recursiva que devuelve un pedazo de
    `c.sub`, de `c.sub.sub`, ...) no se sigue: cuenta como algo que no es de un
    parámetro, y la fn da su error en vez de colgar al compilador."""
    return {f if f[0] is None or len(f[1]) <= 6 else LOCAL for f in fuentes}


def subir_llamadas(items, nombre_de, contador):
    """Baja el uso directo de lo que devuelve una fn de pedazos (`print(mitad(w))`,
    `mitad(w).suma()`, `f(mitad(w))`, `armar(p).w`) a lo que ya tiene sus reglas:

        let _vistaK = mitad(w)     # justo antes de la sentencia
        print(_vistaK)

    `nombre_de(call)` da el nombre de la fn si la llamada devuelve un pedazo (o
    algo que guarda uno), o None. Solo se sube lo que se evalúa una vez y antes
    que cualquier otra llamada de la sentencia (el orden en que corren las cosas
    no cambia). `contador` ([n]) es del programa: los nombres no dependen de qué
    se compiló antes en el mismo proceso. No se sube desde la condición de un while, ni del lado derecho de
    and/or, ni si antes hay otra llamada. Lo que no se sube queda como estaba, y
    el checker pide guardarlo con let. Devuelve cuántas subió."""
    cuenta = [0]

    def raices(st):
        if isinstance(st, (ExprStmt, LetStmt, ReturnStmt)):
            return ["expr"]
        if isinstance(st, AssignStmt):
            return ["target", "expr"]
        if isinstance(st, IfStmt):
            return ["cond"]
        if isinstance(st, ForStmt):
            return ["start", "end"]
        return []

    def bloque(blk):
        i = 0
        while i < len(blk.stmts):
            st = blk.stmts[i]
            nuevas = []
            sucio = [False]

            def ver(n, donde):
                """Recorre en el orden en que se evalúa; devuelve el nodo o su reemplazo."""
                if isinstance(n, (Block, IfExpr)) or not isinstance(n, Node):
                    return n
                if isinstance(n, BinOp) and n.op in ("and", "or"):
                    n.left = ver(n.left, "op")
                    sucio[0] = True   # el lado derecho puede no correr: nada de ahí se sube
                    return n
                fname = nombre_de(n) if isinstance(n, Call) else None
                if fname is not None and not sucio[0] and donde in ("print", "obj", "arg", "op", "campo"):
                    contador[0] += 1
                    nombre = f"_vista{contador[0]}"
                    let = LetStmt(nombre, n).at(n)
                    let.oculta = True
                    let.de_llamada = fname
                    nuevas.append(let)
                    cuenta[0] += 1
                    return Ident(nombre).at(n)
                if isinstance(n, PrintExpr):
                    n.args = [ver(a, "print") for a in n.args]
                elif isinstance(n, MethodCall):
                    n.obj = ver(n.obj, "obj")
                    n.args = [ver(a, "push" if n.method == "push" else "arg") for a in n.args]
                    if n.method not in METODOS_QUE_LEEN:
                        sucio[0] = True   # (los que solo leen no cambian nada: no importa el orden)
                elif isinstance(n, Call):
                    es_vista = fname is not None
                    n.args = [ver(a, "anidada" if es_vista else "arg") for a in n.args]
                    if not (isinstance(n.callee, Ident) and n.callee.name in _FNS_QUE_SOLO_CALCULAN):
                        sucio[0] = True
                elif isinstance(n, (IndexExpr, SliceExpr)):
                    n.obj = ver(n.obj, "obj")
                    for k in ("index", "desde", "hasta"):
                        if hasattr(n, k):
                            setattr(n, k, ver(getattr(n, k), "otro"))
                elif isinstance(n, FieldAccess):
                    n.obj = ver(n.obj, "campo")
                elif isinstance(n, BinOp):
                    n.left = ver(n.left, "op")
                    n.right = ver(n.right, "op")
                elif isinstance(n, UnaryOp):
                    n.expr = ver(n.expr, "op")
                else:
                    # cualquier otra cosa (un literal de struct, Some(...), spawn, ?):
                    # nada de adentro se sube, y lo que sigue ya no es lo primero
                    if any(isinstance(h, Node) for h in hijos(n)):
                        sucio[0] = True
                return n

            for attr in raices(st):
                setattr(st, attr, ver(getattr(st, attr), "raiz"))
            blk.stmts[i:i] = nuevas
            i += len(nuevas) + 1

    def buscar(n):
        if isinstance(n, Block):
            bloque(n)
        if isinstance(n, (Node, list, tuple, dict)):
            for h in hijos(n):
                buscar(h)

    for it in items:
        if isinstance(it, FnDecl):
            buscar(it.body)
    return cuenta[0]


_FNS_QUE_SOLO_CALCULAN = frozenset(["to_f64", "to_f32", "to_i32", "to_i64", "len", "a_texto", "abs", "sqrt",
                                    "min", "max"])


def _retornos_de(decl, tabla):
    """Los `return` de una fn, cada uno con lo que mira lo que devuelve:
    [(sentencia, fuentes o None)]. `fuentes` es un conjunto de (índice del
    parámetro, camino desde él) -- (0, ()) para `return v[a..b]` con v el primer
    parámetro, (1, ((".", "pesos"),)) para `return c.pesos[a..b]` -- o LOCAL si el
    pedazo es de un Vec que no llegó por un parámetro. None si no devuelve un
    pedazo. Sigue los pedazos guardados (`let p = v[a..b]`, `p = w[c..d]`) y las
    llamadas a otras fns de `tabla`, con el alcance de cada nombre."""
    vistas = {}      # id del let -> conjunto de fuentes (crece hasta un punto fijo)
    retornos = []
    cambio = [True]

    def de_lugar(expr, env):
        c = camino(expr)
        if c is None:
            return {LOCAL}
        v = env.get(c[0])
        if isinstance(v, int) and not isinstance(v, bool):
            return _tope({(v, _sufijo(c))})
        if isinstance(v, set):
            return _tope({(k, s + _sufijo(c)) if k is not None else LOCAL for k, s in v})
        return {LOCAL}

    def vista(expr, env):
        if isinstance(expr, SliceExpr):
            return de_lugar(expr.obj, env)
        if isinstance(expr, Ident) and isinstance(env.get(expr.name), set):
            return set(env[expr.name])
        if (isinstance(expr, Call) and isinstance(expr.callee, Ident) and expr.callee.name not in env
                and tabla.get(expr.callee.name)):
            out = set()
            for k, suf in tabla[expr.callee.name]:
                if k is None or k >= len(expr.args):
                    continue
                a = expr.args[k]
                base = vista(a, env)
                if base is None:
                    base = de_lugar(a, env)
                out |= {(kk, s + suf) if kk is not None else LOCAL for kk, s in base}
            return _tope(out)
        return None

    def bloque(stmts, env):
        env = dict(env)
        for st in stmts:
            ver(st, env)

    def ver(node, env):
        if isinstance(node, Block):
            return bloque(node.stmts, env)
        if isinstance(node, LetStmt):
            ver(node.expr, env)
            v = vista(node.expr, env)
            if v is None:
                env[node.name] = None
            else:
                s = vistas.setdefault(id(node), set())
                if not v <= s:
                    s |= v
                    cambio[0] = True
                env[node.name] = s
            return
        if isinstance(node, AssignStmt) and isinstance(node.target, Ident) \
                and isinstance(env.get(node.target.name), set):
            v = vista(node.expr, env)
            s = env[node.target.name]
            if v is not None and not v <= s:
                s |= v
                cambio[0] = True
            return
        if isinstance(node, ReturnStmt):
            ver(node.expr, env)
            retornos.append((node, vista(node.expr, env) if node.expr is not None else None))
            return
        if isinstance(node, ForStmt):
            ver(node.start, env)
            ver(node.end, env)
            adentro = dict(env)
            adentro[node.var] = None
            return bloque(node.body.stmts, adentro)
        if isinstance(node, WhileLetStmt):
            ver(node.expr, env)
            adentro = dict(env)
            adentro[node.pattern] = None
            return bloque(node.body.stmts, adentro)
        if isinstance(node, (Node, list, tuple, dict)):
            for h in hijos(node):
                ver(h, env)

    env0 = {p.name: i for i, p in enumerate(decl.params)}
    while cambio[0]:
        cambio[0] = False
        retornos.clear()
        bloque(decl.body.stmts, env0)
    return retornos


def resolve_llevadas(items, devueltas, structs, problemas=None):
    """nombre -> frozenset de (ruta, índice de parámetro, camino): lo que devuelve
    la fn guarda en `ruta` un pedazo de ese parámetro. Con `fn capa(p: Vec<f64>,
    a: i32) -> Capa { return Capa { w: p[a..a + 4] } }`, en quien llama `let c =
    capa(params, 0)` es una variable que guarda un pedazo de `params` (2.5c). Se
    deduce con la primera pasada del Revisor, hasta un punto fijo. Un pedazo de
    algo que no llegó por un parámetro queda en `problemas`. Solo fns normales
    que devuelven un struct o un Vec."""
    funciones = {it.name: it for it in items if isinstance(it, FnDecl)}
    fns = {name: d for name, d in funciones.items()
           if not d.is_task and not d.type_params
           and getattr(d.return_type, "name", None) in set(structs) | {"Vec"}
           and not devueltas.get(name)}
    tabla = {name: frozenset() for name in fns}

    def retornos(decl):
        rev = Revisor(funciones, {}, {}, {}, {}, {}, lambda *a, **k: None,
                      devueltas=devueltas, llevadas=tabla)
        return rev.recolectar(decl)

    cambio = True
    vueltas = 0
    while cambio and vueltas < 12:
        cambio = False
        vueltas += 1
        for name, decl in fns.items():
            juntas = set()
            for _, entradas in retornos(decl):
                juntas |= entradas
            if not juntas <= tabla[name]:
                tabla[name] = tabla[name] | frozenset(juntas)
                cambio = True
    if problemas is not None:
        for name, decl in fns.items():
            if not tabla[name]:
                continue
            for st, entradas in retornos(decl):
                if any(k is None for _, k, _ in entradas):
                    problemas.append((st, (
                        f"lo que devuelve '{name}' guarda un pedazo de un Vec que no llegó por un "
                        f"parámetro: ese Vec deja de existir cuando la fn vuelve, y el pedazo quedaría "
                        f"apuntando a nada. Guarda pedazos de un parámetro, o un Vec propio")))
    return tabla


def resolve_devueltas(items, problemas=None):
    """nombre -> frozenset de (índice de parámetro, camino desde él): de qué
    devuelve un pedazo cada fn (`fn mitad(v: Vec<f64>) -> Vec<f64> { return
    v[0..v.len() / 2] }` da {(0, ())}). Vacío si la fn no devuelve pedazos. En
    quien llama, `let p = mitad(w)` es un pedazo de `w`.

    Una fn devuelve siempre pedazos o siempre un Vec propio (quien recibe el
    resultado tiene que saber si lo suelta), y un pedazo devuelto es de algo que
    llegó por un parámetro (lo local deja de existir al volver). Lo que no cumple
    queda en `problemas` (una lista de (nodo, mensaje)). Solo fns normales: ni
    tasks ni genéricas."""
    fns = {it.name: it for it in items
           if isinstance(it, FnDecl) and not it.is_task and not it.type_params
           and getattr(it.return_type, "name", None) == "Vec"}
    tabla = {name: frozenset() for name in fns}
    cambio = True
    while cambio:
        cambio = False
        for name, decl in fns.items():
            fuentes = set()
            for _, v in _retornos_de(decl, tabla):
                if v is not None:
                    fuentes |= v
            if not fuentes <= tabla[name]:
                tabla[name] = tabla[name] | frozenset(fuentes)
                cambio = True
    if problemas is not None:
        for name, decl in fns.items():
            if not tabla[name]:
                continue
            for st, v in _retornos_de(decl, tabla):
                if v is None:
                    problemas.append((st, (
                        f"'{name}' devuelve un pedazo en otro 'return' y acá un Vec propio: una fn devuelve "
                        f"siempre pedazos o siempre un Vec propio, porque quien recibe el resultado tiene que "
                        f"saber si lo suelta. Para devolver el Vec entero como pedazo, 'return v[0..v.len()]'")))
                elif LOCAL in v:
                    problemas.append((st, (
                        f"'{name}' devuelve un pedazo de un Vec que no llegó por un parámetro: ese Vec deja de "
                        f"existir cuando la fn vuelve, y el pedazo quedaría apuntando a nada. Devuelve el Vec "
                        f"mismo, o un pedazo de un parámetro. (También sale esto si el pedazo es de "
                        f"algo cada vez más adentro del parámetro, como en una fn recursiva: eso "
                        f"todavía no se sigue)")))
    return tabla


# ---------------------------------------------------------------------------
# Parámetros mirados por un pedazo
# ---------------------------------------------------------------------------

def resolve_vistas(items, structs=None, genericos=None, hondas=None):
    """nombre -> frozenset de los índices de los parámetros de los que la fn toma
    un pedazo (`v[a..b]`, de él o de algo suyo: `c.pesos[a..b]`), o que le pasa a
    otra fn que lo hace. Mientras esa fn corre hay una vista de ese parámetro: el
    mismo Vec no puede llegarle además por otro parámetro que lo agrande.

    Si se pasa `hondas` (un dict), se llena con nombre -> frozenset de los
    parámetros mirados *por adentro*: el pedazo no es del parámetro mismo sino de
    algo que tiene adentro (`a[0][x..y]`, `c.pesos[x..y]`), o es de un Vec cuyos
    elementos tienen Vec adentro (por ese pedazo se llega a ellos). Para esos no
    alcanza con que el otro parámetro no cambie de largo: `b[0].push(x)` no le
    cambia el largo a `b` y suelta el buffer que `a[0][x..y]` mira. El otro
    tiene que ser quieto. `structs` y `genericos`, como en resolve_quietos."""
    fns = {it.name: it for it in items if isinstance(it, FnDecl)}
    vistas = {name: set() for name in fns}
    hondo = {name: set() for name in fns}

    def ver(node, idx, tipos, encontrados, adentro):
        if isinstance(node, SliceExpr):
            c = camino(node.obj)
            if c is not None and c[0] in idx:
                k = idx[c[0]]
                encontrados.add(k)
                t = tipo_de_camino(c, tipos[k], structs or {}, genericos or {}) if tipos[k] is not None else None
                de_numeros = t is not None and t.name == "Vec" and bool(t.args) and _es_numero(t.args[0])
                if len(c) > 1 or not de_numeros:
                    adentro.add(k)
        elif isinstance(node, Call) and isinstance(node.callee, Ident) and node.callee.name in fns:
            for j in vistas[node.callee.name]:
                if j < len(node.args):
                    c = camino(node.args[j])
                    if c is not None and c[0] in idx:
                        encontrados.add(idx[c[0]])
                        if len(c) > 1 or j in hondo[node.callee.name]:
                            adentro.add(idx[c[0]])
        if isinstance(node, (Node, list, tuple, dict)):
            for h in hijos(node):
                ver(h, idx, tipos, encontrados, adentro)

    cambio = True
    while cambio:
        cambio = False
        for name, decl in fns.items():
            idx = {p.name: i for i, p in enumerate(decl.params)}
            tipos = [p.type_ann for p in decl.params]
            encontrados, adentro = set(), set()
            ver(decl.body, idx, tipos, encontrados, adentro)
            if not encontrados <= vistas[name] or not adentro <= hondo[name]:
                vistas[name] |= encontrados
                hondo[name] |= adentro
                cambio = True
    if hondas is not None:
        hondas.update({name: frozenset(v) for name, v in hondo.items()})
    return {name: frozenset(v) for name, v in vistas.items()}


# ---------------------------------------------------------------------------
# Parámetros quietos
# ---------------------------------------------------------------------------
#
# Un parámetro es quieto si la fn no le cambia el largo ni le suelta ningún Vec,
# ni a él ni a nada de lo que tiene adentro (los Vec de sus campos, los Vec de
# un Vec de Vec): solo lee, escribe números (`c.pesos[i] = x`, `c.columnas = 3`)
# y lo pasa a parámetros que también son quietos. Mientras un pedazo mira un Vec
# de `c`, a una fn se le puede pasar `c` solo por un parámetro quieto. Es lo
# mismo que "no cambia de largo" (fresh_owned.resolve_vec_fijos), pero mirando
# también hacia adentro, con los tipos de los campos. Lista blanca.

_ESCALARES = ESCALARES


def _es_numero(t):
    return t is not None and t.name in _ESCALARES and not t.args


def _es_copia(t):
    """Un valor que se copia al leerlo: un número, un bool o un str."""
    return t is not None and t.name in _ESCALARES + ("str",) and not t.args


def tipo_de_camino(cam, tipo, structs, genericos):
    """El tipo de un lugar, bajando por los campos y los elementos desde el tipo
    de su raíz. None si no se sabe (un struct genérico, algo que no es un Vec)."""
    for seg in cam[1:]:
        if tipo is None:
            return None
        if seg[0] == IDX:
            tipo = tipo.args[0] if tipo.name == "Vec" and tipo.args else None
        else:
            campos = structs.get(tipo.name)
            if campos is None or genericos.get(tipo.name) or tipo.args:
                return None
            tipo = campos.get(seg[1])
    return tipo


class _Quietos(_Recorrido):
    def __init__(self, items, structs, genericos):
        self.fns = {it.name: it for it in items
                    if isinstance(it, FnDecl) and not it.is_task and not it.type_params}
        self.structs = structs
        self.genericos = genericos
        self.quietos = {name: set(range(len(d.params))) for name, d in self.fns.items()}
        self.motivos = {name: {} for name in self.fns}

    def run(self):
        cambio = True
        while cambio:
            cambio = False
            for name, decl in self.fns.items():
                if not self.quietos[name]:
                    continue
                self._actual = name
                self._params = {p.name: (i, p.type_ann) for i, p in enumerate(decl.params)}
                self._locales = set()
                _juntar_locales(decl.body, self._locales)
                # los pedazos guardados (`let p = c.capas[a..b]`, el de un `for x in
                # c.capas`) son otro nombre de un lugar: lo que se haga por ellos
                # cuenta para el parámetro
                self._alias = {}
                _juntar_alias(decl.body, self._alias)
                for nombre in self._params:
                    self._alias.pop(nombre, None)
                self._cambio = False
                self.sentencias(decl.body.stmts)
                cambio = cambio or self._cambio
        return {name: frozenset(v) for name, v in self.quietos.items()}

    def _sacar(self, k, node, cam, que):
        if k in self.quietos[self._actual]:
            self.quietos[self._actual].discard(k)
            linea = getattr(node, "line", None)
            self.motivos[self._actual].setdefault(
                k, que.replace("{}", f"'{texto_camino(cam)}'") + (f" (línea {linea})" if linea else ""))
            self._cambio = True

    def _desalias(self, cam, prof=0):
        bases = self._alias.get(cam[0])
        if not bases or prof > 6:
            return [cam]
        resto = cam[1:]
        if resto and resto[0][0] == IDX:
            resto = ((IDX, None),) + resto[1:]
        out = []
        for base in bases:
            out += self._desalias(base + resto, prof + 1)
        return out

    def uso(self, node, cam, ctx):
        if cam[0] in self._alias:
            if (len(cam) == 1 and ctx[0] == "destino" and isinstance(ctx[1], AssignStmt)
                    and ctx[1].target is node and isinstance(ctx[1].expr, SliceExpr)):
                return  # `p = v[c..d]`: el pedazo pasa a mirar otra cosa
            for c in self._desalias(cam):
                if c[0] not in self._alias:
                    self._uso(node, c, ctx)
            return
        self._uso(node, cam, ctx)

    def _uso(self, node, cam, ctx):
        info = self._params.get(cam[0])
        if info is None:
            return
        k, tipo_raiz = info
        if k not in self.quietos[self._actual]:
            return
        t = tipo_de_camino(cam, tipo_raiz, self.structs, self.genericos)
        que = ctx[0]
        if que == "lee":
            return
        if que == "metodo":
            m = ctx[1].method
            if m in METODOS_QUE_LEEN or m in ("acumular", "llenar"):
                return
            if m in ("set", "replace") and t is not None and t.name == "Vec" and t.args and _es_numero(t.args[0]):
                return
            if t is not None and t.name not in ("Vec", "Map") and t.name not in self.structs:
                return  # un método de un str, de un canal...: no toca ningún Vec
            return self._sacar(k, node, cam, f"le hace .{m}() a {{}}")
        if _es_copia(t):
            return  # un número o un texto: se copia
        if que == "arg_metodo":
            if ctx[1].method in ("punto", "acumular") and ctx[2] == 0:
                return
            return self._sacar(k, node, cam, "mueve o guarda {}")
        if que == "arg_fn":
            llamada, j = ctx[1], ctx[2]
            fname = llamada.callee.name if isinstance(llamada.callee, Ident) else None
            if fname in self.fns and fname not in self._locales and j in self.quietos[fname]:
                return
            return self._sacar(k, node, cam, f"le pasa {{}} a {fname or 'una función'}(), que puede cambiarlo")
        if que == "pedazo":
            if t is not None and t.name == "Vec" and t.args and _es_numero(t.args[0]):
                return  # un pedazo de un Vec de números nunca le cambia el largo
            fuera = ctx[2]
            if fuera[0] == "valor" and isinstance(fuera[1], (LetStmt, AssignStmt)) and fuera[1].expr is ctx[1] \
                    and (isinstance(fuera[1], LetStmt) or isinstance(fuera[1].target, Ident)) \
                    and getattr(fuera[1], "name", getattr(getattr(fuera[1], "target", None), "name", None)) in self._alias:
                return  # un pedazo guardado: lo que se haga por él se mira por su nombre
            if fuera[0] == "arg_fn":
                llamada, j = fuera[1], fuera[2]
                fname = llamada.callee.name if isinstance(llamada.callee, Ident) else None
                if fname in self.fns and fname not in self._locales and j in self.quietos[fname]:
                    return  # se le pasa a una fn que tampoco cambia nada
            return self._sacar(k, node, cam, "toma un pedazo de {}")
        if que == "destino":
            return self._sacar(k, node, cam, "le asigna otro valor a {}")
        return self._sacar(k, node, cam, "mueve, guarda o devuelve {}")


def _juntar_alias(n, alias):
    """nombre -> los lugares de los que es un pedazo guardado (`let p = v[a..b]`,
    `p = w[c..d]`), en toda la fn y sin mirar el alcance (de más, nunca de menos)."""
    if isinstance(n, LetStmt) and isinstance(n.expr, SliceExpr):
        c = camino(n.expr.obj)
        if c is not None:
            alias.setdefault(n.name, []).append(c)
    elif isinstance(n, AssignStmt) and isinstance(n.target, Ident) and isinstance(n.expr, SliceExpr):
        c = camino(n.expr.obj)
        if c is not None:
            alias.setdefault(n.target.name, []).append(c)
    if isinstance(n, (Node, list, tuple, dict)):
        for h in hijos(n):
            _juntar_alias(h, alias)


def _juntar_locales(n, locales):
    if isinstance(n, LetStmt):
        locales.add(n.name)
    if isinstance(n, (Node, list, tuple, dict)):
        for h in hijos(n):
            _juntar_locales(h, locales)


def resolve_quietos(items, structs, genericos, motivos=None):
    """nombre -> frozenset de los índices de los parámetros quietos de cada fn
    normal. `structs`: nombre -> {campo: tipo}; `genericos`: nombre -> parámetros
    de tipo del struct. Si se pasa `motivos`, se llena con nombre -> {índice: por
    qué ese parámetro no es quieto}."""
    q = _Quietos(items, structs, genericos)
    r = q.run()
    if motivos is not None:
        motivos.update(q.motivos)
    return r
