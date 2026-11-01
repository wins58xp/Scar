"""Backend de C: SCAR -> C -> gcc -> binario nativo.

Entrada: Codegen(programa).generate(); el build completo (módulos, checker,
gcc) es compile_file(), de codegen/compilar.py. El C que genera tiene que
hacer lo mismo que el intérprete (interpreter.py): la CI lo compara programa
por programa (paridad) y la foto del C (scripts/foto_c.py) fija el C de todo
el corpus.

Cómo se representa cada tipo en C:
- i32/i64/f64/bool: int32_t/int64_t/double/bool. Cada operación de f64 se
  redondea por separado, como en Python (gcc con -ffp-contract=off). El
  overflow de i32/i64 y la división por cero son un panic.
- str: char* terminado en 0, en UTF-8.
- struct de usuario: puntero (se comparte por referencia, como en el
  intérprete), reservado en el heap con scar_blk_heap, con o sin tasks
  (la arena de la tarea no se usa).
- Option<T>/Result<T>: struct por valor {tag, value, err}, monomorfizado al
  primer uso (c_type()). Nunca se muta en sitio.
- Vec<T>: struct por valor {data, len, cap}. Map<K,V>: puntero a una tabla.
- Chan<T>: puntero a una cola con mutex, compartido entre tareas.
- Pipe: struct por valor {read_fd, write_fd}.

Propiedad (quién libera cada valor), las reglas que el codegen cumple:
- Cada valor del heap tiene una sola dueña. `let b = a` mueve;
  pasar un valor a una fn, a push/set/send o a un campo, también.
- get() de Vec/Map devuelve una copia.
- Una fn o task que devuelve str (o algo que lo contiene) entrega uno propio;
  lo prestado sale copiado.
- Lo que el análisis no puede probar se resuelve en el C con un flag de
  propiedad, nunca con un free a ciegas.
- Los análisis que deciden esto viven aparte: fresh_owned.py (parámetros
  que una fn consume) y lugares.py (campos que una fn puede reasignar).

Tareas: una task es un pthread con su TaskContext (cancelación, registro
de dueñas vivas). Un panic cancela a las hermanas, suelta lo vivo y
sube por join(); join() espera en una condvar con el timeout de
SCAR_JOIN_TIMEOUT_SECONDS. Sin tasks en el programa no hay TaskContext: los
helpers usan scar_panic_main en vez de scar_panic.

Dónde está cada cosa:
- El paquete codegen/ (paso C6): este archivo tiene la clase Codegen;
  comun.py, las tablas, CodegenError, BUILTIN_SIGS y los helpers que no
  dependen de un Codegen; compilar.py, el build (gcc, flags, workers de FFI
  aislado). Codegen se arma con mixins, uno por archivo, que aportan
  métodos: el estado vive todo en self, y `import codegen` trae lo mismo
  que antes. `python3 -m codegen archivo.scar salida` compila.
- El runtime fijo de C (panic, vivas, rand, tareas, red, archivos, FFI...)
  está en native/runtime/ y se pega con runtime_c.texto() (codegen/runtime.py).
- Los nombres del usuario pasan a C con un prefijo (nombres_c.py), así no
  chocan con libc ni con el runtime.
- `?` se baja a sentencias con una temporal: por eso gen_expr recibe `out`
  y `pad`, para poder emitir antes del punto de uso.
"""

import re

from .comun import BUILTIN_SIGS, CodegenError, _rand_runtime_c
from .estado import Estado
from .programa import Programa
from .sentencias import Sentencias
from .expresiones import Expresiones
from .propiedad import Propiedad
from .frescura import Frescura
from .tipos_c import TiposC
from .plantillas_c import Plantillas
from .metodos import Metodos
from .impresion import Impresion
from .tareas import Tareas
from .ffi import FFI


class Codegen(Estado, Programa, Sentencias, Expresiones, Propiedad, Frescura, TiposC,
              Plantillas, Metodos, Impresion, Tareas, FFI):
    # un nombre de C (lo usan varios mixins para saber si un código ya es una
    # variable y no hace falta una temporal)
    _RE_C_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# el build nativo (módulos, checker, gcc): `import codegen` lo sigue trayendo
from .compilar import compile_file, flags_semantica_f64, _cc_command  # noqa: E402
