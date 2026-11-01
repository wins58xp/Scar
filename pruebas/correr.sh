#!/bin/sh
# Corre las pruebas de la librería estándar (lib/):
#
#   ./pruebas/correr.sh            # todas
#   ./pruebas/correr.sh json       # solo las de una librería
#
# Hay dos clases:
#   - pruebas/lib_<nombre>.scar: la librería se prueba a sí misma, en SCAR, con
#     la librería `prueba`;
#   - pruebas/test_<nombre>_python.py: compara sus resultados con los de Python
#     (y a veces numpy, scipy, matplotlib o Pillow). Si falta un paquete, esa
#     prueba se salta con un aviso.
# Las de interfaces gráficas necesitan libscarsdl (SDL2); corren sin ventana.

set -u
raiz=$(dirname "$(dirname "$(readlink -f "$0")")")
cd "$raiz" || exit 1
filtro=${1:-}
export SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy SCAR_SDL_MAX_FRAMES=10

bien=0; mal=0; saltadas=0
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT

for f in pruebas/lib_*.scar; do
    case "$f" in *"$filtro"*) ;; *) continue ;; esac
    # el guion de clics de una prueba con ventana (ci-env: SCAR_SDL_GUION=...)
    guion=$(sed -n 's/^# ci-env: SCAR_SDL_GUION=\(.*\)/\1/p' "$f")
    (cd pruebas && SCAR_SDL_GUION=$guion python3 "$raiz/cli.py" run "$raiz/$f") > "$tmp" 2>&1
    rc=$?
    if grep -q "falta la librería" "$tmp"; then
        echo "  · $f: se salta ($(grep -o 'falta la librería [a-z]*' "$tmp" | head -1))"
        saltadas=$((saltadas + 1))
    elif [ $rc -eq 0 ]; then
        echo "  ✓ $f: $(tail -1 "$tmp")"
        bien=$((bien + 1))
    else
        echo "  ✗ $f"; tail -15 "$tmp" | sed 's/^/      /'
        mal=$((mal + 1))
    fi
done

for f in pruebas/test_*.py; do
    case "$f" in *"$filtro"*) ;; *) continue ;; esac
    python3 "$f" > "$tmp" 2>&1
    rc=$?
    ultima=$(tail -1 "$tmp")
    if [ $rc -ne 0 ]; then
        echo "  ✗ $f"; tail -15 "$tmp" | sed 's/^/      /'
        mal=$((mal + 1))
    elif grep -q "se omite" "$tmp"; then
        echo "  · $f: $ultima"
        saltadas=$((saltadas + 1))
    else
        echo "  ✓ $f: $ultima"
        bien=$((bien + 1))
    fi
done

echo
echo "$bien pasaron, $mal fallaron, $saltadas saltadas"
[ $mal -eq 0 ]
