"""lib/juego (reloj, entrada, hojas, animación, mapa, choques, cámara) contra una referencia en Python.

    python3 pruebas/test_juego_python.py            (SCAR_SEMILLA=n para otra)

Python inventa los casos y los escribe en casos.json; pruebas/juego_python.scar los corre con lib/juego y
escribe un resultado por línea (lib/juego usa lib/gui, que enlaza con SDL2: sin SDL2 instalado la prueba
se omite). La referencia de Python calcula lo mismo de otra manera:

  - reloj: la cuenta paso a paso, más una ley (sin tope, los pasos dados son floor(ms * hz / 1000));
  - animación: la lista de cuadros de una pasada (ida y vuelta incluida) indexada con k % largo;
  - choques: se mueve de a UN píxel, y en cada píxel se prueba la caja contra TODAS las baldosas
    sólidas (lib/juego, en cambio, salta de baldosa en baldosa y se pega a la pared);
  - mapa en texto, cámara y entrada: otra escritura de las mismas reglas;
  - hojas y dibujo del mapa: píxel por píxel con la mezcla por alfa de lib/lienzo, mirando TODAS las
    baldosas (lib/juego solo mira las que se ven), y la hoja leída también por un PNG guardado y vuelto a leer;
  - una autocomprobación: si se estropea un resultado, el comparador lo tiene que notar.
"""

import json
import math
import os
import random
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def c_div(a, b):
    """División entera hacia el cero (la de C y de SCAR)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def c_mod(a, b):
    return a - b * c_div(a, b)


def signed32(u):
    return u - (1 << 32) if u >= (1 << 31) else u


# ---------------------------------------------------------------------------------------------
# Referencias
# ---------------------------------------------------------------------------------------------

def ref_reloj(hz, maximo, dts):
    acum = 0
    pasos = []
    for dt in dts:
        dt = min(1000, max(0, dt))
        acum += dt * hz
        n = acum // 1000
        if n > maximo:
            n = maximo
            acum %= 1000
        else:
            acum -= n * 1000
        pasos.append(n)
    return ",".join(map(str, pasos)) + " " + str(acum)


def ref_horas(hz, ts):
    acum = 0
    out = []
    ultimo = None
    for t in ts:
        if ultimo is None:
            out.append(0)
        else:
            dt = t - ultimo
            if dt < 0:
                dt += 1 << 31
            dt = min(1000, max(0, dt))
            acum += dt * hz
            n = acum // 1000
            if n > 5:
                n = 5
                acum %= 1000
            else:
                acum -= n * 1000
            out.append(n)
        ultimo = t
    return ",".join(map(str, out))


def ref_anim(primero, cantidad, ms, modo, ts):
    if modo == 2 and cantidad > 1:
        seq = list(range(cantidad)) + list(range(cantidad - 2, 0, -1))
    else:
        seq = list(range(cantidad))
    cuadros, term = [], []
    for t in ts:
        if t <= 0 or cantidad == 1:
            f = 0
        else:
            k = t // ms
            f = min(k, cantidad - 1) if modo == 0 else seq[k % len(seq)]
        cuadros.append(primero + f)
        term.append(1 if (modo == 0 and t >= cantidad * ms) else 0)
    dur = 2 * (cantidad - 1) * ms if (modo == 2 and cantidad > 1) else cantidad * ms
    return ",".join(map(str, cuadros)) + " " + ",".join(map(str, term)) + " " + str(dur)


def ref_texto(tam, s):
    lineas = s.replace("\r", "").split("\n")
    if lineas and lineas[-1] == "":
        lineas.pop()
    filas = max(1, len(lineas))
    cols = max([1] + [len(x) for x in lineas])
    celdas = [0] * (cols * filas)
    for f, x in enumerate(lineas):
        for c, ch in enumerate(x):
            if ch == "#":
                v = 1
            elif ch in "123456789":
                v = int(ch)
            elif ch in "abcdefghi":
                v = -1 - "abcdefghi".index(ch)
            else:
                v = 0
            celdas[f * cols + c] = v
    return f"{cols} {filas} " + ",".join(map(str, celdas))


class Mapa:
    def __init__(self, cols, filas, tam, celdas, fuera):
        self.cols, self.filas, self.tam, self.celdas, self.fuera = cols, filas, tam, celdas, fuera

    def pisa(self, x, y, w, h):
        t = self.tam
        if self.fuera > 0 and (x < 0 or y < 0 or x + w > self.cols * t or y + h > self.filas * t):
            return True
        for f in range(self.filas):
            for c in range(self.cols):
                if self.celdas[f * self.cols + c] > 0:
                    if x < (c + 1) * t and c * t < x + w and y < (f + 1) * t and f * t < y + h:
                        return True
        return False


def ref_cuerpo(m, x, y, w, h, movs):
    rx = ry = 0.0
    out = []
    for dx8, dy8 in movs:
        vx = vy = 1.0
        suelo = techo = False
        pared = 0
        rx += dx8 / 8.0
        n = math.floor(rx + 0.5)
        rx -= n
        paso = 1 if n > 0 else -1
        for _ in range(abs(n)):
            if m.pisa(x + paso, y, w, h):
                rx = 0.0
                vx = 0.0
                pared = paso
                break
            x += paso
        ry += dy8 / 8.0
        n = math.floor(ry + 0.5)
        ry -= n
        paso = 1 if n > 0 else -1
        for _ in range(abs(n)):
            if m.pisa(x, y + paso, w, h):
                ry = 0.0
                vy = 0.0
                if paso > 0:
                    suelo = True
                else:
                    techo = True
                break
            y += paso
        out.append(f"{x} {y} {math.floor(rx * 8.0 + 0.5)} {math.floor(ry * 8.0 + 0.5)} "
                   f"{int(suelo)}{int(techo)} {pared} {int(vx == 0.0)}{int(vy == 0.0)} "
                   f"{int(m.pisa(x, y, w, h))}{int(m.pisa(x, y + 1, w, h))}")
    return out


def dentro(v, vista, mundo):
    if mundo <= vista:
        return -((vista - mundo) // 2)
    return max(0, min(v, mundo - vista))


def hacia(actual, meta, num, den):
    d = meta - actual
    if d == 0:
        return actual
    paso = c_div(d * num, den)
    if paso == 0:
        paso = 1 if d > 0 else -1
    if (d > 0 and paso > d) or (d < 0 and paso < d):
        paso = d
    return actual + paso


def ref_camara(ancho, alto, mw, mh, ops):
    x = y = 0
    out = []
    for op in ops:
        tipo, a, b = op[0], op[1], op[2]
        if tipo == "mirar":
            x, y = dentro(a, ancho, mw), dentro(b, alto, mh)
        elif tipo == "centrar":
            x, y = dentro(a - ancho // 2, ancho, mw), dentro(b - alto // 2, alto, mh)
        else:
            num, den = op[3], op[4]
            x = hacia(x, dentro(a - ancho // 2, ancho, mw), num, den)
            y = hacia(y, dentro(b - alto // 2, alto, mh), num, den)
        bw = 1 + c_mod(a + b, 37) + 37
        bh = 1 + c_mod(a * 3 + b, 29) + 29
        vis = a < x + ancho and x < a + bw and b < y + alto and y < b + bh
        out.append(f"{x} {y} {a - x} {b - y} {a + x} {b + y} {int(vis)}")
    return out


def ref_entrada(codigos, pasos, consulta):
    ahora = {c: False for c in codigos}
    antes = dict(ahora)
    out = []
    for p in pasos:
        antes = dict(ahora)
        for cod, v in p:
            if cod in ahora:
                ahora[cod] = bool(v)
        s = ""
        for cod in consulta:
            a = ahora.get(cod, False)
            b = antes.get(cod, False)
            s += f"{int(a)}{int(a and not b)}{int(b and not a)} "
        menos, mas = consulta[0], consulta[1]
        s += str(int(ahora.get(mas, False)) - int(ahora.get(menos, False)))
        out.append(s)
    return out


def mezclar(fondo, c):
    """El "over" de lib/lienzo.mezclar, con enteros de 32 bits sin signo."""
    fondo &= 0xFFFFFFFF
    c &= 0xFFFFFFFF
    sa = c >> 24
    if sa == 255:
        return c
    if sa == 0:
        return fondo
    da = fondo >> 24
    resto = da * (255 - sa)
    oa = sa * 255 + resto

    def canal(s):
        return ((c >> s & 255) * sa * 255 + (fondo >> s & 255) * resto + oa // 2) // oa

    return ((oa + 127) // 255 << 24) | (canal(16) << 16) | (canal(8) << 8) | canal(0)


def suma(px):
    h = 0
    for p in px:
        h = (h * 31 + (p & 0xFFFFFFFF)) % 2147483647
    return h


def ref_hoja(img, iw, ih, cw, ch, dest, dw, dh, ops):
    cols, filas = iw // cw, ih // ch
    d = [p & 0xFFFFFFFF for p in dest]
    for espejo, i, x, y in ops:
        if i < 0 or i >= cols * filas:
            continue
        fx, fy = (i % cols) * cw, (i // cols) * ch
        for oy in range(ch):
            for ox in range(cw):
                sx = fx + cw - 1 - ox if espejo else fx + ox
                px, py = x + ox, y + oy
                if 0 <= px < dw and 0 <= py < dh:
                    d[py * dw + px] = mezclar(d[py * dw + px], img[(fy + oy) * iw + sx])
    return f"{cols * filas} {suma(d)} {suma(d)}"


def ref_dibujo(m, img, iw, ih, cw, ch, vw, vh, cx, cy):
    camx = dentro(cx, vw, m.cols * m.tam)
    camy = dentro(cy, vh, m.filas * m.tam)
    d = [0xFF0A141E] * (vw * vh)
    cols, filas = iw // cw, ih // ch
    for f in range(m.filas):
        for c in range(m.cols):
            v = m.celdas[f * m.cols + c]
            if v == 0:
                continue
            k = v - 1 if v > 0 else -v - 1
            if k < 0 or k >= cols * filas:
                continue
            fx, fy = (k % cols) * cw, (k // cols) * ch
            for oy in range(ch):
                for ox in range(cw):
                    px, py = c * m.tam - camx + ox, f * m.tam - camy + oy
                    if 0 <= px < vw and 0 <= py < vh:
                        d[py * vw + px] = mezclar(d[py * vw + px], img[(fy + oy) * iw + fx + ox])
    return f"{camx} {camy} {suma(d)}"


# ---------------------------------------------------------------------------------------------
# Casos al azar
# ---------------------------------------------------------------------------------------------

def color_azar(rng):
    a = rng.choice([0, 255, 255, 255, rng.randrange(256)])
    return signed32((a << 24) | (rng.randrange(256) << 16) | (rng.randrange(256) << 8) | rng.randrange(256))


def imagen_azar(rng, w, h):
    return [color_azar(rng) for _ in range(w * h)]


def mapa_azar(rng):
    tam = rng.choice([1, 2, 4, 8, 16])
    cols, filas = rng.randrange(2, 15), rng.randrange(2, 11)
    celdas = [rng.choice([0, 0, 0, 0, 0, 1, 1, 2, 3, -1, -2]) for _ in range(cols * filas)]
    return {"tam": tam, "cols": cols, "filas": filas, "celdas": celdas, "fuera": rng.choice([0, 1, 1])}


def casos_al_azar(rng):
    casos = {"relojes": [], "horas": [], "anims": [], "textos": [], "mapas": [], "camaras": [], "entradas": [],
             "hojas": [], "dibujos": []}
    esp = {}

    for k in range(40):
        hz = rng.choice([1, 10, 30, 60, 60, 120, 144, 1000])
        maximo = rng.choice([1, 3, 5, 5, 8])
        dts = [rng.choice([0, 1, 8, 16, 17, 33, 100, 500, 1000, 5000, -5, rng.randrange(0, 70)]) for _ in range(rng.randrange(1, 40))]
        casos["relojes"].append({"hz": hz, "maximo": maximo, "dts": dts})
        esp[("R", k)] = ref_reloj(hz, maximo, dts)
    # ley: sin tope, los pasos dados son floor(ms * hz / 1000) (con ms y hz que no llegan al tope)
    for k in range(40, 60):
        hz = rng.choice([30, 60, 75, 144])
        dts = [rng.randrange(0, 1000 // hz * 5 + 1) for _ in range(rng.randrange(5, 60))]
        casos["relojes"].append({"hz": hz, "maximo": 1000, "dts": dts})
        esp[("R", k)] = ref_reloj(hz, 1000, dts)
        dados = sum(int(x) for x in esp[("R", k)].split(" ")[0].split(","))
        assert dados == sum(dts) * hz // 1000, "la ley del reloj no la cumple ni la referencia"
    for k in range(25):
        hz = rng.choice([30, 60, 120])
        t = rng.choice([0, 1000, 2147483647 - 40, 2147483647 - 3])
        ts = []
        for _ in range(rng.randrange(2, 30)):
            ts.append(t)
            t = (t + rng.choice([0, 5, 16, 17, 40, 300, 2000])) % (1 << 31)
        casos["horas"].append({"hz": hz, "t": ts})
        esp[("P", k)] = ref_horas(hz, ts)

    for k in range(60):
        cantidad = rng.choice([1, 2, 3, 4, 6, 8])
        primero, ms, modo = rng.randrange(0, 20), rng.choice([1, 16, 100, 125]), rng.randrange(3)
        ts = [rng.choice([-5, 0, 1, ms - 1, ms, ms * cantidad - 1, ms * cantidad, ms * 3 * cantidad + 7, rng.randrange(0, 5000)])
              for _ in range(30)]
        casos["anims"].append({"primero": primero, "cantidad": cantidad, "ms": ms, "modo": modo, "ts": ts})
        esp[("A", k)] = ref_anim(primero, cantidad, ms, modo, ts)

    letras = "...........#####123456789abcdefghi  xz"
    fijos = ["", "\n", "#", "#\n", "#.\n#", "\n\n#", "##\n#\n###\n", "#\r\n..\r\n", "a1\n\nb", ".\n.\n."]
    for k in range(40):
        if k < len(fijos):
            s = fijos[k]
        else:
            s = "\n".join("".join(rng.choice(letras) for _ in range(rng.randrange(0, 12))) for _ in range(rng.randrange(1, 8)))
            if rng.random() < 0.5:
                s += "\n"
        tam = rng.choice([4, 8, 16])
        casos["textos"].append({"tam": tam, "s": s})
        esp[("T", k)] = ref_texto(tam, s)

    for k in range(40):
        mp = mapa_azar(rng)
        m = Mapa(mp["cols"], mp["filas"], mp["tam"], mp["celdas"], mp["fuera"])
        W, H = m.cols * m.tam, m.filas * m.tam
        cuerpos = []
        q = 0
        while len(cuerpos) < 3:
            w, h = rng.randrange(1, m.tam * 2 + 2), rng.randrange(1, m.tam * 2 + 2)
            if m.fuera:
                x, y = rng.randrange(0, W), rng.randrange(0, H)
            else:
                x, y = rng.randrange(-2 * m.tam, W + 2 * m.tam), rng.randrange(-2 * m.tam, H + 2 * m.tam)
            if m.pisa(x, y, w, h):
                q += 1
                if q > 200:
                    break
                continue
            grande = rng.random() < 0.3
            tope = 400 if grande else 20
            movs = [[rng.choice([0, rng.randrange(-tope, tope + 1), rng.randrange(-4, 5)]),
                     rng.choice([0, rng.randrange(-tope, tope + 1), rng.randrange(-4, 5)])] for _ in range(30)]
            cuerpos.append({"x": x, "y": y, "w": w, "h": h, "movs": movs})
        mp["cuerpos"] = cuerpos
        casos["mapas"].append(mp)
        for qi, cu in enumerate(cuerpos):
            for j, linea in enumerate(ref_cuerpo(m, cu["x"], cu["y"], cu["w"], cu["h"], cu["movs"])):
                esp[("M", k, qi, j)] = linea

    for k in range(40):
        ancho, alto = rng.randrange(8, 200), rng.randrange(8, 120)
        mw, mh = rng.choice([ancho, ancho + rng.randrange(1, 400), max(1, ancho - rng.randrange(0, 6))]), \
            rng.choice([alto, alto + rng.randrange(1, 300), max(1, alto - rng.randrange(0, 6))])
        ops = []
        for _ in range(40):
            t = rng.choice(["mirar", "centrar", "suavizar", "suavizar"])
            a, b = rng.randrange(-100, mw + 100), rng.randrange(-100, mh + 100)
            if t == "suavizar":
                den = rng.choice([1, 2, 4, 8, 16])
                ops.append([t, a, b, rng.randrange(0, 2 * den + 1), den])
            else:
                ops.append([t, a, b])
        casos["camaras"].append({"ancho": ancho, "alto": alto, "mw": mw, "mh": mh, "ops": ops})
        for j, linea in enumerate(ref_camara(ancho, alto, mw, mh, ops)):
            esp[("C", k, j)] = linea

    for k in range(30):
        codigos = rng.sample([4, 7, 22, 26, 40, 41, 44, 79, 80, 81, 82], rng.randrange(2, 7))
        consulta = [rng.choice(codigos), rng.choice(codigos)] + [rng.choice(codigos + [3, 99]) for _ in range(3)]
        pasos = [[[rng.choice(codigos + [5, 100]), rng.randrange(2)] for _ in range(rng.randrange(0, 4))] for _ in range(40)]
        casos["entradas"].append({"codigos": codigos, "consulta": consulta, "pasos": pasos})
        for j, linea in enumerate(ref_entrada(codigos, pasos, consulta)):
            esp[("E", k, j)] = linea

    for k in range(25):
        cw, ch = rng.randrange(1, 9), rng.randrange(1, 9)
        cols, filas = rng.randrange(1, 5), rng.randrange(1, 4)
        iw, ih = cw * cols + rng.randrange(0, 3), ch * filas + rng.randrange(0, 3)
        img = imagen_azar(rng, iw, ih)
        dw, dh = rng.randrange(4, 40), rng.randrange(4, 40)
        dest = imagen_azar(rng, dw, dh)
        ops = [[rng.randrange(2), rng.randrange(-2, cols * filas + 2), rng.randrange(-8, dw + 8), rng.randrange(-8, dh + 8)]
               for _ in range(12)]
        casos["hojas"].append({"cw": cw, "ch": ch, "img": {"w": iw, "h": ih, "px": img},
                               "dest": {"w": dw, "h": dh, "px": dest}, "ops": ops})
        esp[("H", k)] = ref_hoja(img, iw, ih, cw, ch, dest, dw, dh, ops)

    for k in range(25):
        mp = mapa_azar(rng)
        tam = mp["tam"]
        cw = ch = rng.choice([tam, tam, max(1, tam - 1)])
        cols, filas = rng.randrange(1, 4), rng.randrange(1, 4)
        img = imagen_azar(rng, cw * cols, ch * filas)
        vw, vh = rng.randrange(4, 60), rng.randrange(4, 50)
        cx = rng.randrange(-20, mp["cols"] * tam + 20)
        cy = rng.randrange(-20, mp["filas"] * tam + 20)
        mp.update({"cw": cw, "ch": ch, "img": {"w": cw * cols, "h": ch * filas, "px": img}, "vw": vw, "vh": vh, "cx": cx, "cy": cy})
        casos["dibujos"].append(mp)
        m = Mapa(mp["cols"], mp["filas"], tam, mp["celdas"], mp["fuera"])
        esp[("D", k)] = ref_dibujo(m, img, cw * cols, ch * filas, cw, ch, vw, vh, cx, cy)
    return casos, esp


def leer(salida):
    got = {}
    for linea in salida.splitlines():
        p = linea.split(" ")
        if p[0] in ("R", "P", "A", "T", "H", "D"):
            got[(p[0], int(p[1]))] = " ".join(p[2:])
        elif p[0] == "M":
            got[("M", int(p[1]), int(p[2]), int(p[3]))] = " ".join(p[4:])
        elif p[0] in ("C", "E"):
            got[(p[0], int(p[1]), int(p[2]))] = " ".join(p[3:])
    return got


def comparar(esp, got):
    errores = []
    for k in sorted(set(esp) | set(got)):
        if esp.get(k) != got.get(k):
            errores.append(f"{k}: lib={got.get(k)!r} python={esp.get(k)!r}")
    return errores


def main():
    rng = random.Random(int(os.environ.get("SCAR_SEMILLA", "24")))
    casos, esp = casos_al_azar(rng)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w") as f:
            json.dump(casos, f)
        binario = os.path.join(tmp, "b")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/juego_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            if "scarsdl" in (b.stdout + b.stderr):
                print("OK: lib/juego se omite (no hay SDL2 para enlazar lib/gui)")
                return 0
            print(b.stdout + b.stderr)
            print("test_juego_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or "ERROR" in r.stdout:
        print(r.stdout[-2000:] + r.stderr[-2000:])
        print("test_juego_python: FALLA, el programa terminó con", r.returncode)
        return 1
    got = leer(r.stdout)
    errores = comparar(esp, got)
    if errores:
        print("\n".join(errores[:12]))
        print(f"test_juego_python: FALLA ({len(errores)} diferencias de {len(esp)})")
        return 1
    for etiqueta in "RPATMCEHD":
        malo = dict(got)
        clave = next(k for k in malo if k[0] == etiqueta)
        malo[clave] = malo[clave] + "9"
        if not comparar(esp, malo):
            print(f"test_juego_python: FALLA, la autocomprobación no notó un resultado estropeado ({etiqueta})")
            return 1
    print(f"OK: lib/juego contra la referencia de Python: {len(esp)} resultados "
          f"({len(casos['mapas'])} mapas con choques, {len(casos['camaras'])} cámaras, {len(casos['relojes'])} relojes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
