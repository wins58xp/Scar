"""lib/algebra contra una referencia en Python.

    python3 pruebas/test_algebra_python.py

pruebas/algebra_python.scar arma 40 casos al azar (matrices de 1 x 1 a 7 x 7, la mitad con enteros y la
mitad con decimales, más matrices de rango menor armadas como producto de n x r por r x n) y escribe cada
resultado. Acá se comprueba:
  - suma, resta, escala, producto, transpuesta, traza y norma contra numpy;
  - determinante y rango de las matrices enteras con fracciones EXACTAS (fractions.Fraction), y de las
    decimales contra numpy;
  - resolver e inversa: el residuo |a x - b| tiene que ser del orden del redondeo (estabilidad hacia
    atrás) y x tiene que coincidir con numpy dentro de lo que permite el número de condición; si la
    librería dice "singular", la matriz tiene que serlo de verdad (determinante exacto 0) o estar
    al borde (condición > 1e13); y las singulares de verdad tienen que dar error y determinante 0;
  - y que las mal condicionadas pero regulares (Hilbert de 6 x 6, diag(1, 1e-9)) se resuelvan, con rango
    completo y determinante distinto de 0;
  - mínimos cuadrados contra numpy.linalg.lstsq;
  - valores propios contra numpy.linalg.eigh, cada vector propio con a v = lambda v, de largo 1 y con
    el signo documentado, y que una matriz no simétrica dé error;
  - leer matrices de texto, los textos mal escritos y a_texto_mat.
Autocomprobación: si se estropea una línea, se nota.
"""

import math
import os
import subprocess
import sys
import tempfile
from fractions import Fraction

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPS = 2.220446049250313e-16


def leer_mat(p):
    f, c = int(p[1]), int(p[2])
    return np.array([float(x) for x in p[3:3 + f * c]]).reshape(f, c)


def det_exacto(a):
    n = a.shape[0]
    m = [[Fraction(int(round(x))) for x in fila] for fila in a]
    det = Fraction(1)
    for j in range(n):
        p = next((i for i in range(j, n) if m[i][j] != 0), None)
        if p is None:
            return Fraction(0)
        if p != j:
            m[j], m[p] = m[p], m[j]
            det = -det
        det *= m[j][j]
        for i in range(j + 1, n):
            f = m[i][j] / m[j][j]
            for k in range(j, n):
                m[i][k] -= f * m[j][k]
    return det


def rango_exacto(a):
    m = [[Fraction(int(round(x))) for x in fila] for fila in a]
    filas, cols = len(m), len(m[0]) if m else 0
    r = 0
    for j in range(cols):
        p = next((i for i in range(r, filas) if m[i][j] != 0), None)
        if p is None:
            continue
        m[r], m[p] = m[p], m[r]
        for i in range(r + 1, filas):
            f = m[i][j] / m[r][j]
            for k in range(j, cols):
                m[i][k] -= f * m[r][k]
        r += 1
        if r == filas:
            break
    return r


def cerca(a, b, rtol, atol=0.0):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return a.shape == b.shape and bool(np.all(np.abs(a - b) <= atol + rtol * np.maximum(1.0, np.abs(b))))


def revisar(lineas):
    errores = []
    cuenta = {"casos": 0, "resueltos": 0, "singulares_bien": 0, "mc": 0, "propios": 0, "det_exactos": 0}
    M = {}
    caso = -1
    for ln in lineas:
        p = ln.split()
        if not p:
            continue
        cab = p[0]
        try:
            if cab == "CASO":
                caso, n, enteros = int(p[1]), int(p[2]), p[3] == "true"
                M = {}
                cuenta["casos"] += 1
            elif cab in ("A", "B", "V", "C", "SING", "AM", "BM", "SIM", "HILBERT", "UNOS"):
                M[cab] = leer_mat(p)
            elif cab in ("SUMA", "RESTA", "ESCALA", "PROD", "TRANS"):
                a, b, c = M["A"], M["B"], M["C"]
                esp = {"SUMA": a + b, "RESTA": a - b, "ESCALA": a * -2.5, "PROD": a @ c, "TRANS": c.T}[cab]
                if not cerca(leer_mat(p), esp, 1e-12):
                    errores.append("caso %d: %s distinta" % (caso, cab))
            elif cab == "TRAZA":
                if not cerca(float(p[1]), np.trace(M["A"]), 1e-12) or not cerca(float(p[3]), np.linalg.norm(M["C"]), 1e-12):
                    errores.append("caso %d: traza o norma" % caso)
            elif cab == "DET":
                d = float(p[1])
                a = M["A"]
                if enteros:
                    ex = det_exacto(a)
                    cuenta["det_exactos"] += 1
                    if ex == 0:
                        if d != 0.0:
                            errores.append("caso %d: det exacto 0 y dio %r" % (caso, d))
                    elif not cerca(d, float(ex), 1e-9):
                        errores.append("caso %d: det %r y el exacto es %s" % (caso, d, ex))
                else:
                    if not cerca(d, np.linalg.det(a), 1e-8 * max(1.0, np.linalg.cond(a) * EPS * 1e6)):
                        errores.append("caso %d: det %r y numpy da %r" % (caso, d, np.linalg.det(a)))
            elif cab == "RANGO":
                ra, rc = int(p[1]), int(p[2])
                if enteros:
                    ea, ec = rango_exacto(M["A"]), rango_exacto(M["C"])
                else:
                    ea, ec = np.linalg.matrix_rank(M["A"]), np.linalg.matrix_rank(M["C"])
                if (ra, rc) != (ea, ec):
                    errores.append("caso %d: rangos %d %d y no %d %d" % (caso, ra, rc, ea, ec))
            elif cab in ("X", "INV"):
                a = M["A"]
                b = M["V"] if cab == "X" else np.eye(a.shape[0])
                singular_exacta = enteros and det_exacto(a) == 0
                cond = np.linalg.cond(a) if not singular_exacta else math.inf
                if p[1] == "ERR":
                    if not (singular_exacta or cond > 1e13):
                        errores.append("caso %d: %s dio singular y la condición es %.1e" % (caso, cab, cond))
                    continue
                if singular_exacta:
                    errores.append("caso %d: %s resolvió una matriz singular" % (caso, cab))
                    continue
                x = leer_mat(p)
                cuenta["resueltos"] += 1
                res = np.linalg.norm(a @ x - b)
                if res > 1e-12 * max(1.0, np.linalg.norm(a) * np.linalg.norm(x) + np.linalg.norm(b)) * a.shape[0]:
                    errores.append("caso %d: %s con residuo %.2e" % (caso, cab, res))
                if not cerca(x, np.linalg.solve(a, b), 1e-13 * cond * 100, 1e-13 * cond * 100):
                    errores.append("caso %d: %s distinta de numpy" % (caso, cab))
            elif cab == "SING_RANGO":
                s = M["SING"]
                if int(p[1]) != rango_exacto(s):
                    errores.append("caso %d: rango de la singular %s y no %d" % (caso, p[1], rango_exacto(s)))
                if float(p[3]) != 0.0:
                    errores.append("caso %d: det de una singular %s" % (caso, p[3]))
            elif cab == "SING_X":
                if p[1] != "ERR":
                    errores.append("caso %d: resolvió una matriz singular" % caso)
                else:
                    cuenta["singulares_bien"] += 1
            elif cab == "MC":
                if p[1] == "ERR":
                    if np.linalg.matrix_rank(M["AM"]) == M["AM"].shape[1]:
                        errores.append("caso %d: mínimos cuadrados dio error con columnas independientes" % caso)
                    continue
                x = leer_mat(p)
                ref = np.linalg.lstsq(M["AM"], M["BM"], rcond=None)[0]
                cond = np.linalg.cond(M["AM"])
                if not cerca(x, ref, 1e-12 * cond * cond * 10 + 1e-12, 1e-12 * cond * cond * 10):
                    errores.append("caso %d: mínimos cuadrados distinto de numpy" % caso)
                cuenta["mc"] += 1
            elif cab == "VALORES":
                vals = leer_mat(p)[:, 0]
                ref = np.linalg.eigh(M["SIM"])[0]
                escala = max(1.0, np.abs(M["SIM"]).max())
                if not cerca(vals / escala, ref / escala, 1e-10, 1e-10):
                    errores.append("caso %d: valores propios %s y no %s" % (caso, vals, ref))
                cuenta["propios"] += 1
                M["vals"] = vals
            elif cab == "VECTORES":
                q = leer_mat(p)
                s = M["SIM"]
                vals = M["vals"]
                escala = max(1.0, np.abs(s).max())
                for k in range(q.shape[1]):
                    v = q[:, k]
                    if abs(np.linalg.norm(v) - 1) > 1e-10:
                        errores.append("caso %d: vector propio %d de largo %r" % (caso, k, np.linalg.norm(v)))
                    if np.linalg.norm(s @ v - vals[k] * v) > 1e-9 * escala:
                        errores.append("caso %d: a v != lambda v en el vector %d" % (caso, k))
                    if v[int(np.argmax(np.abs(v)))] < 0:
                        errores.append("caso %d: el vector %d no tiene positivo su número más grande" % (caso, k))
                # con valores bien separados el vector es único (salvo signo, ya fijado)
                ref_vals, ref_vecs = np.linalg.eigh(s)
                for k in range(q.shape[1]):
                    gap = min([abs(ref_vals[k] - ref_vals[j]) for j in range(len(ref_vals)) if j != k] or [math.inf])
                    if gap > 1e-3 * escala:
                        r = ref_vecs[:, k]
                        r = r * (1 if r[int(np.argmax(np.abs(r)))] > 0 else -1)
                        if not cerca(q[:, k], r, 1e-7, 1e-7):
                            errores.append("caso %d: vector propio %d distinto de numpy" % (caso, k))
            elif cab == "NOSIM":
                if p[1] != "ERR" and not np.allclose(M["A"], M["A"].T):
                    errores.append("caso %d: propios aceptó una matriz no simétrica" % caso)
            elif cab == "MALCOND":
                if p[1] == "ERR":
                    errores.append("una matriz mal condicionada pero regular dio singular")
                    continue
                a, b = M["HILBERT"], M["UNOS"]
                x = leer_mat(p)
                if not cerca(x, np.linalg.solve(a, b), 1e-13 * np.linalg.cond(a) * 100, 1e-13 * np.linalg.cond(a) * 100):
                    errores.append("mal condicionada resuelta mal")
                cuenta["malcond"] = cuenta.get("malcond", 0) + 1
            elif cab == "MALCOND_RANGO":
                n = M["HILBERT"].shape[0]
                if int(p[1]) != n or float(p[2]) == 0.0 or not cerca(float(p[2]), np.linalg.det(M["HILBERT"]), 1e-6):
                    errores.append("mal condicionada: rango %s o determinante %s" % (p[1], p[2]))
            elif cab == "TEXTO":
                m = leer_mat(p)
                esperadas = [np.array([[1, 2, 3], [4, 5, 6.0]]), np.array([[-1.5, 2000], [0.25, -0.04]]), np.array([[7.0]])]
                if not any(m.shape == e.shape and cerca(m, e, 1e-15) for e in esperadas):
                    errores.append("texto mal leído: " + ln)
                cuenta["textos"] = cuenta.get("textos", 0) + 1
            elif cab == "TEXTO_MAL":
                cuenta["textos_mal"] = cuenta.get("textos_mal", 0) + (p[2] == "ERR")
            elif cab == "ATEXTO":
                if ln != "ATEXTO 1.00 0.00; 0.00 1.00":
                    errores.append("a_texto_mat: " + ln)
            elif cab == "MC_POCAS":
                cuenta["mc_pocas"] = 1
        except (KeyError, ValueError, IndexError) as e:
            errores.append("línea rara (%s): %s" % (e, ln[:80]))
    if cuenta.get("malcond") != 2:
        errores.append("faltan las matrices mal condicionadas")
    if cuenta.get("textos") != 3 or cuenta.get("textos_mal") != 3 or cuenta.get("mc_pocas") != 1:
        errores.append("faltan pruebas de texto o de mínimos cuadrados con pocas ecuaciones: %s" % cuenta)
    return errores, cuenta


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "al")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/algebra_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print("test_algebra_python: FALLA al compilar\n" + b.stdout[-800:] + b.stderr[-800:])
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("test_algebra_python: FALLA, el programa terminó con", r.returncode, r.stderr[-300:])
        return 1
    lineas = r.stdout.strip().splitlines()
    errores, cuenta = revisar(lineas)
    if errores:
        print("test_algebra_python: FALLA\n  " + "\n  ".join(errores[:12]))
        return 1
    if cuenta["casos"] != 40 or cuenta["singulares_bien"] < 25 or cuenta["resueltos"] < 60:
        print("test_algebra_python: FALLA, poca cobertura", cuenta)
        return 1
    for pref in ("PROD ", "DET ", "X ", "MC ", "VALORES ", "VECTORES ", "RANGO "):
        malo = list(lineas)
        for k, l in enumerate(malo):
            q = l.split()
            if l.startswith(pref) and q[1] != "ERR":
                if pref in ("DET ", "RANGO "):
                    q[1] = repr(float(q[1]) + 1) if pref == "DET " else str(int(q[1]) + 1)
                else:
                    q[-1] = repr(float(q[-1]) * 1.01 + 0.01)
                malo[k] = " ".join(q)
                break
        if not revisar(malo)[0]:
            print("test_algebra_python: FALLA, la autocomprobación no notó un cambio en", pref)
            return 1
    print("test_algebra_python: OK (40 casos: %d sistemas e inversas, %d determinantes exactos, %d singulares "
          "detectadas, %d mínimos cuadrados, %d descomposiciones en valores propios)"
          % (cuenta["resueltos"], cuenta["det_exactos"], cuenta["singulares_bien"], cuenta["mc"], cuenta["propios"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
