"""Genera las tablas de lib/colores.scar a partir de matplotlib.

    python3 pruebas/gen_colores_tablas.py

Reescribe lo que hay entre las dos marcas "# ---- TABLAS" y "# ---- FIN DE LAS TABLAS"
de lib/colores.scar:
  - los 148 nombres de color de CSS (matplotlib.colors.CSS4_COLORS, en orden alfabético);
  - las paletas de colores distintos (tab10, tab20, set1, set2, set3, dark2, paired,
    accent, pastel1, pastel2) y okabe_ito (Okabe e Ito, 2008);
  - doce mapas continuos de 256 pasos, tomados con cmap(t, bytes=True) en el centro de
    cada casillero, de modo que la lib da exactamente lo que da matplotlib.
Hace falta matplotlib; la lib compilada no lo necesita.
"""

import os
import sys

import matplotlib
from matplotlib import colormaps
import matplotlib.colors as mc

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVO = os.path.join(RAIZ, "lib", "colores.scar")
INI = "# ---- TABLAS (generadas por pruebas/gen_colores_tablas.py: no se editan a mano) ----"
FIN = "# ---- FIN DE LAS TABLAS ----"

CATEGORICAS = ["tab10", "tab20", "set1", "set2", "set3", "dark2", "paired", "accent", "pastel1", "pastel2"]
MPL_CAT = {"set1": "Set1", "set2": "Set2", "set3": "Set3", "dark2": "Dark2", "paired": "Paired", "accent": "Accent", "pastel1": "Pastel1", "pastel2": "Pastel2"}
OKABE_ITO = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#000000"]
MAPAS = [("viridis", "viridis"), ("magma", "magma"), ("inferno", "inferno"), ("plasma", "plasma"),
         ("cividis", "cividis"), ("turbo", "turbo"), ("coolwarm", "coolwarm"), ("rdbu", "RdBu"),
         ("spectral", "Spectral"), ("ylgnbu", "YlGnBu"), ("greys", "Greys"), ("hot", "hot")]


def rgb24(hexa):
    return int(hexa[1:], 16)


def vec(nombre, valores, por_linea=12):
    lineas = []
    for i in range(0, len(valores), por_linea):
        lineas.append("        " + ", ".join(str(v) for v in valores[i:i + por_linea]))
    return (f"fn {nombre}() -> Vec<i32> {{\n    let v: Vec<i32> = [\n" + ",\n".join(lineas) + "\n    ]\n    return v\n}\n")


def generar():
    out = []
    css = sorted(mc.CSS4_COLORS.items())
    assert len(css) == 148
    out.append("# --- nombres de CSS ---\n")
    out.append("fn _css_nombre(i: i32) -> str {")
    for i, (n, _) in enumerate(css):
        out.append(f'    if i == {i} {{\n        return "{n}"\n    }}')
    out.append('    return ""\n}\n')
    out.append(vec("_css_valores", [rgb24(h) for _, h in css]))
    out.append("fn _css_valor(i: i32) -> i32 {\n    let v = _css_valores()\n    return v.get(i).unwrap_or(0)\n}\n")
    out.append("fn _css_busca(nombre: str) -> i32 {")
    for n, h in css:
        out.append(f'    if nombre == "{n}" {{\n        return {rgb24(h)}\n    }}')
    out.append("    return 0 - 1\n}\n")

    out.append("# --- paletas de colores distintos ---\n")
    cats = []
    for n in CATEGORICAS:
        cats.append((n, [rgb24(mc.to_hex(c)) for c in colormaps[MPL_CAT.get(n, n)].colors]))
    cats.append(("okabe_ito", [rgb24(h) for h in OKABE_ITO]))
    for n, v in cats:
        out.append(vec("_cat_" + n, v))
    out.append("fn _cat(nombre: str) -> Vec<i32> {")
    for n, _ in cats:
        out.append(f'    if nombre == "{n}" {{\n        return _cat_{n}()\n    }}')
    out.append("    let vacio: Vec<i32> = vec_new()\n    return vacio\n}\n")
    out.append("fn _cat_nombre(i: i32) -> str {")
    for i, (n, _) in enumerate(cats):
        out.append(f'    if i == {i} {{\n        return "{n}"\n    }}')
    out.append('    return ""\n}\n')

    out.append("# --- mapas de color de 256 pasos (matplotlib, cmap(t, bytes=True)) ---\n")
    for n, mpl in MAPAS:
        cm = colormaps[mpl]
        assert cm.N == 256, (mpl, cm.N)
        v = []
        for i in range(256):
            r, g, b, _ = cm((i + 0.5) / 256, bytes=True)
            v.append((int(r) << 16) | (int(g) << 8) | int(b))
        out.append(vec("_lut_" + n, v, 10))
    out.append("fn _lut(nombre: str) -> Vec<i32> {")
    for n, _ in MAPAS:
        out.append(f'    if nombre == "{n}" {{\n        return _lut_{n}()\n    }}')
    out.append("    let vacio: Vec<i32> = vec_new()\n    return vacio\n}\n")
    out.append("fn _lut_nombre(i: i32) -> str {")
    for i, (n, _) in enumerate(MAPAS):
        out.append(f'    if i == {i} {{\n        return "{n}"\n    }}')
    out.append('    return ""\n}\n')
    return "\n".join(out)


def main():
    with open(ARCHIVO, encoding="utf-8") as f:
        s = f.read()
    a, b = s.index(INI), s.index(FIN)
    nuevo = s[:a] + INI + "\n" + f"# matplotlib {matplotlib.__version__}\n\n" + generar() + "\n" + s[b:]
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        f.write(nuevo)
    print("tablas escritas en", ARCHIVO, f"({len(nuevo.splitlines())} líneas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
