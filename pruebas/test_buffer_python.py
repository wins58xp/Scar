"""lib/buffer (el texto de un editor) contra un modelo de referencia escrito en Python.

    python3 pruebas/test_buffer_python.py            (SCAR_SEMILLA=n para otra)

Python inventa un texto y una larga lista de pasos al azar (escribir, pegar, Enter con sangría,
Tab, Retroceso, Supr, movimientos con y sin Mayús, por palabras, por páginas, seleccionar, deshacer,
rehacer, buscar, reemplazar) y los escribe en casos.json; pruebas/buffer_python.scar los aplica con
lib/buffer y escribe el estado después de cada uno (texto, cursor, ancla, cuántos pasos hay para
deshacer y rehacer, si está modificado). El modelo de Python hace lo mismo con otra estructura (un
solo texto con posiciones corridas, en vez de una lista de líneas) y los estados tienen que ser
iguales, paso por paso. Además:

  - los colores (buffer.clases) de líneas de código de verdad (las de los .scar del repositorio) y
    de líneas armadas para los bordes (comillas sin cerrar, \\ al final, 1..10, 1e-5, nombres con
    tilde), contra otra implementación en Python;
  - una autocomprobación: si se estropea un estado, el comparador lo tiene que notar.
"""

import glob
import json
import os
import random
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLAVES = set("fn task spawn let mut return if else while for in struct true false and or not Ok Err Result Chan Some None print extern from type own accepts break enum match use export continue".split())
TIPOS = set("i32 i64 f64 str bool Vec Option Map Result Chan String".split())


def cps(s):
    return ",".join(str(ord(c)) for c in s) if s else "_"


# ---------------------------------------------------------------------------------------------
# El modelo: un texto, y las posiciones como (fila, columna) que se pasan a corrimientos
# ---------------------------------------------------------------------------------------------

def partir(t):
    return t.replace("\r", "").replace("\t", "    ").split("\n")


CIERRES = {"(": ")", "[": "]", "{": "}", '"': '"'}


def clase_car(ch):
    if ch is None or ch == " ":
        return 0
    o = ord(ch)
    if ch.isascii() and (ch.isalnum() or ch == "_") or o >= 128:
        return 1
    return 2


class Modelo:
    def __init__(self, t):
        self.L = partir(t)
        self.f = self.c = self.af = self.ac = self.ideal = 0
        self.sucio = False
        self.tipo = 0
        self.U = []
        self.R = []
        self.pares = False

    # posiciones <-> corrimientos
    def texto(self):
        return "\n".join(self.L)

    def off(self, f, c):
        return sum(len(x) + 1 for x in self.L[:f]) + c

    def pos(self, o):
        t = self.texto()
        return t.count("\n", 0, o), o - (t.rfind("\n", 0, o) + 1)

    def car(self, f, c):
        l = self.L[f]
        return l[c] if 0 <= c < len(l) else None

    def hay_sel(self):
        return (self.af, self.ac) != (self.f, self.c)

    def sel(self):
        a, b = (self.af, self.ac), (self.f, self.c)
        return (a, b) if a <= b else (b, a)

    def sel_off(self):
        (f1, c1), (f2, c2) = self.sel()
        return self.off(f1, c1), self.off(f2, c2)

    # movimientos
    def ir(self, f, c, ext):
        f = max(0, min(f, len(self.L) - 1))
        c = max(0, min(c, len(self.L[f])))
        self.f, self.c = f, c
        if not ext:
            self.af, self.ac = f, c
        self.ideal = c
        self.tipo = 0

    def izq(self, ext, pal):
        if self.hay_sel() and not ext:
            (f1, c1), _ = self.sel()
            self.ir(f1, c1, False)
            return
        l = self.L[self.f]
        if self.c == 0:
            if self.f > 0:
                self.ir(self.f - 1, len(self.L[self.f - 1]), ext)
        else:
            c = self.c - 1
            if pal:
                while c > 0 and clase_car(l[c]) == 0:
                    c -= 1
                k = clase_car(l[c])
                while c > 0 and clase_car(l[c - 1]) == k:
                    c -= 1
            self.ir(self.f, c, ext)

    def der(self, ext, pal):
        if self.hay_sel() and not ext:
            _, (f2, c2) = self.sel()
            self.ir(f2, c2, False)
            return
        l = self.L[self.f]
        n = len(l)
        if self.c >= n:
            if self.f < len(self.L) - 1:
                self.ir(self.f + 1, 0, ext)
        else:
            c = self.c + 1
            if pal:
                c = self.c
                while c < n and clase_car(l[c]) == 0:
                    c += 1
                if c < n:
                    k = clase_car(l[c])
                    while c < n and clase_car(l[c]) == k:
                        c += 1
            self.ir(self.f, c, ext)

    def arr(self, ext):
        ideal = self.ideal
        if self.f > 0:
            self.ir(self.f - 1, ideal, ext)
            self.ideal = ideal
        else:
            self.ir(0, 0, ext)

    def abj(self, ext):
        ideal = self.ideal
        if self.f < len(self.L) - 1:
            self.ir(self.f + 1, ideal, ext)
            self.ideal = ideal
        else:
            self.ir(self.f, len(self.L[self.f]), ext)

    def pag(self, d, ext):
        ideal = self.ideal
        self.ir(self.f + d, ideal, ext)
        self.ideal = ideal

    def inicio(self, ext, doc):
        if doc:
            self.ir(0, 0, ext)
        else:
            l = self.L[self.f]
            k = len(l) - len(l.lstrip(" "))
            if self.c == k:
                k = 0
            self.ir(self.f, k, ext)

    def fin(self, ext, doc):
        if doc:
            u = len(self.L) - 1
            self.ir(u, len(self.L[u]), ext)
        else:
            self.ir(self.f, len(self.L[self.f]), ext)

    def todo(self):
        u = len(self.L) - 1
        self.ir(0, 0, False)
        self.ir(u, len(self.L[u]), True)

    def palabra(self):
        l = self.L[self.f]
        n = len(l)
        a = z = self.c
        k = clase_car(self.car(self.f, self.c))
        if k == 0 and self.c > 0:
            k = clase_car(self.car(self.f, self.c - 1))
            a = z = self.c - 1
        if k != 0:
            while a > 0 and clase_car(l[a - 1]) == k:
                a -= 1
            while z < n and clase_car(l[z]) == k:
                z += 1
        self.ir(self.f, a, False)
        self.ir(self.f, z, True)

    # editar
    def editar(self, lo, hi, nuevo, tipo):
        t = self.texto()
        dele = t[lo:hi]
        if dele == "" and nuevo == "":
            return
        juntado = False
        if self.U and self.tipo == tipo and tipo != 0:
            rl, rd, ri = self.U[-1]
            if tipo == 1 and dele == "" and "\n" not in nuevo and rl + len(ri) == lo:
                self.U[-1] = (rl, rd, ri + nuevo)
                juntado = True
            if tipo == 2 and ri == "" and "\n" not in rd and "\n" not in dele and rl == hi:
                self.U[-1] = (lo, dele + rd, "")
                juntado = True
            if tipo == 3 and ri == "" and "\n" not in rd and "\n" not in dele and rl == lo:
                self.U[-1] = (rl, rd + dele, "")
                juntado = True
        if not juntado:
            self.U.append((lo, dele, nuevo))
        self.R = []
        self.L = (t[:lo] + nuevo + t[hi:]).split("\n")
        self.f, self.c = self.pos(lo + len(nuevo))
        self.af, self.ac = self.f, self.c
        self.ideal = self.c
        self.tipo = tipo
        self.sucio = True

    def insertar(self, s):
        lo, hi = self.sel_off()
        self.editar(lo, hi, s, 1)

    def escribir(self, s):
        if self.pares and not self.hay_sel() and len(s) == 1 and self.escribir_par(s):
            return
        solo = self.c >= 4 and not self.hay_sel() and all(ch == " " for ch in self.L[self.f][:self.c])
        if s == "}" and solo:
            self.editar(self.off(self.f, self.c - 4), self.off(self.f, self.c), "}", 1)
        else:
            self.insertar(s)

    def pegar(self, s):
        lo, hi = self.sel_off()
        self.editar(lo, hi, s.replace("\r", "").replace("\t", "    "), 0)

    def borrar_sel(self):
        lo, hi = self.sel_off()
        self.editar(lo, hi, "", 0)

    def enter(self):
        (f1, c1), (f2, c2) = self.sel()
        lo, hi = self.sel_off()
        l = self.L[f1]
        ind = 0
        while ind < c1 and self.car(f1, ind) == " ":
            ind += 1
        k = c1 - 1
        while k >= 0 and self.car(f1, k) == " ":
            k -= 1
        abre = self.car(f1, k) == "{"
        cierra = self.car(f2, c2) == "}"
        if abre and cierra:
            self.editar(lo, hi, "\n" + " " * (ind + 4) + "\n" + " " * ind, 0)
            self.ir(f1 + 1, ind + 4, False)
        else:
            self.editar(lo, hi, "\n" + " " * (ind + (4 if abre else 0)), 0)

    def sangrar(self, atras):
        (f1, c1), (f2, c2) = self.sel()
        if c2 == 0 and f2 > f1:
            f2 -= 1
        nuevo = []
        for k in range(f1, f2 + 1):
            l = self.L[k]
            if atras:
                q = 0
                while q < 4 and q < len(l) and l[q] == " ":
                    q += 1
                nuevo.append(l[q:])
            else:
                nuevo.append("    " + l if l else l)
        self.editar(self.off(f1, 0), self.off(f2, len(self.L[f2])), "\n".join(nuevo), 0)
        self.af, self.ac = f1, 0
        self.f, self.c = f2, len(self.L[f2])

    def tab(self, atras):
        if self.hay_sel() and self.af != self.f:
            self.sangrar(atras)
        elif atras:
            l = self.L[self.f]
            q = 0
            while q < 4 and q < len(l) and l[q] == " ":
                q += 1
            c = self.c
            self.editar(self.off(self.f, 0), self.off(self.f, q), "", 0)
            self.ir(self.f, max(0, c - q), False)
        else:
            c = self.sel()[0][1]
            self.insertar(" " * (4 - c % 4))

    def bs(self, pal):
        if self.pares and not self.hay_sel() and not pal and self.c > 0:
            a, z = self.car(self.f, self.c - 1), self.car(self.f, self.c)
            if a in CIERRES and z == CIERRES[a]:
                self.editar(self.off(self.f, self.c - 1), self.off(self.f, self.c + 1), "", 2)
                return
        if self.hay_sel():
            self.borrar_sel()
        elif self.c > 0:
            if pal:
                f, c = self.f, self.c
                self.izq(True, True)
                self.editar(self.off(f, self.c), self.off(f, c), "", 0)
            else:
                self.editar(self.off(self.f, self.c - 1), self.off(self.f, self.c), "", 2)
        elif self.f > 0:
            self.editar(self.off(self.f - 1, len(self.L[self.f - 1])), self.off(self.f, 0), "", 0)

    def dele(self, pal):
        if self.hay_sel():
            self.borrar_sel()
        else:
            n = len(self.L[self.f])
            if self.c < n:
                if pal:
                    f, c = self.f, self.c
                    self.der(True, True)
                    self.editar(self.off(f, c), self.off(f, self.c), "", 0)
                else:
                    self.editar(self.off(self.f, self.c), self.off(self.f, self.c + 1), "", 3)
            elif self.f < len(self.L) - 1:
                self.editar(self.off(self.f, n), self.off(self.f + 1, 0), "", 0)

    # ---- pares, comentar, duplicar, pareja, historial (otra escritura de las reglas de lib/buffer) ----
    def escribir_par(self, s):
        sig, ant = self.car(self.f, self.c), self.car(self.f, self.c - 1)
        if s in ')]}"' and sig == s:
            self.ir(self.f, self.c + 1, False)
            return True
        deja = sig is None or sig in " )]},"
        if s in "([{" and deja:
            self.insertar(s + CIERRES[s])
            self.ir(self.f, self.c - 1, False)
            return True
        if s == '"' and deja and clase_car(ant) != 1 and ant != '"' and ant != "\\":
            self.insertar('""')
            self.ir(self.f, self.c - 1, False)
            return True
        return False

    def lineas_sel(self):
        (f1, c1), (f2, c2) = self.sel()
        if c2 == 0 and f2 > f1:
            f2 -= 1
        return f1, f2

    def comentar(self):
        f1, f2 = self.lineas_sel()
        varias = self.hay_sel() and self.af != self.f
        llenas = [l for l in self.L[f1:f2 + 1] if l.strip(" ")]
        if not llenas:
            return
        sang = lambda l: len(l) - len(l.lstrip(" "))
        todas = all(l.lstrip(" ").startswith("#") for l in llenas)
        menor = min(sang(l) for l in llenas)
        fila, col, viejo = self.f, self.c, len(self.L[self.f])
        nuevas, lugar = [], 0
        for k in range(f1, f2 + 1):
            l = self.L[k]
            if l.strip(" "):
                i = sang(l)
                if todas:
                    q = 2 if l[i + 1:i + 2] == " " else 1
                    l2 = l[:i] + l[i + q:]
                    if k == fila:
                        lugar = i
                else:
                    l2 = l[:menor] + "# " + l[menor:]
                    if k == fila:
                        lugar = menor
            else:
                l2 = l
            nuevas.append(l2)
        self.editar(self.off(f1, 0), self.off(f2, len(self.L[f2])), "\n".join(nuevas), 0)
        if varias:
            self.af, self.ac = f1, 0
            self.f, self.c = f2, len(self.L[f2])
            self.ideal = self.c
        else:
            d = len(self.L[fila]) - viejo
            nc = col
            if d > 0 and col >= lugar:
                nc = col + d
            if d < 0:
                if col >= lugar - d:
                    nc = col + d
                elif col > lugar:
                    nc = lugar
            self.f, self.c, self.af, self.ac, self.ideal = fila, nc, fila, nc, nc

    def duplicar(self):
        f1, f2 = self.lineas_sel()
        n = f2 - f1 + 1
        bloque = "".join("\n" + l for l in self.L[f1:f2 + 1])
        fila, col, af, ac = self.f, self.c, self.af, self.ac
        fin = self.off(f2, len(self.L[f2]))
        self.editar(fin, fin, bloque, 0)
        self.f, self.c, self.af, self.ac, self.ideal = fila + n, col, af + n, ac, col

    def pareja(self):
        """Recorre el texto como una lista de (fila, col, carácter) que son código."""
        def es_llave(ch):
            return ch is not None and ch in "()[]{}"
        cl = clases_py(self.L[self.f])
        c0 = None
        for c in (self.c, self.c - 1):
            ch = self.car(self.f, c)
            if es_llave(ch) and cl[c] not in (3, 5):
                c0 = c
                break
        if c0 is None:
            return "P-"
        ch = self.L[self.f][c0]
        adelante = ch in "([{"
        par = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}[ch]
        pos = [(f, c, x) for f, l in enumerate(self.L) for c, (x, k) in enumerate(zip(l, clases_py(l))) if k not in (3, 5)]
        i = pos.index((self.f, c0, ch))
        rango = pos[i + 1:] if adelante else reversed(pos[:i])
        prof = 0
        for f, c, x in rango:
            if x == ch:
                prof += 1
            elif x == par:
                if prof == 0:
                    return "P%d,%d,%d,%d" % (self.f, c0, f, c)
                prof -= 1
        return "P-"

    def salir_volver(self):
        # el texto se guarda, se pone otro, y vuelve con su historial: cursor al principio
        self.f = self.c = self.af = self.ac = self.ideal = 0
        self.sucio = False
        self.tipo = 0

    def aplicar(self, lo, hasta_len, nuevo, caret_len):
        t = self.texto()
        self.L = (t[:lo] + nuevo + t[lo + hasta_len:]).split("\n")
        self.f, self.c = self.pos(lo + caret_len)
        self.af, self.ac = self.f, self.c
        self.ideal = self.c
        self.tipo = 0
        self.sucio = True

    def undo(self):
        if not self.U:
            return False
        lo, d, i = self.U.pop()
        self.aplicar(lo, len(i), d, len(d))
        self.R.append((lo, d, i))
        return True

    def redo(self):
        if not self.R:
            return False
        lo, d, i = self.R.pop()
        self.aplicar(lo, len(d), i, len(i))
        self.U.append((lo, d, i))
        return True

    def buscar(self, a, adelante, sensible):
        m = len(a)
        if m == 0:
            return False
        bajar = (lambda s: s) if sensible else (lambda s: s.lower())
        a = bajar(a)
        n = len(self.L)
        (f1, c1), (f2, c2) = self.sel()
        if adelante:
            for paso in range(n + 1):
                f = (f2 + paso) % n
                l = bajar(self.L[f])
                k = l.find(a, c2 if paso == 0 else 0)
                if k >= 0 and (paso < n or k < c2):
                    self.af, self.ac, self.f, self.c = f, k, f, k + m
                    self.ideal = self.c
                    self.tipo = 0
                    return True
        else:
            for paso in range(n + 1):
                f = (f1 - paso + n * 2) % n
                l = bajar(self.L[f])
                if paso == 0:
                    l = l[:c1]
                k = l.rfind(a)
                if k >= 0 and (paso < n or k + m > c1):
                    self.af, self.ac, self.f, self.c = f, k, f, k + m
                    self.ideal = self.c
                    self.tipo = 0
                    return True
        return False

    def reemplazar(self, a, b):
        if not a:
            return 0
        n = len(self.L)
        cuantas = sum(l.count(a) for l in self.L)
        if cuantas:
            nuevo = "\n".join(l.replace(a, b) for l in self.L)
            self.editar(0, len(self.texto()), nuevo, 0)
            self.ir(0, 0, False)
        return cuantas

    def ajustar(self, cols):
        c = max(cols, 8)
        out = []
        for l in self.L:
            if len(l) <= c:
                out.append(l)
            else:
                out.append(l[:c])
                k = c
                while k < len(l):
                    out.append("… " + l[k:k + c - 2])
                    k += c - 2
        self.L = out
        self.f = self.c = self.af = self.ac = self.ideal = 0
        self.tipo = 0
        self.U = []
        self.R = []

    def estado(self):
        return " ".join(str(x) for x in (cps(self.texto()), self.f, self.c, self.af, self.ac,
                                         len(self.U), len(self.R), 1 if self.sucio else 0))


def paso_modelo(m, op):
    n = op[0]
    extra = ""
    if n == "ins": m.insertar(op[1])
    elif n == "esc": m.escribir(op[1])
    elif n == "pegar": m.pegar(op[1])
    elif n == "enter": m.enter()
    elif n == "tab": m.tab(bool(op[1]))
    elif n == "bs": m.bs(bool(op[1]))
    elif n == "del": m.dele(bool(op[1]))
    elif n == "izq": m.izq(bool(op[1]), bool(op[2]))
    elif n == "der": m.der(bool(op[1]), bool(op[2]))
    elif n == "arr": m.arr(bool(op[1]))
    elif n == "abj": m.abj(bool(op[1]))
    elif n == "ini": m.inicio(bool(op[1]), bool(op[2]))
    elif n == "fin": m.fin(bool(op[1]), bool(op[2]))
    elif n == "pag": m.pag(op[1], bool(op[2]))
    elif n == "ir": m.ir(op[1], op[2], bool(op[3]))
    elif n == "todo": m.todo()
    elif n == "pal": m.palabra()
    elif n == "aj": m.ajustar(op[1])
    elif n == "undo": extra = " U1" if m.undo() else " U0"
    elif n == "redo": extra = " U1" if m.redo() else " U0"
    elif n == "buscar": extra = " B1" if m.buscar(op[1], bool(op[2]), bool(op[3])) else " B0"
    elif n == "reemplazar": extra = " R%d" % m.reemplazar(op[1], op[2])
    elif n == "pares": m.pares = bool(op[1])
    elif n == "com":
        m.ir(op[1], op[2], False)
        m.comentar()
    elif n == "ctx":
        m.pares = True
        m.insertar(op[1])
        m.ir(m.f, m.c - op[2], False)
        m.escribir(op[3])
    elif n == "deshist":
        # deshacer, cambiar de pestaña y volver, rehacer: lo de rehacer tiene que sobrevivir al cambio
        m.undo()
        m.salir_volver()
        extra = " U1" if m.redo() else " U0"
    elif n == "dup": m.duplicar()
    elif n == "par":
        m.ir(op[1], op[2], False)
        extra = " " + m.pareja()
    elif n == "hist": m.salir_volver()
    elif n == "sel":
        (f1, c1), (f2, c2) = m.sel()
        lo, hi = m.sel_off()
        extra = " S" + cps(m.texto()[lo:hi])
    return m.estado() + extra


# ---------------------------------------------------------------------------------------------
# Colores: otra implementación
# ---------------------------------------------------------------------------------------------

def letra(ch):
    return ch.isascii() and (ch.isalpha() or ch == "_") or ord(ch) >= 128


def clases_py(s):
    r = [0] * len(s)
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "#":
            for j in range(i, n):
                r[j] = 5
            break
        if ch == '"':
            j = i + 1
            while j < n:
                if s[j] == "\\" and j + 1 < n:
                    j += 2
                elif s[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            for k in range(i, min(j, n)):
                r[k] = 3
            i = j
        elif letra(ch):
            j = i
            while j < n and (letra(s[j]) or s[j] in "0123456789"):
                j += 1
            w = s[i:j]
            if w in CLAVES:
                cl = 1
            elif w in TIPOS or ("A" <= ch <= "Z"):
                cl = 2
            else:
                k = j
                while k < n and s[k] == " ":
                    k += 1
                cl = 6 if k < n and s[k] == "(" else 0
            for k in range(i, j):
                r[k] = cl
            i = j
        elif ch in "0123456789":
            j = i
            while j < n and s[j] in "0123456789":
                j += 1
            if j + 1 < n and s[j] == "." and s[j + 1] in "0123456789":
                j += 1
                while j < n and s[j] in "0123456789":
                    j += 1
            if j < n and s[j] in "eE":
                k = j + 1
                if k < n and s[k] in "+-":
                    k += 1
                if k < n and s[k] in "0123456789":
                    j = k
                    while j < n and s[j] in "0123456789":
                        j += 1
            for k in range(i, j):
                r[k] = 4
            i = j
        else:
            i += 1
    return r


# ---------------------------------------------------------------------------------------------
# Casos al azar
# ---------------------------------------------------------------------------------------------

PALABRAS = ["fn", "main", "let", "x", "yy", "foo_bar", "return", "{", "}", "(", ")", "=", "+", "1", "42", "\"hola\"",
            "#nota", "if", "else", "ñandú", "é", "α", "Vec", "i32", "->", "..", ";", ",", "  ", " ", "Á"]
CARES = list("abcxyz ABCÁñé12_{}()=+-#\"") + ["α", "😀", " ", " "]


def texto_al_azar(rng, lineas=None):
    n = rng.randint(1, 8) if lineas is None else lineas
    out = []
    for _ in range(n):
        ind = " " * rng.choice([0, 0, 2, 4, 4, 8])
        out.append(ind + " ".join(rng.choice(PALABRAS) for _ in range(rng.randint(0, 6))))
    return "\n".join(out)


def paso_al_azar(rng, m):
    """Un paso, mirando el estado del modelo para que haya posiciones y búsquedas que calcen."""
    r = rng.random()
    b = lambda p=0.3: 1 if rng.random() < p else 0
    if r < 0.14:
        # lo nuevo: pares, comentar, duplicar, la llave pareja, el historial por pestaña
        q = rng.random()
        if q < 0.08:
            return ["pares", b(0.7)]
        if q < 0.45:
            return ["esc", rng.choice(list('([{)]}"') + ["x", " "])]
        if q < 0.52:
            # un contexto armado a propósito alrededor del cursor, y una tecla de par
            ctx = rng.choice(['",', '""', "a", '"', ",", ")", "\\", 'x"', " ", "(", "", "]"])
            return ["ctx", ctx, rng.randint(0, len(ctx)), rng.choice(list('([{)]}"'))]
        if q < 0.60:
            # el cursor en una línea al azar, cerca de su sangría (los bordes de "# ")
            f = rng.randrange(len(m.L))
            l = m.L[f]
            ind = len(l) - len(l.lstrip(" "))
            return ["com", f, max(0, ind + rng.choice([-1, 0, 1, 2, 3, 4]))]
        if q < 0.72:
            return ["dup"]
        if q < 0.92:
            # el cursor sobre (o justo después de) una llave al azar del texto, también de las que están
            # dentro de textos o comentarios
            llaves = [(f, c) for f, l in enumerate(m.L) for c, ch in enumerate(l) if ch in "()[]{}"]
            if llaves and rng.random() < 0.9:
                f, c = rng.choice(llaves)
                return ["par", f, c + rng.choice([0, 0, 1])]
            return ["par", m.f, m.c]
        if rng.random() < 0.5:
            return ["hist"]
        return ["deshist"]
    r = rng.random()
    if r < 0.20:
        if rng.random() < 0.4:
            return ["esc", rng.choice(["}", "}", "}", "a", "{"])]
        return ["ins", "".join(rng.choice(CARES) for _ in range(rng.randint(1, 4)))]
    if r < 0.24:
        return ["pegar", "\n".join(" " * rng.choice([0, 1, 4]) + rng.choice(PALABRAS) + rng.choice(["", "\t", "\r"])
                                  for _ in range(rng.randint(1, 4)))]
    if r < 0.30:
        return ["enter"]
    if r < 0.34:
        return ["tab", b()]
    if r < 0.40:
        return ["bs", b(0.15)]
    if r < 0.44:
        return ["del", b(0.15)]
    if r < 0.50:
        return ["izq", b(), b()]
    if r < 0.56:
        return ["der", b(), b()]
    if r < 0.60:
        return ["arr", b()]
    if r < 0.64:
        return ["abj", b()]
    if r < 0.67:
        return ["ini", b(), b(0.2)]
    if r < 0.70:
        return ["fin", b(), b(0.2)]
    if r < 0.72:
        return ["pag", rng.choice([-5, -3, 3, 5, 40, -40]), b()]
    if r < 0.77:
        return ["ir", rng.randint(-1, len(m.L) + 1), rng.randint(-1, 20), b(0.5)]
    if r < 0.78:
        return ["todo"]
    if r < 0.79:
        return ["pal"]
    if r < 0.80:
        return ["aj", rng.choice([0, 5, 8, 9, 12, 30])]
    if r < 0.86:
        return ["undo"]
    if r < 0.90:
        return ["redo"]
    if r < 0.96:
        t = m.texto()
        if t and rng.random() < 0.7:
            i = rng.randrange(len(t))
            frag = t[i:i + rng.randint(1, 3)].replace("\n", "")
        else:
            frag = rng.choice(["a", "x", "É", "é", "fn", "{", "zz"])
        if not frag:
            frag = "a"
        return ["buscar", frag, b(0.7), b(0.5)]
    if r < 0.98:
        return ["reemplazar", rng.choice(["a", "x", "é", "fn", " "]), rng.choice(["", "AA", "ñé", "  "])]
    return ["sel"]


def lineas_de_codigo(rng):
    todas = []
    for f in sorted(glob.glob(os.path.join(RAIZ, "examples", "*.scar")))[:400] + sorted(glob.glob(os.path.join(RAIZ, "lib", "*.scar"))):
        try:
            todas += open(f, encoding="utf-8").read().split("\n")
        except (OSError, UnicodeDecodeError):
            pass
    sel = [l for l in rng.sample(todas, min(500, len(todas))) if len(l) < 200]
    sel += ['"sin cerrar', 'x = "a\\', 'x = "a\\"b" # c', "for i in 0..10 {", "let y = 1e-5 + 2.5E+3 + 1e", "let z = 1.x + 3.",
            "fn ñandú(a: i32) -> Vec<str> {", "   foo (1) + bar(2) + Baz(3)", "#", "", "\"", "\\", "1..2", "0x1F", "é1 é(", "a#b\"c\"",
            "let mut s = \"é\\\"#\" # fin", "Ok(1) Err(\"x\") Some(None)"]
    return sel


def casos_al_azar(rng):
    ini = texto_al_azar(rng)
    m = Modelo(ini)
    ops = []
    for _ in range(3000):
        op = paso_al_azar(rng, m)
        ops.append(op)
        paso_modelo(m, op)
    # los textos van como puntos de código
    codif = []
    for op in ops:
        o = list(op)
        if o[0] == "ctx":
            o[1], o[3] = cps(o[1]), cps(o[3])
        if o[0] in ("ins", "pegar", "esc"):
            o[1] = cps(o[1])
        if o[0] == "buscar":
            o[1] = cps(o[1])
        if o[0] == "reemplazar":
            o[1], o[2] = cps(o[1]), cps(o[2])
        codif.append(o)
    # la llave pareja sobre código de verdad: un archivo del repo y cada una de sus llaves
    codigo = open(os.path.join(RAIZ, "lib", "buffer.scar"), encoding="utf-8").read()
    mc = Modelo(codigo)
    llaves = [[f, c] for f, l in enumerate(mc.L) for c, ch in enumerate(l) if ch in "()[]{}"]
    llaves = rng.sample(llaves, min(600, len(llaves)))
    return {"ini": cps(ini), "ops": codif, "clases": [cps(l) for l in lineas_de_codigo(rng)],
            "codigo": cps(codigo), "llaves": llaves}, ini, ops, lineas_de_codigo


def esperado(ini, ops):
    m = Modelo(ini)
    return [paso_modelo(m, op) for op in ops]


def leer(salida):
    got = {}
    for linea in salida.splitlines():
        p = linea.split(" ", 2)
        if len(p) == 3 and p[0] in ("E", "C", "P") and p[1].isdigit():
            got[(p[0], int(p[1]))] = p[2]
    return got


def comparar(esp_e, esp_c, got, esp_p=()):
    errores = []
    for k, v in enumerate(esp_p):
        g = got.get(("P", k))
        if g != v:
            errores.append(f"pareja {k}: lib={g!r} python={v!r}")
    for k, v in enumerate(esp_e):
        g = got.get(("E", k))
        if g != v:
            errores.append(f"paso {k}: lib={g!r}\n          python={v!r}")
    for k, v in enumerate(esp_c):
        g = got.get(("C", k))
        if g != v:
            errores.append(f"clases {k}: lib={g!r} python={v!r}")
    return errores


def main():
    rng = random.Random(int(os.environ.get("SCAR_SEMILLA", "20")))
    casos, ini, ops, _ = casos_al_azar(rng)
    esp_e = esperado(ini, ops)
    mc = Modelo("".join(chr(int(x)) for x in casos["codigo"].split(",")))
    esp_p = []
    for f, c in casos["llaves"]:
        mc.ir(f, c, False)
        esp_p.append(mc.pareja())
    if sum(1 for x in esp_p if x != "P-") < len(esp_p) * 0.75:
        print("test_buffer_python: FALLA, en el código de verdad casi ninguna llave tiene pareja (¿el modelo?)")
        return 1
    esp_c = []
    for c in casos["clases"]:
        linea = "".join(chr(int(x)) for x in c.split(",")) if c != "_" else ""
        esp_c.append(",".join(str(x) for x in clases_py(linea)))
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w") as f:
            json.dump(casos, f)
        binario = os.path.join(tmp, "b")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/buffer_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_buffer_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or "ERROR" in r.stdout:
        print(r.stdout[-2000:] + r.stderr)
        print("test_buffer_python: FALLA, el programa terminó con", r.returncode)
        return 1
    got = leer(r.stdout)
    errores = comparar(esp_e, esp_c, got, esp_p)
    if errores:
        print("\n".join(errores[:12]))
        print(f"test_buffer_python: FALLA ({len(errores)} diferencias)")
        return 1
    for et in ("E", "C", "P"):
        malo = dict(got)
        clave = next(k for k in malo if k[0] == et)
        malo[clave] = malo[clave] + "9"
        if not comparar(esp_e, esp_c, malo, esp_p):
            print(f"test_buffer_python: FALLA, la autocomprobación no notó un resultado estropeado ({et})")
            return 1
    print(f"OK: lib/buffer contra el modelo de Python: {len(ops)} pasos, {len(esp_c)} líneas coloreadas, "
          f"{len(esp_p)} llaves con su pareja en código de verdad")
    return 0


if __name__ == "__main__":
    sys.exit(main())
