"""`enum` y `match`, bajados a lo que el resto del compilador ya sabe.

    enum Forma {
        Circulo(f64)
        Rect(f64, f64)
        Nada
    }

se convierte, antes del checker, en

    struct Forma { tag: i32  Circulo_0: f64  Rect_0: f64  Rect_1: f64 }
    fn Circulo(dato1: f64) -> Forma { return Forma { tag: 0, Circulo_0: dato1, Rect_0: 0.0, ... } }
    fn Rect(dato1: f64, dato2: f64) -> Forma { ... }
    fn Nada() -> Forma { ... }

(`Nada` suelto pasa a `Nada()`), y `match f { Circulo(r) => A  Rect(w, h) => B  _ => C }` en

    if f.tag == 0 { let r = f.Circulo_0  A } else if f.tag == 1 { let w = f.Rect_0  let h = f.Rect_1  B } else { C }

con el valor de `f` en una variable propia cuando no es un lugar (una llamada,
por ejemplo), para evaluarlo una sola vez. Un `match` que da un valor va en
tres lugares: `return match` (un `return` por brazo), `x = match` (una
asignación por brazo) y `let x: T = match` (una variable temporal de tipo T,
una asignación por brazo y `let x = temporal`).

Por qué así y no un tipo nuevo en cada capa: el checker, el intérprete, el
análisis de propiedad y el codegen ya saben de structs, de str dentro de
structs, de mover y prestar, de Vec y canales de structs; todo eso está
verificado (paridad, ASan, TSan, fuzzer). Un enum es un struct con tag para
todos ellos, y la semántica de un match es la de la cadena de if/else que
sale de acá, en los dos backends por igual. Un dato del brazo es una variable
propia: un str se copia (la misma regla que `let s = x.campo`).

Lo propio del enum se resuelve acá o en el checker, con errores que hablan
de enums y no del struct de abajo:
  - acá: variantes desconocidas o repetidas, cantidad de datos de cada
    patrón, `_` que no va último, exhaustividad (falta una variante y no hay
    `_`), nombres que chocan, tipos de dato no soportados, un match que da
    valor en un lugar donde todavía no se puede;
  - en el checker (los nodos internos van marcados): que el valor del match
    sea del enum de sus brazos, que nadie lea ni escriba los campos internos,
    construya el enum con `{ }` ni lo compare con `==`.
El print muestra la variante (`Rect(3.0, 4.0)`, `Nada`): StructDecl lleva
`enum_variantes` y los dos backends lo miran.

Si acá aparece un error, check() devuelve solo estos errores y no corre el
resto del checker (como un error de sintaxis): seguir con un programa a medio
bajar daría errores de más, que confunden.
"""

import copy

from parser import (
    AssignStmt, BinOp, Block, BoolLit, BreakStmt, ContinueStmt, Call, EnumDecl, ExprStmt, OkExpr, MethodCall,
    FieldAccess, FnDecl, ForStmt, Ident, IfStmt, LetStmt, MatchExpr, Node, NoneExpr,
    NumLit, Param, ReturnStmt, StrLit, StructDecl, StructLit, WhileLetStmt, WhileStmt,
    MatchArm, Patron, PrintExpr,
    ExternFnDecl, ExternTypeDecl, block_always_returns,
)
from types_ import TypeAnn

TAG = "tag"
# los patrones de un match sobre Option o Result
_PATRONES_OPCION = {"Some": "Option", "None": "Option", "Ok": "Result", "Err": "Result"}
DATOS_OK = ("i32", "i64", "f64", "bool", "str")
_ATRIBUTOS_POSICION = ("line", "col", "archivo")


class ErrorEnum(Exception):
    """Un error de enum/match. check() lo entrega como un error de tipo."""
    def __init__(self, msg, line=None, col=None, archivo=None):
        self.msg = msg
        self.line = line
        self.col = col
        self.archivo = archivo
        loc = f" (línea {line})" if line else ""
        super().__init__(f"{msg}{loc}")


def _datos(n):
    return "un dato" if n == 1 else f"{n} datos"


def _tipos(tipos):
    return ", ".join(repr(t) for t in tipos)


def campo_dato(variante, j):
    return f"{variante}_{j}"


def _pos(node, src):
    node.line = getattr(src, "line", None)
    node.col = getattr(src, "col", None)
    node.archivo = getattr(src, "archivo", None)
    return node


def es_lugar(e):
    """`x`, `x.a`, `x.a.b`: se puede leer varias veces sin efectos."""
    if isinstance(e, Ident):
        return True
    return isinstance(e, FieldAccess) and es_lugar(e.obj)


def _raiz(e):
    while isinstance(e, FieldAccess):
        e = e.obj
    return e.name


def _mismo_lugar(a, b):
    if isinstance(a, Ident) and isinstance(b, Ident):
        return a.name == b.name
    if isinstance(a, FieldAccess) and isinstance(b, FieldAccess):
        return a.field == b.field and _mismo_lugar(a.obj, b.obj)
    return False


def _es_panic(e):
    return isinstance(e, Call) and isinstance(e.callee, Ident) and e.callee.name == "panic"


def tiene_enums(program):
    """True si el programa usa enum o match (si no, bajar_enums no toca nada)."""
    pila = [program]
    while pila:
        n = pila.pop()
        if isinstance(n, (EnumDecl, MatchExpr)):
            return True
        if isinstance(n, Node):
            for k, v in vars(n).items():
                if k not in _ATRIBUTOS_POSICION:
                    pila.append(v)
        elif isinstance(n, (list, tuple)):
            pila.extend(n)
        elif isinstance(n, dict):
            pila.extend(n.values())
    return False


class _Bajada:
    def __init__(self, program, nombres_builtin):
        self.program = program
        self.builtins = nombres_builtin
        self.errores = []
        self.enums = {}          # nombre -> [(variante, [TypeAnn])]
        self.variantes = {}      # variante -> (enum, índice, [TypeAnn])
        self.structs = {}        # nombre -> StructDecl del usuario
        self.usados = set()
        self.n_temp = 0

    # ---------- errores y nombres ----------
    def _err(self, msg, node):
        self.errores.append(ErrorEnum(msg, getattr(node, "line", None), getattr(node, "col", None),
                                      getattr(node, "archivo", None)))

    def _juntar_nombres(self):
        """Todos los nombres del programa, para que un temporal nunca choque."""
        pila = [self.program]
        while pila:
            n = pila.pop()
            if isinstance(n, Node):
                for k, v in vars(n).items():
                    if k in _ATRIBUTOS_POSICION:
                        continue
                    if isinstance(v, str):
                        self.usados.add(v)
                    else:
                        pila.append(v)
            elif isinstance(n, (list, tuple)):
                pila.extend(n)
            elif isinstance(n, dict):
                self.usados.update(k for k in n if isinstance(k, str))
                pila.extend(n.values())
            elif isinstance(n, str):
                self.usados.add(n)

    def _temporal(self):
        while True:
            self.n_temp += 1
            nombre = f"match_{self.n_temp}"
            if nombre not in self.usados:
                self.usados.add(nombre)
                return nombre

    # ---------- declaraciones ----------
    def correr(self):
        self._juntar_nombres()
        globales = {}
        for it in self.program.items:
            nombre = getattr(it, "name", None)
            if nombre is not None and not isinstance(it, EnumDecl):
                globales[nombre] = it
            if isinstance(it, StructDecl):
                self.structs[it.name] = it
        tipos_reservados = {"i32", "i64", "f64", "bool", "str", "void", "Vec", "Map", "Option",
                            "Result", "Chan", "File", "Socket", "Listener", "Pipe"}
        for it in self.program.items:
            if not isinstance(it, EnumDecl):
                continue
            if it.name in globales or it.name in self.enums or it.name in tipos_reservados:
                self._err(f"el nombre '{it.name}' ya está en uso: el enum necesita otro", it)
                continue
            if not it.variants:
                self._err(f"el enum '{it.name}' no tiene variantes", it)
                continue
            variantes = []
            for idx, v in enumerate(it.variants):
                if not v.name.split(".")[-1][0].isupper():  # gui.Rojo (módulos)
                    self._err(f"la variante '{v.name}' tiene que empezar con mayúscula "
                              f"(como un tipo: así no se confunde con una variable)", v)
                if v.name in self.variantes:
                    otro = self.variantes[v.name][0]
                    if otro == it.name:
                        self._err(f"la variante '{v.name}' está dos veces en el enum '{it.name}'", v)
                    else:
                        self._err(f"la variante '{v.name}' ya es del enum '{otro}': las "
                                  f"variantes se escriben sin el nombre del enum, así que "
                                  f"no se pueden repetir entre enums", v)
                    continue
                if v.name in globales or v.name in self.builtins or v.name in self.enums:
                    self._err(f"la variante '{v.name}' choca con otro nombre del programa "
                              f"(una fn, un struct o un builtin): elige otro", v)
                    continue
                for t in v.types:
                    if t.name not in DATOS_OK or t.args:
                        self._err(f"la variante '{v.name}' lleva un dato de tipo '{t!r}': "
                                  f"por ahora los datos de una variante son i32, i64, "
                                  f"f64, bool o str", v)
                self.variantes[v.name] = (it.name, idx, list(v.types))
                variantes.append((v.name, list(v.types)))
            self.enums[it.name] = variantes

        # Los enums van primero: sus datos son escalares o str (no dependen de
        # ningún struct), y así un struct declarado más arriba puede tener un
        # campo enum (el codegen pide que un struct esté declarado antes de
        # usarse como campo).
        de_enums, resto = [], []
        for it in self.program.items:
            if isinstance(it, EnumDecl):
                if it.name in self.enums:
                    de_enums.extend(self._struct_y_constructores(it))
            else:
                resto.append(it)
        self.program.items = de_enums + resto

        for it in self.program.items:
            if isinstance(it, FnDecl):
                for p in it.params:
                    self._nombre_local(p.name, p)
                if getattr(it, "es_variante", False):
                    continue
                self._bloque(it.body)
        return self.errores

    def _defecto(self, t, src, prof=0):
        """Un valor cualquiera de tipo t (para llenar los datos de las otras
        variantes y la variable temporal de `let x: T = match`). None si t no
        tiene uno que se pueda escribir."""
        if prof > 8:
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
        if n in self.enums and not t.args:
            v, tipos = self.enums[n][0]
            args = [self._defecto(x, src, prof + 1) for x in tipos]
            return _pos(Call(_pos(Ident(v), src), args), src)
        if n == "Option":
            return _pos(NoneExpr(), src)
        if n == "Result":
            if not t.args:
                return None
            d = self._defecto(t.args[0], src, prof + 1)
            return None if d is None else _pos(OkExpr(d), src)
        if n == "Vec" or n == "Map":
            return _pos(Call(_pos(Ident("vec_new" if n == "Vec" else "map_new"), src), []), src)
        if n in self.structs and not t.args and not self.structs[n].type_params:
            campos = {}
            for fname, ftype in self.structs[n].fields:
                d = self._defecto(ftype, src, prof + 1)
                if d is None:
                    return None
                campos[fname] = d
            return _pos(StructLit(n, campos), src)
        return None

    def _struct_y_constructores(self, e):
        campos = [(TAG, TypeAnn("i32"))]
        for v in e.variants:
            for j, t in enumerate(v.types):
                campos.append((campo_dato(v.name, j), t))
        decl = _pos(StructDecl(e.name, campos), e)
        decl.enum_variantes = [(v.name, len(v.types)) for v in e.variants]
        out = [decl]
        for idx, v in enumerate(e.variants):
            lit = {}
            for fname, ftype in campos:
                lit[fname] = self._defecto(ftype, v)
            lit[TAG] = _pos(NumLit(idx), v)
            params = []
            for j, t in enumerate(v.types):
                pname = f"dato{j + 1}"
                params.append(_pos(Param(pname, t), v))
                lit[campo_dato(v.name, j)] = _pos(Ident(pname), v)
            sl = _pos(StructLit(e.name, lit), v)
            sl.interno_enum = True
            body = _pos(Block([_pos(ReturnStmt(sl), v)]), v)
            fn = _pos(FnDecl(v.name, params, body, False, TypeAnn(e.name)), v)
            fn.es_variante = e.name
            out.append(fn)
        return out

    def _nombre_local(self, nombre, node):
        if nombre in self.variantes:
            self._err(f"'{nombre}' es una variante del enum '{self.variantes[nombre][0]}': "
                      f"una variable no puede llamarse así", node)

    # ---------- sentencias ----------
    def _bloque(self, block):
        nuevas = []
        for st in block.stmts:
            nuevas.extend(self._sentencia(st))
        block.stmts = nuevas

    def _sentencia(self, st):
        if isinstance(st, LetStmt):
            self._nombre_local(st.name, st)
            if isinstance(st.expr, MatchExpr):
                return self._match_let(st)
            st.expr = self._expr(st.expr)
            return [st]
        if isinstance(st, AssignStmt):
            st.target = self._expr(st.target)
            if isinstance(st.expr, MatchExpr):
                return self._match(st.expr, ("asignar", st.target, st))
            st.expr = self._expr(st.expr)
            return [st]
        if isinstance(st, ReturnStmt):
            if isinstance(st.expr, MatchExpr):
                return self._match(st.expr, ("return",))
            if st.expr is not None:
                st.expr = self._expr(st.expr)
            return [st]
        if isinstance(st, ExprStmt):
            if isinstance(st.expr, MatchExpr) and st.expr.es_sentencia:
                return self._match(st.expr, ("sentencia",))
            st.expr = self._expr(st.expr)
            return [st]
        if isinstance(st, IfStmt):
            st.cond = self._expr(st.cond)
            self._bloque(st.then_block)
            if st.else_block is not None:
                self._bloque(st.else_block)
            return [st]
        if isinstance(st, WhileStmt):
            st.cond = self._expr(st.cond)
            self._bloque(st.body)
            return [st]
        if isinstance(st, WhileLetStmt):
            self._nombre_local(st.pattern, st)
            st.expr = self._expr(st.expr)
            self._bloque(st.body)
            return [st]
        if isinstance(st, ForStmt):
            self._nombre_local(st.var, st)
            st.start = self._expr(st.start)
            st.end = self._expr(st.end)
            self._bloque(st.body)
            return [st]
        if isinstance(st, BreakStmt):
            return [st]
        return [st]

    # ---------- expresiones ----------
    def _expr(self, e):
        if isinstance(e, MatchExpr):
            self._err("un match que da un valor va, por ahora, en `let x: T = match ...`, "
                      "en `x = match ...` o en `return match ...`; como sentencia, al "
                      "principio de una línea", e)
            return e
        if isinstance(e, Ident):
            if e.name in self.variantes:
                enum, _, tipos = self.variantes[e.name]
                if tipos:
                    self._err(f"la variante '{e.name}' lleva {_datos(len(tipos))} "
                              f"({_tipos(tipos)}): se escribe {e.name}(...)", e)
                    return e
                return _pos(Call(_pos(Ident(e.name), e), []), e)
            return e
        if isinstance(e, Call) and isinstance(e.callee, Ident):
            v = self.variantes.get(e.callee.name)
            if v is not None and not v[2]:
                self._err(f"la variante '{e.callee.name}' no lleva datos: se escribe sin "
                          f"paréntesis ({e.callee.name})", e)
            e.args = [self._expr(a) for a in e.args]
            return e
        if isinstance(e, StructLit):
            for k in list(e.fields):
                e.fields[k] = self._expr(e.fields[k])
            return e
        if isinstance(e, Node):
            for k, v in list(vars(e).items()):
                if k in _ATRIBUTOS_POSICION:
                    continue
                if isinstance(v, Node):
                    setattr(e, k, self._expr(v))
                elif isinstance(v, list):
                    setattr(e, k, [self._expr(x) if isinstance(x, Node) else x for x in v])
            return e
        return e

    # ---------- match ----------
    def _brazos(self, m):
        """Valida los brazos. Devuelve (enum, [(brazo, índice o None si es '_')])
        o None si hubo un error."""
        enum = None
        vistos = {}
        salida = []
        ok = True
        for i, arm in enumerate(m.arms):
            p = arm.pattern
            if p.name == "_":
                if p.binds is not None:
                    self._err("'_' no lleva datos: es el brazo para todas las variantes "
                              "que no se nombraron", p)
                    ok = False
                if i != len(m.arms) - 1:
                    self._err("el brazo '_' tiene que ser el último: los que siguen no se "
                              "alcanzarían nunca", p)
                    ok = False
                salida.append((arm, None))
                continue
            if p.name in ("Some", "None", "Ok", "Err"):
                self._err(f"el match mezcla '{p.name}' (de un Option o un Result) con "
                          f"variantes de un enum", p)
                return None
            if p.name not in self.variantes:
                self._err(f"'{p.name}' no es una variante de ningún enum", p)
                ok = False
                continue
            e, idx, tipos = self.variantes[p.name]
            if enum is None:
                enum = e
            elif e != enum:
                self._err(f"el match mezcla variantes de '{enum}' y de '{e}' "
                          f"('{p.name}' es de '{e}')", p)
                ok = False
                continue
            if p.name in vistos:
                self._err(f"la variante '{p.name}' ya tiene un brazo en este match "
                          f"(el segundo no se alcanzaría nunca)", p)
                ok = False
                continue
            vistos[p.name] = idx
            if tipos and p.binds is None:
                self._err(f"la variante '{p.name}' lleva {_datos(len(tipos))}: el patrón "
                          f"es {p.name}({', '.join(['x'] * len(tipos))}), con '_' para "
                          f"los que no se usan", p)
                ok = False
            elif not tipos and p.binds is not None:
                self._err(f"la variante '{p.name}' no lleva datos: el patrón es "
                          f"{p.name}, sin paréntesis", p)
                ok = False
            elif tipos and len(p.binds) != len(tipos):
                self._err(f"la variante '{p.name}' lleva {_datos(len(tipos))} y el patrón "
                          f"nombra {len(p.binds)}", p)
                ok = False
            if p.binds:
                nombres = set()
                for b in p.binds:
                    if b.name == "_":
                        continue
                    if b.name in nombres:
                        self._err(f"el nombre '{b.name}' está dos veces en el patrón", b)
                        ok = False
                    nombres.add(b.name)
                    if b.name in self.variantes:
                        self._err(f"'{b.name}' es una variante: el dato necesita otro "
                                  f"nombre", b)
                        ok = False
            salida.append((arm, idx))
        if enum is None and ok:
            self._err("un match necesita al menos un brazo con una variante", m)
            return None
        if not ok:
            return None
        hay_comodin = salida[-1][1] is None
        if hay_comodin and len(vistos) == len(self.enums[enum]):
            self._err(f"todas las variantes de '{enum}' ya tienen un brazo: el '_' no se "
                      f"alcanzaría nunca", salida[-1][0].pattern)
            return None
        if not hay_comodin:
            faltan = [v for v, _ in self.enums[enum] if v not in vistos]
            if faltan:
                self._err(f"el match no cubre todas las variantes de '{enum}': "
                          f"falta{'n' if len(faltan) > 1 else ''} {', '.join(faltan)} "
                          f"(agrega un brazo para cada una, o '_')", m)
                return None
        return enum, salida

    def _match_let(self, st):
        m = st.expr
        if st.declared_type is None:
            self._err(f"`let {st.name} = match ...` necesita el tipo escrito: "
                      f"let {st.name}: T = match ...", st)
            return [st]
        tmp = self._temporal()
        defecto = self._defecto(st.declared_type, st)
        if defecto is None:
            self._err(f"un match que da un '{st.declared_type!r}' todavía no se puede "
                      f"guardar con let: usa `return match ...` o asígnalo a una variable "
                      f"que ya existe", st)
            return [st]
        decl_tmp = _pos(LetStmt(tmp, defecto, True, copy.deepcopy(st.declared_type)), st)
        decl_tmp.oculta = True
        cadena = self._match(m, ("asignar", _pos(Ident(tmp), st)))
        st.expr = _pos(Ident(tmp), st)
        return [decl_tmp] + cadena + [st]

    def _match(self, m, forma):
        if any(a.pattern.name in _PATRONES_OPCION for a in m.arms):
            return self._match_opcion(m, forma)
        r = self._brazos(m)
        if r is None:
            return []
        enum, brazos = r
        antes = []
        scrut = self._expr(m.scrutinee)
        if es_lugar(scrut):
            lugar = scrut
        else:
            tmp = self._temporal()
            let_tmp = _pos(LetStmt(tmp, scrut), m.scrutinee)
            let_tmp.oculta = True
            antes.append(let_tmp)
            lugar = _pos(Ident(tmp), m.scrutinee)

        ramas = []
        n = len(brazos)
        for k, (arm, idx) in enumerate(brazos):
            cuerpo = self._ligaduras(arm, idx, lugar) + self._cuerpo(arm, forma)
            if idx is None or k == n - 1:
                cond = None
            else:
                cond = self._cond_tag(lugar, enum, idx, arm.pattern)
            ramas.append((cond, _pos(Block(cuerpo), arm), arm, idx))

        # el último brazo va sin condición (el match es exhaustivo); con un
        # solo brazo, la condición queda y el else es un panic que no corre.
        if n == 1:
            cond, blk, arm, idx = ramas[0]
            cond = self._cond_tag(lugar, enum, idx, arm.pattern)
            panic = _pos(ExprStmt(_pos(Call(_pos(Ident("panic"), m),
                                            [_pos(StrLit("match: variante imposible"), m)]), m)), m)
            return antes + [_pos(IfStmt(cond, blk, _pos(Block([panic]), m)), m)]
        cadena = ramas[-1][1]
        for cond, blk, arm, idx in reversed(ramas[:-1]):
            cadena = _pos(Block([_pos(IfStmt(cond, blk, cadena), arm)]), arm)
        return antes + cadena.stmts

    # ---------- match sobre Option y Result ----------
    def _brazos_opcion(self, m):
        """Valida un match sobre Option (Some/None) o Result (Ok/Err).
        Devuelve (tipo, {variante: brazo}, brazo '_' o None) o None si hubo
        un error. tipo es "Option" o "Result"."""
        tipo = None
        por_variante = {}
        comodin = None
        ok = True
        for i, arm in enumerate(m.arms):
            p = arm.pattern
            if p.name == "_":
                if p.binds is not None:
                    self._err("'_' no lleva datos: es el brazo para lo que no se nombró", p)
                    ok = False
                if i != len(m.arms) - 1:
                    self._err("el brazo '_' tiene que ser el último: los que siguen no se "
                              "alcanzarían nunca", p)
                    ok = False
                comodin = arm
                continue
            if p.name not in _PATRONES_OPCION:
                self._err(f"el match mezcla '{p.name}' con Some/None/Ok/Err: un match es "
                          f"sobre un enum o sobre un Option o un Result", p)
                ok = False
                continue
            t = _PATRONES_OPCION[p.name]
            if tipo is None:
                tipo = t
            elif t != tipo:
                self._err(f"el match mezcla patrones de un Option (Some/None) y de un "
                          f"Result (Ok/Err)", p)
                ok = False
                continue
            if p.name in por_variante:
                self._err(f"'{p.name}' ya tiene un brazo en este match (el segundo no se "
                          f"alcanzaría nunca)", p)
                ok = False
                continue
            if p.name == "None":
                if p.binds is not None:
                    self._err("None no lleva datos: el patrón es None, sin paréntesis", p)
                    ok = False
            elif p.binds is None or len(p.binds) != 1:
                self._err(f"el patrón es {p.name}(x), con un nombre para el dato ('_' si "
                          f"no se usa)", p)
                ok = False
            elif p.binds[0].name in self.variantes:
                self._err(f"'{p.binds[0].name}' es una variante: el dato necesita otro "
                          f"nombre", p.binds[0])
                ok = False
            por_variante[p.name] = arm
        if not ok:
            return None
        if tipo is None:
            self._err("un match necesita al menos un brazo con Some, None, Ok o Err", m)
            return None
        variantes = ("Some", "None") if tipo == "Option" else ("Ok", "Err")
        if comodin is not None and len(por_variante) == 2:
            self._err(f"{variantes[0]} y {variantes[1]} ya tienen un brazo: el '_' no se "
                      f"alcanzaría nunca", comodin.pattern)
            return None
        if comodin is None and len(por_variante) < 2:
            falta = [v for v in variantes if v not in por_variante][0]
            self._err(f"el match no cubre {falta} (agrega un brazo para {falta}, o '_')", m)
            return None
        return tipo, por_variante, comodin

    def _match_opcion(self, m, forma):
        """`match o { Some(x) => A  None => B }` (y Ok(x)/Err(e)) se baja a

            if o.is_some() { while let Some(x) = o { A  break } } else { B }

        `while let` liga el dato con sus reglas de dueño (prestado si `o` es
        una variable, propio si es un valor nuevo), y el break del final lo
        hace correr una sola vez (el checker lo sabe: un cuerpo que no llega a
        su final no tiene vuelta siguiente). Para Ok(x), el mismo while let con
        el patrón Ok (marca `patron`, solo la pone esta bajada); Err(e) liga
        `let e = r.err()`. El valor, si no es una variable, va antes a una
        variable propia (se evalúa una sola vez).

        Un `break` del brazo apunta al loop de AFUERA del match: dentro del
        while let saldría solo de él. Se reemplaza por `salir = true; break`,
        y después del match va `if salir { break }`. Un `continue`, igual:
        `seguir = true; break` y después `if seguir { continue }`."""
        r = self._brazos_opcion(m)
        if r is None:
            return []
        tipo, por_variante, comodin = r
        antes = []
        scrut = self._expr(m.scrutinee)
        if es_lugar(scrut):
            # una variable o un campo: el while let lo presta, como si el
            # usuario lo hubiera escrito (un let lo movería)
            lugar = scrut
        else:
            tmp = self._temporal()
            let_tmp = _pos(LetStmt(tmp, scrut), m.scrutinee)
            let_tmp.oculta = True
            antes.append(let_tmp)
            lugar = _pos(Ident(tmp), m.scrutinee)
        si, no = ("Some", "None") if tipo == "Option" else ("Ok", "Err")
        salir = []      # [nombre de la bandera] si algún brazo tiene un break de afuera
        a_seguir = []   # lo mismo para un continue de afuera

        def rama(variante):
            arm = por_variante.get(variante, comodin)
            cuerpo = self._cuerpo(arm, forma)
            p = arm.pattern
            dato = p.binds[0].name if p.name == variante and p.binds else "_"
            if variante == si and dato != "_":
                self._reescribir_breaks(cuerpo, salir, arm, a_seguir)
                fin = _pos(BreakStmt(), arm)
                fin.sintetico = True
                wl = _pos(WhileLetStmt(dato, copy.deepcopy(lugar), _pos(Block(cuerpo + [fin]), arm)), arm)
                wl.patron = si
                if forma[0] == "return" or block_always_returns(Block(cuerpo)):
                    # el while let corre siempre (el if ya vio que hay dato),
                    # pero el checker no lo sabe: sin esto, `return match`
                    # daría "puede llegar al final sin return". Lo mismo
                    # vale para un match sentencia cuyo brazo siempre retorna
                    # (`Ok(n) => { return n }`), si no la fn tampoco lo haría
                    imposible = _pos(ExprStmt(_pos(Call(_pos(Ident("panic"), arm),
                                                        [_pos(StrLit("match: rama imposible"), arm)]), arm)), arm)
                    return [wl, imposible]
                return [wl]
            if variante == no and dato != "_":
                err = _pos(MethodCall(copy.deepcopy(lugar), "err", []), p)
                err.match_sobre = tipo
                err.match_error_ya_dado = True   # lo da la condición del if
                let_e = _pos(LetStmt(dato, err), p)
                let_e.dato_de_match = True
                return [let_e] + cuerpo
            return cuerpo

        cond = _pos(MethodCall(copy.deepcopy(lugar), "is_some" if tipo == "Option" else "is_ok", []), m)
        cond.match_sobre = tipo     # para el error del checker si no es de ese tipo
        rama_si = rama(si)
        rama_no = rama(no)
        for bandera in salir + a_seguir:
            decl = _pos(LetStmt(bandera, _pos(BoolLit(False), m), True), m)
            decl.oculta = True
            antes.append(decl)
        salida = antes + [_pos(IfStmt(cond, _pos(Block(rama_si), m), _pos(Block(rama_no), m)), m)]
        if salir:
            # sin marca: si este match está en el brazo de otro, este break
            # también es "de afuera" para ese y se reescribe ahí
            seguir = _pos(BreakStmt(), m)
            salida.append(_pos(IfStmt(_pos(Ident(salir[0]), m), _pos(Block([seguir]), m), None), m))
        if a_seguir:
            # igual que el break: sin marca, para el match de afuera si lo hay
            otra = _pos(ContinueStmt(), m)
            salida.append(_pos(IfStmt(_pos(Ident(a_seguir[0]), m), _pos(Block([otra]), m), None), m))
        return salida

    def _reescribir_breaks(self, stmts, salir, src, seguir=None):
        """Reemplaza, en `stmts` y en sus if (no en loops de adentro, cuyo
        break y continue son de ellos), cada `break` del usuario por
        `salir = true; break` y cada `continue` por `seguir = true; break`.
        Crea cada bandera la primera vez. Devuelve True si reemplazó alguno."""
        hubo = False
        i = 0
        while i < len(stmts):
            st = stmts[i]
            es_break = isinstance(st, BreakStmt) and not getattr(st, "sintetico", False)
            es_continue = isinstance(st, ContinueStmt) and seguir is not None
            if es_break or es_continue:
                bandera = salir if es_break else seguir
                if not bandera:
                    bandera.append(self._temporal())
                asig = _pos(AssignStmt(_pos(Ident(bandera[0]), st), _pos(BoolLit(True), st)), st)
                salto = st if es_break else _pos(BreakStmt(), st)
                salto.sintetico = True
                stmts[i:i + 1] = [asig, salto]
                hubo = True
                i += 2
                continue
            if isinstance(st, IfStmt):
                hubo |= self._reescribir_breaks(st.then_block.stmts, salir, src, seguir)
                if st.else_block is not None:
                    hubo |= self._reescribir_breaks(st.else_block.stmts, salir, src, seguir)
            i += 1
        return hubo

    def _cond_tag(self, lugar, enum, idx, src):
        fa = _pos(FieldAccess(copy.deepcopy(lugar), TAG), src)
        fa.interno_enum = enum
        return _pos(BinOp("==", fa, _pos(NumLit(idx), src)), src)

    def _ligaduras(self, arm, idx, lugar):
        p = arm.pattern
        if idx is None or not p.binds:
            return []
        lets = []
        nombres = [b.name for b in p.binds if b.name != "_"]
        choca = _raiz(lugar) in nombres
        tardias = []
        for j, b in enumerate(p.binds):
            if b.name == "_":
                continue
            fa = _pos(FieldAccess(copy.deepcopy(lugar), campo_dato(p.name, j)), b)
            fa.interno_enum = self.variantes[p.name][0]
            if choca:
                # `match r { Rect(r, h) => ... }`: si `r` se declarara primero,
                # `h` se leería del dato y no del enum. Se lee todo antes.
                t = self._temporal()
                let_t = _pos(LetStmt(t, fa), b)
                let_t.oculta = True
                lets.append(let_t)
                ultimo = _pos(LetStmt(b.name, _pos(Ident(t), b)), b)
                ultimo.dato_de_match = True
                tardias.append(ultimo)
            else:
                dato = _pos(LetStmt(b.name, fa), b)
                dato.dato_de_match = True     # no se reasigna
                lets.append(dato)
        return lets + tardias

    def _cuerpo(self, arm, forma):
        body = arm.body
        tipo = forma[0]
        if tipo == "sentencia":
            if isinstance(body, Block):
                self._bloque(body)
                return list(body.stmts)
            if isinstance(body, MatchExpr):
                return self._match(body, ("sentencia",))
            return [_pos(ExprStmt(self._expr(body)), body)]
        if isinstance(body, Block):
            self._err("en un match que da un valor, cada brazo es una expresión, sin "
                      "llaves (por ejemplo `Circulo(r) => 3.0 * r * r`)", body)
            return []
        if _es_panic(body):
            return [_pos(ExprStmt(self._expr(body)), body)]
        if isinstance(body, MatchExpr):
            return self._match(body, forma)
        if tipo == "return":
            return [_pos(ReturnStmt(self._expr(body)), body)]
        destino = forma[1]
        valor = self._expr(body)
        if _mismo_lugar(destino, valor):
            return []      # `total = match op { ... _ => total }`: no cambia nada
        asig = _pos(AssignStmt(copy.deepcopy(destino), valor), body)
        asig.brazo_de_match = True
        if len(forma) > 2:
            # `x = match` con x sin mut es un error, una vez y en
            # la línea del match (no una por brazo)
            asig.match_pos = (forma[2].line, forma[2].col)
        return [asig]


# ---------- main -> Result<i32> ----------
MAIN_RESULT = "__main_result"


def bajar_main_result(program):
    """`fn main() -> Result<i32> { cuerpo }` se baja a

        fn __main_result() -> Result<i32> { cuerpo }
        fn main() -> i32 {
            match __main_result() {
                Ok(n) => { return n }
                Err(e) => { print("error:", e)   (a stderr)   return 1 }
            }
        }

    Así `?` funciona en main y nada de los backends cambia: Ok(n) sale con n
    (como main -> i32) y Err sale con 1 y el mensaje en stderr, igual en los
    dos. El print del Err lleva la marca `a_stderr` (solo la pone esta
    bajada). Va antes de bajar_enums, que baja ese match. Devuelve la lista de
    errores (ErrorEnum)."""
    errores = []
    for i, item in enumerate(program.items):
        if not (isinstance(item, FnDecl) and item.name == "main" and not item.is_task):
            continue
        rt = item.return_type
        if rt is None or rt.name != "Result":
            return errores
        if not rt.args or rt.args[0].name != "i32":
            errores.append(ErrorEnum(
                f"'main' devuelve nada, un i32 o un Result<i32> (el código de salida del "
                f"programa, y en un Err el mensaje), no {rt!r}",
                getattr(item, "line", None), getattr(item, "col", None)))
            return errores
        if any(isinstance(x, FnDecl) and x.name == MAIN_RESULT for x in program.items):
            errores.append(ErrorEnum(f"'{MAIN_RESULT}' es un nombre reservado", None, None))
            return errores
        item.name = MAIN_RESULT
        item.es_main_result = True
        llamada = _pos(Call(_pos(Ident(MAIN_RESULT), item), []), item)
        aviso = _pos(PrintExpr([_pos(StrLit("error:"), item), _pos(Ident("e"), item)]), item)
        aviso.a_stderr = True
        ok = MatchArm(_pos(Patron("Ok", [_pos(Ident("n"), item)]), item),
                      _pos(Block([_pos(ReturnStmt(_pos(Ident("n"), item)), item)]), item))
        err = MatchArm(_pos(Patron("Err", [_pos(Ident("e"), item)]), item),
                       _pos(Block([_pos(ExprStmt(aviso), item),
                                   _pos(ReturnStmt(_pos(NumLit(1), item)), item)]), item))
        _pos(ok, item)
        _pos(err, item)
        m = _pos(MatchExpr(llamada, [ok, err], es_sentencia=True), item)
        # el return del final no se alcanza (el match sale por un brazo), pero
        # el checker no sabe que el while let del Ok corre siempre
        final = _pos(ReturnStmt(_pos(NumLit(1), item)), item)
        envoltorio = _pos(FnDecl("main", [], _pos(Block([_pos(ExprStmt(m), item), final]), item),
                                 is_task=False, return_type=TypeAnn("i32")), item)
        program.items.insert(i + 1, envoltorio)
        return errores
    return errores


def bajar_enums(program, nombres_builtin):
    """Baja los enum y match de `program` (en el lugar). Devuelve la lista de
    errores (ErrorEnum); vacía si todo está bien. Sin enum ni match, no toca
    nada."""
    if not tiene_enums(program):
        return []
    return _Bajada(program, nombres_builtin).correr()
