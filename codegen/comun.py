"""Lo que comparten los archivos de codegen/ (paso C6): las tablas de tipos y
marcas, BUILTIN_SIGS, CodegenError, los helpers que arman trozos de runtime
según el programa y las funciones sobre el AST que no dependen del estado de
un Codegen. Cada mixin importa de acá lo que usa.
"""

import re

from parser import FieldAccess, Ident, hijos
from types_ import (TypeAnn, T_I32, T_I64, T_F64, T_STR, T_VOID, TASK_MARK, CHAN_MARK, FN_MARK,
                    PIPE_MARK, FILE_MARK, SOCKET_MARK, LISTENER_MARK, VEC_MARK, MAP_MARK,
                    FFI_SUPPORTED_TYPES)

from . import runtime as runtime_c


def literal_c(texto):
    """Un str de SCAR como literal de C, byte por byte igual en el nativo.

    Cada '?' va como \\? para cortar los trigrafos de C (??( ??/ ...), que gcc
    aplica con -std=c11 y cambiaban el texto o rompían el literal (informe de
    seguridad). Los caracteres de control van en octal de 3
    dígitos, así un dígito que venga después no se pega al escape."""
    partes = []
    for ch in texto:
        o = ord(ch)
        if ch == "\\":
            partes.append("\\\\")
        elif ch == '"':
            partes.append('\\"')
        elif ch == "?":
            partes.append("\\?")
        elif ch == "\n":
            partes.append("\\n")
        elif ch == "\t":
            partes.append("\\t")
        elif ch == "\r":
            partes.append("\\r")
        elif o < 0x20 or o == 0x7f:
            partes.append(f"\\{o:03o}")
        else:
            partes.append(ch)
    return '"' + "".join(partes) + '"'


# Una parte de una función partida que puede terminarla con `return`
# devuelve esto cuando no la terminó; la función hace
# `_r = self._parte(...)` / `if _r is not _SIGUE: return _r`. Un objeto propio,
# así ningún valor que el codegen devuelva (None incluido) se confunde con él.
_SIGUE = object()


class CodegenError(Exception):
    pass


_RE_USA_POOL = re.compile(r"\bscar_(?:malloc|free|aprintf|sb_\w+)\s*\(")

# Texto sin tope: scar_aprintf mide primero y reserva lo justo, y
# ScarSb es un texto que crece (para un Vec, que no tiene largo máximo). Nada
# se corta en un buffer fijo. Lo que devuelven se libera con scar_free.
_TEXTO_SIN_TOPE_C = runtime_c.texto("texto_sin_tope")


C_TYPE = {
    "i32": "int32_t",
    "i64": "int64_t",
    "f64": "double",
    "str": "const char*",
    "bool": "bool",
    "void": "void",
}

# Al arrancar main(): que glibc sirva los bloques grandes con brk y no con
# mmap/munmap. munmap toma un lock del kernel compartido por todo el proceso,
# y con varias tareas liberando Vec grandes a la vez ese lock se llevaba la
# mayor parte del tiempo (medido con push/pop de Vec entre varias tareas).
SCAR_MALLOPT_PROLOGUE = (
    "#ifdef __GLIBC__\n"   # mallopt/M_MMAP_* son de glibc; MinGW/otros no los tienen
    "    mallopt(M_MMAP_THRESHOLD, 64 * 1024 * 1024);\n"
    "    mallopt(M_MMAP_MAX, 0);\n"
    "#endif\n"
)

# Prólogo de main() cuando el programa usa rand(): siembra el hilo de main
# (con SCAR_SEED si está, si no con la hora); las tasks derivan su semilla de
# la de su madre. Ver _rand_runtime_c.
SCAR_RAND_SEED_LINE = "    scar_rand_arranque();\n"


# Builtins de libm: nombre en SCAR -> función de C (todas en <math.h>).
_LIBM_C = {"sin": "sin", "cos": "cos", "tan": "tan", "atan": "atan", "exp": "exp",
           "ln": "log", "log10": "log10", "pow": "pow", "floor": "floor", "abs": "fabs"}


def panic_c(has_tasks, propio=False):
    """La función de C que hace un panic: con tasks, scar_panic (cascada por el
    TaskContext); sin tasks, scar_panic_main (suelta las vivas y exit(1)).
    `propio`: la variante que copia el mensaje del usuario."""
    base = "scar_panic" if has_tasks else "scar_panic_main"
    return base + "_propio" if propio else base


def _chr_ord_helpers_c(has_tasks):
    """chr(n)/ord(s): código Unicode <-> str de un carácter (UTF-8)."""
    panic = panic_c(has_tasks)
    return runtime_c.texto(
        "chr_ord",
        PANIC=panic,
    )


def _to_i32_helper_c(has_tasks):
    """to_i32(x): trunca hacia cero. Antes revisa el rango, porque convertir a
    int32_t un double que no entra (o NaN) es comportamiento indefinido en C;
    NaN falla las dos comparaciones."""
    panic = panic_c(has_tasks)
    return (
        "static inline int32_t scar_to_i32(double x) {\n"
        "    if (!(x > -2147483649.0 && x < 2147483648.0)) " + panic
        + "(\"to_i32: NaN o fuera del rango de i32\");\n"
        "    return (int32_t)x;\n"
        "}\n"
    )


def _i64_helpers_c(has_tasks):
    """El runtime de i64, con las mismas reglas y los mismos textos
    que i32 y que el intérprete: desbordar, dividir por cero y correr fuera de
    0..63 son un panic, igual que una conversión que no cabe (to_i32 de un i64,
    to_i64 de un f64)."""
    panic = panic_c(has_tasks)
    return runtime_c.texto(
        "i64",
        PANIC=panic,
    )


def _abs_min_max_helpers_c(has_tasks):
    """abs/min/max, iguales al intérprete (_abs_min_max). abs de un entero es
    exacto, y el del mínimo (que no tiene positivo) es un panic. min/max
    devuelven el primero salvo que el segundo sea menor (mayor): con NaN, el
    primero. Como son funciones, cada argumento se evalúa una sola vez."""
    panic = panic_c(has_tasks)
    s = ""
    for t, ct, lo in (("i32", "int32_t", "INT32_MIN"), ("i64", "int64_t", "INT64_MIN")):
        s += (
            f"static inline {ct} scar_abs_{t}({ct} x) {{\n"
            f"    if (x == {lo}) " + panic + f"(\"abs: %lld no tiene valor absoluto en {t}\", (long long)x);\n"
            "    return x < 0 ? -x : x;\n"
            "}\n"
        )
    for t, ct in (("i32", "int32_t"), ("i64", "int64_t"), ("f64", "double")):
        s += (
            f"static inline {ct} scar_min_{t}({ct} a, {ct} b) {{ return (b < a) ? b : a; }}\n"
            f"static inline {ct} scar_max_{t}({ct} a, {ct} b) {{ return (b > a) ? b : a; }}\n"
        )
    return s


def _shift_helpers_c(con_chequeo, has_tasks):
    """Corrimientos de bits, con panic fuera de rango (ver Codegen._gen_bits)."""
    panic = panic_c(has_tasks)
    s = (
        "// >> aritmético sin depender del compilador (correr un negativo a la\n"
        "// derecha es 'implementation-defined' en C)\n"
        "static inline int32_t scar_sar_k(int32_t a, int n) {\n"
        "    return a < 0 ? ~(~a >> n) : a >> n;\n"
        "}\n"
    )
    if con_chequeo:
        s += (
            # la cantidad es int64_t: puede venir de un i64, y convertirla a
            # int32_t la truncaría antes de revisar el rango
            runtime_c.texto(
            "shift",
            PANIC=panic,
        )
        )
    return s


def _rand_runtime_c(needs_rand, has_tasks):
    """El generador de rand(), idéntico al del intérprete (_ScarRand):
    xorshift64 con estado por hilo, sembrado con splitmix64. La
    semilla de una task sale de la de su madre y del número de spawn de la
    madre, calculada en el hilo de la madre: no depende de qué hilo corre
    primero. seed(n) reinicia la semilla del hilo actual; SCAR_SEED fija la de
    main. Sin rand() en el programa no se emite nada (las macros quedan
    vacías)."""
    if not needs_rand:
        if not has_tasks:
            return ""
        return ("#define SCAR_RAND_SEMILLA_HIJA() 0\n"
                "#define SCAR_RAND_HILO(s) ((void)0)\n")
    return runtime_c.texto("rand")

BIN_OPS = {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=",
           "&", "|", "^", "<<", ">>"}  # bits: ver _gen_bits
BITS_OPS = {"&", "|", "^", "<<", ">>"}
COMPARISON_OPS = {"==", "!=", "<", ">", "<=", ">="}
BOOL_OPS = {"and", "or"}
C_BOOL_OP = {"and": "&&", "or": "||"}
GENERIC_NAMES = {"Result", "Option"}

# Marcas de los tipos del lenguaje que no son primitivos: viven en types_.py.
# Pipe, File, Socket y Listener no son genéricos, pero File y Socket pueden ser
# el T de un Result (ver _generic_c_type). Vec<T> y Map<K,V> se monomorfizan
# por tipo (ver _vec_c_type, _map_c_type).

# Builtins: nombre SCAR -> (tipos de parámetros, tipo de retorno). El checker
# ya validó aridad y tipos: acá los tipos de parámetro solo dan el tipo
# esperado de cada argumento por posición, y el de retorno, el de la llamada.
BUILTIN_SIGS = {
    "sqrt": ([T_F64], T_F64),
    # rand(): f64 en [0.0, 1.0)
    "rand": ([], T_F64),
    # seed(n): fija la semilla de rand() del hilo actual
    "seed": ([T_I32], T_VOID),
    # libm
    "sin": ([T_F64], T_F64),
    "cos": ([T_F64], T_F64),
    "tan": ([T_F64], T_F64),
    "atan": ([T_F64], T_F64),
    "exp": ([T_F64], T_F64),
    "ln": ([T_F64], T_F64),
    "log10": ([T_F64], T_F64),
    "pow": ([T_F64, T_F64], T_F64),
    "floor": ([T_F64], T_F64),
    "abs": ([T_F64], T_F64),
    # abs/min/max: el tipo real sale de los argumentos (ver infer/Call)
    "min": ([T_F64, T_F64], T_F64),
    "max": ([T_F64, T_F64], T_F64),
    # to_i32/to_f64
    "to_i32": ([T_F64], T_I32),
    "to_i64": ([T_F64], T_I64),
    "to_f64": ([T_I32], T_F64),
    "chr": ([T_I32], T_STR),
    "a_texto": ([T_STR], T_STR),  # ver el sitio de Call
    "ord": ([T_STR], T_I32),
    # now(): reloj monotónico en segundos, para medir duraciones
    "now": ([], T_F64),
    # arg(i): el str es prestado de argv (vive todo el proceso, como un
    # literal): no tiene dueño y nada lo libera.
    "arg": ([T_I32], TypeAnn("Option", [T_STR])),
    "len": ([T_STR], T_I32),
    "int": ([T_STR], TypeAnn("Result", [T_I32])),
    "int64": ([T_STR], TypeAnn("Result", [T_I64])),
    "sleep": ([T_F64], T_VOID),
    "panic": ([T_STR], T_VOID),  # ver el sitio de Call
    # chan_new()/vec_new() aceptan una capacidad opcional (0 = sin límite). Sin
    # anotación en el `let` que las recibe, T es i32, como en el checker; con
    # anotación (let v: Vec<T> = vec_new()), ver marca_new_generico.
    "chan_new": ([T_I32], TypeAnn(CHAN_MARK, [T_I32])),
    "pipe_new": ([], TypeAnn(PIPE_MARK)),
    "read_pipe": ([T_I32], TypeAnn("Result", [T_STR])),
    # file_open(), tcp_connect() y tcp_listen() no son genéricas: no necesitan
    # anotación en el `let`.
    "file_open": ([T_STR, T_STR], TypeAnn("Result", [TypeAnn(FILE_MARK)])),
    "tcp_connect": ([T_STR, T_I32], TypeAnn("Result", [TypeAnn(SOCKET_MARK)])),
    "tcp_listen": ([T_I32], TypeAnn("Result", [TypeAnn(LISTENER_MARK)])),
    "vec_new": ([T_I32], TypeAnn(VEC_MARK, [T_I32])),
    # map_new(): sin anotación, Map<i32,i32> (como en el checker); con
    # anotación, ver marca_new_generico.
    "map_new": ([], TypeAnn(MAP_MARK, [T_I32, T_I32])),
    # inject_chan(handle, chan): los tipos de parámetro son solo de
    # posición (el handle trae su task y el Chan su T); lo que importa es el
    # retorno, Result<()>, para que `let r = inject_chan(...)` infiera bien.
    "inject_chan": ([TypeAnn(TASK_MARK), TypeAnn(CHAN_MARK, [T_I32])], TypeAnn("Result", [T_VOID])),
}


class _ShadowSubBlock:
    """Un bloque falso (solo `.stmts`) con la cola de un bloque a partir de un
    `let` que sombrea a otro. Sirve para pasarle esa cola a
    _block_is_straight_line/_block_always_returns, que solo miran `.stmts`,
    cuando gen_block le abre un `{}` propio. No es un nodo del AST."""

    __slots__ = ("stmts",)

    def __init__(self, stmts):
        self.stmts = stmts


def _vivos_runtime_c():
    """El registro de dueñas vivas, que un panic recorre para soltar lo que
    estaba vivo. Vive en ScarHilo (tls.c): por hilo con tasks, y con el
    planificador el de cada tarea."""
    return runtime_c.texto("vivos")


# scar_hilo no es static: el asm la nombra, y con -flto una variable static que
# solo se usa desde un asm se cae (undefined reference); 'used' la sostiene
_TLS_X86 = (
    "__thread ScarHilo scar_hilo __attribute__((used, visibility(\"hidden\")));\n"
    "static inline ScarHilo *scar_tls(void) {\n"
    "    ScarHilo *p;\n"
    "    __asm__ volatile(\"movq %%fs:0, %0\\n\\tleaq scar_hilo@tpoff(%0), %0\" : \"=r\"(p));\n"
    "    return p;\n"
    "}"
)
_TLS_ARM64 = (
    "__thread ScarHilo scar_hilo __attribute__((used, visibility(\"hidden\")));\n"
    "static inline ScarHilo *scar_tls(void) {\n"
    "    ScarHilo *p;\n"
    "    __asm__ volatile(\"mrs %0, tpidr_el0\\n\\tadd %0, %0, #:tprel_hi12:scar_hilo, lsl #12\\n\\t\"\n"
    "                     \"add %0, %0, #:tprel_lo12_nc:scar_hilo\" : \"=r\"(p));\n"
    "    return p;\n"
    "}"
)
# en una librería (.so) no hay modelo local-exec, y en otras arquitecturas no
# hay asm: una función que no se inlinea, con una barrera para que el
# compilador no la tome por pura y junte dos llamadas
_TLS_LENTO = (
    "static __thread ScarHilo scar_hilo;\n"
    "__attribute__((noinline)) static ScarHilo *scar_tls(void) {\n"
    "    ScarHilo *p = &scar_hilo;\n"
    "    __asm__ volatile(\"\" : \"+r\"(p));\n"
    "    return p;\n"
    "}"
)


# Capa portable de salto no-local del guardián de las extern fn: en POSIX
# sigsetjmp/siglongjmp (preservan la máscara de señales); en Windows (MinGW) no
# existen, se cae a setjmp/longjmp.
_GUARD_TIPOS_C = (
    "#include <setjmp.h>\n"
    "#ifdef _WIN32\n"
    "typedef jmp_buf scar_sig_jmp_buf;\n"
    "#define SCAR_SIGSETJMP(env) setjmp(env)\n"
    "#define SCAR_SIGLONGJMP(env, v) longjmp((env), (v))\n"
    "#else\n"
    "typedef sigjmp_buf scar_sig_jmp_buf;\n"
    "#define SCAR_SIGSETJMP(env) sigsetjmp((env), 1)\n"
    "#define SCAR_SIGLONGJMP(env, v) siglongjmp((env), (v))\n"
    "#endif"
)


def _tls_runtime_c(por_hilo, libreria, con_guard):
    """ScarHilo (tls.c) y scar_tls(): sin hilos, una variable común. El
    sigjmp_buf del guardián de las extern fn solo cuando hay extern fn
    (sigjmp_buf pide _GNU_SOURCE, que sin tareas ni extern no se define)."""
    if not por_hilo:
        tls = "static ScarHilo scar_hilo;\n#define scar_tls() (&scar_hilo)"
    elif libreria:
        tls = _TLS_LENTO
    else:
        # (en Windows no hay planificador ni TLS por %fs: la variante común)
        tls = ("#if defined(__x86_64__) && !defined(_WIN32)\n" + _TLS_X86
               + "\n#elif defined(__aarch64__) && !defined(_WIN32) && !defined(__APPLE__)\n"
               + _TLS_ARM64 + "\n#else\n" + _TLS_LENTO + "\n#endif")
    return runtime_c.texto("tls", TLS=tls,
                           GUARD_TIPOS=_GUARD_TIPOS_C if con_guard else "",
                           GUARD_ENV="    scar_sig_jmp_buf guard_env;" if con_guard else "")


_PANIC_MAIN_C = runtime_c.texto("panic_main")


# Nombres que una export fn no puede tener: el símbolo de C que exporta la
# librería chocaría con C, con la libc o con el runtime.
_C_RESERVADOS_EXPORT = frozenset("""
auto break case char const continue default do double else enum extern float
goto if inline int long register restrict return short signed sizeof static
struct switch typedef union unsigned void volatile while bool true false
NULL EOF stdin stdout stderr errno FILE main
printf fprintf sprintf snprintf vprintf puts putchar fputs fwrite fread fopen
fclose fflush fgets getline scanf perror remove rename tmpfile
malloc calloc realloc free exit abort atexit atoi atol strtol strtod qsort
bsearch abs labs rand srand getenv system
strlen strcmp strncmp strcpy strncpy strcat strdup strchr strstr memcpy
memmove memset memcmp strerror
sin cos tan asin acos atan atan2 exp log log2 log10 pow sqrt floor ceil
round fabs fmod hypot
read write close open pipe fork dup dup2 select poll kill signal raise
sleep usleep nanosleep socket bind listen accept connect send recv
setjmp longjmp
""".split())


def _vivos_truncar_returns(line):
    """Antepone `scar_nvivos = __scar_vbase;` a cada `return` de una línea de C
    (fuera de literales de cadena o carácter), para dar de baja las vivas de la
    función al salir."""
    if "return" not in line:
        return line
    out = []
    i, n = 0, len(line)
    cambio = False
    while i < n:
        ch = line[i]
        if ch in "\"'":
            j = i + 1
            while j < n and line[j] != ch:
                j += 2 if line[j] == "\\" else 1
            out.append(line[i:j + 1])
            i = j + 1
            continue
        if line.startswith("return", i) and (i == 0 or not (line[i - 1].isalnum() or line[i - 1] == "_")) \
                and (i + 6 >= n or not (line[i + 6].isalnum() or line[i + 6] == "_")):
            j = i
            while j < n and line[j] != ";":
                if line[j] in "\"'":
                    q = line[j]
                    j += 1
                    while j < n and line[j] != q:
                        j += 2 if line[j] == "\\" else 1
                j += 1
            if j >= n:
                out.append(line[i:])
                break
            out.append("{ scar_nvivos = __scar_vbase; " + line[i:j + 1] + " }")
            cambio = True
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out) if cambio else line


def _expr_mentions_name(node, name):
    """True si `node` (una expresión o cualquier subárbol) lee la variable
    `name`. Se usa con el lado derecho de un `let` que sombrea."""
    if isinstance(node, Ident):
        return node.name == name
    return any(_expr_mentions_name(h, name) for h in hijos(node))


def _field_path(node):
    """`c.data.x` -> ("c", "data", "x"); None si la raíz no es una variable."""
    parts = []
    while isinstance(node, FieldAccess):
        parts.append(node.field)
        node = node.obj
    if not isinstance(node, Ident):
        return None
    parts.append(node.name)
    return tuple(reversed(parts))


def _expr_mentions_path(node, path):
    """True si `node` usa el campo `path` o algo que lo contiene o que está
    dentro de él (el struct entero, un subcampo). Un campo hermano (`c.nombre`
    frente a `c.data`) no cuenta."""
    if isinstance(node, FieldAccess):
        p = _field_path(node)
        if p is not None:
            n = min(len(p), len(path))
            return p[:n] == path[:n]
        return _expr_mentions_path(node.obj, path)
    if isinstance(node, Ident):
        return node.name == path[0]
    return any(_expr_mentions_path(h, path) for h in hijos(node))


# s[i] y len(s) no recorren el str entero en cada llamada:
# cada hilo recuerda los dos últimos str que midió (dos, para recorrer
# dos a la vez) con su largo en caracteres, si es todo ASCII y el último
# carácter visitado. Vale mientras esa dirección tenga ese texto: un str
# no cambia mientras vive, así que solo deja de valer al liberarse
# (scar_free) o al salir del hilo (send, spawn, memoria de quien llama a
# una librería). Ahí se olvida (las marcas /*SCAR_STRC*/).
# El contexto raíz de main (y de cada llamada a una export fn): las mismas
# líneas en los dos lugares.
def _raiz_inicio_c(nombre):
    return runtime_c.texto(
        "raiz_inicio",
        NOMBRE=str(nombre),
    )


# cancela y espera a las hijas sin join, y suelta la raíz
def _raiz_fin_c(pad="    "):
    return runtime_c.texto(
        "raiz_fin",
        PAD=str(pad),
    )


_STRC_C = (
    "// Los dos últimos str medidos en este hilo: scar_strc y scar_strc_ult, en\n"
    "// ScarHilo (tls.c); ver scar_strc_medir\n"
    "#define SCAR_HAY_STRC 1"
)

_RE_MARCA_STRC = re.compile(r"^([ \t]*)/\*SCAR_STRC(_FREE)?\*/\n", re.M)


def _marcas_strc(c, usa):
    """Donde un str puede dejar de valer, se olvida el recuerdo (en
    scar_free, solo si lo que se libera es el recordado); si el programa no
    usa s[i] ni len(s), la marca desaparece."""
    if not usa:
        return _RE_MARCA_STRC.sub("", c)

    def poner(m):
        if m.group(2):
            return (f"{m.group(1)}if (p == scar_strc[0].p) scar_strc[0].p = NULL;\n"
                    f"{m.group(1)}if (p == scar_strc[1].p) scar_strc[1].p = NULL;\n")
        return f"{m.group(1)}scar_strc[0].p = scar_strc[1].p = NULL;\n"
    return _RE_MARCA_STRC.sub(poner, c)
