"""
Autocompletado de campos/métodos del LSP al escribir `foo.` (o `foo.bar.`).

Diseño (continúa el de scope_resolver.py -- misma filosofía: PURO, sin
tocar type_checker.py, tolerante a un archivo a medio escribir):

  - `resolve_dot_completions(program, symbols, chain)` recibe la cadena
    de identificadores YA separada por punto (ej. `["foo", "bar"]` para
    lo que el usuario escribió como `foo.bar.`) y la lista de Symbol
    visibles en ese punto (la misma que ya devuelve
    `scope_resolver.resolve_scope` -- se reusa tal cual, no se duplica
    la resolución de scope). No parsea texto ni conoce nada de LSP: el
    llamador (lsp_server.py) es quien
    extrae `chain` del buffer crudo con una regex chica, porque en el
    momento en que el usuario está escribiendo `foo.` el archivo casi
    siempre tiene un error de sintaxis (falta terminar la línea) y no
    se puede volver a parsear -- por eso `chain` viene del texto tal
    cual está tipeado, no de un nodo `FieldAccess` real del AST.
  - Resolución de tipo encadenado: el primer elemento de `chain` se
    busca en `symbols` (variable local o parámetro); cada elemento
    siguiente se resuelve como CAMPO de struct del tipo acumulado hasta
    ahí (nunca como método -- no se puede seguir encadenando `.` sobre
    lo que devuelve un método sin re-parsear la expresión completa,
    ver huecos más abajo). Si en cualquier paso
    el tipo no se puede resolver (variable desconocida, no es un
    struct, el campo no existe), se devuelve `[]` -- mejor no ofrecer
    nada que ofrecer algo incorrecto.
  - Con el tipo final ya resuelto: si es un struct declarado en este
    archivo, se ofrecen sus campos (kind "field"); si es uno de los
    tipos con métodos fijos del lenguaje (Vec/Map/Chan/Task/Pipe/File/
    Socket/Listener/str -- la misma tabla que ya usa
    `type_checker.py._infer` en el bloque de `MethodCall`, sección
    "if obj_ty.name == VEC_MARK:" etc.), se ofrecen esos métodos (kind
    "method"). Para un primitivo (i32/f64/bool) o un tipo que no se
    pudo resolver, `[]`.

Huecos conocidos, a propósito:
  - Bases que no son un Ident simple, ej. `foo().bar.` (resultado de
    una llamada) o `v.get(0).campo` (resultado de un método) -- solo se
    resuelve una cadena de FieldAccess sobre una variable, igual que
    `type_checker.py._lvalue_root_name` hace del lado del checker.
  - Structs con parámetros de tipo (`struct Foo<T>`): los campos se
    devuelven con el TypeAnn crudo tal como está declarado (con 'T'
    sin sustituir) -- no se intenta resolver el T concreto de esta
    instancia, a diferencia de `_substitute_type_params` en el checker.
"""
import re

from parser import StructDecl

# Misma tabla de métodos por marca de tipo que type_checker.py usa en el
# bloque de MethodCall (_infer) -- copiada a mano en vez de importada
# porque ahí está mezclada con la lógica de validación de argumentos,
# no expuesta como una tabla reusable. Si esa lista cambia en
# type_checker.py, hay que actualizar esta también (documentado acá
# para que quien la toque sepa que tiene un espejo).
BUILTIN_METHODS = {
    "Task": ["join"],
    "Chan": ["send", "recv", "try_recv", "close", "sender", "receiver"],
    "Pipe": ["read_fd", "write_fd"],
    "File": ["read_all", "read_bytes", "write", "write_bytes", "close"],
    "Socket": ["read", "read_bytes", "write", "write_bytes", "close"],
    "Listener": ["accept", "close"],
    "Vec": ["push", "get", "pop", "set", "replace", "len"],
    "Map": ["set", "get", "remove", "len"],
    "str": ["len", "contains", "starts_with", "ends_with"],
}

# Al final de una cadena `foo.bar.` que el usuario está escribiendo, lo
# que interesa es el texto ANTES del último punto (chain) -- lo que
# venga después del punto (parcial, ej. la 'v' de 'foo.val') se ignora
# acá a propósito: el editor ya filtra la lista por lo tecleado, y
# tratar de acotar la lista nosotros mismos solo duplicaría ese trabajo
# con peor información (no sabemos dónde el editor considera que
# termina la palabra parcial).
_DOT_CHAIN_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\.[A-Za-z0-9_]*$"
)


def extract_dot_chain(line_text_before_cursor):
    """Dado el texto de la línea actual HASTA el cursor (sin incluirlo a
    él), devuelve la lista de identificadores de la cadena antes del
    último punto (ej. `["foo", "bar"]` para `"  x = foo.bar.": None`
    truncado en `"  x = foo.bar."`), o `None` si el cursor no está
    justo después de un punto de una cadena de identificadores (ej. en
    medio de una palabra clave, un string, o a nivel de módulo)."""
    m = _DOT_CHAIN_RE.search(line_text_before_cursor)
    if m is None:
        return None
    return m.group(1).split(".")


def _struct_field_map(program):
    """name del struct -> dict(nombre_campo -> TypeAnn), para los structs
    declarados en `program`. Recalculado en cada llamada a propósito
    (mismo espíritu que scope_resolver: sin caché, el AST puede haber
    cambiado desde la última vez -- el archivo se sigue editando)."""
    return {
        item.name: dict(item.fields)
        for item in program.items
        # un enum (bajado a struct con tag) no tiene campos para el
        # usuario; sus datos se leen con match
        if isinstance(item, StructDecl) and not getattr(item, "enum_variantes", None)
    }


def resolve_dot_completions(program, symbols, chain):
    """Ver docstring del módulo. Devuelve una lista de (nombre, kind)
    con kind en {"field", "method"}; [] si no se pudo resolver nada."""
    if not chain or program is None:
        return []

    base = chain[0]
    ty = None
    for sym in symbols:
        if sym.name == base:
            ty = sym.type_ann
            break
    if ty is None:
        return []

    struct_fields = _struct_field_map(program)
    for field_name in chain[1:]:
        if ty.name not in struct_fields:
            return []
        fields = struct_fields[ty.name]
        if field_name not in fields:
            return []
        ty = fields[field_name]

    if ty.name in struct_fields:
        return [(name, "field") for name in struct_fields[ty.name]]
    if ty.name in BUILTIN_METHODS:
        return [(name, "method") for name in BUILTIN_METHODS[ty.name]]
    return []
