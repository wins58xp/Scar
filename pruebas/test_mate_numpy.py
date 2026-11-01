"""lib/mate contra numpy y scipy.

    python3 pruebas/test_mate_numpy.py

Compila pruebas/mate_numpy.scar, que genera matrices, ejes y ángulos con el
xorshift32 de mate, y los mismos datos se regeneran acá con un xorshift32 en
Python (así también se prueba el generador). Se compara con numpy (producto,
determinante, inversa), scipy.spatial.transform.Rotation (rotación por eje,
producto de cuaterniones, slerp), una vista de cámara armada aparte, math
(atan2, asin, acos) y los 1000 primeros números del generador, que tienen que
ser idénticos. Tolerancia: 1e-12 (los f64 se imprimen con todos sus dígitos).

Sin numpy o scipy se omite.
"""

import math
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL = 1e-12


class Xorshift32:
    def __init__(self, semilla):
        self.x = (semilla if semilla != 0 else 2463534242) & 0xFFFFFFFF

    def siguiente(self):
        x = self.x
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.x = x
        return x - (1 << 32) if x >= 1 << 31 else x

    def uniforme(self):
        u = self.siguiente()
        return (u + 4294967296.0 if u < 0 else float(u)) / 4294967296.0

    def entre(self, lo, hi):
        return lo + (hi - lo) * self.uniforme()


def main():
    try:
        import numpy as np
        from scipy.spatial.transform import Rotation, Slerp
    except ImportError:
        print("OK: test_mate_numpy se omite (sin numpy/scipy en esta máquina)")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "m")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/mate_numpy.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_mate_numpy: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=RAIZ, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_mate_numpy: FALLA, el programa terminó con", r.returncode)
            return 1

    scar = {}
    for linea in r.stdout.splitlines():
        p = linea.split()
        scar[(p[0], int(p[1]))] = p[2:]

    malas, n, peor = [], 0, 0.0

    def comparar(etq, k, esperado):
        nonlocal n, peor
        obtenido = np.array([float(v) for v in scar[(etq, k)]])
        esperado = np.asarray(esperado, dtype=float).ravel()
        d = float(np.max(np.abs(obtenido - esperado) / np.maximum(1.0, np.abs(esperado))))
        n += 1
        peor = max(peor, d)
        if not d <= TOL:
            malas.append(f"  {etq} {k}: diferencia relativa {d:.3e}")

    def eje_angulo(eje, ang):
        e = np.array(eje) / np.linalg.norm(eje)
        return Rotation.from_rotvec(e * ang)

    g = Xorshift32(20261026)
    for k in range(20):
        a = np.array([[g.entre(-1, 1) for _ in range(4)] for _ in range(4)])
        b = np.array([[g.entre(-1, 1) for _ in range(4)] for _ in range(4)])
        comparar("PROD", k, a @ b)
        comparar("DET", k, [np.linalg.det(a)])
        comparar("INV", k, np.linalg.inv(a))
    for k in range(20):
        eje = [g.entre(-1, 1) for _ in range(3)]
        ang = g.entre(-3, 3)
        m = np.eye(4)
        r1 = eje_angulo(eje, ang)
        m[:3, :3] = r1.as_matrix()
        comparar("ROT", k, m)
        eje2 = [g.entre(-1, 1) for _ in range(3)]
        ang2 = g.entre(-3, 3)
        r2 = eje_angulo(eje2, ang2)
        m = np.eye(4)
        m[:3, :3] = (r1 * r2).as_matrix()
        comparar("CPROD", k, m)
        tt = g.uniforme()
        m = np.eye(4)
        m[:3, :3] = Slerp([0, 1], Rotation.concatenate([r1, r2]))([tt]).as_matrix()[0]
        comparar("SLERP", k, m)
        ojo = np.array([g.entre(-1, 1) for _ in range(3)]) * 10.0
        centro = np.array([g.entre(-1, 1) for _ in range(3)])
        f = (centro - ojo) / np.linalg.norm(centro - ojo)
        s = np.cross(f, [0, 1, 0]); s /= np.linalg.norm(s)
        u = np.cross(s, f)
        rot = np.eye(4); rot[0, :3], rot[1, :3], rot[2, :3] = s, u, -f
        tras = np.eye(4); tras[:3, 3] = -ojo
        comparar("MIRAR", k, rot @ tras)
    for k in range(10):
        y, x, u = g.entre(-5, 5), g.entre(-5, 5), g.entre(-1, 1)
        comparar("TRIG", k, [math.atan2(y, x), math.asin(u), math.acos(u)])
    h = Xorshift32(42)
    distintos = [k for k in range(1000) if int(scar[("AZAR", k)][0]) != h.siguiente()]
    if distintos:
        malas.append(f"  xorshift32: {len(distintos)} de 1000 números distintos (el primero, el {distintos[0]})")

    if malas:
        print("\n".join(malas))
        print("test_mate_numpy: FALLA")
        return 1
    print(f"OK: mate igual a numpy/scipy en {n} comparaciones (diferencia relativa máxima {peor:.1e}) "
          f"y xorshift32 idéntico en 1000 números")
    return 0


if __name__ == "__main__":
    sys.exit(main())
