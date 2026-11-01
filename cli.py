"""
CLI unificado de SCAR.

Uso:
    python3 cli.py run   archivo.scar              # type-check + ejecuta en el intérprete
    python3 cli.py check archivo.scar [archivo2 ...]  # solo type-check, no ejecuta
    python3 cli.py build archivo.scar [-o salida]   # compila a binario nativo vía C

Este archivo es la fachada única que agrupa el intérprete (main.py) y el
compilador (codegen/) bajo un solo punto de entrada.
"""
import argparse
import os
import sys

from parser import parse, ParseError
from lexer import LexError
from type_checker import check, TypeError_
from version import VERSION
from main import run_file
from interpreter import salida_utf8
from codegen import compile_file, CodegenError
from fmt import format_source
from modulos import cargar, ErrorDeModulo
from source_context import source_context
import mensajes_error
from pila_grande import con_pila_grande


def _source_context(path, line, col, context_lines=1):
    """Fragmento de código alrededor de (line, col) con un puntero '^'.
    (implementación real vive en source_context.py, compartida con main.py;
    este wrapper queda para no tocar los call sites existentes en este
    archivo)."""
    return source_context(path, line, col, context_lines)


def _print_syntax_error(path, e):
    # módulos: un error dentro de un módulo se muestra en ese archivo
    path = getattr(e, "archivo", None) or path
    print(f"{path}: {mensajes_error.SINTAXIS}: {e}")
    ctx = _source_context(path, getattr(e, "line", None), getattr(e, "col", None))
    if ctx:
        print(ctx)


def _print_type_error(path, e):
    print(f"{path}: {mensajes_error.TIPO}: {e}")
    ctx = _source_context(getattr(e, "archivo", None) or path,
                          getattr(e, "line", None), getattr(e, "col", None))
    if ctx:
        print(ctx)


def _apply_join_timeout(args):
    """--join-timeout fija SCAR_JOIN_TIMEOUT antes de que el intérprete y el
    compilador la lean (ambos leen la misma variable, ver
    _read_join_timeout_env() en cada módulo) -- una sola fuente de verdad
    para que intérprete y binario nativo nunca diverjan. Sin el flag, no se
    toca la variable de entorno (si ya estaba seteada afuera, se respeta;
    si no, cada módulo cae a su propio default de 8.0)."""
    if getattr(args, "join_timeout", None) is not None:
        os.environ["SCAR_JOIN_TIMEOUT"] = str(args.join_timeout)


def _apply_ffi_strict(args):
    """Mismo criterio que _apply_join_timeout -- el flag de CLI solo
    setea la variable de entorno que ffi_worker.py ya sabe leer
    (_ffi_strict_mode()), sin duplicar la lógica de decisión acá."""
    if getattr(args, "ffi_strict", False):
        os.environ["SCAR_FFI_STRICT"] = "1"


def cmd_run(args):
    _apply_join_timeout(args)
    _apply_ffi_strict(args)
    for path in args.files:
        try:
            run_file(path, args.program_args, args.verbose)
        except (LexError, ParseError, ErrorDeModulo) as e:
            _print_syntax_error(path, e)
            sys.exit(1)


def cmd_check(args):
    """Solo type-check: parsea y corre el verificador de tipos, sin ejecutar nada."""
    exit_code = 0
    for path in args.files:
        try:
            program = cargar(path)
        except (LexError, ParseError, ErrorDeModulo) as e:
            _print_syntax_error(path, e)
            exit_code = 1
            continue

        errors = check(program)
        if errors:
            for e in errors:
                _print_type_error(path, e)
            exit_code = 1
        else:
            print(f"{path}: sin errores de tipo")
    sys.exit(exit_code)


def cmd_lsp(args):
    # el editor lo lanza y le habla por stdin/stdout con el protocolo LSP
    from lsp_server import LSPServer
    sys.exit(LSPServer().run())


def cmd_build(args):
    _apply_join_timeout(args)
    out_path = args.output or args.file.rsplit(".scar", 1)[0]
    if getattr(args, "lib", False) and not args.output:
        # libnombre.so, lo que espera ctypes.util.find_library / -lnombre
        carpeta, base = os.path.split(out_path)
        out_path = os.path.join(carpeta, f"lib{base}.so")
    try:
        c_path, binary = compile_file(args.file, out_path, libreria=getattr(args, "lib", False))
    except (LexError, ParseError, ErrorDeModulo) as e:
        _print_syntax_error(args.file, e)
        sys.exit(1)
    except CodegenError as e:
        print(f"----- ERROR DE COMPILACIÓN: {e} -----")
        sys.exit(1)
    print(f"C generado: {c_path}")
    if getattr(args, "lib", False):
        print(f"librería: {binary}")
    else:
        print(f"binario nativo: {binary}")


def cmd_fmt(args):
    """re-indenta según profundidad de llaves. Por defecto imprime a
    stdout; --write aplica el cambio en el archivo; --check no imprime nada
    y sale con 1 si el archivo no está ya formateado (para CI)."""
    exit_code = 0
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            src = f.read()
        formatted = format_source(src)

        if args.check:
            if formatted != src:
                print(f"{path}: no está formateado (correr 'scar fmt --write')")
                exit_code = 1
            continue

        if args.write:
            if formatted != src:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(formatted)
                print(f"{path}: formateado")
            else:
                print(f"{path}: ya estaba formateado")
        else:
            sys.stdout.write(formatted)
    sys.exit(exit_code)


def main():
    # Los mensajes del CLI (errores, el fuente de `fmt`) salen en UTF-8, como
    # la salida de un programa. En Windows, con la salida a un pipe o a un
    # archivo, Python usa cp1252: "línea" llegaba como "l\xednea" a quien la
    # leyera (ci.py, un editor).
    salida_utf8()
    parser_ = argparse.ArgumentParser(prog="scar", description="CLI de SCAR")
    parser_.add_argument("--version", action="version", version=f"scar {VERSION}")
    sub = parser_.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="type-check y ejecuta en el intérprete")
    p_run.add_argument("files", nargs="+", help="archivo(s) .scar a ejecutar")
    p_run.add_argument(
        "-v", "--verbose", action="store_true",
        help="muestra además los encabezados, las trazas del intérprete ([región], [tarea]...) y lo que devolvió main",
    )
    p_run.add_argument(
        "--join-timeout", type=float, default=None, metavar="SEGUNDOS",
        help="timeout de join()/deadlock (default: 8.0, o $SCAR_JOIN_TIMEOUT si está seteada)",
    )
    p_run.add_argument(
        "--ffi-strict", action="store_true",
        help=(
            "si el worker FFI aislado de una librería no arranca, "
            "rechazar la carga del programa en vez de ejecutar sus llamadas "
            "extern sin aislamiento de proceso (equivalente a $SCAR_FFI_STRICT=1)"
        ),
    )
    p_run.set_defaults(func=cmd_run)

    p_check = sub.add_parser("check", help="solo type-check, no ejecuta")
    p_check.add_argument("files", nargs="+", help="archivo(s) .scar a verificar")
    p_check.set_defaults(func=cmd_check)

    p_build = sub.add_parser("build", help="compila a binario nativo (backend de C)")
    p_build.add_argument("file", help="archivo .scar a compilar")
    p_build.add_argument("-o", "--output", help="ruta del binario de salida")
    p_build.add_argument(
        "--join-timeout", type=float, default=None, metavar="SEGUNDOS",
        help="timeout de join()/deadlock embebido en el binario (default: 8.0, o $SCAR_JOIN_TIMEOUT si está seteada)",
    )
    p_build.add_argument(
        "--lib", action="store_true",
        help="compila una librería compartida (.so) con las `export fn`, para llamarla "
             "desde otro lenguaje (Python con ctypes, C)",
    )
    p_build.set_defaults(func=cmd_build)

    p_fmt = sub.add_parser("fmt", help="re-indenta según profundidad de llaves")
    p_fmt.add_argument("files", nargs="+", help="archivo(s) .scar a formatear")
    p_fmt.add_argument("-w", "--write", action="store_true", help="aplica el cambio en el archivo")
    p_fmt.add_argument("--check", action="store_true", help="no escribe nada; exit 1 si falta formatear")
    p_fmt.set_defaults(func=cmd_fmt)

    p_lsp = sub.add_parser("lsp", help="servidor de lenguaje (LSP) para editores: habla por "
                                       "stdin/stdout, lo lanza el editor")
    p_lsp.set_defaults(func=cmd_lsp)

    # Lo que va después de `--` son los argumentos del programa
    # (los que lee arg(i)), no opciones de scar: `scar run f.scar -- 1000`.
    # Se separa antes de argparse para que un argumento del programa que
    # empiece con '-' nunca se confunda con una opción del CLI.
    argv = sys.argv[1:]
    program_args = []
    if "--" in argv:
        corte = argv.index("--")
        argv, program_args = argv[:corte], argv[corte + 1:]
    args = parser_.parse_args(argv)
    if program_args and args.command != "run":
        parser_.error(f"'{args.command}' no recibe argumentos de programa después de '--' "
                      "(un binario los recibe directo: ./programa 1000)")
    args.program_args = program_args
    try:
        con_pila_grande(lambda: args.func(args))
    except BrokenPipeError:
        # `scar run f.scar | head`: quien leía cerró la tubería. Se sale en
        # silencio, como cualquier programa de terminal, sin traceback. La
        # salida estándar se apunta a /dev/null para que el vaciado final de
        # Python no vuelva a fallar al cerrar.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(141)


if __name__ == "__main__":
    main()
