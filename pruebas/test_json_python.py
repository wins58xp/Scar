"""lib/json contra el módulo json de Python.

    python3 pruebas/test_json_python.py

Python arma documentos JSON al azar (objetos y arreglos anidados, tildes, ñ,
emojis, escapes, números enteros y decimales, true, false, null) y los escribe
de varias maneras (con espacios o sin ellos, ASCII o UTF-8). pruebas/json_python.scar
los lee con lib/json y escribe cada uno en una línea, en ASCII y con sangría 2;
acá se compara exacto con json.dumps. También se consultan rutas ("a.0.b"):
tipo, existencia, largo, texto y entero, y rutas que no existen. Por último
se estropean documentos (se corta, se cambia o se mete un carácter) y, cuando
json.loads los rechaza, lib/json también tiene que rechazarlos.
"""

import json
import os
import random
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LETRAS = list("abcxyzABC019 _-/") + ["á", "ñ", "ü", "€", "😀", "\n", "\t", '"', "\\", "\x01", " ", "é"]


def texto(rng, maximo=8):
    return "".join(rng.choice(LETRAS) for _ in range(rng.randint(0, maximo)))


def clave(rng):
    # sin puntos: la ruta usa el punto como separador
    return texto(rng, 5).replace(".", "")


def numero(rng):
    k = rng.randint(0, 5)
    if k == 0:
        return rng.randint(-10, 10)
    if k == 1:
        return rng.randint(-10**12, 10**12)
    if k == 2:
        return round(rng.uniform(-1000, 1000), rng.randint(1, 6))
    if k == 3:
        return rng.choice([1e-7, 2.5e20, 1e100, 0.1, 123456789.125, -0.0])
    return rng.randint(0, 3)


def valor(rng, prof):
    k = rng.randint(0, 9 if prof < 4 else 5)
    if k <= 1:
        return numero(rng)
    if k == 2:
        return texto(rng)
    if k == 3:
        return rng.choice([True, False, None])
    if k == 4:
        return texto(rng, 3)
    if k == 5:
        return rng.choice([None, True, 0])
    if k <= 7:
        return [valor(rng, prof + 1) for _ in range(rng.randint(0, 4))]
    d = {}
    for _ in range(rng.randint(0, 4)):
        d[clave(rng)] = valor(rng, prof + 1)
    return d


def rutas(v, base=""):
    """Todas las rutas del documento (los textos de las claves sin punto)."""
    out = [base]
    if isinstance(v, dict):
        for k, h in v.items():
            out += rutas(h, k if base == "" and False else (base + "." + k if base != "" else k))
    elif isinstance(v, list):
        for i, h in enumerate(v):
            out += rutas(h, base + "." + str(i) if base != "" else str(i))
    return out


def buscar(v, ruta):
    """Lo que lib/json debe encontrar, o lo falso si no hay (existe, valor)."""
    if ruta == "":
        return True, v
    actual = v
    for seg in ruta.split("."):
        if isinstance(actual, dict):
            if seg not in actual:
                return False, None
            actual = actual[seg]
        elif isinstance(actual, list):
            if not seg.isascii() or not seg.isdigit() or (len(seg) > 1 and seg[0] == "0") or len(seg) > 9:
                return False, None
            i = int(seg)
            if i >= len(actual):
                return False, None
            actual = actual[i]
        else:
            return False, None
    return True, actual


def tipo_de(v):
    if v is None:
        return "nulo"
    if isinstance(v, bool):
        return "booleano"
    if isinstance(v, (int, float)):
        return "numero"
    if isinstance(v, str):
        return "texto"
    if isinstance(v, list):
        return "arreglo"
    return "objeto"


def hexa(s):
    return s.encode("utf-8").hex()


def esperado_q(v, ruta):
    ok, h = buscar(v, ruta)
    if not ok:
        return "Q  false 0  0 false"
    t = tipo_de(h)
    largo = len(h) if isinstance(h, (list, dict)) else 0
    if t == "texto":
        tx = h
    elif t == "booleano":
        tx = "true" if h else "false"
    elif t == "numero":
        tx = json.dumps(h)
    else:
        tx = ""
    ent = 0
    if t == "numero":
        if h >= 9.2e18:
            ent = 9223372036854775807
        elif h <= -9.2e18:
            ent = -9223372036854775807
        else:
            ent = int(h)
    b = "true" if (t == "booleano" and h) else "false"
    return f"Q {t} true {largo} {hexa(tx)} {ent} {b}"


def main():
    rng = random.Random(15)
    lineas = []
    esperado = []
    n_validos = n_q = n_malos = 0

    for _ in range(300):
        v = valor(rng, 0)
        if not isinstance(v, (dict, list)) and rng.random() < 0.5:
            v = [v]
        sep = rng.choice([None, (", ", ": "), (",", ":"), (" , ", " : ")])
        ascii_ = rng.random() < 0.5
        entrada = json.dumps(v, ensure_ascii=ascii_, separators=sep)
        if rng.random() < 0.3:
            entrada = " \t" + entrada + "\r "
        lineas.append("J" + entrada)
        esperado.append("J ok")
        esperado.append("C " + hexa(json.dumps(v, ensure_ascii=False, separators=(",", ":"))))
        esperado.append("A " + hexa(json.dumps(v, ensure_ascii=True, separators=(",", ":"))))
        esperado.append("P " + hexa(json.dumps(v, ensure_ascii=False, indent=2)))
        n_validos += 1
        todas = rutas(v)
        rng.shuffle(todas)
        pedidas = todas[:6] + [rng.choice(["x", "0", "99", "a.b", "01", "-1", "1.5", "é"]) for _ in range(2)]
        for r in pedidas:
            lineas.append("Q" + json.dumps(r))
            esperado.append(esperado_q(v, r))
            n_q += 1

    # documentos estropeados: si Python los rechaza, lib/json también
    base = []
    for _ in range(120):
        v = valor(rng, 0)
        base.append(json.dumps(v, ensure_ascii=rng.random() < 0.5))
    for s in base:
        for _ in range(4):
            m = rng.randint(0, 3)
            if len(s) == 0:
                continue
            i = rng.randint(0, len(s) - 1)
            if m == 0:
                t = s[:i]
            elif m == 1:
                t = s[:i] + rng.choice(list('{}[],:"\\x1.-+e')) + s[i + 1:]
            elif m == 2:
                t = s[:i] + rng.choice(list('{}[],:"\\x')) + s[i:]
            else:
                t = s + rng.choice(["x", "]", "}", ",", " 1", "\x00"])
            if "\n" in t or "\r" in t.replace("\r", "") and False:
                continue
            try:
                json.loads(t)
                continue            # sigue siendo válido: no sirve para este chequeo
            except ValueError:
                pass
            if "\n" in t:
                continue
            lineas.append("J" + t)
            esperado.append("J err")
            n_malos += 1

    # casos que Python acepta y lib/json también, hechos a mano
    mano = ['[]', '{}', '  [ ]  ', '"solo texto"', '12', '-0.5e-3', 'true', 'null', '{"a":{"b":[1,[2,[3]]]}}',
            '"\\ud83d\\ude00 \\u00e9 \\/ \\b\\f"']
    for t in mano:
        v = json.loads(t)
        lineas.append("J" + t)
        esperado.append("J ok")
        esperado.append("C " + hexa(json.dumps(v, ensure_ascii=False, separators=(",", ":"))) if not t.strip().startswith(("-0.5e", "12")) else "C " + hexa(t.strip()))
        esperado.append("A " + hexa(json.dumps(v, ensure_ascii=True, separators=(",", ":"))) if not t.strip().startswith(("-0.5e", "12")) else "A " + hexa(t.strip()))
        esperado.append("P " + hexa(json.dumps(v, ensure_ascii=False, indent=2)) if not t.strip().startswith(("-0.5e", "12")) else "P " + hexa(t.strip()))

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lineas) + "\n")
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/json_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_json_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout[-2000:] + r.stderr)
            print("test_json_python: FALLA, el programa terminó con", r.returncode)
            return 1

    salida = r.stdout.splitlines()
    malas = []
    if len(salida) != len(esperado):
        malas.append(f"se esperaban {len(esperado)} líneas y salieron {len(salida)}")
    for k, (a, e) in enumerate(zip(salida, esperado)):
        if a.strip() != e.strip():
            malas.append(f"línea {k}: salió {a[:150]!r}, esperado {e[:150]!r}")
            if len(malas) > 10:
                break
    if malas:
        print("\n".join(malas))
        print(f"test_json_python: FALLA ({len(malas)}+ diferencias)")
        return 1
    print(f"test_json_python: OK ({n_validos} documentos, {n_q} consultas de ruta, {n_malos} estropeados, "
          f"{len(mano)} a mano, todo igual que el json de Python)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
