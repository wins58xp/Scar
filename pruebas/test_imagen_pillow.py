"""lib/imagen (BMP) contra Pillow.

    python3 pruebas/test_imagen_pillow.py

1. Deja en una carpeta temporal BMP de 24 y 32 bits hechos con Pillow (con
   anchos que obligan a rellenar las filas) y otros armados a mano: uno de
   arriba hacia abajo (alto negativo), uno de 32 bits con máscaras en otro
   orden y alfa (BITMAPV4), uno BITMAPV5 con alfa, y los que tienen que dar
   Err: 16 bits, paleta, RLE, un archivo cortado y uno que no es BMP.
2. Compila pruebas/imagen_pillow.scar, que lee cada uno con imagen.leer_bmp y
   escribe sus píxeles, y que dibuja una escena con lienzo (con alfa) y la
   guarda con guardar_bmp y guardar_bmp32.
3. Compara cada píxel leído con lo que Pillow (o el armado a mano) dice que
   hay, y abre con Pillow los dos BMP que guardó SCAR: el de 24 bits tiene que
   dar los colores de la escena y el de 32, también el alfa.

Sin Pillow se omite.
"""

import os
import random
import struct
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def argb(r, g, b, a=255):
    return (a << 24) | (r << 16) | (g << 8) | b


def bmp_a_mano(w, h, pixeles, bpp, comp, masks=None, dib=40, de_arriba=False):
    """pixeles: lista de filas (de arriba hacia abajo) de (r, g, b, a)."""
    filas = []
    for fila in pixeles:
        datos = bytearray()
        for r, g, b, a in fila:
            if bpp == 24:
                datos += bytes((b, g, r))
            else:
                p = 0
                for valor, m in zip((r, g, b, a), masks):
                    if m:
                        corr = (m & -m).bit_length() - 1
                        p |= (valor << corr) & m
                datos += struct.pack("<I", p)
        datos += b"\0" * ((4 - len(datos) % 4) % 4)
        filas.append(bytes(datos))
    if not de_arriba:
        filas.reverse()
    datos = b"".join(filas)
    cab = struct.pack("<IiiHHIIiiII", dib, w, -h if de_arriba else h, 1, bpp, comp, len(datos), 2835, 2835, 0, 0)
    if dib > 40:
        extra = struct.pack("<IIII", *masks) + struct.pack("<I", 0x73524742) + b"\0" * 48
        if dib == 124:
            extra += struct.pack("<IIII", 4, 0, 0, 0)  # intent, perfil, tamaño, reservado
        cab += extra[:dib - 40]
    desde = 14 + len(cab)
    return b"BM" + struct.pack("<IHHI", desde + len(datos), 0, 0, desde) + cab + datos


def main():
    try:
        from PIL import Image
    except ImportError:
        print("OK: test_imagen_pillow se omite (sin Pillow en esta máquina)")
        return 0

    azar = random.Random(20261026)
    esperado = {}       # nombre -> (w, h, [argb...]) o "ERR"
    malas = []
    n = 0

    with tempfile.TemporaryDirectory() as dir:
        def con_pillow(nombre, modo, w, h):
            im = Image.new(modo, (w, h))
            px = [tuple(azar.randrange(256) for _ in modo) for _ in range(w * h)]
            im.putdata(px)
            im.save(os.path.join(dir, nombre))
            leida = Image.open(os.path.join(dir, nombre)).convert("RGBA")
            esperado[nombre] = (w, h, [argb(*leida.getpixel((x, y))) for y in range(h) for x in range(w)])

        con_pillow("rgb_1x1.bmp", "RGB", 1, 1)
        con_pillow("rgb_3x2.bmp", "RGB", 3, 2)
        con_pillow("rgb_5x7.bmp", "RGB", 5, 7)
        con_pillow("rgb_17x9.bmp", "RGB", 17, 9)
        con_pillow("rgba_6x4.bmp", "RGBA", 6, 4)   # Pillow lo guarda en 32 bits BI_RGB: se lee opaco

        def a_mano(nombre, w, h, bpp, comp, masks=None, dib=40, de_arriba=False, alfa=True):
            px = [[(azar.randrange(256), azar.randrange(256), azar.randrange(256),
                    azar.randrange(256) if alfa else 255) for _ in range(w)] for _ in range(h)]
            with open(os.path.join(dir, nombre), "wb") as f:
                f.write(bmp_a_mano(w, h, px, bpp, comp, masks, dib, de_arriba))
            esperado[nombre] = (w, h, [argb(r, g, b, a) for fila in px for (r, g, b, a) in fila])

        a_mano("abajo_arriba_7x3.bmp", 7, 3, 24, 0, de_arriba=True, alfa=False)
        # máscaras en el orden RGBA (no el BGRA de siempre), con alfa
        a_mano("mascaras_alfa_5x5.bmp", 5, 5, 32, 3,
               masks=(0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000), dib=108)
        a_mano("v5_alfa_3x3.bmp", 3, 3, 32, 3,
               masks=(0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000), dib=124)

        # los que tienen que dar Err
        with open(os.path.join(dir, "mascaras_565_4x4.bmp"), "wb") as f:
            cab = struct.pack("<IiiHHIIiiII", 40, 4, 4, 1, 16, 3, 32, 2835, 2835, 0, 0)
            cab += struct.pack("<III", 0xF800, 0x07E0, 0x001F)
            f.write(b"BM" + struct.pack("<IHHI", 14 + len(cab) + 32, 0, 0, 14 + len(cab)) + cab + b"\0" * 32)
        esperado["mascaras_565_4x4.bmp"] = "ERR"
        Image.new("P", (4, 4)).save(os.path.join(dir, "paleta_4x4.bmp"))
        esperado["paleta_4x4.bmp"] = "ERR"
        with open(os.path.join(dir, "rgb_17x9.bmp"), "rb") as f:
            entero = f.read()
        with open(os.path.join(dir, "cortado.bmp"), "wb") as f:
            f.write(entero[:len(entero) - 40])
        esperado["cortado.bmp"] = "ERR"
        with open(os.path.join(dir, "texto.bmp"), "w") as f:
            f.write("hola, esto no es una imagen\n")
        esperado["texto.bmp"] = "ERR"
        with open(os.path.join(dir, "rle_4x4.bmp"), "wb") as f:
            cab = struct.pack("<IiiHHIIiiII", 40, 4, 4, 1, 24, 1, 0, 2835, 2835, 0, 0)
            f.write(b"BM" + struct.pack("<IHHI", 14 + len(cab), 0, 0, 14 + len(cab)) + cab)
        esperado["rle_4x4.bmp"] = "ERR"

        binario = os.path.join(dir, "img")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/imagen_pillow.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_imagen_pillow: FALLA, no compila")
            return 1
        r = subprocess.run([binario, dir], cwd=RAIZ, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_imagen_pillow: FALLA, el programa terminó con", r.returncode)
            return 1

        vistos = set()
        escena = None
        for linea in r.stdout.splitlines():
            p = linea.split(" ")
            if p[0] == "LEE":
                nombre, w, h, buf = p[1], int(p[2]), int(p[3]), p[4]
                vistos.add(nombre)
                obtenido = [int(buf[i:i + 8], 16) for i in range(0, len(buf), 8)]
                n += 1
                if esperado.get(nombre) == "ERR":
                    malas.append(f"{nombre}: tenía que dar Err y se leyó")
                elif (w, h, obtenido) != esperado[nombre]:
                    ew, eh, ep = esperado[nombre]
                    distintos = sum(1 for a, b in zip(obtenido, ep) if a != b)
                    malas.append(f"{nombre}: SCAR {w}x{h}, esperado {ew}x{eh}, {distintos} píxeles distintos")
            elif p[0] == "ERR" and p[1].startswith("scar"):
                malas.append("no se pudo guardar: " + linea)
            elif p[0] == "ERR":
                vistos.add(p[1])
                n += 1
                if esperado.get(p[1]) != "ERR":
                    malas.append(f"{p[1]}: dio Err ({' '.join(p[2:])}) y tenía que leerse")
            elif p[0] == "ESCENA":
                w, h, buf = int(p[1]), int(p[2]), p[3]
                escena = (w, h, [int(buf[i:i + 8], 16) for i in range(0, len(buf), 8)])
        faltan = set(esperado) - vistos
        if faltan:
            malas.append(f"no se probaron: {sorted(faltan)}")
        if escena is None:
            malas.append("no se dibujó la escena")
        else:
            w, h, px = escena
            for nombre, modo in (("scar24.bmp", "RGB"), ("scar32.bmp", "RGBA")):
                n += 1
                try:
                    im = Image.open(os.path.join(dir, nombre))
                    if im.size != (w, h) or im.mode != modo:
                        malas.append(f"{nombre}: Pillow lo abre como {im.mode} {im.size}, "
                                     f"se esperaba {modo} {(w, h)}")
                        continue
                    datos = [im.getpixel((x, y)) for y in range(h) for x in range(w)]
                except OSError as e:
                    malas.append(f"{nombre}: Pillow no lo puede abrir: {e}")
                    continue
                for i, p in enumerate(px):
                    a, rr, g, bb = (p >> 24) & 255, (p >> 16) & 255, (p >> 8) & 255, p & 255
                    quiero = (rr, g, bb) if modo == "RGB" else (rr, g, bb, a)
                    if datos[i] != quiero:
                        malas.append(f"{nombre}: píxel ({i % w}, {i // w}): Pillow {datos[i]}, SCAR {quiero}")
                        break

    if malas:
        for m in malas[:15]:
            print("  ", m)
        print(f"test_imagen_pillow: FALLA, {len(malas)} diferencias")
        return 1
    print(f"OK: imagen igual a Pillow: {n} archivos (BMP de 24 y 32 bits de Pillow y armados a mano, "
          f"de arriba hacia abajo, con máscaras y alfa; 16 bits, paleta, RLE, cortado y no-BMP dan Err; "
          f"los de SCAR los abre Pillow igual)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
