"""lib/imagen (PNG, con el DEFLATE de lib/zlib) contra Pillow.

    python3 pruebas/test_png_pillow.py

1. Deja en una carpeta temporal PNG hechos con Pillow: RGB de varios
   tamaños con compress_level 0 (bloques guardados), 1, 6 y 9 y con
   optimize (Huffman dinámico y otros filtros), RGBA, gris, gris con alfa,
   paleta, paleta con transparencia (tRNS), RGB y gris con un color
   transparente; y los que tienen que dar Err: 1 bit, 16 bits, entrelazado
   (Adam7), un CRC roto, un archivo cortado, datos que no inflan y algo que
   no es PNG.
2. Compila pruebas/png_pillow.scar, que lee cada uno con imagen.leer_png y
   escribe sus píxeles, y guarda dos escenas (una opaca, otra con alfa) con
   imagen.guardar_png.
3. Compara cada píxel leído con Image.open(...).convert("RGBA"), y abre con
   Pillow lo que guardó SCAR: la escena opaca tiene que salir RGB y la otra
   RGBA, con todos los píxeles iguales.

Sin Pillow se omite.
"""

import os
import random
import struct
import subprocess
import sys
import tempfile
import zlib

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def argb(px):
    r, g, b, a = px
    return (a << 24) | (r << 16) | (g << 8) | b


def chunks(datos):
    pos, out = 8, []
    while pos < len(datos):
        largo = struct.unpack(">I", datos[pos:pos + 4])[0]
        out.append([datos[pos + 4:pos + 8], bytearray(datos[pos + 8:pos + 8 + largo])])
        pos += 12 + largo
    return out


def armar(cs):
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    for tipo, dat in cs:
        out += struct.pack(">I", len(dat)) + tipo + bytes(dat)
        out += struct.pack(">I", zlib.crc32(tipo + bytes(dat)))
    return bytes(out)


def main():
    try:
        from PIL import Image
    except ImportError:
        print("OK: test_png_pillow se omite (sin Pillow en esta máquina)")
        return 0

    azar = random.Random(2026)
    esperado = {}
    malas = []
    n = 0
    with tempfile.TemporaryDirectory() as dir:
        nombres = []

        def guardar(nombre, im, **opc):
            ruta = os.path.join(dir, nombre)
            im.save(ruta, **opc)
            nombres.append(nombre)
            leida = Image.open(ruta).convert("RGBA")
            w, h = leida.size
            esperado[nombre] = (w, h, [argb(leida.getpixel((x, y))) for y in range(h) for x in range(w)])

        def al_azar(modo, w, h, valores=256):
            im = Image.new(modo, (w, h))
            canales = len(im.getbands())
            im.putdata([tuple(azar.randrange(valores) for _ in range(canales)) if canales > 1
                        else azar.randrange(valores) for _ in range(w * h)])
            return im

        def suave(w, h):
            im = Image.new("RGB", (w, h))
            im.putdata([((x * 7) % 256, (y * 11) % 256, ((x + y) * 3) % 256) for y in range(h) for x in range(w)])
            return im

        guardar("rgb_1x1.png", al_azar("RGB", 1, 1))
        guardar("rgb_5x3_n0.png", al_azar("RGB", 5, 3), compress_level=0)
        guardar("rgb_33x17_n1.png", al_azar("RGB", 33, 17), compress_level=1)
        guardar("rgb_33x17_n9.png", al_azar("RGB", 33, 17), compress_level=9)
        guardar("suave_64x40_n6.png", suave(64, 40), compress_level=6)
        guardar("suave_64x40_opt.png", suave(64, 40), optimize=True)
        guardar("rgba_20x9.png", al_azar("RGBA", 20, 9))
        guardar("gris_17x5.png", al_azar("L", 17, 5))
        guardar("gris_alfa_9x9.png", al_azar("LA", 9, 9))
        p = al_azar("P", 12, 7, valores=200)
        p.putpalette([azar.randrange(256) for _ in range(768)])
        guardar("paleta_12x7.png", p)
        guardar("paleta_trns_12x7.png", p, transparency=bytes(azar.randrange(256) for _ in range(200)))
        rgb_t = al_azar("RGB", 8, 8, valores=3)
        guardar("rgb_trns_8x8.png", rgb_t, transparency=(1, 2, 0))
        guardar("gris_trns_8x8.png", al_azar("L", 8, 8, valores=4), transparency=2)

        def mal(nombre, contenido):
            with open(os.path.join(dir, nombre), "wb") as f:
                f.write(contenido)
            nombres.append(nombre)
            esperado[nombre] = "ERR"

        def con_pillow_bytes(im, **opc):
            ruta = os.path.join(dir, "_tmp.png")
            im.save(ruta, **opc)
            with open(ruta, "rb") as f:
                return f.read()

        mal("bits1_8x8.png", con_pillow_bytes(al_azar("1", 8, 8, valores=2)))
        mal("bits16_4x4.png", con_pillow_bytes(al_azar("I;16", 4, 4)))
        base = con_pillow_bytes(al_azar("RGB", 6, 6))
        cs = chunks(base)
        cs[0][1][12] = 1                    # IHDR: entrelazado
        mal("entrelazado.png", armar(cs))
        roto = bytearray(base)
        roto[-20] ^= 0xFF                   # un byte del IDAT, sin arreglar el CRC
        mal("crc_roto.png", bytes(roto))
        mal("cortado.png", base[:len(base) - 30])
        cs = chunks(base)
        cs[1][1] = bytearray(b"\x78\x9c\xff\xff\xff\xff")
        mal("no_infla.png", armar([c for c in cs if c[0] != b"IDAT"][:1] + [cs[1]] + cs[2:]))
        mal("texto.png", b"esto no es un png, aunque se llame asi\n")

        with open(os.path.join(dir, "indice.txt"), "w") as f:
            f.write("\n".join(nombres) + "\n")

        binario = os.path.join(dir, "png")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/png_pillow.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_png_pillow: FALLA, no compila")
            return 1
        r = subprocess.run([binario, dir], cwd=RAIZ, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_png_pillow: FALLA, el programa terminó con", r.returncode)
            return 1

        vistos = set()
        for linea in r.stdout.splitlines():
            p = linea.split(" ")
            if p[0] == "LEE":
                nombre, w, h, buf = p[1], int(p[2]), int(p[3]), p[4]
                vistos.add(nombre)
                n += 1
                obtenido = [int(buf[i:i + 8], 16) for i in range(0, len(buf), 8)]
                if esperado.get(nombre) == "ERR":
                    malas.append(f"{nombre}: tenía que dar Err y se leyó")
                elif (w, h, obtenido) != esperado[nombre]:
                    ew, eh, ep = esperado[nombre]
                    distintos = [i for i, (a, b) in enumerate(zip(obtenido, ep)) if a != b]
                    detalle = (f"; el primero ({distintos[0] % w}, {distintos[0] // w}): SCAR {obtenido[distintos[0]]:08x}, "
                               f"Pillow {ep[distintos[0]]:08x}") if distintos else ""
                    malas.append(f"{nombre}: SCAR {w}x{h}, Pillow {ew}x{eh}, {len(distintos)} distintos{detalle}")
            elif p[0] == "ERR":
                vistos.add(p[1])
                n += 1
                if esperado.get(p[1]) != "ERR":
                    malas.append(f"{p[1]}: dio Err ({' '.join(p[2:])}) y tenía que leerse")
            elif p[0] == "ERRG":
                malas.append("no se pudo guardar: " + linea)
            elif p[0] == "ESCENA":
                nombre, w, h, buf = p[1], int(p[2]), int(p[3]), p[4]
                px = [int(buf[i:i + 8], 16) for i in range(0, len(buf), 8)]
                n += 1
                modo = "RGB" if all((v >> 24) & 255 == 255 for v in px) else "RGBA"
                try:
                    im = Image.open(os.path.join(dir, nombre))
                    im.load()
                except OSError as e:
                    malas.append(f"{nombre}: Pillow no lo puede abrir: {e}")
                    continue
                if im.size != (w, h) or im.mode != modo:
                    malas.append(f"{nombre}: Pillow lo abre como {im.mode} {im.size}, se esperaba {modo} {(w, h)}")
                    continue
                for i, v in enumerate(px):
                    quiero = ((v >> 16) & 255, (v >> 8) & 255, v & 255) + ((((v >> 24) & 255),) if modo == "RGBA" else ())
                    if im.getpixel((i % w, i // w)) != quiero:
                        malas.append(f"{nombre}: píxel ({i % w}, {i // w}): Pillow {im.getpixel((i % w, i // w))}, "
                                     f"SCAR {quiero}")
                        break
        faltan = set(nombres) - vistos
        if faltan:
            malas.append(f"no se probaron: {sorted(faltan)}")

    if malas:
        for m in malas[:15]:
            print("  ", m)
        print(f"test_png_pillow: FALLA, {len(malas)} diferencias")
        return 1
    print(f"OK: PNG igual a Pillow en {n} archivos (RGB, RGBA, gris, gris con alfa, paleta, tRNS; "
          f"compress_level 0/1/6/9 y optimize; 1 y 16 bits, Adam7, CRC roto, cortado, no-PNG dan Err; "
          f"lo que guarda SCAR, opaco y con alfa, lo abre Pillow igual)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
