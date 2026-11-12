#!/usr/bin/env python3
"""Compila las librerías nativas de SCAR (native/*.c) en native/lib/ para la
plataforma actual. Alternativa multiplataforma a instalar.sh (que es solo bash):
sirve en Windows con MinGW además de Linux/Unix.

Uso:
    python construir_nativas.py            # todas las que se puedan
    python construir_nativas.py scarsdl    # solo esa(s)

En Windows hace falta MinGW-w64 (gcc) y SDL2 en el PATH. Con MSYS2:
    pacman -S mingw-w64-x86_64-gcc mingw-w64-x86_64-SDL2
    y agregar C:\\msys64\\mingw64\\bin al PATH (trae gcc, headers de SDL2 y SDL2.dll).

Produce scarsdl.dll (+ libscarsdl.dll.a para enlazar) en Windows, o libscarsdl.so
en Linux. El build del juego (scar build) ya busca el archivo correcto por plataforma.
"""
import os
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(RAIZ, "native", "lib")
ES_WINDOWS = os.name == "nt"

# nombre en `from "..."` -> fuente en native/
FUENTES = {
    "scarproc": "native/scarproc.c",   # lanzar procesos (sin dependencias)
    "scarsdl": "native/scarsdl.c",     # ventanas/dibujo/sonido (SDL2)
    "scarhttp": "native/scarhttp.c",   # HTTPS (libcurl)
}


def compilador():
    return (os.environ.get("SCAR_CC") or shutil.which("gcc")
            or shutil.which("clang") or shutil.which("cc"))


def _sdl2_flags():
    """Flags para enlazar SDL2. Usa sdl2-config si está (Linux/MSYS2 shell);
    si no (PowerShell con MinGW en el PATH), el toolchain ya trae include/SDL2
    y libSDL2, así que alcanza con -lSDL2."""
    cfg = shutil.which("sdl2-config")
    if cfg and not ES_WINDOWS:
        out = subprocess.run([cfg, "--cflags", "--libs"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout.split()
    return ["-lSDL2"]


def _flags_extra(lib):
    if lib == "scarsdl":
        return _sdl2_flags()
    if lib == "scarhttp":
        return ["-lcurl"]
    return []


def construir(lib, fuente):
    cc = compilador()
    if not cc:
        print("no hay compilador de C (gcc/clang/cc) en el PATH")
        return False
    os.makedirs(CARPETA, exist_ok=True)
    salida = os.path.join(CARPETA, (f"{lib}.dll" if ES_WINDOWS else f"lib{lib}.so"))
    cmd = [cc, "-shared", "-O2"]
    if not ES_WINDOWS:
        cmd.append("-fPIC")
    cmd += [os.path.join(RAIZ, fuente), "-o", salida]
    if ES_WINDOWS:
        # import lib (libX.dll.a) para poder enlazar con -lX desde scar build
        cmd.append("-Wl,--out-implib," + os.path.join(CARPETA, f"lib{lib}.dll.a"))
    cmd += _flags_extra(lib)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  OK    {salida}")
        return True
    print(f"  FALLO {lib}:\n{(r.stderr.strip() or r.stdout.strip())}")
    return False


def main():
    pedidas = sys.argv[1:] or list(FUENTES)
    ok = True
    for lib in pedidas:
        if lib not in FUENTES:
            print(f"librería desconocida: {lib} (conocidas: {', '.join(FUENTES)})")
            ok = False
            continue
        print(f"compilando {lib} ...")
        if not construir(lib, FUENTES[lib]):
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
