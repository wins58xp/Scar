"""El runtime de C que el codegen pega en el programa generado (paso C3; en el
paquete desde C6, antes runtime_c.py: los mixins lo importan como runtime_c).

Cada archivo de native/runtime/ es un trozo de C tal cual sale en el .c
generado. Donde el texto depende de cómo se compila el programa (con tasks o
sin, el tipo de un Vec, ...) lleva una marca @@NOMBRE@@ que el codegen
reemplaza al pegarlo: texto("archivo", NOMBRE=valor).

El archivo termina con un salto de línea que no es parte del C (así los
editores no lo cambian al guardar): texto() lo saca. Cualquier otro cambio
en estos archivos cambia el C generado, y la foto del C (scripts/foto_c.py)
lo muestra.
"""
import os
import re

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "native", "runtime")
_MARCA = re.compile(r"@@([A-Z0-9_]+)@@")
_cache = {}


def _plantilla(nombre):
    t = _cache.get(nombre)
    if t is None:
        with open(os.path.join(DIR, nombre + ".c"), encoding="utf-8", newline="") as f:
            t = f.read()
        if t.endswith("\n"):
            t = t[:-1]
        _cache[nombre] = t
    return t


def texto(nombre, **marcas):
    """El C de native/runtime/<nombre>.c con cada @@MARCA@@ reemplazada.
    Falta una marca o sobra un valor: error (un trozo de C a medio armar no
    puede llegar al programa)."""
    t = _plantilla(nombre)
    usadas = set(_MARCA.findall(t))
    if usadas != set(marcas):
        raise ValueError(f"runtime_c.texto({nombre!r}): marcas del archivo {sorted(usadas)}, "
                         f"valores dados {sorted(marcas)}")
    return _MARCA.sub(lambda m: marcas[m.group(1)], t)
