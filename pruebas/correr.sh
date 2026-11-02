#!/bin/sh
# Corre las pruebas de la librería estándar (lib/):
#
#   ./pruebas/correr.sh            # todas
#   ./pruebas/correr.sh json       # solo las de una librería
#
# Hay tres clases:
#   - pruebas/lib_<nombre>.scar: la librería se prueba a sí misma, en SCAR, con
#     la librería `prueba`;
#   - pruebas/test_<nombre>_python.py: compara sus resultados con los de Python
#     (y a veces numpy, scipy, matplotlib o Pillow). Si falta un paquete, esa
#     prueba se salta con un aviso;
#   - pruebas/deben_fallar/*.scar: programas que rompen una regla del lenguaje;
#     `scar check` tiene que rechazarlos con el mensaje de sus líneas
#     `# espera:` (./pruebas/correr.sh deben_fallar corre solo esos).
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

rechazos=0
for f in pruebas/deben_fallar/*.scar; do
    case "$f" in *"$filtro"*) ;; *) continue ;; esac
    rechazos=$((rechazos + 1))
    python3 cli.py check "$f" > "$tmp" 2>&1
    rc=$?
    falta=""
    if [ $rc -eq 0 ]; then
        falta="scar check lo acepta, y no debería"
    elif grep -q "Traceback (most recent call last)" "$tmp"; then
        falta="scar check se cae (Traceback)"
    else
        espera=$(sed -n 's/^# espera: *//p' "$f")
        [ -n "$espera" ] || falta="le falta la línea '# espera: ...'"
        # una línea # espera: por renglón; cada una tiene que estar en el mensaje
        while IFS= read -r e; do
            [ -z "$e" ] || grep -qF -- "$e" "$tmp" || { falta="lo rechaza con otro mensaje (esperaba: $e)"; break; }
        done <<EOF2
$espera
EOF2
    fi
    if [ -z "$falta" ]; then
        bien=$((bien + 1))
    else
        echo "  ✗ $f: $falta"; tail -8 "$tmp" | sed 's/^/      /'
        mal=$((mal + 1))
    fi
done
[ $rechazos -eq 0 ] || echo "  · pruebas/deben_fallar: $rechazos programas que rompen reglas, revisados"

echo
echo "$bien pasaron, $mal fallaron, $saltadas saltadas"
[ $mal -eq 0 ]
