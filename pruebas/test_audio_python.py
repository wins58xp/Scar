"""lib/audio contra Python (el módulo wave y las fórmulas con math).

    python3 pruebas/test_audio_python.py

1. Compila y corre pruebas/audio_python.scar, que genera 30 sonidos al azar
   (seno, cuadrada, sierra, triángulo y ruido con el xorshift32 de mate, con y
   sin envolvente ADSR, solos, mezclados con un seno o en estéreo, con
   amplitudes que pasan de 1 para que se recorten, a 8, 11, 22 y 44 kHz) y
   los guarda como WAV. Acá cada uno se calcula de nuevo con math y se lee el
   WAV con wave: la cabecera (canales, 16 bits, tasa, cuadros) y cada muestra
   tienen que ser iguales.
2. Python deja WAV hechos con wave (mono y estéreo, varias tasas, uno con un
   chunk LIST de largo impar antes de los datos) y otros que tienen que dar
   Err (8 y 24 bits, cortado, sin fmt, no es WAV): SCAR lee los primeros con
   las mismas muestras.
"""

import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import wave

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PI = 3.141592653589793


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


def recortar(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def silencio(tasa, dur):
    return [0.0] * int(math.floor(dur * float(tasa) + 0.5))


def fase(f, i, tasa):
    x = f * float(i) / float(tasa)
    return x - math.floor(x)


def onda(tipo, f, a, dur, tasa):
    s = silencio(tasa, dur)
    for i in range(len(s)):
        if tipo == 0:
            s[i] = a * math.sin(2.0 * PI * f * float(i) / float(tasa))
        elif tipo == 1:
            s[i] = a if fase(f, i, tasa) < 0.5 else 0.0 - a
        elif tipo == 2:
            s[i] = a * (2.0 * fase(f, i, tasa) - 1.0)
        else:
            s[i] = a * (1.0 - 4.0 * abs(fase(f, i, tasa) - 0.5))
    return s


def ruido(a, dur, tasa, semilla):
    s = silencio(tasa, dur)
    g = Xorshift32(semilla)
    return [g.entre(0.0 - a, a) for _ in s]


def ads(t, at, de, so):
    if t < at:
        return t / at
    if t < at + de:
        return 1.0 - (1.0 - so) * (t - at) / de
    return so


def envolvente(t, dur, at, de, so, li):
    suelta = dur - li
    if li > 0.0 and t >= suelta:
        return ads(max(suelta, 0.0), at, de, so) * max(0.0, (dur - t) / li)
    return ads(t, at, de, so)


def a_16(x):
    v = int(math.floor(recortar(x, -1.0, 1.0) * 32767.0 + 0.5))
    return max(-32767, min(32767, v))


def esperado(tipo, modo, tasa, f, a, dur, at, de, so, li, semilla):
    s = ruido(a, dur, tasa, semilla) if tipo == 4 else onda(tipo, f, a, dur, tasa)
    if at > 0.001 and de > 0.001:
        d = float(len(s)) / float(tasa)
        s = [v * envolvente(float(i) / float(tasa), d, at, de, so, li) for i, v in enumerate(s)]
    if modo == 0:
        return 1, s
    if modo == 1:
        b = onda(0, f * 1.5, 0.3, dur, tasa)
        n = max(len(s), len(b))
        return 1, [recortar((s[i] if i < len(s) else 0.0) + (b[i] if i < len(b) else 0.0), -1.0, 1.0)
                   for i in range(n)]
    b = onda(2, f / 2.0, 0.4, dur * 0.5, tasa)
    n = max(len(s), len(b))
    out = []
    for i in range(n):
        out += [s[i] if i < len(s) else 0.0, b[i] if i < len(b) else 0.0]
    return 2, out


def main():
    azar = random.Random(16)
    malas, n = [], 0
    with tempfile.TemporaryDirectory() as dir:
        nombres, leibles = [], {}

        def escribir_wave(nombre, canales, tasa, muestras):
            with wave.open(os.path.join(dir, nombre), "wb") as w:
                w.setnchannels(canales)
                w.setsampwidth(2)
                w.setframerate(tasa)
                w.writeframes(struct.pack(f"<{len(muestras)}h", *muestras))
            nombres.append(nombre)
            leibles[nombre] = (canales, tasa, muestras)

        for k, (canales, tasa) in enumerate(((1, 8000), (2, 22050), (1, 44100), (2, 11025))):
            cuadros = azar.randrange(1, 300)
            escribir_wave(f"py_{k}.wav", canales, tasa,
                          [azar.randrange(-32767, 32768) for _ in range(cuadros * canales)])
        # un chunk LIST de largo impar (con su byte de relleno) antes de los datos
        muestras = [azar.randrange(-32767, 32768) for _ in range(50)]
        datos = struct.pack("<50h", *muestras)
        fmt = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
        lista = b"LIST" + struct.pack("<I", 5) + b"INFOx" + b"\0"
        cuerpo = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + lista + b"data" + struct.pack("<I", 100) + datos
        with open(os.path.join(dir, "con_list.wav"), "wb") as f:
            f.write(b"RIFF" + struct.pack("<I", len(cuerpo)) + cuerpo)
        nombres.append("con_list.wav")
        leibles["con_list.wav"] = (1, 16000, muestras)

        def mal(nombre, contenido):
            with open(os.path.join(dir, nombre), "wb") as f:
                f.write(contenido)
            nombres.append(nombre)

        for bits in (8, 24):
            ruta = os.path.join(dir, f"bits{bits}.wav")
            with wave.open(ruta, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(bits // 8)
                w.setframerate(8000)
                w.writeframes(bytes(bits // 8 * 10))
            nombres.append(f"bits{bits}.wav")
        with open(os.path.join(dir, "py_0.wav"), "rb") as f:
            entero = f.read()
        mal("cortado.wav", entero[:len(entero) - 7])
        mal("sin_fmt.wav", b"RIFF" + struct.pack("<I", 12) + b"WAVE" + b"data" + struct.pack("<I", 0))
        mal("texto.wav", b"esto no es un wav\n")
        with open(os.path.join(dir, "indice.txt"), "w") as f:
            f.write("\n".join(nombres) + "\n")

        binario = os.path.join(dir, "a")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/audio_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_audio_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario, dir], cwd=RAIZ, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_audio_python: FALLA, el programa terminó con", r.returncode)
            return 1

        generados, vistos, recortadas = 0, set(), 0
        for linea in r.stdout.splitlines():
            p = linea.split(" ")
            if p[0] == "GEN":
                k, tipo, modo, tasa = (int(x) for x in p[1:5])
                f, a, dur, at, de, so, li = (float(x) for x in p[5:12])
                semilla = int(p[12])
                canales, quiero = esperado(tipo, modo, tasa, f, a, dur, at, de, so, li, semilla)
                quiero16 = [a_16(v) for v in quiero]
                recortadas += sum(1 for v in quiero if abs(v) > 1.0)
                with wave.open(os.path.join(dir, f"scar_{k}.wav"), "rb") as w:
                    cab = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
                    leido = list(struct.unpack(f"<{w.getnframes() * w.getnchannels()}h",
                                               w.readframes(w.getnframes())))
                n += 2
                generados += 1
                if cab != (canales, 2, tasa, len(quiero) // canales):
                    malas.append(f"scar_{k}.wav: cabecera {cab}, se esperaba {(canales, 2, tasa, len(quiero) // canales)}")
                elif leido != quiero16:
                    dist = [i for i, (x, y) in enumerate(zip(leido, quiero16)) if x != y]
                    malas.append(f"scar_{k}.wav (tipo {tipo}, modo {modo}): {len(dist)} muestras distintas; "
                                 f"la primera, {dist[0]}: SCAR {leido[dist[0]]}, Python {quiero16[dist[0]]}")
            elif p[0] == "LEE":
                nombre, canales, tasa, cuadros = p[1], int(p[2]), int(p[3]), int(p[4])
                muestras = [int(x) for x in p[5].split(",")] if len(p) > 5 and p[5] else []
                vistos.add(nombre)
                n += 1
                if nombre not in leibles:
                    malas.append(f"{nombre}: tenía que dar Err y se leyó")
                elif (canales, tasa, muestras) != leibles[nombre]:
                    malas.append(f"{nombre}: SCAR {canales} canales, {tasa} Hz, {len(muestras)} muestras: distinto")
            elif p[0] == "ERR":
                vistos.add(p[1])
                n += 1
                if p[1] in leibles or p[1] == "gen":
                    malas.append("inesperado: " + linea)
        faltan = set(nombres) - vistos
        if faltan:
            malas.append(f"no se probaron: {sorted(faltan)}")
    if malas or generados < 30 or recortadas == 0:
        for m in malas[:15]:
            print("  ", m)
        print(f"test_audio_python: FALLA, {len(malas)} diferencias ({generados} generados, {recortadas} recortadas)")
        return 1
    print(f"OK: audio igual a Python en {n} comparaciones (30 WAV generados por SCAR, muestra por muestra, "
          f"{recortadas} recortadas; WAV de wave leídos igual; 8 y 24 bits, cortado, sin fmt y no-WAV dan Err)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
