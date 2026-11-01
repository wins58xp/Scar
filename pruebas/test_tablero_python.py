"""Las funciones puras de lib/tablero contra Python.

    python3 pruebas/test_tablero_python.py            (SCAR_SEMILLA=n para otra)

Python inventa números y colores al azar y los escribe en casos.json; pruebas/tablero_python.scar
los procesa con lib/tablero y Python calcula lo mismo con math:

  - fraccion (dónde cae un valor entre un mínimo y un máximo, recortado a 0..1);
  - estado (verde / ámbar / rojo, con el sentido "más es peor" o "menos es peor");
  - compacto (1234 -> "1.2k", 3400000 -> "3.4M", 2.0 -> "2", negativos, bordes);
  - arco_x / arco_y (los puntos de la media luna de un medidor);
  - mezclar (mezcla de dos colores) y sobre (texto claro u oscuro sobre un fondo);
  - una autocomprobación: si se estropea un resultado, el comparador lo tiene que notar.

Dibujar (tarjetas, medidores, botones) no se prueba acá: lo mira a ojo pruebas/lib_tablero.scar,
y su guion de clics (pruebas/gui/302_tablero.guion) prueba que los botones responden.
lib/tablero usa lib/gui, que enlaza con SDL2: sin SDL2 instalado la prueba se omite.
"""

import json
import math
import os
import random
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def py_fraccion(v, lo, hi):
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def py_estado(v, aviso, critico):
    if aviso == critico:
        return -1
    if critico > aviso:
        return 2 if v >= critico else 1 if v >= aviso else 0
    return 2 if v <= critico else 1 if v <= aviso else 0


def py_decimales(x, n):
    escala = 10.0 ** n
    v, signo = x, ""
    if v < 0:
        signo, v = "-", -v
    ent = int(math.floor(v * escala + 0.5))
    if ent == 0:
        signo = ""
    if n <= 0:
        return signo + str(ent)
    pot = int(escala)
    return signo + str(ent // pot) + "." + str(ent % pot).rjust(n, "0")


def sin_cero(s):
    return s[:-2] if len(s) > 2 and s.endswith(".0") else s


def py_compacto(v):
    a = abs(v)
    for lim, suf in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if a >= lim:
            return sin_cero(py_decimales(v / lim, 1)) + suf
    return sin_cero(py_decimales(v, 1))


def trunc_div(a, b):  # la división de enteros de C trunca hacia cero
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def py_mezclar(a, b, t):
    out = 0
    for sh in (16, 8, 0):
        x, y = (a >> sh) & 255, (b >> sh) & 255
        out |= (x + trunc_div((y - x) * t, 100)) << sh
    return out


def py_sobre(c):
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return 1315860 if r * 299 + g * 587 + b * 114 > 150000 else 16777215


def py_arco(cx, r, f):
    x = cx + math.floor(r * math.cos(math.pi * (1.0 - f)) + 0.5)
    y = cx - math.floor(r * math.sin(math.pi * (1.0 - f)) + 0.5)
    return f"{x} {y}"


def casos_al_azar(rng):
    def q(lo, hi):  # múltiplos de 1/8: el JSON los lleva exactos
        return rng.randint(int(lo * 8), int(hi * 8)) / 8

    fr = [[0, 0, 100], [100, 0, 100], [50, 0, 100], [-5, 0, 100], [130, 0, 100], [5, 5, 5], [3, 5, 1]]
    fr += [[q(-50, 150), q(-20, 20), q(-20, 120)] for _ in range(120)]
    es = [[1, 1, 1], [70, 70, 90], [90, 70, 90], [69.875, 70, 90], [20, 40, 20], [40, 40, 20], [41, 40, 20]]
    es += [[q(0, 120), q(0, 100), q(0, 100)] for _ in range(150)]
    co = [0, 1, -1, 999, 1000, 999.95, 999999, 1e6, 1234, 3.4e6, 2.0, 3.14159, -1234.5, 1e9, 2.5e9, -0.04, 0.05, 12345678901]
    co += [rng.choice([1, 10, 100, 1000, 1e6, 1e9]) * q(-1000, 1000) / 7 for _ in range(150)]
    ar = [[100, 50.0, f / 8] for f in range(9)]
    ar += [[rng.randint(0, 500), float(rng.randint(5, 150)), rng.randint(0, 64) / 64] for _ in range(150)]
    mz = [[0, 0xFFFFFF, 0], [0, 0xFFFFFF, 100], [0xFF0000, 0x0000FF, 50]]
    mz += [[rng.randrange(1 << 24), rng.randrange(1 << 24), rng.randint(0, 100)] for _ in range(150)]
    justos = [(r << 16) | (g << 8) | b for r in range(0, 256, 5) for g in range(0, 256, 5) for b in range(256)
              if r * 299 + g * 587 + b * 114 in (149999, 150000, 150001)]  # el borde claro/oscuro
    so = justos[:40] + [0, 0xFFFFFF, 0x808080, 0xFFFF00, 0x0000FF] + [rng.randrange(1 << 24) for _ in range(150)]
    return {"fr": fr, "es": es, "co": co, "ar": ar, "mz": mz, "so": so}


def esperado(casos):
    e = {}
    for k, (v, lo, hi) in enumerate(casos["fr"]):
        e[("FR", k)] = repr(py_fraccion(v, lo, hi))
    for k, (v, a, c) in enumerate(casos["es"]):
        e[("ES", k)] = str(py_estado(v, a, c))
    for k, v in enumerate(casos["co"]):
        e[("CO", k)] = py_compacto(v)
    for k, (cx, r, f) in enumerate(casos["ar"]):
        e[("AR", k)] = py_arco(cx, r, f)
    for k, (a, b, t) in enumerate(casos["mz"]):
        e[("MZ", k)] = str(py_mezclar(a, b, t))
    for k, c in enumerate(casos["so"]):
        e[("SO", k)] = str(py_sobre(c))
    return e


def leer(salida):
    got = {}
    for linea in salida.splitlines():
        p = linea.split(" ", 2)
        if len(p) == 3 and p[1].isdigit():
            got[(p[0], int(p[1]))] = p[2]
    return got


def igual(et, a, b):
    if et == "FR":  # a_texto de SCAR y repr de Python pueden escribir distinto el mismo f64
        try:
            return float(a) == float(b)
        except ValueError:
            return False
    return a == b


def comparar(esp, got):
    errores = []
    for clave, v in esp.items():
        if clave not in got:
            errores.append(f"{clave}: falta")
        elif not igual(clave[0], got[clave], v):
            errores.append(f"{clave}: lib={got[clave]!r} python={v!r}")
    return errores


def main():
    rng = random.Random(int(os.environ.get("SCAR_SEMILLA", "20")))
    casos = casos_al_azar(rng)
    esp = esperado(casos)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w") as f:
            json.dump(casos, f)
        binario = os.path.join(tmp, "t")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/tablero_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            if "scarsdl" in (b.stdout + b.stderr):
                print("OK: lib/tablero se omite (no hay SDL2 para enlazar lib/gui)")
                return 0
            print(b.stdout + b.stderr)
            print("test_tablero_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or "ERROR" in r.stdout:
        print(r.stdout[-2000:] + r.stderr)
        print("test_tablero_python: FALLA, el programa terminó con", r.returncode)
        return 1
    got = leer(r.stdout)
    errores = comparar(esp, got)
    if errores:
        print("\n".join(errores[:25]))
        print(f"test_tablero_python: FALLA ({len(errores)} diferencias)")
        return 1
    for et in ("FR", "ES", "CO", "AR", "MZ", "SO"):
        malo = dict(got)
        clave = next(k for k in malo if k[0] == et)
        malo[clave] = malo[clave] + "9"
        if not comparar(esp, malo):
            print(f"test_tablero_python: FALLA, la autocomprobación no notó un resultado estropeado ({et})")
            return 1
    print(f"OK: lib/tablero contra Python: {len(esp)} casos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
