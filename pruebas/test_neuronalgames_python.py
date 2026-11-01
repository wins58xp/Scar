"""lib/neuronalgames contra una referencia en Python.

    python3 pruebas/test_neuronalgames_python.py

pruebas/neuronalgames_python.scar arma 16 redes al azar (1 a 3 capas de 1 a 5 neuronas, las cuatro activaciones,
con y sin momento, con y sin mezclar los ejemplos), las calcula, las entrena, las copia, las muta, las cruza
y las guarda y relee. Acá se rehace todo aparte:
  - el generador xorshift32 de lib/mate y los pesos iniciales de Glorot;
  - el cálculo hacia adelante con math.tanh y la sigmoide de libro (no las fórmulas de la librería);
  - el entrenamiento con matrices por capa y retropropagación escrita de nuevo, y además el gradiente de
    esta referencia se compara con derivadas numéricas (diferencias centradas) para saber que ella
    misma está bien;
  - el error, los aciertos, la mutación y el cruce con el mismo generador;
  - guardar y leer: el texto releído tiene que ser idéntico y la red releída calcular lo mismo bit a bit;
  - y que la red aprenda XOR, y que los textos mal formados den error.
Los pesos tienen que coincidir con diferencia relativa de a lo sumo 1e-8 (tanh y exp de distintas
bibliotecas pueden variar en el último bit). Autocomprobación: si se estropea una línea, se nota.
"""

import math
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL = 1e-8


def s32(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x >= (1 << 31) else x


class Azar:
    def __init__(self, semilla):
        self.x = -1831433054 if semilla == 0 else semilla

    def sig(self):
        x = self.x
        x = s32(x ^ (x << 13))
        x = s32(x ^ ((x >> 17) & 32767))
        x = s32(x ^ (x << 5))
        self.x = x
        return x

    def uniforme(self):
        u = float(self.sig())
        if u < 0:
            u += 4294967296.0
        return u / 4294967296.0

    def entre(self, lo, hi):
        return lo + (hi - lo) * self.uniforme()

    def entero(self, lo, hi):
        k = math.floor(self.uniforme() * float(hi - lo + 1))
        return lo + min(k, hi - lo)


def act(f, z):
    if f == 1:
        return max(z, 0.0)
    if f == 2:
        return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))
    if f == 3:
        return math.tanh(z)
    return z


def dact(f, z, a):
    if f == 1:
        return 1.0 if z > 0 else 0.0
    if f == 2:
        return a * (1 - a)
    if f == 3:
        return 1 - a * a
    return 1.0


class Red:
    def __init__(self, n_in, capas, semilla):
        """capas: [(n, f), ...]. W[l][j][i], b[l][j]."""
        self.n_in, self.capas = n_in, capas
        self.azar = Azar(semilla)
        self.W, self.b = [], []
        ant = n_in
        for n, f in capas:
            lim = math.sqrt(6.0 / (ant + n))
            self.W.append([[self.azar.entre(-lim, lim) for _ in range(ant)] for _ in range(n)])
            self.b.append([0.0] * n)
            ant = n
        self.vW = [[[0.0] * len(fila) for fila in W] for W in self.W]
        self.vb = [[0.0] * len(b) for b in self.b]

    def plano(self):
        return [w for W in self.W for fila in W for w in fila], [x for b in self.b for x in b]

    def adelante(self, x):
        zs, as_ = [], [list(x)]
        for (n, f), W, b in zip(self.capas, self.W, self.b):
            z = [b[j] + sum(W[j][i] * as_[-1][i] for i in range(len(as_[-1]))) for j in range(n)]
            zs.append(z)
            as_.append([act(f, v) for v in z])
        return zs, as_

    def gradiente(self, x, y):
        zs, as_ = self.adelante(x)
        L = len(self.capas)
        deltas = [None] * L
        f = self.capas[-1][1]
        deltas[-1] = [(as_[-1][j] - y[j]) * dact(f, zs[-1][j], as_[-1][j]) for j in range(len(y))]
        for l in range(L - 2, -1, -1):
            f = self.capas[l][1]
            Wn = self.W[l + 1]
            deltas[l] = [sum(Wn[j][i] * deltas[l + 1][j] for j in range(len(Wn))) * dact(f, zs[l][i], as_[l + 1][i])
                         for i in range(self.capas[l][0])]
        gW = [[[deltas[l][j] * as_[l][i] for i in range(len(as_[l]))] for j in range(len(deltas[l]))]
              for l in range(L)]
        gb = [list(deltas[l]) for l in range(L)]
        return gW, gb

    def paso(self, x, y, tasa, mom):
        gW, gb = self.gradiente(x, y)
        for l in range(len(self.capas)):
            for j in range(len(self.W[l])):
                for i in range(len(self.W[l][j])):
                    v = mom * self.vW[l][j][i] - tasa * gW[l][j][i]
                    self.vW[l][j][i] = v
                    self.W[l][j][i] += v
                v = mom * self.vb[l][j] - tasa * gb[l][j]
                self.vb[l][j] = v
                self.b[l][j] += v

    def perdida(self, x, y):
        a = self.adelante(x)[1][-1]
        return 0.5 * sum((a[j] - y[j]) ** 2 for j in range(len(y)))

    def error(self, ej):
        s = 0.0
        for x, y in ej:
            a = self.adelante(x)[1][-1]
            s += sum((a[j] - y[j]) ** 2 for j in range(len(y)))
        return s / (len(ej) * len(ej[0][1]))

    def aciertos(self, ej):
        bien = 0
        for x, y in ej:
            a = self.adelante(x)[1][-1]
            if len(y) == 1:
                bien += (a[0] >= 0.5) == (y[0] >= 0.5)
            else:
                ka = max(range(len(a)), key=lambda j: (a[j], -j))
                ky = max(range(len(y)), key=lambda j: (y[j], -j))
                bien += ka == ky
        return bien / len(ej)


def chequeo_numerico(red, x, y):
    """El gradiente de la referencia contra diferencias centradas (para saber que la referencia está bien)."""
    gW, gb = red.gradiente(x, y)
    eps = 1e-6
    peor = 0.0
    for l in range(len(red.W)):
        for j in range(len(red.W[l])):
            for i in range(len(red.W[l][j])):
                w0 = red.W[l][j][i]
                red.W[l][j][i] = w0 + eps
                mas = red.perdida(x, y)
                red.W[l][j][i] = w0 - eps
                menos = red.perdida(x, y)
                red.W[l][j][i] = w0
                num = (mas - menos) / (2 * eps)
                peor = max(peor, abs(num - gW[l][j][i]) / max(1e-6, abs(num) + abs(gW[l][j][i])))
    return peor


def cerca_lista(a, b):
    return len(a) == len(b) and all(abs(x - y) <= TOL * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


def pesos_de(texto):
    a, b = texto.split("|")
    return [float(v) for v in a.split()], [float(v) for v in b.split()]


def revisar(lineas):
    errores = []
    cuenta = {"redes": 0, "chequeos": 0, "peor_numerico": 0.0}
    red = None
    ej = []
    i = 0
    while i < len(lineas):
        ln = lineas[i]
        p = ln.split()
        i += 1
        if not p:
            continue
        cab = p[0]
        if cab == "RED":
            caso, semilla, mom, mezcla = int(p[1]), int(p[2]), float(p[3]), p[4] == "true"
            forma = ln.split("|")[1].split()
            n_in = int(forma[0])
            capas = [tuple(int(v) for v in c.split(":")) for c in forma[1:]]
            red = Red(n_in, capas, semilla)
            ej = []
            cuenta["redes"] += 1
        elif cab == "INICIO":
            w, b = pesos_de(ln[len("INICIO"):])
            if not cerca_lista(w, red.plano()[0]) or not cerca_lista(b, red.plano()[1]):
                errores.append("red %d: pesos iniciales distintos" % caso)
        elif cab == "CALC":
            partes = ln[len("CALC"):].split("|")
            x = [float(v) for v in partes[0].split()]
            sal = [float(v) for v in partes[1].split()]
            esp = red.adelante(x)[1][-1]
            if not cerca_lista(sal, esp):
                errores.append("red %d: calcular %s da %s y no %s" % (caso, x, sal, esp))
            km = max(range(len(esp)), key=lambda j: (esp[j], -j))
            if int(partes[2]) != km and abs(esp[km] - esp[int(partes[2])]) > 1e-12:
                errores.append("red %d: mayor_salida %s y no %d" % (caso, partes[2].strip(), km))
        elif cab == "EJEMPLO":
            a, b = ln[len("EJEMPLO"):].split("|")
            ej.append(([float(v) for v in a.split()], [float(v) for v in b.split()]))
        elif cab == "ENTRENO":
            vueltas, tasa, e0, e, acc = int(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])
            if not cerca_lista([e0], [red.error(ej)]):
                errores.append("red %d: error antes de entrenar %r y no %r" % (caso, e0, red.error(ej)))
            cuenta["peor_numerico"] = max(cuenta["peor_numerico"], chequeo_numerico(red, *ej[0]))
            cuenta["chequeos"] += 1
            orden = list(range(len(ej)))
            for _ in range(vueltas):
                if mezcla:
                    for k in range(len(orden) - 1, 0, -1):
                        j = red.azar.entero(0, k)
                        orden[k], orden[j] = orden[j], orden[k]
                for k in orden:
                    red.paso(ej[k][0], ej[k][1], tasa, mom)
            if not cerca_lista([e], [red.error(ej)]):
                errores.append("red %d: error después de entrenar %r y no %r" % (caso, e, red.error(ej)))
            if abs(acc - red.aciertos(ej)) > 1e-12:
                errores.append("red %d: aciertos %r y no %r" % (caso, acc, red.aciertos(ej)))
        elif cab == "FINAL":
            w, b = pesos_de(ln[len("FINAL"):])
            if not cerca_lista(w, red.plano()[0]) or not cerca_lista(b, red.plano()[1]):
                errores.append("red %d: pesos después de entrenar distintos" % caso)
        elif cab == "GEMELA":
            if p[1] != "true":
                errores.append("red %d: dos copias entrenadas igual quedaron distintas" % caso)
        elif cab == "SIGUE":
            # la copia, una vuelta más de entrenamiento (sin mezclar: la copia usa la semilla 1), tiene que
            # seguir con el momento de la original
            copia = Red(red.n_in, red.capas, 1)
            copia.W = [[list(f) for f in W] for W in red.W]
            copia.b = [list(b) for b in red.b]
            copia.vW = [[list(f) for f in W] for W in red.vW]
            copia.vb = [list(b) for b in red.vb]
            copia.azar = Azar(1)
            orden = list(range(len(ej)))
            if mezcla:
                for k in range(len(orden) - 1, 0, -1):
                    j = copia.azar.entero(0, k)
                    orden[k], orden[j] = orden[j], orden[k]
            for k in orden:
                copia.paso(ej[k][0], ej[k][1], tasa, mom)
            w, b = pesos_de(ln[len("SIGUE"):])
            if not cerca_lista(w, copia.plano()[0]) or not cerca_lista(b, copia.plano()[1]):
                errores.append("red %d: la copia no siguió entrenando como la original" % caso)
        elif cab == "ENORME":
            if p[1:] != ["true", "true", "true"]:
                errores.append("pesos enormes o diminutos no vuelven exactos: " + ln)
        elif cab == "COPIA":
            if p[1] != "true":
                errores.append("red %d: la copia no es igual" % caso)
        elif cab == "MUTADA":
            prob, fz = float(p[1]), float(p[2])
            w, b = red.plano()
            az = Azar(semilla + 1)
            for lista in (w, b):
                for k in range(len(lista)):
                    if az.uniforme() < prob:
                        lista[k] += az.entre(-fz, fz)
            mw, mb = pesos_de(ln.split("|", 1)[1])
            if not cerca_lista(mw, w) or not cerca_lista(mb, b):
                errores.append("red %d: mutación distinta" % caso)
            mutada = (w, b)
        elif cab == "ORIGINAL_INTACTA":
            w, b = pesos_de(ln[len("ORIGINAL_INTACTA"):])
            if not cerca_lista(w, red.plano()[0]) or not cerca_lista(b, red.plano()[1]):
                errores.append("red %d: mutar la copia cambió la original" % caso)
        elif cab == "HIJA":
            w, b = red.plano()
            az = Azar(semilla + 2)
            for lista, otra in ((w, mutada[0]), (b, mutada[1])):
                for k in range(len(lista)):
                    if az.uniforme() < 0.5:
                        lista[k] = otra[k]
            hw, hb = pesos_de(ln[len("HIJA"):])
            if not cerca_lista(hw, w) or not cerca_lista(hb, b):
                errores.append("red %d: cruce distinto" % caso)
        elif cab in ("RELEER", "RELEIDA_CALCULA_IGUAL"):
            if p[1] != "true":
                errores.append("red %d: %s" % (caso, ln))
        elif cab == "XOR":
            if float(p[1]) > 0.01 or float(p[2]) != 1.0:
                errores.append("no aprendió XOR: " + ln)
        elif cab == "LEER_MAL":
            esp = "OK" if p[1] == "bien" else "ERR"
            if p[2] != esp:
                errores.append("leer el texto '%s' dio %s" % (p[1], p[2]))
    if cuenta["peor_numerico"] > 1e-5:
        errores.append("la referencia no pasa el chequeo numérico del gradiente (%.2e)" % cuenta["peor_numerico"])
    return errores, cuenta


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "nn")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/neuronalgames_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print("test_neuronalgames_python: FALLA al compilar\n" + b.stdout[-800:] + b.stderr[-800:])
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("test_neuronalgames_python: FALLA, el programa terminó con", r.returncode, r.stderr[-300:])
        return 1
    lineas = r.stdout.strip().splitlines()
    errores, cuenta = revisar(lineas)
    if errores:
        print("test_neuronalgames_python: FALLA\n  " + "\n  ".join(errores[:12]))
        return 1
    if cuenta["redes"] != 16:
        print("test_neuronalgames_python: FALLA, se esperaban 16 redes y hay", cuenta["redes"])
        return 1
    for pref in ("INICIO", "CALC", "FINAL", "MUTADA", "HIJA", "ENTRENO"):
        malo = list(lineas)
        for k, l in enumerate(malo):
            if l.startswith(pref + " "):
                q = l.split()
                if pref == "CALC":
                    j = len(q) - 1 - q[::-1].index("|")
                    q[j - 1] = repr(float(q[j - 1]) * 1.001)
                    malo[k] = " ".join(q)
                    break
                for idx in range(len(q) - 1, 0, -1):
                    try:
                        v = float(q[idx])
                    except ValueError:
                        continue
                    if v != 0.0 and pref != "ENTRENO":
                        q[idx] = repr(v * 1.001)
                        break
                    if pref == "ENTRENO" and idx == 4:
                        q[idx] = repr(v * 1.001 + 1e-3)
                        break
                malo[k] = " ".join(q)
                break
        if not revisar(malo)[0]:
            print("test_neuronalgames_python: FALLA, la autocomprobación no notó un cambio en", pref)
            return 1
    print("test_neuronalgames_python: OK (16 redes: inicio, cálculo, entrenamiento, mutación, cruce y guardado; "
          "gradiente de la referencia contra derivadas numéricas: %.1e; XOR aprendido)" % cuenta["peor_numerico"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
