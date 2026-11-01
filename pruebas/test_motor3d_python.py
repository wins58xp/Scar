"""lib/motor3d contra una referencia en Python.

    python3 pruebas/test_motor3d_python.py

Compila y corre pruebas/motor3d_python.scar, que dibuja 24 escenas (un cubo,
una esfera y un modelo .obj que se deja acá en una carpeta temporal, con
sombreado plano, Gouraud y alambre, rotaciones y cámaras al azar, y las
últimas con la cámara tan cerca que el plano cercano corta el modelo) y
escribe los parámetros y el lienzo de cada una. Acá se dibuja cada escena de
nuevo con una implementación aparte, escrita con listas de Python y las
fórmulas de los libros (gluPerspective, gluLookAt, Sutherland-Hodgman contra
el plano cercano, funciones de borde con z-buffer, Lambert), y se comparan
los lienzos píxel por píxel: tienen que ser iguales, salvo a lo sumo un 0,5 %
de píxeles por diferencias de redondeo.
"""

import math
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cortados = 0

OBJ = """# una casita: base de cubo con caras cuadradas y techo de pirámide
o casa
v -0.8 -0.8 -0.8
v 0.8 -0.8 -0.8
v 0.8 -0.8 0.8
v -0.8 -0.8 0.8
v -0.8 0.4 -0.8
v 0.8 0.4 -0.8
v 0.8 0.4 0.8
v -0.8 0.4 0.8
v 0 1.3 0
vt 0 0
s 1
f 1 2 3 4
f 5/1 8/1 7/1 6/1
f 1 5 6 2
f 2 6 7 3
f 3 7 8 4
f 4 8 5 1
f 5 9 8
f 8 9 7
f 7 9 6
f 6 9 5
"""


def norm(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return [v[0] / l, v[1] / l, v[2] / l] if l != 0.0 else [0.0, 0.0, 0.0]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def mm(a, b):
    r = [[0.0] * 4 for _ in range(4)]
    for f in range(4):
        for c in range(4):
            s = 0.0
            for k in range(4):
                s = s + a[f][k] * b[k][c]
            r[f][c] = s
    return r


def mv(a, v):
    return [a[f][0] * v[0] + a[f][1] * v[1] + a[f][2] * v[2] + a[f][3] * v[3] for f in range(4)]


def perspectiva(fovy, asp, n, f):
    t = 1.0 / math.tan(fovy / 2.0)
    return [[t / asp, 0.0, 0.0, 0.0], [0.0, t, 0.0, 0.0],
            [0.0, 0.0, (f + n) / (n - f), 2.0 * f * n / (n - f)], [0.0, 0.0, -1.0, 0.0]]


def mirar_a(e, c, u):
    f = norm(sub(c, e))
    s = norm(cross(f, u))
    uu = cross(s, f)
    return [[s[0], s[1], s[2], 0.0 - dot(s, e)], [uu[0], uu[1], uu[2], 0.0 - dot(uu, e)],
            [0.0 - f[0], 0.0 - f[1], 0.0 - f[2], dot(f, e)], [0.0, 0.0, 0.0, 1.0]]


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return [[1.0, 0.0, 0.0, 0.0], [0.0, c, 0.0 - s, 0.0], [0.0, s, c, 0.0], [0.0, 0.0, 0.0, 1.0]]


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0.0, s, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0 - s, 0.0, c, 0.0], [0.0, 0.0, 0.0, 1.0]]


def cubo(lado):
    h = lado / 2.0
    V, N, T = [], [], []
    caras = [(1, 0, 0, 0, 0, -1, 0, 1, 0), (-1, 0, 0, 0, 0, 1, 0, 1, 0), (0, 1, 0, 1, 0, 0, 0, 0, -1),
             (0, -1, 0, 1, 0, 0, 0, 0, 1), (0, 0, 1, 1, 0, 0, 0, 1, 0), (0, 0, -1, -1, 0, 0, 0, 1, 0)]
    for c in caras:
        n, u, v = [float(x) for x in c[0:3]], [float(x) for x in c[3:6]], [float(x) for x in c[6:9]]
        base = len(V)
        for su, sv in ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)):
            p = [n[i] * h + (u[i] * (su * h) + v[i] * (sv * h)) for i in range(3)]
            V.append(p)
            N.append(n)
        T += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return V, N, T


def esfera(r, seg, ani):
    V, N, T = [], [], []
    for a in range(ani + 1):
        th = 3.141592653589793 * float(a) / float(ani)
        for s in range(seg + 1):
            ph = 2.0 * 3.141592653589793 * float(s) / float(seg)
            nx, ny, nz = math.sin(th) * math.cos(ph), math.cos(th), 0.0 - math.sin(th) * math.sin(ph)
            V.append([r * nx, r * ny, r * nz])
            N.append([nx, ny, nz])
    for a in range(ani):
        for s in range(seg):
            i0 = a * (seg + 1) + s
            i1 = i0 + seg + 1
            if a > 0:
                T.append((i0, i1, i0 + 1))
            if a < ani - 1:
                T.append((i0 + 1, i1, i1 + 1))
    return V, N, T


def de_obj(fuente):
    pos, V, T = [], [], []
    for linea in fuente.splitlines():
        p = linea.split()
        if not p:
            continue
        if p[0] == "v":
            pos.append([float(x) for x in p[1:4]])
        elif p[0] == "f":
            idx = []
            for tok in p[1:]:
                V.append(list(pos[int(tok.split("/")[0]) - 1]))
                idx.append(len(V) - 1)
            for k in range(1, len(idx) - 1):
                T.append((idx[0], idx[k], idx[k + 1]))
    # sin normales: el promedio de las caras, después juntando las de la misma posición
    N = [[0.0, 0.0, 0.0] for _ in V]
    for a, b, c in T:
        f = cross(sub(V[b], V[a]), sub(V[c], V[a]))
        for i in (a, b, c):
            N[i] = [N[i][0] + f[0], N[i][1] + f[1], N[i][2] + f[2]]
    N = [norm(n) for n in N]
    suaves = []
    for i in range(len(V)):
        ax = ay = az = 0.0
        for j in range(len(V)):
            if V[i] == V[j]:
                ax, ay, az = ax + N[j][0], ay + N[j][1], az + N[j][2]
        suaves.append(norm([ax, ay, az]))
    return V, suaves, T


def borde(a, b, px, py):
    return (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])


def bresenham(x0, y0, x1, y1):
    puntos = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        puntos.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return puntos
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def color_de(c, i):
    k = min(max(i, 0.0), 1.0)
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return 0xFF000000 | (int(r * k + 0.5) << 16) | (int(g * k + 0.5) << 8) | int(b * k + 0.5)


def dibujar(W, H, fondo, malla, M, ojo, fov, luz, col, modo, cerca):
    V, N, T = malla
    img = [fondo] * (W * H)
    zb = [2.0] * (W * H)
    L = norm(luz)
    MVP = mm(perspectiva(fov, float(W) / float(H), cerca, 30.0), mm(mirar_a(ojo, [0.0, 0.0, 0.0], [0.0, 1.0, 0.0]), M))

    def inten(n):
        return 0.15 + 0.85 * max(0.0, 0.0 - dot(n, L))

    clip = [mv(MVP, v + [1.0]) for v in V]
    global cortados
    cortados = sum(1 for tri in T if len({clip[v][2] + clip[v][3] >= 0.0 for v in tri}) == 2)
    mundo = [mv(M, v + [1.0]) for v in V]
    mundo = [[p[0] / p[3], p[1] / p[3], p[2] / p[3]] for p in mundo]
    vi = [inten(norm(mv(M, n + [0.0])[:3])) for n in N] if modo == 1 else [0.0] * len(V)
    for a, b, c in T:
        if modo == 0:
            ic = inten(norm(cross(sub(mundo[b], mundo[a]), sub(mundo[c], mundo[a]))))
        poli = [clip[v] + [ic if modo == 0 else vi[v]] for v in (a, b, c)]
        sal = []
        for k in range(3):
            A, B = poli[k], poli[(k + 1) % 3]
            da, db = A[2] + A[3], B[2] + B[3]
            if da >= 0.0:
                sal.append(A)
            if (da >= 0.0) != (db >= 0.0):
                t = da / (da - db)
                sal.append([A[i] + (B[i] - A[i]) * t for i in range(5)])
        if len(sal) < 3:
            continue
        S = [((p[0] / p[3] + 1.0) * 0.5 * float(W), (1.0 - p[1] / p[3]) * 0.5 * float(H), p[2] / p[3], p[4])
             for p in sal]
        if modo == 2:
            if borde(S[0], S[1], S[2][0], S[2][1]) < 0.0:
                for k in range(len(S)):
                    j = (k + 1) % len(S)
                    for x, y in bresenham(math.floor(S[k][0]), math.floor(S[k][1]),
                                          math.floor(S[j][0]), math.floor(S[j][1])):
                        if 0 <= x < W and 0 <= y < H:
                            img[y * W + x] = col
            continue
        for k in range(1, len(S) - 1):
            p0, p1, p2 = S[0], S[k], S[k + 1]
            area = 0.0 - borde(p0, p1, p2[0], p2[1])
            if area <= 0.0:
                continue
            xs, ys = (p0[0], p1[0], p2[0]), (p0[1], p1[1], p2[1])
            for y in range(max(0, math.floor(min(ys))), min(H - 1, math.floor(max(ys))) + 1):
                py = float(y) + 0.5
                for x in range(max(0, math.floor(min(xs))), min(W - 1, math.floor(max(xs))) + 1):
                    px = float(x) + 0.5
                    b0 = 0.0 - borde(p1, p2, px, py)
                    b1 = 0.0 - borde(p2, p0, px, py)
                    b2 = 0.0 - borde(p0, p1, px, py)
                    if b0 >= 0.0 and b1 >= 0.0 and b2 >= 0.0:
                        z = (b0 * p0[2] + b1 * p1[2] + b2 * p2[2]) / area
                        i = y * W + x
                        if -1.0 <= z <= 1.0 and z < zb[i]:
                            zb[i] = z
                            img[i] = color_de(col, (b0 * p0[3] + b1 * p1[3] + b2 * p2[3]) / area)
    return img


def main():
    with tempfile.TemporaryDirectory() as dir:
        with open(os.path.join(dir, "modelo.obj"), "w") as f:
            f.write(OBJ)
        binario = os.path.join(dir, "m")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/motor3d_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_motor3d_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario, dir], cwd=RAIZ, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_motor3d_python: FALLA, el programa terminó con", r.returncode)
            return 1

    mallas = {0: cubo(1.6), 1: esfera(1.0, 12, 8), 2: de_obj(OBJ)}
    malas, escenas, pixeles, distintos_total, objmal, recortadas = [], 0, 0, 0, 0, 0
    for linea in r.stdout.splitlines():
        p = linea.split(" ")
        if p[0] == "OBJMAL":
            objmal += 1
            if "se leyó" in linea:
                malas.append("un .obj con errores se leyó: " + linea)
            continue
        if p[0] != "ESC":
            malas.append("inesperado: " + linea[:100])
            continue
        k, tipo, modo, W, H = (int(x) for x in p[1:6])
        ang, ox, oy, oz, fov, lx, ly, lz, cerca = (float(x) for x in p[6:15])
        col = int(p[15]) & 0xFFFFFFFF
        buf = p[16]
        obtenido = [int(buf[i:i + 8], 16) for i in range(0, len(buf), 8)]
        M = mm(rot_y(ang), rot_x(ang * 0.5))
        fondo = 0xFF050514
        esperado = dibujar(W, H, fondo, mallas[tipo], M, [ox, oy, oz], fov, [lx, ly, lz], col, modo, cerca)
        escenas += 1
        pixeles += len(esperado)
        dist = sum(1 for a, b in zip(obtenido, esperado) if a != b)
        distintos_total += dist
        pintados = sum(1 for v in esperado if v != fondo)
        if len(obtenido) != len(esperado) or dist > 0.005 * len(esperado):
            malas.append(f"escena {k} (malla {tipo}, modo {modo}): {dist} píxeles distintos de {len(esperado)}")
        elif pintados == 0:
            malas.append(f"escena {k}: no se ve nada (la escena no prueba nada)")
        if k >= 18 and cortados == 0:
            malas.append(f"escena {k}: el plano cercano no corta ningún triángulo (no prueba el recorte)")
        recortadas += 1 if cortados else 0
    if malas or escenas < 24 or objmal < 2:
        for m in malas[:15]:
            print("  ", m)
        print(f"test_motor3d_python: FALLA, {len(malas)} problemas en {escenas} escenas")
        return 1
    print(f"OK: motor3d igual a la referencia en Python: {escenas} escenas (cubo, esfera y .obj; plano, Gouraud "
          f"y alambre; {recortadas} con triángulos cortados por el plano cercano), {pixeles} píxeles, "
          f"{distintos_total} distintos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
