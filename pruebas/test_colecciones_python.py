"""lib/colecciones contra Python.

    python3 pruebas/test_colecciones_python.py

Compila y corre pruebas/colecciones_python.scar, que hace miles de operaciones
al azar sobre Pila, Cola, Mapa, MapaEnt, Conjunto y ConjuntoEnt, y ordena
listas al azar (i32, i64, f64, str, y structs con ordenar_por). Acá se repite
cada operación con list, collections.deque, dict (que también guarda el orden
de inserción) y sorted, y se compara todo, exacto: lo que devuelve cada
operación, el contenido completo de los mapas en orden, las uniones,
intersecciones y diferencias en orden, y que ordenar_por sea estable.
"""

import collections
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


def opt_txt(c):
    return None if c == "N" else txt(c)


def opt_int(c):
    return None if c == "N" else int(c)


def booleano(c):
    assert c in ("true", "false"), c
    return c == "true"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/colecciones_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_colecciones_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=RAIZ, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stdout[-2000:] + r.stderr)
            print("test_colecciones_python: FALLA, el programa terminó con", r.returncode)
            return 1

    malas = []
    n = 0
    cuenta = collections.Counter()

    def igual(etq, obtenido, esperado):
        nonlocal n
        n += 1
        if obtenido != esperado:
            malas.append(f"{etq}: SCAR {obtenido!r}, Python {esperado!r}")

    pila = []
    cola = collections.deque()
    mapa = {}
    mapa_ent = {}
    mapa_f = {}
    conj = {"A": {}, "B": {}}
    conj_e = {"A": {}, "B": {}}
    entrada = {}
    fin = False

    for num, linea in enumerate(r.stdout.splitlines(), 1):
        p = linea.split()
        etq = p[0]
        cuenta[etq] += 1
        e = f"línea {num} {etq}"
        if etq == "PUSH":
            pila.append(int(p[1]))
        elif etq == "POP":
            igual(e, opt_int(p[1]), pila.pop() if pila else None)
        elif etq == "TOP":
            igual(e, (opt_int(p[1]), int(p[2]), booleano(p[3])),
                  (pila[-1] if pila else None, len(pila), not pila))
        elif etq == "ENQ":
            cola.append(txt(p[1]))
        elif etq == "DEQ":
            igual(e, opt_txt(p[1]), cola.popleft() if cola else None)
        elif etq == "FRONT":
            igual(e, (opt_txt(p[1]), int(p[2]), booleano(p[3])),
                  (cola[0] if cola else None, len(cola), not cola))
        elif etq == "MPUT":
            mapa[txt(p[1])] = int(p[2])
        elif etq == "MADD":
            k = txt(p[1])
            mapa[k] = mapa.get(k, 0) + int(p[2])
        elif etq == "MDEL":
            k = txt(p[1])
            igual(e, booleano(p[2]), k in mapa)
            mapa.pop(k, None)
        elif etq == "MGET":
            k = txt(p[1])
            igual(e, (opt_int(p[2]), booleano(p[3])), (mapa.get(k), k in mapa))
        elif etq == "MDUMP":
            items = [x.rsplit(":", 1) for x in p[2:]]
            igual(e, (int(p[1]), [(txt(k), int(v)) for k, v in items]), (len(mapa), list(mapa.items())))
        elif etq == "MKEYS":
            igual(e, (int(p[1]), [txt(k) for k in p[2:]]), (len(mapa), list(mapa)))
        elif etq == "EPUT":
            mapa_ent[int(p[1])] = txt(p[2])
        elif etq == "EDEL":
            k = int(p[1])
            igual(e, booleano(p[2]), k in mapa_ent)
            mapa_ent.pop(k, None)
        elif etq == "EGET":
            k = int(p[1])
            igual(e, (opt_txt(p[2]), booleano(p[3])), (mapa_ent.get(k), k in mapa_ent))
        elif etq == "EDUMP":
            items = [x.split(":", 1) for x in p[2:]]
            igual(e, (int(p[1]), [(int(k), txt(v)) for k, v in items]), (len(mapa_ent), list(mapa_ent.items())))
        elif etq == "FADD":
            k = int(p[1])
            mapa_f[k] = mapa_f.get(k, 0.0) + float(p[2])
        elif etq == "FDUMP":
            items = [x.split(":", 1) for x in p[2:]]
            igual(e, (int(p[1]), [(int(k), float(v)) for k, v in items]), (len(mapa_f), list(mapa_f.items())))
        elif etq == "SADD":
            conj[p[1]][txt(p[2])] = True
        elif etq == "SADDE":
            conj_e[p[1]][int(p[2])] = True
        elif etq == "SDEL":
            k = txt(p[2])
            igual(e, booleano(p[3]), k in conj[p[1]])
            conj[p[1]].pop(k, None)
            igual(e, booleano(p[4]), False)
        elif etq == "SDELE":
            k = int(p[2])
            igual(e, booleano(p[3]), k in conj_e[p[1]])
            conj_e[p[1]].pop(k, None)
            igual(e, booleano(p[4]), False)
        elif etq in ("SUNION", "SINTER", "SDIFF", "SUNIONE", "SINTERE", "SDIFFE"):
            a, b = (conj_e["A"], conj_e["B"]) if etq.endswith("E") else (conj["A"], conj["B"])
            if etq.startswith("SUNION"):
                esp = list(dict.fromkeys(list(a) + list(b)))
            elif etq.startswith("SINTER"):
                esp = [x for x in a if x in b]
            else:
                esp = [x for x in a if x not in b]
            conv = int if etq.endswith("E") else txt
            igual(e, (int(p[1]), [conv(x) for x in p[2:]]), (len(esp), esp))
        elif etq == "SFIN":
            conj = {"A": {}, "B": {}}
            conj_e = {"A": {}, "B": {}}
        elif etq == "ORD_IN":
            v = [int(x) for x in p[2:]]
            igual(e, (int(p[1]), v), (len(v), sorted(v)))
        elif etq in ("ORD", "DESC", "ORDF", "ORDL", "TXT", "EST"):
            entrada[etq] = p[2:] if int(p[1]) > 0 else []
        elif etq == "ORDR":
            v = [int(x) for x in entrada["ORD"]]
            igual(e, [int(x) for x in p[2:]], sorted(v))
        elif etq == "DESCR":
            v = [int(x) for x in entrada["DESC"]]
            igual(e, [int(x) for x in p[2:]], sorted(v, reverse=True))
        elif etq == "ORDFR":
            sal = p[2:] if int(p[1]) > 0 else []
            igual(e, sal, sorted(entrada["ORDF"], key=float))
        elif etq == "ORDLR":
            sal = p[2:] if int(p[1]) > 0 else []
            igual(e, [int(x) for x in sal], sorted(int(x) for x in entrada["ORDL"]))
        elif etq == "TXTR":
            sal = p[2:] if int(p[1]) > 0 else []
            igual(e, [opt_txt(x) for x in sal], sorted(txt(x) for x in entrada["TXT"]))
        elif etq == "TXTL":
            sal = p[2:] if int(p[1]) > 0 else []
            igual(e, [opt_txt(x) for x in sal], sorted((txt(x) for x in entrada["TXT"]), key=len))
        elif etq == "ESTR":
            claves = [int(x) for x in entrada["EST"]]
            esp = sorted(((k, i) for i, k in enumerate(claves)), key=lambda t: t[0])
            sal = p[2:] if int(p[1]) > 0 else []
            igual(e, [tuple(int(y) for y in x.split(":")) for x in sal], esp)
        elif etq == "FIN":
            fin = True
        else:
            malas.append(f"etiqueta desconocida: {linea[:80]}")

    if not fin:
        malas.append("la salida no llegó a FIN")
    if malas or n < 10000:
        for m in malas[:20]:
            print("  ", m)
        print(f"test_colecciones_python: FALLA, {len(malas)} diferencias en {n} comparaciones")
        return 1
    print(f"OK: colecciones igual a Python en {n} comparaciones ({cuenta['PUSH'] + cuenta['POP'] + cuenta['TOP']} "
          f"de pila contra list, {cuenta['ENQ'] + cuenta['DEQ'] + cuenta['FRONT']} de cola contra deque, "
          f"{sum(cuenta[k] for k in cuenta if k[0] in 'MEF')} de mapas contra dict con su orden, "
          f"{cuenta['SFIN']} rondas de conjuntos, "
          f"{sum(cuenta[k] for k in ('ORD_IN', 'ORDR', 'DESCR', 'ORDFR', 'ORDLR', 'TXTR', 'TXTL', 'ESTR'))} "
          f"listas ordenadas contra sorted, estable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
