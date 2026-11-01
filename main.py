import sys
from lexer import LexError
from parser import parse, ParseError
from interpreter import Interpreter, scar_str, ScarPanic, ScarRuntimeError, salida_utf8
from type_checker import check
from source_context import source_context
from modulos import cargar, ErrorDeModulo
import mensajes_error


def run_file(path, program_args=(), verbose=False):
    """Verifica los tipos de `path` y lo corre en el intérprete. Sin `verbose`
    solo se ve lo que imprime el programa (y los errores); con `verbose`,
    además los encabezados, las trazas del intérprete ([región], [tarea]...)
    y lo que devolvió main."""
    salida_utf8()
    program = cargar(path)  # módulos: resuelve los `use`

    errors = check(program)
    if verbose:
        print(f"===== verificando tipos: {path} =====")
    if errors:
        prefijo = "  " if verbose else f"{path}: "
        for e in errors:
            print(f"{prefijo}{mensajes_error.TIPO}: {e}")
            ctx = source_context(getattr(e, "archivo", None) or path,
                                 getattr(e, "line", None), getattr(e, "col", None))
            if ctx:
                print(ctx)
        print(f"----- {len(errors)} error(es) de tipo en {path}. No se ejecuta. -----\n")
        # Exit != 0, para que un CI o un script
        # que confía en el código de salida no deje pasar código inválido.
        sys.exit(1)
    if verbose:
        print("  sin errores de tipo\n")

    interp = Interpreter(verbose=True, program_args=program_args, trazas=verbose)
    try:
        interp.load(program)
    except ScarRuntimeError as e:
        # Modo seguro FFI (SCAR_FFI_STRICT): la carga puede rechazarse acá
        # mismo si un worker aislado no arrancó, antes de
        # ejecutar nada -- mismo tratamiento que un error de tipo, no un
        # traceback de Python.
        print(f"----- ERROR AL CARGAR: {e} -----\n")
        sys.exit(1)
    if verbose:
        print(f"===== ejecutando {path} =====")
    try:
        result = interp.run_main()
    except ScarPanic as p:   # incluye ScarDeadlock
        # el mismo texto que el binario, en la salida de errores
        sys.stdout.flush()
        if len(p.task_chain) > 1:
            # nació en una tarea y subió hasta main
            print(f"[PANIC] main murió porque su hija '{p.task_chain[-2]}' panickeó: "
                  f"{p.message}", file=sys.stderr)
        else:
            print(f"[PANIC] main murió: {p.message}", file=sys.stderr)
        sys.exit(1)
    if verbose:
        print(f"----- main() devolvió: {scar_str(result)} -----\n")
    # Un main -> i32 sale con ese código, igual que el binario
    # nativo (el checker solo deja devolver nada o un i32).
    if isinstance(result, int) and not isinstance(result, bool):
        sys.exit(result & 0xFF)


if __name__ == "__main__":
    # `python3 main.py f.scar -- 1000` (lo de después de `--` va a arg(i))
    argv = sys.argv[1:]
    program_args = []
    verbose = False
    if "--" in argv:
        corte = argv.index("--")
        argv, program_args = argv[:corte], argv[corte + 1:]
    if "-v" in argv or "--verbose" in argv:
        verbose = True
        argv = [a for a in argv if a not in ("-v", "--verbose")]
    def _correr_todo():
        for path in argv:
            _correr_uno(path)

    def _correr_uno(path):
        try:
            run_file(path, program_args, verbose)
        except (LexError, ParseError, ErrorDeModulo) as e:
            # Un error de sintaxis (un exponente mal formado, un
            # string sin cerrar) salía como un traceback de Python. Mismo
            # formato que el resto de los errores de este runner.
            if verbose:
                print(f"===== verificando tipos: {path} =====")
            print(f"{'  ' if verbose else path + ': '}{mensajes_error.SINTAXIS}: {e}")
            ctx = source_context(getattr(e, "archivo", None) or path,
                                 getattr(e, "line", None), getattr(e, "col", None))
            if ctx:
                print(ctx)
            print("----- error de sintaxis. No se ejecuta. -----\n")
            sys.exit(1)

    from pila_grande import con_pila_grande
    con_pila_grande(_correr_todo)
