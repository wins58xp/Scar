"""Módulos de SCAR: `use "gui"`.

Un programa trae un módulo con `use "ruta"` al principio del archivo y usa lo
que el módulo declara con su nombre adelante: `gui.boton(ui, "Sumar")`,
`gui.Ventana`, `gui.Rojo` en un `match`. El nombre del módulo es la última parte
de la ruta (`use "comun/json"` trae `json.`).

Dónde se busca `use "x"`: primero `x.scar` al lado del archivo que lo pide, y
si no está, en `lib/` de SCAR (la carpeta de este archivo): la librería que
viene con el lenguaje.

Reglas:
  - Todo lo que declara un módulo se ve desde afuera, salvo lo que empieza con
    `_` (`gui._medir` es un error; lo controla el parser).
  - Un módulo ve lo suyo y lo de los módulos que él mismo trae; nunca lo de
    quien lo usa (un nombre que no es del módulo ni un builtin se lee como del
    módulo, y el checker dice que no existe: "gui.dibujar").
  - Cada módulo se carga una sola vez aunque lo pidan varios; un ciclo (`a`
    trae a `b` y `b` a `a`) es un error que muestra el ciclo.
  - Dos módulos distintos no pueden llamarse igual en un mismo programa.
  - Una variable, un parámetro o una fn no pueden llamarse como un módulo que
    el archivo trae (`gui.x` sería ambiguo).

Cómo (agua): antes del checker, cada módulo se lee y sus nombres pasan a
llevar el prefijo (`boton` -> `gui.boton`), adentro de él también; después todo
se junta en UN programa. El checker, el intérprete y el codegen reciben un
programa como cualquier otro, así que la paridad entre los dos backends no
depende de nada nuevo. Cada nodo que viene de un módulo lleva `archivo`: los
errores dicen en qué archivo están. Las `extern fn` y los `extern type` no se
prefijan (son nombres de C); si dos archivos declaran la misma, tiene que ser
idéntica, y queda una sola.
"""
import os

from lexer import LexError
from parser import (
    Block, Call, EnumDecl, ExternFnDecl, ExternLibDecl, ExternTypeDecl, FnDecl,
    ForStmt, Ident, LetStmt, MatchExpr, Node, ParseError, Patron, Program,
    StructDecl, StructLit, WhileLetStmt, parse,
)
from types_ import FN_MARK, PRIMITIVE_NAMES, TypeAnn

RAIZ_SCAR = os.path.dirname(os.path.abspath(__file__))
DIR_LIB = os.path.join(RAIZ_SCAR, "lib")

# Tipos del lenguaje (no se prefijan en un módulo).
TIPOS_DEL_LENGUAJE = frozenset(PRIMITIVE_NAMES) | {
    "Option", "Result", "Task", "Chan", "Vec", "Map", "Pipe", "File", "Socket",
    "Listener", FN_MARK,
}
_PATRONES_DEL_LENGUAJE = {"_", "Some", "None", "Ok", "Err"}


class ErrorDeModulo(Exception):
    """Un `use` que no se puede resolver (no existe, ciclo, nombre repetido)
    o un nombre que choca con un módulo. Se muestra como un error de sintaxis,
    con el archivo y la línea donde está."""

    def __init__(self, msg, archivo=None, line=None, col=None):
        self.msg = msg
        self.archivo = archivo
        self.line = line
        self.col = col
        super().__init__(f"{msg} (línea {line})" if line else msg)


def leer_fuente(ruta, archivo=None):
    """El texto de un .scar. Un byte que no es
    UTF-8 daba un traceback de Python; ahora es un error con la línea."""
    with open(ruta, "rb") as f:
        crudo = f.read()
    try:
        return crudo.decode("utf-8")
    except UnicodeDecodeError as e:
        linea = crudo.count(b"\n", 0, e.start) + 1
        col = e.start - (crudo.rfind(b"\n", 0, e.start) + 1) + 1
        raise ErrorDeModulo(
            f"el archivo no es UTF-8 válido: byte 0x{crudo[e.start]:02x} en la línea {linea} "
            f"(guardalo como UTF-8)", archivo, linea, col)


def cargar(ruta, texto=None):
    """El programa de `ruta` con todos sus módulos resueltos y juntos. `texto`
    reemplaza el contenido del archivo (el editor manda lo que no se guardó).
    Puede lanzar LexError / ParseError (con `archivo` si el error está en un
    módulo) o ErrorDeModulo."""
    ruta = os.path.abspath(ruta)
    if texto is None:
        texto = leer_fuente(ruta)
    principal = parse(texto)
    if not principal.usos:
        return principal
    return _Cargador(ruta).cargar(principal)


class _Cargador:
    def __init__(self, ruta_principal):
        self.principal = ruta_principal
        self.cargados = {}       # ruta absoluta -> items ya prefijados
        self.nombre_de = {}      # nombre del módulo -> ruta absoluta
        self.en_curso = []       # pila de rutas (para ver ciclos)
        self.items = []          # items de los módulos, en orden de carga

    def cargar(self, principal):
        self.en_curso.append(self.principal)
        self._traer_usos(principal.usos, self.principal, None)
        self.en_curso.pop()
        _revisar_nombres_de_modulo(principal, {u.nombre for u in principal.usos}, None)
        items = _sin_repetidos(self.items + principal.items)
        prog = Program(items)
        prog.line, prog.col = principal.line, principal.col
        return prog

    def _resolver(self, uso, desde, archivo_uso):
        base = os.path.dirname(desde)
        candidatos = [os.path.join(base, uso.ruta + ".scar"), os.path.join(DIR_LIB, uso.ruta + ".scar")]
        for c in candidatos:
            if os.path.isfile(c):
                return os.path.abspath(c)
        donde = f"{base} y en {DIR_LIB}"
        raise ErrorDeModulo(
            f"no encontré el módulo '{uso.ruta}': busqué {uso.ruta}.scar en {donde}",
            archivo_uso, uso.line, uso.col)

    def _traer_usos(self, usos, desde, archivo_uso):
        for uso in usos:
            ruta = self._resolver(uso, desde, archivo_uso)
            otra = self.nombre_de.get(uso.nombre)
            if otra is not None and otra != ruta:
                raise ErrorDeModulo(
                    f"dos módulos distintos se llaman '{uso.nombre}' en este programa "
                    f"({_visible(otra)} y {_visible(ruta)})",
                    archivo_uso, uso.line, uso.col)
            self.nombre_de[uso.nombre] = ruta
            if ruta == self.principal and desde == self.principal:
                # el programa se pide a sí mismo directo; antes que el ciclo: "fecha -> fecha" no explica nada. El
                # caso típico es un programa que se llama como un módulo de
                # lib/ (fecha.scar con use "fecha"): se encuentra a sí mismo
                # primero, porque lo de al lado del archivo va antes que lib/.
                de_lib = os.path.join(DIR_LIB, uso.ruta + ".scar")
                if os.path.isfile(de_lib):
                    msg = (f"el programa se trae a sí mismo con use \"{uso.ruta}\": se llama "
                           f"igual que el módulo {uso.ruta} de lib/, y lo que está al lado "
                           f"del programa se busca primero. Cambia el nombre del archivo")
                else:
                    msg = f"el programa se trae a sí mismo con use \"{uso.ruta}\""
                raise ErrorDeModulo(msg, archivo_uso, uso.line, uso.col)
            if ruta in self.en_curso:
                ciclo = self.en_curso[self.en_curso.index(ruta):] + [ruta]
                raise ErrorDeModulo(
                    "ciclo de módulos: " + " -> ".join(_nombre_corto(r) for r in ciclo),
                    archivo_uso, uso.line, uso.col)
            if ruta in self.cargados:
                continue
            self._cargar_modulo(ruta, uso.nombre)

    def _cargar_modulo(self, ruta, nombre):
        visible = _visible(ruta)
        texto = leer_fuente(ruta, visible)
        try:
            prog = parse(texto)
        except (LexError, ParseError) as e:
            e.archivo = visible
            raise
        _marcar_archivo(prog, visible)
        self.en_curso.append(ruta)
        self._traer_usos(prog.usos, ruta, visible)
        self.en_curso.pop()
        for it in prog.items:
            if isinstance(it, FnDecl) and it.name == "main":
                raise ErrorDeModulo(
                    f"el módulo '{nombre}' tiene una fn main: un módulo no es un programa",
                    visible, it.line, it.col)
        _revisar_nombres_de_modulo(prog, {u.nombre for u in prog.usos}, visible)
        _Prefijador(nombre, prog).aplicar()
        self.cargados[ruta] = prog.items
        self.items.extend(prog.items)


def _visible(ruta):
    """La ruta como la muestran los errores: relativa a donde se corre si
    queda adentro, si no completa."""
    rel = os.path.relpath(ruta)
    return ruta if rel.startswith("..") else rel


def _nombre_corto(ruta):
    return os.path.splitext(os.path.basename(ruta))[0]


def _marcar_archivo(nodo, archivo):
    pila = [nodo]
    while pila:
        n = pila.pop()
        if isinstance(n, Node):
            n.archivo = archivo
            pila.extend(v for k, v in vars(n).items() if k not in ("line", "col", "archivo"))
        elif isinstance(n, (list, tuple)):
            pila.extend(n)
        elif isinstance(n, dict):
            pila.extend(n.values())


def _sin_repetidos(items):
    """Las `extern lib`, `extern type` y `extern fn` que dos archivos declaran
    igual quedan una vez; si difieren, es un error."""
    vistos = {}
    salida = []
    for it in items:
        if isinstance(it, ExternLibDecl):
            clave = ("lib", it.library)
            firma = it.modo
        elif isinstance(it, ExternTypeDecl):
            clave = ("type", it.name)
            firma = None
        elif isinstance(it, ExternFnDecl):
            clave = ("fn", it.name)
            firma = (it.abi, it.library, repr(it.return_type),
                     tuple((repr(p.type_ann), getattr(p, "consumes", False)) for p in it.params))
        else:
            salida.append(it)
            continue
        if clave in vistos:
            if vistos[clave] != firma:
                que = {"lib": "extern lib", "type": "extern type", "fn": "extern fn"}[clave[0]]
                raise ErrorDeModulo(
                    f"'{que} {clave[1]}' está declarada distinta en dos archivos del programa",
                    getattr(it, "archivo", None), it.line, it.col)
            continue
        vistos[clave] = firma
        salida.append(it)
    return salida


def _revisar_nombres_de_modulo(prog, modulos, archivo):
    """Nada declarado en el archivo puede llamarse como un módulo que trae."""
    if not modulos:
        return

    def choca(nombre, nodo):
        if nombre in modulos:
            raise ErrorDeModulo(
                f"'{nombre}' es el nombre de un módulo que este archivo trae con use: "
                f"elige otro nombre", archivo, getattr(nodo, "line", None), getattr(nodo, "col", None))

    pila = list(prog.items)
    while pila:
        n = pila.pop()
        if isinstance(n, (FnDecl, StructDecl, EnumDecl, ExternFnDecl, ExternTypeDecl)):
            choca(n.name, n)
        if isinstance(n, FnDecl):
            for p in n.params:
                choca(p.name, p)
        elif isinstance(n, LetStmt):
            choca(n.name, n)
        elif isinstance(n, ForStmt):
            choca(n.var, n)
        elif isinstance(n, WhileLetStmt) and isinstance(n.pattern, str):
            choca(n.pattern, n)
        elif isinstance(n, Patron) and n.binds:
            for b in n.binds:
                choca(b.name, b)
        if isinstance(n, Node):
            pila.extend(v for k, v in vars(n).items() if k not in ("line", "col", "archivo"))
        elif isinstance(n, (list, tuple)):
            pila.extend(n)
        elif isinstance(n, dict):
            pila.extend(n.values())


class _Prefijador:
    """Pone el prefijo del módulo (`gui.`) a todo lo que el módulo declara y a
    cada referencia a eso adentro del módulo. Una referencia que no es una
    variable local, un builtin, una extern fn ni algo de otro módulo
    (`otro.x`) es del módulo: si no existe, el checker lo dice con el nombre
    completo."""

    def __init__(self, nombre, prog):
        from type_checker import NOMBRES_BUILTIN
        self.p = nombre + "."
        self.builtins = NOMBRES_BUILTIN
        self.prog = prog
        self.externs = {it.name for it in prog.items if isinstance(it, ExternFnDecl)}
        self.tipos_externos = {it.name for it in prog.items if isinstance(it, ExternTypeDecl)}
        self.scopes = []
        self.params_tipo = set()
        self.vistos = set()      # id() de los TypeAnn ya prefijados (pueden estar compartidos)

    def _prefijo(self, nombre):
        return self.p + nombre

    def aplicar(self):
        for it in self.prog.items:
            self.params_tipo = set(getattr(it, "type_params", None) or [])
            if isinstance(it, StructDecl):
                it.name = self._prefijo(it.name)
                for _, t in it.fields:
                    self.tipo(t)
            elif isinstance(it, EnumDecl):
                it.name = self._prefijo(it.name)
                for v in it.variants:
                    v.name = self._prefijo(v.name)
                    for t in v.types:
                        self.tipo(t)
            elif isinstance(it, FnDecl):
                it.name = self._prefijo(it.name)
                self.tipo(it.return_type)
                for t in it.accepts:
                    self.tipo(t)
                self.scopes = [set()]
                for p in it.params:
                    self.tipo(p.type_ann)
                    self.scopes[-1].add(p.name)
                self.bloque(it.body, nuevo=False)
                self.scopes = []
            elif isinstance(it, ExternFnDecl):
                for p in it.params:
                    self.tipo(p.type_ann)
                self.tipo(it.return_type)
            self.params_tipo = set()

    # -- nombres --
    def _es_local(self, nombre):
        return any(nombre in s for s in self.scopes)

    def _del_modulo(self, nombre, de_valor=True):
        """¿`nombre` (una referencia) se lee como algo de este módulo?"""
        if "." in nombre:
            return False                       # de otro módulo, ya calificado
        if de_valor and self._es_local(nombre):
            return False
        return nombre not in self.builtins and nombre not in self.externs

    def tipo(self, t):
        if not isinstance(t, TypeAnn) or id(t) in self.vistos:
            return
        self.vistos.add(id(t))
        n = t.name
        if ("." not in n and n not in TIPOS_DEL_LENGUAJE and n not in self.tipos_externos
                and n not in self.params_tipo):
            t.name = self._prefijo(n)
        for a in t.args:
            self.tipo(a)

    # -- recorrido --
    def bloque(self, b, nuevo=True):
        if nuevo:
            self.scopes.append(set())
        for st in b.stmts:
            self.nodo(st)
        if nuevo:
            self.scopes.pop()

    def nodo(self, n):
        if isinstance(n, Block):
            self.bloque(n)
        elif isinstance(n, LetStmt):
            self.nodo(n.expr)               # `let x = x + 1` lee la x de afuera
            self.tipo(n.declared_type)
            self.scopes[-1].add(n.name)
        elif isinstance(n, ForStmt):
            self.nodo(n.start)
            self.nodo(n.end)
            self.scopes.append({n.var})
            self.bloque(n.body)
            self.scopes.pop()
        elif isinstance(n, WhileLetStmt):
            self.nodo(n.expr)
            self.scopes.append({n.pattern} if isinstance(n.pattern, str) else set())
            if not isinstance(n.pattern, str):
                self.nodo(n.pattern)
            self.bloque(n.body)
            self.scopes.pop()
        elif isinstance(n, MatchExpr):
            self.nodo(n.scrutinee)
            for arm in n.arms:
                pat = arm.pattern
                if pat.name not in _PATRONES_DEL_LENGUAJE and "." not in pat.name:
                    pat.name = self._prefijo(pat.name)
                self.scopes.append({b.name for b in (pat.binds or [])})
                self.nodo(arm.body)
                self.scopes.pop()
        elif isinstance(n, Ident):
            if self._del_modulo(n.name):
                n.name = self._prefijo(n.name)
        elif isinstance(n, Call):
            if isinstance(n.callee, Ident):
                if self._del_modulo(n.callee.name):
                    n.callee.name = self._prefijo(n.callee.name)
            else:
                self.nodo(n.callee)
            for a in n.args:
                self.nodo(a)
        elif isinstance(n, StructLit):
            if "." not in n.name:
                n.name = self._prefijo(n.name)
            for v in n.fields.values():
                self.nodo(v)
        elif isinstance(n, Node):
            for k, v in vars(n).items():
                if k in ("line", "col", "archivo"):
                    continue
                self._valor(v)

    def _valor(self, v):
        if isinstance(v, TypeAnn):
            self.tipo(v)
        elif isinstance(v, Node):
            self.nodo(v)
        elif isinstance(v, (list, tuple)):
            for x in v:
                self._valor(x)
        elif isinstance(v, dict):
            for x in v.values():
                self._valor(x)
