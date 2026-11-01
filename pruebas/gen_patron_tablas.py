"""Genera las tablas de Unicode de lib/patron.scar a partir de Python.

    python3 pruebas/gen_patron_tablas.py

Reescribe lo que hay entre las dos marcas "# ---- TABLAS" y "# ---- FIN DE LAS TABLAS"
de lib/patron.scar:
  - _txt_alnum: los rangos de caracteres para los que str.isalnum() es verdadero
    (es lo que usa `re` para \\w, junto con el guion bajo);
  - _txt_decimal: los rangos de str.isdecimal() (lo que usa `re` para \\d).
Cada tabla es una lista de pares (desde, hasta) escrita como diferencias en hexadecimal
separadas por espacios; la lib la decodifica al compilar un patrón que la necesita.
La lib compilada no necesita Python.
"""

import os
import unicodedata

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVO = os.path.join(RAIZ, "lib", "patron.scar")
INI = "# ---- TABLAS (generadas por pruebas/gen_patron_tablas.py: no se editan a mano) ----"
FIN = "# ---- FIN DE LAS TABLAS ----"


def rangos(f):
    r = []
    ini = None
    for c in range(0x110000):
        if f(chr(c)):
            if ini is None:
                ini = c
        elif ini is not None:
            r.append((ini, c - 1))
            ini = None
    if ini is not None:
        r.append((ini, 0x10FFFF))
    return r


def texto(rs):
    nums = []
    ant = 0
    for lo, hi in rs:
        nums.append(lo - ant)
        nums.append(hi - lo)
        ant = hi
    # la primera diferencia es contra 0; las demás contra el hi anterior: coincide con
    # el acumulado que hace _decodificar (suma corrida de todos los números)
    # (lo - ant) se cuenta desde hi; (hi - lo) desde lo: es la suma corrida
    return " ".join(format(n, "x") for n in nums)


def funcion(nombre, rs):
    t = texto(rs)
    trozos = [t[i:i + 100] for i in range(0, len(t), 100)]
    lineas = [f"fn {nombre}() -> str {{", '    let mut s = ""']
    for tr in trozos:
        lineas.append(f'    s = s + "{tr}"')
    lineas.append("    return s")
    lineas.append("}")
    return "\n".join(lineas)


def main():
    cuerpo = [INI, f"# Unicode {unicodedata.unidata_version} ({len(rangos(str.isalnum))} rangos de \\w, "
                   f"{len(rangos(str.isdecimal))} de \\d)", ""]
    cuerpo.append(funcion("_txt_alnum", rangos(str.isalnum)))
    cuerpo.append("")
    cuerpo.append(funcion("_txt_decimal", rangos(str.isdecimal)))
    cuerpo.append(FIN)
    s = open(ARCHIVO, encoding="utf-8").read()
    a = s.index(INI)
    b = s.index(FIN) + len(FIN)
    s = s[:a] + "\n".join(cuerpo) + s[b:]
    open(ARCHIVO, "w", encoding="utf-8").write(s)
    print("tablas escritas en", ARCHIVO)


main()
