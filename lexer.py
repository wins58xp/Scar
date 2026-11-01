"""Lexer para SCAR: convierte texto fuente en una lista de tokens."""

KEYWORDS = {
    "fn", "task", "spawn", "let", "mut", "return", "if", "else", "while",
    "for", "in", "struct", "true", "false", "and", "or", "not",
    "Ok", "Err", "Result", "Chan", "Some", "None", "print",
    "extern", "from", "type", "own", "accepts", "break", "enum", "match", "use",
    "export", "continue",
}
# 'continue': salta a la vuelta siguiente del loop más interno.
# 'break': sale del loop más interno.
# 'export': `export fn` marca una fn que una librería de SCAR (cli.py
# build --lib) deja llamar desde otro lenguaje.
# 'use' (módulos): `use "gui"` al principio de un archivo.
# 'enum' y 'match': tipos con variantes y su análisis por casos.
# 'accepts': cláusula opcional en la firma de una 'task' que declara qué
# tipos de Chan<T> acepta por inyección en runtime (inject_chan() /
# accept_chan()). La firma es información de compilación (ver parse_fn en
# parser.py).
# 'extern'/'from'/'type'/'own': declaraciones FFI,
# `extern "C" fn nombre(...) -> T from "lib"` y `extern type Nombre`.

SYMBOLS = [
    "->", "=>", "==", "!=", "<=", ">=", "..", "?",
    "+", "-", "*", "/", "%", "=", "<", ">", "(", ")", "{", "}", "[", "]",
    ",", ":", ".",
    # Operadores de bits sobre i32. `<<` y `>>` NO son tokens:
    # el parser los arma con dos `<`/`>` pegados, para que `Vec<Vec<i32>>`
    # siga cerrando dos genéricos (el problema clásico de C++).
    "&", "|", "^",
]
# SCAR no usa ';': cada sentencia va en su línea. Es una decisión del lenguaje:
# un solo estilo, y el ';' queda libre para un
# significado futuro (permitirlo después no rompe nada; quitarlo sí). Un ';' da
# un error que dice eso, no "carácter inesperado".


class Token:
    def __init__(self, kind, value, line, col=None):
        self.kind = kind    # 'kw' | 'id' | 'num' | 'str' | 'sym' | 'eof'
        self.value = value
        self.line = line
        self.col = col      # columna 1-based donde empieza el token (None si no se pudo derivar)

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, line={self.line}, col={self.col})"


class LexError(Exception):
    def __init__(self, msg, line=None, col=None):
        super().__init__(msg)
        self.line = line
        self.col = col


def _es_digito(ch):
    """Un dígito 0-9. str.isdigit() también acepta '²' o '٣', y int('²')
    revienta con un ValueError de Python en vez de un error de SCAR."""
    return "0" <= ch <= "9"


def _corto(texto):
    """Un literal para un mensaje de error: uno de 300 dígitos no se copia
    entero."""
    return texto if len(texto) <= 40 else texto[:20] + "..." + texto[-12:]


# "Trojan Source" (CVE-2021-42574): los caracteres de control bidireccional de Unicode son invisibles y reordenan
# cómo se ve el texto en el editor: un comentario o un string puede esconder
# código que el compilador sí ve. No tienen ningún uso legítimo en un .scar.
_BIDI = {
    "\u202a": "LRE", "\u202b": "RLE", "\u202c": "PDF", "\u202d": "LRO", "\u202e": "RLO",
    "\u2066": "LRI", "\u2067": "RLI", "\u2068": "FSI", "\u2069": "PDI",
    "\u200e": "LRM", "\u200f": "RLM", "\u061c": "ALM",
}


def _revisar_bidi(src):
    for i, ch in enumerate(src):
        if ch in _BIDI:
            linea = src.count("\n", 0, i) + 1
            col = i - (src.rfind("\n", 0, i) + 1) + 1
            raise LexError(
                f"carácter de control bidireccional U+{ord(ch):04X} ({_BIDI[ch]}) en línea {linea}: "
                f"es invisible y cambia cómo se ve el código en el editor (\"Trojan Source\"); borralo",
                linea, col)


def tokenize(src: str):
    if any(ch in src for ch in _BIDI):
        _revisar_bidi(src)
    tokens = []
    i = 0
    line = 1
    line_start = 0  # índice en src donde empieza la línea actual
    n = len(src)

    def col_at(pos):
        return pos - line_start + 1

    while i < n:
        c = src[i]

        if c == "\n":
            line += 1
            i += 1
            line_start = i
            continue
        if c in " \t\r":
            i += 1
            continue
        if c == "#":  # comentario de línea
            while i < n and src[i] != "\n":
                i += 1
            continue

        if c.isalpha() or c == "_":
            start = i
            start_col = col_at(i)
            while i < n and (src[i].isalnum() or src[i] == "_"):
                i += 1
            word = src[start:i]
            kind = "kw" if word in KEYWORDS else "id"
            tokens.append(Token(kind, word, line, start_col))
            continue

        if _es_digito(c):
            start = i
            start_col = col_at(i)
            is_float = False
            while i < n and _es_digito(src[i]):
                i += 1
            # Un solo punto decimal, y solo si viene seguido de un dígito.
            # Sin este chequeo, "0..10" se leía entero como un número inválido
            # en vez de num(0) + sym('..') + num(10) — ver GRAMMAR.md §6.1.
            if i < n and src[i] == "." and i + 1 < n and _es_digito(src[i + 1]):
                is_float = True
                i += 1
                while i < n and _es_digito(src[i]):
                    i += 1
            # Exponente, como en Python, Rust y C (`1e-5`, `2.5E3`,
            # `6.02e+23`). Un número con exponente es siempre f64, aunque no
            # tenga punto (`1e3` vale 1000.0), igual que en esos lenguajes.
            # Antes, `1e-5` se leía como num(1) id(e) - num(5) y el error
            # era "variable no declarada: 'e'", que no decía qué pasó.
            if i < n and src[i] in "eE":
                j = i + 1
                if j < n and src[j] in "+-":
                    j += 1
                if j < n and _es_digito(src[j]):
                    is_float = True
                    i = j
                    while i < n and _es_digito(src[i]):
                        i += 1
                else:
                    # `1e`, `1e+`, `2.5ex`: lo que viene pegado al número
                    # empieza un exponente que no termina. Se señala el
                    # literal entero, con lo que tiene pegado.
                    k = j
                    while k < n and (src[k].isalnum() or src[k] == "_"):
                        k += 1
                    raise LexError(
                        f"exponente mal formado '{_corto(src[start:k])}' en línea {line}: "
                        f"después de la 'e' tiene que venir un entero, con signo "
                        f"opcional, por ejemplo 1e5, 2.5e-3 o 6.02E+23",
                        line, start_col)
            if i < n and (src[i].isalnum() or src[i] == "_"):
                # `3abc`, `1e-5x`, `2²`: un número con letras (o dígitos que
                # no son 0-9) pegados. Antes se partía en dos tokens y, como
                # no hace falta separador entre sentencias, `let x = 1e-5x`
                # se aceptaba como `let x = 1e-5` seguido de la sentencia `x`.
                k = i
                while k < n and (src[k].isalnum() or src[k] == "_"):
                    k += 1
                raise LexError(
                    f"número mal formado '{_corto(src[start:k])}' en línea {line}: un "
                    f"número no puede llevar letras ni '_' pegados (para "
                    f"multiplicar se escribe 3 * x; un exponente, 1e-5)",
                    line, start_col)
            text = src[start:i]
            if not is_float and len(text.lstrip("0")) > 19:
                # Un entero de miles de dígitos
                # hacía reventar int() de Python. Ningún entero de SCAR pasa
                # de 19 dígitos (i64).
                raise LexError(
                    f"literal entero demasiado grande '{_corto(text)}' en línea {line}: "
                    f"no entra en un i64 (el máximo es 9223372036854775807)",
                    line, start_col)
            value = float(text) if is_float else int(text)
            if is_float:
                # float() de Python redondea al double más cercano, igual que
                # el compilador de C con el literal que emite el codegen
                # (repr del valor, que vuelve exacto al mismo double). Lo que
                # no tiene double representable no se acepta en silencio: el
                # intérprete tendría inf (o 0.0) y el C generado no
                # compilaría ("inf" no es un literal de C).
                if value == float("inf"):
                    raise LexError(
                        f"literal f64 fuera de rango '{_corto(text)}' en línea {line}: no "
                        f"entra en un f64 (el máximo es 1.7976931348623157e308)",
                        line, start_col)
                if value == 0.0 and any(ch in "123456789" for ch in text.lower().split("e")[0]):
                    raise LexError(
                        f"literal f64 demasiado chico '{_corto(text)}' en línea {line}: "
                        f"se redondea a 0.0 (el menor f64 positivo es 5e-324)",
                        line, start_col)
            tokens.append(Token("num", value, line, start_col))
            continue

        if c == '"':
            start_line, start_col = line, col_at(i)
            i += 1
            chars = []
            while i < n and src[i] != '"':
                ch = src[i]
                if ch == "\n":
                    line += 1
                    chars.append(ch)
                    i += 1
                    line_start = i
                elif ch == "\\":
                    if i + 1 >= n:
                        raise LexError(f"string sin cerrar en línea {line}", line, col_at(i))
                    esc = src[i + 1]
                    if esc == '"':
                        chars.append('"')
                    elif esc == "\\":
                        chars.append("\\")
                    elif esc == "n":
                        chars.append("\n")
                    elif esc == "t":
                        chars.append("\t")
                    elif esc == "r":
                        chars.append("\r")
                    elif esc == "0":
                        # Un str de SCAR no puede
                        # llevar el carácter nulo. En el nativo el texto se
                        # cortaba ahí (len("ab\0cd") daba 2 en vez de 5):
                        # el mismo programa decía cosas distintas según el backend.
                        raise LexError(
                            f"un string no puede tener el carácter nulo (\\0) en línea {line}",
                            line, col_at(i))
                    else:
                        raise LexError(
                            f"secuencia de escape no soportada '\\{esc}' en línea {line}",
                            line, col_at(i),
                        )
                    i += 2
                else:
                    if ch == "\0":
                        raise LexError(f"un string no puede tener el carácter nulo en línea {line}", line, col_at(i))
                    chars.append(ch)
                    i += 1
            if i >= n:
                raise LexError(f"string sin cerrar en línea {start_line}", start_line, start_col)
            text = "".join(chars)
            i += 1  # saltar comilla final
            tokens.append(Token("str", text, start_line, start_col))
            continue

        matched = False
        for sym in SYMBOLS:
            if src.startswith(sym, i):
                tokens.append(Token("sym", sym, line, col_at(i)))
                i += len(sym)
                matched = True
                break
        if matched:
            continue

        if c == ";":
            raise LexError(
                f"en SCAR no se usa ';' (línea {line}): cada sentencia va en su propia "
                "línea. Saca el ';' y, si había algo después, pásalo a la línea siguiente",
                line, col_at(i))
        raise LexError(f"carácter inesperado {c!r} en línea {line}", line, col_at(i))

    tokens.append(Token("eof", None, line, col_at(i)))
    return tokens
