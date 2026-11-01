"""Qué campos de sus parámetros puede reasignar cada fn.

El codegen lee antes un lugar (`d.b`, el campo de un campo de una variable) si
lo que se evalúa después llama a una fn que recibe esa variable: la fn puede
reasignar el campo, y el intérprete ya leyó el valor viejo (ver
Codegen._fijar_lugar). Pero decidía solo por la raíz: `agregar(s.ev,
analizar(s.red.actual))` copiaba `s.ev` porque `analizar` recibe algo de `s`,
`agregar` agregaba a la copia y la copia se soltaba al terminar la sentencia;
el evento se perdía (el sismógrafo nativo no anotaba ningún evento de la red).
Un struct se presta: lo que la fn le hace tiene que verse afuera.

Ahora se mira el camino entero. Un lugar L = raíz.f1...fn cambia de valor
(su objeto se reemplaza) solo si una llamada recibe un camino P que es un
prefijo propio de L (P = raíz.f1...fk, k < n) y esa fn puede reasignar, en su
parámetro, un prefijo de lo que falta (fk+1...fm, m <= n). Si la fn recibe L
mismo, o algo de adentro de L, o un campo hermano, no puede reemplazar a L
(reasignar el parámetro entero no cambia nada afuera); a lo sumo cambia lo de
adentro, que el intérprete también ve porque comparte el objeto.

`reasignaciones(items, conocidas)` devuelve, por fn, una lista con lo que
puede reasignar cada parámetro: un set de caminos (tuplas de nombres de
campo) o TODO (no se sabe: un valor fn, una task, un camino demasiado largo).
Es transitivo: si `f(p)` llama a `g(p.a)` y `g` reasigna `q.b`, `f` reasigna
`p.a.b`. Se calcula como punto fijo (las fns se pueden llamar en ciclo).
"""
from parser import (AssignStmt, BinOp, Call, FieldAccess, FnDecl, Ident, IndexExpr, LetStmt, MethodCall,
                    PrintExpr, SpawnExpr, StructLit, ArrayLit, hijos)

TODO = "*"
_LARGO_MAXIMO = 8


def camino(e):
    """(raíz, (f1, ..., fn)) si `e` es una variable o un campo de un campo de
    una variable; None si no."""
    campos = []
    while isinstance(e, FieldAccess):
        campos.append(e.field)
        e = e.obj
    if not isinstance(e, Ident):
        return None
    return e.name, tuple(reversed(campos))


def _recorrer(nodo):
    pila = [nodo]
    while pila:
        n = pila.pop()
        yield n
        pila.extend(x for x in hijos(n) if not isinstance(x, (str, int, float, bool)) and x is not None)


def _llamadas(nodo):
    """(nombre o None, args) de cada llamada (y spawn) dentro de `nodo`.
    None: no se sabe a qué fn llama (un spawn, un callee que no es un
    nombre)."""
    for n in _recorrer(nodo):
        if isinstance(n, SpawnExpr):
            c = n.call
            if isinstance(c, Call):
                yield None, c.args
        elif isinstance(n, Call):
            if isinstance(n.callee, Ident):
                yield n.callee.name, n.args
            else:
                yield None, n.args


def reasignaciones(items, conocidas):
    """`items`: los del programa ya juntado (con los módulos). `conocidas`:
    nombres de builtins y extern fns, que no reasignan campos de un struct
    de SCAR. Cualquier otro nombre que no sea una fn del programa (un valor
    fn guardado en una variable) puede hacer cualquier cosa."""
    fns = {d.name: d for d in items if isinstance(d, FnDecl)}
    efecto = {nombre: [set() for _ in d.params] for nombre, d in fns.items()}

    def agregar(destino, i, c):
        if destino[i] == TODO:
            return False
        if c == TODO or len(c) > _LARGO_MAXIMO:
            destino[i] = TODO
            return True
        if c in destino[i]:
            return False
        destino[i].add(c)
        return True

    def uno(d, destino):
        # alias: nombre local -> {(índice del parámetro, prefijo)}
        alias = {p.name: {(i, ())} for i, p in enumerate(d.params)}
        cambio = False
        for _ in range(4):          # los alias de alias, en el orden que sea
            nuevos = False
            for n in _recorrer(d.body):
                if isinstance(n, LetStmt) and n.expr is not None:
                    c = camino(n.expr)
                    if c is not None and c[0] in alias:
                        for i, pre in list(alias[c[0]]):
                            par = (i, pre + c[1])
                            if par not in alias.setdefault(n.name, set()):
                                alias[n.name].add(par)
                                nuevos = True
                elif isinstance(n, AssignStmt) and isinstance(n.target, Ident):
                    c = camino(n.expr)
                    if c is not None and c[0] in alias:
                        for i, pre in list(alias[c[0]]):
                            par = (i, pre + c[1])
                            if par not in alias.setdefault(n.target.name, set()):
                                alias[n.target.name].add(par)
                                nuevos = True
            if not nuevos:
                break
        for n in _recorrer(d.body):
            if isinstance(n, AssignStmt) and isinstance(n.target, FieldAccess):
                c = camino(n.target)
                if c is not None and c[0] in alias:
                    for i, pre in alias[c[0]]:
                        cambio |= agregar(destino, i, pre + c[1])
        for nombre, args in _llamadas(d.body):
            for k, a in enumerate(args):
                c = camino(a)
                if c is None or c[0] not in alias:
                    continue
                if nombre is None or (nombre not in fns and nombre not in conocidas):
                    for i, _pre in alias[c[0]]:
                        cambio |= agregar(destino, i, TODO)
                    continue
                if nombre not in fns or k >= len(efecto[nombre]):
                    continue
                suyo = efecto[nombre][k]
                for i, pre in alias[c[0]]:
                    if suyo == TODO:
                        cambio |= agregar(destino, i, TODO)
                    else:
                        for g in list(suyo):
                            cambio |= agregar(destino, i, pre + c[1] + g)
        return cambio

    hubo = True
    while hubo:
        hubo = False
        for nombre, d in fns.items():
            hubo |= uno(d, efecto[nombre])
    return efecto


def puede_reemplazar(efecto, conocidas, expr, lugar, misma_raiz):
    """Si evaluar `expr` puede reemplazar el objeto del lugar `lugar` (o uno
    que lo contiene), el nombre de la fn que lo puede hacer ("una fn
    guardada en una variable o una task" si no se sabe cuál); si no, None.
    Ver el docstring del módulo. `misma_raiz(n)` dice si la variable `n` es
    la raíz del lugar o un alias suyo."""
    c_lugar = camino(lugar)
    if c_lugar is None:
        return False
    campos = c_lugar[1]
    for nombre, args in _llamadas(expr):
        for k, a in enumerate(args):
            c = camino(a)
            if c is None or not misma_raiz(c[0]):
                continue
            p = c[1] if c[0] == c_lugar[0] else ()
            if len(p) >= len(campos) or campos[:len(p)] != p:
                continue        # L mismo, algo de adentro de L o un hermano
            resto = campos[len(p):]
            if nombre is None or (nombre not in efecto and nombre not in conocidas):
                return nombre or "una fn guardada en una variable o una task"
            if nombre not in efecto or k >= len(efecto[nombre]):
                continue
            suyo = efecto[nombre][k]
            if suyo == TODO or any(g and resto[:len(g)] == g for g in suyo):
                return nombre
    return None


def en_orden(n):
    """Las partes de `n` que el intérprete evalúa una después de la otra, de
    izquierda a derecha (los argumentos de una llamada, el receptor de un
    método y sus argumentos, los campos de un struct literal en el orden
    del fuente, los dos lados de una operación, un índice). [] si `n` no es
    de esos."""
    if isinstance(n, Call):
        return list(n.args) if isinstance(n.callee, Ident) else [n.callee] + list(n.args)
    if isinstance(n, MethodCall):
        return [n.obj] + list(n.args)
    if isinstance(n, StructLit):
        return list(n.fields.values()) if isinstance(n.fields, dict) else [v for _k, v in n.fields]
    if isinstance(n, ArrayLit):
        return list(n.elems)
    if isinstance(n, BinOp):
        return [n.left, n.right]
    if isinstance(n, IndexExpr):
        return [n.obj, n.index]
    if isinstance(n, PrintExpr):
        return list(n.args)
    return []


def ligada_se_mueve(nombre, stmts, param_contenedor):
    """True si en `stmts` la ligada `nombre` (un Vec/Map que un while
    let presta de una variable) va a algún lugar que se queda con ella: un
    return, un let o una asignación, un campo de un struct literal, un
    Some/Ok/Err, un arreglo, un argumento de un método (push, set...), un
    spawn, o un argumento de una fn que recibe un Vec/Map (una fn se queda con
    lo que recibe). `param_contenedor(fn, k)` dice si el parámetro k de la fn
    de usuario `fn` es de esos (None si `fn` no es de usuario). Leerla
    (métodos sobre ella, campos, print, len) no la mueve."""
    from parser import (ReturnStmt, LetStmt, SomeExpr, OkExpr, ErrExpr, ArrayLit, StructLit,
                        AssignStmt, MethodCall, SpawnExpr, Call, Ident, Node, hijos)

    def mueve(padre, nodo):
        if isinstance(padre, (ReturnStmt, LetStmt, SomeExpr, OkExpr, ErrExpr, ArrayLit, StructLit, SpawnExpr)):
            return True
        if isinstance(padre, AssignStmt):
            return padre.expr is nodo
        if isinstance(padre, MethodCall):
            return padre.obj is not nodo
        if isinstance(padre, Call) and isinstance(padre.callee, Ident):
            for k, a in enumerate(padre.args):
                if a is nodo:
                    r = param_contenedor(padre.callee.name, k)
                    if r is None or r:
                        return True
        return False

    def recorrer(nodo, padre):
        if isinstance(nodo, Ident):
            return nodo.name == nombre and mueve(padre, nodo)
        for h in hijos(nodo):
            if isinstance(h, (Node, list, tuple, dict)) and recorrer(h, nodo if isinstance(nodo, Node) else padre):
                return True
        return False

    return any(recorrer(st, None) for st in stmts)
