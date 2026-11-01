"""Cómo `cli.py check` anuncia que rechazó un programa.

`cli.py` imprime estos encabezados y sale con 1 cuando el programa tiene un
error de sintaxis o de tipo. Pero también sale con 1 si se cae él mismo (en
Windows revienta al importar), y eso no es un rechazo: quien lea la salida
(la CI) usa es_rechazo() para distinguirlos.

Un solo lugar para el texto que se imprime y para la regla que lo reconoce,
así no pueden divergir. Todos los que imprimen estos errores usan las
constantes de acá: cli.py (check y build), main.py (run) y
codegen/compilar.py (compile_file). Este módulo no importa nada del compilador a
propósito: tiene que poder cargarse aunque el compilador no arranque.
"""

SINTAXIS = "ERROR DE SINTAXIS"
TIPO = "ERROR DE TIPO"


def es_rechazo(salida: str) -> bool:
    """La salida de `cli.py check` dice que el checker rechazó el programa."""
    return SINTAXIS in salida or TIPO in salida
