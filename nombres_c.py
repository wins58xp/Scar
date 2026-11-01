"""Los nombres del usuario nunca llegan crudos al C.

El codegen escribía cada nombre del programa tal cual como identificador de C.
Un nombre válido en SCAR podía chocar con algo de C: una variable `exp` tapaba
la función de libm, `printf` o `exit` chocaban con libc, `FILE`, `stdin` o
`errno` con macros y tipos de stdio, `int` o `double` con palabras clave de C.
Entonces el checker lo aceptaba, el intérprete lo corría y el nativo no
compilaba. Que con `malloc` o `strlen` compilara era suerte: dependía de que el
C generado no llamara a esa función en el mismo bloque.

La regla: antes del codegen, una COPIA del programa recibe un prefijo en cada
nombre que eligió el usuario: una letra por clase de nombre, el largo del
nombre y un guion bajo.

    v   variables, parámetros, variable de `for` y de `while let`   v3_exp
    f   fn y task (menos `main`, que el codegen trata aparte)       f6_printf
    S   structs                                                     S4_FILE
    c   campos de struct                                            c3_int
    g   fn genéricas                                                g6_memcpy
    G   structs genéricos                                           G4_Caja

Ningún prefijo así coincide con lo que usa el runtime (`scar_`, `__scar_`,
`Vec_`, `Option_`, `TaskContext`) ni con libc. El largo hace que la
codificación aguante sufijos: el codegen arma nombres agregando algo al de un
struct o de un genérico (`S5_Punto_free`, la instancia `G4_Caja_i32`), y
ninguno de esos puede ser el nombre de C de otra cosa del usuario: un struct
`Punto_free` es `S10_Punto_free`, una fn `Caja_i32` es `f8_Caja_i32`. Con un
prefijo fijo (`S_`) sí chocaban: el struct `Option_str` generaba el helper
`S_Option_str_free`, que era el nombre de un struct `Option_str_free`.

No llevan prefijo los builtins, las `extern fn` (son símbolos de una librería
de C y tienen que llamarse exactamente así), los `extern type`, ni los
parámetros de tipo de un genérico (`T`).

El intérprete y las herramientas (LSP, autocompletado) siguen usando el
programa original. Lo que el programa muestra (el print de un struct, el
nombre de una task, el mensaje de un Err de inject_chan, un error de
compilación) pasa por `mostrar()`/`desproteger()`, que devuelven el nombre
original."""
import copy
import re

from parser import (
    Block, Call, ExternFnDecl, FieldAccess, FnDecl, ForStmt, Ident, LetStmt,
    Node, Param, StructDecl, StructLit, WhileLetStmt,
)
from type_checker import NOMBRES_BUILTIN
from types_ import TypeAnn

VAR, FN, STRUCT, CAMPO, FN_GENERICA, STRUCT_GENERICO = "v", "f", "S", "c", "g", "G"

# fn que el codegen reconoce por su nombre: no se renombra.
_FN_SIN_PREFIJO = frozenset({"main"})


def nombre_c(clase, nombre):
    """Módulos: un nombre de módulo (`gui.boton`) no es un
    identificador de C; se escribe `f3mgui_5_boton`: después del largo del
    módulo va una `m` (en un nombre sin módulo, después de los dígitos viene
    siempre `_`), así que no puede coincidir con ningún otro."""
    if "." in nombre:
        modulo, base = nombre.split(".", 1)
        return f"{clase}{len(modulo)}m{modulo}_{len(base)}_{base}"
    return f"{clase}{len(nombre)}_{nombre}"


_RE_NOMBRE_C = re.compile(r"([vfScgG])(\d+)_")
_RE_NOMBRE_C_MODULO = re.compile(r"([vfScgG])(\d+)m")


class Nombres:
    """Lo que hizo proteger(): el nombre original de cada nombre de C."""

    def __init__(self):
        self.originales = {}   # nombre en C -> nombre del usuario

    def anotar(self, c_name, original):
        self.originales[c_name] = original
        return c_name

    def _partir(self, w):
        """`G4_Caja_i32` -> ("Caja", "_i32") si empieza con un nombre de C
        del usuario; None si no."""
        m = _RE_NOMBRE_C.match(w)
        if m is not None:
            base = w[:m.end() + int(m.group(2))]
        else:
            # módulos: `f3mgui_5_boton` (ver nombre_c)
            m = _RE_NOMBRE_C_MODULO.match(w)
            if m is None:
                return None
            fin_mod = m.end() + int(m.group(2))
            m2 = re.compile(r"_(\d+)_").match(w, fin_mod)
            if m2 is None:
                return None
            base = w[:m2.end() + int(m2.group(1))]
        if base not in self.originales:
            return None
        return self.originales[base], w[len(base):]

    def mostrar(self, c_name):
        """El nombre que vio el usuario. Una instancia de un struct genérico
        (`G4_Caja_i32`) se muestra con el nombre del genérico (`Caja`), como
        en el intérprete."""
        partes = self._partir(c_name)
        return c_name if partes is None else partes[0]

    _RE_PALABRA = re.compile(r"\b[A-Za-z_]\w*\b")

    def desproteger(self, texto):
        """Devuelve un mensaje (p. ej. un error de compilación) con los
        nombres del usuario como los escribió (una instancia, `Caja_i32`)."""
        def cambiar(m):
            partes = self._partir(m.group(0))
            return m.group(0) if partes is None else partes[0] + partes[1]
        return self._RE_PALABRA.sub(cambiar, texto)


def proteger(program):
    """Devuelve (copia del programa con los nombres protegidos, Nombres)."""
    prog = copy.deepcopy(program)
    nombres = Nombres()
    # nombre del usuario -> clase
    structs = {it.name: STRUCT_GENERICO if it.type_params else STRUCT
               for it in prog.items if isinstance(it, StructDecl)}
    fns = {it.name: FN_GENERICA if it.type_params else FN
           for it in prog.items
           if isinstance(it, FnDecl) and it.name not in _FN_SIN_PREFIJO}
    externs = {it.name for it in prog.items if isinstance(it, ExternFnDecl)}
    r = _Renombrador(nombres, structs, fns, externs)
    for item in prog.items:
        r.item(item)
    return prog, nombres


class _Renombrador:
    def __init__(self, nombres, structs, fns, externs):
        self.n = nombres
        self.structs = structs
        self.fns = fns
        self.externs = externs
        self.vistos = set()      # id() de TypeAnn ya renombrados (pueden estar compartidos)
        self.scopes = []

    # -- nombres --
    def _c(self, clase, name):
        return self.n.anotar(nombre_c(clase, name), name)

    def var(self, name):
        return self._c(VAR, name)

    def fn(self, name):
        if name in _FN_SIN_PREFIJO:
            return name
        return self._c(self.fns[name], name)

    def struct(self, name):
        return self._c(self.structs[name], name)

    def campo(self, name):
        return self._c(CAMPO, name)

    def tipo(self, ty):
        if not isinstance(ty, TypeAnn) or id(ty) in self.vistos:
            return
        self.vistos.add(id(ty))
        if ty.name in self.structs:
            ty.name = self.struct(ty.name)
        if ty.name == "Task" and len(ty.args) >= 2:
            # Task<T, tarea> escrito a mano (Option<Task<i32, t>>): el segundo
            # argumento nombra la tarea, que se renombra como una fn (igual
            # que el tipo que arma spawn), no como un struct.
            nombre = ty.args[1]
            if isinstance(nombre, TypeAnn) and id(nombre) not in self.vistos:
                self.vistos.add(id(nombre))
                if nombre.name in self.fns:
                    nombre.name = self.fn(nombre.name)
            self.tipo(ty.args[0])
            return
        for a in ty.args:
            self.tipo(a)

    # -- scopes --
    def declarar(self, name):
        self.scopes[-1].add(name)
        return self.var(name)

    def es_local(self, name):
        return any(name in s for s in self.scopes)

    def ident(self, node):
        """Una referencia: la variable más cercana, si no una fn del usuario;
        si no es ninguna de las dos (builtin, extern fn), queda igual."""
        if self.es_local(node.name):
            node.name = self.var(node.name)
        elif node.name in self.fns:
            node.name = self.fn(node.name)

    def callee(self, node):
        """`nombre(...)`. A diferencia de una referencia, una variable solo
        gana si es de tipo fn: `let exp = 2.0` y después `exp(1.0)` llama al
        builtin (type_checker, Call). El checker marca ese caso con
        `es_valor_fn`; sin la marca (un AST que no pasó por el checker) una
        variable gana solo si el nombre no es de ninguna función."""
        if not isinstance(node, Ident):
            self.expr(node)
        elif getattr(node, "es_valor_fn", False):
            node.name = self.var(node.name)
        elif node.name in self.fns:
            node.name = self.fn(node.name)
        elif self.es_local(node.name) and node.name not in self.externs \
                and node.name not in NOMBRES_BUILTIN:
            node.name = self.var(node.name)

    # -- recorrido --
    def item(self, item):
        if isinstance(item, StructDecl):
            item.name = self.struct(item.name)
            nuevos = []
            for fname, fty in item.fields:
                self.tipo(fty)
                nuevos.append((self.campo(fname), fty))
            item.fields = nuevos
        elif isinstance(item, FnDecl):
            item.name = self.fn(item.name)
            self.tipo(item.return_type)
            for t in item.accepts:
                self.tipo(t)
            self.scopes = [set()]
            for p in item.params:
                self.tipo(p.type_ann)
                p.name = self.declarar(p.name)
            self.bloque(item.body, nuevo_scope=False)
            self.scopes = []
        elif isinstance(item, ExternFnDecl):
            # el nombre es el símbolo de C; los parámetros no se usan como
            # identificadores en ningún cuerpo, pero sus tipos sí pueden ser
            # structs del usuario
            for p in item.params:
                self.tipo(p.type_ann)
            self.tipo(item.return_type)
        else:
            self.generico(item)

    def bloque(self, block, nuevo_scope=True):
        if nuevo_scope:
            self.scopes.append(set())
        for st in block.stmts:
            self.stmt(st)
        if nuevo_scope:
            self.scopes.pop()

    def stmt(self, st):
        if isinstance(st, LetStmt):
            # el lado derecho se resuelve ANTES de declarar el nombre:
            # `let x = x + 1` lee la x de afuera
            self.expr(st.expr)
            self.tipo(st.declared_type)
            st.name = self.declarar(st.name)
        elif isinstance(st, ForStmt):
            self.expr(st.start)
            self.expr(st.end)
            self.scopes.append(set())
            st.var = self.declarar(st.var)
            self.bloque(st.body)
            self.scopes.pop()
        elif isinstance(st, WhileLetStmt):
            self.expr(st.expr)
            self.scopes.append(set())
            st.pattern = self.declarar(st.pattern)
            self.bloque(st.body)
            self.scopes.pop()
        elif isinstance(st, Block):
            self.bloque(st)
        else:
            self.generico(st)

    def expr(self, e):
        if isinstance(e, Ident):
            self.ident(e)
        elif isinstance(e, StructLit):
            if e.name in self.structs:
                e.name = self.struct(e.name)
            e.fields = {self.campo(k): v for k, v in e.fields.items()}
            for v in e.fields.values():
                self.expr(v)
        elif isinstance(e, FieldAccess):
            self.expr(e.obj)
            e.field = self.campo(e.field)
        elif isinstance(e, Call):
            self.callee(e.callee)
            for a in e.args:
                self.expr(a)
            self.generico(e, saltar=("callee", "args"))
        else:
            self.generico(e)

    def generico(self, node, saltar=()):
        """Cualquier otro nodo: recorre sus atributos (sub-nodos, bloques,
        listas, tipos) sin cambiar nada propio."""
        for k, v in vars(node).items():
            if k in saltar:
                continue
            self._valor(v)

    def _valor(self, v):
        if isinstance(v, Block):
            self.bloque(v)
        elif isinstance(v, (LetStmt, ForStmt, WhileLetStmt)):
            self.stmt(v)
        elif isinstance(v, Node):
            if isinstance(v, (Param, FnDecl, StructDecl)):
                raise AssertionError(f"nombres_c: {type(v).__name__} en un lugar inesperado")
            # una sentencia sin nombre propio (if, while, return, asignación,
            # expresión) o una expresión: mismo trato
            self.expr(v) if not _es_stmt(v) else self.generico(v)
        elif isinstance(v, TypeAnn):
            self.tipo(v)
        elif isinstance(v, (list, tuple)):
            for x in v:
                self._valor(x)
        elif isinstance(v, dict):
            for x in v.values():
                self._valor(x)


def _es_stmt(node):
    from parser import AssignStmt, ExprStmt, IfStmt, ReturnStmt, WhileStmt
    return isinstance(node, (AssignStmt, ExprStmt, IfStmt, ReturnStmt, WhileStmt))
