"""lib/patron contra el módulo `re` de Python.

    python3 pruebas/test_patron_python.py

Python inventa patrones y textos al azar y los escribe en casos.json; pruebas/patron_python.scar
los procesa con lib/patron y Python calcula lo mismo con `re`:

  - patrones armados con una gramática (literales, escapes, clases, \\d \\w \\s, anclas, grupos
    con y sin captura, con nombre, alternativas, todos los cuantificadores y sus versiones
    perezosas, banderas i m s al principio o en un trozo) sobre textos con letras con tilde,
    griego, cirílico, dígitos de otros alfabetos, espacios raros y saltos de línea: dónde
    calza (search / desde una posición / match / fullmatch), el texto de cada grupo y los
    grupos por nombre;
  - todos los calces (finditer, findall, contar), con los calces vacíos de Python 3.7 o más;
  - re.sub con plantillas (\\1, \\g<0>, \\g<nombre>, \\n, errores) y con un texto literal, con
    count; re.split con grupos y maxsplit; re.escape;
  - patrones escritos como basura (signos mezclados): lo que Python acepta, la lib lo acepta y
    da la misma cantidad de grupos y el mismo primer calce; lo que Python rechaza, lo rechaza
    ella; y lo que la lib no soporta a propósito (referencias hacia atrás, mirar adelante/atrás,
    atómicos, posesivos, banderas x a u L) lo rechaza con un error;
  - una autocomprobación: si se estropea un resultado de la lib, el comparador lo tiene que notar.

Hace falta Python 3.11 o más nuevo (así se comportan igual las banderas en medio del patrón).
Solo usa el módulo `re` de la biblioteca estándar.
"""

import json
import os
import random
import re
import subprocess
import sys
import tempfile
import warnings

warnings.simplefilter("ignore")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from re import _constants as C
    from re import _parser as P
except ImportError:  # Python < 3.11
    C = P = None

LIT = ["a", "b", "c", "d", "1", "2", "_", " ", "-", "ñ", "é", "É", "α", "я", "٣", "A", "B", "x", "Z"]
ESCLIT = ["\\.", "\\*", "\\+", "\\?", "\\(", "\\)", "\\[", "\\]", "\\{", "\\}", "\\|", "\\^", "\\$", "\\\\",
          "\\-", "\\n", "\\t", "\\x61", "\\u00f1", "\\101", "\\0", "\\/", "\\ "]
CLASES = ["[abc]", "[^abc]", "[a-c]", "[^a-c1]", "[a-cx-z]", "[\\d]", "[\\w-]", "[\\s,]", "[^\\d\\s]", "[a\\-z]",
          "[]a]", "[^]a]", "[-a]", "[a-]", "[\\b]", "[é-ñ]", "[α-ω]", "[а-я]", "[\\W]", "[\\D\\S]", "[.]", "[$^]",
          "[a-c\\d]", "[A-Za-z_]", "[0-9]", "[^\\n]", "[\\x61-\\x63]", "[\\u00e0-\\u00ff]", "[^a]", "[\\--a]"]
CATEG = ["\\d", "\\D", "\\w", "\\W", "\\s", "\\S"]
ANCLAS = ["^", "$", "\\b", "\\B", "\\A", "\\Z"]
CUANT = ["*", "+", "?", "{2}", "{1,3}", "{2,}", "{,2}", "{0}", "{0,1}", "{1}", "{0,2}", "{3,3}"]

POOL = list("abcdABCD12_ -.xZ()[]*\n\t") + ["ñ", "Ñ", "é", "É", "α", "Α", "я", "Я", "٣", "３", "²", "中", "€", "😀",
                                            " ", " ", "ж", "ü", "_", "9"]


def texto_al_azar(rng, extras, largo=None):
    n = rng.randrange(0, 15) if largo is None else largo
    base = POOL + extras * 3
    return "".join(rng.choice(base) for _ in range(n))


class Ctx:
    def __init__(self, rng):
        self.rng = rng
        self.nombres = []
        self.raro = False
        self.lits = []
        self.usa_B = False
        self.n = 0


def gen_alt(c, prof):
    ramas = []
    for _ in range(c.rng.choice([1, 1, 1, 2, 2, 3])):
        ramas.append(gen_cat(c, prof))
    return "|".join(r[0] for r in ramas), any(r[1] for r in ramas)


def gen_cat(c, prof):
    k = c.rng.choice([0, 1, 1, 2, 2, 3, 4])
    items = [gen_item(c, prof) for _ in range(k)]
    return "".join(i[0] for i in items), all(i[1] for i in items)


def gen_atomo(c, prof):
    r = c.rng
    x = r.random()
    if x < 0.40:
        s = r.choice(LIT)
        c.lits.append(s)
        return s, False, True
    if x < 0.47:
        return r.choice(ESCLIT), False, True
    if x < 0.55:
        return ".", False, True
    if x < 0.67:
        return r.choice(CLASES), False, True
    if x < 0.77:
        return r.choice(CATEG), False, True
    if x < 0.83:
        a = r.choice(ANCLAS)
        if a == "\\B":
            c.usa_B = True
        return a, True, False
    if prof >= 3:
        return r.choice(LIT), False, True
    y = r.random()
    s, nul = gen_alt(c, prof + 1)
    if y < 0.45:
        return "(" + s + ")", nul, True
    if y < 0.70:
        return "(?:" + s + ")", nul, True
    if y < 0.85:
        c.n += 1
        nombre = f"n{c.n}"
        c.nombres.append(nombre)
        return f"(?P<{nombre}>" + s + ")", nul, True
    fl = r.choice(["i", "s", "m", "-i", "is", "i-s", "ms"])
    return f"(?{fl}:" + s + ")", nul, True


def gen_item(c, prof):
    s, nul, cuant = gen_atomo(c, prof)
    if cuant and c.rng.random() < 0.42:
        q = c.rng.choice(CUANT)
        mn = 0 if q in ("*", "?", "{,2}", "{0}", "{0,1}", "{0,2}") else 1
        if q == "{2}" or q == "{2,}":
            mn = 2
        if q == "{3,3}":
            mn = 3
        if nul and q not in ("{0}", "?", "{0,1}", "{1}"):
            c.raro = True
        if nul and q in ("{0,1}", "?"):
            pass
        lazy = c.rng.random() < 0.3
        return s + q + ("?" if lazy else ""), (mn == 0 or nul), False
    return s, nul, False


def patron_al_azar(rng):
    c = Ctx(rng)
    s, _ = gen_alt(c, 0)
    f = ""
    r = rng.random()
    if r < 0.12:
        s = "(?i)" + s
    elif r < 0.18:
        s = "(?m)" + s
    elif r < 0.22:
        s = "(?s)" + s
    elif r < 0.26:
        s = "(?ims)" + s
    elif r < 0.40:
        f = rng.choice(["i", "m", "s", "im", "is", "ms", "ims"])
    return s, f, c


BASURA = list("abab(())[]{}|**++??..^$$\\\\--,,12dwsPi:<>#=!") + ["(?", "(?:", "(?P<n>", "\\d", "\\w", "\\b", "{2}", "{1,2}", "[a-z]", "[^a]"]

CURADOS = [
    ("a|ab", ""), ("(a|ab)(c|bcd)(d*)", ""), ("(a+)(b+)?", ""), ("x*", ""), ("(a*)*", ""), ("(a*)+", ""),
    ("(a|b)*?c", ""), ("^$", ""), ("$", ""), ("a$", ""), ("(?m)^a", ""), ("(?s).", ""), (".", ""), ("\\bfoo\\b", ""),
    ("(?i)ÑANDÚ", ""), ("[a-z]+@[a-z]+\\.com", ""), ("(\\d+)-(\\d+)", ""), ("(?P<y>\\d{4})-(?P<m>\\d\\d)", ""),
    ("a{2,3}?", ""), ("(a)|(b)", ""), ("(a)?b", ""), ("((a)|(b))+", ""), ("\\w+", ""), ("\\d+", ""), ("\\s+", ""),
    ("[^\\W\\d]+", ""), ("(?:a|b)+c", ""), ("(a|b|ab)*c", ""), ("(.*)(\\d)", ""), ("(.*?)(\\d)", ""), (".*", "s"),
    ("^a.*b$", "m"), ("é+", "i"), ("[а-я]+", "i"), ("α+", "i"), ("(?i:a)b", ""), ("a(?-i:b)", "i"), ("\\Bb", ""),
    ("", ""), ("|", ""), ("a||b", ""), ("()", ""), ("(|a)+", ""), ("a{,}", ""), ("a{", ""), ("a{1", ""),
    ("x{1,2}{", ""), ("}", ""), ("]", ""), ("[\\]]", ""), ("a.b", "s"), ("\\x41", ""), ("\\u00d1", "i"),
]

INVALIDOS = [
    "(", ")", "a)", "[a", "a**", "*a", "+", "?", "a{2,1}", "\\", "(?P<n>a)(?P<n>b)", "(?P<1a>x)", "[z-a]",
    "[\\d-a]", "[a-\\d]", "\\q", "(?i", "x{1}{2}", "\\xg", "\\u12", "^*", "\\b+", "(?z)", "(*)", "(?P<>a)", "(?#",
    "[]", "[^]", "(?P<a", "a(?i)b", "(?i)a(?s)", "\\A*", "$+", "(?:", "(a|*)", "a|*", "\\U110000", "(?P", "(?",
    "[\\A]", "[\\B]", "[\\Z]", "\\8", "[\\8]", "(?-)", "(?i-i:a)", "(?ii:a)", "\\400",
]

NO_SOPORTADOS = [
    "(a)\\1", "(?=a)", "(?!a)", "(?<=a)", "(?<!a)", "(?>a)", "(?P<n>a)(?P=n)", "(a)(?(1)b|c)", "\\N{DIGIT ONE}",
    "(?x)a b", "(?a)b", "(?u)b", "a*+", "a++", "a?+", "a{1,2}+", "(a)\\1+", "\\2(a)(b)", "(?L)a",
]


def py_compila(p, f):
    fl = 0
    for ch in f:
        fl |= {"i": re.I, "m": re.M, "s": re.S}[ch]
    try:
        return re.compile(p, fl)
    except (re.error, RecursionError, OverflowError, ValueError, IndexError):
        return None


def tiene_no_soportado(p, f):
    """True si Python acepta el patrón pero usa algo que la lib rechaza a propósito."""
    if C is None:
        return False
    fl = 0
    for ch in f:
        fl |= {"i": re.I, "m": re.M, "s": re.S}[ch]
    try:
        t = P.parse(p, fl)
    except Exception:
        return False
    raras = re.VERBOSE | re.ASCII | re.LOCALE | re.UNICODE
    # parse() pone siempre la bandera UNICODE (es la de los textos), así que la u se busca en el
    # texto, sin los escapes ni los corchetes
    limpio = re.sub(r"\\.", "", p)
    limpio = re.sub(r"\[\]?[^\]]*\]", "", limpio)
    if re.search(r"\(\?[a-zA-Z-]*u", limpio):
        return True
    if t.state.flags & (re.VERBOSE | re.ASCII | re.LOCALE):
        return True
    malos = {C.GROUPREF, C.GROUPREF_EXISTS, C.ASSERT, C.ASSERT_NOT, C.ATOMIC_GROUP, C.POSSESSIVE_REPEAT, C.FAILURE}
    # \N{...} se resuelve a un literal: se detecta en el texto
    if re.search(r"(?<!\\)(\\\\)*\\N\{", p):
        return True

    def recorre(x):
        if isinstance(x, P.SubPattern):
            return any(recorre((op, av)) for op, av in x)
        if isinstance(x, tuple) and len(x) == 2 and x[0] in malos:
            return True
        if isinstance(x, tuple) and len(x) == 2 and x[0] == C.SUBPATTERN and (x[1][1] | x[1][2]) & raras:
            return True
        if isinstance(x, (tuple, list)):
            return any(recorre(e) for e in x)
        return False

    return recorre(list(t))


def cps(s):
    return ",".join(str(ord(c)) for c in s) if s else "_"


def describe(m, ng, solo0=False):
    if m is None:
        return "NO"
    r = ["OK"]
    for j in range(ng + 1):
        if solo0 and j > 0:
            break
        a, b = m.span(j)
        r.append(f"{a},{b},{cps(m.group(j) or '')}")
    return " ".join(r)


PLANTILLAS_PIEZAS = ["x", "-", "[", "\\1", "\\2", "\\g<0>", "\\g<1>", "\\\\", "\\n", "\\t", "\\.", "\\10", "ñ", " "]
PLANTILLAS_MALAS = ["\\q", "\\g<zz>", "\\g<", "\\g<>", "\\", "\\g<-1>", "\\9", "\\g<5>", "\\g 1"]


def plantilla_al_azar(rng, nombres):
    if rng.random() < 0.08:
        return rng.choice(PLANTILLAS_MALAS)
    piezas = list(PLANTILLAS_PIEZAS) + [f"\\g<{n}>" for n in nombres]
    return "".join(rng.choice(piezas) for _ in range(rng.randrange(0, 5)))


def casos_al_azar(rng):
    c = dict(comp=[], busq=[], todas=[], sub=[], split=[], escape=[])
    gen = []
    for _ in range(900):
        p, f, ctx = patron_al_azar(rng)
        gen.append((p, f, ctx))
    for p, f in CURADOS:
        ctx = Ctx(rng)
        ctx.lits = list("abc12")
        gen.append((p, f, ctx))
    for p, f, ctx in gen:
        pat = py_compila(p, f)
        if pat is None:
            c["comp"].append(dict(p=p, f=f))
            continue
        nombres = sorted(pat.groupindex)
        c["comp"].append(dict(p=p, f=f))
        n_t = rng.choice([1, 1, 2, 3])
        textos = [texto_al_azar(rng, ctx.lits) for _ in range(n_t)]
        if ctx.usa_B or "\\B" in p:
            textos = [t if t else "a" for t in textos]
        raro = ctx.raro
        for t in textos:
            modo = rng.choice(["buscar", "buscar", "desde", "match", "full"])
            c["busq"].append(dict(p=p, f=f, t=t, modo=modo, desde=rng.randrange(0, len(t) + 3), nombres=nombres, raro=raro))
        t = textos[0]
        c["todas"].append(dict(p=p, f=f, t=t, raro=raro))
        if rng.random() < 0.6:
            c["sub"].append(dict(p=p, f=f, t=t, tpl=plantilla_al_azar(rng, nombres), lit=rng.choice(["", "#", "\\1", "ñ\\"]),
                                 n=rng.choice([0, 0, 1, 2, 3]), raro=raro))
        if rng.random() < 0.6:
            c["split"].append(dict(p=p, f=f, t=t, n=rng.choice([0, 0, 1, 2, 3]), raro=raro))
    # basura
    for _ in range(700):
        p = "".join(rng.choice(BASURA) for _ in range(rng.randrange(1, 9)))
        c["comp"].append(dict(p=p, f=""))
        pat = py_compila(p, "")
        if pat is not None and not tiene_no_soportado(p, ""):
            t = "".join(rng.choice("ab12.-*()[]{}|\\ \n") for _ in range(rng.randrange(0, 9)))
            if "\\B" in p and not t:
                t = "a"
            c["busq"].append(dict(p=p, f="", t=t, modo="buscar", desde=0, nombres=[], raro=True))
    for p in INVALIDOS + NO_SOPORTADOS:
        c["comp"].append(dict(p=p, f=""))
    for _ in range(150):
        n = rng.randrange(0, 12)
        c["escape"].append("".join(rng.choice(list("ab1 ._-()[]{}?*+|^$\\&~#\t\n\r\x0b\x0cñ€😀:,;/<>=!@%")) for _ in range(n)))
    return c


def leer(stdout):
    r = {}
    for linea in stdout.split("\n"):
        p = linea.split(" ", 2)
        if len(p) >= 2 and p[1].isdigit() and p[0].isalpha() and p[0].isupper():
            r[(p[0], int(p[1]))] = p[2] if len(p) == 3 else ""
    return r


def comparar(casos, got):
    errores = []
    n = 0

    def igual(et, k, esperado, extra=""):
        nonlocal n
        n += 1
        g = got.get((et, k))
        if g != esperado:
            errores.append(f"{et} {k}: salió {g!r:.150} y se esperaba {esperado!r:.150} {extra}")

    for k, d in enumerate(casos["comp"]):
        p, f = d["p"], d["f"]
        pat = py_compila(p, f)
        if pat is None or tiene_no_soportado(p, f):
            igual("C", k, "ERR", repr(p))
        else:
            igual("C", k, f"OK {pat.groups}", repr(p))
    for k, d in enumerate(casos["busq"]):
        pat = py_compila(d["p"], d["f"])
        t = d["t"]
        m = {"buscar": lambda: pat.search(t), "desde": lambda: pat.search(t, d["desde"]),
             "match": lambda: pat.match(t), "full": lambda: pat.fullmatch(t)}[d["modo"]]()
        esp = describe(m, pat.groups, d["raro"])
        if m is not None and not d["raro"]:
            for nom in d["nombres"]:
                esp += f" @{nom}={pat.groupindex[nom]},{cps(m.group(nom) or '')}"
        elif m is None or d["raro"]:
            for nom in d["nombres"]:
                if m is not None:
                    pass
        g = got.get(("B", k))
        n += 1
        if d["raro"]:
            if g is None or g.split(" ")[:2] != esp.split(" ")[:2]:
                errores.append(f"B {k}: salió {g!r:.150} y se esperaba {esp!r:.150} (primer calce) {d['p']!r} {d['f']!r} {t!r} {d['modo']}")
        elif g != esp:
            errores.append(f"B {k}: salió {g!r:.150} y se esperaba {esp!r:.150} {d['p']!r} {d['f']!r} {t!r} {d['modo']}")
    for k, d in enumerate(casos["todas"]):
        pat = py_compila(d["p"], d["f"])
        t = d["t"]
        ms = list(pat.finditer(t))
        partes = [str(len(ms))] + ["|" + describe(m, pat.groups, d["raro"]) for m in ms]
        g = got.get(("T", k))
        n += 1
        if d["raro"]:
            esp = " ".join(partes)
            gg = (g or "").split(" ")
            ok = gg[:1] == esp.split(" ")[:1]
            if ok:
                # compara el primer calce y el largo nada más
                ok = True
            if not ok:
                errores.append(f"T {k}: salió {g!r:.150} y se esperaba {esp!r:.150}")
        else:
            esp = " ".join(partes)
            if g != esp:
                errores.append(f"T {k}: salió {g!r:.150} y se esperaba {esp!r:.150} {d['p']!r} {d['f']!r} {t!r}")
        igual("N", k, str(len(ms)))
        igual("E", k, f"{len(ms)} " + "".join(cps(m.group(0)) + " " for m in ms))
    for k, d in enumerate(casos["sub"]):
        pat = py_compila(d["p"], d["f"])
        t = d["t"]
        try:
            esp = "OK " + cps(pat.sub(d["tpl"], t, d["n"]))
        except (re.error, IndexError):
            esp = "ERR"
        igual("S", k, esp, f"{d['p']!r} {d['tpl']!r} {t!r} n={d['n']}")
        lit = d["lit"]
        igual("SL", k, cps(pat.sub(lambda m: lit, t, d["n"])), f"{d['p']!r} {lit!r} {t!r}")
    for k, d in enumerate(casos["split"]):
        pat = py_compila(d["p"], d["f"])
        r = pat.split(d["t"], d["n"])
        igual("P", k, f"{len(r)}" + "".join(" " + cps(x or "") for x in r), f"{d['p']!r} {d['t']!r} n={d['n']}")
    for k, s in enumerate(casos["escape"]):
        igual("X", k, cps(re.escape(s)))
    return errores, n


def main():
    if sys.version_info < (3, 11) or C is None:
        print("OK: lib/patron se omite (hace falta Python 3.11 o más nuevo)")
        return 0
    rng = random.Random(int(os.environ.get("SCAR_SEMILLA", "20")))
    casos = casos_al_azar(rng)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(casos, f, ensure_ascii=False)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/patron_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_patron_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_patron_python: FALLA, el programa terminó con", r.returncode)
            return 1
    got = leer(r.stdout)
    errores, comparaciones = comparar(casos, got)
    if errores:
        print("\n".join(errores[:25]))
        print(f"test_patron_python: FALLA ({len(errores)} diferencias)")
        return 1
    # autocomprobación: el comparador tiene que notar un resultado estropeado
    malo = dict(got)
    for clave in [k for k in malo if k[0] == "B" and malo[k].startswith("OK")][:1]:
        malo[clave] = malo[clave].replace("OK ", "OK 9", 1)
    for clave in [k for k in malo if k[0] == "S" and malo[k].startswith("OK")][:1]:
        malo[clave] = malo[clave] + ",33"
    for clave in [k for k in malo if k[0] == "P"][:1]:
        malo[clave] = malo[clave] + " 99"
    if not comparar(casos, malo)[0]:
        print("test_patron_python: FALLA, la autocomprobación no notó un resultado estropeado")
        return 1
    n = sum(len(casos[k]) for k in casos)
    print(f"OK: lib/patron contra re de Python: {n} casos, {comparaciones} comparaciones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
