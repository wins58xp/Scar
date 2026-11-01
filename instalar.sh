#!/bin/sh
# Deja el comando `scar` listo para usar desde cualquier carpeta.
#
#   ./instalar.sh
#
# Revisa Python y el compilador de C, compila las librerías de C de SCAR que
# se puedan con lo que hay instalado (en native/lib/, dentro de esta
# carpeta) y enlaza bin/scar en ~/.local/bin. No usa sudo ni instala nada
# del sistema: si falta algo, dice qué instalar. Se puede correr de nuevo
# las veces que haga falta (por ejemplo, después de instalar SDL2).

set -u
raiz=$(dirname "$(readlink -f "$0")")
falta_algo=0

echo "SCAR en $raiz"
echo

# --- Python 3.12 o más nuevo ---
if ! command -v python3 >/dev/null 2>&1; then
    echo "  ✗ Python 3: no está. Instala python3 (sudo apt install python3)"
    falta_algo=1
elif python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
    echo "  ✓ $(python3 --version)"
else
    echo "  ✗ $(python3 --version): SCAR necesita Python 3.12 o más nuevo"
    falta_algo=1
fi

# --- compilador de C (para scar build y las librerías) ---
cc=""
for c in gcc clang cc; do
    if command -v "$c" >/dev/null 2>&1; then cc=$c; break; fi
done
if [ -n "$cc" ]; then
    echo "  ✓ compilador de C: $cc"
else
    echo "  ✗ compilador de C: no hay. Instala gcc (sudo apt install gcc) o clang"
    echo "    (scar run y scar check andan igual; scar build lo necesita)"
    falta_algo=1
fi

# --- librerías de C de SCAR, en native/lib/ ---
echo
lib="$raiz/native/lib"
mkdir -p "$lib"

compilar() {  # nombre, qué hace, flags extra
    nombre=$1; para=$2; shift 2
    if "$cc" -shared -fPIC -O2 "$raiz/native/$nombre.c" -o "$lib/lib$nombre.so" "$@" 2>/dev/null; then
        echo "  ✓ lib$nombre ($para)"
        return 0
    fi
    return 1
}

if [ -n "$cc" ]; then
    compilar scarproc "lanzar otros programas" \
        || echo "  ✗ libscarproc: no compiló (revisa con: $cc -shared -fPIC native/scarproc.c)"

    if command -v sdl2-config >/dev/null 2>&1; then
        # shellcheck disable=SC2046
        compilar scarsdl "ventanas, dibujo y sonido" $(sdl2-config --cflags --libs) \
            || echo "  ✗ libscarsdl: no compiló con el SDL2 instalado"
    else
        echo "  · libscarsdl (ventanas, dibujo y sonido): falta SDL2."
        echo "    Para usar la GUI: sudo apt install libsdl2-dev y vuelve a correr ./instalar.sh"
    fi

    compilar scarhttp "HTTPS" -lcurl || {
        echo "  · libscarhttp (HTTPS): falta libcurl."
        echo "    Para usar https: sudo apt install libcurl4-openssl-dev y vuelve a correr ./instalar.sh"
    }
else
    echo "  · las librerías de C se compilan cuando haya un compilador de C"
fi

# --- el comando scar ---
echo
destino="$HOME/.local/bin"
mkdir -p "$destino"
ln -sf "$raiz/bin/scar" "$destino/scar"
echo "  ✓ comando: $destino/scar"
case ":$PATH:" in
    *":$destino:"*) ;;
    *)
        echo "    $destino no está en tu PATH. Agrega esta línea a ~/.bashrc (o ~/.zshrc)"
        echo "    y abre una terminal nueva:"
        echo "        export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

echo
if [ "$falta_algo" -eq 0 ]; then
    echo "Listo. Prueba:  scar --version"
else
    echo "Falta algo de arriba (✗). Instálalo y vuelve a correr ./instalar.sh"
fi
