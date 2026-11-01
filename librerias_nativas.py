"""Las librerías de C que trae SCAR (ventanas y sonido, HTTPS, lanzar
procesos) y los mensajes cuando falta una librería o el compilador.

`instalar.sh` compila las de SCAR en native/lib/ de esta carpeta, sin sudo.
El compilador las busca ahí (-L y -rpath, así el binario las encuentra al
correr) y el intérprete también, antes que en el sistema. Una librería
instalada a mano en el sistema (/usr/local/lib) sigue funcionando igual.
"""

import os
import re

RAIZ = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(RAIZ, "native", "lib")

# nombre en `from "..."` -> (fuente, para qué sirve, qué instalar antes)
PROPIAS = {
    "scarsdl": ("native/scarsdl.c", "ventanas, dibujo y sonido",
                "SDL2 (sudo apt install libsdl2-dev)"),
    "scarhttp": ("native/scarhttp.c", "HTTPS",
                 "libcurl (sudo apt install libcurl4-openssl-dev)"),
    "scarproc": ("native/scarproc.c", "lanzar otros programas", None),
}

# El mismo texto en todos los mensajes de falta: la CI lo reconoce como un
# fallo del entorno y no del compilador.
FALTA = "falta la librería"

INSTALAR_CC = "instala gcc (sudo apt install gcc) o clang"


def ruta_local(lib):
    """La .so de una librería de SCAR compilada por instalar.sh, o None."""
    if lib not in PROPIAS:
        return None
    ruta = os.path.join(CARPETA, f"lib{lib}.so")
    return ruta if os.path.exists(ruta) else None


def flags_de_enlace(libs):
    """-L y -rpath a native/lib/ si alguna de `libs` está compilada ahí."""
    if any(ruta_local(lib) for lib in libs):
        return ["-L" + CARPETA, "-Wl,-rpath," + CARPETA]
    return []


def explicar_falta(lib):
    """Una línea: qué librería falta y cómo conseguirla."""
    if lib in PROPIAS:
        _, para, antes = PROPIAS[lib]
        pasos = f"instala {antes} y " if antes else ""
        return (f"{FALTA} lib{lib}, la de SCAR para {para}: {pasos}corre "
                f"./instalar.sh en la carpeta de SCAR, que la compila")
    return (f"{FALTA} lib{lib} (la que pide `from \"{lib}\"`): instálala, o pon "
            f"la carpeta donde está en LIBRARY_PATH y LD_LIBRARY_PATH")


_NO_ENCONTRADA = re.compile(r"(?:cannot find|no se puede encontrar) -l([\w.+-]+)")


def explicar_fallo_de_enlace(salida):
    """Si el linker no encontró una -l<lib>, la línea que lo explica; si no, None."""
    faltan = sorted(set(_NO_ENCONTRADA.findall(salida)))
    if not faltan:
        return None
    return "\n".join(explicar_falta(lib) for lib in faltan)
