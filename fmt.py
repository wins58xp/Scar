"""
Formateador de SCAR.

Diseño deliberado: NO parsea a AST y reimprime. El lexer (lexer.py) descarta
los comentarios por completo -- nunca se vuelven tokens -- así que un
formateador vía AST borraría cualquier comentario del archivo. En vez de eso,
este formateador trabaja directamente sobre el texto fuente: recalcula solo
la indentación de cada línea según la profundidad de llaves `{`/`}` (fuera de
strings y comentarios), y deja el resto de cada línea tal cual estaba
-- comentarios, espaciado interno, todo. Estilo canónico: 4 espacios por
nivel, llaves K&R -- ya es el estilo que usan los 31 ejemplos del repo.

Limitación explícita de este corte: no normaliza espaciado alrededor de
operadores ni separa/junta líneas -- solo indentación, que es lo que se
puede hacer sin riesgo de cambiar el programa.
"""

INDENT_UNIT = "    "  # 4 espacios


def format_source(src: str) -> str:
    lines = src.split("\n")
    depth = 0
    in_string = False  # ¿venimos de una línea anterior con un string sin cerrar?
    out_lines = []

    for raw_line in lines:
        n = len(raw_line)

        if in_string:
            # No es seguro reindentar una línea que es continuación de un
            # string literal (la nueva línea es contenido literal). Se deja
            # tal cual y solo se sigue el rastro de cuándo cierra el string.
            out_lines.append(raw_line)
            j = 0
            while j < n:
                c = raw_line[j]
                if c == "\\" and j + 1 < n:
                    j += 2
                    continue
                if c == '"':
                    in_string = False
                    j += 1
                    break
                j += 1
            scan_start = j
        else:
            stripped = raw_line.strip()
            if stripped == "":
                out_lines.append("")
                scan_start = n  # nada más que escanear en una línea vacía
            else:
                # Las líneas que empiezan con '}' (posiblemente varias
                # seguidas) se indentan un nivel menos por cada una --
                # el cierre de un bloque vive al nivel del bloque, no adentro.
                dedent = 0
                k = 0
                while k < len(stripped) and stripped[k] == "}":
                    dedent += 1
                    k += 1
                indent_level = max(0, depth - dedent)
                out_lines.append((INDENT_UNIT * indent_level) + stripped)
                scan_start = 0

        # Recorre la línea original completa desde donde corresponda para
        # actualizar profundidad de llaves, sin contar nada dentro de un
        # string o de un comentario.
        j = scan_start
        while j < n:
            c = raw_line[j]
            if in_string:
                if c == "\\" and j + 1 < n:
                    j += 2
                    continue
                if c == '"':
                    in_string = False
                j += 1
                continue
            if c == "#":
                break  # resto de la línea es comentario
            if c == '"':
                in_string = True
                j += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth = max(0, depth - 1)
            j += 1

    return "\n".join(out_lines)
