"""
Resolución de scope local para el autocompletado del LSP.

Diseño:

  - No se reusa el recorrido de type_checker.py (Checker/TypeEnv). Ese
    camino exige que el programa ENTERO type-cheque sin error para poder
    acumular scopes (una sola llamada a check_program hace todo el
    trabajo junto), y el caso de uso real de autocompletado es lo
    opuesto: el usuario está escribiendo, el archivo está roto la mitad
    del tiempo. Un resolver paralelo, más chico y que NO valida tipos,
    tolera eso -- solo necesita el ÚLTIMO AST que haya parseado bien
    (lsp_server.py lo guarda en `last_good_ast`),
    no que además type-cheque.
  - Tabla de símbolos por posición: dado (línea, columna) 1-based (mismo
    sistema que Token/Node.line/col, ver parser.py), se devuelve la
    lista de nombres visibles ahí -- parámetros de la función que
    contiene el cursor, más cada `let`/patrón de `while let`/variable de
    `for` ya declarado ANTES del cursor en algún bloque que lo contiene.
  - "Contiene" se resuelve con una heurística de líneas, no con un rango
    exacto: cada nodo trae `line`/`col` de INICIO (Node.at()), pero
    ninguno trae
    dónde termina. Para saber si el cursor cae DENTRO de un bloque
    anidado (el `then`/`else` de un `if`, el cuerpo de un `while`/`for`)
    en vez de simplemente DESPUÉS de todo el `if`, se usa como cota
    superior la línea del próximo statement HERMANO en el bloque
    exterior (o `None` si es el último -- ver `_next_sibling_bound`).
    No es un rango exacto, pero alcanza para autocompletar: con
    indentación razonable, un editor real nunca deja el cursor en el
    borde ambiguo de una sola línea.
  - Tipo de cada nombre: se usa la anotación explícita si el
    `let`/parámetro la tiene; si no, un best-effort chico (litoral
    numérico -> i32/f64 según corresponda, string -> str, bool -> bool,
    `StructLit` -> el nombre del struct, llamada a una `fn`/`task`/
    `extern fn` del mismo Program -> su `return_type`) -- nunca el
    inferidor completo de `type_checker.py`. Si no se puede inferir
    nada barato, el tipo queda en `None` (el LSP igual puede ofrecer el
    nombre sin tipo, ver `_handle_completion` en lsp_server.py).

La entrada es `resolve_scope(program, line, col)`, PURA (no toca
lsp_server.py, no tiene estado propio).
"""

from parser import (
    FnDecl, ExternFnDecl, IfStmt, WhileStmt, WhileLetStmt, ForStmt,
    LetStmt, Call, Ident, NumLit, StrLit, BoolLit, StructLit,
)
from types_ import TypeAnn


class Symbol:
    """Un nombre visible en la posición (line, col) consultada."""

    def __init__(self, name, type_ann, kind):
        self.name = name
        self.type_ann = type_ann  # TypeAnn o None -- ver nota de best-effort arriba
        self.kind = kind  # "param" | "let" | "while_let" | "for_var"

    def __repr__(self):
        ty = repr(self.type_ann) if self.type_ann is not None else "?"
        return f"{self.name}: {ty} ({self.kind})"

    def __eq__(self, other):
        return (
            isinstance(other, Symbol)
            and self.name == other.name
            and self.type_ann == other.type_ann
            and self.kind == other.kind
        )


def resolve_scope(program, line, col):
    """Dado el Program y una posición 1-based, devuelve la lista de
    Symbol visibles ahí: parámetros de la función/task que contiene el
    cursor, más cada let/while-let/for declarado antes del cursor en un
    bloque que lo contiene. Lista vacía si la posición no cae dentro de
    ninguna fn/task (ej. a nivel de módulo) o si `program` es None (ver
    lsp_server.py: pasa None cuando todavía no hay ningún AST válido)."""
    if program is None:
        return []
    fn = _enclosing_fn(program, line)
    if fn is None or fn.body is None:
        return []
    visible = [Symbol(p.name, p.type_ann, "param") for p in fn.params]
    return _walk_block(fn.body.stmts, line, col, None, visible, program)


def _enclosing_fn(program, line):
    """La fn/task cuyo cuerpo contiene `line`: la última declarada antes
    o en esa línea (heurística -- no hay línea de cierre de fn en el AST
    hoy, ver nota de diseño arriba; correcta salvo que el cursor esté
    literalmente en la línea de la llave de cierre de una fn anterior,
    caso borde sin impacto práctico en autocompletado)."""
    candidates = [
        item
        for item in program.items
        if isinstance(item, FnDecl) and item.line is not None and item.line <= line
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.line)


def _next_sibling_bound(stmts, i, outer_bound):
    """Línea del statement siguiente a stmts[i] en el mismo bloque, o
    `outer_bound` (la cota heredada del llamador) si stmts[i] es el
    último del bloque."""
    if i + 1 < len(stmts) and stmts[i + 1].line is not None:
        return stmts[i + 1].line
    return outer_bound


def _block_could_contain(block, line, bound):
    """¿Puede `line` caer dentro de `block`? `block.line` es la línea del
    '{' de apertura (siempre presente, ver Node.at() en Parser.parse_block);
    `bound` es la cota superior heredada del llamador (línea del próximo
    hermano, o None si no hay cota conocida -- último bloque abierto en
    ese punto del archivo)."""
    if block is None or block.line is None:
        return False
    if line < block.line:
        return False
    return bound is None or line < bound


def _nested_scopes(stmt):
    """Bloques hijos de `stmt` que abren su propio scope, junto con los
    Symbol extra que ese bloque agrega (binding de `while let`, variable
    de `for`) -- lista de (Block, [Symbol]). Un IfStmt puede aportar dos
    (then/else); el resto, a lo sumo uno."""
    if isinstance(stmt, IfStmt):
        out = [(stmt.then_block, [])]
        if stmt.else_block is not None:
            out.append((stmt.else_block, []))
        return out
    if isinstance(stmt, WhileStmt):
        return [(stmt.body, [])]
    if isinstance(stmt, WhileLetStmt):
        # `while let Some(x) = expr { ... }`: x vive solo dentro del
        # cuerpo. Tipo desconocido acá a propósito (haría falta inferir
        # el T de expr, que es justo el trabajo que este módulo evita) --
        # None, no un TypeAnn inventado.
        return [(stmt.body, [Symbol(stmt.pattern, None, "while_let")])]
    if isinstance(stmt, ForStmt):
        # `for i in a..b { ... }`: i siempre es i32 -- el checker exige
        # rango i32..i32 (type_checker.py, _check_stmt/ForStmt), no hay
        # otro caso posible.
        return [(stmt.body, [Symbol(stmt.var, TypeAnn("i32"), "for_var")])]
    return []


def _walk_block(stmts, line, col, outer_bound, visible, program):
    """Recorre un bloque en orden; devuelve los Symbol visibles en el
    scope más profundo que contiene (line, col). `visible` ya trae lo
    heredado de bloques exteriores (params, lets de scopes padre)."""
    for i, stmt in enumerate(stmts):
        s_line = stmt.line if stmt.line is not None else -1
        s_col = stmt.col if stmt.col is not None else 0
        if (s_line, s_col) > (line, col):
            # el cursor está antes de este statement: acá termina lo
            # visible en este bloque, nada más que recorrer.
            return visible

        bound = _next_sibling_bound(stmts, i, outer_bound)
        for nested_block, extra in _nested_scopes(stmt):
            if _block_could_contain(nested_block, line, bound):
                return _walk_block(
                    nested_block.stmts, line, col, bound, visible + extra, program,
                )

        if isinstance(stmt, LetStmt) and not getattr(stmt, "oculta", False):
            # (`oculta` marca las variables temporales que arma
            # enum_match al bajar un match; el usuario no las escribió)
            visible = visible + [
                Symbol(stmt.name, _infer_let_type(stmt, program), "let")
            ]

    return visible


def _infer_let_type(stmt, program):
    """Best-effort chico (ver nota de diseño arriba) -- nunca el
    inferidor completo de type_checker.py. Devuelve TypeAnn o None."""
    if stmt.declared_type is not None:
        return stmt.declared_type
    return _infer_expr_type(stmt.expr, program)


def _infer_expr_type(expr, program):
    if isinstance(expr, NumLit):
        return TypeAnn("f64") if isinstance(expr.value, float) else TypeAnn("i32")
    if isinstance(expr, StrLit):
        return TypeAnn("str")
    if isinstance(expr, BoolLit):
        return TypeAnn("bool")
    if isinstance(expr, StructLit):
        return TypeAnn(expr.name)
    if isinstance(expr, Call) and isinstance(expr.callee, Ident):
        return _lookup_return_type(expr.callee.name, program)
    return None


def _lookup_return_type(name, program):
    for item in program.items:
        if isinstance(item, (FnDecl, ExternFnDecl)) and item.name == name:
            return item.return_type
    return None
