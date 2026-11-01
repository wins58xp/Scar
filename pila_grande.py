"""Corre el CLI con una pila grande (lo usan cli.py y main.py)."""
import os
import sys


# El lexer/parser/checker/codegen son
# recursivos, y un programa muy anidado (20.000 paréntesis, 50.000 sumandos,
# 3.000 else-if) agotaba el límite de recursión de Python: traceback. Se corre
# todo en un hilo con una pila grande y un límite alto; si aun así no alcanza,
# es un error limpio, no un traceback.
LIMITE_RECURSION = 400_000
PILA_HILO = 1 << 30   # 1 GiB de memoria virtual (solo se usa lo que se toca)


def con_pila_grande(fn):
    import threading
    resultado = {}

    def correr():
        try:
            fn()
        except SystemExit as e:
            resultado["exit"] = e.code
        except RecursionError:
            print("----- ERROR: el programa está anidado demasiado profundo para procesarlo "
                  "(paréntesis, expresiones o if/else muy encadenados): partilo en partes "
                  "más chicas -----")
            resultado["exit"] = 1
        except BaseException as e:  # noqa: B902 -- se relanza en el hilo principal
            resultado["error"] = e

    viejo_limite = sys.getrecursionlimit()
    try:
        threading.stack_size(PILA_HILO)
        sys.setrecursionlimit(LIMITE_RECURSION)
    except (ValueError, RuntimeError):
        # la plataforma no deja una pila así: se corre directo, como antes
        correr()
    else:
        hilo = threading.Thread(target=correr, name="scar-cli")
        try:
            hilo.start()
        finally:
            # solo ESTE hilo lleva la pila grande: las tasks del intérprete
            # (un hilo cada una) vuelven al tamaño normal
            threading.stack_size(0)
        try:
            hilo.join()
        except KeyboardInterrupt:
            os._exit(130)
        finally:
            sys.setrecursionlimit(viejo_limite)
    sys.stdout.flush()
    if "error" in resultado:
        raise resultado["error"]
    if "exit" in resultado:
        sys.exit(resultado["exit"])
