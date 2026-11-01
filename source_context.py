"""Fragmento de código fuente con un puntero '^' señalando un (line, col).

Extraído de cli.py a un módulo propio para que main.py
(usado por `scar run`) pueda mostrar el mismo contexto que `scar check`
sin crear un import circular entre cli.py y main.py.
"""


def source_context(path, line, col, context_lines=1):
    """Fragmento de código alrededor de (line, col) con un puntero '^'.
    Si line o col no se pudieron derivar, devuelve None (el llamador cae de
    vuelta al mensaje plano: no todos los errores tienen posición)."""
    if line is None:
        return None
    try:
        # errors="replace": el error puede ser justamente un byte que no es
        # UTF-8; mostrarlo no debe reventar.
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    if not (1 <= line <= len(lines)):
        return None

    out = []
    start = max(1, line - context_lines)
    end = min(len(lines), line + context_lines)
    width = len(str(end))
    # una línea gigante (un literal de 100.000 dígitos) se muestra recortada
    # alrededor de la columna señalada
    MAX = 160
    corrido = 0
    if col is not None and col > MAX - 20:
        corrido = col - 40
    for n in range(start, end + 1):
        marker = ">" if n == line else " "
        texto = lines[n - 1]
        if corrido:
            texto = "…" + texto[corrido:]
        if len(texto) > MAX:
            texto = texto[:MAX] + "…"
        out.append(f"  {marker} {n:>{width}} | {texto}")
        if n == line and col is not None:
            # El prefijo de cada línea es "  > N | ": 2 + 1 + 1 + width + 3
            # = width + 7 caracteres. Con width + 6 el '^' quedaba una
            # columna a la izquierda de lo señalado.
            pad = " " * (width + 7) + " " * (col - 1 - corrido + (1 if corrido else 0))
            out.append(f"{pad}^")
    return "\n".join(out)
