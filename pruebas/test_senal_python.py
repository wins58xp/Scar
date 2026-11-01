"""lib/senal contra numpy.fft y scipy.signal.

    python3 pruebas/test_senal_python.py

Python inventa señales y filtros al azar y los escribe en casos.json.
pruebas/senal_python.scar calcula con lib/senal y Python lo repite con numpy y scipy:

  - FFT, FFT real, inversas, magnitud, fase y frecuencias (numpy.fft), con tamaños
    potencia de dos y también primos y compuestos (algoritmo de Bluestein);
  - convolución directa y por FFT, y correlación cruzada (numpy.convolve/correlate);
  - ventanas hann, hamming, blackman, bartlett, boxcar y kaiser, simétricas y
    periódicas (scipy.signal.get_window);
  - filtros FIR por ventanas (scipy.signal.firwin) de los cuatro tipos;
  - filtros Butterworth pasabajo, pasaalto, pasabanda y rechazabanda (scipy.signal.butter):
    los coeficientes b y a, y con los coeficientes de la propia lib: lfilter, lfilter_zi,
    filtfilt y la respuesta en frecuencia (freqz);
  - el periodograma (scipy.signal.periodogram) con varias ventanas;
  - el remuestreo por Fourier (scipy.signal.resample) y el polifásico
    (scipy.signal.resample_poly).

Además se comprueba que el propio comparador detecta una diferencia chica (así un
resultado equivocado no pasa de largo por una tolerancia floja).
"""

import json
import math
import os
import random
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def casos_al_azar(rng):
    def senal(n, escala=1.0):
        return [rng.gauss(0, 1) * escala for _ in range(n)]

    c = dict(fft=[], conv=[], ventanas=[], fir=[], butter=[], espectro=[], remuestreo=[], poly=[])
    for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 16, 17, 31, 32, 64, 97, 100, 127, 128, 210, 256, 257, 500, 1000]:
        c["fft"].append(dict(x=senal(n)))
    c["fft"].append(dict(x=[rng.uniform(-1e6, 1e6) for _ in range(50)]))
    c["fft"].append(dict(x=[0.0] * 9))
    c["fft"].append(dict(x=[1.0] + [0.0] * 15))
    for _ in range(25):
        c["conv"].append(dict(a=senal(rng.randint(1, 60)), b=senal(rng.randint(1, 40))))
    for nombre in ["hann", "hamming", "blackman", "bartlett", "boxcar"]:
        for n in [1, 2, 3, 8, 9, 50, 51]:
            for sim in (True, False):
                c["ventanas"].append(dict(nombre=nombre, n=n, sim=str(sim).lower(), beta=rng.uniform(0.5, 12)))
    for _ in range(20):
        fs = rng.choice([1.0, 2.0, 8000.0, 44100.0])
        tipo = rng.choice(["pasabajo", "pasaalto", "pasabanda", "rechazabanda"])
        n = rng.randrange(5, 120, 2)  # impar
        if tipo in ("pasabajo", "pasabanda") and rng.random() < 0.4:
            n += 1
        if tipo in ("pasabajo", "pasaalto"):
            cortes = [rng.uniform(0.05, 0.9) * fs / 2]
        else:
            a, b = sorted(rng.uniform(0.05, 0.9) for _ in range(2))
            if b - a < 0.05:
                b = min(0.95, a + 0.05)
            cortes = [a * fs / 2, b * fs / 2]
        c["fir"].append(dict(tipo=tipo, numtaps=n, fs=fs, cortes=cortes))
    for _ in range(40):
        fs = rng.choice([1.0, 2.0, 100.0, 8000.0])
        tipo = rng.choice(["pasabajo", "pasaalto", "pasabanda", "rechazabanda"])
        if tipo in ("pasabajo", "pasaalto"):
            orden = rng.randint(1, 6)
            cortes = [rng.uniform(0.05, 0.85) * fs / 2]
        else:
            orden = rng.randint(1, 3)
            a, b = sorted(rng.uniform(0.1, 0.85) for _ in range(2))
            if b - a < 0.1:
                b = min(0.95, a + 0.1)
            cortes = [a * fs / 2, b * fs / 2]
        n = rng.randint(80, 300)
        c["butter"].append(dict(tipo=tipo, orden=orden, fs=fs, cortes=cortes, x=senal(n),
                                hz=[rng.uniform(0, fs / 2) for _ in range(6)] + [0.0, fs / 2]))
    for _ in range(25):
        c["espectro"].append(dict(x=senal(rng.randint(8, 300)), fs=rng.choice([1.0, 100.0, 1000.0]),
                                  ventana=rng.choice(["boxcar", "hann", "hamming", "blackman", "bartlett"])))
    for _ in range(30):
        n = rng.randint(2, 200)
        c["remuestreo"].append(dict(x=senal(n), num=rng.randint(1, 300)))
    for _ in range(25):
        c["poly"].append(dict(x=senal(rng.randint(1, 150)), up=rng.randint(1, 6), down=rng.randint(1, 6)))
    return c


def leer(stdout):
    r = {}
    for linea in stdout.splitlines():
        p = linea.split()
        if len(p) >= 2 and p[0].isupper() and p[1].isdigit():
            r[(p[0], int(p[1]))] = [float(v) for v in p[2:]]
    return r


class Comparador:
    def __init__(self):
        self.errores = []
        self.comparaciones = 0

    def vec(self, etiqueta, k, got, esp, tol):
        """|got - esp| <= tol en cada punto (tol absoluta ya escalada)."""
        self.comparaciones += 1
        if got is None:
            self.errores.append(f"{etiqueta} {k}: no salió")
            return
        if len(got) != len(esp):
            self.errores.append(f"{etiqueta} {k}: {len(got)} valores y se esperaban {len(esp)}")
            return
        peor = 0.0
        for a, b in zip(got, esp):
            if math.isnan(a) or math.isnan(b):
                if not (math.isnan(a) and math.isnan(b)):
                    peor = float("inf")
                continue
            peor = max(peor, abs(a - b))
        if peor > tol:
            self.errores.append(f"{etiqueta} {k}: diferencia máxima {peor:.3g} (tolerancia {tol:.3g})")


def main():
    try:
        import numpy as np
        import scipy.signal as sg
    except ImportError:
        print("OK: test_senal_python se omite (sin numpy y scipy en esta máquina)")
        return 0
    rng = random.Random(19)
    casos = casos_al_azar(rng)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(casos, f)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/senal_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_senal_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_senal_python: FALLA, el programa terminó con", r.returncode)
            return 1
    got = leer(r.stdout)
    cmp = Comparador()
    V = cmp.vec

    for k, c in enumerate(casos["fft"]):
        x = np.array(c["x"])
        n = len(x)
        esc = max(1.0, float(np.sum(np.abs(x)))) * 1e-12 * max(1.0, math.log2(n + 1))
        F = np.fft.fft(x)
        V("FFTRE", k, got.get(("FFTRE", k)), F.real, esc)
        V("FFTIM", k, got.get(("FFTIM", k)), F.imag, esc)
        R = np.fft.rfft(x)
        V("RFFTRE", k, got.get(("RFFTRE", k)), R.real, esc)
        V("RFFTIM", k, got.get(("RFFTIM", k)), R.imag, esc)
        tx = 1e-12 * max(1.0, float(np.max(np.abs(x)))) * math.log2(n + 1)
        V("IFFT", k, got.get(("IFFT", k)), x, tx)
        V("IRFFT", k, got.get(("IRFFT", k)), x, tx)
        V("MAG", k, got.get(("MAG", k)), np.abs(F), esc)
        mag = got.get(("MAG", k)) or []
        fase = got.get(("FASE", k))
        if fase is not None and len(fase) == n:
            # la fase solo importa donde hay magnitud (con ruido de 1e-15 es cualquiera)
            gran = np.abs(F) > 1e-9 * max(1.0, float(np.max(np.abs(F))))
            d = np.angle(F)
            dif = np.abs(np.array(fase) - d)
            dif = np.minimum(dif, 2 * math.pi - dif)
            if np.any(dif[gran] > 1e-9):
                cmp.errores.append(f"FASE {k}: diferencia {float(np.max(dif[gran])):.3g}")
        else:
            cmp.errores.append(f"FASE {k}: tamaño equivocado")
        V("FREQ", k, got.get(("FREQ", k)), np.fft.fftfreq(n, 0.25), 1e-12)
        V("FREQR", k, got.get(("FREQR", k)), np.fft.rfftfreq(n, 0.25), 1e-12)

    for k, c in enumerate(casos["conv"]):
        a, b = np.array(c["a"]), np.array(c["b"])
        esc = 1e-12 * max(1.0, float(np.sum(np.abs(a)) * np.max(np.abs(b))))
        V("CONV", k, got.get(("CONV", k)), np.convolve(a, b), esc)
        V("CONVFFT", k, got.get(("CONVFFT", k)), np.convolve(a, b), esc * 10)
        V("CORR", k, got.get(("CORR", k)), np.correlate(a, b, "full"), esc)

    for k, c in enumerate(casos["ventanas"]):
        sim = c["sim"] == "true"
        V("WIN", k, got.get(("WIN", k)), sg.get_window(c["nombre"], c["n"], fftbins=not sim), 1e-13)
        V("KAISER", k, got.get(("KAISER", k)), sg.get_window(("kaiser", c["beta"]), c["n"], fftbins=not sim), 1e-12)

    tipos = dict(pasabajo="lowpass", pasaalto="highpass", pasabanda="bandpass", rechazabanda="bandstop")
    for k, c in enumerate(casos["fir"]):
        cortes = c["cortes"] if len(c["cortes"]) > 1 else c["cortes"][0]
        pass_zero = dict(pasabajo=True, pasaalto=False, pasabanda=False, rechazabanda=True)[c["tipo"]]
        esp = sg.firwin(c["numtaps"], cortes, pass_zero=pass_zero, window="hamming", fs=c["fs"])
        V("FIR", k, got.get(("FIR", k)), esp, 1e-12)

    for k, c in enumerate(casos["butter"]):
        wn = c["cortes"] if len(c["cortes"]) > 1 else c["cortes"][0]
        b, a = sg.butter(c["orden"], wn, btype=tipos[c["tipo"]], fs=c["fs"])
        gb, ga = got.get(("B", k)), got.get(("A", k))
        V("B", k, gb, b, 1e-9 * max(1.0, float(np.max(np.abs(b)))))
        V("A", k, ga, a, 1e-9 * max(1.0, float(np.max(np.abs(a)))))
        if gb is None or ga is None or len(gb) != len(b) or len(ga) != len(a):
            continue
        # con los coeficientes de la lib, el resto se compara en seco
        gb, ga = np.array(gb), np.array(ga)
        x = np.array(c["x"])
        esc = 1e-11 * max(1.0, float(np.max(np.abs(x))))
        V("LFILTER", k, got.get(("LFILTER", k)), sg.lfilter(gb, ga, x), esc)
        V("ZI", k, got.get(("ZI", k)), sg.lfilter_zi(gb, ga), 1e-9)
        V("FILTFILT", k, got.get(("FILTFILT", k)), sg.filtfilt(gb, ga, x), esc * 10)
        _, h = sg.freqz(gb, ga, worN=c["hz"], fs=c["fs"])
        V("GAIN", k, got.get(("GAIN", k)), np.abs(h), 1e-9)
        # y que sean de verdad un filtro del tipo pedido: ganancia ≈ 1 en la banda que pasa
        g = got.get(("GAIN", k))
        if g is not None and c["tipo"] == "pasabajo" and len(g) == 8:
            if abs(g[6] - 1.0) > 1e-9:
                cmp.errores.append(f"butter {k}: ganancia en 0 Hz es {g[6]!r}")
        if g is not None and c["tipo"] == "pasaalto" and len(g) == 8:
            if abs(g[7] - 1.0) > 1e-6:
                cmp.errores.append(f"butter {k}: ganancia en Nyquist es {g[7]!r}")

    for k, c in enumerate(casos["espectro"]):
        x = np.array(c["x"])
        f, p = sg.periodogram(x, c["fs"], window=c["ventana"], detrend="constant", scaling="density")
        V("PERF", k, got.get(("PERF", k)), f, 1e-9 * c["fs"])
        V("PERP", k, got.get(("PERP", k)), p, 1e-11 * max(float(np.max(p)), 1e-300))

    for k, c in enumerate(casos["remuestreo"]):
        x = np.array(c["x"])
        esp = sg.resample(x, c["num"])
        V("RES", k, got.get(("RES", k)), esp, 1e-10 * max(1.0, float(np.max(np.abs(x)))))

    for k, c in enumerate(casos["poly"]):
        x = np.array(c["x"])
        esp = sg.resample_poly(x, c["up"], c["down"])
        V("POLY", k, got.get(("POLY", k)), esp, 1e-11 * max(1.0, float(np.max(np.abs(x)))))

    # el comparador tiene que notar un error chico
    prueba = Comparador()
    prueba.vec("MUT", 0, [1.0, 2.0, 3.0 + 1e-6], [1.0, 2.0, 3.0], 1e-9)
    prueba.vec("MUT", 1, [1.0, 2.0], [1.0, 2.0, 3.0], 1e-9)
    if len(prueba.errores) != 2:
        print("test_senal_python: FALLA, el comparador no detecta diferencias chicas")
        return 1

    if cmp.errores:
        print("\n".join(cmp.errores[:15]))
        print(f"test_senal_python: FALLA ({len(cmp.errores)} diferencias)")
        return 1
    n = sum(len(casos[k]) for k in casos)
    print(f"OK: lib/senal contra numpy y scipy: {n} casos, {cmp.comparaciones} comparaciones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
