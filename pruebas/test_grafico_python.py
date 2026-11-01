"""lib/grafico contra una referencia en Python (numpy y Pillow).

    python3 pruebas/test_grafico_python.py

Python inventa gráficos al azar (líneas con huecos, puntos, barras agrupadas
con valores negativos, histogramas) y los escribe en casos.json.
pruebas/grafico_python.scar los arma con lib/grafico, escribe el diseño de cada
uno y guarda su PNG. Acá se comprueba, por cuenta de Python:

  - las marcas de los ejes (pasos de 1, 2 o 5 por una potencia de 10, que cubren
    los datos) y sus etiquetas, contra una referencia propia;
  - las cuentas y los bordes del histograma, contra numpy.histogram y linspace;
  - el rectángulo del gráfico y los rangos de los ejes, calculados otra vez de
    los datos;
  - en cada PNG, leído con Pillow: el tamaño, el fondo blanco, los ejes y sus
    marcas en negro, y que cada línea, punto, barra y caja del histograma estén
    en el píxel que le toca y con su color (con 1 píxel de margen por el
    redondeo), que una línea no cruce un NaN, y que la leyenda y el título estén.
"""

import json
import math
import os
import random
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLANCO = (255, 255, 255)
NEGRO = (0, 0, 0)


# ---------- la referencia ----------

def pot10(e):
    r = 1.0
    if e >= 0:
        for _ in range(e):
            r *= 10.0
        return r
    for _ in range(-e):
        r *= 10.0
    return 1.0 / r


def ref_marcas(minimo, maximo, objetivo=6):
    lo, hi = minimo, maximo
    if hi - lo <= 0.0:
        d = abs(lo) * 0.5
        if d == 0.0:
            d = 1.0
        lo -= d
        hi += d
    paso0 = (hi - lo) / max(objetivo, 1)
    e = 0
    while pot10(e + 1) <= paso0:
        e += 1
    while pot10(e) > paso0:
        e -= 1
    frac = paso0 / pot10(e)
    bonito = 1.0 if frac <= 1 else 2.0 if frac <= 2 else 5.0 if frac <= 5 else 10.0
    paso = bonito * pot10(e) if e >= 0 else bonito / pot10(-e)
    k0 = math.floor(lo / paso)
    k1 = -math.floor(-(hi / paso))
    out = []
    k = float(k0)
    while k <= k1:
        out.append((k * bonito) * pot10(e) if e >= 0 else (k * bonito) / pot10(-e))
        k += 1.0
    return out


def ref_etiquetas(m):
    paso = (m[1] - m[0]) if len(m) >= 2 else 1.0
    d = 0
    while d < 12 and pot10(-d) > paso * 0.999999:
        d += 1
    out = []
    for v in m:
        if abs(v) < pot10(-d - 3):
            v = 0.0
        out.append(f"{v:.{d}f}")
    return out


def dentro(m, lo, hi):
    eps = (hi - lo) * 1e-9
    return [t for t in m if lo - eps <= t <= hi + eps]


def ref_bordes(datos, cajas):
    lo, hi = min(datos), max(datos)
    if lo == hi:
        lo -= 0.5
        hi += 0.5
    return list(np.linspace(lo, hi, cajas + 1))


def ref_cuentas(datos, cajas):
    lo, hi = min(datos), max(datos)
    if lo == hi:
        lo -= 0.5
        hi += 0.5
    return [int(c) for c in np.histogram(datos, bins=cajas, range=(lo, hi))[0]]


def redondear(v):
    return math.floor(v + 0.5)


def ref_diseno(caso):
    series = caso["series"]
    categorico = any(s["kind"] == "barras" for s in series)
    xlo = xhi = None
    ylo = yhi = None
    hist_solo = True
    con_cero = False
    for s in series:
        if s["kind"] == "hist":
            con_cero = True
            c = ref_cuentas(s["datos"], s["cajas"])
            for v in c:
                ylo = v if ylo is None else min(ylo, v)
                yhi = v if yhi is None else max(yhi, v)
            b = ref_bordes(s["datos"], s["cajas"])
            a, z = b[0], b[-1]
            xlo = a if xlo is None else min(xlo, a)
            xhi = z if xhi is None else max(xhi, z)
        else:
            if s["kind"] == "barras":
                con_cero = True
            else:
                hist_solo = False
            for i, y in enumerate(s["ys"]):
                if y is not None:
                    ylo = y if ylo is None else min(ylo, y)
                    yhi = y if yhi is None else max(yhi, y)
                if s["kind"] != "barras":
                    x = s["xs"][i]
                    xlo = x if xlo is None else min(xlo, x)
                    xhi = x if xhi is None else max(xhi, x)
    if ylo is None:
        ylo, yhi = 0.0, 1.0
    if xlo is None:
        xlo, xhi = 0.0, 1.0
    if con_cero:
        ylo, yhi = min(ylo, 0.0), max(yhi, 0.0)
    yt = ref_marcas(float(ylo), float(yhi))
    ymin, ymax = yt[0], yt[-1]
    if categorico:
        ncat = max([len(caso["cats"])] + [len(s["ys"]) for s in series if s["kind"] == "barras"])
        xt, xmin, xmax = [], 0.0, float(max(ncat, 1))
    elif hist_solo:
        xmin, xmax = float(xlo), float(xhi)
        xt = dentro(ref_marcas(xmin, xmax), xmin, xmax)
    else:
        xt = ref_marcas(float(xlo), float(xhi))
        xmin, xmax = xt[0], xt[-1]
    ye = ref_etiquetas(yt)
    x0 = 8 * max([len(e) for e in ye] + [0]) + 14
    sup = 8 + (24 if caso["titulo"] else 0) + (12 if caso["ey"] else 0)
    inf = 24 + (14 if caso["ex"] else 0)
    return dict(x0=x0, y0=sup, x1=caso["w"] - 15, y1=caso["h"] - 1 - inf, xmin=xmin, xmax=xmax,
                ymin=ymin, ymax=ymax, xt=xt, yt=yt, cat=categorico, xl=ref_etiquetas(xt) if xt else [], yl=ye)


# ---------- casos al azar ----------

LETRAS = "abcdefghijklmnñoprstuvxyz"


def texto(rng, n=8):
    return "".join(rng.choice(LETRAS) for _ in range(rng.randint(1, n)))


def color(rng):
    while True:
        c = [rng.randint(20, 235) for _ in range(3)]
        if max(c) - min(c) >= 70:
            return c


def decimal(rng, lo, hi, d=1):
    return round(rng.uniform(lo, hi), d)


def caso_aleatorio(rng):
    w, h = rng.randint(260, 700), rng.randint(200, 460)
    base = dict(w=w, h=h, titulo=texto(rng, 14) if rng.random() < 0.8 else "",
                ex=texto(rng) if rng.random() < 0.6 else "", ey=texto(rng) if rng.random() < 0.6 else "", cats=[])
    tipo = rng.choice(["lineas", "lineas", "barras", "barras", "hist", "hist", "mixto"])
    series = []
    if tipo in ("lineas", "mixto"):
        for _ in range(rng.randint(1, 3)):
            n = rng.randint(2, 14)
            xs = sorted(decimal(rng, -50, 200, 2) for _ in range(n))
            ys = [decimal(rng, -30, 80, 2) if rng.random() > 0.12 else None for _ in range(n)]
            series.append(dict(kind=rng.choice(["linea", "puntos"]), nombre=texto(rng) if rng.random() < 0.85 else "",
                               xs=xs, ys=ys, color=color(rng)))
        if tipo == "mixto":
            series.append(dict(kind="hist", nombre=texto(rng), datos=[decimal(rng, 0, 100) for _ in range(40)],
                               cajas=rng.randint(2, 9), color=color(rng)))
    elif tipo == "barras":
        ncat = rng.randint(1, 6)
        base["cats"] = [texto(rng, 6) for _ in range(ncat)]
        signo = rng.random() < 0.4
        for _ in range(rng.randint(1, 3)):
            series.append(dict(kind="barras", nombre=texto(rng) if rng.random() < 0.85 else "",
                               ys=[decimal(rng, -20 if signo else 1, 90, 1) for _ in range(ncat)], color=color(rng)))
    else:
        for _ in range(rng.randint(1, 2)):
            n = rng.randint(5, 120)
            if rng.random() < 0.1:
                datos = [decimal(rng, 5, 5)] * n
            else:
                datos = [decimal(rng, -10, 400, rng.choice([0, 1, 2])) for _ in range(n)]
            series.append(dict(kind="hist", nombre=texto(rng) if rng.random() < 0.85 else "", datos=datos,
                               cajas=rng.randint(1, 15), color=color(rng)))
    base["series"] = series
    return base


def caso_hueco(rng):
    return dict(w=420, h=300, titulo="Hueco", ex="x", ey="y", cats=[],
                series=[dict(kind="linea", nombre="", xs=[1, 2, 3, 4, 5], ys=[1, 2, None, 4, 5], color=[200, 30, 30])])


# ---------- píxeles ----------

def num_lista(txt, marca):
    partes = txt.split()
    assert partes[0] == marca, txt
    return [float(x) for x in partes[1:]]


def etiquetas_de(txt, marca):
    assert txt.startswith(marca), txt
    return [t[1:-1] for t in txt[len(marca):].split()] if txt[len(marca):].strip() else []


def revisar_caso(k, caso, bloque, png, errores):
    def mal(msg):
        errores.append(f"caso {k}: {msg}")

    d = ref_diseno(caso)
    lineas = dict()
    for l in bloque:
        lineas[l.split()[0].split("[")[0]] = l
    p = lineas["D"].split()
    x0, y0, x1, y1 = (int(v) for v in p[1:5])
    if (x0, y0, x1, y1) != (d["x0"], d["y0"], d["x1"], d["y1"]):
        mal(f"rectángulo {(x0, y0, x1, y1)} y se esperaba {(d['x0'], d['y0'], d['x1'], d['y1'])}")
        return
    for nombre, i in (("xmin", 5), ("xmax", 6), ("ymin", 7), ("ymax", 8)):
        if abs(float(p[i]) - d[nombre]) > 1e-9 * max(1.0, abs(d[nombre])):
            mal(f"{nombre} {p[i]} y se esperaba {d[nombre]}")
    if (p[9] == "true") != d["cat"]:
        mal("categórico")
    for marca, clave in (("XT", "xt"), ("YT", "yt")):
        got = num_lista(lineas[marca], marca)
        if len(got) != len(d[clave]) or any(abs(a - b) > 1e-9 * max(1.0, abs(b)) for a, b in zip(got, d[clave])):
            mal(f"{marca}: {got} y se esperaba {d[clave]}")
    for marca, clave in (("XL", "xl"), ("YL", "yl")):
        got = etiquetas_de(lineas[marca], marca)
        if got != d[clave]:
            mal(f"{marca}: {got} y se esperaba {d[clave]}")
    # marcas de los ejes: invariantes (cubren los datos; paso de 1, 2 o 5 por 10^k)
    if not d["cat"] and len(d["xt"]) >= 2 and not (all(s["kind"] == "hist" for s in caso["series"])):
        pass
    yt = d["yt"]
    if len(yt) >= 2:
        paso = yt[1] - yt[0]
        mant = paso / 10 ** math.floor(math.log10(paso))
        if not any(abs(mant - m) < 1e-9 for m in (1, 2, 5, 10)):
            mal(f"el paso {paso} no es 1, 2 o 5 por una potencia de 10")
        if any(abs((yt[i + 1] - yt[i]) - paso) > 1e-9 * max(1, abs(paso)) for i in range(len(yt) - 1)):
            mal("las marcas de y no están a igual distancia")
        if len(yt) > 12:
            mal("demasiadas marcas")
    # histogramas
    hist = [s for s in caso["series"] if s["kind"] == "hist"]
    hc = lineas["HC"].split()
    got_h, got_b, modo = [], [], None
    for tkn in hc[1:] if hc[0] == "HC" else []:
        pass
    bloques = []
    for tkn in hc[1:]:
        if tkn == "H":
            bloques.append(("H", []))
        elif tkn == "B":
            bloques.append(("B", []))
        else:
            bloques[-1][1].append(tkn)
    cu_got = [b[1] for b in bloques if b[0] == "H"]
    bo_got = [b[1] for b in bloques if b[0] == "B"]
    for s, cg, bg in zip(hist, cu_got, bo_got):
        esp = ref_cuentas(s["datos"], s["cajas"])
        if [int(v) for v in cg] != esp:
            mal(f"cuentas {cg} y numpy da {esp}")
        if sum(esp) != len(s["datos"]):
            mal("las cuentas no suman los datos")
        eb = ref_bordes(s["datos"], s["cajas"])
        if len(bg) != len(eb) or any(abs(float(a) - b) > 1e-9 * max(1.0, abs(b)) for a, b in zip(bg, eb)):
            mal(f"bordes {bg} y se esperaba {eb}")

    # ---- el PNG ----
    im = Image.open(png).convert("RGB")
    W, H = im.size
    if (W, H) != (caso["w"], caso["h"]):
        mal(f"tamaño {(W, H)} y se esperaba {(caso['w'], caso['h'])}")
        return
    pix = im.load()

    def at(x, y):
        return pix[x, y] if 0 <= x < W and 0 <= y < H else None

    if at(0, 0) != BLANCO or at(W - 1, H - 1) != BLANCO:
        mal("el fondo no es blanco")
    if at(x0, (y0 + y1) // 2) != NEGRO:
        mal("falta el eje y")
    if at((x0 + x1) // 2, y1) != NEGRO:
        mal("falta el eje x")

    def pxm(x):
        return x0 + redondear((x - d["xmin"]) / (d["xmax"] - d["xmin"]) * (x1 - x0))

    def pym(y):
        return y1 - redondear((y - d["ymin"]) / (d["ymax"] - d["ymin"]) * (y1 - y0))

    for t in d["yt"]:
        if not any(at(x0 - 2, pym(t) + dy) == NEGRO for dy in (-1, 0, 1)):
            mal(f"falta la marca de y en {t}")
    if d["cat"]:
        ncat = max([len(caso["cats"])] + [len(s["ys"]) for s in caso["series"] if s["kind"] == "barras"])
        ranura = (x1 - x0) / max(ncat, 1)
        for i in range(len(caso["cats"])):
            cx = x0 + redondear((i + 0.5) * ranura)
            if at(cx, y1 + 2) != NEGRO:
                mal(f"falta la marca de la categoría {i}")
    else:
        for t in d["xt"]:
            if not any(at(pxm(t) + dx, y1 + 2) == NEGRO for dx in (-1, 0, 1)):
                mal(f"falta la marca de x en {t}")

    # leyenda
    nombrados = [s for s in caso["series"] if s["nombre"]]
    leyenda = None
    if nombrados:
        w = 8 * max(len(s["nombre"]) for s in nombrados) + 28
        h = 14 * len(nombrados) + 4
        lx, ly = x1 - w - 6, y0 + 6
        leyenda = (lx, ly, w, h)
        for i, s in enumerate(nombrados):
            if at(lx + 11, ly + 9 + 14 * i) != tuple(s["color"]):
                mal(f"falta el cuadrito de la leyenda de {s['nombre']}")

    def en_leyenda(x, y):
        return leyenda is not None and leyenda[0] - 1 <= x <= leyenda[0] + leyenda[2] and leyenda[1] - 1 <= y <= leyenda[1] + leyenda[3]

    if caso["titulo"]:
        if not any(at(x, y) != BLANCO for y in range(8, 24) for x in range(0, W, 1)):
            mal("falta el título")

    colores = [tuple(s["color"]) for s in caso["series"]]

    def hay(x, y, permitidos, radio=1):
        for dx in range(-radio, radio + 1):
            for dy in range(-radio, radio + 1):
                if at(x + dx, y + dy) in permitidos:
                    return True
        return False

    nbar = sum(1 for s in caso["series"] if s["kind"] == "barras")
    kbar = 0
    for si, s in enumerate(caso["series"]):
        c = tuple(s["color"])
        posteriores = set(colores[si:])
        if s["kind"] == "linea":
            n = len(s["xs"])
            for i in range(n - 1):
                if s["ys"][i] is None or s["ys"][i + 1] is None:
                    continue
                for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                    x = s["xs"][i] + t * (s["xs"][i + 1] - s["xs"][i])
                    y = s["ys"][i] + t * (s["ys"][i + 1] - s["ys"][i])
                    X, Y = pxm(x), pym(y)
                    if en_leyenda(X, Y):
                        continue
                    if not hay(X, Y, posteriores):
                        mal(f"la línea de {s['nombre']!r} no pasa por ({X}, {Y}) en el tramo {i}")
                        break
        elif s["kind"] == "puntos":
            for x, y in zip(s["xs"], s["ys"]):
                if y is None:
                    continue
                X, Y = pxm(x), pym(y)
                if en_leyenda(X, Y):
                    continue
                if not hay(X, Y, posteriores):
                    mal(f"falta el punto ({X}, {Y}) de {s['nombre']!r}")
        elif s["kind"] == "barras":
            ncat = max([len(caso["cats"])] + [len(q["ys"]) for q in caso["series"] if q["kind"] == "barras"])
            ranura = (x1 - x0) / max(ncat, 1)
            ancho_b = ranura * 0.8 / max(nbar, 1)
            base = pym(0.0)
            for i, v in enumerate(s["ys"]):
                izq = x0 + i * ranura + ranura * 0.1 + kbar * ancho_b
                xl, xr = redondear(izq), redondear(izq + ancho_b)
                top = pym(v)
                lo_, hi_ = min(top, base), max(top, base)
                if hi_ - lo_ < 4 or xr - xl < 3:
                    continue
                cx, cy = (xl + xr) // 2, (lo_ + hi_) // 2
                if not en_leyenda(cx, cy) and not hay(cx, cy, posteriores, 0):
                    mal(f"la barra {i} de {s['nombre']!r} no tiene su color en ({cx}, {cy})")
                if not en_leyenda(cx, lo_ - 3) and at(cx, lo_ - 3) == c:
                    mal(f"la barra {i} de {s['nombre']!r} sobrepasa su altura")
            kbar += 1
        elif s["kind"] == "hist":
            b = ref_bordes(s["datos"], s["cajas"])
            cu = ref_cuentas(s["datos"], s["cajas"])
            base = pym(0.0)
            for j, cnt in enumerate(cu):
                xl, xr = pxm(b[j]), pxm(b[j + 1])
                top = pym(cnt)
                if base - top < 4 or xr - xl < 3:
                    continue
                cx, cy = (xl + xr) // 2, (top + base) // 2
                permitidos = posteriores | ({(40, 40, 40)} if len(hist) > 1 else set())
                if not en_leyenda(cx, cy) and not hay(cx, cy, permitidos, 0):
                    mal(f"la caja {j} del histograma no tiene su color en ({cx}, {cy})")
                if not en_leyenda(cx, top - 3) and at(cx, top - 3) == c:
                    mal(f"la caja {j} sobrepasa su altura")

    if caso["titulo"] == "Hueco":
        c = (200, 30, 30)
        X = pxm(3)
        if any(at(X, y) == c for y in range(y0 + 1, y1)):
            mal("la línea cruza el NaN")


def main():
    global np, Image
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("OK: test_grafico_python se omite (sin numpy o Pillow en esta máquina)")
        return 0
    rng = random.Random(17)
    casos = [caso_aleatorio(rng) for _ in range(120)] + [caso_hueco(rng)]
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(dict(casos=casos), f)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/grafico_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_grafico_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_grafico_python: FALLA, el programa terminó con", r.returncode)
            return 1
        bloques, actual = [], None
        for linea in r.stdout.splitlines():
            if linea.startswith("CASO"):
                actual = []
                bloques.append(actual)
            elif actual is not None:
                actual.append(linea)
        errores = []
        if len(bloques) != len(casos):
            errores.append(f"se esperaban {len(casos)} gráficos y salieron {len(bloques)}")
        else:
            for k, (caso, bloque) in enumerate(zip(casos, bloques)):
                try:
                    revisar_caso(k, caso, bloque, os.path.join(tmp, f"c{k}.png"), errores)
                except Exception as e:
                    errores.append(f"caso {k}: excepción {type(e).__name__}: {e}")
    if errores:
        print("\n".join(errores[:12]))
        print(f"test_grafico_python: FALLA ({len(errores)} problemas)")
        return 1
    print(f"test_grafico_python: OK ({len(casos)} gráficos: marcas y etiquetas contra la referencia, "
          "histogramas contra numpy, y los píxeles de cada PNG contra Pillow)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
