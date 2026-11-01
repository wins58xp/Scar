"""lib/ansi contra una referencia en Python.

    python3 pruebas/test_ansi_python.py

Python inventa colores y textos al azar (con secuencias de escape ya puestas, bien y mal
terminadas, y con ñ, tildes y emojis) y los escribe en casos.json. pruebas/ansi_python.scar
los procesa con lib/ansi y Python arma por su cuenta lo esperado:

  - las secuencias de 24 bits, de 256 y de 16 colores, letra por letra, y los estilos
    (negrita, tenue, cursiva, subrayado, invertido, tachado) con su cierre;
  - la paleta de 256 de xterm (el cubo de 6 x 6 x 6 y los 24 grises) y la de 16;
  - a_256 y a_16: el color más cercano por distancia en RGB, buscado a la fuerza entre
    todas las entradas (a igual distancia, el número más bajo);
  - quitar (una expresión regular de las secuencias CSI; las que no terminan se dejan) y
    largo_visible, rellenar_der;
  - degradado_texto y barra: se separan los colores de los caracteres y se comprueba cada
    canal contra la mezcla en Oklab (con la tolerancia de redondeo de test_colores_python).
"""

import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESC = "\x1b"


def lin(u):
    return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4


def gam(u):
    return 12.92 * u if u <= 0.0031308 else 1.055 * u ** (1 / 2.4) - 0.055


def cbrt(x):
    return math.copysign(abs(x) ** (1 / 3), x)


def a_oklab(rgb):
    r, g, b = (lin(v / 255) for v in rgb)
    l = cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def de_oklab(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return tuple(gam(min(1.0, max(0.0, v))) for v in (r, g, bb))


def aceptables(f):
    x = min(1.0, max(0.0, f)) * 255.0
    if abs(x - math.floor(x) - 0.5) < 1e-9:
        return {math.floor(x), math.floor(x) + 1}
    return {math.floor(x + 0.5)}


XTERM16 = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
           (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
NIVELES = [0, 95, 135, 175, 215, 255]


def xterm256():
    t = list(XTERM16)
    for i in range(216):
        t.append((NIVELES[i // 36], NIVELES[(i // 6) % 6], NIVELES[i % 6]))
    for i in range(24):
        t.append((8 + 10 * i,) * 3)
    return t


def mas_cercano(rgb, tabla, desde):
    mejor, dmin = None, None
    for i in range(desde, len(tabla)):
        d = sum((a - b) ** 2 for a, b in zip(rgb, tabla[i]))
        if dmin is None or d < dmin:
            mejor, dmin = i, d
    return mejor


def hexa(rgb):
    return "#%02x%02x%02xff" % tuple(rgb)


def casos_al_azar(rng):
    c = dict(colores=[], textos=[], degradados=[], barras=[])
    bordes = [[0, 0, 0], [255, 255, 255], [128, 128, 128], [255, 0, 0], [0, 255, 0], [0, 0, 255], [75, 75, 75], [115, 115, 115],
              [95, 135, 175], [8, 8, 8], [7, 7, 7], [238, 238, 238], [248, 248, 248], [13, 13, 13], [18, 18, 18], [47, 47, 47], [127, 127, 127]]
    c["colores"] = bordes + [[rng.randrange(256) for _ in range(3)] for _ in range(150)]
    c["colores"] += [[0, 0, 12], [0, 1, 11], [1, 1, 10], [3, 2, 7], [0, 2, 10]]  # a igual distancia del cubo y de los grises
    for v in (75, 115, 155, 195, 235, 3, 13, 23):  # justo en el medio entre dos niveles
        c["colores"].append([v, v, v])
        c["colores"].append([v, 0, 255])
    c["textos"] = ["", "hola", "año ñandú", "emoji 😀 y más", "  con espacios  ", "x", ESC + "[31mrojo" + ESC + "[0m", ESC + "[38;2;1;2;3mx" + ESC + "[39m",
                   "a" + ESC + "[1;4mb" + ESC + "[0mc", ESC + "[12", ESC, "fin" + ESC + "[", ESC + "[m", ESC + "[2Kborra", ESC + "[1\x7fmdel", ESC + "[1 qcursor", ESC + "[?25l",
                   ESC + "[38;5;200mcolor" + ESC + "[0m" + ESC + "[1mnegrita" + ESC + "[22m", "ESC[31m sin escape real", "tab\ty", "12345678901234567890"]
    for _ in range(30):
        alfabeto = "abc ñé😀" + ESC + "[0123;m"
        c["textos"].append("".join(rng.choice(alfabeto) for _ in range(rng.randint(0, 20))))
    for s in ["a", "hola mundo", "de punta a punta", "ñandú 😀", "x y", "    ", ""]:
        c["degradados"].append(dict(s=s, a=[rng.randrange(256) for _ in range(3)], b=[rng.randrange(256) for _ in range(3)]))
    for _ in range(10):
        c["degradados"].append(dict(s="".join(rng.choice("abcd ") for _ in range(rng.randint(1, 30))), a=[rng.randrange(256) for _ in range(3)], b=[rng.randrange(256) for _ in range(3)]))
    for f in (0.0, 1.0, 0.5, 0.333, 0.999, -1.0, 2.0, 0.01):
        for w in (1, 2, 10, 30):
            c["barras"].append(dict(f=f, w=w, a=[rng.randrange(256) for _ in range(3)], b=[rng.randrange(256) for _ in range(3)]))
    return c


def leer(stdout):
    r = {}
    for linea in stdout.split("\n"):
        p = linea.split(" ", 2)
        if len(p) >= 2 and p[0].isalnum() and p[0].isupper() or (len(p) >= 2 and p[0][:-1].isupper() and p[0][-1].isdigit()):
            if p[1].isdigit():
                r[(p[0], int(p[1]))] = p[2] if len(p) == 3 else ""
    return r


def quitar(s):
    return re.sub(ESC + r"\[[\x20-\x3f]*[\x40-\x7e]", "", s)


def tokens(s):
    """Parte un texto en [(color_actual o None, carácter)] siguiendo solo ESC[38;2;r;g;bm y ESC[39m."""
    out, color, i = [], None, 0
    while i < len(s):
        m = re.match(ESC + r"\[38;2;(\d+);(\d+);(\d+)m", s[i:])
        if m:
            color = tuple(int(x) for x in m.groups())
            i += m.end()
            continue
        if s.startswith(ESC + "[39m", i):
            color = None
            i += 5
            continue
        out.append((color, s[i]))
        i += 1
    return out


def main():
    rng = random.Random(28)
    casos = casos_al_azar(rng)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(casos, f)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/ansi_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_ansi_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_ansi_python: FALLA, el programa terminó con", r.returncode)
            return 1
    got = leer(r.stdout)
    errores = []
    comparaciones = 0

    def igual(etiqueta, k, esperado):
        nonlocal comparaciones
        comparaciones += 1
        g = got.get((etiqueta, k))
        if g != esperado:
            errores.append(f"{etiqueta} {k}: salió {g!r:.100} y se esperaba {esperado!r:.100}")

    t256 = xterm256()
    for k, c in enumerate(casos["colores"]):
        r_, g_, b_ = c
        igual("FG", k, f"{ESC}[38;2;{r_};{g_};{b_}m")
        igual("BG", k, f"{ESC}[48;2;{r_};{g_};{b_}m")
        i256 = mas_cercano(c, t256, 16)
        i16 = mas_cercano(c, XTERM16, 0)
        igual("A256", k, str(i256))
        igual("A16", k, str(i16))
        igual("P", k, f"{ESC}[38;2;{r_};{g_};{b_}mx{ESC}[39m")
        igual("PF", k, f"{ESC}[48;2;{r_};{g_};{b_}mx{ESC}[49m")
        igual("P256", k, f"{ESC}[38;5;{i256}mx{ESC}[39m")
        igual("P16", k, f"{ESC}[{30 + i16 if i16 < 8 else 90 + i16 - 8}mx{ESC}[39m")

    for k, t in enumerate(casos["textos"]):
        for etiqueta, a, z in (("NEG", 1, 22), ("TEN", 2, 22), ("CUR", 3, 23), ("SUB", 4, 24), ("INV", 7, 27), ("TAC", 9, 29)):
            igual(etiqueta, k, f"{ESC}[{a}m{t}{ESC}[{z}m")
        igual("QUITAR", k, quitar(t))
        igual("LARGO", k, str(len(quitar(t))))
        igual("RELLENO", k, t + " " * max(0, 12 - len(quitar(t))) + "|")

    for i in range(256):
        igual("R256", i, "#%02x%02x%02x" % t256[i])
        igual("F256", i, f"{ESC}[38;5;{i}m{ESC}[48;5;{i}m")
    for i in range(16):
        igual("R16", i, "#%02x%02x%02x" % XTERM16[i])
        igual("F16", i, f"{ESC}[{30 + i if i < 8 else 90 + i - 8}m{ESC}[{40 + i if i < 8 else 100 + i - 8}m")
    igual("REI", 0, f"{ESC}[0m")
    igual("ESC", 0, "27")
    igual("FUERA", 0, f"{ESC}[38;5;255m{ESC}[48;5;0m{ESC}[97m{ESC}[40m")

    def color_ok(etiqueta, k, obtenido, esperado_f):
        nonlocal comparaciones
        comparaciones += 1
        for q in range(3):
            if obtenido[q] not in aceptables(esperado_f[q]):
                errores.append(f"{etiqueta} {k}: canal {q} salió {obtenido[q]} y se esperaba {sorted(aceptables(esperado_f[q]))}")
                return

    for k, c in enumerate(casos["degradados"]):
        s, a, b = c["s"], c["a"], c["b"]
        g = got.get(("DEG", k))
        if g is None or not g.endswith(f"{ESC}[39m"):
            errores.append(f"DEG {k}: salió {g!r}")
            continue
        toks = tokens(g)
        if [ch for _, ch in toks] != list(s):
            errores.append(f"DEG {k}: los caracteres son {''.join(ch for _, ch in toks)!r} y se esperaba {s!r}")
            continue
        oa, ob = a_oklab(a), a_oklab(b)
        n = len(s)
        for i, (col, ch) in enumerate(toks):
            if ch == " ":
                continue
            t = i / (n - 1) if n > 1 else 0.0
            esp = de_oklab(*(oa[q] + (ob[q] - oa[q]) * t for q in range(3)))
            if col is None:
                errores.append(f"DEG {k}: el carácter {i} no lleva color")
            else:
                color_ok("DEG", k, col, esp)

    for k, c in enumerate(casos["barras"]):
        f, w, a, b = c["f"], c["w"], c["a"], c["b"]
        g = got.get(("BARRA", k))
        llenas = math.floor(max(0.0, min(1.0, f)) * w)
        toks = tokens(g or "")
        if g is None or [ch for _, ch in toks] != ["█"] * llenas + ["░"] * (w - llenas):
            errores.append(f"BARRA {k}: salió {g!r:.100} con f={f} w={w}")
            continue
        oa, ob = a_oklab(a), a_oklab(b)
        for i in range(llenas):
            t = i / (w - 1) if w > 1 else 0.0
            color_ok("BARRA", k, toks[i][0], de_oklab(*(oa[q] + (ob[q] - oa[q]) * t for q in range(3))))
        for i in range(llenas, w):
            comparaciones += 1
            if toks[i][0] != (90, 90, 90):
                errores.append(f"BARRA {k}: la casilla vacía {i} tiene el color {toks[i][0]}")
        if not (g or "").endswith(f"{ESC}[39m"):
            errores.append(f"BARRA {k}: no restablece el color")

    if errores:
        print("\n".join(errores[:20]))
        print(f"test_ansi_python: FALLA ({len(errores)} diferencias)")
        return 1
    n = sum(len(casos[k]) for k in casos)
    print(f"OK: lib/ansi contra la referencia en Python: {n} casos, {comparaciones} comparaciones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
