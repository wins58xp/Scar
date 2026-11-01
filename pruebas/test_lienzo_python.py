"""lib/lienzo contra una referencia en Python.

    python3 pruebas/test_lienzo_python.py

Compila y corre pruebas/lienzo_python.scar, que dibuja 60 escenas al azar y
escribe cada operación y el lienzo final. Acá cada escena se dibuja de nuevo
con una implementación aparte, escrita para comparar y no para ser rápida:

- el círculo lleno y el polígono lleno se deciden píxel por píxel (¿el centro
  está adentro?), no por filas como en la librería;
- el borde de un círculo y de un polígono se arman como un conjunto de puntos
  (cada píxel una vez), sin los casos especiales de la librería;
- la línea es el Bresenham de los libros, y la mezcla por alfa, la fórmula
  "over" escrita con los canales por separado.

Lienzos de 1x1 a 40x30, coordenadas fuera del lienzo, radios negativos y
cero, polígonos de 1 a 6 vértices (también los que se cruzan), y colores
opacos, a medias, al azar y transparentes, sobre fondos opacos y
transparentes. Se compara cada píxel y la suma de control.
"""

import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def u32(c):
    return c & 0xFFFFFFFF


def canales(c):
    c = u32(c)
    return (c >> 24) & 255, (c >> 16) & 255, (c >> 8) & 255, c & 255


def mezclar(fondo, c):
    sa, sr, sg, sb = canales(c)
    if sa == 255:
        return u32(c)
    if sa == 0:
        return u32(fondo)
    da, dr, dg, db = canales(fondo)
    resto = da * (255 - sa)
    oa = sa * 255 + resto

    def canal(s, d):
        return (s * sa * 255 + d * resto + oa // 2) // oa

    a = (oa + 127) // 255
    return (a << 24) | (canal(sr, dr) << 16) | (canal(sg, dg) << 8) | canal(sb, db)


class Lienzo:
    def __init__(self, w, h, fondo):
        self.w, self.h = w, h
        self.p = [u32(fondo)] * (w * h)

    def pintar(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = y * self.w + x
            self.p[i] = mezclar(self.p[i], c)

    def pintar_conjunto(self, puntos, c):
        for x, y in sorted(set(puntos)):
            self.pintar(x, y, c)


def bresenham(x0, y0, x1, y1):
    """El de los libros (Wikipedia, "all cases")."""
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


def circulo(cx, cy, r):
    if r < 0:
        return []
    puntos = []
    x, y, err = r, 0, 1 - r
    while x >= y:
        for a, b in ((x, y), (y, x)):
            for sx in (1, -1):
                for sy in (1, -1):
                    puntos.append((cx + sx * a, cy + sy * b))
        y += 1
        if err < 0:
            err += 2 * y + 1
        else:
            x -= 1
            err += 2 * (y - x) + 1
    return puntos


def dentro_poligono(px, py, xs, ys):
    """Par-impar: cuántos lados cruza una semirrecta hacia la derecha desde el
    centro del píxel (el corte se calcula con la misma cuenta que la librería,
    para que un centro justo sobre un lado se decida igual)."""
    n = len(xs)
    yc, xc = py + 0.5, px + 0.5
    adentro = False
    for i in range(n):
        j = (i + 1) % n
        ya, yb = float(ys[i]), float(ys[j])
        if (ya <= yc < yb) or (yb <= yc < ya):
            xa, xb = float(xs[i]), float(xs[j])
            corte = xa + (yc - ya) * (xb - xa) / (yb - ya)
            if corte > xc:
                adentro = not adentro
    return adentro


def dibujar(l, op):
    tipo = op[0]
    a = [int(v) for v in op[1:]]
    if tipo == "linea":
        x0, y0, x1, y1, c = a
        l.pintar_conjunto(bresenham(x0, y0, x1, y1), c)
    elif tipo == "rect":
        x, y, w, h, c = a
        if w > 0 and h > 0:
            borde = [(xx, yy) for yy in range(y, y + h) for xx in range(x, x + w)
                     if xx in (x, x + w - 1) or yy in (y, y + h - 1)]
            l.pintar_conjunto(borde, c)
    elif tipo == "rect_lleno":
        x, y, w, h, c = a
        l.pintar_conjunto([(xx, yy) for yy in range(y, y + h) for xx in range(x, x + w)], c)
    elif tipo == "circulo":
        cx, cy, r, c = a
        l.pintar_conjunto(circulo(cx, cy, r), c)
    elif tipo == "circulo_lleno":
        cx, cy, r, c = a
        if r >= 0:
            l.pintar_conjunto([(x, y) for y in range(cy - r, cy + r + 1) for x in range(cx - r, cx + r + 1)
                               if (x - cx) ** 2 + (y - cy) ** 2 <= r * r], c)
    elif tipo in ("poligono", "poligono_lleno"):
        c, n = a[0], a[1]
        xs, ys = a[2:2 + 2 * n:2], a[3:3 + 2 * n:2]
        if tipo == "poligono":
            puntos = []
            for i in range(n):
                j = (i + 1) % n
                puntos += bresenham(xs[i], ys[i], xs[j], ys[j])
            l.pintar_conjunto(puntos, c)
        elif n >= 3:
            l.pintar_conjunto([(x, y) for y in range(l.h) for x in range(l.w)
                               if dentro_poligono(x, y, xs, ys)], c)
    elif tipo == "copiar":
        sw, sh, c, x0, y0 = a
        for y in range(sh):
            for x in range(sw):
                l.pintar(x0 + x, y0 + y, 0 if (x, y) == (0, 0) else c)
    else:
        raise ValueError(tipo)


def suma(l):
    h = 0
    for p in l.p:
        h = (h * 31 + p) % 2147483647
    return h


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "l")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/lienzo_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_lienzo_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=RAIZ, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_lienzo_python: FALLA, el programa terminó con", r.returncode)
            return 1

    malas = []
    escenas = pixeles = ops = 0
    tipos = set()
    l = None
    for linea in r.stdout.splitlines():
        p = linea.split()
        if p[0] == "L":
            k, w, h, fondo = int(p[1]), int(p[2]), int(p[3]), int(p[4])
            l = Lienzo(w, h, fondo)
        elif p[0] == "OP":
            dibujar(l, p[2:])
            tipos.add(p[2])
            ops += 1
        elif p[0] == "BUF":
            k, s, buf = int(p[1]), int(p[2]), p[3] if len(p) > 3 else ""
            obtenido = [int(buf[i:i + 8], 16) for i in range(0, len(buf), 8)]
            escenas += 1
            pixeles += len(obtenido)
            if obtenido != l.p:
                distintos = [i for i in range(len(l.p)) if i >= len(obtenido) or obtenido[i] != l.p[i]]
                i = distintos[0]
                malas.append(f"escena {k}: {len(distintos)} píxeles distintos; el primero ({i % l.w}, {i // l.w}): "
                             f"SCAR {obtenido[i] if i < len(obtenido) else None:08x}, Python {l.p[i]:08x}")
            elif s != suma(l):
                malas.append(f"escena {k}: suma SCAR {s}, Python {suma(l)}")
    if malas or escenas < 60 or len(tipos) < 8:
        for m in malas[:10]:
            print("  ", m)
        print(f"test_lienzo_python: FALLA, {len(malas)} escenas distintas de {escenas}")
        return 1
    print(f"OK: lienzo igual a la referencia en Python: {escenas} escenas, {ops} operaciones, "
          f"{pixeles} píxeles (líneas, rectángulos, círculos, polígonos y copias, con alfa)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
