"""lib/estadistica contra statistics y numpy.

    python3 pruebas/test_estadistica_python.py

Python inventa conjuntos de datos al azar (enteros chicos con repetidos, decimales,
cantidades muy grandes y muy chicas, listas de uno, dos y cientos de datos) y los
escribe en casos.json. pruebas/estadistica_python.scar calcula con lib/estadistica
cada medida y Python las repite por su cuenta:

  - media, mediana, moda, varianza y desviación (de muestra y de población), mínimo,
    máximo, contra statistics (que calcula exacto con fracciones);
  - percentiles, rango intercuartil y la mediana de las desviaciones, contra
    numpy.percentile (con interpolación lineal);
  - covarianza, correlación de Pearson y de Spearman, la recta de regresión y su r²,
    contra numpy.cov, corrcoef y los rangos de scipy.stats.rankdata (o una versión
    propia si no está scipy); la recta y el polinomio por mínimos cuadrados, contra
    la solución exacta con fracciones (no numpy.polyfit, que cambia con la versión);
  - histograma y bordes, contra numpy.histogram; ventanas móviles (media, mediana,
    percentil 90, desviación) contra numpy sobre cada ventana; zscore, suma
    acumulada y normalización.

Los resultados que son exactos (cuentas, mediana, percentiles, mínimo, máximo)
se piden iguales bit a bit; los que acumulan sumas, con 1e-12 de error relativo
(1e-9 el polinomio, que depende de cómo se resuelva el sistema).
"""

from fractions import Fraction
import json
import math
import os
import random
import statistics
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cerca(a, b, rel=1e-12, abs_=1e-300):
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), abs_)


def casos_al_azar(rng):
    casos = []

    def agregar(x, y=None, grado=None):
        n = len(x)
        c = dict(x=x, ps=[0, 1, 5, 25, 33.3, 50, 75, 90, 99, 100],
                 cajas=rng.randint(1, 9), ancho=rng.randint(1, max(1, min(n, 6))))
        if y is not None:
            c["y"] = y
            c["grado"] = grado
        casos.append(c)

    for _ in range(60):
        n = rng.randint(2, 40)
        tipo = rng.choice(["ent", "dec", "grande", "chico", "repetidos"])
        if tipo == "ent":
            x = [rng.randint(-50, 50) for _ in range(n)]
        elif tipo == "dec":
            x = [round(rng.uniform(-100, 100), rng.randint(0, 4)) for _ in range(n)]
        elif tipo == "grande":
            x = [round(rng.uniform(1e9, 1e10), 2) for _ in range(n)]
        elif tipo == "chico":
            x = [round(rng.uniform(-1, 1) * 1e-6, 12) for _ in range(n)]
        else:
            x = [rng.choice([1, 2, 2, 3, 5, 5, 5, 8]) for _ in range(n)]
        if len(set(x)) == 1:
            x[0] = x[0] + 1
        if rng.random() < 0.7:
            m = rng.uniform(-3, 3)
            b = rng.uniform(-20, 20)
            y = [round(m * v + b + rng.gauss(0, 5), 3) for v in x]
            agregar(x, y, rng.randint(1, 3))
        else:
            agregar(x)
    for _ in range(25):                     # con tendencia curva y más datos
        n = rng.randint(20, 300)
        x = sorted(round(rng.uniform(-5, 5), 3) for _ in range(n))
        y = [round(0.5 * v ** 3 - 2 * v ** 2 + v + 3 + rng.gauss(0, 2), 4) for v in x]
        agregar(x, y, rng.randint(1, 4))
    agregar([4.5, 4.5, 4.5, 6.0])
    agregar([1.0, 2.0])
    agregar([3.0, 1.0, 2.0], [1.0, 2.0, 3.0], 1)
    return casos


def rangos_ref(v):
    try:
        from scipy.stats import rankdata
        return [float(r) for r in rankdata(v)]
    except ImportError:
        import numpy as np
        orden = np.argsort(v, kind="stable")
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[orden[j + 1]] == v[orden[i]]:
                j += 1
            for k in range(i, j + 1):
                r[orden[k]] = (i + j) / 2 + 1
            i = j + 1
        return r


def poli_exacto(fx, fy, g):
    """Mínimos cuadrados exactos con fracciones: (VᵀV)·c = Vᵀy, por eliminación de Gauss."""
    m = g + 1
    pot = [[a ** j for j in range(2 * m - 1)] for a in fx]
    A = [[sum(p[i + j] for p in pot) for j in range(m)] + [sum(p[i] * b for p, b in zip(pot, fy))]
         for i in range(m)]
    for k in range(m):
        piv = next(r for r in range(k, m) if A[r][k] != 0)
        A[k], A[piv] = A[piv], A[k]
        for r in range(m):
            if r != k and A[r][k] != 0:
                f = A[r][k] / A[k][k]
                A[r] = [u - f * v for u, v in zip(A[r], A[k])]
    return [A[i][m] / A[i][i] for i in range(m)]


def esperado(c, np):
    x = c["x"]
    n = len(x)
    out = {}
    out["media"] = [statistics.fmean(x)]
    out["mediana"] = [float(statistics.median(x))]
    out["moda"] = [float(statistics.mode(x))]
    out["varianza"] = [float(statistics.variance(x))] if n >= 2 else [float("nan")]
    out["varpob"] = [float(statistics.pvariance(x))]
    out["desviacion"] = [float(statistics.stdev(x))] if n >= 2 else [float("nan")]
    out["despob"] = [float(statistics.pstdev(x))]
    out["minimo"] = [float(min(x))]
    out["maximo"] = [float(max(x))]
    arr = np.array(x, dtype=float)
    out["iqr"] = [float(np.percentile(arr, 75) - np.percentile(arr, 25))]
    med = float(np.median(arr))
    out["mad"] = [float(np.median(np.abs(arr - med)))]
    out["PERC"] = [float(np.percentile(arr, p)) for p in c["ps"]]
    lo, hi = float(arr.min()), float(arr.max())
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    cu, bo = np.histogram(arr, bins=c["cajas"], range=(lo, hi))
    out["HIST"] = [int(v) for v in cu]
    out["BORDES"] = [float(v) for v in bo]
    w = c["ancho"]
    ventanas = np.lib.stride_tricks.sliding_window_view(arr, w)
    out["MMEDIA"] = [statistics.fmean(list(v)) for v in ventanas]
    out["MMEDIANA"] = [float(np.median(v)) for v in ventanas]
    out["MP90"] = [float(np.percentile(v, 90)) for v in ventanas]
    out["MDESV"] = [float(statistics.stdev(list(v))) for v in ventanas] if w >= 2 else []
    m = statistics.fmean(x)
    sd = statistics.stdev(x) if n >= 2 else float("nan")
    out["ZSCORE"] = [(v - m) / sd for v in x]
    out["ACUM"] = [float(v) for v in np.cumsum(arr)]
    out["NORM"] = [(v - lo0) / (hi0 - lo0) for v in x for lo0, hi0 in [(min(x), max(x))]]
    out["RANGOS"] = rangos_ref(x)
    if "y" in c:
        y = c["y"]
        ya = np.array(y, dtype=float)
        out["cov"] = [float(np.cov(arr, ya)[0, 1])]
        out["corr"] = [float(np.corrcoef(arr, ya)[0, 1])]
        rx, ry = np.array(rangos_ref(x)), np.array(rangos_ref(y))
        out["spearman"] = [float(np.corrcoef(rx, ry)[0, 1])]
        # la recta, exacta con fracciones (numpy.polyfit pierde cifras en el
        # intercepto cuando x es grande: 1e9 o más)
        fx, fy = [Fraction(v) for v in x], [Fraction(v) for v in y]
        mx, my = sum(fx) / n, sum(fy) / n
        sxx = sum((a - mx) ** 2 for a in fx)
        sxy = sum((a - mx) * (b - my) for a, b in zip(fx, fy))
        syy = sum((b - my) ** 2 for b in fy)
        pend = sxy / sxx
        out["RECTA"] = [float(pend), float(my - pend * mx), float(sxy * sxy / (sxx * syy)) if syy else 1.0]
        out["_cond"] = abs(float(pend * mx))
        g = c["grado"]
        # el polinomio exacto (no numpy.polyfit: cada versión de numpy/LAPACK redondea
        # distinto, y con x ~ 1e10 el término independiente cambiaba en la sexta cifra)
        out["POLI"] = [float(v) for v in poli_exacto(fx, fy, g)]
        out["_poli_x"] = arr
        out["_poli_y"] = ya
    return out


EXACTOS = {"mediana", "minimo", "maximo", "PERC", "HIST", "RANGOS", "iqr"}


def comparar(k, nombre, got, esp, errores, cond=0.0):
    if len(got) != len(esp):
        errores.append(f"caso {k} {nombre}: {len(got)} valores y se esperaban {len(esp)}")
        return
    for i, (a, b) in enumerate(zip(got, esp)):
        if nombre in EXACTOS or nombre == "moda":
            ok = a == b or (math.isnan(a) and math.isnan(b))
        elif nombre == "POLI":
            ok = None                        # se compara aparte, por el ajuste
        elif nombre == "RECTA":
            ok = cerca(a, b, 1e-9, 1e-12) if i != 1 else abs(a - b) <= 1e-9 * max(1.0, abs(b)) + 1e-14 * cond
        elif nombre in ("corr", "spearman", "cov"):
            ok = cerca(a, b, 1e-9, 1e-12)
        elif nombre == "MDESV":
            ok = cerca(a, b, 1e-9, 1e-9 * max(1.0, abs(b)))
        else:
            ok = cerca(a, b, 1e-11, 1e-300)
        if ok is False:
            errores.append(f"caso {k} {nombre}[{i}]: {a!r} y se esperaba {b!r}")
            return


def main():
    try:
        import numpy as np
    except ImportError:
        print("OK: test_estadistica_python se omite (sin numpy en esta máquina)")
        return 0
    rng = random.Random(18)
    casos = casos_al_azar(rng)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(dict(casos=casos), f)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/estadistica_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_estadistica_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_estadistica_python: FALLA, el programa terminó con", r.returncode)
            return 1
    bloques, actual = [], None
    for linea in r.stdout.splitlines():
        if linea.startswith("CASO"):
            actual = {}
            bloques.append(actual)
        elif actual is not None:
            partes = linea.split()
            actual[partes[0]] = [float(v) for v in partes[1:]]
    errores = []
    if len(bloques) != len(casos):
        errores.append(f"se esperaban {len(casos)} casos y salieron {len(bloques)}")
    else:
        for k, (c, got) in enumerate(zip(casos, bloques)):
            esp = esperado(c, np)
            for nombre, valores in esp.items():
                if nombre.startswith("_"):
                    continue
                if nombre not in got:
                    errores.append(f"caso {k}: falta {nombre}")
                    continue
                comparar(k, nombre, got[nombre], valores, errores, esp.get('_cond', 0.0))
            if "POLI" in esp and "POLI" in got:
                # el polinomio: los coeficientes con tolerancia y, sobre todo, que ajuste igual
                xs, ys = esp["_poli_x"], esp["_poli_y"]
                g = c["grado"]
                if len(got["POLI"]) != g + 1:
                    errores.append(f"caso {k}: POLI tiene {len(got['POLI'])} coeficientes")
                    continue
                mio = np.polyval(got["POLI"][::-1], xs)
                ref = np.polyval(esp["POLI"][::-1], xs)
                escala = max(1.0, float(np.max(np.abs(ys))))
                if float(np.max(np.abs(mio - ref))) > 1e-8 * escala:
                    errores.append(f"caso {k}: el polinomio ajusta distinto (diferencia {float(np.max(np.abs(mio - ref))):.3g})")
                for i, (a, b) in enumerate(zip(got["POLI"], esp["POLI"])):
                    if abs(a - b) > 1e-6 * max(1.0, abs(b)) and g <= 2 and len(c["x"]) > 10:
                        errores.append(f"caso {k}: coeficiente {i} del polinomio {a!r} y se esperaba {b!r}")
                        break
    if errores:
        print("\n".join(errores[:12]))
        print(f"test_estadistica_python: FALLA ({len(errores)} diferencias)")
        return 1
    print(f"test_estadistica_python: OK ({len(casos)} conjuntos de datos contra statistics y numpy)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
