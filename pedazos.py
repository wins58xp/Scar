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
    WhileLetStmt, WhileStmt, hijos,
)

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


def real(cam, ped):
    """El camino `cam`, que empieza en el pedazo guardado `ped`, dicho desde el Vec
    que el pedazo mira: `p` es ese Vec y `p[i]` es uno de sus elementos (el
    `i + desde`, si los dos son números escritos; si no, cualquiera)."""
    resto = cam[1:]
    if resto and resto[0][0] == IDX:
        i = resto[0][1]
        resto = ((IDX, i + ped.desde if i is not None and ped.desde is not None else None),) + resto[1:]
    return ped.fuente + resto


def camino_real(expr, cam=None):
    """Como camino(), pero si el lugar empieza en un pedazo guardado (`p[0].pesos`
    con `let p = red[2..5]`) da el camino desde el Vec de origen (`red[2].pesos`):
    dos nombres para el mismo lugar dan el mismo camino. Revisor deja en cada
    Ident que nombra un pedazo guardado su `_vista`."""
    if cam is None:
        cam = camino(expr)
    if cam is None:
        return None
    r = raiz_de(expr)
    ped = getattr(r, "_vista", None) if r is not None else None
    return real(cam, ped) if ped is not None else cam


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


class _Pedazo:
    __slots__ = ("nombre", "linea", "fuente", "desde")

    def __init__(self, nombre, linea, fuente, desde=None):
        self.nombre = nombre    # la variable
        self.linea = linea      # la línea de su let
        self.fuente = fuente    # el camino del Vec que mira (el de más afuera)
        self.desde = desde      # dónde empieza en ese Vec, si es un número escrito


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
            if self.tapada and getattr(r, "_vista", None) is None:
                return  # otra variable, que tapa a la del Vec de origen
            vista = getattr(r, "_vista", None)
            if vista is not None and len(cam) == 1 and len(vista.fuente) == len(self.s):
                return  # un pedazo de este mismo Vec, entero: ya lo miran sus propias reglas
            cam = camino_real(node, cam)
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
            return self.error(node, ("pedazo", cam))
        if que == "devuelve" and not self.es_pedazo:
            return  # devolver el Vec termina la fn: el pedazo ya no se usa
        if que == "destino":
            return self.error(node, ("destino", isinstance(ctx[1], MethodCall), cam))
        return self.error(node, ("valor", cam))

    def error(self, node, motivo):
        p = self.ped
        clase = motivo[0]
        if self.es_pedazo:
            base = f"'{p.nombre}' es un pedazo de '{texto_camino(p.fuente)}' (línea {p.linea})"
            if clase == "metodo":
                msg = (f"{base}, y un pedazo no se agranda ni se achica: no se le puede hacer "
                       f".{motivo[1]}()")
            elif clase == "arg_fn":
                msg = self.rev.motivo_arg(motivo[1], motivo[2], es_pedazo=True) or \
                    f"{base}: no se le puede pasar a {motivo[1] or 'esa función'}()"
            elif clase == "destino":
                msg = f"{base} y no se reasigna: para otro pedazo, usa otro 'let'"
            else:
                msg = (f"{base}: es una vista de ese Vec, no un Vec propio, así que no se puede "
                       f"devolver, guardar en otro lado ni mover. Para una copia, arma un Vec nuevo con push")
        else:
            cam = motivo[-1]
            de = texto_camino(self.s)
            base = (f"'{de}' no puede cambiar de largo mientras se usa el pedazo '{p.nombre}' "
                    f"(línea {p.linea})")
            aca = f"'{texto_camino(cam)}'" if len(cam) != len(self.s) or clase == "destino" and motivo[1] else "se"
            if clase == "metodo":
                msg = (f"{base}: acá se le hace .{motivo[1]}()" if motivo[2] else
                       f"{base}: acá a '{texto_camino(cam)}' se le hace .{motivo[1]}()")
            elif clase == "arg_fn":
                fname = motivo[1] or "una función"
                porque = self.rev.motivo_arg(motivo[1], motivo[2], es_pedazo=False) if motivo[3] else None
                if porque:
                    msg = f"{base}: acá se le pasa a {fname}(), que {porque}"
                elif motivo[3]:
                    msg = f"{base}: acá se le pasa a {fname}(), que puede cambiarle el largo"
                else:
                    porque = self.rev.quietos_motivos.get(motivo[1], {}).get(motivo[2])
                    msg = (f"{base}: acá '{texto_camino(cam)}' se le pasa a {fname}(), que podría cambiarlo"
                           + (f" ({porque})" if porque else ""))
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
            msg += (f". Usa '{p.nombre}' solo antes de esta línea, o toma el pedazo de nuevo después")
        self.rev.fallar(msg, node)


class Revisor:
    """Revisa los `let p = v[a..b]` de una fn. `fallar(msg, nodo)` registra un
    error. Marca cada pedazo guardado (`_pedazo_ok`) para que el checker lo
    deje pasar."""

    def __init__(self, funciones, vec_fijos, fijos_motivos, prestados, quietos, quietos_motivos, fallar):
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
    def revisar_fn(self, decl):
        self._marcar_llamadas_a_variables(decl)
        # primero, qué pedazos hay y a qué nombra cada nombre (un pedazo guardado
        # es otro nombre de un trozo de su Vec); después, las reglas de cada uno
        self._pendientes = []
        self._bloque(decl.body.stmts, {})
        for ped, es_pedazo, cam, stmts in self._pendientes:
            if ped is None:
                self.fallar(es_pedazo, cam)  # un error del let mismo: (None, mensaje, nodo, None)
            else:
                _Congelado(self, ped, cam, es_pedazo).sentencias(stmts)

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
            if isinstance(stmt, LetStmt) and isinstance(stmt.expr, SliceExpr):
                self._let_pedazo(stmt, stmts[i + 1:], pedazos)
                continue
            if isinstance(stmt, LetStmt):
                pedazos.pop(stmt.name, None)  # otra variable con ese nombre
            self._bajar(stmt, pedazos)

    def _bajar(self, node, pedazos):
        if isinstance(node, Ident):
            node._vista = pedazos.get(node.name)
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

    def _let_pedazo(self, stmt, resto, pedazos):
        self._bajar(stmt.expr, pedazos)
        cam = camino(stmt.expr.obj)
        if cam is None:
            return  # no es un lugar: el checker ya lo dice
        stmt.expr._pedazo_ok = True
        if stmt.mutable:
            self._pendientes.append((None, f"un pedazo guardado no lleva 'mut': '{stmt.name}' no se reasigna "
                                     f"(sus elementos se escriben igual, con '{stmt.name}[i] = x'). Para otro "
                                     f"pedazo, usa otro 'let'", stmt, None))
        d = stmt.expr.desde
        desde = d.value if isinstance(d, NumLit) and isinstance(d.value, int) and not isinstance(d.value, bool) else None
        previo = pedazos.get(cam[0])
        if previo is not None:
            # un pedazo de un pedazo (o de algo de adentro de uno: `p[0][a..b]`)
            # mira el Vec de más afuera
            fuente = real(cam, previo)
            if len(cam) == 1:
                desde = desde + previo.desde if desde is not None and previo.desde is not None else None
        else:
            fuente = cam
        ped = _Pedazo(stmt.name, getattr(stmt, "line", None), fuente, desde)
        # 1. el pedazo mismo, hasta el final del bloque
        self._pendientes.append((ped, True, (stmt.name,), resto))
        # 2. el Vec de origen, mientras el pedazo se usa
        ultima = -1
        for k, s in enumerate(resto):
            if menciona(s, stmt.name):
                ultima = k
            if isinstance(s, LetStmt) and s.name == stmt.name:
                break  # otra variable con ese nombre: lo que sigue ya no es este pedazo
        if fuente[0] != stmt.name:
            self._pendientes.append((ped, False, fuente, resto[:ultima + 1]))
        pedazos[stmt.name] = ped


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

_ESCALARES = ("i32", "i64", "f32", "f64", "bool")


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

    def uso(self, node, cam, ctx):
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
            return self._sacar(k, node, cam, "toma un pedazo de {}")
        if que == "destino":
            return self._sacar(k, node, cam, "le asigna otro valor a {}")
        return self._sacar(k, node, cam, "mueve, guarda o devuelve {}")


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
