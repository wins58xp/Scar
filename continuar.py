"""`continue`: se baja a if antes del checker, así el checker, el intérprete y
el nativo nunca lo ven y sus reglas de propiedad (las de un if) valen tal cual.

Dentro del cuerpo de cada loop, para los `continue` de ESE loop (los de un
loop anidado son de él):

    if c { A  continue }  B          ->   if c { A } else { B }

Lo que sigue a un if cuya rama siempre termina en `continue` va a la otra
rama: es el mismo programa, sin variables nuevas. Si las dos ramas pueden o
no seguir (un `continue` dentro de otro if), hace falta recordar si se saltó:

    let mut seguir_N = false              (al principio de cada vuelta)
    if c { if d { A  seguir_N = true } else { B } }   if not seguir_N { C }

Lo que sigue a un `continue` en su mismo bloque nunca corre y se descarta. Un
`match` ya llegó bajado a if (enum_match, que reescribe el `continue` de un
brazo que corre dentro de un while let). Un `continue` fuera de un loop queda
como está y el checker da el error.
"""

from parser import (
    AssignStmt, Block, BoolLit, ContinueStmt, ForStmt, Ident, IfStmt, LetStmt, Node,
    UnaryOp, WhileLetStmt, WhileStmt,
)

_POSICION = ("line", "col", "archivo")
_LOOPS = (WhileStmt, WhileLetStmt, ForStmt)
NUNCA, A_VECES, SIEMPRE = 0, 1, 2


def _pos(node, src):
    for k in _POSICION:
        setattr(node, k, getattr(src, k, None))
    return node


def _nombres(program):
    """Todos los strings del programa, para que una bandera nunca choque."""
    usados = set()
    pila = [program]
    while pila:
        n = pila.pop()
        if isinstance(n, Node):
            for k, v in vars(n).items():
                if k in _POSICION:
                    continue
                if isinstance(v, str):
                    usados.add(v)
                else:
                    pila.append(v)
        elif isinstance(n, (list, tuple)):
            pila.extend(n)
        elif isinstance(n, dict):
            usados.update(k for k in n if isinstance(k, str))
            pila.extend(n.values())
    return usados


def _tiene_continue(stmts):
    """True si hay un `continue` de este loop: directo o dentro de un if."""
    for st in stmts:
        if isinstance(st, ContinueStmt):
            return True
        if isinstance(st, IfStmt):
            if _tiene_continue(st.then_block.stmts):
                return True
            if st.else_block is not None and _tiene_continue(st.else_block.stmts):
                return True
    return False


def _estado(stmts):
    """NUNCA, A_VECES o SIEMPRE: si esta lista salta a la vuelta siguiente."""
    for i, st in enumerate(stmts):
        if isinstance(st, ContinueStmt):
            return SIEMPRE
        if isinstance(st, IfStmt) and _tiene_continue([st]):
            resto = list(stmts[i + 1:])
            then_ = st.then_block.stmts
            else_ = st.else_block.stmts if st.else_block is not None else []
            e_then, e_else = _estado(then_), _estado(else_)
            if e_then == SIEMPRE and e_else == SIEMPRE:
                return SIEMPRE
            if e_then == SIEMPRE:
                return SIEMPRE if _estado(else_ + resto) == SIEMPRE else A_VECES
            if e_else == SIEMPRE:
                return SIEMPRE if _estado(then_ + resto) == SIEMPRE else A_VECES
            return A_VECES
    return NUNCA


def _necesita_bandera(stmts):
    """True si en algún punto lo que sigue a un if depende de si se saltó en
    alguna de sus dos ramas (ninguna salta siempre)."""
    for i, st in enumerate(stmts):
        if isinstance(st, ContinueStmt):
            return False
        if isinstance(st, IfStmt) and _tiene_continue([st]):
            resto = list(stmts[i + 1:])
            then_ = st.then_block.stmts
            else_ = st.else_block.stmts if st.else_block is not None else []
            e_then, e_else = _estado(then_), _estado(else_)
            if e_then == SIEMPRE and e_else == SIEMPRE:
                return False
            if e_then == SIEMPRE:
                return _necesita_bandera(then_) or _necesita_bandera(else_ + resto)
            if e_else == SIEMPRE:
                return _necesita_bandera(then_ + resto) or _necesita_bandera(else_)
            return True
    return False


class _Bajada:
    def __init__(self, program):
        self.usados = _nombres(program)
        self.n = 0

    def _bandera_nueva(self):
        while True:
            self.n += 1
            nombre = f"seguir_{self.n}"
            if nombre not in self.usados:
                self.usados.add(nombre)
                return nombre

    def bloques(self, nodo):
        """Recorre todo el programa y baja el cuerpo de cada loop."""
        pila = [nodo]
        while pila:
            n = pila.pop()
            if isinstance(n, _LOOPS):
                self.loop(n)
            if isinstance(n, Node):
                pila.extend(v for k, v in vars(n).items() if k not in _POSICION)
            elif isinstance(n, (list, tuple)):
                pila.extend(n)
            elif isinstance(n, dict):
                pila.extend(n.values())

    def loop(self, loop):
        cuerpo = loop.body.stmts
        if not _tiene_continue(cuerpo):
            return
        self.bandera = self._bandera_nueva() if _necesita_bandera(cuerpo) else None
        nuevos = self.lista(cuerpo)
        if self.bandera is not None:
            decl = _pos(LetStmt(self.bandera, _pos(BoolLit(False), loop), True), loop)
            decl.oculta = True
            nuevos = [decl] + nuevos
        loop.body.stmts = nuevos

    def lista(self, stmts):
        """Las mismas sentencias sin `continue` (cada una aparece una sola vez:
        lo que sigue a un if va a una sola rama, o detrás de la bandera)."""
        out = []
        for i, st in enumerate(stmts):
            if isinstance(st, ContinueStmt):
                if self.bandera is not None:
                    out.append(_pos(AssignStmt(_pos(Ident(self.bandera), st),
                                               _pos(BoolLit(True), st)), st))
                return out
            if not (isinstance(st, IfStmt) and _tiene_continue([st])):
                out.append(st)
                continue
            resto = list(stmts[i + 1:])
            then_orig = st.then_block.stmts
            else_orig = st.else_block.stmts if st.else_block is not None else []
            e_then, e_else = _estado(then_orig), _estado(else_orig)
            if e_then == SIEMPRE and e_else == SIEMPRE:
                out.append(self._if(st, self.lista(then_orig), self.lista(else_orig)))
            elif e_then == SIEMPRE:
                out.append(self._if(st, self.lista(then_orig), self.lista(else_orig + resto)))
            elif e_else == SIEMPRE:
                out.append(self._if(st, self.lista(then_orig + resto), self.lista(else_orig)))
            else:
                out.append(self._if(st, self.lista(then_orig), self.lista(else_orig)))
                if resto:
                    cond = _pos(UnaryOp("not", _pos(Ident(self.bandera), st)), st)
                    out.append(_pos(IfStmt(cond, _pos(Block(self.lista(resto)), st), None), st))
            return out
        return out

    @staticmethod
    def _if(st, then_stmts, else_stmts):
        st.then_block = _pos(Block(then_stmts), st.then_block)
        if else_stmts or st.else_block is not None:
            src = st.else_block if st.else_block is not None else st
            st.else_block = _pos(Block(else_stmts), src)
        return st


def bajar(program):
    """Baja todos los `continue` de los loops de `program` (lo modifica)."""
    _Bajada(program).bloques(program)
