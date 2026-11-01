"""lib/zlib contra el zlib de Python (que es el zlib de C).

    python3 pruebas/test_zlib_python.py

Los dos sentidos:
- lo que comprime lib/zlib (con LZ77 y Huffman fijo, y sin comprimir) lo
  descomprime zlib.decompress y da los datos originales;
- lo que comprime zlib, con los niveles 0, 1, 6 y 9 y las estrategias
  Z_FIXED, Z_HUFFMAN_ONLY, Z_RLE y Z_FILTERED (bloques guardados, de Huffman
  fijo y de Huffman dinámico), lo descomprime lib/zlib igual;
- crc32 y adler32 dan lo mismo que zlib.crc32 y zlib.adler32;
- un flujo dañado (sin el final, con el Adler-32 cambiado, con el encabezado
  roto, con diccionario, con un bloque de tipo 3) da Err, no basura.

Datos: vacío, un byte, 100 KB de ceros, 70 KB al azar (más de un bloque
guardado), texto que se repite, filas de una imagen, todos los bytes en ciclo.
"""

import os
import random
import subprocess
import sys
import tempfile
import zlib

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def con_signo(n):
    return n - (1 << 32) if n >= 1 << 31 else n


def main():
    azar = random.Random(1950)
    texto = ("En un lugar de la Mancha, de cuyo nombre no quiero acordarme, no ha mucho tiempo que "
             "vivía un hidalgo de los de lanza en astillero, adarga antigua, rocín flaco y galgo "
             "corredor. Año, ñandú, pingüino. ").encode("utf-8")
    datos = {
        "vacio": b"",
        "uno": b"\x07",
        "ceros": bytes(100000),
        "azar": bytes(azar.randrange(256) for _ in range(70000)),
        "texto": texto * 120,
        "filas": b"".join(bytes([0] + [(x * 3 + y) % 256 for x in range(300)]) for y in range(60)),
        "ciclo": bytes(range(256)) * 40,
        "poco_azar": bytes(azar.choice(b"abcab") for _ in range(20000)),
    }
    variantes = {"n0": dict(level=0), "n1": dict(level=1), "n6": dict(level=6), "n9": dict(level=9),
                 "fijo": dict(level=6, strategy=zlib.Z_FIXED),
                 "huffman": dict(level=6, strategy=zlib.Z_HUFFMAN_ONLY),
                 "rle": dict(level=6, strategy=zlib.Z_RLE),
                 "filtrado": dict(level=9, strategy=zlib.Z_FILTERED)}

    malas = []
    n = 0
    with tempfile.TemporaryDirectory() as dir:
        nombres = []

        def escribir(nombre, contenido):
            with open(os.path.join(dir, nombre), "wb") as f:
                f.write(contenido)
            nombres.append(nombre)

        for clave, d in datos.items():
            escribir(f"orig_{clave}.bin", d)
            for var, opciones in variantes.items():
                c = zlib.compressobj(**opciones)
                escribir(f"z_{clave}_{var}.z", c.compress(d) + c.flush())
        base = zlib.compress(datos["texto"], 9)
        malos = {
            "malo_sin_final.z": base[:-4],
            "malo_cortado.z": base[:len(base) // 2],
            "malo_adler.z": base[:-1] + bytes([base[-1] ^ 1]),
            "malo_encabezado.z": bytes([0x78, 0x9D]) + base[2:],
            "malo_no_deflate.z": bytes([0x79, 0x9C - 0x1F]) + base[2:],
            "malo_diccionario.z": bytes([0x78, 0xBB, 0, 0, 0, 1]) + base[2:],
            "malo_tipo3.z": bytes([0x78, 0x9C, 0x07, 0, 0, 0, 0, 1]),
            "malo_vacio.z": b"",
        }
        for nombre, contenido in malos.items():
            escribir(nombre, contenido)
        with open(os.path.join(dir, "indice.txt"), "w") as f:
            f.write("\n".join(nombres) + "\n")

        binario = os.path.join(dir, "z")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/zlib_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_zlib_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario, dir], cwd=RAIZ, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_zlib_python: FALLA, el programa terminó con", r.returncode)
            return 1

        vistos = set()
        tam_scar = tam_zlib = 0
        for linea in r.stdout.splitlines():
            p = linea.split(" ")
            if p[0] == "SUMAS":
                d = datos[p[1][5:-4]]
                n += 2
                if int(p[2]) != con_signo(zlib.crc32(d)):
                    malas.append(f"crc32 de {p[1]}: SCAR {p[2]}, zlib {con_signo(zlib.crc32(d))}")
                if int(p[3]) != con_signo(zlib.adler32(d)):
                    malas.append(f"adler32 de {p[1]}: SCAR {p[3]}, zlib {con_signo(zlib.adler32(d))}")
            elif p[0] == "COMPRIME":
                clave = p[1][5:-4]
                vistos.add(p[1])
                for pref in ("scar_", "scarg_"):
                    n += 1
                    try:
                        with open(os.path.join(dir, f"{pref}{clave}.z"), "rb") as f:
                            comprimido = f.read()
                        if zlib.decompress(comprimido) != datos[clave]:
                            malas.append(f"{pref}{clave}.z: zlib lo descomprime distinto")
                    except (OSError, zlib.error) as e:
                        malas.append(f"{pref}{clave}.z: zlib no lo puede descomprimir: {e}")
                tam_scar += int(p[3])
                tam_zlib += len(zlib.compress(datos[clave], 6))
            elif p[0] == "DESC":
                nombre = p[1]
                vistos.add(nombre)
                n += 1
                if nombre.startswith("malo_"):
                    malas.append(f"{nombre}: tenía que dar Err")
                    continue
                clave = nombre[2:].rsplit("_", 1)[0]
                with open(os.path.join(dir, f"des_{nombre}.bin"), "rb") as f:
                    if f.read() != datos[clave]:
                        malas.append(f"{nombre}: SCAR lo descomprime distinto")
            elif p[0] == "ERR":
                vistos.add(p[1])
                n += 1
                if not p[1].startswith("malo_"):
                    malas.append("inesperado: " + linea)
        faltan = set(nombres) - vistos
        if faltan:
            malas.append(f"no se probaron: {sorted(faltan)[:5]}")

    if malas:
        for m in malas[:15]:
            print("  ", m)
        print(f"test_zlib_python: FALLA, {len(malas)} diferencias en {n} comparaciones")
        return 1
    print(f"OK: zlib igual al de C en {n} comparaciones (lo de SCAR lo abre zlib, lo de zlib en 8 niveles y "
          f"estrategias lo abre SCAR, crc32/adler32, 8 flujos dañados dan Err); comprimido: "
          f"{tam_scar} bytes contra {tam_zlib} de zlib -6")
    return 0


if __name__ == "__main__":
    sys.exit(main())
