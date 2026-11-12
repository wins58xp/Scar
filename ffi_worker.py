# Aislar cada llamada FFI en un PROCESO separado, no en un signal handler
# dentro del mismo proceso.
#
# Por qué no un guardia con sigsetjmp/siglongjmp: "recuperarse" de un
# SIGSEGV/SIGBUS/SIGABRT saltando de vuelta al MISMO espacio de memoria donde
# la librería C acaba de crashear no deja nada consistente. Si esa librería
# tenía el lock global de malloc tomado, o el heap a medio modificar, el
# proceso "sobrevive" con memoria potencialmente corrupta.
#
# Cada librería FFI (agrupadas por `from "lib"`) corre
# en su propio proceso hijo ("worker"). El intérprete de Python nunca
# ejecuta código de la librería C directamente -- le manda la llamada por
# un pipe, el worker la ejecuta y devuelve el resultado por otro pipe. Si
# la librería crashea, el sistema operativo mata a ESE proceso con su
# comportamiento normal (sin signal handler, sin intento de "arreglar"
# nada) y listo: el kernel libera toda su memoria de una. El proceso de
# Python nunca compartió esa memoria, así que no hay nada que corromper
# del lado de acá. Se detecta como pipe roto y se convierte en panic de
# SCAR (ver política de decisión más abajo).
#
# Handles opacos (`extern type`, ej. SDLWindow) y estado con vida entre
# llamadas (ej. g_win/g_ren en scarsdl.c) siguen funcionando sin cambios:
# el worker es UN SOLO proceso que vive mientras dure el programa SCAR,
# no uno por llamada. El puntero opaco que scar_sdl_create_window()
# devuelve solo tiene sentido dentro del espacio de memoria del worker,
# pero eso no es un problema: SCAR nunca lo dereferencia, solo lo guarda
# y se lo devuelve tal cual en la siguiente llamada -- viaja como un
# número de 8 bytes sin significado para Python, y el worker es quien lo
# interpreta como puntero real, siempre dentro de su propia memoria.
#
# Política de crash: panic recuperable, el programa SCAR sigue corriendo, pero esa librería queda
# marcada como muerta para el resto de la corrida -- NO se reinicia el
# worker automáticamente. Reabrir un worker nuevo dejaría vivo un
# programa que cree tener un handle válido (ej. una ventana) cuando en
# realidad esa ventana ya no existe en ningún lado: es el mismo tipo de
# "estado inconsistente silencioso" que esto reemplaza, solo que
# corriendo un nivel más arriba. Matar el programa entero tampoco: un
# crash en una librería no debería tumbar código que usa otra librería
# sin relación.

import ctypes
import os
import struct
import subprocess
import sys
import tempfile
import threading
import re

import librerias_nativas

# El nombre de la librería va al comando del
# compilador (-l<nombre>) y al código C del worker. El checker ya rechaza los
# nombres raros; esto es la segunda barrera, por si alguien llama al backend
# sin pasar por el checker.
_NOMBRE_LIB_OK = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.+-]{0,63}$')


def validar_nombre_lib(library):
    if not isinstance(library, str) or not _NOMBRE_LIB_OK.match(library):
        raise ValueError(f"nombre de librería inválido: {library!r}")


class ScarFfiWorkerError(Exception):
    """La librería FFI de este worker crasheó o el proceso murió por otra
    razón. El llamador (interpreter.py) la traduce a ScarRuntimeError."""


_C_TYPE_NAMES = {
    "i32": "int32_t",
    "i64": "int64_t",
    "f64": "double",
    "bool": "bool",
    "str": "char*",
}


def _c_type_name(type_name, extern_types):
    if type_name in _C_TYPE_NAMES:
        return _C_TYPE_NAMES[type_name]
    if type_name in extern_types:
        return "void*"
    raise ValueError(f"extern: tipo {type_name!r} no soportado en worker FFI")


# Un Vec de escalares cruza como puntero +
# largo. Por el pipe va el largo (int64) y los elementos; después de la
# llamada, el worker devuelve los elementos (C pudo cambiarlos) detrás del
# valor de retorno, en el orden de los parámetros.
_VEC_ELEM = {"i32": ("int32_t", 4, "<i"), "i64": ("int64_t", 8, "<q"),
             "f64": ("double", 8, "<d"), "bool": ("bool", 1, "<?")}
# Cómo vuelve cada elemento a SCAR; interpreter.py cambia el de i64 por su I64.
_VEC_CONV = {"vec_i32": int, "vec_i64": int, "vec_f64": float, "vec_bool": bool}


def _param_kind(type_name, extern_types):
    """'i32' | 'f64' | 'bool' | 'str' | 'ptr' | 'vec_<T>' -- para el
    (de)serializador, sin necesitar el nombre C. Recibe el nombre del tipo
    o el TypeAnn (hace falta para Vec<T>)."""
    if not isinstance(type_name, str):
        ann = type_name
        if ann.name == "Vec":
            elem = ann.args[0].name if ann.args else "i32"
            if elem in _VEC_ELEM:
                return "vec_" + elem
            raise ValueError(f"extern: Vec<{elem}> no soportado en worker FFI")
        type_name = ann.name
    if type_name == "i32":
        return "i32"
    if type_name == "i64":
        return "i64"
    if type_name == "f64":
        return "f64"
    if type_name == "bool":
        return "bool"
    if type_name == "str":
        return "str"
    if type_name in extern_types:
        return "ptr"
    raise ValueError(f"extern: tipo {type_name!r} no soportado en worker FFI")


def _ret_kind(ret_ann, extern_types):
    wraps_result = ret_ann is not None and ret_ann.name == "Result"
    ret_inner = ret_ann.args[0] if wraps_result else ret_ann
    ret_name = ret_inner.name if ret_inner is not None else "void"
    if ret_name == "void":
        return "void", "void"
    return ret_name, _param_kind(ret_name, extern_types)


_HARNESS_PRELUDE = """\
// Worker FFI generado (ver ffi_worker.py) -- un proceso por librería.
// Sin manejador de señales: si la librería crashea, el proceso muere
// con el comportamiento normal del sistema operativo. El padre (Python)
// detecta el pipe cerrado y lo convierte en panic. Nada intenta
// "recuperarse" en esta memoria.
#define _GNU_SOURCE
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int read_exact(int fd, void *buf, size_t n) {
    size_t got = 0;
    while (got < n) {
        ssize_t r = read(fd, (char *)buf + got, n - got);
        if (r <= 0) return 0;  // EOF o error -> el padre cerró/murió
        got += (size_t)r;
    }
    return 1;
}

static int write_exact(int fd, const void *buf, size_t n) {
    size_t sent = 0;
    while (sent < n) {
        ssize_t w = write(fd, (const char *)buf + sent, n - sent);
        if (w <= 0) return 0;
        sent += (size_t)w;
    }
    return 1;
}

static int32_t read_i32(void)  { int32_t v; if(!read_exact(0,&v,4)) exit(1); return v; }
static int64_t read_i64(void)  { int64_t v; if(!read_exact(0,&v,8)) exit(1); return v; }
static double  read_f64(void)  { double  v; if(!read_exact(0,&v,8)) exit(1); return v; }
static uint8_t read_bool(void) { uint8_t v; if(!read_exact(0,&v,1)) exit(1); return v; }
static uint64_t read_ptr(void) { uint64_t v; if(!read_exact(0,&v,8)) exit(1); return v; }
static char *read_str(void) {
    uint32_t len; if(!read_exact(0,&len,4)) exit(1);
    char *s = malloc((size_t)len + 1);
    if (len > 0 && !read_exact(0, s, len)) exit(1);
    s[len] = 0;
    return s;
}

static void write_i32(int32_t v)  { write_exact(1,&v,4); }
static void write_i64(int64_t v)  { write_exact(1,&v,8); }
static void write_f64(double v)   { write_exact(1,&v,8); }
static void write_bool(uint8_t v) { write_exact(1,&v,1); }
static void write_ptr(uint64_t v) { write_exact(1,&v,8); }
static void write_str(const char *s) {
    // NULL vs "" son casos distintos para SCAR (Result<T> vs Ok("")) --
    // un flag de 1 byte los distingue en vez de colapsar NULL a largo 0.
    uint8_t is_null = s ? 0 : 1;
    write_exact(1, &is_null, 1);
    if (is_null) return;
    uint32_t len = (uint32_t)strlen(s);
    write_exact(1,&len,4);
    if (len > 0) write_exact(1, s, len);
}
"""


def _emit_call(idx, decl, extern_types, lines):
    param_kinds = [_param_kind(p.type_ann, extern_types) for p in decl.params]
    # Un str como parámetro es `const char*` (C no lo modifica;
    # convención de la libc), igual que en el backend de C (_ffi_c_type).
    # Un Vec<T> son dos parámetros de C, `T*` y `int64_t`.
    param_c_types = []
    for p, kind in zip(decl.params, param_kinds):
        if kind.startswith("vec_"):
            param_c_types += [_VEC_ELEM[kind[4:]][0] + "*", "int64_t"]
        elif p.type_ann.name == "str":
            param_c_types.append("const char*")
        else:
            param_c_types.append(_c_type_name(p.type_ann.name, extern_types))
    ret_name, ret_kind = _ret_kind(decl.return_type, extern_types)
    ret_c_type = None if ret_kind == "void" else _c_type_name(ret_name, extern_types)

    raw_param_list = ", ".join(param_c_types) or "void"
    # nombre de C propio con la etiqueta del símbolo real (ver
    # codegen/programa.py, _SIMBOLO_C): una extern fn que se llama como una
    # función de la libc ya declarada por los #include (strlen) no choca
    lines.append(f"extern {ret_c_type or 'void'} scar_ext_{decl.name}({raw_param_list}) "
                 f"SCAR_SIMBOLO(\"{decl.name}\");\n")
    lines.append(f"static void call_{idx}(void) {{\n")

    reader_for_kind = {
        "i32": ("int32_t", "read_i32()"),
        "i64": ("int64_t", "read_i64()"),
        "f64": ("double", "read_f64()"),
        "bool": ("bool", "(bool)read_bool()"),
        "str": ("char*", "read_str()"),
        "ptr": ("void*", "(void*)(uintptr_t)read_ptr()"),
    }
    arg_names = []
    for i, kind in enumerate(param_kinds):
        if kind.startswith("vec_"):
            elem_c, size, _ = _VEC_ELEM[kind[4:]]
            lines.append(f"    int64_t n{i} = read_i64();\n")
            lines.append(f"    if (n{i} < 0) exit(1);\n")
            lines.append(f"    {elem_c} *a{i} = malloc((size_t)n{i} * {size} + 1);\n")
            lines.append(f"    if (n{i} > 0 && !read_exact(0, a{i}, (size_t)n{i} * {size})) exit(1);\n")
            arg_names += [f"a{i}", f"n{i}"]
            continue
        c_type, reader = reader_for_kind[kind]
        lines.append(f"    {c_type} a{i} = {reader};\n")
        arg_names.append(f"a{i}")
    args_fwd = ", ".join(arg_names)

    if ret_kind == "void":
        lines.append(f"    scar_ext_{decl.name}({args_fwd});\n")
    else:
        lines.append(f"    {ret_c_type} r = scar_ext_{decl.name}({args_fwd});\n")
        writer = {
            "i32": "write_i32(r);",
            "i64": "write_i64(r);",
            "f64": "write_f64(r);",
            "bool": "write_bool((uint8_t)r);",
            "str": "write_str(r);",
            "ptr": "write_ptr((uint64_t)(uintptr_t)r);",
        }[ret_kind]
        lines.append(f"    {writer}\n")
    for i, kind in enumerate(param_kinds):
        if kind == "str":
            lines.append(f"    free(a{i});\n")
        elif kind.startswith("vec_"):
            size = _VEC_ELEM[kind[4:]][1]
            lines.append(f"    if (n{i} > 0) write_exact(1, a{i}, (size_t)n{i} * {size});\n")
            lines.append(f"    free(a{i});\n")
    lines.append("}\n\n")


def _build_worker_source(library, decls, extern_types):
    validar_nombre_lib(library)
    lines = [_HARNESS_PRELUDE, "#include <stdint.h>\n\n",
             "#define SCAR_SIMBOLO_TXT2(x) #x\n"
             "#define SCAR_SIMBOLO_TXT(x) SCAR_SIMBOLO_TXT2(x)\n"
             "#define SCAR_SIMBOLO(n) __asm__(SCAR_SIMBOLO_TXT(__USER_LABEL_PREFIX__) n)\n\n"]
    for idx, decl in enumerate(decls):
        _emit_call(idx, decl, extern_types, lines)

    lines.append("int main(void) {\n")
    lines.append("    uint32_t idx;\n")
    lines.append("    while (read_exact(0, &idx, 4)) {\n")
    lines.append("        switch (idx) {\n")
    for idx in range(len(decls)):
        lines.append(f"            case {idx}: call_{idx}(); break;\n")
    lines.append("            default: exit(1);\n")
    lines.append("        }\n")
    lines.append("    }\n")
    lines.append("    return 0;\n")
    lines.append("}\n")
    return "".join(lines)


def build_worker_source(library, decls, extern_types):
    """Alias público de `_build_worker_source` (backend de C):
    el compilador (codegen/) reusa el MISMO generador de C puro que ya prueba este
    módulo para el intérprete, en vez de reimplementar el protocolo de
    pipe una segunda vez. Nombre público a propósito -- un módulo
    distinto importando un `_nombre` privado sería un acoplamiento
    incómodo de leer en el sitio de la llamada."""
    return _build_worker_source(library, decls, extern_types)


class FfiWorker:
    """Un proceso worker vivo para UNA librería (`from "lib"`). Vive
    mientras dure el programa SCAR o hasta que la librería crashee."""

    def __init__(self, library, decls, extern_types):
        self.library = library
        self.decls = decls
        self.extern_types = extern_types
        self.index_of = {d.name: i for i, d in enumerate(decls)}
        self.kinds = {
            d.name: (
                [_param_kind(p.type_ann, extern_types) for p in d.params],
                _ret_kind(d.return_type, extern_types)[1],
            )
            for d in decls
        }
        self.dead = False
        self.dead_reason = None
        self.proc = None
        # Las tasks del intérprete son hilos de Python y todas comparten
        # ESTE worker y su único par de pipes. Sin un lock, dos tasks
        # intercalarían el pedido de una con la respuesta de otra. Mismo
        # criterio que el backend de C, que serializa con
        # pthread_mutex_lock(&scar_ffi_worker_<lib>.mu) todo el ida y vuelta
        # (_gen_ffi_pipe_wrapper en codegen/ffi.py).
        self._lock = threading.Lock()
        self._start()

    def _start(self):
        source = _build_worker_source(self.library, self.decls, self.extern_types)
        tmpdir = tempfile.mkdtemp(prefix="scar_ffi_worker_")
        c_path = os.path.join(tmpdir, "worker.c")
        bin_path = os.path.join(tmpdir, "worker")
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(source)

        cc_cmd = ["cc", "-O2", "-o", bin_path, c_path,
                  *librerias_nativas.flags_de_enlace([self.library]), f"-l{self.library}"]
        result = subprocess.run(cc_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise OSError(result.stderr.strip() or "gcc/cc devolvió error sin detalle")

        self.proc = subprocess.Popen(
            [bin_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # hereda stderr: los avisos propios de la librería C se ven igual que antes
            bufsize=0,
        )

    def _mark_dead(self, reason):
        self.dead = True
        self.dead_reason = reason
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=1)
            except Exception:
                pass

    def _crash_reason(self):
        if self.proc is None:
            return "el proceso worker nunca llegó a iniciarse"
        code = self.proc.wait()
        if code < 0:
            import signal as _sig

            try:
                signame = _sig.Signals(-code).name
            except ValueError:
                signame = f"señal {-code}"
            return f"terminó por {signame}"
        return f"terminó con código de salida {code}"

    def call(self, fn_name, args):
        # Todo el ida y vuelta (chequeo de 'dead', escritura del pedido y
        # lectura de la respuesta) va bajo el lock: ver __init__.
        with self._lock:
            return self._call_locked(fn_name, args)

    def _call_locked(self, fn_name, args):
        if self.dead:
            raise ScarFfiWorkerError(
                f"la librería '{self.library}' ya no está disponible en esta "
                f"corrida (worker murió antes: {self.dead_reason})"
            )

        idx = self.index_of[fn_name]
        param_kinds, ret_kind = self.kinds[fn_name]

        try:
            payload = struct.pack("<I", idx)
            for value, kind in zip(args, param_kinds):
                if kind == "i32":
                    payload += struct.pack("<i", value)
                elif kind == "i64":
                    payload += struct.pack("<q", value)
                elif kind == "f64":
                    payload += struct.pack("<d", value)
                elif kind == "bool":
                    payload += struct.pack("<B", 1 if value else 0)
                elif kind == "ptr":
                    payload += struct.pack("<Q", value or 0)
                elif kind == "str":
                    b = value if isinstance(value, bytes) else value.encode("utf-8")
                    payload += struct.pack("<I", len(b)) + b
                elif kind.startswith("vec_"):
                    fmt = _VEC_ELEM[kind[4:]][2]
                    items = value.items
                    payload += struct.pack("<q", len(items))
                    payload += struct.pack("<" + fmt[1] * len(items), *items)
            self.proc.stdin.write(payload)
            self.proc.stdin.flush()
            r = self._leer_retorno(ret_kind)
            # Después del retorno, los elementos de cada Vec, que C
            # pudo cambiar: vuelven al Vec de SCAR.
            for value, kind in zip(args, param_kinds):
                if kind.startswith("vec_") and value.items:
                    _, size, fmt = _VEC_ELEM[kind[4:]]
                    n = len(value.items)
                    nuevos = struct.unpack("<" + fmt[1] * n, self._read(n * size))
                    value.items[:] = [_VEC_CONV[kind](x) for x in nuevos]
            return r
        except (BrokenPipeError, OSError):
            reason = self._crash_reason()
            self._mark_dead(reason)
            raise ScarFfiWorkerError(
                f"la función extern '{fn_name}' de la librería '{self.library}' "
                f"tumbó su proceso worker ({reason}) -- el resto del proceso SCAR "
                "sigue corriendo sin daño, pero esta librería queda inutilizable "
                "por el resto de esta corrida"
            )

    def _leer_retorno(self, ret_kind):
        if True:
            if ret_kind == "void":
                return None
            if ret_kind == "i32":
                raw = self._read(4)
                return struct.unpack("<i", raw)[0]
            if ret_kind == "i64":
                return struct.unpack("<q", self._read(8))[0]
            if ret_kind == "f64":
                raw = self._read(8)
                return struct.unpack("<d", raw)[0]
            if ret_kind == "bool":
                raw = self._read(1)
                return struct.unpack("<B", raw)[0] != 0
            if ret_kind == "ptr":
                raw = self._read(8)
                val = struct.unpack("<Q", raw)[0]
                return val or None
            if ret_kind == "str":
                is_null = self._read(1)[0]
                if is_null:
                    return None
                length = struct.unpack("<I", self._read(4))[0]
                return self._read(length) if length > 0 else b""

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.proc.stdout.read(n - len(buf))
            if not chunk:
                reason = self._crash_reason()
                self._mark_dead(reason)
                raise BrokenPipeError(reason)
            buf += chunk
        return buf


def _ffi_strict_mode() -> bool:
    """Modo estricto. Sin él, si el worker aislado no puede compilar o
    iniciar, se ejecutan las llamadas extern SIN aislamiento de proceso
    (fail-open). Para
    código .scar no confiable eso reabre exactamente el riesgo que el
    worker evita (un crash de la librería C corrompiendo el proceso
    anfitrión). Mismo patrón que SCAR_JOIN_TIMEOUT (ver cli.py,
    _apply_join_timeout): una sola variable de entorno, leída acá y en
    ningún otro lado, sin nueva lógica de parsing de flags. Default sin
    setear = comportamiento anterior sin cambios (modo desarrollo)."""
    return os.environ.get("SCAR_FFI_STRICT", "") not in ("", "0")


def library_pipe_eligible(decls, extern_types):
    """Todo o nada por librería, misma regla que el backend de C
    (Codegen._library_pipe_eligible): si UNA sola función
    usa un tipo que el protocolo de pipe no puede representar (struct por
    valor, fn como valor), ninguna función de la librería se aísla en
    worker y la librería entera queda en el camino sin aislamiento. Así el
    intérprete nunca intenta armar un worker que _param_kind() no puede
    describir."""
    try:
        for d in decls:
            for p in d.params:
                _param_kind(p.type_ann, extern_types)
            _ret_kind(d.return_type, extern_types)
    except ValueError:
        return False
    return True


class FfiWorkerPool:
    """Un FfiWorker por nombre de librería, construido perezosamente la
    primera vez que se declara una extern fn de esa librería.

    Por defecto (SCAR_FFI_STRICT sin setear) nunca lanza al construirse
    el pool en sí: cada worker individual puede fallar a compilar/iniciar
    sin afectar a los demás -- 'degradarse, no romper', igual que el
    guardia anterior. Con SCAR_FFI_STRICT=1 (modo seguro) el
    criterio cambia a 'fallar cerrado': un worker que no arranca aborta
    la carga del programa entero en vez de exponer esa librería sin
    aislamiento."""

    def __init__(self, strict: bool = None):
        self._workers = {}
        self._failed = {}
        self._ineligible = set()
        self.strict = _ffi_strict_mode() if strict is None else strict

    def get_or_build(self, library, decls, extern_types):
        if library in self._workers:
            return self._workers[library]
        if library in self._ineligible:
            return None
        if library in self._failed:
            if self.strict:
                raise ScarFfiWorkerError(
                    f"modo seguro (SCAR_FFI_STRICT): la librería '{library}' "
                    f"ya había fallado antes ({self._failed[library]}) y no "
                    "se permite reintentar sin aislamiento"
                )
            return None
        if not library_pipe_eligible(decls, extern_types):
            # No es una falla (como en el nativo, tampoco cuenta para
            # SCAR_FFI_STRICT): es el límite documentado del protocolo de
            # pipe. Se recuerda para no reevaluar en cada extern fn.
            self._ineligible.add(library)
            return None
        try:
            worker = FfiWorker(library, decls, extern_types)
        except OSError as e:
            self._failed[library] = str(e)
            falta = librerias_nativas.explicar_fallo_de_enlace(str(e))
            if falta is not None:
                # la librería no está: sin aislamiento tampoco va a cargar, y
                # la carga lo dice en una línea (el aviso de abajo solo
                # agregaba el error crudo del linker)
                if self.strict:
                    raise ScarFfiWorkerError(falta)
                return None
            if self.strict:
                raise ScarFfiWorkerError(
                    f"modo seguro (SCAR_FFI_STRICT): no se pudo iniciar el "
                    f"worker FFI aislado para '{library}' ({e}) -- se rechaza "
                    "la carga en vez de ejecutar sus llamadas extern sin "
                    "aislamiento de proceso"
                )
            print(
                f"[scar] aviso: no se pudo iniciar el worker FFI aislado para "
                f"'{library}' ({e}) -- las llamadas extern de esa librería "
                "seguirán funcionando pero SIN aislamiento de proceso ante un "
                "crash. Corre con SCAR_FFI_STRICT=1 "
                "para rechazar esto en vez de degradarse.",
                file=sys.stderr,
            )
            return None
        self._workers[library] = worker
        return worker
