"""if como expresión.

`let x = if c { .. a } else { .. b }` se baja, después de un primer pase del
checker (que dio el tipo del valor en `IfExpr.tipo_if` y todos los errores),
a código de siempre:

    let mut si_1: T = <un valor cualquiera de T>
    if c { ..; si_1 = a } else { ..; si_1 = b }
    let x = si_1

y el checker vuelve a correr sobre el programa bajado (type_checker.check).
El intérprete y el codegen nunca ven un IfExpr: reciben un if normal y una
variable, con todas las reglas de propiedad de siempre (como enum_match con
el match que da un valor).

Formas directas, sin temporal: `x = if ..` asigna `x` en cada rama y
`return if ..` hace `return` en cada rama. Un `else if` se baja a la misma
cadena. En cualquier otro lugar (un argumento, un operando, un campo) el if
va a un temporal, y para no cambiar el orden de evaluación, lo que estaba a
su izquierda en la misma expresión y no es un literal ni un lugar (una
llamada, una cuenta) también va antes a un temporal. `a and (if ..)` se
baja a `if a { if .. } else { false }` (el if de la derecha solo corre si
hace falta), y `a or (if ..)` igual.
"""

import copy

from parser import (
    ArrayLit, AssignStmt, OkExpr, BinOp, Block, BoolLit, Call, ExprStmt, FieldAccess, FnDecl,
    ForStmt, Ident, IfExpr, IfStmt, IndexExpr, LetStmt, MethodCall, Node, NoneExpr, NumLit,
    PrintExpr, ReturnStmt, StrLit, StructDecl, StructLit, WhileLetStmt, WhileStmt,
    es_panic, hijos,
)
from types_ import TypeAnn, T_BOOL, T_VOID

_POSICION = ("line", "col", "archivo")


class ErrorIf:
    def __init__(self, msg, node):
        self.msg = msg
        self.line = getattr(node, "line", None)
        self.col = getattr(node, "col", None)
        self.archivo = getattr(node, "archivo", None)


def _pos(node, src):
    for k in _POSICION:
        v = getattr(src, k, None)
        if v is not None:
            setattr(node, k, v)
    return node


def tiene_if(n):
    """True si en `n` (un nodo, una lista, un bloque) hay algún IfExpr."""
    pila = [n]
    while pila:
        x = pila.pop()
        if isinstance(x, IfExpr):
            return True
        if isinstance(x, (Node, list, tuple, dict)):
            pila.extend(h for h in hijos(x) if isinstance(h, (Node, list, tuple, dict)))
    return False


def _trivial(e):
    """Un literal o un lugar: evaluarlo antes o después da lo mismo, y
    sacarlo a un temporal movería un valor que no es Copy."""
    if isinstance(e, (NumLit, StrLit, BoolLit, NoneExpr, Ident)):
        return True
    while isinstance(e, FieldAccess):
        e = e.obj
    return isinstance(e, Ident)


def _mismo_lugar(a, b):
    if isinstance(a, Ident) and isinstance(b, Ident):
        return a.name == b.name
    if isinstance(a, FieldAccess) and isinstance(b, FieldAccess):
        return a.field == b.field and _mismo_lugar(a.obj, b.obj)
    return False


class _Bajador:
    def __init__(self, program):
        self.structs = {it.name: it for it in program.items if isinstance(it, StructDecl)}
        self.usados = set()
        self._juntar_nombres(program)
        self.n = 0
        self.errores = []

    def _juntar_nombres(self, program):
        pila = [program]
        while pila:
            x = pila.pop()
            if isinstance(x, Node):
                for k in ("name", "pattern", "var"):
                    v = getattr(x, k, None)
                    if isinstance(v, str):
                        self.usados.add(v)
            if isinstance(x, (Node, list, tuple, dict)):
                pila.extend(h for h in hijos(x) if isinstance(h, (Node, list, tuple, dict)))
        # parámetros
        for it in program.items:
            for p in getattr(it, "params", None) or []:
                self.usados.add(p.name)

    def _nuevo(self):
        while True:
            self.n += 1
            nombre = f"si_{self.n}"
            if nombre not in self.usados:
                self.usados.add(nombre)
                return nombre

    def _defecto(self, t, src, prof=0):
        """Un valor cualquiera de tipo t, para declarar el temporal (se pisa en
        la rama que corre). None si t no tiene uno que se pueda escribir."""
        if prof > 8 or t is None:
            return None
        n = t.name
        if n in ("i32", "i64"):
            return _pos(NumLit(0), src)  # en un lugar i64, el checker lo amplía
        if n == "f64":
            return _pos(NumLit(0.0), src)
        if n == "bool":
            return _pos(BoolLit(False), src)
        if n == "str":
            return _pos(StrLit(""), src)
        if n == "Option":
            return _pos(NoneExpr(), src)
        if n == "Result" and t.args:
            d = self._defecto(t.args[0], src, prof + 1)
            return None if d is None else _pos(OkExpr(d), src)
        if n == "Vec":
            return _pos(Call(_pos(Ident("vec_new"), src), []), src)
        if n == "Map":
            return _pos(Call(_pos(Ident("map_new"), src), []), src)
        if n in self.structs and not t.args and not getattr(self.structs[n], "type_params", None):
            campos = {}
            for fname, ftype in self.structs[n].fields:
                d = self._defecto(ftype, src, prof + 1)
                if d is None:
                    return None
                campos[fname] = d
            return _pos(StructLit(n, campos), src)
        return None

    # ---------- sentencias ----------
    def correr(self, program):
        for it in program.items:
            body = getattr(it, "body", None)
            if isinstance(it, FnDecl) and isinstance(body, Block):
                self._bloque(body)

    def _bloque(self, block):
        if not tiene_if(block):
            return
        nuevas = []
        for st in block.stmts:
            nuevas.extend(self._sentencia(st))
        block.stmts = nuevas

    def _sentencia(self, st):
        if isinstance(st, LetStmt):
            if isinstance(st.expr, IfExpr):
                tmp = self._temporal(st.expr)
                if tmp is None:
                    return [st]
                decl, nombre = tmp
                cadena = self._cadena(st.expr, ("asignar", _pos(Ident(nombre), st)))
                st.expr = _pos(Ident(nombre), st.expr)
                return [decl] + cadena + [st]
            antes = []
            st.expr = self._sacar(st.expr, antes)
            return antes + [st]
        if isinstance(st, AssignStmt):
            if isinstance(st.expr, IfExpr):
                return self._cadena(st.expr, ("asignar", st.target))
            antes = []
            st.expr = self._sacar(st.expr, antes)
            return antes + [st]
        if isinstance(st, ReturnStmt):
            if isinstance(st.expr, IfExpr):
                return self._cadena(st.expr, ("return",))
            if st.expr is None:
                return [st]
            antes = []
            st.expr = self._sacar(st.expr, antes)
            return antes + [st]
        if isinstance(st, ExprStmt):
            antes = []
            st.expr = self._sacar(st.expr, antes)
            return antes + [st]
        if isinstance(st, IfStmt):
            # el checker ya rechazó un if que da valor en la condición
            self._bloque(st.then_block)
            if st.else_block is not None:
                self._bloque(st.else_block)
            return [st]
        if isinstance(st, (WhileStmt, WhileLetStmt, ForStmt)):
            self._bloque(st.body)
            return [st]
        return [st]

    def _temporal(self, e):
        """`let mut si_N: T = <defecto>` para el valor de `e`."""
        tipo = getattr(e, "tipo_if", None)
        d = self._defecto(tipo, e)
        if d is None:
            self.errores.append(ErrorIf(
                f"un if que da un {tipo!r} todavía no se puede usar como valor: escribe "
                f"un if normal que haga lo suyo en cada rama", e))
            return None
        nombre = self._nuevo()
        decl = _pos(LetStmt(nombre, d, True, copy.deepcopy(tipo)), e)
        decl.oculta = True
        return decl, nombre

    def _cadena(self, e, forma):
        """El IfStmt (y lo que va antes, si la condición tiene algo que sacar)
        que hace en cada rama lo que dice `forma`: ("asignar", lugar) o
        ("return",)."""
        antes = []
        cond = self._sacar(e.cond, antes)
        then_b = _pos(Block(self._rama(e.then_block, forma)), e.then_block)
        else_b = _pos(Block(self._rama(e.else_block, forma)), e.else_block)
        return antes + [_pos(IfStmt(cond, then_b, else_b), e)]

    def _rama(self, block, forma):
        cuerpo = _pos(Block(list(block.stmts[:-1])), block)
        self._bloque(cuerpo)
        ultima = block.stmts[-1]
        if es_panic(ultima):
            final = [ultima]
        elif isinstance(ultima.expr, IfExpr):
            final = self._cadena(ultima.expr, forma)
        else:
            antes = []
            valor = self._sacar(ultima.expr, antes)
            if forma[0] == "return":
                final = antes + [_pos(ReturnStmt(valor), ultima)]
            elif _mismo_lugar(forma[1], valor):
                final = antes  # `x = if c { x } else { 0 }`: esa rama no cambia nada
            else:
                final = antes + [_pos(AssignStmt(copy.deepcopy(forma[1]), valor), ultima)]
        return cuerpo.stmts + final

    # ---------- expresiones ----------
    def _sacar(self, e, antes):
        """Devuelve `e` sin IfExpr, agregando a `antes` lo que tiene que correr
        primero (en el orden en que corría adentro de la expresión)."""
        if isinstance(e, IfExpr):
            tmp = self._temporal(e)
            if tmp is None:
                return e
            decl, nombre = tmp
            antes.append(decl)
            antes.extend(self._cadena(e, ("asignar", _pos(Ident(nombre), e))))
            return _pos(Ident(nombre), e)
        if not tiene_if(e):
            return e
        if isinstance(e, BinOp) and e.op in ("and", "or") and tiene_if(e.right):
            si = _pos(ExprStmt(e.right), e.right)
            corto = _pos(ExprStmt(_pos(BoolLit(e.op == "or"), e)), e)
            if e.op == "and":
                nuevo = IfExpr(e.left, _pos(Block([si]), e.right), _pos(Block([corto]), e))
            else:
                nuevo = IfExpr(e.left, _pos(Block([corto]), e), _pos(Block([si]), e.right))
            _pos(nuevo, e)
            nuevo.tipo_if = T_BOOL
            return self._sacar(nuevo, antes)
        pendientes = []
        for get, put in self._lugares(e):
            v = get()
            if v is None:
                continue
            if tiene_if(v):
                for g2, p2 in pendientes:
                    w = g2()
                    if not _trivial(w):
                        nombre = self._nuevo()
                        tipo = getattr(w, "tipo_visto", None)
                        if tipo is not None and tipo == T_VOID:
                            tipo = None
                        decl = _pos(LetStmt(nombre, w, False,
                                            copy.deepcopy(tipo) if tipo is not None else None), w)
                        decl.oculta = True
                        antes.append(decl)
                        p2(_pos(Ident(nombre), w))
                pendientes = []
                put(self._sacar(v, antes))
            else:
                pendientes.append((get, put))
        return e

    @staticmethod
    def _lugares(e):
        """Los hijos expresión de `e`, en el orden en que se evalúan, como
        pares (leer, escribir)."""
        def attr(nombre):
            return (lambda: getattr(e, nombre), lambda v: setattr(e, nombre, v))

        def item(lista, i):
            return (lambda: lista[i], lambda v: lista.__setitem__(i, v))

        def campo(d, k):
            return (lambda: d[k], lambda v: d.__setitem__(k, v))

        if isinstance(e, Call):
            out = [] if isinstance(e.callee, Ident) else [attr("callee")]
            return out + [item(e.args, i) for i in range(len(e.args))]
        if isinstance(e, MethodCall):
            return [attr("obj")] + [item(e.args, i) for i in range(len(e.args))]
        if isinstance(e, StructLit):
            if isinstance(e.fields, dict):
                return [campo(e.fields, k) for k in list(e.fields)]
            return []
        if isinstance(e, (ArrayLit,)):
            return [item(e.elems, i) for i in range(len(e.elems))]
        if isinstance(e, PrintExpr):
            return [item(e.args, i) for i in range(len(e.args))]
        if isinstance(e, BinOp):
            return [attr("left"), attr("right")]
        if isinstance(e, IndexExpr):
            return [attr("obj"), attr("index")]
        out = []
        for k, v in list(vars(e).items()):
            if k in _POSICION:
                continue
            if isinstance(v, Node) and not isinstance(v, (Block, TypeAnn)):
                out.append(attr(k))
            elif isinstance(v, list):
                out.extend(item(v, i) for i in range(len(v)) if isinstance(v[i], Node))
        return out


def hay_if_expr(program):
    return tiene_if(program)


def bajar(program):
    """Baja todos los IfExpr del programa (en el lugar). Devuelve la lista de
    errores (un if cuyo tipo no tiene un valor por defecto que escribir)."""
    b = _Bajador(program)
    b.correr(program)
    return b.errores
