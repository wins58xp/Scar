#!/usr/bin/env python3
"""Genera native/scarfuente.h: la fuente de texto de scarsdl.

SCAR dibuja texto con una fuente propia ya rasterizada, embebida en la
librería: no depende de SDL_ttf ni de una fuente instalada en la máquina que
corre el programa. Este script la arma una vez a partir de DejaVu Sans (libre;
licencia en el encabezado del .h generado) y el resultado se guarda en el repo.
Solo hace falta correrlo de nuevo para cambiar la fuente, los tamaños o los
caracteres.

Caracteres: ASCII imprimible (32..126), Latin-1 (160..255: á é í ó ú ñ ü ¿ ¡
º ª ° ...), el € y los de EXTRA (– — ‘ ’ “ ” • … ← ↑ → ↓ − ≈ ≤ ≥ Δ ▲ ▼ ✓ ✗).
Cualquier otro carácter se dibuja como '?'.

Tamaños: TAMANOS (en píxeles, alto de la letra). scar_sdl_texto() usa el más
cercano al pedido.

Formato: por tamaño, el alto de línea, la línea de base y una tabla de glifos
(código, avance, ancho, alto, desplazamiento x/y desde el borde de arriba de la
línea, posición en el arreglo de alfa). El alfa (cuánto tapa cada píxel, con
suavizado) se guarda en 4 bits por píxel, dos píxeles por byte.

Uso:  python3 pruebas/gen_fuente.py [ruta.ttf]           (scarfuente.h)
      python3 pruebas/gen_fuente.py --mono [ruta.ttf]    (scarfuente_mono.h, de ancho fijo)
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TTF = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
TAMANOS = (13, 16, 20, 28)
TTF_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
TAMANOS_MONO = (13, 16, 20)
# y unos pocos signos más para interfaces (guiones, comillas, puntos,
# flechas, menos, aproximado, mayor/menor o igual, marcas)
EXTRA = [0x20AC, 0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026,
         0x2190, 0x2191, 0x2192, 0x2193, 0x2212, 0x2248, 0x2264, 0x2265, 0x0394,
         0x25B2, 0x25BC, 0x2713, 0x2717]
CODIGOS = list(range(32, 127)) + list(range(160, 256)) + EXTRA

LICENCIA = """\
 * Glifos rasterizados de DejaVu Sans (https://dejavu-fonts.github.io/).
 * Fonts are (c) Bitstream (see below). DejaVu changes are in public domain.
 * Bitstream Vera Fonts Copyright (c) 2003 by Bitstream, Inc. All Rights
 * Reserved. Bitstream Vera is a trademark of Bitstream, Inc. Permission is
 * hereby granted, free of charge, to any person obtaining a copy of the fonts
 * accompanying this license ("Fonts") and associated documentation files (the
 * "Font Software"), to reproduce and distribute the Font Software, including
 * without limitation the rights to use, copy, merge, publish, distribute,
 * and/or sell copies of the Font Software, and to permit persons to whom the
 * Font Software is furnished to do so, subject to the following conditions:
 * The above copyright and trademark notices and this permission notice shall
 * be included in all copies of one or more of the Font Software typefaces.
 * (Texto completo de la licencia: https://dejavu-fonts.github.io/License.html)"""


def glifos(tam, ruta):
    f = ImageFont.truetype(ruta, tam)
    asc, desc = f.getmetrics()
    salida = []
    for cp in CODIGOS:
        ch = chr(cp)
        avance = int(round(f.getlength(ch)))
        x0, y0, x1, y1 = f.getbbox(ch)
        w, h = max(0, x1 - x0), max(0, y1 - y0)
        alfa = []
        if w and h:
            img = Image.new("L", (w, h), 0)
            ImageDraw.Draw(img).text((-x0, -y0), ch, font=f, fill=255)
            px = img.load()
            alfa = [(px[x, y] + 8) // 17 for y in range(h) for x in range(w)]  # 0..15
        salida.append((cp, avance, w, h, x0, y0, alfa))
    return asc, desc, salida


def tablas(tamanos, ruta, prefijo):
    """Las líneas de C con los glifos de cada tamaño, y la lista de ScarFuente."""
    lineas, fuentes = [], []
    for tam in tamanos:
        asc, desc, gs = glifos(tam, ruta)
        nib = []
        tabla = []
        for cp, av, w, h, dx, dy, alfa in gs:
            pos = len(nib)
            nib.extend(alfa)
            tabla.append(f"{{{cp},{av},{w},{h},{dx},{dy},{pos}}}")
        if len(nib) % 2:
            nib.append(0)
        datos = [nib[i] | (nib[i + 1] << 4) for i in range(0, len(nib), 2)]
        lineas.append(f"static const ScarGlifo {prefijo}glifos_{tam}[] = {{")
        for i in range(0, len(tabla), 8):
            lineas.append("    " + ",".join(tabla[i:i + 8]) + ",")
        lineas.append("};")
        lineas.append(f"static const uint8_t {prefijo}alfa_{tam}[] = {{")
        for i in range(0, len(datos), 24):
            lineas.append("    " + ",".join(str(b) for b in datos[i:i + 24]) + ",")
        lineas.append("};")
        lineas.append("")
        fuentes.append(f"{{{tam},{asc + desc},{asc},{prefijo}glifos_{tam},{prefijo}alfa_{tam}}}")
    return lineas, fuentes


def main():
    mono = "--mono" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if mono:
        # La fuente de ancho fijo para editores de código: native/scarfuente_mono.h. Va aparte para
        # no cambiar los glifos de scarfuente.h (que usa toda la librería gráfica).
        ruta = args[0] if args else TTF_MONO
        lic = LICENCIA.replace("DejaVu Sans", "DejaVu Sans Mono")
        lineas = ["/* native/scarfuente_mono.h -- GENERADO por pruebas/gen_fuente.py --mono; no editar a mano.",
                  " *", lic, " *", " * Los mismos glifos que scarfuente.h (mismo orden), de ancho fijo. Hay que incluir",
                  " * scarfuente.h antes que este archivo.", " */", ""]
        cuerpo, fuentes = tablas(TAMANOS_MONO, ruta, "scar_mono_")
        lineas += cuerpo
        lineas.append(f"#define SCAR_MONO_NTAMANOS {len(TAMANOS_MONO)}")
        lineas.append("static const ScarFuente scar_fuentes_mono[] = {" + ", ".join(fuentes) + "};")
        destino = os.path.join(RAIZ, "native", "scarfuente_mono.h")
        with open(destino, "w", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n")
        print(f"{destino}: {len(TAMANOS_MONO)} tamaños, {len(CODIGOS)} glifos cada uno")
        return
    ruta = args[0] if args else TTF
    lineas = ["/* native/scarfuente.h -- GENERADO por pruebas/gen_fuente.py; no editar a mano.",
              " *", LICENCIA, " */", "#include <stdint.h>", "",
              "typedef struct { uint16_t cp; uint8_t avance, w, h; int8_t dx, dy; uint32_t pos; } ScarGlifo;",
              "typedef struct { uint8_t tam, alto, base; const ScarGlifo *glifos; const uint8_t *alfa; } ScarFuente;",
              f"#define SCAR_FUENTE_NGLIFOS {len(CODIGOS)}", ""]
    cuerpo, fuentes = tablas(TAMANOS, ruta, "scar_")
    lineas += cuerpo
    lineas.append(f"#define SCAR_FUENTE_NTAMANOS {len(TAMANOS)}")
    lineas.append("static const ScarFuente scar_fuentes[] = {" + ", ".join(fuentes) + "};")
    destino = os.path.join(RAIZ, "native", "scarfuente.h")
    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print(f"{destino}: {len(TAMANOS)} tamaños, {len(CODIGOS)} glifos cada uno")


if __name__ == "__main__":
    main()
