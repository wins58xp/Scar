"""lib/fisica contra una referencia en Python.

    python3 pruebas/test_fisica_python.py

Compila y corre pruebas/fisica_python.scar, que arma 12 mundos al azar
(paredes fijas, círculos y cajas fijos y móviles, restitución, fricción y
velocidades al azar, con y sin gravedad) y los avanza 300 pasos de 1/60 s.
Acá cada mundo se avanza de nuevo con una implementación aparte, escrita con
las fórmulas que documenta la librería (Euler semi-implícito, impulso normal
con la restitución menor, fricción de Coulomb con la raíz del producto,
corrección de posición del 80 % con 0,01 de tolerancia), y se compara cada
posición y velocidad cada 25 pasos: tienen que ser iguales (diferencia
relativa de a lo sumo 1e-9, por si una cuenta se ordena distinto).
"""

import math
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Mundo:
    def __init__(self, gy):
        self.gy = gy
        self.c = []
        self.choques = 0

    def agregar(self, forma, x, y, s1, s2, masa, e, mu, vx, vy):
        im = 1.0 / masa if masa > 0.0 else 0.0
        if forma == 0:
            d = dict(f=0, x=x, y=y, vx=vx, vy=vy, im=im, r=s1, a=0.0, b=0.0, e=e, mu=mu)
        else:
            d = dict(f=1, x=x, y=y, vx=vx, vy=vy, im=im, r=0.0, a=s1 / 2.0, b=s2 / 2.0, e=e, mu=mu)
        self.c.append(d)


def circ_circ(i, j):
    dx, dy = j["x"] - i["x"], j["y"] - i["y"]
    rr = i["r"] + j["r"]
    d2 = dx * dx + dy * dy
    if d2 >= rr * rr:
        return None
    d = math.sqrt(d2)
    if d == 0.0:
        return (1.0, 0.0, rr)
    return (dx / d, dy / d, rr - d)


def caja_caja(i, j):
    dx, dy = j["x"] - i["x"], j["y"] - i["y"]
    px = i["a"] + j["a"] - abs(dx)
    py = i["b"] + j["b"] - abs(dy)
    if px <= 0.0 or py <= 0.0:
        return None
    if px < py:
        return (-1.0 if dx < 0.0 else 1.0, 0.0, px)
    return (0.0, -1.0 if dy < 0.0 else 1.0, py)


def circ_caja(c, k):
    cx, cy, r = c["x"], c["y"], c["r"]
    bx, by, a, b = k["x"], k["y"], k["a"], k["b"]
    qx = max(bx - a, min(cx, bx + a))
    qy = max(by - b, min(cy, by + b))
    dx, dy = qx - cx, qy - cy
    d2 = dx * dx + dy * dy
    if d2 > 0.0:
        if d2 >= r * r:
            return None
        d = math.sqrt(d2)
        return (dx / d, dy / d, r - d)
    lados = [(cx - (bx - a), (1.0, 0.0)), (bx + a - cx, (-1.0, 0.0)), (cy - (by - b), (0.0, 1.0)), (by + b - cy, (0.0, -1.0))]
    menor = min(min(lados[0][0], lados[1][0]), min(lados[2][0], lados[3][0]))
    for dist, (nx, ny) in lados:
        if menor == dist:
            return (nx, ny, r + dist)


def contacto(i, j):
    if i["f"] == 0 and j["f"] == 0:
        return circ_circ(i, j)
    if i["f"] == 1 and j["f"] == 1:
        return caja_caja(i, j)
    if i["f"] == 0:
        return circ_caja(i, j)
    c = circ_caja(j, i)
    return None if c is None else (-c[0], -c[1], c[2])


def resolver(m, i, j, ct):
    nx, ny, pen = ct
    s = i["im"] + j["im"]
    if s == 0.0:
        return
    m.choques += 1
    corr = max(pen - 0.01, 0.0) / s * 0.8
    i["x"] -= i["im"] * corr * nx
    i["y"] -= i["im"] * corr * ny
    j["x"] += j["im"] * corr * nx
    j["y"] += j["im"] * corr * ny
    rvx, rvy = j["vx"] - i["vx"], j["vy"] - i["vy"]
    vn = rvx * nx + rvy * ny
    if vn > 0.0:
        return
    e = min(i["e"], j["e"])
    jn = 0.0 - (1.0 + e) * vn / s
    i["vx"] -= i["im"] * jn * nx
    i["vy"] -= i["im"] * jn * ny
    j["vx"] += j["im"] * jn * nx
    j["vy"] += j["im"] * jn * ny
    rvx, rvy = j["vx"] - i["vx"], j["vy"] - i["vy"]
    vn2 = rvx * nx + rvy * ny
    tx, ty = rvx - vn2 * nx, rvy - vn2 * ny
    lt = math.sqrt(tx * tx + ty * ty)
    if lt == 0.0:
        return
    ux, uy = tx / lt, ty / lt
    mu = math.sqrt(i["mu"] * j["mu"])
    jt = 0.0 - (rvx * ux + rvy * uy) / s
    lo, hi = 0.0 - jn * mu, jn * mu
    jt = lo if jt < lo else (hi if jt > hi else jt)
    i["vx"] -= i["im"] * jt * ux
    i["vy"] -= i["im"] * jt * uy
    j["vx"] += j["im"] * jt * ux
    j["vy"] += j["im"] * jt * uy


def paso(m, dt):
    for c in m.c:
        if c["im"] > 0.0:
            c["vx"] = c["vx"] + 0.0 * dt
            c["vy"] = c["vy"] + m.gy * dt
            c["x"] = c["x"] + c["vx"] * dt
            c["y"] = c["y"] + c["vy"] * dt
    m.choques = 0
    n = len(m.c)
    for a in range(n):
        for b in range(a + 1, n):
            ct = contacto(m.c[a], m.c[b])
            if ct is not None and ct[2] > 0.0:
                resolver(m, m.c[a], m.c[b], ct)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "f")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/fisica_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_fisica_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=RAIZ, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_fisica_python: FALLA, el programa terminó con", r.returncode)
            return 1

    mundos, avance = {}, {}
    malas, n, peor, choques = [], 0, 0.0, 0
    for linea in r.stdout.splitlines():
        p = linea.split()
        if p[0] == "MUNDO":
            mundos[int(p[1])] = Mundo(float(p[2]))
            avance[int(p[1])] = 0
        elif p[0] == "CUERPO":
            k = int(p[1])
            mundos[k].agregar(int(p[2]), *(float(v) for v in p[3:12]))
        elif p[0] == "EST":
            k, pas, c = int(p[1]), int(p[2]), int(p[3])
            m = mundos[k]
            while avance[k] < pas:
                paso(m, 1.0 / 60.0)
                avance[k] += 1
            cu = m.c[c]
            for nombre, v in zip(("x", "y", "vx", "vy"), (float(x) for x in p[4:8])):
                n += 1
                d = abs(v - cu[nombre]) / max(1.0, abs(cu[nombre]))
                peor = max(peor, d)
                if d > 1e-9:
                    malas.append(f"mundo {k}, paso {pas}, cuerpo {c}, {nombre}: SCAR {v!r}, Python {cu[nombre]!r}")
        elif p[0] == "CHOQUES":
            k = int(p[1])
            choques += int(p[3])
            if int(p[3]) != mundos[k].choques:
                malas.append(f"mundo {k}, paso {p[2]}: SCAR {p[3]} choques, Python {mundos[k].choques}")
    if malas or n == 0 or choques == 0:
        for m in malas[:10]:
            print("  ", m)
        print(f"test_fisica_python: FALLA, {len(malas)} diferencias en {n} comparaciones")
        return 1
    print(f"OK: fisica igual a la referencia en Python: 12 mundos, 300 pasos, {n} valores comparados "
          f"(diferencia relativa máxima {peor:.1e}), {choques} choques en los pasos mirados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
