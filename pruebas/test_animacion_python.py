"""lib/animacion (curvas de easing y tweens) contra una referencia en Python.

    python3 pruebas/test_animacion_python.py

pruebas/animacion_python.scar imprime los valores de las 17 curvas en 41 puntos (algunos fuera de [0, 1])
y de tweens que se corren con pasos de tiempo irregulares. La referencia de Python usa las fórmulas de
easings.net (con la forma partida en dos mitades, otra escritura que la de la librería), y los tweens
se calculan con el tiempo total acumulado en vez de ir sumando. Autocomprobación: si se estropea un
valor, el comparador lo tiene que notar.
"""

import math
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C1 = 1.70158
C2 = C1 * 1.525
C3 = C1 + 1


def rebote(x):
    n, d = 7.5625, 2.75
    if x < 1 / d:
        return n * x * x
    if x < 2 / d:
        x -= 1.5 / d
        return n * x * x + 0.75
    if x < 2.5 / d:
        x -= 2.25 / d
        return n * x * x + 0.9375
    x -= 2.625 / d
    return n * x * x + 0.984375


def curva(c, x):
    x = min(1.0, max(0.0, x))
    if c == 0:
        return x
    if c in (1, 4, 7):
        return x ** (2 if c == 1 else 3 if c == 4 else 4)
    if c in (2, 5, 8):
        return 1 - (1 - x) ** (2 if c == 2 else 3 if c == 5 else 4)
    if c in (3, 6, 9):
        n = {3: 2, 6: 3, 9: 4}[c]
        return 2 ** (n - 1) * x ** n if x < 0.5 else 1 - (-2 * x + 2) ** n / 2
    if c == 10:
        return 3 * x ** 2 - 2 * x ** 3
    if c == 11:
        return 6 * x ** 5 - 15 * x ** 4 + 10 * x ** 3
    if c == 12:
        return rebote(x)
    if c == 13:
        return 1 - rebote(1 - x)
    if c == 14:
        return C3 * x ** 3 - C1 * x ** 2
    if c == 15:
        return 1 + C3 * (x - 1) ** 3 + C1 * (x - 1) ** 2
    if c == 16:
        if x < 0.5:
            return ((2 * x) ** 2 * ((C2 + 1) * 2 * x - C2)) / 2
        return ((2 * x - 2) ** 2 * ((C2 + 1) * (x * 2 - 2) + C2) + 2) / 2
    raise ValueError(c)


def m(v):
    return math.floor(v * 1e6 + 0.5)


def esperado():
    L = []
    for c in range(17):
        L.append("curva %d: " % c + " ".join(str(m(curva(c, (k - 5) / 30))) for k in range(41)))
    L.append("entre %d %d" % (m(10 + 10 * curva(2, 0.25)), m(5 - 10 * curva(10, 0.5))))
    for modo in range(3):
        total = 0
        vals = []
        for i in range(60):
            total += (i * 37 + 11) % 50
            dur = 400
            if modo == 0:
                p, fin = min(total, dur) / dur, total >= dur
            elif modo == 1:
                p, fin = (total % dur) / dur, False
            else:
                p, fin = (total % dur) / dur, False
                if (total // dur) % 2 == 1:
                    p = 1 - p
            vals.append(str(m(100 + 200 * curva(6, p))) + ("T" if fin else ""))
        L.append("tween %d: " % modo + " ".join(vals))
    L.append("fin 1000000 true")
    L.append("progreso 0")
    L.append("progreso 1000000")
    L.append("cero 7000000 false")
    L.append("cero 9000000 true")
    L.append("salto 70000000")
    L.append("salto 30000000")
    L.append("reinicio 0 false")
    return L


def comparar(obtenido, esp):
    """Devuelve una lista de diferencias; tolera 1 millonésimo (redondeo en empates)."""
    dif = []
    if len(obtenido) != len(esp):
        return ["cantidad de líneas: %d contra %d" % (len(obtenido), len(esp))]
    for a, b in zip(obtenido, esp):
        ta, tb = a.split(), b.split()
        if len(ta) != len(tb):
            dif.append("largo distinto: " + a[:40])
            continue
        for x, y in zip(ta, tb):
            if x == y:
                continue
            sx, sy = x.rstrip("T"), y.rstrip("T")
            try:
                ok = abs(int(sx) - int(sy)) <= 1 and x.endswith("T") == y.endswith("T")
            except ValueError:
                ok = False
            if not ok:
                dif.append("%s: %s != %s" % (a[:12], x, y))
                break
    return dif


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "anim")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/animacion_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print("test_animacion_python: FALLA al compilar\n" + b.stdout[-800:] + b.stderr[-800:])
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print("test_animacion_python: FALLA, el programa terminó con", r.returncode)
        return 1
    obtenido = r.stdout.strip().splitlines()
    esp = esperado()
    dif = comparar(obtenido, esp)
    if dif:
        print("test_animacion_python: FALLA\n  " + "\n  ".join(dif[:10]))
        return 1
    malo = list(obtenido)
    malo[5] = malo[5].replace(" ", " 7 ", 3)
    if not comparar(malo, esp):
        print("test_animacion_python: FALLA, la autocomprobación no notó un valor estropeado")
        return 1
    print("test_animacion_python: OK (17 curvas x 41 puntos, 3 tweens x 60 pasos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
