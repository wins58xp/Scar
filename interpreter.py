"""
Intérprete/runtime de SCAR.

La pieza central es la relación región <-> tarea: cada `task` corre en un thread real
de Python, con su propia "región" (aquí modelada como un objeto que se libera al
terminar la tarea) y su propio `cancel_event`. Las tareas hijas que una tarea crea con
`spawn` quedan registradas en su contexto; si la tarea padre termina sin haber hecho
`join()` sobre ellas, se cancelan en cascada — esto es concurrencia estructurada real,
no solo prosa de diseño.
"""

import os


def _fds_abiertos(hasta=1024):
    """Los descriptores abiertos ahora mismo, sin abrir ninguno para saberlo:
    listar /proc/self/fd abre el directorio, y si el fd 3 estaba cerrado el
    listado diría que el 3 está abierto (es el del propio directorio)."""
    abiertos = set()
    for fd in range(hasta):
        try:
            os.fstat(fd)
        except OSError:
            continue
        abiertos.add(fd)
    return abiertos


# Los fd que el programa heredó al arrancar, tomados ANTES de importar ctypes:
# libffi 3.5 abre su propio .so al cargar y lo deja abierto, con el número
# libre más bajo. Si el fd 3 llegaba cerrado, read_pipe(3) leía esa librería
# (Ok('\x7fELF...')) en vez de fallar como el binario nativo. read_pipe() solo
# acepta estos fd y los de pipe_new() (ver _fd_del_programa). Este bloque
# tiene que quedar antes de cualquier import que pueda abrir archivos.
_FDS_HEREDADOS = frozenset(_fds_abiertos())

import ctypes  # noqa: E402
import ctypes.util  # noqa: E402
import librerias_nativas  # noqa: E402
import math
import random
import re
import select
import signal as _signal_module
import socket
import subprocess
import sys
import tempfile
import threading
import queue
import time

import ffi_worker as _ffi_worker_mod  # noqa: E402
from ffi_worker import FfiWorkerPool, ScarFfiWorkerError
from types_ import FN_MARK, mensaje_movida

from parser import (
    Program, StructDecl, FnDecl, ExternFnDecl, ExternTypeDecl, ExternLibDecl, Block, LetStmt, ReturnStmt, BreakStmt, ExprStmt, IfStmt,
    WhileStmt, WhileLetStmt, ForStmt, AssignStmt, NumLit, StrLit, BoolLit, Ident,
    BinOp, UnaryOp, Call, MethodCall, FieldAccess, IndexExpr, StructLit, SpawnExpr, ArrayLit,
    TryExpr, OkExpr, ErrExpr, SomeExpr, NoneExpr, PrintExpr,
)


# ---------------- Valores del runtime ----------------

class Ok:
    def __init__(self, value): self.value = value
    def __repr__(self): return f"Ok({self.value!r})"

class Err:
    def __init__(self, value): self.value = value
    def __repr__(self): return f"Err({self.value!r})"

class SomeVal:
    def __init__(self, value): self.value = value
    def __repr__(self): return f"Some({self.value!r})"

class NoneVal:
    def __repr__(self): return "None"

class StructInstance:
    def __init__(self, name, fields, variantes=None):
        self.name = name; self.fields = fields
        # Un enum es un struct con tag (enum_match.py); `variantes`
        # es [(nombre, cantidad de datos)] y el print muestra la variante.
        self.variantes = variantes

    def __repr__(self):
        if self.variantes is not None:
            v, n = self.variantes[self.fields["tag"]]
            if n == 0:
                return v
            datos = ", ".join(repr(self.fields[f"{v}_{j}"]) for j in range(n))
            return f"{v}({datos})"
        inner = ", ".join(f"{k}={v!r}" for k, v in self.fields.items())
        return f"{self.name}({inner})"


def scar_copy_value(v):
    """Un valor de SCAR tiene
    semántica de VALOR, no de referencia compartida. `push`, `Map.set` y
    `chan.send()` ya MUEVEN (el checker no deja usar el original después);
    `get()` era la única vía por la que una variable y un elemento de un
    contenedor podían ser el mismo objeto, y el intérprete devolvía ese alias
    mientras el nativo devolvía una copia (128_get_alias_vs_copia). Ahora
    `get()` devuelve una copia profunda en los dos backends; para modificar un
    elemento se usa `let x = v.get(i)`, se modifica `x` y `v.set(i, x)`.

    Copia en profundidad structs, Vec, Map y lo que envuelven (Some/Ok/Err).
    str, números y bool son inmutables: se comparten sin costo. Los handles
    (canales, archivos, pipes, sockets, tareas, funciones) son referencias a
    un recurso del sistema, no datos: se comparten igual que en el nativo."""
    if isinstance(v, StructInstance):
        return StructInstance(v.name, {k: scar_copy_value(x) for k, x in v.fields.items()}, v.variantes)
    if isinstance(v, ScarVec):
        out = ScarVec()
        out.items = [scar_copy_value(x) for x in v.items]
        return out
    if isinstance(v, ScarMap):
        out = ScarMap()
        out.items = {k: scar_copy_value(x) for k, x in v.items.items()}
        return out
    if isinstance(v, SomeVal):
        return SomeVal(scar_copy_value(v.value))
    if isinstance(v, Ok):
        return Ok(scar_copy_value(v.value))
    if isinstance(v, Err):
        return Err(scar_copy_value(v.value))
    return v


# ---- deadlock seguro en canales ----------------------------------------
#
# send() a un canal lleno o recv() de uno vacío esperarían para siempre. Se lleva la cuenta de las
# tareas vivas (main incluida) y de cuántas están esperando un canal o un join(): si TODAS esperan y nada
# avanza durante un momento, ninguna va a poder seguir nunca. Es un deadlock seguro, no "probable": una
# tarea que duerme, lee de la red o del teclado, o corre código, no está esperando y no lo dispara.
# Mismo mecanismo en el nativo (scar_hilos_vivos / scar_hilos_esperando).
_HILOS = {"vivos": 1, "esperando": 0}
_HILOS_LOCK = threading.Lock()
_DEADLOCK_MSG = ("deadlock: todas las tareas están esperando un canal o un join() y ninguna puede "
                 "seguir (un send() a un canal lleno o un recv() de uno vacío que nadie va a llenar; "
                 "¿falta un ch.close() o una tarea que lea?)")


def _hilos_sumar(campo, n):
    with _HILOS_LOCK:
        _HILOS[campo] += n


class _EsperaCanal:
    """Una espera bloqueada (send/recv/join): cuenta como 'esperando' mientras dura y revisa si todas
    las tareas quedaron trabadas."""

    def __init__(self):
        self.activa = False
        self.visto = None
        self.desde = 0.0

    def entrar(self):
        if not self.activa:
            self.activa = True
            _hilos_sumar("esperando", 1)

    def salir(self):
        if self.activa:
            self.activa = False
            _hilos_sumar("esperando", -1)

    def revisar(self):
        """Lanza ScarRuntimeError si todas las tareas esperan y nada avanzó en ~0,3 s."""
        with _HILOS_LOCK:
            todas = _HILOS["esperando"] >= _HILOS["vivos"]
        ahora = time.time()
        prog = _PROGRESO[0]
        if not todas or prog != self.visto:
            self.visto = prog
            self.desde = ahora
            return
        if ahora - self.desde >= 0.3:
            self.salir()
            raise ScarRuntimeError(_DEADLOCK_MSG)


class ScarChan:
    """Canal thread-safe: única forma de cruzar el límite de una región."""
    def __repr__(self):
        # Placeholder fijo, igual que el backend de C (el repr por
        # defecto de Python trae una dirección distinta en cada corrida).
        return "<canal>"

    def __init__(self, cap=0):
        self.q = queue.Queue()
        self.closed = False
        self.lock = threading.Lock()
        # 'cap': capacidad del canal, 0 = sin límite (como scar_chan_new_<T>).
        self.cap = cap
        # 'count': valores encolados, bajo el mismo 'lock' que protege
        # 'closed'; send() espera mientras count >= cap.
        self.count = 0

    def send(self, value, cancel_event=None, poll=0.02):
        # Paridad con scar_chan_send_<T> del backend de C --
        # misma condición de bloqueo (cap>0 && count>=cap && !closed) y
        # mismo trato de 'closed' como condición de despertar (si el canal
        # se cierra mientras send() espera lugar, deja de esperar y
        # encola, no descarta el valor). A diferencia de C, acá no hace
        # falta un camino de cancelación separado (send_cancel_line): no
        # hay un 'node' malloc'eado antes del loop que liberar a mano --
        # CancelledError es una excepción normal de Python, el value
        # todavía no se encoló en ningún lado cuando se propaga.
        espera = _EsperaCanal()
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError()
                with self.lock:
                    if not (self.cap > 0 and self.count >= self.cap and not self.closed):
                        self.q.put(value)
                        self.count += 1
                        _PROGRESO[0] += 1  # pasar un mensaje es avanzar
                        return
                espera.entrar()
                espera.revisar()
                time.sleep(poll * random.uniform(0.7, 1.3))
        finally:
            espera.salir()

    def recv(self, cancel_event, poll=0.02):
        espera = _EsperaCanal()
        try:
            return self._recv(cancel_event, poll, espera)
        finally:
            espera.salir()

    def _recv(self, cancel_event, poll, espera):
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError()
            try:
                # Jitter (±30%) sobre el poll: con muchos canales/tareas
                # esperando, un timeout fijo hace que todos los threads se
                # despierten en el mismo instante y compitan por el GIL a la
                # vez ("thundering herd"). El jitter desincroniza esos
                # despertares sin cambiar la cota máxima de espera por vuelta
                # ni la semántica de cancelación/cierre (ver AVANCE_CAP8.md).
                v = self.q.get_nowait() if not espera.activa else self.q.get(timeout=poll * random.uniform(0.7, 1.3))
                with self.lock:
                    self.count -= 1
                _PROGRESO[0] += 1  # pasar un mensaje es avanzar
                return SomeVal(v)
            except queue.Empty:
                with self.lock:
                    if self.closed and self.q.empty():
                        return NoneVal()
                espera.entrar()
                espera.revisar()
                continue

    def try_recv(self):
        """Some(valor) si hay uno encolado ahora mismo; None si no (no espera)."""
        with self.lock:
            try:
                v = self.q.get_nowait()
            except queue.Empty:
                return NoneVal()
            self.count -= 1
            return SomeVal(v)

    def close(self):
        with self.lock:
            self.closed = True

    def sender(self):
        return self

    def receiver(self):
        return self


class ScarVec:
    """Lista dinámica de tamaño variable. No es
    thread-safe a propósito (a diferencia de ScarChan): un Vec compartido
    entre tareas ya está cubierto por la regla de 'mover' del checker
    -- igual que un struct de usuario, cruza el límite de spawn/chan.send()
    por valor de propiedad, nunca por referencia compartida en vivo. Solo
    guarda referencias a lo que se empuja (`push` no copia), igual que
    ScarChan.send().

    'cap' (capacidad inicial opcional, ver scar_vec_new_<T> en codegen/
    y el bloque dedicado de vec_new en type_checker.py/_infer/Call) se
    acepta acá solo para que 'vec_new(N)' interprete igual de bien que
    compila -- no tiene ningún efecto real sobre una `list` de Python
    (ésta ya maneja su propio crecimiento amortizado internamente, no hay
    nada que "reservar" desde afuera como sí hace falta con el malloc
    manual del backend de C)."""
    def __init__(self, cap=0):
        self.items = []

    def push(self, value):
        self.items.append(value)

    def get(self, index):
        # Copia, no alias (ver scar_copy_value).
        if 0 <= index < len(self.items):
            return SomeVal(scar_copy_value(self.items[index]))
        return NoneVal()

    def pop(self):
        if self.items:
            return SomeVal(self.items.pop())
        return NoneVal()

    def set(self, index, value):
        # Mutación indexada (tape de Grad<T>): a diferencia de
        # push()/pop(), acá el índice debe existir de antes -- no extiende
        # el Vec ni actúa como "insert". Fuera de rango es un error real
        # del programa (panic), no un caso silencioso como get()/pop()
        # devolviendo None: escribir en un índice que no existe casi
        # siempre es un bug del llamador, y silenciarlo escondería una
        # escritura perdida. Mismo criterio que el indexado de str
        # ("índice fuera de rango", ver eval de IndexExpr).
        if not (0 <= index < len(self.items)):
            raise ScarRuntimeError(
                f"índice fuera de rango: {index} (longitud {len(self.items)})"
            )
        self.items[index] = value

    def replace(self, index, value):
        # Como set(), pero devuelve el elemento que estaba (el
        # mismo objeto, sin copiar: ya no está en el Vec, así que pasa a ser
        # de quien llama). Para modificar un struct guardado en un Vec sin
        # copiarlo: sacarlo con replace, cambiarlo y devolverlo con set.
        if not (0 <= index < len(self.items)):
            raise ScarRuntimeError(
                f"índice fuera de rango: {index} (longitud {len(self.items)})"
            )
        viejo = self.items[index]
        self.items[index] = value
        return viejo

    def __len__(self):
        return len(self.items)

    def __repr__(self):
        # Cada elemento con el formato de adentro de un contenedor
        # (str entre comillas, bool True/False), igual que Some(...) y un
        # campo de struct, y en cualquier lugar (suelto, en un Option o
        # Result, en un campo). Antes un Vec adentro de algo salía como
        # <interpreter.ScarVec object at 0x...>, y suelto como [a, b], que no
        # distingue ["a, b"] de ["a", "b"]. Mismo texto que scar_fmt_Vec_* del
        # nativo.
        return "[" + ", ".join(repr(x) for x in self.items) + "]"


class ScarMap:
    """Diccionario clave->valor. Mismo patrón que ScarVec: no es thread-safe a
    propósito (la regla de 'mover' del checker ya
    cubre un Map compartido entre tareas), y `.set()` no copia el valor --
    guarda la misma referencia, igual que ScarVec.push()/ScarChan.send(). Las
    claves se comparan por igualdad/hash de Python, que ya coincide con `==`
    de SCAR para los primitivos (i32/i64/f64/str/bool son los únicos K
    soportados por ahora -- ver la nota en MAP_MARK de type_checker.py sobre
    por qué no hay hashing de structs todavía)."""
    def __init__(self):
        self.items = {}

    def set(self, key, value):
        self.items[key] = value

    def get(self, key):
        # Copia, no alias (ver scar_copy_value).
        if key in self.items:
            return SomeVal(scar_copy_value(self.items[key]))
        return NoneVal()

    def remove(self, key):
        if key in self.items:
            return SomeVal(self.items.pop(key))
        return NoneVal()

    def __len__(self):
        return len(self.items)

    def __repr__(self):
        # Mismo criterio que ScarVec.__repr__. El nativo todavía no
        # imprime un Map (su tabla no guarda el orden de inserción).
        return "{" + ", ".join(f"{k!r}: {v!r}" for k, v in self.items.items()) + "}"


class ScarPipe:
    """Un pipe real del sistema operativo (os.pipe()), expuesto a SCAR como sus
    dos extremos (fd de lectura y fd de escritura) vía métodos, igual que ScarChan
    expone .sender()/.receiver() en vez de campos — así el type checker no necesita
    que el usuario declare un struct para esto (ver PIPE_MARK en type_checker.py).

    Es la primera fuente real de I/O bloqueante del lenguaje: a
    diferencia de sleep(), read_pipe() sobre el extremo de lectura puede bloquearse
    de verdad esperando datos externos.
    """
    def __init__(self):
        self.read_fd, self.write_fd = os.pipe()
        _FDS_DE_PIPES.update((self.read_fd, self.write_fd))

    def __repr__(self):
        # un placeholder fijo, como <file>/<canal>, no el repr de Python (que
        # cambia en cada corrida). El nativo imprime lo mismo.
        return "<pipe>"


# Los fd que el programa abrió con pipe_new(). Junto con _FDS_HEREDADOS, son los
# únicos que read_pipe() puede leer: el resto pertenece a Python o a una
# librería del intérprete, no al programa.
_FDS_DE_PIPES = set()


def _fd_del_programa(fd):
    return fd in _FDS_HEREDADOS or fd in _FDS_DE_PIPES


class ScarFile:
    """Un archivo del
    sistema operativo abierto vía file_open(path, mode). Mismo patrón
    estructural que ScarPipe/ScarChan: expone su comportamiento por métodos
    (.read_all()/.write()/.close()), no por campos de struct de usuario (ver
    FILE_MARK en type_checker.py) -- así no hace falta que el usuario declare
    un struct para esto. mode está restringido a 'r'/'w'/'a' (texto): modos
    binarios o combinados ('rb', 'r+') quedan fuera de este corte a propósito,
    para no tener que decidir todavía cómo se vería un str binario en SCAR.

    A diferencia de read_pipe(), NO necesita el mecanismo de cancelación
    cooperativa (self.ctx del intérprete): fopen()/fread()/fwrite() sobre un
    archivo local son operaciones que terminan solas (a diferencia de un pipe
    esperando datos de otro proceso), así que puede vivir en BUILTINS como
    cualquier función común en vez de necesitar despacho especial en eval().
    """
    def __init__(self, handle):
        self.handle = handle

    def __repr__(self):
        # Igual que TaskHandle, un placeholder fijo -- no el repr por defecto
        # de Python (que incluiría una dirección de memoria no reproducible)
        # -- para que Ok(File)/Err(...) se pueda imprimir con salida
        # comparable, carácter por carácter, contra el backend de C (ver
        # _value_fmt en codegen/, caso FILE_MARK).
        return "<file>"

    # Cerrar uno ya cerrado no hace nada y usarlo da Err, igual
    # que la tabla de handles del nativo (scar_h_ver/scar_h_soltar).
    @property
    def cerrado(self):
        return self.handle.closed

    def read_all(self):
        if self.cerrado:
            return Err("archivo cerrado")
        try:
            return Ok(self.handle.read())
        except OSError as e:
            return Err(f"error de lectura: {e.strerror or str(e)}")

    def read_bytes(self, n):
        """Hasta n bytes crudos (0..255) en un Vec<i32>;
        vacío en el fin de archivo. Mismo contrato que scar_file_read_bytes."""
        if n < 0:
            raise ScarRuntimeError(f"read_bytes: cantidad negativa ({n})")
        if self.cerrado:
            return Err("archivo cerrado")
        try:
            data = self.handle.buffer.read(n)
        except OSError as e:
            return Err(f"error de lectura: {e.strerror or str(e)}")
        v = ScarVec(len(data))
        v.items = list(data)
        return Ok(v)

    def write(self, s):
        if self.cerrado:
            return Err("archivo cerrado")
        try:
            n = self.handle.write(s)
            return Ok(n)
        except OSError as e:
            return Err(f"error de escritura: {e.strerror or str(e)}")

    def write_bytes(self, v):
        if self.cerrado:
            return Err("archivo cerrado")
        data = _bytes_de_vec(v)
        try:
            self.handle.flush()
            self.handle.buffer.write(data)
            return Ok(len(data))
        except OSError as e:
            return Err(f"error de escritura: {e.strerror or str(e)}")

    def close(self):
        self.handle.close()


def _bytes_de_vec(v):
    """Los valores de un Vec<i32> como bytes; uno
    fuera de 0..255 es un panic (igual que scar_bytes_de_vec en el nativo)."""
    for x in v.items:
        if not 0 <= x <= 255:
            raise ScarRuntimeError(f"write_bytes: {x} no es un byte (0..255)")
    return bytes(v.items)


class ScarSocket:
    """Backlog de I/O, último pendiente de la stdlib mínima: E/S
    de red. Envuelve un socket.socket() de Python ya conectado -- devuelto
    por tcp_connect() o por Listener.accept() -- mismo patrón estructural
    que ScarFile/ScarPipe: sin struct de usuario, todo por métodos
    (.read()/.write()/.close(), ver SOCKET_MARK en type_checker.py).

    A diferencia de ScarFile.read_all() (que lee hasta EOF, algo que un
    archivo local siempre alcanza), .read() de un socket NO puede esperar a
    EOF: la otra punta puede seguir la conexión abierta indefinidamente sin
    mandar nada más. Por eso .read() tiene la MISMA semántica que
    read_pipe(): devuelve lo que haya disponible en una sola
    lectura (Ok(str), posiblemente parcial), Err("EOF") si la otra punta
    cerró, o ScarIOTimeout si nadie manda nada y nadie cancela -- ver
    Interpreter._interruptible_socket_read().
    """
    def __init__(self, sock):
        self.sock = sock

    def __repr__(self):
        # Mismo criterio que ScarFile/TaskHandle: placeholder fijo, no la
        # dirección de memoria del objeto Python, para salida comparable
        # carácter por carácter contra el backend de C.
        return "<socket>"

    @property
    def cerrado(self):
        # ver ScarFile.cerrado
        return self.sock.fileno() == -1

    def write(self, s):
        if self.cerrado:
            return Err("socket cerrado")
        try:
            data = s.encode("utf-8")
            self.sock.sendall(data)
            return Ok(len(data))
        except OSError as e:
            return Err(f"error de escritura: {e.strerror or str(e)}")

    def write_bytes(self, v):
        if self.cerrado:
            return Err("socket cerrado")
        data = _bytes_de_vec(v)
        try:
            self.sock.sendall(data)
            return Ok(len(data))
        except OSError as e:
            return Err(f"error de escritura: {e.strerror or str(e)}")

    def close(self):
        self.sock.close()


class ScarListener:
    """Devuelto por tcp_listen(port): un socket de servidor ya en bind()+
    listen(), esperando conexiones entrantes. Igual que ScarSocket, sin
    struct de usuario -- expone .accept()/.close() (ver LISTENER_MARK en
    type_checker.py). .accept() es la segunda fuente de I/O bloqueante real
    del lenguaje después de read_pipe(): esperar una conexión
    entrante puede bloquearse indefinidamente esperando a un proceso
    externo, así que necesita el mismo mecanismo de cancelación cooperativa
    -- ver Interpreter._interruptible_accept().
    """
    def __init__(self, sock):
        self.sock = sock

    def __repr__(self):
        return "<listener>"

    @property
    def cerrado(self):
        return self.sock.fileno() == -1

    def close(self):
        self.sock.close()


class Region:
    """Región de memoria ligada al ciclo de vida de una tarea."""
    def __init__(self, owner_name):
        self.owner_name = owner_name
        self.released = False

    def release(self, log):
        if not self.released:
            self.released = True
            log(f"[región] liberada: región de '{self.owner_name}'")


_M64 = (1 << 64) - 1


def _splitmix64(z):
    z = (z + 0x9E3779B97F4A7C15) & _M64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
    return z ^ (z >> 31)


class _ScarRand:
    """El generador de rand(), idéntico al del nativo
    (codegen._rand_runtime_c): xorshift64 sembrado con splitmix64, uno por
    tarea. La semilla de una task sale de la de su madre y del número de
    spawn de la madre, al crearla: no depende del scheduling. Con la misma
    semilla, los dos backends dan exactamente los mismos números (la
    conversión a f64 es exacta)."""
    __slots__ = ("state", "base", "hijos")

    def __init__(self, semilla):
        self.init(semilla)

    def init(self, semilla):
        self.base = semilla & _M64
        self.hijos = 0
        s = _splitmix64(self.base)
        self.state = s if s else 0x9E3779B97F4A7C15

    def semilla_hija(self):
        self.hijos += 1
        return _splitmix64(self.base ^ ((self.hijos * 0xD1B54A32D192ED03) & _M64))

    def next(self):
        x = self.state
        x ^= (x << 13) & _M64
        x ^= x >> 7
        x ^= (x << 17) & _M64
        self.state = x
        return (x >> 11) * (1.0 / (1 << 53))


def _semilla_de_arranque():
    env = os.environ.get("SCAR_SEED", "")
    if env:
        return int(env) & _M64
    return (int(time.time()) ^ id(object())) & _M64


class TaskContext:
    """Contexto de ejecución de una tarea: sus hijos, su región, su señal de cancelación."""
    def __init__(self, name, region, cancel_event, parent=None):
        self.name = name
        # Generador de rand() de esta tarea (ver _ScarRand). La
        # semilla de una hija se calcula acá, en el hilo de la madre.
        self.rand = _ScarRand(parent.rand.semilla_hija() if parent is not None
                              else _semilla_de_arranque())
        self.region = region
        self.cancel_event = cancel_event
        self.parent = parent
        self.children = []  # lista de TaskHandle
        # inject_chan/accept_chan: referencia al propio TaskHandle, para que
        # accept_chan() -- que corre DESDE ADENTRO de la task, en su propio
        # thread -- pueda encontrar el slot donde inject_chan() (que corre
        # en el thread de quien inyecta, típicamente otra tarea/main) deja
        # lo que le inyectaron. None para main (root_ctx): accept_chan()
        # nunca se llama ahí -- el checker ya lo prohíbe fuera de una
        # 'task' -- pero se inicializa igual para no depender de que nadie
        # lo pise primero.
        self.own_handle = None


class TaskHandle:
    def __init__(self, name, thread, cancel_event, region, accepted_types=None):
        self.name = name
        self.thread = thread
        self.cancel_event = cancel_event
        self.region = region
        self.result = None
        self.panic = None  # ScarPanic si la tarea murió anormalmente; None si no
        self._joined = False
        # True si la tarea terminó por
        # CANCELACIÓN antes de completar su cuerpo. Mismo papel que el
        # flag 'completed' del TaskContext nativo (ver scar_join_wait).
        self.cancelled_before_complete = False
        # Un slot POR TIPO declarado en 'accepts', no uno solo compartido.
        # Cada TypeAnn de 'accepts' de la task (accepted_types,
        # que spawn_task() arma desde decl.accepts) recibe su propio slot
        # independiente: así 'accepts Chan<i32>, Chan<str>' no hace que un
        # Chan<i32> en tránsito bloquee a un Chan<str> que nadie está
        # disputando (lo que pasaría con un solo slot compartido con tag de
        # tipo), ni permite que accept_chan() devuelva un canal de un tipo
        # que no es el que esa llamada en particular anotó (lo que pasaría
        # si el slot no tuviera tag de tipo en absoluto). Mismo
        # 'injected_lock' de siempre protege TODO el dict -- un lock por
        # tipo sería sobre-ingeniería para la concurrencia real de este
        # mecanismo (pocas tasks, pocos tipos aceptados por task).
        self.injected_lock = threading.Lock()
        self.injected_slots = {ty: None for ty in (accepted_types or [])}

    def __repr__(self):
        return f"<task {self.name}>"


class CancelledError(Exception):
    pass

class ReturnSignal(Exception):
    def __init__(self, value): self.value = value

class BreakSignal(Exception):
    """`break`. La atrapa el loop más interno; el checker ya
    garantizó que hay uno."""

class PropagateErr(Exception):
    def __init__(self, err_value): self.err_value = err_value

class ScarRuntimeError(Exception):
    pass


def salida_utf8():
    """La salida de un programa SCAR es UTF-8, como la del binario (que
    escribe los bytes del str tal cual). Sin esto, en una máquina con otro
    locale (es_ES.ISO-8859-1) el intérprete escribía "ñ" en Latin-1 y el
    nativo en UTF-8: misma letra, bytes distintos. La llaman los que corren
    un programa (main.run_file, el runner de paridad), no la importación del
    módulo, para no cambiarle la salida a quien solo importa el intérprete."""
    for flujo in (sys.stdout, sys.stderr):
        if (hasattr(flujo, "reconfigure")
                and (flujo.encoding or "").lower().replace("-", "") != "utf8"):
            flujo.reconfigure(encoding="utf-8")


class ScarPanic(Exception):
    """Un panic real de SCAR: un error que no se puede manejar con Result/?.

    A diferencia de CancelledError (cooperación normal) o PropagateErr (control de
    flujo de `?`), esto representa que una tarea murió de forma anormal. Carga un
    mensaje ya formateado para humanos (nunca un traceback crudo de Python) y una
    cadena (`task_chain`) con los nombres de las tareas por las que se propagó, del
    origen hacia afuera, para poder mostrar "quién causó qué" en cascada.
    """
    def __init__(self, message, task_chain=None):
        super().__init__(message)
        self.message = message
        self.task_chain = task_chain if task_chain is not None else []


class ScarDeadlock(ScarPanic):
    """Caso especial de ScarPanic: join() no terminó dentro del timeout.

    Detectar deadlocks en general es indecidible; esto NO es una prueba de que hay
    un deadlock, es un timeout que dice "esto tardó demasiado, algo está mal".
    """
    pass


class ScarIOTimeout(ScarRuntimeError):
    """Timeout de una operación de I/O bloqueante real (ej. read_pipe), no de un
    join() sobre una tarea.

    Deliberadamente NO es subclase de ScarPanic: si lo fuera, el `except ScarPanic`
    de spawn_task() la confundiría con "una tarea hija panickeó y me la re-lanzó
    join()" (un bug real que encontramos probando el timeout de read_pipe sin
    cancelación externa). Al ser un tipo separado, cae en el `except Exception`
    genérico de spawn_task(), que la envuelve como panic PROPIO de esta tarea, con
    el mensaje y task_chain correctos.
    """
    pass


# Timeout por defecto de join(): si una tarea no termina en este tiempo, se asume
# "probable deadlock", se cancela y se reporta — nunca nos colgamos en silencio.
# Es deliberadamente generoso para no dar falsos positivos con los sleep() de los
# ejemplos (hasta ~3s); un programa real debería poder ajustar esto por-llamada.
#
# Se ajusta sin tocar código con la variable de entorno
# SCAR_JOIN_TIMEOUT (segundos, float) -- 8.0 si no está seteada o no es un float
# válido. `cli.py` expone además `--join-timeout` en `run`/`build`, que fija esta
# misma variable antes de invocar al intérprete o a codegen.
#
# Deliberadamente NO son constantes de módulo calculadas una sola vez al
# importar: `cli.py` hace `import interpreter` (vía `main.py`) ANTES de
# parsear sus argumentos, así que si `--join-timeout` recién setea la
# variable de entorno después, una constante ya congelada en el import
# nunca la vería. Por eso cada sitio de uso llama a estas funciones, que
# releen la variable de entorno en el momento real de usar el timeout
# (join()/read_pipe()/sockets), no al importar el módulo.
# Progreso global del programa (todas las tasks): cada safepoint de trabajo
# real (entrada de bloque -- cuerpo de loop, de fn, rama de if -- y cada paso de
# sleep()) lo incrementa. join() solo declara "probable deadlock" si NINGUNA
# task avanzó durante SCAR_JOIN_TIMEOUT segundos seguidos: una task que tarda
# más de eso trabajando (programa lento, máquina cargada) ya no es un deadlock.
# Las esperas bloqueadas (recv/send en un canal, el propio join, I/O) no
# cuentan como progreso. Con el GIL, un += 1 ocasionalmente perdido no importa:
# solo se compara si cambió. Mismo mecanismo en el nativo (scar_progreso).
_PROGRESO = [0]


def _read_join_timeout_env():
    raw = os.environ.get("SCAR_JOIN_TIMEOUT")
    if raw is None:
        return 8.0
    try:
        value = float(raw)
    except ValueError:
        print(
            f"[scar] aviso: SCAR_JOIN_TIMEOUT={raw!r} no es un número válido, "
            "usando el valor por defecto (8.0)",
            file=sys.stderr,
        )
        return 8.0
    if value <= 0:
        print(
            f"[scar] aviso: SCAR_JOIN_TIMEOUT={raw!r} debe ser > 0, "
            "usando el valor por defecto (8.0)",
            file=sys.stderr,
        )
        return 8.0
    return value


# Timeout por defecto de una I/O bloqueante real (ej. read_pipe) cuando nadie la
# cancela. Deliberadamente MENOR que el de join(): si el timeout interno de
# I/O y el de join() del padre compitieran por el mismo valor, cuál gana sería una
# carrera de timing (a veces se ve el panic real de I/O, a veces el join() del padre
# gana primero y muestra "probable deadlock" en su lugar — un mensaje mucho menos
# útil, porque esconde la causa real). Con este margen, el panic de I/O SIEMPRE se
# dispara y se ve primero. El margen sigue fijo (0.5s); lo ajustable es la base
# (SCAR_JOIN_TIMEOUT), así que este valor siempre se recalcula relativo a ella.
IO_TIMEOUT_MARGIN = 0.5


def _read_io_timeout_env():
    return _read_join_timeout_env() - IO_TIMEOUT_MARGIN


def format_panic_message(exc: BaseException) -> str:
    """Formatea una excepción de Python como mensaje de panic legible para humanos,
    sin exponer un traceback interno del intérprete."""
    if isinstance(exc, ScarRuntimeError):
        return str(exc)
    if isinstance(exc, RecursionError):
        # El mismo mensaje que da el backend nativo
        return "desbordamiento de pila: recursión demasiado profunda (¿falta un caso base?)"
    return f"{type(exc).__name__}: {exc}"


_MISSING = object()


class _Movida:
    """Lo que queda en una variable que una vuelta de un loop movió
    en una sola rama de un if (el checker marca esos usos con
    `verificar_movida` y esos movimientos con `registra_mov`). Volver a
    usarla así es un panic, igual que en el nativo (su flag de dueña)."""
    __slots__ = ()


_MOVIDA = _Movida()



class Environment:
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def define(self, name, value):
        self.vars[name] = value

    def get(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise ScarRuntimeError(f"variable no definida: {name}")

    def set(self, name, value):
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return
            env = env.parent
        raise ScarRuntimeError(f"variable no definida: {name}")

    def lookup(self, name, default=None):
        """Como get(), pero sin excepción si no existe (camino caliente de
        _eval_Call: se consulta en cada llamada por nombre)."""
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        return default


class FnValue:
    """Una fn top-level usada como VALOR ('aplicar(duplicar, 5)', parámetros
    'f: fn(i32) -> i32'), como en el nativo (_fn_c_type en codegen/: puntero
    a función C). Sin captura: solo el nombre de la fn."""
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<fn {self.name}>"

    def __eq__(self, other):
        return isinstance(other, FnValue) and other.name == self.name

    def __hash__(self):
        return hash(("FnValue", self.name))


class Interpreter:
    def __init__(self, verbose=True, program_args=(), trazas=True):
        # Argumentos del programa (sin el nombre del archivo), los
        # que lee arg(i). Solo lectura después de construir el intérprete,
        # así que las tasks los leen sin lock.
        self.program_args = tuple(program_args)
        self.functions = {}
        self.structs = {}
        self.extern_functions = {}  # nombre -> callable de ctypes
        self.extern_types = {}  # nombre -> ExternTypeDecl: handle
                                  # opaco de FFI, representado en runtime como
                                  # ctypes.c_void_p -- ver _ctype_for/_bind_extern_fn.
        self.verbose = verbose
        # las líneas de depuración ([región], [tarea], [cascada], [nursery]):
        # `scar run` las muestra solo con --verbose
        self.trazas = trazas
        self._local = threading.local()   # contexto de tarea por-thread
        self._log_lock = threading.Lock()

    def log(self, msg):
        if self.verbose:
            with self._log_lock:
                print(msg)

    def aviso(self, msg):
        """Un aviso del runtime ([PANIC] ...): va a la salida de errores, con
        el mismo texto que el binario. Lo impreso antes sale primero."""
        with self._log_lock:
            sys.stdout.flush()
            print(msg, file=sys.stderr, flush=True)

    def traza(self, msg):
        """Una línea de depuración del intérprete, no del programa."""
        if self.trazas:
            self.log(msg)

    # ---- contexto de tarea actual (por thread) ----
    @property
    def ctx(self) -> TaskContext:
        return self._local.ctx

    @ctx.setter
    def ctx(self, value):
        self._local.ctx = value

    def _builtin_arg(self, i):
        """arg(i): Some(el i-ésimo argumento) o None fuera de
        rango. Python decodifica argv con surrogateescape, así que se vuelve
        a los bytes originales (os.fsencode) y se decodifica en UTF-8
        estricto: la misma regla que scar_arg() del nativo sobre los mismos
        bytes. Un argumento que no es UTF-8 es un panic, nunca un texto
        inventado (reemplazar bytes cambiaría el dato sin avisar)."""
        if i < 0 or i >= len(self.program_args):
            return NoneVal()
        a = self.program_args[i]
        crudo = os.fsencode(a) if isinstance(a, str) else bytes(a)
        try:
            return SomeVal(crudo.decode("utf-8"))
        except UnicodeDecodeError:
            raise ScarRuntimeError(f"arg({i}): el argumento no es UTF-8 válido")

    def cancel_check(self):
        if self.ctx.cancel_event.is_set():
            raise CancelledError()

    def join_task(self, handle: "TaskHandle", timeout=None):
        """join() consciente de la cancelación de quien espera.

        Un `thread.join()` bloqueante ciego tiene un problema real en cascadas de
        más de un nivel: si a MÍ (quien está esperando) me cancelan mientras estoy
        bloqueado acá, no me entero hasta que la tarea hija termine sola o se venza
        el timeout de deadlock — es decir, sigo "esperando en vano" exactamente lo
        que la concurrencia estructurada promete evitar. Por eso esperamos en pasos
        cortos, revisando en cada paso tanto si la hija ya terminó como si a
        nosotros nos cancelaron mientras tanto.
        """
        # Un segundo join() sobre el mismo handle es un error del programa,
        # no una lectura idempotente: el nativo panickea (scar_join_wait,
        # 'joined' en el TaskContext -- pthread_tryjoin_np() sobre un thread
        # ya joineado es UB), y el intérprete hace lo mismo, con el mismo
        # mensaje.
        if handle._joined:
            raise ScarPanic(
                f"join() llamado más de una vez sobre '{handle.name}' -- "
                f"una tarea solo puede joinearse una vez"
            )
        wait = timeout if timeout is not None else _read_join_timeout_env()
        poll = 0.02
        deadline = time.time() + wait
        visto = _PROGRESO[0]
        waiter_cancel = self.ctx.cancel_event
        espera_join = _EsperaCanal()   # Esperar un join también es estar trabado
        espera_join.entrar()
        try:
            self._join_esperar(handle, wait, poll, deadline, visto, waiter_cancel)
        finally:
            espera_join.salir()
        return self._join_resultado(handle)

    def _join_esperar(self, handle, wait, poll, deadline, visto, waiter_cancel):
        while True:
            if waiter_cancel is not None and waiter_cancel.is_set():
                # A quien está haciendo join() lo cancelaron mientras esperaba. No
                # tiene sentido seguir esperando a la hija sin supervisión: la
                # cancelamos también (best-effort) y nos vamos ya vía
                # CancelledError, para que nuestro propio `finally` (en spawn_task
                # o run_main) siga la cascada hacia nuestros propios hijos.
                handle.cancel_event.set()
                raise CancelledError()
            step = min(poll, max(0.0, deadline - time.time()))
            handle.thread.join(timeout=step)
            if not handle.thread.is_alive():
                break
            if _PROGRESO[0] != visto:
                # alguna task avanzó: el plazo se cuenta desde acá
                visto = _PROGRESO[0]
                deadline = time.time() + wait
            if time.time() >= deadline:
                # No sabemos si es un deadlock real (indecidible en general), pero
                # nos negamos a colgarnos en silencio. Cancelamos y lo reportamos
                # como probable deadlock.
                handle.cancel_event.set()
                handle.thread.join(timeout=1)
                raise ScarDeadlock(
                    f"join() sobre '{handle.name}' no terminó tras {wait}s — "
                    f"probable deadlock (tarea cancelada, no se pudo confirmar "
                    f"la causa)",
                    task_chain=[handle.name],
                )

    def _join_resultado(self, handle):
        handle._joined = True
        if handle.panic is not None:
            # Re-lanzar el panic de la tarea hija en quien la joinea. Si "quien" es
            # otra tarea, esto se vuelve un panic de esa tarea también (se propaga
            # solo, vía las excepciones de Python, tarea por tarea hacia arriba).
            raise handle.panic
        if handle.cancelled_before_complete:
            # Joinear una tarea que fue CANCELADA antes de terminar --
            # típicamente por la cascada de una hermana que panickeó -- es un
            # panic de quien espera, igual que en el nativo (scar_join_wait,
            # rama '!completed'), con el mismo mensaje. Si no, quien espera
            # seguiría ejecutando como si nada.
            raise ScarPanic(
                f"join() sobre '{handle.name}' nunca completo -- fue cancelada antes "
                f"de terminar (probablemente por la cascada de una tarea "
                f"hermana que panickeó)"
            )
        return handle.result


    def _inject_chan(self, handle: "TaskHandle", chan: "ScarChan", chan_ty: "TypeAnn"):
        """Entrega un canal a una task ya corriendo (inject_chan() en SCAR).
        De las tres condiciones, "la task destino declaró 'accepts' el
        tipo correcto" ya la probó type_checker.py de forma 100% estática
        antes de que este código corra (cuando pudo resolver la task
        concreta -- ver el comentario en type_checker.py sobre 'target is
        None') -- acá quedan las de runtime por naturaleza ("el handle
        sigue vivo", "no hay una inyección previa sin consumir PARA ESE
        TIPO"), verificadas atómicamente bajo el lock del propio handle
        para que dos inject_chan() concurrentes no se pisen en silencio, MÁS
        una repetición defensiva de "el tipo es uno de los aceptados" por si
        el checker no pudo validarlo estáticamente (handle con task destino
        no resuelta en compilación). chan_ty es el tipo estático de 'chan'
        tal como lo infirió el checker en el sitio de la llamada (anotado
        en el nodo Call por type_checker.py, ver 'expr.chan_ty' ahí) --  es
        la clave que decide A CUÁL slot va este canal quedan varios tipos
        aceptados a la vez, cada uno con su propio slot independiente (ver
        TaskHandle.injected_slots). Nunca bloquea: si el slot de ese tipo
        está ocupado, el tipo no es uno de los aceptados, o la task ya
        terminó, devuelve Err de inmediato -- es responsabilidad de quien
        llama reintentar si quiere."""
        if not handle.thread.is_alive():
            return Err(f"la task '{handle.name}' ya terminó, no se puede inyectar")
        with handle.injected_lock:
            if chan_ty not in handle.injected_slots:
                # Defensivo (ver docstring): el checker no siempre puede
                # resolver estáticamente la task destino de un TaskHandle
                # genérico, así que esta condición SÍ puede llegar a pasar
                # en un programa que compiló limpio.
                return Err(
                    f"la task '{handle.name}' no declaró aceptar "
                    f"{chan_ty!r} por inyección"
                )
            if handle.injected_slots[chan_ty] is not None:
                return Err(
                    f"la task '{handle.name}' ya tiene una inyección de "
                    f"{chan_ty!r} pendiente sin consumir (accept_chan())"
                )
            handle.injected_slots[chan_ty] = chan
        return Ok(None)

    def _accept_chan(self, expected_ty: "TypeAnn"):
        """Contraparte de _inject_chan(): corre DESDE ADENTRO de la propia
        task, en su propio thread. A propósito no bloqueante (mismo
        criterio que documenta accept_chan() en type_checker.py: "intenta
        recibir un canal extra sin bloquear el resto de su trabajo") --
        consume el slot de expected_ty si hay algo esperando ahí, si no
        devuelve None ya mismo; la task decide sola si vuelve a preguntar
        más adelante. expected_ty viene de la anotación del 'let' que
        recibe esta llamada (ver _exec_LetStmt) -- es la ÚNICA fuente
        posible de T, igual que ya pasaba antes de este cambio, solo que
        ahora además decide de cuál de los slots (uno por tipo aceptado) se
        drena: si la task acepta más de un tipo, cada uno tiene su propio
        slot independiente, así que una inyección de un tipo nunca le tapa
        el paso a una inyección pendiente de otro tipo."""
        handle = self.ctx.own_handle
        if handle is None:
            # Defensivo: el checker ya garantiza que accept_chan() solo
            # aparece dentro de una 'task' (fn.is_task), así que esto no
            # debería pasar nunca en un programa que compiló limpio.
            return NoneVal()
        with handle.injected_lock:
            chan = handle.injected_slots.get(expected_ty)
            if chan is not None:
                handle.injected_slots[expected_ty] = None
        return NoneVal() if chan is None else SomeVal(chan)

    def _cancel_siblings(self, parent_ctx: TaskContext, panicked_handle: "TaskHandle"):
        """Semántica 'nursery': cuando una tarea panickea, sus hermanas (los otros
        hijos de su mismo padre) se cancelan de inmediato — no hace falta esperar a
        que el padre termine o haga join() para dejar de trabajar en vano."""
        for sib in parent_ctx.children:
            if sib is not panicked_handle and sib.thread.is_alive():
                self.traza(
                    f"[nursery] '{panicked_handle.name}' panickeó -> "
                    f"cancelando a su hermana '{sib.name}'"
                )
                sib.cancel_event.set()

    # ---- carga del programa ----
    def load(self, program: Program):
        # Hace falta el dict de extern_types COMPLETO antes de poder
        # arrancar los workers de FFI -- por eso un pre-paso aparte solo
        # para ExternTypeDecl, ANTES del loop principal (que sigue
        # registrando todo lo demás en un solo pase).
        for item in program.items:
            if isinstance(item, ExternTypeDecl):
                self.extern_types[item.name] = item
            elif isinstance(item, StructDecl):
                # un extern puede usar un struct declarado más abajo
                self.structs[item.name] = item

        extern_decls = [item for item in program.items if isinstance(item, ExternFnDecl)]
        ffi_pool = FfiWorkerPool()
        # Un worker por librería (`from "lib"`), no uno por función: así
        # el estado que una librería mantiene entre llamadas (ej. la
        # ventana viva de scarsdl) sigue funcionando -- ver comentario de
        # cabecera de ffi_worker.py.
        # `extern lib "x" en_proceso`: esas librerías se llaman directo por
        # ctypes, sin worker (el checker ya exigió la marca a las que no se
        # pueden aislar).
        en_proceso = {item.library for item in program.items if isinstance(item, ExternLibDecl)}
        decls_by_library = {}
        for decl in extern_decls:
            if decl.library is not None:
                decls_by_library.setdefault(decl.library, []).append(decl)

        for item in program.items:
            if isinstance(item, StructDecl):
                self.structs[item.name] = item
            elif isinstance(item, FnDecl):
                self.functions[item.name] = item
            elif isinstance(item, ExternTypeDecl):
                pass  # ya cargado en el pre-paso de arriba
            elif isinstance(item, ExternFnDecl):
                worker = None
                if item.library is not None and item.library not in en_proceso:
                    try:
                        worker = ffi_pool.get_or_build(
                            item.library, decls_by_library[item.library], self.extern_types
                        )
                    except ScarFfiWorkerError as e:
                        # En modo estricto (SCAR_FFI_STRICT), un
                        # worker que no arranca debe abortar la carga del
                        # programa, no las llamadas individuales -- todavía
                        # no hay llamadas hechas acá, así que el error más
                        # claro es fallar ya mismo, igual que un error de
                        # tipo detectado antes de ejecutar (ver run_file en
                        # main.py, que ahora atrapa esto).
                        raise ScarRuntimeError(str(e))
                self.extern_functions[item.name] = _bind_extern_fn(
                    item, self.extern_types, worker, interp=self,
                    structs={n: d for n, d in self.structs.items() if not d.type_params},
                )

    def run_main(self, args=None):
        root_region = Region("main")
        root_ctx = TaskContext("main", root_region, threading.Event())
        self.ctx = root_ctx
        result = None
        panic = None
        try:
            result = self.call_function("main", args or [])
        except ScarPanic as p:
            # Llegó por cascada (un join() dentro de main() re-lanzó el panic de
            # una tarea hija).
            p.task_chain.append("main")
            panic = p
        except Exception as e:
            # Panic directo en el cuerpo de main() (no dentro de una tarea): antes
            # esto salía como traceback crudo de Python; ahora es un panic más.
            panic = ScarPanic(format_panic_message(e), task_chain=["main"])
        finally:
            # main() se trata como cualquier tarea a efectos de concurrencia
            # estructurada: si termina (normal, por panic, o lo que sea) con hijos
            # vivos sin join(), se cancelan en cascada antes de liberar su región.
            for child in root_ctx.children:
                if child.thread.is_alive():
                    self.traza(f"[cascada] 'main' termina -> cancelando '{child.name}'")
                    child.cancel_event.set()
                    child.thread.join(timeout=1)
            root_region.release(self.traza)
        if panic is not None:
            raise panic
        return result

    # ---- fn de SCAR como callback de una extern "C" fn ----
    def _ffi_cb_estado(self):
        """Estado por hilo de la llamada extern en curso: el panic que haya
        ocurrido adentro de un callback (None si ninguno)."""
        estado = getattr(self._local, "ffi_cb", None)
        if estado is None:
            estado = self._local.ffi_cb = _FfiCbEstado()
        return estado

    def _ffi_trampolin(self, fv, ann, cfunctype):
        if not isinstance(fv, FnValue):
            raise ScarRuntimeError(f"extern: se esperaba una fn como callback, se dio {fv!r}")
        cache = self.__dict__.setdefault("_ffi_trampolines", {})
        key = (fv.name, tuple(repr(t) for t in ann.args))
        if key in cache:
            return cache[key][0]
        params, ret = ann.args[:-1], ann.args[-1]

        def py_cb(*c_args):
            estado = self._ffi_cb_estado()
            if estado.error is not None:
                # Ya hubo un panic en esta llamada extern: en el nativo el
                # proceso (o la task) ya no vuelve a ejecutar código SCAR.
                return _CB_DEFAULT[ret.name]
            _flush_c_stdio()
            args = [
                ctypes.string_at(a).decode("utf-8", errors="replace")
                if t.name == "str" and a is not None else
                ("" if t.name == "str" else a)
                for a, t in zip(c_args, params)
            ]
            try:
                r = self.call_function(fv.name, args)
            except BaseException as e:  # panic/cancelación: se re-lanza al volver de C
                estado.error = e
                return _CB_DEFAULT[ret.name]
            finally:
                sys.stdout.flush()
            return r

        tramp = cfunctype(py_cb)
        cache[key] = (tramp,)
        return tramp

    # ---- llamada de función/tarea (misma lógica; task añade thread+región) ----
    def call_function(self, name, arg_values):
        decl = self.functions.get(name)
        if decl is None:
            raise ScarRuntimeError(f"función no definida: {name}")
        env = Environment()
        for param, val in zip(decl.params, arg_values):
            env.define(param.name, val)
        try:
            self.exec_block(decl.body, env)
        except ReturnSignal as r:
            return r.value
        except PropagateErr as p:
            return Err(p.err_value)
        return None

    def spawn_task(self, name, arg_values):
        decl = self.functions.get(name)
        if decl is None:
            raise ScarRuntimeError(f"tarea no definida: {name}")

        parent_ctx = self.ctx
        region = Region(name)
        cancel_event = threading.Event()
        handle = TaskHandle(name, None, cancel_event, region, accepted_types=decl.accepts)
        child_ctx = TaskContext(name, region, cancel_event, parent=parent_ctx)
        # La propia task necesita encontrar su TaskHandle desde
        # adentro (accept_chan() corre en su thread, ver comentario en
        # TaskContext) -- se conecta acá, antes de arrancar el thread, para
        # que esté listo desde el primer statement del cuerpo.
        child_ctx.own_handle = handle

        def run():
            self.ctx = child_ctx
            env = Environment()
            for param, val in zip(decl.params, arg_values):
                env.define(param.name, val)
            self.traza(f"[tarea] iniciando '{name}' (región propia)")
            result = None
            try:
                self.exec_block(decl.body, env)
            except ReturnSignal as r:
                result = r.value
            except PropagateErr as p:
                result = Err(p.err_value)
            except CancelledError:
                self.traza(f"[tarea] '{name}' cancelada")
                result = Err("cancelada")
                handle.cancelled_before_complete = True
            except ScarPanic as p:
                # Esto llegó de un join() sobre una hija que panickeó: el panic se
                # vuelve nuestro también, y sigue subiendo la cadena tarea por tarea.
                p.task_chain.append(name)
                hija = p.task_chain[-2]
                self.aviso(f"[PANIC] la tarea '{name}' murió porque su hija '{hija}' "
                           f"panickeó: {p.message}")
                self._cancel_siblings(parent_ctx, handle)
                handle.panic = p
            except Exception as e:
                # Un panic real y propio de esta tarea (no un Err() manejable): se
                # loguea con mensaje claro, nunca un traceback crudo de Python.
                msg = format_panic_message(e)
                self.aviso(f"[PANIC] la tarea '{name}' murió: {msg}")
                panic = ScarPanic(msg, task_chain=[name])
                self._cancel_siblings(parent_ctx, handle)
                handle.panic = panic
            finally:
                # Concurrencia estructurada: si esta tarea termina y aún tiene
                # hijos sin `join()`, se cancelan en cascada antes de liberar la región.
                for child in child_ctx.children:
                    if child.thread.is_alive():
                        self.traza(f"[cascada] '{name}' termina sin join() de '{child.name}' -> cancelando")
                        child.cancel_event.set()
                        child.thread.join(timeout=1)
                region.release(self.traza)
            handle.result = result

        # daemon=True: un thread verdaderamente huérfano (ej. bloqueado para siempre
        # en un recv() sin nadie que lo cancele) no puede retener al proceso entero
        # como rehén cuando el programa decide terminar.
        def run_contado():
            try:
                run()
            finally:
                _hilos_sumar("vivos", -1)  # Una tarea menos que puede mover algo

        t = threading.Thread(target=run_contado, name=name, daemon=True)
        handle.thread = t
        parent_ctx.children.append(handle)
        _hilos_sumar("vivos", 1)
        try:
            t.start()
        except BaseException:
            _hilos_sumar("vivos", -1)
            raise
        return handle

    # ---- ejecución de statements ----
    def exec_block(self, block: Block, env: Environment):
        # Punto de cancelación único por entrada de bloque (no por statement).
        # Un bloque se re-entra exactamente en los lugares donde el trabajo puede
        # volverse no acotado: cada iteración de un loop (el cuerpo es un bloque),
        # cada llamada a función/tarea (el cuerpo es un bloque), cada rama de un
        # `if` que se toma. Código lineal sin loops ni llamadas es acotado por
        # construcción y no necesita revisión intermedia. Esto es exactamente lo
        # que un compilador real insertaría como "safepoint": en el back-edge de
        # cada loop y en el prólogo de cada función, no en cada instrucción — es
        # el mismo patrón que usan los safepoints de GC en JVM/Go, y evita el
        # costo de revisar una bandera en cada statement una vez que esto compile
        # a código nativo en vez de interpretarse.
        _PROGRESO[0] += 1
        self.cancel_check()
        for stmt in block.stmts:
            self.exec_stmt(stmt, env)

    def exec_stmt(self, stmt, env: Environment):
        handler = self._STMT_DISPATCH.get(type(stmt))
        if handler is None:
            raise ScarRuntimeError(f"statement no soportado: {type(stmt).__name__}")
        handler(self, stmt, env)

    def _exec_LetStmt(self, stmt, env: Environment):
        if (
            isinstance(stmt.expr, Call)
            and isinstance(stmt.expr.callee, Ident)
            and stmt.expr.callee.name == "accept_chan"
        ):
            # accept_chan() no tiene de dónde sacar su T salvo la anotación
            # de ESTE 'let' -- mismo criterio que type_checker.py (ver el
            # branch dedicado en _check_stmt/LetStmt ahí); además esa T decide de
            # cuál slot (uno por tipo aceptado) se drena, ver _accept_chan.
            # stmt.declared_type es Option<Chan<T>>; .args[0] es Chan<T>,
            # que es la clave que usa TaskHandle.injected_slots.
            expected_ty = stmt.declared_type.args[0]
            value = self._accept_chan(expected_ty)
        else:
            value = self.eval(stmt.expr, env)
        # 'let z: f64 = 5; let m = z / 2' da 2.5: el intérprete es dinámico
        # y, sin esto, una anotación 'f64' sobre un valor que evalúa a un
        # int de Python (literal i32, u otro entero) dejaría 'z' guardado
        # como int -- _scar_div/_scar_mod deciden
        # truncar o no SOLO mirando el tipo runtime de Python, no lo que
        # type_checker.py ya validó y promovió (mismo criterio que ese
        # checker: i32 -> f64 es una promoción válida en un 'let'
        # anotado). 'bool' es subclase de 'int' en Python -- excluido a
        # propósito, un 'let x: f64 = true' ya es un error de tipo que
        # type_checker.py rechaza antes de llegar acá.
        if (
            stmt.declared_type is not None
            and stmt.declared_type.name == "f64"
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            value = float(value)
        env.define(stmt.name, value)

    def _exec_ReturnStmt(self, stmt, env: Environment):
        value = self.eval(stmt.expr, env) if stmt.expr is not None else None
        raise ReturnSignal(value)

    def _exec_BreakStmt(self, stmt, env: Environment):
        raise BreakSignal()

    def _exec_ExprStmt(self, stmt, env: Environment):
        self.eval(stmt.expr, env)

    def _exec_AssignStmt(self, stmt, env: Environment):
        value = self.eval(stmt.expr, env)
        if isinstance(stmt.target, Ident):
            env.set(stmt.target.name, value)
        elif isinstance(stmt.target, FieldAccess):
            obj = self.eval(stmt.target.obj, env)
            obj.fields[stmt.target.field] = value
        else:
            raise ScarRuntimeError("destino de asignación inválido")

    def _exec_IfStmt(self, stmt, env: Environment):
        if truthy(self.eval(stmt.cond, env)):
            self.exec_block(stmt.then_block, Environment(env))
        elif stmt.else_block is not None:
            self.exec_block(stmt.else_block, Environment(env))

    def _exec_WhileStmt(self, stmt, env: Environment):
        while truthy(self.eval(stmt.cond, env)):
            # exec_block() revisa cancelación al entrar; no hace falta
            # duplicarlo acá (ver comentario en exec_block).
            try:
                self.exec_block(stmt.body, Environment(env))
            except BreakSignal:
                break

    def _exec_WhileLetStmt(self, stmt, env: Environment):
        while True:
            val = self.eval(stmt.expr, env)
            # el match sobre un Result se baja a un while let Ok(x)
            if isinstance(val, Ok if getattr(stmt, "patron", "Some") == "Ok" else SomeVal):
                inner_env = Environment(env)
                # Si el cuerpo mueve un Vec/Map prestado, una copia
                # (lo marca el checker; el nativo hace lo mismo)
                dato = scar_copy_value(val.value) if getattr(stmt, "copia_ligada", False) else val.value
                inner_env.define(stmt.pattern, dato)
                try:
                    self.exec_block(stmt.body, inner_env)
                except BreakSignal:
                    break
            else:
                break

    def _exec_ForStmt(self, stmt, env: Environment):
        start = self.eval(stmt.start, env)
        end = self.eval(stmt.end, env)
        es_i64 = getattr(stmt, "tipo_var", "i32") == "i64"
        for i in range(start, end):
            inner_env = Environment(env)
            inner_env.define(stmt.var, I64(i) if es_i64 else i)
            try:
                self.exec_block(stmt.body, inner_env)
            except BreakSignal:
                break

    # ---- evaluación de expresiones ----
    def eval(self, expr, env: Environment):
        handler = self._EVAL_DISPATCH.get(type(expr))
        if handler is None:
            raise ScarRuntimeError(f"expresión no soportada: {type(expr).__name__}")
        if expr.promover_f64:
            # i32 donde se espera f64 (ver Node.promover_f64), igual
            # que la conversión implícita de C en el nativo.
            return float(handler(self, expr, env))
        if expr.promover_i64:
            # i32 donde se espera i64 (ver Node.promover_i64).
            return I64(handler(self, expr, env))
        return handler(self, expr, env)

    def _eval_NumLit(self, expr, env: Environment):
        if expr.tipo_int == "i64":
            return I64(expr.value)
        return expr.value

    def _eval_StrLit(self, expr, env: Environment):
        return expr.value

    def _eval_BoolLit(self, expr, env: Environment):
        return expr.value

    def _eval_Ident(self, expr, env: Environment):
        _missing = _MISSING
        value = env.lookup(expr.name, _missing)
        if value is not _missing:
            if value is _MOVIDA:
                # solo llega acá un uso que el checker marcó
                raise ScarPanic(mensaje_movida(expr.name))
            if expr.registra_mov:
                env.set(expr.name, _MOVIDA)
            return value
        # Una fn top-level referenciada por nombre, sin paréntesis, es
        # un valor función. El checker ya validó que el nombre existe y que
        # el tipo encaja; acá solo se materializa el valor.
        if expr.name in self.functions:
            return FnValue(expr.name)
        return env.get(expr.name)  # mismo error de siempre si no existe

    def _eval_NoneExpr(self, expr, env: Environment):
        return NoneVal()

    def _eval_SomeExpr(self, expr, env: Environment):
        return SomeVal(self.eval(expr.expr, env))

    def _eval_OkExpr(self, expr, env: Environment):
        return Ok(self.eval(expr.expr, env))

    def _eval_ErrExpr(self, expr, env: Environment):
        return Err(self.eval(expr.expr, env))

    def _eval_UnaryOp(self, expr, env: Environment):
        if expr.literal_plegado is not None:
            # `-N` con N literal es un literal negativo con su tipo.
            v = expr.literal_plegado
            return I64(v) if expr.tipo_int == "i64" else v
        v = self.eval(expr.expr, env)
        if expr.op == "-":
            if _es_i32(v):
                kind = expr.tipo_int or _tipo_entero(v)
                if -v < (I64_MIN if kind == "i64" else I32_MIN) or -v > (I64_MAX if kind == "i64" else I32_MAX):
                    raise ScarRuntimeError(f"desbordamiento de {kind}: 0 - {v}")
                return I64(-v) if kind == "i64" else -v
            return -v
        if expr.op == "not":
            return not truthy(v)
        # Mismo comportamiento que la cadena de isinstance original: un
        # operador unario no reconocido no tiene otra rama que lo capture,
        # así que cae al mismo error genérico que antes.
        raise ScarRuntimeError(f"expresión no soportada: {type(expr).__name__}")

    def _eval_BinOp(self, expr, env: Environment):
        if expr.op == "and":
            return truthy(self.eval(expr.left, env)) and truthy(self.eval(expr.right, env))
        if expr.op == "or":
            return truthy(self.eval(expr.left, env)) or truthy(self.eval(expr.right, env))
        l = self.eval(expr.left, env)
        r = self.eval(expr.right, env)
        return apply_binop(expr.op, l, r, expr.tipo_int)

    def _eval_TryExpr(self, expr, env: Environment):
        val = self.eval(expr.expr, env)
        if isinstance(val, Ok):
            return val.value
        if isinstance(val, Err):
            raise PropagateErr(val.value)
        raise ScarRuntimeError("operador ? usado sobre un valor que no es Result")

    def _eval_ArrayLit(self, expr, env: Environment):
        # [a, b, c]: vec_new() + un push por elemento, en orden (los
        # elementos que hay que ampliar ya traen promover_f64/_i64).
        v = ScarVec(len(expr.elems))
        for e in expr.elems:
            v.push(self.eval(e, env))
        return v

    def _eval_StructLit(self, expr, env: Environment):
        fields = {k: self.eval(v, env) for k, v in expr.fields.items()}
        decl = self.structs.get(expr.name)
        return StructInstance(expr.name, fields, getattr(decl, "enum_variantes", None))

    def _eval_FieldAccess(self, expr, env: Environment):
        obj = self.eval(expr.obj, env)
        if isinstance(obj, StructInstance):
            return obj.fields[expr.field]
        raise ScarRuntimeError(f"acceso a campo inválido: {expr.field}")

    def _eval_IndexExpr(self, expr, env: Environment):
        # El checker ya garantiza obj: str e índice: i32 en
        # programas que pasan type-check -- lo que queda para runtime es
        # justo lo que el checker NO puede saber en tiempo de compilación:
        # si el índice cae dentro del rango real de este str en particular.
        # Fuera de rango es panic (ver docstring de IndexExpr en parser.py:
        # misma familia que un acceso a campo inexistente, no un caso
        # "esperable" que el programa deba manejar con Option/Result).
        obj = self.eval(expr.obj, env)
        idx = self.eval(expr.index, env)
        if not isinstance(obj, str):
            raise ScarRuntimeError(f"indexado inválido: se esperaba str, se dio {type(obj).__name__}")
        if idx < 0 or idx >= len(obj):
            raise ScarRuntimeError(
                f"índice fuera de rango: {idx} (longitud {len(obj)})"
            )
        return obj[idx]

    def _eval_SpawnExpr(self, expr, env: Environment):
        call = expr.call
        if not isinstance(call, Call) or not isinstance(call.callee, Ident):
            raise ScarRuntimeError("spawn requiere una llamada a función tipo task")
        arg_values = [self.eval(a, env) for a in call.args]
        return self.spawn_task(call.callee.name, arg_values)

    def _eval_PrintExpr(self, expr, env: Environment):
        # Cada argumento se pasa a texto apenas se evalúa (lo encontró
        # el fuzzer): en `print(w, f(w))` con f que se queda con el Vec w y le
        # agrega cosas, el intérprete mostraba w DESPUÉS de f (es la misma lista
        # de Python). El valor de w es el del momento en que se lee, que es lo
        # que imprime el nativo (punto 8).
        textos = [scar_str(self.eval(a, env)) for a in expr.args]
        if getattr(expr, "a_stderr", False):
            # el error de un main -> Result (ver enum_match.bajar_main_result)
            sys.stdout.flush()
            print(" ".join(textos), file=sys.stderr, flush=True)
            return None
        self.log(" ".join(textos))
        return None

    def _eval_Call(self, expr, env: Environment):
        if isinstance(expr.callee, Ident):
            fname = expr.callee.name
            arg_values = [self.eval(a, env) for a in expr.args]
            if fname == "sleep":
                self._interruptible_sleep(arg_values[0])
                return None
            if fname == "panic":
                # El mismo camino que un panic de runtime (división
                # por cero, índice fuera de rango): termina la tarea y sigue
                # en cascada.
                raise ScarRuntimeError(arg_values[0])
            if fname == "read_pipe":
                return self._interruptible_read_pipe(arg_values[0])
            if fname == "inject_chan":
                return self._inject_chan(arg_values[0], arg_values[1], expr.chan_ty)
            if fname == "accept_chan":
                # No debería poder llegar acá sin pasar por el camino
                # especial de _exec_LetStmt (ver ahí) -- type_checker.py
                # rechaza en compilación cualquier otro sitio donde
                # aparezca 'accept_chan()' (ver el 'accept_chan() solo
                # puede usarse como...' en type_checker.py). Si esto se
                # dispara, es un programa que compiló limpio pero rompió
                # esa invariante -- mejor un error claro que adivinar un T.
                raise ScarRuntimeError(
                    "accept_chan() solo puede evaluarse como la expresión "
                    "de un 'let' anotado (bug del checker si esto se ve)"
                )
            if fname == "rand":
                return self.ctx.rand.next()
            if fname == "seed":
                self.ctx.rand.init(arg_values[0])
                return None
            if fname == "arg":
                return self._builtin_arg(arg_values[0])
            if fname in ("abs", "min", "max"):
                return _abs_min_max(fname, arg_values, expr.tipo_int)
            if fname in BUILTINS:
                return BUILTINS[fname](*arg_values)
            if fname in self.extern_functions:
                return self.extern_functions[fname](*arg_values)
            # Llamada a través de una variable/parámetro que guarda un
            # valor función ('return f(x)' con 'f: fn(i32) -> i32'). Se
            # consulta antes que self.functions para respetar el shadowing
            # (un parámetro 'f' tapa a una fn top-level 'f', igual que en
            # el checker y en el C generado).
            local = env.lookup(fname, _MISSING)
            if isinstance(local, FnValue):
                return self.call_function(local.name, arg_values)
            if fname in self.functions:
                return self.call_function(fname, arg_values)
        raise ScarRuntimeError(f"llamada inválida a {expr.callee}")

    def _eval_MethodCall(self, expr, env: Environment):
        obj = self.eval(expr.obj, env)
        arg_values = [self.eval(a, env) for a in expr.args]
        return self.call_method(obj, expr.method, arg_values)

    # Tablas de despacho por tipo de nodo AST, construidas una sola vez a
    # nivel de clase (no de instancia) apenas termina de definirse la clase
    # más abajo -- ver el bloque _STMT_DISPATCH/_EVAL_DISPATCH después de
    # `class Interpreter`. Un dict por tipo de nodo en vez de una cadena de
    # `isinstance`: el costo de despacho es O(1) por nodo evaluado, no
    # O(posición en la cadena) (con cProfile, la cadena de isinstance se
    # llevaba buena parte del tiempo de eval()).

    def _interruptible_sleep(self, seconds, step=0.02):
        end = time.time() + seconds
        while time.time() < end:
            _PROGRESO[0] += 1  # dormir es avanzar: termina solo
            self.cancel_check()
            remaining = max(0, end - time.time())
            # Mismo jitter que ScarChan.recv (ver ese comentario): con 1000
            # sensores durmiendo con el mismo step, sin jitter se despiertan
            # todos casi en el mismo tick y contienden el GIL en manada.
            jittered_step = step * random.uniform(0.7, 1.3)
            time.sleep(min(jittered_step, remaining))

    def _interruptible_read_pipe(self, fd, timeout=None, step=0.02):
        """Lee de un file descriptor (pipe) de forma bloqueante-pero-cancelable.

        Igual que sleep, necesita el contexto de la tarea actual (self.ctx) para
        poder revisar cancelación en pasos cortos en vez de bloquearse ciego en un
        read() real del sistema operativo — por eso es un builtin especial acá y
        no una entrada de BUILTINS (esas no tienen acceso al intérprete).

        Devuelve Ok(str) con lo leído, o Err("EOF") si el otro extremo cerró el
        pipe sin escribir nada. Si nadie escribe y nadie cancela, dispara
        ScarIOTimeout (ver su docstring: a propósito NO es un ScarPanic, y a
        propósito el timeout es menor que el de join()).
        """
        if not _fd_del_programa(fd):
            # Un fd que el programa no heredó ni abrió puede estar ocupado por
            # el propio intérprete (libffi, un .pyc): leerlo sería leer algo
            # ajeno. Para el programa ese fd no existe, como en el nativo.
            raise ScarRuntimeError(
                f"read_pipe: el fd={fd} no está abierto (no se heredó al "
                f"arrancar ni viene de pipe_new())"
            )
        wait = timeout if timeout is not None else _read_io_timeout_env()
        end = time.time() + wait
        while True:
            self.cancel_check()
            remaining = end - time.time()
            if remaining <= 0:
                raise ScarIOTimeout(
                    f"read_pipe: timeout de I/O ({wait}s) sin datos en fd={fd}"
                )
            ready, _, _ = select.select([fd], [], [], min(step, remaining))
            if ready:
                data = os.read(fd, 4096)
                if not data:
                    return Err("EOF")
                return Ok(data.decode("utf-8", errors="replace"))

    def _interruptible_socket_read(self, sock, timeout=None, step=0.02):
        """Lee de un socket TCP de forma bloqueante-pero-cancelable. Mismo
        mecanismo exacto que _interruptible_read_pipe (select() en pasos
        cortos revisando cancel_check() entre medio), adaptado a un socket
        en vez de un fd de pipe: usa sock.fileno() para select() y
        sock.recv() en vez de os.read() (equivalentes sobre un fd real de
        Linux, pero recv() es la API correcta para un socket)."""
        wait = timeout if timeout is not None else _read_io_timeout_env()
        end = time.time() + wait
        while True:
            self.cancel_check()
            remaining = end - time.time()
            if remaining <= 0:
                raise ScarIOTimeout(
                    f"socket.read: timeout de I/O ({wait}s) sin datos"
                )
            ready, _, _ = select.select([sock.fileno()], [], [], min(step, remaining))
            if ready:
                try:
                    data = sock.recv(4096)
                except OSError as e:
                    return Err(f"error de lectura: {e.strerror or str(e)}")
                if not data:
                    return Err("EOF")
                return Ok(data.decode("utf-8", errors="replace"))

    def _interruptible_socket_read_bytes(self, sock, n, step=0.02):
        """EXACTAMENTE n bytes crudos (0..255) en un
        Vec<i32> -- lo que necesita un protocolo binario (un registro SeedLink
        mide 520). Err("EOF") si la otra punta cierra antes; Err("timeout") si
        pasa el timeout de I/O sin ningún byte nuevo (a diferencia de .read(),
        que hace panic: un programa que corre 24/7 tiene que poder
        reconectarse). Mismo contrato que scar_socket_read_bytes."""
        if n < 0:
            raise ScarRuntimeError(f"read_bytes: cantidad negativa ({n})")
        wait = _read_io_timeout_env()
        out = bytearray()
        end = time.time() + wait
        while len(out) < n:
            self.cancel_check()
            remaining = end - time.time()
            if remaining <= 0:
                return Err("timeout")
            ready, _, _ = select.select([sock.fileno()], [], [], min(step, remaining))
            if ready:
                try:
                    data = sock.recv(n - len(out))
                except OSError as e:
                    return Err(f"error de lectura: {e.strerror or str(e)}")
                if not data:
                    return Err("EOF")
                out += data
                end = time.time() + wait  # el timeout cuenta desde el último byte
        v = ScarVec(n)
        v.items = list(out)
        return Ok(v)

    def _interruptible_accept(self, listener_sock, timeout=None, step=0.02):
        """Espera una conexión entrante de forma bloqueante-pero-cancelable.
        Mismo mecanismo que _interruptible_socket_read/_interruptible_read_pipe,
        aplicado a accept() en vez de a una lectura."""
        wait = timeout if timeout is not None else _read_io_timeout_env()
        end = time.time() + wait
        while True:
            self.cancel_check()
            remaining = end - time.time()
            if remaining <= 0:
                raise ScarIOTimeout(
                    f"listener.accept: timeout de I/O ({wait}s) sin conexión entrante"
                )
            ready, _, _ = select.select([listener_sock.fileno()], [], [], min(step, remaining))
            if ready:
                try:
                    conn, _addr = listener_sock.accept()
                except OSError as e:
                    return Err(f"error de accept: {e.strerror or str(e)}")
                return Ok(ScarSocket(conn))

    def call_method(self, obj, method, args):
        if isinstance(obj, TaskHandle):
            if method == "join":
                return self.join_task(obj)
        if isinstance(obj, ScarChan):
            if method == "send":
                obj.send(args[0], self.ctx.cancel_event)
                return None
            if method == "recv":
                return obj.recv(self.ctx.cancel_event)
            if method == "try_recv":
                return obj.try_recv()
            if method == "close":
                obj.close()
                return None
            if method == "sender":
                return obj.sender()
            if method == "receiver":
                return obj.receiver()
        if isinstance(obj, ScarPipe):
            if method == "read_fd":
                return obj.read_fd
            if method == "write_fd":
                return obj.write_fd
        if isinstance(obj, ScarFile):
            if method == "read_all":
                return obj.read_all()
            if method == "read_bytes":
                return obj.read_bytes(args[0])
            if method == "write":
                return obj.write(args[0])
            if method == "write_bytes":
                return obj.write_bytes(args[0])
            if method == "close":
                obj.close()
                return None
        if isinstance(obj, ScarSocket):
            if method == "read":
                if obj.cerrado:
                    return Err("socket cerrado")
                return self._interruptible_socket_read(obj.sock)
            if method == "read_bytes":
                if args[0] < 0:
                    raise ScarRuntimeError(f"read_bytes: cantidad negativa ({args[0]})")
                if obj.cerrado:
                    return Err("socket cerrado")
                return self._interruptible_socket_read_bytes(obj.sock, args[0])
            if method == "write":
                return obj.write(args[0])
            if method == "write_bytes":
                return obj.write_bytes(args[0])
            if method == "close":
                obj.close()
                return None
        if isinstance(obj, (Ok, Err, SomeVal, NoneVal)):
            # ver type_checker._metodo_result_option
            if method in ("is_ok", "is_some"):
                return isinstance(obj, (Ok, SomeVal))
            if method in ("is_err", "is_none"):
                return isinstance(obj, (Err, NoneVal))
            if method == "err":
                return obj.value if isinstance(obj, Err) else ""
            if method == "unwrap_or":
                return obj.value if isinstance(obj, (Ok, SomeVal)) else args[0]
        if isinstance(obj, ScarListener):
            if method == "accept":
                if obj.cerrado:
                    return Err("listener cerrado")
                return self._interruptible_accept(obj.sock)
            if method == "close":
                obj.close()
                return None
        if isinstance(obj, ScarVec):
            if method == "push":
                obj.push(args[0])
                return None
            if method == "get":
                return obj.get(args[0])
            if method == "pop":
                return obj.pop()
            if method == "set":
                obj.set(args[0], args[1])
                return None
            if method == "replace":
                return obj.replace(args[0], args[1])
            if method == "len":
                return len(obj)
        if isinstance(obj, ScarMap):
            if method == "set":
                obj.set(args[0], args[1])
                return None
            if method == "get":
                return obj.get(args[0])
            if method == "remove":
                return obj.remove(args[0])
            if method == "len":
                return len(obj)
        if isinstance(obj, str):
            if method == "len":
                return len(obj)
            if method == "contains":
                return args[0] in obj
            if method == "starts_with":
                return obj.startswith(args[0])
            if method == "ends_with":
                return obj.endswith(args[0])
        raise ScarRuntimeError(f"método no soportado: .{method}() sobre {type(obj).__name__}")


# Tablas de despacho por tipo de nodo AST (ver comentario en Interpreter.eval).
# Se construyen acá, una sola vez a nivel de módulo, mapeando cada clase de
# nodo del AST a su método _exec_<Tipo>/_eval_<Tipo> correspondiente.
Interpreter._STMT_DISPATCH = {
    LetStmt: Interpreter._exec_LetStmt,
    ReturnStmt: Interpreter._exec_ReturnStmt,
    BreakStmt: Interpreter._exec_BreakStmt,
    ExprStmt: Interpreter._exec_ExprStmt,
    AssignStmt: Interpreter._exec_AssignStmt,
    IfStmt: Interpreter._exec_IfStmt,
    WhileStmt: Interpreter._exec_WhileStmt,
    WhileLetStmt: Interpreter._exec_WhileLetStmt,
    ForStmt: Interpreter._exec_ForStmt,
}

Interpreter._EVAL_DISPATCH = {
    NumLit: Interpreter._eval_NumLit,
    StrLit: Interpreter._eval_StrLit,
    BoolLit: Interpreter._eval_BoolLit,
    Ident: Interpreter._eval_Ident,
    NoneExpr: Interpreter._eval_NoneExpr,
    SomeExpr: Interpreter._eval_SomeExpr,
    OkExpr: Interpreter._eval_OkExpr,
    ErrExpr: Interpreter._eval_ErrExpr,
    UnaryOp: Interpreter._eval_UnaryOp,
    BinOp: Interpreter._eval_BinOp,
    TryExpr: Interpreter._eval_TryExpr,
    StructLit: Interpreter._eval_StructLit,
    ArrayLit: Interpreter._eval_ArrayLit,
    FieldAccess: Interpreter._eval_FieldAccess,
    IndexExpr: Interpreter._eval_IndexExpr,
    SpawnExpr: Interpreter._eval_SpawnExpr,
    PrintExpr: Interpreter._eval_PrintExpr,
    Call: Interpreter._eval_Call,
    MethodCall: Interpreter._eval_MethodCall,
}


# ---------------- utilidades ----------------

def truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return bool(v)


I32_MIN = -(2 ** 31)
I32_MAX = 2 ** 31 - 1
I64_MIN = -(2 ** 63)
I64_MAX = 2 ** 63 - 1


class I64(int):
    """Un entero de SCAR de tipo i64. Es un int de Python (se imprime,
    se compara y sirve de clave igual), pero lleva su tipo: una cuenta en la
    que entra un I64 desborda con el rango de i64 y da otro I64. Un int pelado
    es un i32."""
    __slots__ = ()


_ffi_worker_mod._VEC_CONV["vec_i64"] = I64  # un i64 que vuelve de C


def _tipo_entero(v):
    return "i64" if isinstance(v, I64) else "i32"


def _entero(kind, v, l, op, r):
    """El resultado `v` de `l op r` como entero de tipo `kind`, con el panic
    de desborde de ese tipo (mismo texto que el nativo)."""
    lo, hi = (I64_MIN, I64_MAX) if kind == "i64" else (I32_MIN, I32_MAX)
    if v < lo or v > hi:
        raise ScarRuntimeError(f"desbordamiento de {kind}: {l} {op} {r}")
    return I64(v) if kind == "i64" else int(v)


def _es_i32(v):
    # bool es subclase de int en Python, pero nunca es un i32 de SCAR.
    return isinstance(v, int) and not isinstance(v, bool)


def _check_i32(resultado, l, op, r):
    """El overflow de i32 es panic, igual que en el backend de C
    (scar_iadd/scar_isub/scar_imul/scar_ineg/scar_idiv en codegen/).
    Antes el intérprete usaba los enteros sin límite de Python y nunca
    desbordaba, mientras el nativo hacía overflow con signo (UB en C)."""
    if resultado < I32_MIN or resultado > I32_MAX:
        raise ScarRuntimeError(f"desbordamiento de i32: {l} {op} {r}")
    return resultado


def _a_i64(x):
    """Los 64 bits bajos de x, leídos en complemento a dos (como un int64_t)."""
    x &= 0xFFFFFFFFFFFFFFFF
    return x - 0x10000000000000000 if x & 0x8000000000000000 else x


def _a_i32(x):
    """Los 32 bits bajos de x, leídos en complemento a dos (como un int32_t)."""
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


def _bits(op, l, r, kind=None):
    """Operadores de bits sobre enteros (i32 e i64), con
    la misma semántica que el nativo (codegen: scar_shl/scar_shr). & | ^ ya
    caen en rango. Un corrimiento fuera de 0..31 (0..63 en i64) es un panic
    (en C sería comportamiento indefinido); `<<` descarta los bits que salen
    por arriba (puede cambiar el signo) y `>>` es aritmético (propaga el
    signo), como en Rust. `kind` es el tipo del resultado (el de la izquierda
    en un corrimiento); sin anotar, lo dice el valor."""
    if kind is None:
        if op in ("<<", ">>"):
            kind = _tipo_entero(l)
        else:
            kind = "i64" if "i64" in (_tipo_entero(l), _tipo_entero(r)) else "i32"
    envolver = I64 if kind == "i64" else int
    if op == "&": return envolver(l & r)
    if op == "|": return envolver(l | r)
    if op == "^": return envolver(l ^ r)
    bits = 64 if kind == "i64" else 32
    if not 0 <= r < bits:
        raise ScarRuntimeError(f"corrimiento fuera de rango ({l} {op} {r})")
    if op == "<<": return envolver(_a_i64(l << r) if kind == "i64" else _a_i32(l << r))
    return envolver(l >> r)


def apply_binop(op, l, r, kind=None):
    """`kind`: el tipo entero de la cuenta que anotó el checker ("i32"/"i64");
    sin anotar (el cuerpo de una fn genérica), lo dicen los valores."""
    if op in ("&", "|", "^", "<<", ">>"):
        return _bits(op, l, r, kind)
    if op in ("+", "-", "*", "/", "%") and _es_i32(l) and _es_i32(r):
        if kind is None:
            kind = "i64" if "i64" in (_tipo_entero(l), _tipo_entero(r)) else "i32"
        if op == "+": return _entero(kind, l + r, l, op, r)
        if op == "-": return _entero(kind, l - r, l, op, r)
        if op == "*": return _entero(kind, l * r, l, op, r)
        if op == "/": return _entero(kind, _scar_div(l, r), l, op, r)
        return _entero(kind, _scar_mod(l, r), l, op, r)
    if op == "+": return l + r
    if op == "-": return l - r
    if op == "*": return l * r
    if op == "/": return _scar_div(l, r)
    if op == "%": return _scar_mod(l, r)
    if op == "==": return l == r
    if op == "!=": return l != r
    if op == "<": return l < r
    if op == ">": return l > r
    if op == "<=": return l <= r
    if op == ">=": return l >= r
    raise ScarRuntimeError(f"operador no soportado: {op}")


def _scar_div(l, r):
    """'/' entre dos i32 (Python int) trunca hacia cero, como en C — coincide
    con lo que type_checker.py ya promete (i32 / i32 -> i32). Antes de esto,
    el intérprete usaba división de Python (siempre float) sin que ningún
    ejemplo lo ejerciera: 10 / 3 devolvía 3.3333333333333335 en vez de 3, una
    divergencia real entre el tipo que el checker anuncia y lo que el runtime
    entrega. Si cualquiera de los dos lados es f64 (Python float), la
    división sigue siendo real, sin truncar."""
    if isinstance(l, int) and isinstance(r, int):
        if r == 0:
            # Mismo mensaje que scar_idiv en el nativo (antes salía el
            # ZeroDivisionError crudo de Python).
            raise ScarRuntimeError(f"división por cero ({l} / {r})")
        q = l // r
        if q < 0 and l % r != 0:
            q += 1  # floor// redondea hacia -inf; C trunca hacia 0
        return q
    return _f64_div(float(l), float(r))


def _f64_div(l, r):
    """'/' con f64 sigue IEEE 754, igual que C en el nativo: x / 0.0 es ±inf
    y 0.0 / 0.0 es NaN (Python, en cambio, lanza ZeroDivisionError: antes
    eso era un panic en el intérprete y un inf en el nativo)."""
    if r != 0.0:
        return l / r
    if l != l or l == 0.0:
        return math.nan
    return math.copysign(math.inf, l) * math.copysign(1.0, r)


def _scar_mod(l, r):
    """'%' entre dos i32 (Python int): resto de la división truncada hacia
    cero, igual que en C (y que _scar_div de acá arriba). Python's '%'
    nativo sigue el signo del divisor (floor mod), que difiere de C cuando
    los signos de l y r no coinciden -- ej. -7 % 2 da 1 en Python pero -1
    en C. Se deriva del mismo q truncado que ya usa _scar_div, para que
    'l == (l / r) * r + (l % r)' se cumpla igual que en C, sin duplicar la
    lógica de truncamiento en dos lugares con reglas distintas."""
    if isinstance(l, int) and isinstance(r, int):
        if r == 0:
            raise ScarRuntimeError(f"módulo por cero ({l} % {r})")
        return l - _scar_div(l, r) * r
    l, r = float(l), float(r)
    if r == 0.0 or math.isinf(l):
        return math.nan  # fmod() de C; math.fmod de Python lanza ValueError
    return math.fmod(l, r)


def scar_str(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (Ok, Err, SomeVal, StructInstance)):
        return repr(v)
    if isinstance(v, NoneVal):
        return "None"
    if isinstance(v, TaskHandle):
        return f"<task {v.name}>"
    if isinstance(v, (ScarVec, ScarMap)):
        return repr(v)
    return str(v)


# int(s) / int64(s), UNA regla en los dos backends (scar_parse_int en
# el nativo): espacios ASCII opcionales al principio y al final, signo opcional
# y dígitos decimales ASCII. Antes el intérprete usaba int() de Python, que
# acepta " 42 ", "1_000" y dígitos de otros alfabetos ("٣"), y el nativo
# strtol, que no: el mismo programa daba Ok en uno y Err en el otro.
_INT_TEXTO = re.compile(r"[ \t\n\v\f\r]*([+-]?[0-9]+)[ \t\n\v\f\r]*\Z")


def _parse_int(s, kind):
    m = _INT_TEXTO.match(s) if isinstance(s, str) else None
    if m is None:
        return Err(f"no se pudo convertir '{s}' a entero")
    v = int(m.group(1))
    lo, hi = (I64_MIN, I64_MAX) if kind == "i64" else (I32_MIN, I32_MAX)
    if v < lo or v > hi:
        # Devuelve Result, así que fuera de rango es Err (no panic).
        return Err(f"'{s}' esta fuera del rango de {kind}")
    return Ok(I64(v) if kind == "i64" else v)


def _builtin_int(s):
    return _parse_int(s, "i32")


def _builtin_int64(s):
    return _parse_int(s, "i64")


def _builtin_file_open(path, mode):
    if mode not in ("r", "w", "a"):
        return Err(f"mode invalido: '{mode}' (use 'r'/'w'/'a')")
    try:
        handle = open(path, mode, encoding="utf-8")
    except OSError as e:
        return Err(f"no se pudo abrir '{path}': {e.strerror or str(e)}")
    return Ok(ScarFile(handle))


def _builtin_tcp_connect(host, port):
    # connect() en sí (a diferencia de leer luego del socket) NO usa el
    # mecanismo de cancelación cooperativa -- se acota con un timeout de
    # socket normal en su lugar, mismo espíritu que file_open() no siendo
    # cancelable: es una operación que termina sola (conecta, falla, o
    # expira), no una espera potencialmente indefinida por datos externos
    # como sí lo es .read()/.accept() después de establecida la conexión.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(_read_io_timeout_env())
    try:
        s.connect((host, port))
    except OSError as e:
        s.close()
        return Err(f"no se pudo conectar a {host}:{port}: {e.strerror or str(e)}")
    s.settimeout(None)  # de acá en más, .read() controla el bloqueo con select()
    return Ok(ScarSocket(s))


def _builtin_tcp_listen(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
        s.listen(5)
    except OSError as e:
        s.close()
        return Err(f"no se pudo escuchar en el puerto {port}: {e.strerror or str(e)}")
    return Ok(ScarListener(s))


def _libm(f, borde):
    """Una función de math con la semántica de C (la del nativo): donde Python
    lanza ValueError u OverflowError, C devuelve inf/nan. `borde(args)` da ese
    valor."""
    def g(*args):
        args = tuple(float(a) for a in args)
        try:
            return f(*args)
        except (ValueError, OverflowError, ZeroDivisionError):
            return borde(*args)
    return g


def _ln_borde(x):
    if x == 0.0:
        return -math.inf
    return math.nan  # negativo o nan


def _exp_borde(x):
    return math.inf  # solo desborda hacia arriba (hacia abajo da 0.0)


def _pow_borde(b, e):
    # math.pow lanza en: 0 ** negativo (C: ±inf), base negativa con exponente
    # no entero (C: nan) y desborde (C: ±inf)
    if b == 0.0:
        impar = e == math.floor(e) and abs(e) < 2 ** 53 and int(e) % 2 == 1
        return math.copysign(math.inf, b) if impar else math.inf
    if b < 0.0 and e != math.floor(e):
        return math.nan
    grande = math.inf
    if b < 0.0 and e == math.floor(e) and abs(e) < 2 ** 53 and int(e) % 2 == 1:
        grande = -math.inf
    return grande if abs(b) > 1.0 or (abs(b) < 1.0 and e < 0) else 0.0


def _builtin_chr(n):
    if n < 1 or n > 0x10FFFF or 0xD800 <= n <= 0xDFFF:
        raise ScarRuntimeError(f"chr: código inválido ({n})")
    return chr(n)


def _builtin_ord(s):
    if s == "":
        raise ScarRuntimeError("ord: str vacío")
    return ord(s[0])


def _builtin_to_i32(x):
    """to_i32(x): de un f64 trunca hacia cero, igual que scar_to_i32 en el
    nativo; de un entero (también i64) lo deja igual. Lo que no cabe
    en i32 es un panic."""
    if isinstance(x, int):
        if not I32_MIN <= x <= I32_MAX:
            raise ScarRuntimeError(f"to_i32: {x} esta fuera del rango de i32")
        return int(x)
    x = float(x)
    if not (-2147483649.0 < x < 2147483648.0):  # NaN también cae acá
        raise ScarRuntimeError("to_i32: NaN o fuera del rango de i32")
    return int(x)


def _abs_min_max(fname, args, kind):
    """abs/min/max, igual que el nativo. `kind` es el
    tipo entero que anotó el checker (None para f64). abs de un entero es
    exacto, y el del mínimo (que no tiene positivo) es un panic. min/max
    devuelven el primero salvo que el segundo sea menor (mayor): con NaN, el
    primero, como `(b < a) ? b : a` en C."""
    if fname == "abs":
        x = args[0]
        if kind is None:
            return BUILTINS["abs"](x)
        lo, hi = (I64_MIN, I64_MAX) if kind == "i64" else (I32_MIN, I32_MAX)
        if x == lo:
            raise ScarRuntimeError(f"abs: {x} no tiene valor absoluto en {kind}")
        return I64(abs(x)) if kind == "i64" else abs(int(x))
    a, b = args
    r = b if (b < a if fname == "min" else b > a) else a
    if kind == "i64":
        return I64(r)
    return r


def _builtin_to_i64(x):
    """to_i64(x): un entero siempre cabe; un f64 se trunca hacia
    cero, y NaN o fuera de rango es un panic (como scar_to_i64 en el nativo)."""
    if isinstance(x, int):
        return I64(x)
    x = float(x)
    if not (-9223372036854775808.0 <= x < 9223372036854775808.0):
        raise ScarRuntimeError("to_i64: NaN o fuera del rango de i64")
    return I64(int(x))


BUILTINS = {
    # sqrt de un negativo es NaN, como sqrt() de C (math.sqrt lanza ValueError)
    "sqrt": lambda x: math.sqrt(x) if x >= 0 else math.nan,
    "sin": _libm(math.sin, lambda x: math.nan),
    "cos": _libm(math.cos, lambda x: math.nan),
    "tan": _libm(math.tan, lambda x: math.nan),
    "atan": _libm(math.atan, lambda x: math.nan),
    "exp": _libm(math.exp, _exp_borde),
    "ln": _libm(math.log, _ln_borde),
    "log10": _libm(math.log10, _ln_borde),
    "pow": _libm(math.pow, _pow_borde),
    "floor": _libm(lambda x: float(math.floor(x)) if math.isfinite(x) else x, lambda x: x),
    "abs": _libm(math.fabs, lambda x: math.nan),
    # min/max: ver _abs_min_max (no pasan por acá; están para la lista de
    # builtins que comparan los tests)
    "min": lambda a, b: _abs_min_max("min", (a, b), None),
    "max": lambda a, b: _abs_min_max("max", (a, b), None),
    "to_i32": _builtin_to_i32,
    "to_i64": _builtin_to_i64,
    "chr": _builtin_chr,
    "a_texto": lambda v: scar_str(v),  # el mismo texto que print
    "ord": _builtin_ord,
    "to_f64": lambda n: float(n),
    # rand()/seed() van por el generador de la tarea actual (ver
    # _ScarRand y _eval_Call), no por el random global de Python.
    # now(): reloj MONOTÓNICO (no time.time(), que puede saltar hacia atrás
    # con ajustes de NTP/reloj del sistema) -- pensado para restar dos
    # llamadas y medir latencia/duración, no para timestamps absolutos. Mismo
    # criterio que scar_monotonic_now()/CLOCK_MONOTONIC del lado de C, ver
    # scar_now() en codegen/.
    "now": lambda: time.monotonic(),
    "int": _builtin_int,
    "int64": _builtin_int64,
    "len": lambda x: len(x),
    # cap=0 default: cubre 'chan_new()' (aridad 0, de siempre) tal cual
    # 'chan_new(N)' (aridad 1) -- ver ScarChan.__init__ para por
    # qué 'cap' se guarda pero todavía no se aplica.
    "chan_new": lambda cap=0: ScarChan(cap),
    "vec_new": lambda cap=0: ScarVec(cap),
    "map_new": lambda: ScarMap(),
    "pipe_new": lambda: ScarPipe(),
    "file_open": _builtin_file_open,
    "tcp_connect": _builtin_tcp_connect,
    "tcp_listen": _builtin_tcp_listen,
}


# ---------------- FFI vía ctypes ----------------
# Mismo par (params, ret) que ya usan type_checker.py/codegen/ -- acá se
# traduce una vez, al cargar el programa, a un ctypes._FuncPtr con
# argtypes/restype configurados, para que cada llamada después sea un
# invoke directo sin volver a resolver tipos.

CTYPES_MAP = {
    "i32": ctypes.c_int32,
    "i64": ctypes.c_int64,
    "f64": ctypes.c_double,
    "bool": ctypes.c_bool,
    "str": ctypes.c_char_p,
}


def _ctype_for(type_name, extern_types):
    """Tipo de ctypes para un nombre de tipo SCAR en la frontera FFI.
    Generaliza el `CTYPES_MAP[...]` directo de antes
    para que también resuelva un `extern type` declarado por el usuario --
    mismo criterio que `c_type()` en codegen/ (ver su rama nueva para
    `self.extern_types`): un handle opaco es, en runtime, exactamente un
    `void*` sin interpretar, así que `ctypes.c_void_p` es la
    representación correcta (no hace falta un ctypes.Structure ni nada
    más elaborado, igual que en C no hace falta más que el typedef)."""
    if type_name in CTYPES_MAP:
        return CTYPES_MAP[type_name]
    if type_name in extern_types:
        return ctypes.c_void_p
    raise ScarRuntimeError(
        f"extern: tipo {type_name!r} no soportado en runtime (ni en "
        f"CTYPES_MAP ni declarado con 'extern type')"
    )


# ---- una fn de SCAR como callback de una extern "C" fn ----
# Mismo corte que el nativo (_fn_c_type en codegen/): parámetros
# primitivos (i32/f64/bool/str) y retorno i32/f64/bool/void. El nativo pasa el puntero a
# la función C; acá se pasa un trampolín de ctypes (CFUNCTYPE) que vuelve
# a entrar al intérprete. Un trampolín por (fn, firma), cacheado y vivo
# por el resto del proceso: igual que el puntero del nativo, C puede
# guardarlo y llamarlo más tarde (ej. on_click de scarsdl).

_CB_CTYPES = {
    "i32": ctypes.c_int32,
    "i64": ctypes.c_int64,  # El checker y el binario ya lo aceptaban
    "f64": ctypes.c_double,
    "bool": ctypes.c_bool,
    # str de C a SCAR: char* prestado durante la llamada. Un callback que
    # devuelva str lo rechaza el checker (C no podría liberarlo).
    "str": ctypes.c_void_p,
}
_CB_DEFAULT = {"i32": 0, "i64": 0, "f64": 0.0, "bool": False, "str": None, "void": None}


def _cfunctype_for(ann):
    params, ret = ann.args[:-1], ann.args[-1]
    for t in ann.args:
        if t.name not in _CB_CTYPES and t.name != "void":
            raise ScarRuntimeError(
                f"extern: un callback fn(...) solo admite parámetros/retorno "
                f"primitivos (i32/i64/f64/str/bool/void), se dio {t!r}"
            )
    restype = None if ret.name == "void" else _CB_CTYPES[ret.name]
    return ctypes.CFUNCTYPE(restype, *[_CB_CTYPES[t.name] for t in params])


_LIBC_STDIO = None  # las libc cuyo stdout vacía _flush_c_stdio; se cargan al usarse


def _libc_stdio():
    """Las libc a las que hay que hacerles fflush(NULL). En Linux/macOS,
    los símbolos ya cargados en el proceso (CDLL(None)). En Windows no hay
    CDLL(None) (lanza TypeError), y no hay una libc sino varias: ucrtbase
    (la de CPython) y msvcrt (la de una librería compilada con MinGW). Se
    cargan recién acá y no al importar el módulo: antes `import interpreter`
    reventaba en Windows y con él todo cli.py, aunque el programa no usara
    FFI."""
    global _LIBC_STDIO
    if _LIBC_STDIO is None:
        if sys.platform == "win32":
            libs = []
            for nombre in ("ucrtbase", "msvcrt"):
                try:
                    libs.append(ctypes.CDLL(nombre))
                except OSError:
                    pass
            _LIBC_STDIO = libs
        else:
            _LIBC_STDIO = [ctypes.CDLL(None)]
    return _LIBC_STDIO

# ---- struct de usuario POR VALOR en la frontera FFI ----
# El nativo pasa el mismo `struct` que genera gen_struct, por valor (ver
# _ffi_c_type en codegen/); el checker solo admite structs no genéricos
# con todos sus campos i32/i64/f64/bool (types_.ffi_tipo_ok). Acá se arma una vez por
# struct un ctypes.Structure con los mismos campos en el mismo orden -- el
# mismo layout de C -- y se convierte en cada cruce.

_FFI_STRUCT_CACHE = {}


def _ffi_struct_ctype(decl):
    cls = _FFI_STRUCT_CACHE.get(decl.name)
    if cls is None:
        cls = type(f"_FfiStruct_{decl.name}", (ctypes.Structure,), {
            "_fields_": [(fname, CTYPES_MAP[fty.name]) for fname, fty in decl.fields],
        })
        _FFI_STRUCT_CACHE[decl.name] = cls
    return cls


def _ffi_struct_a_c(valor, decl):
    return _ffi_struct_ctype(decl)(**{f: valor.fields[f] for f, _ in decl.fields})


def _ffi_struct_de_c(c_valor, decl):
    # un campo i64 que vuelve de C es un I64 (sigue contando en 64 bits)
    return StructInstance(decl.name, {f: I64(getattr(c_valor, f)) if fty.name == "i64" else getattr(c_valor, f)
                                      for f, fty in decl.fields})


class _FfiCbEstado:
    __slots__ = ("error",)

    def __init__(self):
        self.error = None


def _flush_c_stdio():
    """El nativo escribe todo por el stdout de la libc, en orden de
    programa. Acá SCAR imprime por sys.stdout y la librería C por el stdout
    de la libc: cada cruce de la frontera vacía el lado que deja de
    escribir, para que el orden sea el mismo que en el nativo."""
    for libc in _libc_stdio():
        libc.fflush(None)


class _LibcWindows:
    """Un `extern fn` sin `from` busca en la libc. En Windows no hay
    CDLL(None) ni una sola libc: se busca el símbolo en ucrtbase y después en
    msvcrt (ver _libc_stdio), como lo vería una librería de cualquiera de
    las dos."""

    def __init__(self, libs):
        self._libs = libs

    def __getattr__(self, nombre):
        for lib in self._libs:
            try:
                return getattr(lib, nombre)
            except AttributeError:
                continue
        raise AttributeError(nombre)


_LIBRARY_CACHE = {}  # nombre de lib (o None) -> ctypes.CDLL, para no volver a
                       # abrir el mismo .so si dos extern fn comparten 'from'


def _load_library(libname):
    """None -> símbolos ya cargados en el proceso (ctypes.CDLL(None), cubre
    libc siempre; en la práctica también libm en CPython estándar de Linux,
    porque el propio intérprete de Python ya la linkea para su módulo
    `math` -- pero un `from "m"` explícito no depende de ese detalle, abre
    libm.so directo). Con nombre, usa ctypes.util.find_library() para
    resolver el .so real (maneja el sufijo de versión, ej. libm.so.6);
    si eso falla (sistema sin ldconfig/plataforma rara), cae a 'lib<nombre>.so'
    a secas como último intento, mismo criterio conservador que el resto del
    proyecto: fallar con un mensaje claro en vez de silenciar el problema."""
    if libname in _LIBRARY_CACHE:
        return _LIBRARY_CACHE[libname]
    if libname is None and sys.platform == "win32":
        lib = _LibcWindows(_libc_stdio())
    elif libname is None:
        lib = ctypes.CDLL(None)
    else:
        # primero la de SCAR que compiló instalar.sh (native/lib/)
        path = (librerias_nativas.ruta_local(libname)
                or ctypes.util.find_library(libname) or f"lib{libname}.so")
        try:
            lib = ctypes.CDLL(path)
        except OSError as e:
            if "cannot open shared object file" in str(e):
                raise ScarRuntimeError(librerias_nativas.explicar_falta(libname))
            raise ScarRuntimeError(
                f"no se pudo cargar la librería '{libname}' (intentado como "
                f"'{path}'): {e}"
            )
    _LIBRARY_CACHE[libname] = lib
    return lib


# ---------------- FFI: aislamiento por proceso worker ----------
# (ver ffi_worker.py para el diseño completo y por qué). Esta sección queda deliberadamente chica:
# toda la lógica de compilar y hablar con el worker vive en ffi_worker.py,
# acá solo se conecta con _bind_extern_fn.


def _bind_extern_fn(decl: "ExternFnDecl", extern_types, worker=None, interp=None, structs=None):
    """ExternFnDecl -> callable de Python con argtypes/restype ya fijados.
    decl.abi/tipos ya fueron validados por type_checker.py (FFI_SUPPORTED_TYPES
    o un 'extern type' declarado) antes de que esto corra -- acá no se
    revalida, se confía en eso, a diferencia de codegen/ que sí revalida
    (ver su comentario) porque codegen puede invocarse fuera del flujo de
    `check()`. El intérprete siempre pasa por cli.py, que siempre corre
    `check()` primero.

    `extern_types`: dict nombre -> ExternTypeDecl ya
    poblado por Interpreter.load() al momento en que esto se llama --
    necesario para que _ctype_for() sepa resolver un parámetro/retorno de
    tipo opaco a ctypes.c_void_p en vez de fallar con KeyError contra
    CTYPES_MAP (el bug que esta fase cierra).

    `worker` (ver ffi_worker.py): si no es None, la llamada
    real pasa por el proceso worker aislado de esa librería -- Python
    NUNCA hace dlopen/getattr sobre la librería en su propio proceso en
    ese caso, para que un fallo de esa librería no tenga ninguna chance
    de tocar memoria compartida con el intérprete. Solo se cae al ctypes
    directo de siempre (`lib`/`fn` de más abajo) cuando no hay worker:
    símbolo sin `from` (fuera del alcance del aislamiento, documentado en
    ffi_worker.py) o el worker de esa librería no pudo iniciarse
    (degradado con aviso, ver FfiWorkerPool)."""
    ret_ann = decl.return_type
    wraps_result = ret_ann is not None and ret_ann.name == "Result"
    ret_inner = ret_ann.args[0] if wraps_result else ret_ann
    ret_name = ret_inner.name if ret_inner is not None else "void"
    param_types = [p.type_ann.name for p in decl.params]
    has_cb = FN_MARK in param_types
    structs = structs or {}
    # parámetros/retorno struct por valor (ver _ffi_struct_ctype)
    struct_params = {i: structs[t] for i, t in enumerate(param_types) if t in structs}
    ret_struct = structs.get(ret_name)
    # Un Vec<T> de escalares son dos
    # argumentos de C, T* y int64_t; lo que C cambie vuelve al Vec.
    vec_params = {i: (p.type_ann.args[0].name if p.type_ann.args else "i32")
                  for i, p in enumerate(decl.params) if p.type_ann.name == "Vec"}

    if worker is not None:
        def call_raw(*args):
            try:
                return worker.call(decl.name, args)
            except ScarFfiWorkerError as e:
                raise ScarRuntimeError(str(e))
    else:
        lib = _load_library(decl.library)
        try:
            fn = getattr(lib, decl.name)
        except AttributeError:
            libref = decl.library or "el proceso actual"
            raise ScarRuntimeError(
                f"extern '{decl.name}': símbolo no encontrado en {libref!r}"
            )
        argtypes = [
            _cfunctype_for(p.type_ann) if p.type_ann.name == FN_MARK
            else _ffi_struct_ctype(struct_params[i]) if i in struct_params
            else ctypes.POINTER(CTYPES_MAP[vec_params[i]]) if i in vec_params
            else _ctype_for(p.type_ann.name, extern_types)
            for i, p in enumerate(decl.params)
        ]
        ret_ctype = (None if ret_name == "void"
                     else _ffi_struct_ctype(ret_struct) if ret_struct is not None
                     else _ctype_for(ret_name, extern_types))
        c_argtypes = []
        for i, t in enumerate(argtypes):
            c_argtypes.append(t)
            if i in vec_params:
                c_argtypes.append(ctypes.c_int64)
        fn.argtypes = c_argtypes
        fn.restype = ret_ctype
        call_raw = fn

    # 'str' es el único tipo de FFI_SUPPORTED_TYPES
    # donde el valor de SCAR (str de Python) y el valor de ctypes (bytes,
    # porque c_char_p no acepta str en Python 3) no son el mismo objeto --
    # i32/f64/bool sí lo son, por eso solo 'str' necesita este wrapper.
    if (worker is None and "str" not in param_types and ret_name not in ("str", "i64")
            and not wraps_result and not has_cb and not struct_params and ret_struct is None
            and not vec_params):
        return call_raw

    param_anns = [p.type_ann for p in decl.params]

    def _call_with_callbacks(c_args):
        # Los FnValue pasan como trampolín; un panic adentro del
        # callback se re-lanza acá, apenas C devuelve el control.
        c_args = [
            interp._ffi_trampolin(a, ann, argtypes[i]) if ann.name == FN_MARK else a
            for i, (a, ann) in enumerate(zip(c_args, param_anns))
        ]
        estado = interp._ffi_cb_estado()
        prev = estado.error
        estado.error = None
        sys.stdout.flush()
        try:
            result = call_raw(*c_args)
        finally:
            _flush_c_stdio()
            error, estado.error = estado.error, prev
        if error is not None:
            raise error
        return result

    def _expandir_vecs(c_args):
        # Cada Vec pasa como un arreglo de ctypes con sus elementos y
        # el largo; después de la llamada, los elementos vuelven al Vec.
        planos, arreglos = [], []
        for i, a in enumerate(c_args):
            if i in vec_params:
                elem = vec_params[i]
                arr = (CTYPES_MAP[elem] * max(1, len(a.items)))(*a.items)
                arreglos.append((a, arr, elem))
                planos += [arr, len(a.items)]
            else:
                planos.append(a)
        return planos, arreglos

    def _volver_vecs(arreglos):
        for vec, arr, elem in arreglos:
            n = len(vec.items)
            conv = I64 if elem == "i64" else (lambda x: x)
            vec.items[:] = [conv(arr[k]) for k in range(n)]

    def _wrapper(*args):
        c_args = [
            a.encode("utf-8") if t == "str"
            else _ffi_struct_a_c(a, struct_params[i]) if i in struct_params
            else a
            for i, (a, t) in enumerate(zip(args, param_types))
        ]
        if vec_params and worker is None:
            if has_cb:
                c_args = [
                    interp._ffi_trampolin(a, ann, argtypes[i]) if ann.name == FN_MARK else a
                    for i, (a, ann) in enumerate(zip(c_args, param_anns))
                ]
            planos, arreglos = _expandir_vecs(c_args)
            if has_cb:
                estado = interp._ffi_cb_estado()
                prev = estado.error
                estado.error = None
                sys.stdout.flush()
                try:
                    result = call_raw(*planos)
                finally:
                    _flush_c_stdio()
                    error, estado.error = estado.error, prev
                if error is not None:
                    _volver_vecs(arreglos)
                    raise error
            else:
                result = call_raw(*planos)
            _volver_vecs(arreglos)
        else:
            result = _call_with_callbacks(c_args) if has_cb else call_raw(*c_args)
        if ret_struct is not None:
            return _ffi_struct_de_c(result, ret_struct)
        if wraps_result:
            # Mismo criterio que _builtin_file_open(): NULL de C (acá,
            # None de ctypes -- c_void_p/c_char_p lo representan así) se
            # traduce a Err(...), nunca a un handle corrupto silencioso.
            if result is None:
                return Err(f"{decl.name} devolvió NULL")
            if ret_name == "str":
                return Ok(result.decode("utf-8", errors="replace"))
            return Ok(I64(result) if ret_name == "i64" else result)
        if ret_name == "i64":
            return I64(result)  # el valor de C entra como i64
        if ret_name != "str":
            return result
        # La regla de la frontera FFI ("ajeno a regiones hasta que se
        # demuestre lo contrario") para el caso de retorno:
        # 'result' es un bytes que ctypes YA copió del char* que devolvió
        # C -- el puntero original de C nunca queda expuesto a Python ni a
        # SCAR, así que no hay nada que liberar ni que retener del lado de
        # SCAR. La excepción explícita de la regla (SCAR se queda con una
        # copia propia) ocurre acá mismo, en este único punto, no por
        # inferencia del compilador.
        if result is None:
            raise ScarRuntimeError(
                f"extern '{decl.name}': devolvió NULL -- puntero nulo de "
                "retorno todavía no soportado en la frontera FFI (para un "
                "retorno que puede ser NULL, declara Result<str>)"
            )
        return result.decode("utf-8", errors="replace")

    return _wrapper

