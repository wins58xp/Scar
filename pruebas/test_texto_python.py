"""lib/texto contra Python.

    python3 pruebas/test_texto_python.py

Compila y corre pruebas/texto_python.scar, que arma textos al azar (con
tildes, ñ, ß, letras del latín extendido, emojis, chino y los espacios raros
de Unicode) y escribe cada entrada y cada resultado como códigos de carácter.
Acá se calcula lo mismo con los str de Python y se compara todo, exacto:
upper/lower, strip, split, find, rfind, count, replace, rjust/ljust/center,
splitlines (con "\\n" y "\\r\\n"), join, f"{x:.nf}" y f"{x:,.nf}" con números
al azar y casos borde (empates, -0.0, 5e-324, 1e300), f"{n:,}" y las clases
de carácter (isalpha/isdecimal en U+0000-U+017F, isspace en U+0001-U+32C7).
"""

import math
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def txt(c):
    """'=97.98' -> 'ab'"""
    assert c.startswith("="), c
    c = c[1:]
    return "".join(chr(int(x)) for x in c.split(".")) if c else ""


def lista(campos):
    n = int(campos[0])
    return [txt(c) for c in campos[1:1 + n]]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "t")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/texto_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_texto_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=RAIZ, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_texto_python: FALLA, el programa terminó con", r.returncode)
            return 1

    malas = []
    n = 0
    textos = {}

    def igual(etq, obtenido, esperado):
        nonlocal n
        n += 1
        if obtenido != esperado:
            malas.append(f"{etq}: SCAR {obtenido!r}, Python {esperado!r}")

    for linea in r.stdout.splitlines():
        p = linea.split(" ")
        etq, k = p[0], int(p[1])
        if etq == "T":
            textos[k] = txt(p[2])
            continue
        s = textos.get(k)
        e = f"{etq} {k}"
        if etq == "MAY":
            igual(e, txt(p[2]), s.upper())
        elif etq == "MIN":
            igual(e, txt(p[2]), s.lower())
        elif etq == "STRIP":
            igual(e, txt(p[2]), s.strip())
        elif etq == "LSTRIP":
            igual(e, txt(p[2]), s.lstrip())
        elif etq == "RSTRIP":
            igual(e, txt(p[2]), s.rstrip())
        elif etq == "INV":
            igual(e, txt(p[2]), s[::-1])
        elif etq == "SPLITWS":
            igual(e, lista(p[2:]), s.split())
        elif etq == "SUB":
            a, b = int(p[2]), int(p[3])
            igual(e, txt(p[4]), s[a:b])
        elif etq == "FIND":
            igual(e, int(p[3]), s.find(txt(p[2])))
        elif etq == "FINDFROM":
            igual(e, int(p[4]), s.find(txt(p[2]), int(p[3])))
        elif etq == "RFIND":
            igual(e, int(p[3]), s.rfind(txt(p[2])))
        elif etq == "COUNT":
            igual(e, int(p[3]), s.count(txt(p[2])))
        elif etq == "REPL":
            igual(e, txt(p[3]), s.replace(txt(p[2]), "<ñ>"))
        elif etq == "SPLIT":
            igual(e, lista(p[3:]), s.split(txt(p[2])))
        elif etq in ("RJUST", "LJUST", "CENTER"):
            w, c = int(p[2]), txt(p[3])
            f = {"RJUST": s.rjust, "LJUST": s.ljust, "CENTER": s.center}[etq]
            igual(e, txt(p[4]), f(w, c))
        elif etq == "REP":
            igual(e, txt(p[3]), s * int(p[2]))
        elif etq == "JOIN":
            igual(e, txt(p[2]), "--".join(s.split()))
        elif etq == "LIN":
            fuente = txt(p[2])
            igual(e, lista(p[3:]), fuente.splitlines())
        elif etq == "DEC":
            x, nd = float(p[2]), int(p[3])
            igual(f"{e} ({p[2]}, {nd})", p[4], f"{x:.{nd}f}")
        elif etq == "DECM":
            x, nd = float(p[2]), int(p[3])
            igual(f"{e} ({p[2]}, {nd})", p[4], f"{x:,.{nd}f}")
        elif etq == "MILES":
            igual(e, p[3], f"{int(p[2]):,}")
        elif etq == "AF64":
            fuente = txt(p[2])
            try:
                esperado = float(fuente.replace("_", "#"))   # Python acepta 1_000; SCAR no
            except ValueError:
                esperado = None
            if p[3] == "ERR" or esperado is None:
                igual(f"{e} a_f64({fuente!r})", p[3] == "ERR", esperado is None)
            else:
                obtenido = float(p[3])
                if math.isnan(esperado):
                    igual(f"{e} a_f64({fuente!r})", math.isnan(obtenido), True)
                else:
                    # el camino exacto: entero de hasta 15 cifras por 10^k, con |k| <= 22
                    mant = fuente.strip().lower().split("e")[0].lstrip("+-")
                    exp = int(fuente.lower().split("e")[1]) if "e" in fuente.lower() else 0
                    entera, _, frac = mant.partition(".")
                    cifras_txt = (entera + frac).lstrip("0")
                    k = exp - len(frac) + (len(cifras_txt) - len(cifras_txt.rstrip("0")))
                    cifras = len(cifras_txt.rstrip("0"))
                    if cifras <= 15 and abs(k) <= 22 and abs(esperado) > 1e-300:
                        igual(f"{e} a_f64({fuente!r}) exacto", (obtenido, math.copysign(1, obtenido)),
                              (esperado, math.copysign(1, esperado)))
                    else:
                        n += 1
                        if not (obtenido == esperado or abs(obtenido - esperado) <= 4.5e-16 * abs(esperado)):
                            malas.append(f"{e} a_f64({fuente!r}): SCAR {obtenido!r}, Python {esperado!r}")
        elif etq == "CLS":
            ch = chr(k)
            letra, digito, espacio = int(p[2]), int(p[3]), int(p[4])
            if k < 384:
                igual(f"{e} isalpha", letra, int(ch.isalpha()))
                igual(f"{e} isdecimal", digito, int(ch.isdecimal()))
            igual(f"{e} isspace", espacio, int(ch.isspace()))
        else:
            malas.append(f"etiqueta desconocida: {linea[:80]}")

    # isspace: también que no falte ninguno (CLS solo trae los espacios de 400 en adelante)
    vistos = {int(l.split(" ")[1]) for l in r.stdout.splitlines()
              if l.startswith("CLS ") and l.split(" ")[4] == "1"}
    esperados = {c for c in range(1, 13000) if chr(c).isspace()}
    igual("isspace (todos)", sorted(vistos), sorted(esperados))

    if malas or n < 5000:
        for m in malas[:20]:
            print("  ", m)
        print(f"test_texto_python: FALLA, {len(malas)} diferencias en {n} comparaciones")
        return 1
    print(f"OK: texto igual a Python en {n} comparaciones (upper/lower, strip, split, find, replace, "
          f"justificar, splitlines, join, f\"{{x:.nf}}\" exacto con empates y bordes, miles, a_f64 contra float(), "
          f"clases de carácter)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
