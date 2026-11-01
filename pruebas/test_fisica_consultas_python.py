"""lib/fisica (rayos, cuerpo_en, contactos_de, impulso) contra una referencia en Python.

    python3 pruebas/test_fisica_consultas_python.py

pruebas/fisica_consultas_python.scar arma 10 mundos al azar (círculos y cajas), tira 60 rayos por mundo
(sueltos, paralelos a un eje, apuntados a un centro, y con el origen adentro de un cuerpo), pregunta por 40
puntos (más 4 pegados al borde de cada cuerpo, adentro y afuera) y por los contactos de cada cuerpo, y da un impulso. Acá se calcula todo de otra manera:
  - rayo contra círculo: por la proyección del centro sobre el rayo (distancia mínima y cuerda);
  - rayo contra caja: contra cada uno de los 4 lados por separado, quedándose con el más cercano;
  - contactos: círculo-círculo por distancia, caja-caja por solape de intervalos, círculo-caja por el
    punto de la caja más cercano al centro;
  - además cada rayo se comprueba marchando por él de a 0,005: nunca puede haber un cuerpo adentro antes
    del t que dio la librería, y si no dio en nada no puede haber ninguno en todo el recorrido.
Autocomprobación: si se estropea una línea de la salida, el comparador lo tiene que notar.
"""

import math
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL = 1e-9


class Cuerpo:
    def __init__(self, forma, x, y, s1, s2, masa):
        self.f, self.x, self.y, self.masa = forma, x, y, masa
        if forma == 0:
            self.r = s1
        else:
            self.a, self.b = s1 / 2, s2 / 2

    def adentro(self, px, py, estricto=True):
        dx, dy = px - self.x, py - self.y
        if self.f == 0:
            return dx * dx + dy * dy < self.r * self.r if estricto else dx * dx + dy * dy <= self.r * self.r
        if estricto:
            return abs(dx) < self.a and abs(dy) < self.b
        return abs(dx) <= self.a and abs(dy) <= self.b


def rayo_cuerpo(c, ox, oy, dx, dy, maximo):
    """(t, nx, ny) o None."""
    if c.adentro(ox, oy, estricto=False):
        return (0.0, -dx, -dy)
    if c.f == 0:
        vx, vy = c.x - ox, c.y - oy
        tca = vx * dx + vy * dy
        d2 = vx * vx + vy * vy - tca * tca
        if tca < 0 or d2 > c.r * c.r:
            return None
        t = tca - math.sqrt(c.r * c.r - d2)
        if t > maximo:
            return None
        return (t, (ox + dx * t - c.x) / c.r, (oy + dy * t - c.y) / c.r)
    mejor = None
    for lado in range(4):
        if lado < 2:
            sg = 1 if lado == 0 else -1
            xe = c.x + sg * c.a
            if dx == 0:
                continue
            t = (xe - ox) / dx
            y = oy + dy * t
            ok = t >= 0 and abs(y - c.y) <= c.b
            nor = (sg, 0.0)
        else:
            sg = 1 if lado == 2 else -1
            ye = c.y + sg * c.b
            if dy == 0:
                continue
            t = (ye - oy) / dy
            x = ox + dx * t
            ok = t >= 0 and abs(x - c.x) <= c.a
            nor = (0.0, sg)
        if ok and (mejor is None or t < mejor[0]):
            mejor = (t, nor[0], nor[1])
    if mejor is None or mejor[0] > maximo:
        return None
    return mejor


def se_tocan(i, j):
    if i.f == 0 and j.f == 0:
        return math.hypot(j.x - i.x, j.y - i.y) < i.r + j.r
    if i.f == 1 and j.f == 1:
        return abs(j.x - i.x) < i.a + j.a and abs(j.y - i.y) < i.b + j.b
    c, k = (i, j) if i.f == 0 else (j, i)
    qx = min(k.x + k.a, max(k.x - k.a, c.x))
    qy = min(k.y + k.b, max(k.y - k.b, c.y))
    return (c.x - qx) ** 2 + (c.y - qy) ** 2 < c.r * c.r


def cerca(a, b):
    return abs(a - b) <= TOL * max(1.0, abs(a), abs(b))


def revisar(salida):
    errores = []
    mundo = -1
    cuerpos = []
    nrayos = 0
    vistos = {"RAYO": 0, "PUNTO": 0, "CONTACTOS": 0, "IMPULSO": 0}
    hits = 0
    for linea in salida:
        p = linea.split()
        if not p:
            continue
        if p[0] == "MUNDO":
            mundo = int(p[1])
            cuerpos = []
        elif p[0] == "CUERPO":
            cuerpos.append(Cuerpo(int(p[1]), *map(float, p[2:7])))
        elif p[0] == "RAYO0":
            if p[1] != "-1":
                errores.append("rayo sin dirección dio en algo")
        elif p[0] == "RAYO":
            ox, oy, dx0, dy0, maximo = map(float, p[1:6])
            cuerpo = int(p[6])
            t, x, y, nx, ny = map(float, p[7:12])
            vistos["RAYO"] += 1
            largo = math.hypot(dx0, dy0)
            dx, dy = dx0 / largo, dy0 / largo
            mejor = None
            for i, c in enumerate(cuerpos):
                h = rayo_cuerpo(c, ox, oy, dx, dy, maximo)
                if h is not None and (mejor is None or h[0] < mejor[1][0]):
                    mejor = (i, h)
            if mejor is None:
                if cuerpo != -1:
                    errores.append("mundo %d: rayo dio en %d y no debía dar en nada" % (mundo, cuerpo))
                # marcha: no puede haber ningún cuerpo en todo el recorrido
                s = 0.0
                while s <= maximo:
                    if any(c.adentro(ox + dx * s, oy + dy * s) for c in cuerpos):
                        errores.append("mundo %d: no dio en nada pero hay un cuerpo a t=%.3f" % (mundo, s))
                        break
                    s += 0.005
            else:
                hits += 1
                i, (te, nex, ney) = mejor
                if cuerpo != i or not (cerca(t, te) and cerca(nx, nex) and cerca(ny, ney)
                                       and cerca(x, ox + dx * te) and cerca(y, oy + dy * te)):
                    errores.append("mundo %d: rayo esperaba cuerpo %d t=%r n=(%r,%r) y dio %d t=%r n=(%r,%r)"
                                   % (mundo, i, te, nex, ney, cuerpo, t, nx, ny))
                s = 0.0
                while s < te - 0.02:
                    if any(c.adentro(ox + dx * s, oy + dy * s) for c in cuerpos):
                        errores.append("mundo %d: hay un cuerpo antes (t=%.3f) del que dio la librería" % (mundo, s))
                        break
                    s += 0.005
        elif p[0] == "PUNTO":
            px, py = float(p[1]), float(p[2])
            vistos["PUNTO"] += 1
            esp = next((i for i, c in enumerate(cuerpos) if c.adentro(px, py)), -1)
            if int(p[3]) != esp:
                errores.append("mundo %d: punto (%r, %r) esperaba %d y dio %s" % (mundo, px, py, esp, p[3]))
        elif p[0] == "CONTACTOS":
            c = int(p[1])
            vistos["CONTACTOS"] += 1
            esp = [j for j in range(len(cuerpos)) if j != c and se_tocan(cuerpos[c], cuerpos[j])]
            obt = [int(v) for v in p[3:]]
            if obt != esp or int(p[2]) != len(esp):
                errores.append("mundo %d: contactos de %d esperaba %s y dio %s" % (mundo, c, esp, obt))
        elif p[0] == "IMPULSO":
            jx, jy, vx, vy = map(float, p[1:5])
            vistos["IMPULSO"] += 1
            im = 1.0 / cuerpos[0].masa
            if not (cerca(vx, 1.0 + jx * im) and cerca(vy, 2.0 + jy * im)):
                errores.append("mundo %d: impulso da (%r, %r)" % (mundo, vx, vy))
    esperados = {"RAYO": 600, "PUNTO": None, "CONTACTOS": None, "IMPULSO": 10}
    for k, v in esperados.items():
        if v is not None and vistos[k] != v:
            errores.append("se esperaban %d líneas %s y hay %d" % (v, k, vistos[k]))
    if vistos["PUNTO"] < 400:
        errores.append("faltan puntos: %d" % vistos["PUNTO"])
    return errores, hits, vistos


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "fc")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/fisica_consultas_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print("test_fisica_consultas_python: FALLA al compilar\n" + b.stdout[-800:] + b.stderr[-800:])
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("test_fisica_consultas_python: FALLA, el programa terminó con", r.returncode)
        return 1
    salida = r.stdout.strip().splitlines()
    errores, hits, vistos = revisar(salida)
    if errores:
        print("test_fisica_consultas_python: FALLA\n  " + "\n  ".join(errores[:10]))
        return 1
    if hits < 150:
        print("test_fisica_consultas_python: FALLA, solo %d rayos dieron en algo (poca cobertura)" % hits)
        return 1
    # autocomprobación: se estropea un rayo que dio en algo, un punto y un contacto
    for pref, cambio in (("RAYO ", lambda p: p[:7] + [str(float(p[7]) + 0.001)] + p[8:]),
                         ("PUNTO ", lambda p: p[:3] + [str(int(p[3]) + 1)]),
                         ("IMPULSO ", lambda p: p[:3] + [str(float(p[3]) + 0.5)] + p[4:])):
        malo = list(salida)
        for i, l in enumerate(malo):
            p = l.split()
            if l.startswith(pref) and (pref != "RAYO " or p[6] != "-1"):
                malo[i] = " ".join(cambio(p))
                break
        if not revisar(malo)[0]:
            print("test_fisica_consultas_python: FALLA, la autocomprobación no notó un cambio en", pref)
            return 1
    print("test_fisica_consultas_python: OK (%d rayos, %d dieron en algo, %d puntos, %d impulsos)"
          % (vistos["RAYO"], hits, vistos["PUNTO"], vistos["IMPULSO"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
