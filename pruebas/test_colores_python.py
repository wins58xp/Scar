"""lib/colores contra colorsys, scikit-image y matplotlib.

    python3 pruebas/test_colores_python.py

Python inventa colores al azar (con casos de borde: negro, blanco, grises, los primarios,
con y sin alfa) y los escribe en casos.json. pruebas/colores_python.scar los procesa con
lib/colores y Python repite todo por su cuenta:

  - HSV y HSL contra colorsys, CIE Lab contra skimage.color.rgb2lab y lab2rgb, Oklab contra
    una implementación aparte de las fórmulas de Ottosson (y sus valores publicados para
    rojo, verde y azul), y las vueltas de cada uno;
  - mezclar (en sRGB y en Oklab), aclarar, oscurecer, saturar, girar el tono, invertir,
    gris y complementario, luminancia y contraste WCAG, el texto que se lee mejor, la
    diferencia CIEDE2000 contra skimage.color.deltaE_ciede2000 y el nombre más cercano;
  - la simulación de daltonismo contra una implementación aparte con numpy;
  - de_hex contra matplotlib.colors.to_rgba, los 148 nombres de CSS contra
    matplotlib.colors.CSS4_COLORS, las paletas contra matplotlib.colormaps y los mapas de
    color contra cmap(t, bytes=True), incluidos t fuera de rango y nombres que no existen;
  - degradados de varios colores y paleta_n.

Los colores que salen de un cálculo con decimales se aceptan si cada canal es el redondeo
de lo esperado (o el vecino, cuando el valor cae a menos de 1e-9 de la mitad); lo demás
tiene que dar exacto. También se comprueba que el comparador detecta un canal corrido en 1.
"""

import colorsys
import warnings
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore", message=".*negative Z values.*")


def hexa(c):
    return "#%02x%02x%02x%02x" % tuple(c)


def aceptables(f):
    """Los bytes que son el redondeo de f (0 a 1), con el vecino si cae en la mitad."""
    x = min(1.0, max(0.0, f)) * 255.0
    base = math.floor(x + 0.5)
    if abs(x - math.floor(x) - 0.5) < 1e-9:
        return {math.floor(x), math.floor(x) + 1}
    return {base}


def canales(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5, 7)]


def lin(u):
    return u / 12.92 if u <= 0.04045 else ((u + 0.055) / 1.055) ** 2.4


def gam(u):
    return 12.92 * u if u <= 0.0031308 else 1.055 * u ** (1 / 2.4) - 0.055


def a_oklab(rgb):
    r, g, b = (lin(v / 255) for v in rgb)
    l = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
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


def lum(rgb):
    r, g, b = (lin(v / 255) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


MATRICES = {
    "protanopia": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deuteranopia": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritanopia": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
    "acromatopsia": [[0.2126, 0.7152, 0.0722]] * 3,
}


def simular(rgb, tipo, k):
    v = np.array([lin(x / 255) for x in rgb])
    m = np.eye(3) + k * (np.array(MATRICES[tipo]) - np.eye(3))
    return tuple(gam(min(1.0, max(0.0, x))) for x in m @ v)


def casos_al_azar(rng):
    c = dict(colores=[], pares=[], inversos=[], hex=[], nombres=[], mapas=[], paletas=[], degradados=[])

    def col(alfa=True):
        return [rng.randrange(256), rng.randrange(256), rng.randrange(256), rng.randrange(256) if alfa and rng.random() < 0.3 else 255]

    bordes = [[0, 0, 0, 255], [255, 255, 255, 255], [128, 128, 128, 255], [255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255],
              [255, 255, 0, 255], [0, 255, 255, 255], [255, 0, 255, 255], [1, 1, 1, 255], [254, 254, 254, 255], [10, 20, 30, 0],
              [100, 100, 101, 255], [200, 50, 50, 128]]
    # colores muy oscuros, donde Lab cambia de fórmula (los canales XYZ entre 0.0088 y 0.00886)
    oscuros = [[0, 7, 58, 255], [0, 22, 24, 255], [26, 18, 27, 255], [59, 36, 20, 255], [59, 53, 15, 255], [22, 22, 22, 255], [23, 23, 23, 255],
               [24, 24, 24, 255], [25, 25, 25, 255], [20, 30, 25, 255], [30, 25, 20, 255], [0, 0, 1, 255], [1, 0, 0, 255], [0, 1, 0, 255]]
    c["colores"] = bordes + oscuros + [col() for _ in range(120)]
    for _ in range(80):
        c["pares"].append(dict(a=col(), b=col(), t=rng.choice([0.0, 1.0, 0.5, -0.4, 1.6, rng.random(), rng.random(), rng.random()])))
    c["pares"].append(dict(a=[255, 255, 255, 255], b=[0, 0, 0, 255], t=0.5))
    c["pares"].append(dict(a=[255, 0, 0, 255], b=[0, 0, 255, 255], t=0.5))
    for _ in range(200):
        c["inversos"].append(dict(hsv=[rng.uniform(-400, 800), rng.uniform(-0.2, 1.3), rng.uniform(-0.2, 1.3)],
                                  hsl=[rng.uniform(-400, 800), rng.uniform(-0.2, 1.3), rng.uniform(-0.2, 1.3)],
                                  lab=[rng.uniform(-5, 105), rng.uniform(-110, 110), rng.uniform(-110, 110)],
                                  ok=[rng.uniform(-0.1, 1.1), rng.uniform(-0.45, 0.45), rng.uniform(-0.45, 0.45)]))
    for L in (7.9989, 7.9992, 7.9995, 7.9998, 8.0, 8.0003):
        c["inversos"].append(dict(hsv=[0, 0, 0], hsl=[0, 0, 0], lab=[L, rng.uniform(-3, 3), rng.uniform(-3, 3)], ok=[0.1, 0, 0]))
        c["inversos"].append(dict(hsv=[0, 0, 0], hsl=[0, 0, 0], lab=[L + 20.0, 0.0, 0.0], ok=[0.1, 0, 0]))
    c["hex"] = ["#abc", "abc", "#ABCD", "#aabbcc", "AABBCC", "#AABBCCDD", "aabbccdd", "#ab", "#abcde", "#abcdefg", "#ggg", "", "#", "# 123",
                "#12345", "#1234567", "#fff0", "#FF8000", "ff8000", "#00000000", "#ffffffff", "#12", "xyz", "#0a0"]
    for _ in range(30):
        c["hex"].append("#" + "".join(rng.choice("0123456789abcdefABCDEF") for _ in range(rng.choice([3, 4, 6, 8]))))
    c["nombres"] = ["red", "RED", "Red", " blue ", "rebeccapurple", "LightGoldenRodYellow", "grey", "gray", "darkslategray", "notacolor", "",
                    "gris", "orange red", "transparent", "#ff0000", "navy", "Tomato", "yellowgreen", "whitesmoke", "aliceblue"]
    nombres_mapas = ["viridis", "magma", "inferno", "plasma", "cividis", "turbo", "coolwarm", "rdbu", "spectral", "ylgnbu", "greys", "hot"]
    ts = [0.0, 1.0, 0.5, 0.999999, 1e-9, -0.3, 1.7, 1 / 256, 255 / 256, 0.25, 0.75, 0.0039, 0.0040] + [rng.random() for _ in range(40)] + [k / 255 for k in range(0, 256, 5)]
    for n in nombres_mapas + ["Viridis", "VIRIDIS", "jet", "nada", ""]:
        c["mapas"].append(dict(nombre=n, t=ts))
    nombres_pal = ["tab10", "tab20", "set1", "set2", "set3", "dark2", "paired", "accent", "pastel1", "pastel2", "okabe_ito"]
    for n in nombres_pal + ["Tab10", "nada", ""]:
        c["paletas"].append(dict(nombre=n, i=[0, 1, 2, 7, 8, 9, 10, 11, 19, 20, 21, 25, -1, -5, 100]))
    for _ in range(30):
        n = rng.choice([0, 1, 2, 2, 3, 4, 5])
        c["degradados"].append(dict(c=[col() for _ in range(n)], t=[-0.2, 0.0, 0.2, 0.25, 0.5, 0.75, 0.99, 1.0, 1.3, rng.random(), rng.random()]))
    return c


def leer(stdout):
    r = {}
    for linea in stdout.splitlines():
        p = linea.split(" ", 2)
        if len(p) >= 2 and p[0].isupper() or (len(p) >= 2 and p[0][:-1].isupper() and p[0][-1].isdigit()):
            if p[1].isdigit():
                r[(p[0], int(p[1]))] = p[2] if len(p) == 3 else ""
    return r


def main():
    global np
    try:
        import numpy as np
        import matplotlib
        import matplotlib.colors as mc
        from matplotlib import colormaps
        from skimage import color as sk
    except ImportError:
        print("OK: test_colores_python se omite (sin numpy, matplotlib y scikit-image en esta máquina)")
        return 0
    rng = random.Random(27)
    casos = casos_al_azar(rng)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(casos, f)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/colores_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_colores_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_colores_python: FALLA, el programa terminó con", r.returncode)
            return 1
    got = leer(r.stdout)
    errores = []
    comparaciones = 0

    def exacto(etiqueta, k, esperado):
        nonlocal comparaciones
        comparaciones += 1
        g = got.get((etiqueta, k))
        if g != esperado:
            errores.append(f"{etiqueta} {k}: salió {g!r:.90} y se esperaba {esperado!r:.90}")

    def numeros(etiqueta, k, esperado, tol, cíclico=None):
        nonlocal comparaciones
        comparaciones += 1
        g = got.get((etiqueta, k))
        if g is None:
            errores.append(f"{etiqueta} {k}: no salió")
            return
        v = [float(x) for x in g.split()]
        if len(v) != len(esperado):
            errores.append(f"{etiqueta} {k}: {len(v)} valores y se esperaban {len(esperado)}")
            return
        for i, (a, e) in enumerate(zip(v, esperado)):
            d = abs(a - e)
            if cíclico is not None and i == 0:
                d = min(d, cíclico - d)
            if d > tol * max(1.0, abs(e)):
                errores.append(f"{etiqueta} {k}: valor {i} salió {a!r} y se esperaba {e!r}")
                return

    def color(etiqueta, k, flotantes, alfa, g=None):
        """Un color con canales decimales esperados (0 a 1) y alfa entero."""
        nonlocal comparaciones
        comparaciones += 1
        if g is None:
            g = got.get((etiqueta, k))
        if g is None or not re.fullmatch(r"#[0-9a-f]{8}", g):
            errores.append(f"{etiqueta} {k}: salió {g!r}")
            return
        ch = canales(g)
        for i in range(3):
            if ch[i] not in aceptables(flotantes[i]):
                errores.append(f"{etiqueta} {k}: canal {i} salió {ch[i]} y se esperaba uno de {sorted(aceptables(flotantes[i]))} ({g})")
                return
        if ch[3] != alfa:
            errores.append(f"{etiqueta} {k}: alfa {ch[3]} y se esperaba {alfa}")

    # el comparador tiene que notar un canal corrido en 1
    antes = len(errores)
    color("MUT", 0, (0.5, 0.5, 0.5), 255, g="#808090ff")
    if len(errores) != antes + 1:
        print("test_colores_python: FALLA, el comparador no detecta un canal corrido")
        return 1
    errores.pop()

    for k, c in enumerate(casos["colores"]):
        rgb, a = c[:3], c[3]
        r, g, b = (v / 255 for v in rgb)
        exacto("HEX", k, hexa(c))
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        numeros("HSV", k, [h * 360, s, v], 1e-12, cíclico=360.0)
        h2, l2, s2 = colorsys.rgb_to_hls(r, g, b)
        numeros("HSL", k, [h2 * 360, s2, l2], 1e-12, cíclico=360.0)
        lab = sk.rgb2lab(np.array([[[r, g, b]]]))[0, 0]
        numeros("LAB", k, list(lab), 1e-9)
        ok = a_oklab(rgb)
        numeros("OKLAB", k, list(ok), 1e-12)
        color("VUELTAHSV", k, (r, g, b), a)
        color("VUELTAHSL", k, (r, g, b), a)
        color("VUELTALAB", k, (r, g, b), a)
        color("VUELTAOK", k, (r, g, b), a)
        numeros("LUM", k, [lum(rgb)], 1e-12)
        y = gam(lum(rgb))
        color("GRIS", k, (y, y, y), a)
        exacto("INV", k, hexa([255 - rgb[0], 255 - rgb[1], 255 - rgb[2], a]))
        hh, ll, ss = h2, l2, s2

        def de_hls(h_, l_, s_):
            return colorsys.hls_to_rgb((h_ % 360) / 360, min(1, max(0, l_)), min(1, max(0, s_)))
        color("COMP", k, de_hls(hh * 360 + 180, ll, ss), a)
        ver = got.get(("SAT", k), "").split()
        if len(ver) == 2:
            color("SAT", k, de_hls(hh * 360, ll, ss * 0.5), a, ver[0])
            color("SAT", k, de_hls(hh * 360, ll, ss * 1.7), a, ver[1])
        else:
            errores.append(f"SAT {k}: {ver}")
        ver = got.get(("GIRO", k), "").split()
        if len(ver) == 2:
            color("GIRO", k, de_hls(hh * 360 + 37, ll, ss), a, ver[0])
            color("GIRO", k, de_hls(hh * 360 - 200, ll, ss), a, ver[1])
        else:
            errores.append(f"GIRO {k}: {ver}")
        negro_c, blanco_c = contraste(rgb, [0, 0, 0]), contraste(rgb, [255, 255, 255])
        exacto("TEXTO", k, "#000000ff" if negro_c >= blanco_c else "#ffffffff")
        exacto("GUI", k, str((c[0] << 16) | (c[1] << 8) | c[2]))
        for i, tipo in enumerate(["protanopia", "deuteranopia", "tritanopia"]):
            ver = got.get((f"DALT{i}", k), "").split()
            if len(ver) == 3:
                color(f"DALT{i}", k, simular(rgb, tipo, 1.0), a, ver[0])
                color(f"DALT{i}", k, simular(rgb, tipo, 0.4), a, ver[1])
                exacto(f"DALT{i}", k, f"{ver[0]} {ver[1]} {hexa(c)}")
            else:
                errores.append(f"DALT{i} {k}: {ver}")
        color("DALTA", k, simular(rgb, "acromatopsia", 1.0), a)
        exacto("DALTX", k, "ERR")
        # nombre más cercano: el que salga tiene que estar a la distancia mínima
        nombre = got.get(("CERCANO", k))
        if nombre not in mc.CSS4_COLORS:
            errores.append(f"CERCANO {k}: {nombre!r}")
        else:
            comparaciones += 1
            lista = sorted(mc.CSS4_COLORS.items())
            labs = sk.rgb2lab(np.array([[mc.to_rgb(h_) for _, h_ in lista]]))
            d = sk.deltaE_ciede2000(np.repeat(lab[None, None, :], len(lista), axis=1), labs)[0]
            mio = [n for n, _ in lista].index(nombre)
            if d[mio] > d.min() + 1e-9:
                errores.append(f"CERCANO {k}: {nombre} está a {d[mio]:.4f} y lo mejor era {lista[int(d.argmin())][0]} a {d.min():.4f}")

    # los valores publicados de Oklab para rojo, verde y azul
    for rgb, esp in (([255, 0, 0], (0.62796, 0.22486, 0.12585)), ([0, 255, 0], (0.86644, -0.23389, 0.17950)), ([0, 0, 255], (0.45201, -0.03246, -0.31153)), ([255, 255, 255], (1.0, 0.0, 0.0))):
        if max(abs(a - b) for a, b in zip(a_oklab(rgb), esp)) > 1e-4:
            errores.append(f"el Oklab de {rgb} no da lo publicado {esp}")

    for k, c in enumerate(casos["pares"]):
        a, b, t = c["a"], c["b"], min(1.0, max(0.0, c["t"]))
        ch = [math.floor(a[i] + (b[i] - a[i]) * t + 0.5) for i in range(4)]
        exacto("MEZ", k, hexa(ch))
        oa, ob = a_oklab(a[:3]), a_oklab(b[:3])
        mix = de_oklab(*(oa[i] + (ob[i] - oa[i]) * t for i in range(3)))
        color("MEZOK", k, mix, ch[3])
        blanco = [math.floor(a[i] + (255 - a[i]) * t + 0.5) for i in range(3)]
        negro = [math.floor(a[i] + (0 - a[i]) * t + 0.5) for i in range(3)]
        exacto("ACL", k, hexa(blanco + [a[3]]) + " " + hexa(negro + [a[3]]))
        numeros("CONTR", k, [contraste(a[:3], b[:3])], 1e-12)
        la = sk.rgb2lab(np.array([[[v / 255 for v in a[:3]]]]))
        lb = sk.rgb2lab(np.array([[[v / 255 for v in b[:3]]]]))
        numeros("DE", k, [float(sk.deltaE_ciede2000(la, lb)[0, 0])], 1e-8)

    for k, c in enumerate(casos["inversos"]):
        hh, sy, vz = c["hsv"]
        color("IHSV", k, colorsys.hsv_to_rgb((hh % 360) / 360, min(1, max(0, sy)), min(1, max(0, vz))), 255)
        hh, sy, lz = c["hsl"]
        color("IHSL", k, colorsys.hls_to_rgb((hh % 360) / 360, min(1, max(0, lz)), min(1, max(0, sy))), 255)
        color("ILAB", k, tuple(sk.lab2rgb(np.array([[c["lab"]]]))[0, 0]), 255)
        color("IOK", k, de_oklab(*c["ok"]), 255)

    for k, h_ in enumerate(casos["hex"]):
        if re.fullmatch(r"#?([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", h_):
            rgba = mc.to_rgba(h_ if h_.startswith("#") else "#" + h_)
            exacto("DHEX", k, hexa([round(v * 255) for v in rgba]))
        else:
            exacto("DHEX", k, "ERR")

    css = sorted(mc.CSS4_COLORS.items())
    for k, n in enumerate(casos["nombres"]):
        clave = n.strip().lower()
        if clave in mc.CSS4_COLORS:
            exacto("NOM", k, hexa([round(v * 255) for v in mc.to_rgba(mc.CSS4_COLORS[clave])]))
        else:
            exacto("NOM", k, "ERR")
    for i, (n, h_) in enumerate(css):
        exacto("TODOS", i, f"{n} " + hexa([round(v * 255) for v in mc.to_rgba(h_)]))

    mapas_mpl = {"viridis": "viridis", "magma": "magma", "inferno": "inferno", "plasma": "plasma", "cividis": "cividis", "turbo": "turbo",
                 "coolwarm": "coolwarm", "rdbu": "RdBu", "spectral": "Spectral", "ylgnbu": "YlGnBu", "greys": "Greys", "hot": "hot"}
    for k, c in enumerate(casos["mapas"]):
        n = c["nombre"].lower()
        if n in mapas_mpl:
            cm = colormaps[mapas_mpl[n]]
            esp = "OK" + "".join(" " + hexa(list(map(int, cm(min(1.0, max(0.0, t)), bytes=True)))) for t in c["t"])
        else:
            esp = "ERR"
        exacto("MAPA", k, esp)
    for i, n in enumerate(mapas_mpl):
        exacto("NMAPA", i, n)

    cats = {n: [mc.to_hex(x) for x in colormaps[m].colors] for n, m in
            [("tab10", "tab10"), ("tab20", "tab20"), ("set1", "Set1"), ("set2", "Set2"), ("set3", "Set3"), ("dark2", "Dark2"),
             ("paired", "Paired"), ("accent", "Accent"), ("pastel1", "Pastel1"), ("pastel2", "Pastel2")]}
    cats["okabe_ito"] = ["#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2", "#d55e00", "#cc79a7", "#000000"]
    for k, c in enumerate(casos["paletas"]):
        n = c["nombre"].lower()
        if n in cats:
            v = cats[n]
            esp = f"OK {len(v)}" + "".join(" " + v[i % len(v)] + "ff" for i in c["i"])
        else:
            esp = "ERR"
        exacto("PAL", k, esp)
    for i, n in enumerate(cats):
        exacto("NPAL", i, n)

    for k, c in enumerate(casos["degradados"]):
        cols, ts = c["c"], c["t"]
        n = len(cols)
        partes = []
        ver = got.get(("DEG", k), "").split()
        if len(ver) != 2 * len(ts):
            errores.append(f"DEG {k}: {len(ver)} colores y se esperaban {2 * len(ts)}")
            continue
        for j, t in enumerate(ts):
            if n == 0:
                esp_s = esp_o = "#000000ff"
                comparaciones += 1
                if ver[2 * j] != esp_s or ver[2 * j + 1] != esp_o:
                    errores.append(f"DEG {k}: con la lista vacía salió {ver[2*j:2*j+2]}")
                continue
            if n == 1:
                comparaciones += 1
                if ver[2 * j] != hexa(cols[0]) or ver[2 * j + 1] != hexa(cols[0]):
                    errores.append(f"DEG {k}: con un color salió {ver[2*j:2*j+2]}")
                continue
            u = min(1.0, max(0.0, t)) * (n - 1)
            i = min(math.floor(u), n - 2)
            f = u - i
            a, b = cols[i], cols[i + 1]
            ch = [math.floor(a[q] + (b[q] - a[q]) * f + 0.5) for q in range(4)]
            comparaciones += 1
            if ver[2 * j] != hexa(ch):
                errores.append(f"DEG {k} t={t}: sRGB salió {ver[2*j]} y se esperaba {hexa(ch)}")
            oa, ob = a_oklab(a[:3]), a_oklab(b[:3])
            mix = de_oklab(*(oa[q] + (ob[q] - oa[q]) * f for q in range(3)))
            color("DEG", k, mix, ch[3], ver[2 * j + 1])

    for n in range(1, 13):
        ver = got.get(("PALN", n), "").split()
        if len(ver) != n:
            errores.append(f"PALN {n}: {len(ver)} colores")
            continue
        for i in range(n):
            h_ = math.radians(360 * i / n + 29)
            color("PALN", n, de_oklab(0.72, 0.13 * math.cos(h_), 0.13 * math.sin(h_)), 255, ver[i])
        labs = sk.rgb2lab(np.array([[[v / 255 for v in canales(x)[:3]] for x in ver]]))
        if n > 1:
            mn = min(float(sk.deltaE_ciede2000(labs[:, i:i + 1], labs[:, j:j + 1])[0, 0]) for i in range(n) for j in range(i + 1, n))
            if mn < 5.0:
                errores.append(f"PALN {n}: dos colores se parecen demasiado (ΔE {mn:.2f})")

    if errores:
        print("\n".join(errores[:20]))
        print(f"test_colores_python: FALLA ({len(errores)} diferencias)")
        return 1
    n = sum(len(casos[k]) for k in casos)
    print(f"OK: lib/colores contra colorsys, scikit-image y matplotlib: {n} casos, {comparaciones} comparaciones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
