"""lib/config contra configparser y tomllib de Python.

    python3 pruebas/test_config_python.py            (SCAR_SEMILLA=n para otra)

Python inventa archivos INI y TOML (bien armados, estropeados a mano y unos cuantos casos
difíciles escritos a mano) y líneas "clave valor", y los escribe en casos.json.
pruebas/config_python.scar los lee con lib/config y escribe lo que sacó, y acá se compara:

  - INI: el mismo error o el mismo árbol que RawConfigParser().read_string (secciones, claves
    en minúsculas, valores en varias líneas, [DEFAULT]); ini_texto, ini_tiene, ini_entero,
    ini_booleano, ini_decimal e ini_secciones contra get, has_option, int(), BOOLEAN_STATES
    y float(); y escribir_ini igual, letra por letra, a RawConfigParser.write.
  - TOML: el mismo error, o el mismo árbol (con el mismo orden de claves, enteros, flotantes
    y textos) que tomllib.loads. Lo único que se deja pasar es lo que lib/config no acepta
    y dice (fechas y horas, enteros de más de 63 bits en hexadecimal, \\u0000). Lo que escribe
    escribir_toml lo lee tomllib con el mismo resultado y lo lee lib/config con el mismo árbol.
  - líneas: leer_lineas, escribir_lineas, ultima, todas y campo contra su definición escrita en
    Python (esta parte no es de ningún módulo: es el formato de sismografo_vivo.conf).

Si Python no tiene tomllib (antes de 3.11) se omite.
"""

import configparser
import io
import json
import math
import os
import random
import re
import string
import subprocess
import sys
import tempfile

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Textos al azar
# ---------------------------------------------------------------------------

EXTRA = ["ñ", "Ñ", "é", "É", "á", "ü", "€", "😀", "中", "ß", "\u00a0", "\u2003"]
BARE = string.ascii_letters + string.digits + "-_"


def palabra(rng, extras=True, n=None):
    pool = string.ascii_letters + string.digits + "-_" + ("" if not extras else "ñÑéÉ€")
    return "".join(rng.choice(pool) for _ in range(n or rng.randint(1, 7)))


def basura(rng, n=None, extra=""):
    """Texto de una línea con signos, espacios y letras raras (sin saltos de línea)."""
    pool = list(string.ascii_letters + string.digits + " .,:;=#[]{}()-_+*/!?@%&'\"") + EXTRA + list(extra)
    return "".join(rng.choice(pool) for _ in range(n if n is not None else rng.randint(0, 14)))


def cps(s):
    return "_" if s == "" else ",".join(str(ord(c)) for c in s)


def de_cps(s):
    return "" if s == "_" else "".join(chr(int(x)) for x in s.split(","))


# ---------------------------------------------------------------------------
# TOML: documentos al azar
# ---------------------------------------------------------------------------

CTRL = [chr(i) for i in range(32) if i not in (9, 10)] + [chr(127)]


def esc_basica(s, rng, multi=False):
    r = []
    for c in s:
        o = ord(c)
        if c == '"':
            r.append('\\"')
        elif c == "\\":
            r.append("\\\\")
        elif c == "\n" and multi:
            r.append("\n")
        elif c == "\n":
            r.append("\\n")
        elif c == "\t" and rng.random() < 0.3:
            r.append("\\t")
        elif c == "\r":
            r.append("\\r")
        elif o < 32 or o == 127:
            r.append("\\u%04X" % o if rng.random() < 0.5 else {8: "\\b", 12: "\\f"}.get(o, "\\u%04x" % o))
        elif o > 127 and rng.random() < 0.15:
            r.append("\\u%04X" % o if o < 65536 else "\\U%08X" % o)
        else:
            r.append(c)
    return "".join(r)


def texto_valor(rng, multi=False):
    pool = list(string.ascii_letters + string.digits + " .,:;=#[]{}()-_+*/!?@%&'\"\\\t") + EXTRA
    if multi:
        pool += ["\n", "\n", "\n"]
    n = rng.choice([0, 1, 3, 8, 20])
    return "".join(rng.choice(pool) for _ in range(n))


def cadena_toml(rng):
    k = rng.random()
    s = texto_valor(rng, multi=k > 0.6)
    if k < 0.35:
        s = s.replace("\n", "")
        return '"' + esc_basica(s, rng) + '"'
    if k < 0.55:
        s = "".join(c for c in s if c not in "'\n" and (ord(c) >= 32 or c == "\t") and ord(c) != 127)
        return "'" + s + "'"
    if k < 0.8:
        cuerpo = esc_basica(s, rng, multi=True)
        cuerpo = cuerpo.replace('"""', '""\\"')
        if cuerpo.endswith('"'):
            cuerpo = cuerpo[:-1] + '\\"'
        pre = "\n" if rng.random() < 0.4 else ""
        if rng.random() < 0.3:
            cuerpo = cuerpo.replace(" ", " \\\n   ", 1)
        return '"""' + pre + cuerpo + '"""'
    s = "".join(c for c in s if (ord(c) >= 32 or c in "\t\n") and ord(c) != 127)
    s = s.replace("'''", "''")
    if s.endswith("'"):
        s = s + " "
    pre = "\n" if rng.random() < 0.4 else ""
    return "'''" + pre + s + "'''"


def digitos(rng, n, guion=True):
    r = str(rng.randint(1, 9))
    for _ in range(n - 1):
        if guion and rng.random() < 0.15:
            r += "_"
        r += str(rng.randint(0, 9))
    return r


def numero_toml(rng):
    k = rng.random()
    sg = rng.choice(["", "", "+", "-"])
    if k < 0.3:
        return sg + rng.choice(["0", digitos(rng, rng.randint(1, 9))])
    if k < 0.4:
        base = rng.choice(["0x", "0o", "0b"])
        ds = {"0x": "0123456789abcdefABCDEF", "0o": "01234567", "0b": "01"}[base]
        return base + "".join(rng.choice(ds) + ("_" if rng.random() < 0.1 else "") for _ in range(rng.randint(1, 8))).rstrip("_")
    if k < 0.75:
        ent = rng.choice(["0", digitos(rng, rng.randint(1, 6))])
        fr = "." + digitos(rng, rng.randint(1, 6)).lstrip("0").rjust(1, "0") if rng.random() < 0.8 else ""
        ex = rng.choice(["e", "E"]) + rng.choice(["", "+", "-"]) + digitos(rng, rng.randint(1, 3)) if (rng.random() < 0.4 or not fr) else ""
        return sg + ent + fr + ex
    return rng.choice(["inf", "+inf", "-inf", "nan", "+nan", "-nan"])


def escalar_toml(rng):
    k = rng.random()
    if k < 0.4:
        return cadena_toml(rng)
    if k < 0.85:
        return numero_toml(rng)
    if k < 0.97:
        return rng.choice(["true", "false"])
    return rng.choice(["1979-05-27", "07:32:00", "1979-05-27T07:32:00Z", "1979-05-27 07:32:00.5-03:00"])


def esp(rng):
    return rng.choice(["", " ", "  ", "\t"])


def clave_parte(rng):
    k = rng.random()
    if k < 0.7:
        return palabra(rng, extras=False)
    s = "".join(rng.choice(string.ascii_letters + " .-_=[]#ñ€😀") for _ in range(rng.randint(0, 6)))
    if rng.random() < 0.5 or "'" in s:
        return '"' + esc_basica(s, rng) + '"'
    return "'" + s + "'"


def nombre_unico(rng, usados):
    for _ in range(50):
        k = clave_parte(rng)
        # claves distintas por el significado, no por cómo se escriben
        try:
            sig = tomllib.loads(f"{k} = 1")
            nombre = next(iter(sig))
        except Exception:
            continue
        if nombre not in usados:
            usados.add(nombre)
            return k
    return None


def clave_toml(rng, partes):
    return (esp(rng) + "." + esp(rng)).join(partes) if len(partes) > 1 else partes[0]


def comentario(rng):
    if rng.random() < 0.2:
        return esp(rng) + "#" + basura(rng, rng.randint(0, 10), extra="\t")
    return ""


def inline_toml(rng, prof):
    usados = set()
    items = []
    for _ in range(rng.randint(0, 4)):
        k = nombre_unico(rng, usados)
        if k is None:
            continue
        if rng.random() < 0.2:
            k2 = clave_parte(rng)
            k = k + esp(rng) + "." + esp(rng) + k2
        items.append(k + esp(rng) + "=" + esp(rng) + valor_toml(rng, prof + 1))
    sep = esp(rng) + "," + esp(rng)
    return "{" + esp(rng) + sep.join(items) + esp(rng) + "}"


def arreglo_toml(rng, prof):
    elems = [valor_toml(rng, prof + 1) for _ in range(rng.randint(0, 4))]
    r = "["
    for i, e in enumerate(elems):
        r += rng.choice(["", " ", "\n  ", "\n# nota\n"]) + e
        if i < len(elems) - 1 or rng.random() < 0.3:
            r += esp(rng) + ","
    return r + rng.choice(["", " ", "\n"]) + "]"


def valor_toml(rng, prof=0):
    k = rng.random()
    if prof < 3 and k < 0.12:
        return arreglo_toml(rng, prof)
    if prof < 3 and k < 0.2:
        return inline_toml(rng, prof)
    return escalar_toml(rng)


def tabla_toml(rng, ruta, salida, prof):
    usados = set()
    pendientes = []
    for _ in range(rng.randint(0, 5)):
        k = nombre_unico(rng, usados)
        if k is None:
            continue
        t = rng.random()
        if prof < 3 and t < 0.12:
            pendientes.append(("tabla", k))
        elif prof < 3 and t < 0.2:
            pendientes.append(("lista", k))
        elif t < 0.3:
            # clave con puntos
            partes = [k] + [clave_parte(rng) for _ in range(rng.randint(1, 2))]
            salida.append(esp(rng) + clave_toml(rng, partes) + esp(rng) + "=" + esp(rng) + valor_toml(rng) + comentario(rng))
            # otra hermana con puntos, sin repetir el nombre completo
            if rng.random() < 0.5:
                hermana = clave_parte(rng)
                if hermana != partes[1]:
                    salida.append(clave_toml(rng, [k, hermana]) + " = " + valor_toml(rng))
        else:
            salida.append(esp(rng) + k + esp(rng) + "=" + esp(rng) + valor_toml(rng) + comentario(rng))
        if rng.random() < 0.1:
            salida.append("")
        if rng.random() < 0.1:
            salida.append("# " + basura(rng, 8))
    for tipo, k in pendientes:
        sub = ruta + [k]
        if tipo == "tabla":
            salida.append("[" + esp(rng) + clave_toml(rng, sub) + esp(rng) + "]" + comentario(rng))
            tabla_toml(rng, sub, salida, prof + 1)
        else:
            for _ in range(rng.randint(1, 3)):
                salida.append("[[" + esp(rng) + clave_toml(rng, sub) + esp(rng) + "]]" + comentario(rng))
                tabla_toml(rng, sub, salida, prof + 1)


def doc_toml(rng):
    salida = []
    tabla_toml(rng, [], salida, 0)
    fin = rng.choice(["\n", "\n", "\r\n", ""])
    sep = "\r\n" if fin == "\r\n" else "\n"
    return sep.join(salida) + fin


MUT_CHARS = list("[]=\"'.,{}\n#\\ \t0_-+eExXob:TZ") + ["\r", "\x00" if False else "a", "é", "\x7f", "\x01", "😀", "\u2028"]


def mutar(rng, t):
    t = list(t)
    for _ in range(rng.choice([1, 1, 1, 2, 3])):
        if not t:
            t.append(rng.choice(MUT_CHARS))
            continue
        k = rng.random()
        i = rng.randrange(len(t))
        if k < 0.3:
            del t[i]
        elif k < 0.6:
            t.insert(i, rng.choice(MUT_CHARS))
        elif k < 0.8:
            t[i] = rng.choice(MUT_CHARS)
        elif k < 0.9:
            t = t[:i]
        else:
            j = rng.randrange(len(t))
            t[i], t[j] = t[j], t[i]
    return "".join(t)


def mutar_lineas(rng, t):
    ls = t.split("\n")
    if len(ls) > 1:
        i, j = rng.randrange(len(ls)), rng.randrange(len(ls))
        k = rng.random()
        if k < 0.4:
            ls.insert(j, ls[i])
        elif k < 0.7:
            ls[i], ls[j] = ls[j], ls[i]
        else:
            del ls[i]
    return "\n".join(ls)


TOML_A_MANO = [
    "", "\n\n", "# solo un comentario", "a = 1", "a=1\nb=2", "a = 1\na = 2", "a = 1\n[a]", "[a]\nb=1\n[a]",
    "[a.b]\n[a]", "[a]\n[a.b]\n[a]", "[a.b.c]\nx=1\n[a]\ny=2\n[a.b]\nz=3", "[a]\nb.c = 1\n[a.b]", "[a]\nb.c = 1\n[a.b.d]",
    "a.b = 1\n[a]", "a.b = 1\n[a.c]\nd=1", "[x]\na.b = 1\n[x.a]", "[x]\na.b.c = 1\n[x.a.b]", "[x]\na.b.c = 1\n[x.a.d]",
    "[[a]]\n[[a]]\nx=1\n[a.b]\n[[a]]\n[a.b]", "[[a]]\n[a]", "[a]\n[[a]]", "a = [1]\n[[a]]", "a = []\n[[a]]", "a = [{b=1}]\n[a.c]",
    "a = [{b=1}]\n[[a]]", "a = {b=1}\n[a.c]", "a = {b=1}\na.c = 2", "a = {b=1}\n[a]", "a = {b = 1, b = 2}", "a = {b.c = 1, b.d = 2}",
    "a = {b = {c = 1}, b.d = 2}", "a = {b = [1], b.d = 2}", "a = {b.c = 1, b = 2}", "a = {b = 1,}", "a = {,}", "a = {b = 1\n}",
    "a = {\n}", "a = {}", "a = []", "a = [,]", "a = [1,,2]", "a = [1,2,]", "a = [\n1,\n# c\n2,\n]", "a = [1 2]", "a = [[1],[2,[3]]]",
    "a = [1, 'x', true, {b=1}, [2.5]]", "a = [", "a = ]", "a = 1 2", "a = 1 # c", "a = 1\t# c\r\nb = 2", "a = 1\rb = 2",
    "a =", "= 1", "a", "a b = 1", "a. = 1", ".a = 1", "a..b = 1", "a . b = 1", " a = 1", "\ta = 1", "[ a ]", "[ a . b ]", "[]", "[a", "[a]]",
    "[[a]", "[[a]]]", "[[ a ]]", "[ [a]]", "[a]b=1", "[a] b=1", "[a] # c", "[a]\r\nb=1\r\n", "\"\" = 1", "'' = 1", "[\"\"]", "''.a = 1",
    "\"a.b\" = 1", "'a.b' = 1\n\"a\" = 2", "a = 0", "a = -0", "a = +0", "a = 00", "a = 01", "a = 0x", "a = 0x1", "a = 0x_1", "a = 0x1_", "a = 0xdead_beef",
    "a = 0XFF", "a = 0b102", "a = 0o78", "a = 1_000", "a = 1__000", "a = _1", "a = 1_", "a = +1_0", "a = 1.", "a = .1", "a = 1.0", "a = 1.e3", "a = 1e", "a = 1e+",
    "a = 1e+5", "a = 1E5", "a = 1.5E-3", "a = 1_0.0_1", "a = 1._0", "a = 1.0_", "a = -0.0", "a = inf", "a = +inf", "a = -inf", "a = nan", "a = -nan",
    "a = Inf", "a = infx", "a = 9223372036854775807", "a = 9223372036854775808", "a = 123456789012345678901234567890", "a = 0x7fffffffffffffff", "a = 0xffffffffffffffff",
    "a = true", "a = True", "a = truex", "a = false", "a = t", "a = 'x'", "a = ''", "a = \"\"", "a = \"x", "a = 'x", "a = \"a\\qb\"", "a = \"\\u00e9\"", "a = \"\\u00E9\"",
    "a = \"\\U0001F600\"", "a = \"\\ud800\"", "a = \"\\U00110000\"", "a = \"\\u12\"", "a = \"\\u12G4\"", "a = \"\\u0000\"", "a = \"tab\there\"", "a = \"nl\nx\"",
    "a = \"\"\"\nx\ny\"\"\"", "a = \"\"\"x\"\"\"\"", "a = \"\"\"x\"\"\"\"\"", "a = \"\"\"x\"\"\"\"\"\"", "a = \"\"\"x\\\n   y\"\"\"", "a = \"\"\"x\\  \n  y\"\"\"", "a = \"\"\"x\\ y\"\"\"",
    "a = \"\"\"x\\", "a = \"\"\"x", "a = '''x'''", "a = '''x''''", "a = '''x'''''", "a = '''x''''''", "a = '''\nx\n'''", "a = '''x\\n'''", "a = 'x\ny'", "a = \"\"\"\r\nx\r\ny\"\"\"",
    "a = \"x\x01\"", "a = 'x\x7f'", "a = 1 # \x01", "# \x7f", "# ok \t ok\na=1", "a = 1979-05-27", "a = 07:32:00", "a = 1979-13-27", "a = 1979-05-27T07:32:00", "a = 12:00",
    "a = 2024", "a = 2024-1", "a = 2024-01-01x", "[a]\nb = 1\n[c]\nb = 2", "[a]\n[b]\n[a.c]", "[a.b]\nx=1\n[a.b.c]\ny=2\n[a.d]\n", "[a]\nx = 1\n[a.x]", "[a]\n[b]\na.x = 1", "[t.a]\n[t]\na.x = 1", "[t.a]\nz=1\n[t]\na.x = 1", "[t]\na.x = 1\n[u]\na.y = 2", "[t]\na.x = 1\n[t.a]", "[[t]]\na.x = 1\n[t.a]", "[t]\na.x = 1\na.y = 2\n[t.b]\n[t.a.c]", "a.b.c = 1\n[a.b.d]", "a.b.c = 1\n[a.b]\n", "a.b.c = 1\n[a]", "[x]\ny.z = 1\n[x.y]\n", "[x.y]\n[x]\ny.z = 1", "a = 1\na.b = 2", "a = [1]\na.b = 2", "a = {b = 1}\na.b = 2",
    "[a]\nx = 1\n[a.x.y]", "a.b.c = 1\na.b.d = 2\na.e = 3", "a.b = 1\na = 2", "a = 1\na.b = 2", "a.b = 1\na.b.c = 2", "a.b.c = 1\na.b = 2",
    "[t]\na.b = 1\n[t2]\na.b = 2", "[[t]]\na.b = 1\n[[t]]\na.b = 2", "[[t]]\n[t.u]\nx=1\n[[t]]\n[t.u]\nx=2", "[[t.u]]\n[[t.u]]\n[t]\n", "[t]\n[[t.u]]\n[[t.u]]\n[t.u.v]",
    "[[a.b]]\nc=1\n[[a.b]]\nc=2\n[a]\nd=3", "[a]\n[[a.b]]\n[a.b.c]\n[a.b.d]\n[[a.b]]\n[a.b.c]", "[[a]]\nb=1\n[[a.c]]\nd=2\n[[a]]\n[[a.c]]\n[a.e]",
    "x = 1\n\n\n[y]\n\n\nz = 2\n\n", "\ufeffa = 1", "a = 1\n\x0b", "a = 1\u2028", "é = 1", "[é]", "\"é\" = 'ñ'", "a = [[[[[[[[[[1]]]]]]]]]]",
    "a = " + "[" * 100 + "]" * 100, "a = " + "{b=" * 5 + "1" + "}" * 5,
]
# Los límites de tomllib salen del límite de recursión de Python (1000 por omisión); los de
# lib/config son fijos (1000 partes en una clave, 470 niveles), así que solo se prueban con 1000.
def _lee_o_no(t):
    try:
        tomllib.loads(t)
        return True
    except Exception:
        return False


if tomllib is not None and sys.getrecursionlimit() == 1000:
    # (tomllib de Python 3.11 no limita las partes de una clave; solo se prueba si lo hace)
    TOML_A_MANO += ["a = " + "[" * 450 + "]" * 450, "a" + ".b" * 250 + " = 1"]
    if not _lee_o_no("a" + ".b" * 1005 + " = 1"):
        TOML_A_MANO.append("a" + ".b" * 1005 + " = 1")

# ---------------------------------------------------------------------------
# INI: archivos al azar
# ---------------------------------------------------------------------------

SECCIONES = ["servidor", "ui", "DEFAULT", "a b", "x]y", "Ñandú", "uno.dos", "[raro", "s", "números", "[x]", " espacio "]
CLAVES = ["host", "puerto", "Oscuro", "NOMBRE", "a b", "x-y", "café", "Ñu", "k.1", "clave_larga", "http://x", "a=b", "q:r", "x y z", "ÉL"]
VALORES = ["42", "-7", "+3", "5", "1_000", "0x10", "3.14", "1e3", "-0.5", ".5", "5.", "yes", "No", "TRUE", "off", "1", "0", "ON", "maybe", "",
           "9999999999999999999", "9223372036854775807", "12abc", "inf", "nan", "localhost", "a=b", "x: y", "# no es comentario", "; tampoco",
           "con ñ y é", "http://ejemplo.cl:80/x", "1 2", "  ", "\u00a0 7 \u2003", "1e400", "00012", "-0", "True ", "f"]


def doc_ini(rng):
    ls = []
    sep = "\n"
    n_sec = rng.randint(0, 4)
    usadas = set()
    if rng.random() < 0.05:
        ls.append(rng.choice(["# solo comentario", "; otro", "", "   "]))
    for _ in range(n_sec):
        s = rng.choice(SECCIONES)
        if s in usadas and s != "DEFAULT":
            continue
        usadas.add(s)
        if rng.random() < 0.05:
            ls.append("")
        ls.append(rng.choice(["", "", " ", "\t"]) * 0 + "[" + s + "]" + rng.choice(["", "", " ", " # x", "xyz"]))
        claves = set()
        for _ in range(rng.randint(0, 5)):
            k = rng.choice(CLAVES + [palabra(rng)])
            kl = k.lower()
            if kl in claves or "=" in k or ":" in k:
                continue
            claves.add(kl)
            d = rng.choice(["=", "=", " = ", ": ", " :", "=\t", "  =  "])
            if rng.random() < 0.7:
                v = rng.choice(VALORES)
            else:
                v = basura(rng, rng.randint(0, 12))
            ls.append(rng.choice(["", "", "", "  "]) * 0 + k + d + v)
            for _ in range(rng.choice([0, 0, 0, 1, 2])):
                ls.append(rng.choice(["  ", "\t", " ", "    ", ""]) + rng.choice(VALORES + [basura(rng, 6), "", "# ", "; c"]))
            if rng.random() < 0.15:
                ls.append(rng.choice(["# c", "; c", "   # c", "", "  "]))
    fin = rng.choice(["\n", "\n", "", "\r\n"])
    if fin == "\r\n":
        sep = "\r\n"
    return sep.join(ls) + fin


INI_A_MANO = [
    "", "\n", "# c", "; c\n\n", "[a]", "[a]\n", "[a]\nk=v", "[a]\nk = v\n", "[a]\nK = V\n", "[a]\nk: v", "[a]\nk : v", "[a]\nk=v=w", "[a]\nk:v:w", "[a]\nk=v:w", "[a]\nk:v=w",
    "k=v", "k=v\n[a]", "[a]\nk", "[a]\nk\n", "[a]\n=v", "[a]\n: v", "[a]\n k=v", "[a]\nk=v\n  w", "[a]\nk=v\n  w\n    x", "[a]\nk=v\n  w\n x", "[a]\nk=v\n\n  w", "[a]\nk=v\n\nw=1",
    "[a]\nk=v\n  # c\n  w", "[a]\nk=v\n# c\n  w", "[a]\nk=\n  w\n  x", "[a]\nk=v\n\n\n", "[a]\nk=v\n  \n  w\n  \n", "[a]\nk=v\n[b]\n  w", "[a]\nk=v\n  [b]", "[a]\n  k=v", "  [a]\nk=v",
    "[a]\nk=v\n  k2=w", "[a]\n[a]", "[a]\nk=1\n[b]\n[a]", "[a]\nk=1\nk=2", "[a]\nk=1\nK=2", "[a]\nk=1\n[b]\nk=1", "[DEFAULT]\nk=1\n[a]\nj=2", "[DEFAULT]\nk=1\n[DEFAULT]\nj=2", "[DEFAULT]\nk=1\n[DEFAULT]\nk=2",
    "[DEFAULT]\nk=1\n[a]\n[DEFAULT]\nj=2", "[a]\nk=1\n[DEFAULT]\nk=2", "[a]b]", "[a]]", "[a] x", "[a]x]y", "[]]", "[]", "[ ]", "[ a ]", "[[a]]", "[a\nk=1", "a]\n", "[a]\n[b]\nk=v\n[c]",
    "[a]\r\nk=v\r\n  w\r\n", "[a]\rk=v", "[a]\nk=v\r", "[a] # no\nk=v # tampoco", "[a]\nk = v ; no\n", "[a]\n; c\nk=v\n# d", "[a]\nk=\"v\"", "[a]\nk='v'",
    "[a]\n\tk=v\n\t\tw", "[a]\nk=v\n\t\n\tw", "[a]\n\u00a0k=v", "[a]\nÑ=1\nñ=2", "[a]\nÉL=1", "[ñ]\nk=1", "\u2003[a]\nk=1", "[a]\nk=v\u2003", "[a]\nk\u2003=\u2003v\u2003",
    "[a]\nx=1\n[b]\nx=2\n[c]\nx=3", "[a]\nk=v\n\t# c\n\tw", "[a]\nk = 1 2  3 \n", "[a]\n k=1", "[a]\nk=1\n\n[b]\n\nk=2",
]


def py_escribir_ini(p):
    """RawConfigParser.write, con los saltos de línea como en Python 3.13 (\r\n y \r también
    pasan a salto y tab; las versiones anteriores solo hacían eso con \n)."""
    def sec(nombre, items):
        r = "[" + nombre + "]\n"
        for k, v in items:
            r += k + " = " + v.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\n\t") + "\n"
        return r + "\n"
    r = sec("DEFAULT", p._defaults.items()) if p._defaults else ""
    for s in p.sections():
        r += sec(s, p._sections[s].items())
    if "\r" not in "".join(v for s in p.sections() for v in p._sections[s].values()) + "".join(p._defaults.values()):
        fp = io.StringIO()
        p.write(fp)
        assert fp.getvalue() == r, "py_escribir_ini no coincide con configparser.write"
    return r


def py_ini(t):
    p = configparser.RawConfigParser()
    try:
        p.read_string(t)
    except configparser.Error:
        return None
    return p


# ---------------------------------------------------------------------------
# Líneas
# ---------------------------------------------------------------------------

def doc_lineas(rng):
    ls = []
    for _ in range(rng.randint(0, 8)):
        k = rng.random()
        if k < 0.1:
            ls.append("")
        elif k < 0.2:
            ls.append("# " + basura(rng, 8))
        elif k < 0.25:
            ls.append(rng.choice(["  ", "\t", "\u2003"]) + "#x")
        else:
            clave = rng.choice(["servidor", "estacion", "usgs", "hora", "ñu", "k", "coincidencia", "x#y"])
            partes = [rng.choice(["geofon.gfz", "18000", "PB06", "CX", "BHZ", "chile", "é", "😀", "a=b", "#"]) for _ in range(rng.randint(0, 4))]
            ls.append(rng.choice(["", "", " ", "\t"]) + clave + "".join(rng.choice([" ", "  ", "\t", " \u00a0 "]) + p for p in partes) + rng.choice(["", " ", "\r"]))
    return rng.choice(["\n", "\r\n"]).join(ls) + rng.choice(["", "\n"])


def py_lineas(t):
    od = {}
    for l in t.split("\n"):
        l = l.strip()
        if l and not l.startswith("#"):
            i = 0
            while i < len(l) and not l[i].isspace():
                i += 1
            od.setdefault(l[:i], []).append(l[i:].strip())
    return od


# ---------------------------------------------------------------------------
# Casos y comparación
# ---------------------------------------------------------------------------

def casos_al_azar(rng):
    c = {"ini": [], "iniget": [], "toml": [], "lineas": []}
    # TOML
    c["toml"].extend(TOML_A_MANO)
    validos = []
    for _ in range(520):
        t = doc_toml(rng)
        validos.append(t)
        c["toml"].append(t)
    for _ in range(620):
        t = rng.choice(validos)
        t = mutar_lineas(rng, t) if rng.random() < 0.25 else mutar(rng, t)
        c["toml"].append(t)
    for t in TOML_A_MANO:
        if rng.random() < 0.6:
            c["toml"].append(mutar(rng, t))
    # INI
    c["ini"].extend(INI_A_MANO)
    ini_ok = []
    for _ in range(420):
        t = doc_ini(rng)
        c["ini"].append(t)
        ini_ok.append(t)
    for _ in range(420):
        t = rng.choice(ini_ok + INI_A_MANO)
        t = mutar_lineas(rng, t) if rng.random() < 0.3 else mutar(rng, t)
        c["ini"].append(t)
    # consultas de INI
    fuentes = [t for t in c["ini"] if py_ini(t) is not None]
    for _ in range(700):
        t = rng.choice(fuentes)
        p = py_ini(t)
        secs = p.sections() + ["DEFAULT", "inexistente"]
        s = rng.choice(secs)
        pos = list(p._defaults) + [k for sec in p.sections() for k in p._sections[sec]]
        if pos and rng.random() < 0.8:
            k = rng.choice(pos)
            k = rng.choice([k, k.upper(), k.capitalize(), k])
        else:
            k = rng.choice(CLAVES + ["nada"])
        if rng.random() < 0.6 and p.sections():
            s = rng.choice(p.sections())
        c["iniget"].append({"t": t, "s": s, "c": k})
    # líneas
    for _ in range(300):
        t = doc_lineas(rng)
        ps = py_lineas(t)
        clave = rng.choice(list(ps) + ["nada"]) if ps else "nada"
        r = rng.choice(ps[clave]) if clave in ps else rng.choice(["a b c", "  x\ty  z ", "", "uno"])
        c["lineas"].append({"t": t, "c": clave, "r": r})
    return c


def leer(stdout):
    r = {}
    for linea in stdout.split("\n"):
        p = linea.split(" ", 2)
        if len(p) >= 2 and p[1].isdigit() and p[0].isalpha() and p[0].isupper():
            r[(p[0], int(p[1]))] = p[2] if len(p) == 3 else ""
    return r


class Volcado:
    """Lee el árbol que escribe config_python.scar."""

    def __init__(self, s):
        self.s = s
        self.i = 0

    def leer_hasta(self, fin):
        j = self.i
        while self.s[self.i] not in fin:
            self.i += 1
        return self.s[j:self.i]

    def nodo(self):
        c = self.s[self.i]
        if c in "OA":
            self.i += 2
            items = []
            while self.s[self.i] != ")":
                if c == "O":
                    nombre = de_cps(self.leer_hasta(":"))
                    self.i += 1
                    items.append((nombre, self.nodo()))
                else:
                    items.append(self.nodo())
                if self.s[self.i] == ";":
                    self.i += 1
            self.i += 1
            return (c, items)
        if c == "S":
            self.i += 1
            return ("S", de_cps(self.leer_hasta(";)")))
        if c == "N":
            self.i += 1
            return ("N", self.leer_hasta(";)"))
        if c == "B":
            self.i += 2
            return ("B", self.s[self.i - 1] == "1")
        raise ValueError("volcado raro: " + self.s[self.i:self.i + 20])


def volcado(s):
    v = Volcado(s)
    n = v.nodo()
    if v.i != len(s):
        raise ValueError("volcado con basura al final")
    return n


ENTERO = re.compile(r"^-?[0-9]+$")


def igual_valor(py, n, ruta=""):
    """None si el valor de Python y el nodo coinciden; si no, por qué no."""
    tipo, v = n
    if isinstance(py, dict):
        if tipo != "O":
            return f"{ruta}: Python tiene una tabla y la librería {tipo}"
        if [k for k, _ in v] != list(py):
            return f"{ruta}: claves {[k for k, _ in v]!r} y Python {list(py)!r}"
        for (k, x) in v:
            e = igual_valor(py[k], x, ruta + "." + k)
            if e:
                return e
        return None
    if isinstance(py, list):
        if tipo != "A" or len(v) != len(py):
            return f"{ruta}: arreglo distinto"
        for i, (a, b) in enumerate(zip(py, v)):
            e = igual_valor(a, b, f"{ruta}[{i}]")
            if e:
                return e
        return None
    if isinstance(py, bool):
        return None if (tipo == "B" and v == py) else f"{ruta}: booleano {py} y la librería {n}"
    if isinstance(py, int):
        if tipo == "N" and ENTERO.match(v) and int(v) == py:
            return None
        return f"{ruta}: entero {py} y la librería {n}"
    if isinstance(py, float):
        if tipo == "N" and not ENTERO.match(v):
            f = float(v)
            if f == py or (math.isnan(f) and math.isnan(py)):
                return None
        return f"{ruta}: flotante {py!r} y la librería {n}"
    if isinstance(py, str):
        return None if (tipo == "S" and v == py) else f"{ruta}: texto {py!r} y la librería {n}"
    return f"{ruta}: Python tiene {type(py).__name__} (fechas) y la librería {n}"


def norm(x):
    if isinstance(x, dict):
        return ("d", sorted((k, norm(v)) for k, v in x.items()))
    if isinstance(x, list):
        return ("l", [norm(v) for v in x])
    if isinstance(x, float) and math.isnan(x):
        return ("nan",)
    return (type(x).__name__, x)


def tiene_fecha(t):
    return re.search(r"[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{2}:[0-9]{2}:[0-9]{2}", t) is not None


def bool_ini(v, defecto):
    t = v.lower()
    if t in ("1", "yes", "true", "on"):
        return True
    if t in ("0", "no", "false", "off"):
        return False
    return defecto


def entero_py(v, defecto):
    try:
        n = int(v)
    except ValueError:
        return defecto
    return n if abs(n) <= 9223372036854775807 else defecto


def comparar(casos, got):
    errores = []
    n = 0
    omitidos = 0

    def malo(msg):
        errores.append(msg)

    # ---- TOML ----
    for k, t in enumerate(casos["toml"]):
        n += 1
        r = got.get(("T", k))
        if r is None:
            malo(f"TOML {k}: la librería no escribió nada; texto {t!r}")
            continue
        try:
            py = tomllib.loads(t)
            py_ok = True
        except Exception:
            py_ok = False
        if not py_ok:
            if not r.startswith("ERR"):
                malo(f"TOML {k}: tomllib da error y la librería lo acepta; texto {t!r}")
            continue
        if r.startswith("ERR"):
            clase = r[4:5]
            ok = (clase == "F" and tiene_fecha(t)) or (clase == "G" and re.search(r"0[xob]", t)) or (clase == "N" and "u0000" in t.lower().replace("\\u0000", "u0000") or "\\U00000000" in t)
            if ok:
                omitidos += 1
            else:
                malo(f"TOML {k}: tomllib lo lee y la librería da error ({r}); texto {t!r}")
            continue
        try:
            nodo = volcado(r[3:])
        except Exception as e:
            malo(f"TOML {k}: volcado ilegible ({e}); {r[:100]!r}")
            continue
        e = igual_valor(py, nodo)
        if e:
            malo(f"TOML {k}: {e}; texto {t!r}")
            continue
        # escribir
        w = got.get(("TW", k), "")
        n += 1
        if not w or w.startswith("ERR"):
            malo(f"TOML {k}: escribir_toml falló; texto {t!r}")
            continue
        marca, _, cod = w.partition(" ")
        if marca != "S":
            malo(f"TOML {k}: lo escrito no se lee igual ({marca}); texto {t!r}")
            continue
        try:
            escrito = de_cps(cod)
            py2 = tomllib.loads(escrito)
        except Exception as ex:
            malo(f"TOML {k}: tomllib no lee lo que escribió la librería ({ex}); escrito {escrito!r}")
            continue
        if norm(py2) != norm(py):
            malo(f"TOML {k}: tomllib lee otra cosa de lo escrito; texto {t!r}; escrito {escrito!r}")

    # ---- INI ----
    for k, t in enumerate(casos["ini"]):
        n += 1
        r = got.get(("I", k))
        p = py_ini(t)
        if r is None:
            malo(f"INI {k}: la librería no escribió nada; texto {t!r}")
            continue
        if p is None:
            if not r.startswith("ERR"):
                malo(f"INI {k}: configparser da error y la librería lo acepta; texto {t!r}")
            continue
        if r.startswith("ERR"):
            malo(f"INI {k}: configparser lo lee y la librería da error; texto {t!r}")
            continue
        try:
            tipo, items = volcado(r[3:])
        except Exception as e:
            malo(f"INI {k}: volcado ilegible ({e})")
            continue
        nombres = [a for a, _ in items if a != "DEFAULT"]
        if nombres != p.sections():
            malo(f"INI {k}: secciones {nombres!r} y configparser {p.sections()!r}; texto {t!r}")
            continue
        bien = True
        for nombre, nodo in items:
            esperado = p._defaults if nombre == "DEFAULT" else p._sections[nombre]
            lo = [(a, b[1]) for a, b in nodo[1]]
            if lo != list(esperado.items()):
                malo(f"INI {k}: sección {nombre!r}: {lo!r} y configparser {list(esperado.items())!r}; texto {t!r}")
                bien = False
        if bien and p._defaults and "DEFAULT" not in [a for a, _ in items]:
            malo(f"INI {k}: falta DEFAULT; texto {t!r}")
        # escribir
        n += 1
        w = got.get(("IW", k), "")
        marca, _, cod = w.partition(" ")
        if bien:
            esperado = py_escribir_ini(p)
            if marca != "S" or de_cps(cod) != esperado:
                malo(f"INI {k}: escribir_ini {de_cps(cod) if cod else w!r} y configparser {esperado!r} ({marca}); texto {t!r}")

    for k, c in enumerate(casos["iniget"]):
        p = py_ini(c["t"])
        s, clave = c["s"], c["c"]
        v = p.get(s, clave, fallback=None)
        n += 5

        def chequea(et, esperado):
            g = got.get((et, k))
            if g != esperado:
                malo(f"INI get {k} {et}: {g!r} y lo esperado {esperado!r}; sección {s!r} clave {clave!r} texto {c['t']!r}")
        chequea("GT", cps("pordefecto" if v is None else v))
        chequea("GH", "1" if v is not None else "0")
        chequea("GI", str(7777 if v is None else entero_py(v, 7777)))
        chequea("GB", "1" if (True if v is None else bool_ini(v, True)) else "0")
        chequea("GN", "1" if (False if v is None else bool_ini(v, False)) else "0")
        chequea("GS", "".join(cps(x) + ";" for x in p.sections()))
        # decimales: a_f64 no hace guiones bajos
        if v is None or "_" not in v:
            try:
                esperado = float(v) if v is not None else 1234.5
            except ValueError:
                esperado = 1234.5
            g = got.get(("GF", k))
            try:
                gf = float(g)
            except (TypeError, ValueError):
                gf = None
            if gf is None or not (gf == esperado or (math.isnan(gf) and math.isnan(esperado)) or abs(gf - esperado) <= 1e-12 * abs(esperado)):
                malo(f"INI get {k} GF: {g!r} y lo esperado {esperado!r}; valor {v!r}")

    # ---- líneas ----
    for k, c in enumerate(casos["lineas"]):
        ps = py_lineas(c["t"])
        n += 6
        esp_v = "O(" + ";".join(cps(a) + ":A(" + ";".join("S" + cps(x) for x in b) + ")" for a, b in ps.items()) + ")"
        if got.get(("L", k)) != esp_v:
            malo(f"líneas {k} L: {got.get(('L', k))!r} y lo esperado {esp_v!r}; texto {c['t']!r}")
        w = "".join(a + " " + x + "\n" for a, b in ps.items() for x in b)
        if got.get(("LW", k)) != cps(w):
            malo(f"líneas {k} LW: {got.get(('LW', k))!r} y lo esperado {cps(w)!r}")
        ult = ps[c["c"]][-1] if c["c"] in ps else "pordefecto"
        if got.get(("LU", k)) != cps(ult):
            malo(f"líneas {k} LU: {got.get(('LU', k))!r} y lo esperado {cps(ult)!r}")
        tod = "".join(cps(x) + ";" for x in ps.get(c["c"], []))
        if got.get(("LT", k)) != tod:
            malo(f"líneas {k} LT: {got.get(('LT', k))!r} y lo esperado {tod!r}")
        pal = c["r"].split()
        campos = "".join(cps(pal[j] if j < len(pal) else "") + ";" for j in range(4))
        if got.get(("LC", k)) != campos:
            malo(f"líneas {k} LC: {got.get(('LC', k))!r} y lo esperado {campos!r}; resto {c['r']!r}")
    return errores, n, omitidos


def main():
    if tomllib is None:
        print("OK: lib/config se omite (hace falta Python 3.11 o más nuevo, por tomllib)")
        return 0
    rng = random.Random(int(os.environ.get("SCAR_SEMILLA", "20")))
    casos = casos_al_azar(rng)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(casos, f, ensure_ascii=False)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/config_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_config_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_config_python: FALLA, el programa terminó con", r.returncode)
            return 1
    got = leer(r.stdout)
    errores, comparaciones, omitidos = comparar(casos, got)
    if errores:
        print("\n".join(errores[:25]))
        print(f"test_config_python: FALLA ({len(errores)} diferencias)")
        return 1
    # autocomprobación: el comparador tiene que notar un resultado estropeado
    for et, cambio in (("T", lambda v: v.replace("S", "S9", 1) if "S" in v else v + "x"),
                       ("I", lambda v: v.replace("S", "S9", 1) if "S" in v else v + "x"),
                       ("GI", lambda v: v + "1"), ("L", lambda v: v + "x"), ("TW", lambda v: v[2:])):
        malo = dict(got)
        for clave in [k for k in malo if k[0] == et and not malo[k].startswith("ERR")][:3]:
            malo[clave] = cambio(malo[clave])
        if not comparar(casos, malo)[0]:
            print(f"test_config_python: FALLA, la autocomprobación no notó un resultado estropeado ({et})")
            return 1
    malo = dict(got)
    for clave in [k for k in malo if k[0] == "T" and malo[k].startswith("ERR")][:1]:
        malo[clave] = "OK O()"
    if not comparar(casos, malo)[0]:
        print("test_config_python: FALLA, la autocomprobación no notó un error que pasó a éxito")
        return 1
    total = sum(len(casos[k]) for k in casos)
    print(f"OK: lib/config contra configparser y tomllib: {total} casos, {comparaciones} comparaciones ({omitidos} TOML con fechas o enteros enormes omitidos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
