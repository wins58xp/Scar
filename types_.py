"""Representación de tipos para el verificador estático de SCAR."""

PRIMITIVE_NAMES = {"i32", "i64", "f64", "str", "bool", "void"}

# Marcas de los tipos del lenguaje que no son primitivos (TypeAnn.name). Viven
# solo acá: type_checker.py y codegen/ las importan (paso C9).
RESULT = "Result"
OPTION_MARK = "Option"    # lo producen Some/None aunque el usuario no lo escriba
TASK_MARK = "Task"
CHAN_MARK = "Chan"
VEC_MARK = "Vec"          # Vec<T>: genérico por la anotación del let, todo por métodos
MAP_MARK = "Map"          # Map<K,V>: K primitivo; set() transfiere el valor
PIPE_MARK = "Pipe"        # pipe_new(): sus fds por métodos
FILE_MARK = "File"        # file_open(path, mode), mode "r"/"w"/"a"
SOCKET_MARK = "Socket"    # tcp_connect() y Listener.accept()
LISTENER_MARK = "Listener"  # tcp_listen(port): solo accept() y close()
# 'fn(T1, T2) -> U': args = [tipos de parámetro..., tipo de retorno]
FN_MARK = "__Fn"

# Los tipos escalares que cruzan la frontera de una extern fn tal cual. Un str
# cruza como const char*; quién libera lo que C reservó lo decide el backend.
FFI_SUPPORTED_TYPES = {"i32", "i64", "f64", "bool", "str"}


class TypeAnn:
    """Una anotación de tipo tal como aparece en el código fuente: 'i32', 'Point',
    'Result<i32>', 'Chan<i32>', etc. args es una lista de TypeAnn (para genéricos)."""

    def __init__(self, name, args=None):
        self.name = name
        self.args = args or []

    def __eq__(self, other):
        return isinstance(other, TypeAnn) and self.name == other.name and self.args == other.args

    def __hash__(self):
        return hash((self.name, tuple(self.args)))

    def __repr__(self):
        if self.name == FN_MARK and self.args:
            # como lo escribe el usuario (`fn(i32) -> i32`), no el
            # nombre interno (`__Fn<i32, i32>`) que salía en los mensajes
            params = ", ".join(repr(a) for a in self.args[:-1])
            return f"fn({params}) -> {self.args[-1]!r}"
        if self.args:
            inner = ", ".join(repr(a) for a in self.args)
            return f"{self.name}<{inner}>"
        return self.name

    def is_numeric(self):
        return self.name in ("i32", "i64", "f64")

    def is_integer(self):
        return self.name in ("i32", "i64")

    def is_primitive(self):
        return self.name in PRIMITIVE_NAMES

    def is_copy(self):
        # Los tipos primitivos son Copy (se duplican, no se mueven). Todo lo
        # demás (structs de usuario) es no-Copy y se mueve al cruzar spawn.
        # Un valor función (FN_MARK) también es Copy -- es un puntero a
        # código estático del binario, nunca a memoria de una Region, así
        # que no hay nada que mover ni liberar. Verificado ahí que ningún
        # otro mecanismo de ownership (_move_if_needed/TypeEnv) necesita un
        # caso especial adicional para este tipo, a diferencia de 'str'.
        return (self.is_primitive() or self.name == FN_MARK
                or (not self.args and self.name in PARAMS_COPIA))


# Los parámetros de tipo con cota Numeric de la fn que el checker está
# revisando (ver type_checker._check_fn): adentro de `fn f<T: Numeric>`, un T
# siempre es un número, así que se copia como uno (`let p = x` no mueve x).
PARAMS_COPIA = set()

# Tipos primitivos reutilizables
T_I32 = TypeAnn("i32")
T_I64 = TypeAnn("i64")
T_F64 = TypeAnn("f64")
T_STR = TypeAnn("str")
T_BOOL = TypeAnn("bool")
T_VOID = TypeAnn("void")


# ---------------------------------------------------------------------------
# Reglas numéricas, UNA sola fuente para el checker, el intérprete y
# el codegen.
#
# Enteros i32 e i64; desbordar cualquiera de los dos es un panic. Ampliaciones
# implícitas solo si no pierden información: i32 -> i64 e i32 -> f64. i64 -> f64
# pierde precisión por encima de 2**53, así que mezclar i64 con f64 es un error
# de tipo y se convierte a mano con to_f64() / to_i64(). Las conversiones
# explícitas (to_i32 / to_i64 / to_f64) hacen panic si el valor no cabe: nunca
# truncan en silencio un entero.
# ---------------------------------------------------------------------------
I32_MIN, I32_MAX = -2 ** 31, 2 ** 31 - 1
I64_MIN, I64_MAX = -2 ** 63, 2 ** 63 - 1
INT_RANGES = {"i32": (I32_MIN, I32_MAX), "i64": (I64_MIN, I64_MAX)}


def int_literal_type(v):
    """Tipo de un literal entero ya con su signo: i32 si cabe, si no i64; None
    si no cabe en ninguno (error de compilación)."""
    if I32_MIN <= v <= I32_MAX:
        return T_I32
    if I64_MIN <= v <= I64_MAX:
        return T_I64
    return None


def numeric_result(l, r):
    """Tipo de `l op r` (+, -, *, /, %) para dos operandos numéricos concretos.
    None si la mezcla no está permitida (i64 con f64)."""
    names = {l.name, r.name}
    if "f64" in names:
        return None if "i64" in names else T_F64
    if "i64" in names:
        return T_I64
    return T_I32


def numeric_mix_ok(l, r):
    """True si l y r se pueden comparar (misma regla que la aritmética: i64 y
    f64 no se mezclan sin una conversión explícita)."""
    return {l.name, r.name} != {"i64", "f64"}


def mensaje_movida(nombre):
    """El panic de usar una variable que una vuelta anterior del loop
    movió (el mismo texto en el intérprete y en el nativo)."""
    return f"'{nombre}' ya se movió en una vuelta anterior del loop"


def ffi_tipo_ok(ty, structs, extern_types, excluidos=()):
    """True si `ty` puede cruzar la frontera de una extern fn: un tipo de
    FFI_SUPPORTED_TYPES, un `extern type` (sin argumentos), una fn sin captura
    cuyos parámetros y retorno también crucen (el retorno puede ser void), o un
    struct no genérico con todos sus campos i32/i64/f64/bool, por valor (un str
    o un struct anidado de campo no cruza). `structs`: nombre -> {campo: tipo};
    `excluidos`: nombres de `structs` que no cruzan (genéricos, enums). La usan
    el checker y el backend (paso C9)."""
    if ty.name in FFI_SUPPORTED_TYPES:
        return True
    if ty.name == FN_MARK:
        return all(t.name == "void" or ffi_tipo_ok(t, structs, extern_types, excluidos)
                   for t in ty.args)
    if ty.name in structs and not ty.args:
        if ty.name in excluidos:
            return False
        return all(fty.name in ("i32", "i64", "f64", "bool") for fty in structs[ty.name].values())
    return ty.name in extern_types and not ty.args
