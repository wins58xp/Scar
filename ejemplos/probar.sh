#!/bin/sh
# Corre cada programa de ejemplos/ con el intérprete (scar run) y compilado
# (scar build), y compara: tienen que imprimir lo mismo (la salida estándar; un
# programa puede usar stderr para algo que cambia en cada corrida, como un
# tiempo medido) y salir con el mismo código.
#
#   ./ejemplos/probar.sh
#
# Necesita el comando `scar` (./instalar.sh) y un compilador de C. El ejemplo de
# interfaces gráficas se salta si no está libscarsdl (SDL2); se corre sin
# ventana, unos pocos cuadros.

set -u
aca=$(dirname "$(readlink -f "$0")")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy SCAR_SDL_MAX_FRAMES=3

bien=0; mal=0; saltados=0
for f in "$aca"/*.scar "$aca"/*/*.scar; do
    [ -f "$f" ] || continue
    grep -q '^fn main' "$f" || continue          # un módulo, no un programa
    nombre=${f#"$aca"/}
    cd "$(dirname "$f")" || exit 1

    salida_run=$(scar run "$f" 2>"$tmp/err"); rc_run=$?
    if grep -q "falta la librería" "$tmp/err" || printf '%s' "$salida_run" | grep -q "falta la librería"; then
        echo "  · $nombre: se salta ($( { cat "$tmp/err"; printf '%s' "$salida_run"; } | grep -o 'falta la librería [a-z]*' | head -1))"
        saltados=$((saltados + 1)); continue
    fi
    if ! scar build "$f" -o "$tmp/prog" > "$tmp/build.txt" 2>&1; then
        echo "  ✗ $nombre: no compila"; sed 's/^/      /' "$tmp/build.txt"
        mal=$((mal + 1)); continue
    fi
    salida_bin=$("$tmp/prog" 2>/dev/null); rc_bin=$?

    if [ "$salida_run" = "$salida_bin" ] && [ $rc_run -eq $rc_bin ]; then
        echo "  ✓ $nombre"
        bien=$((bien + 1))
    else
        echo "  ✗ $nombre: el intérprete y el binario no coinciden (códigos $rc_run y $rc_bin)"
        printf '%s\n' "$salida_run" > "$tmp/a"; printf '%s\n' "$salida_bin" > "$tmp/b"
        diff "$tmp/a" "$tmp/b" | head -10 | sed 's/^/      /'
        mal=$((mal + 1))
    fi
done

echo
echo "$bien iguales, $mal distintos, $saltados saltados"
[ $mal -eq 0 ]
