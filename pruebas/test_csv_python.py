"""lib/csv contra el módulo csv de Python.

    python3 pruebas/test_csv_python.py

Python arma tablas al azar (campos con el separador, comillas, saltos de línea
\\n y \\r, tildes, emojis, campos vacíos, filas sin celdas y de distinto largo) y
las escribe con csv.writer (con coma, punto y coma, tabulador y barra). Además
inventa textos sucios con comillas sueltas, comillas que se cierran antes de
tiempo, saltos de línea de los tres tipos y finales sin terminar. Todo eso lo
lee pruebas/csv_python.scar con lib/csv, que escribe las filas que leyó y el CSV
que sale de escribir la tabla; acá se compara exacto con csv.reader y con
csv.writer.
"""

import csv
import io
import os
import random
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LETRA = {",": "C", ";": "S", "\t": "T", "|": "P"}
ALFABETO = list("abcxyz019 _-/") + ["á", "ñ", "ü", "€", "😀", '"', "\n", "\r", "\r\n", ",", ";", "\t", "|", "é"]


def campo(rng, maximo=7):
    return "".join(rng.choice(ALFABETO) for _ in range(rng.randint(0, maximo)))


def hexa(s):
    return s.encode("utf-8").hex()


def leer(texto, d):
    return list(csv.reader(io.StringIO(texto, newline=""), delimiter=d))


def escribir(filas, d):
    o = io.StringIO(newline="")
    csv.writer(o, delimiter=d).writerows(filas)
    return o.getvalue()


def esperado(texto, d):
    filas = leer(texto, d)
    out = [f"N {len(filas)}"]
    for f in filas:
        out.append("R" + "".join(" " + hexa(c) for c in f))
    out.append("W " + hexa(escribir(filas, d)))
    return out


def main():
    rng = random.Random(16)
    casos = []
    for _ in range(300):
        d = rng.choice(list(LETRA))
        filas = [[campo(rng) for _ in range(rng.choice([0, 1, 1, 2, 3, 5]))] for _ in range(rng.randint(0, 6))]
        casos.append((d, escribir(filas, d)))
    for _ in range(500):
        d = rng.choice(list(LETRA))
        casos.append((d, "".join(rng.choice(['"', '"', d, "\n", "\r", "\r\n", "a", "b", " ", "ñ"]) for _ in range(rng.randint(0, 14)))))
    for texto in ['', '\n', '\r\n', 'a', 'a,b', 'a,b\n', 'a,b\r\n1,2', '"a,b",c', '"a""b"', '"abc"def,x', 'a"b,c', '"sin cerrar',
                  '"sin cerrar\nmas', ',,', ',', '\n\n', 'a\n\nb', 'a\rb\rc', '"x"\r\n"y"\r\n', ' "a"', '"a" ,b', '""', '"",""', 'é,😀\n']:
        casos.append((",", texto))

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.txt"), "w", encoding="utf-8", newline="\n") as f:
            for d, t in casos:
                f.write(LETRA[d] + " " + hexa(t) + "\n")
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/csv_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_csv_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout[-2000:] + r.stderr)
            print("test_csv_python: FALLA, el programa terminó con", r.returncode)
            return 1

    esp = []
    for d, t in casos:
        esp += esperado(t, d)
    salida = r.stdout.splitlines()
    malas = []
    if len(salida) != len(esp):
        malas.append(f"se esperaban {len(esp)} líneas y salieron {len(salida)}")
    for k, (a, e) in enumerate(zip(salida, esp)):
        if a.rstrip() != e.rstrip():
            malas.append(f"línea {k}: salió {a[:140]!r}, esperado {e[:140]!r}")
            if len(malas) > 10:
                break
    if malas:
        print("\n".join(malas))
        print(f"test_csv_python: FALLA ({len(malas)}+ diferencias)")
        return 1
    print(f"test_csv_python: OK ({len(casos)} textos, {sum(1 for l in esp if l.startswith('R'))} filas, "
          "lectura y escritura iguales a csv.reader y csv.writer)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
