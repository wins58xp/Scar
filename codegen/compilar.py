"""El build nativo: SCAR -> C -> gcc -> binario (paso C6).

compile_file() junta los módulos (`use`), corre el checker, genera el C con
Codegen.generate() y lo compila. Acá vive todo lo que llama a un compilador
de C: las flags del build (_cc_command, flags_semantica_f64, que también usan
la CI y el fuzzer) y los workers de FFI aislado. La foto del C no pasa por
acá (no compila): esto lo cubre la etapa build de scripts/ci.py.
"""

import os
import shutil
import subprocess
import sys

from type_checker import check as type_check
import mensajes_error
import ffi_worker
import librerias_nativas
from . import Codegen
from .comun import CodegenError

ES_WINDOWS = os.name == "nt"


def _read_join_timeout_env():
    """SCAR_JOIN_TIMEOUT, con la misma regla que
    interpreter._read_join_timeout_env (duplicada: codegen no importa el
    intérprete). cli.py fija la misma variable para los dos."""
    raw = os.environ.get("SCAR_JOIN_TIMEOUT")
    if raw is None:
        return 8.0
    try:
        value = float(raw)
    except ValueError:
        return 8.0
    if value <= 0:
        return 8.0
    return value


def flags_semantica_f64(compilador):
    """Las opciones que fijan la semántica de f64 del C generado, las
    mismas en todo lugar que lo compila (este build, la CI, el fuzzer):
    cada operación se redondea por separado según IEEE-754, como el
    intérprete.

    -ffp-contract=off: sin FMA.
    -frounding-math (solo gcc): gcc reescribía `0.0 - x` como
    `-x` (`0.0 - i` con i = 0 daba -0.0) y plegaba cuentas
    que IEEE no deja plegar. En clang activa el modo estricto (más lento)
    y no hace falta: no se le pasa."""
    fp = ["-ffp-contract=off"]
    if "clang" not in os.path.basename(compilador or ""):
        fp.append("-frounding-math")
    return fp


def _cc_command(out_binary, c_path):
    """El compilador y las flags del backend de C. Si hay clang en el PATH,
    `clang -std=c11 -O3 -march=native -flto` (bench 51: ~4.6x sobre
    `cc -O2`, a la par de Rust); si no, `cc -std=c11 -O2`.
    SCAR_CC_NATIVE=0 quita -march=native (que ata el binario a la CPU);
    SCAR_CC fuerza un compilador."""
    forced = os.environ.get("SCAR_CC")
    compiler = forced or shutil.which("clang") or shutil.which("gcc") or "cc"

    # f64: cada operación se redondea por separado, como IEEE-754 y el
    # intérprete; sin esto clang fusiona a*b+c en una FMA y el último
    # decimal cambia (110_, 113_). Cuesta 3-5 % en el bench 51.
    fp = flags_semantica_f64(compiler)
    if os.path.basename(compiler) == "clang" and not forced:
        cmd = [compiler, "-std=c11", "-O3", "-flto", *fp]
        if os.environ.get("SCAR_CC_NATIVE", "1") != "0":
            cmd.append("-march=native")
    else:
        cmd = [compiler, "-std=c11", "-O2", *fp]

    if "clang" in os.path.basename(compiler):
        # clang corta en 256 paréntesis o llaves anidados (una suma de 500
        # términos o 300 else-if); gcc no tiene ese límite.
        cmd.append("-fbracket-depth=100000")
    endurecer = os.environ.get("SCAR_CC_HARDEN", "1")
    if endurecer != "0":
        # Las defensas de siempre de un compilador de C (canario, FORTIFY,
        # PIE, RELRO), K02. -fstack-protector (no -strong, que costaba ~15 % en
        # fib(36)); SCAR_CC_HARDEN=max usa el strong, =0 apaga todo.
        protector = "-fstack-protector-strong" if endurecer == "max" else "-fstack-protector"
        if ES_WINDOWS:
            # En Windows (MinGW) las defensas ELF no aplican: sin -pie ni
            # relro/now, y sin _FORTIFY_SOURCE (no está en la libc de MinGW).
            cmd += [protector, "-Wformat", "-Wformat-security"]
        else:
            cmd += [protector, "-U_FORTIFY_SOURCE", "-D_FORTIFY_SOURCE=2",
                    "-Wformat", "-Wformat-security", "-fPIE", "-pie", "-Wl,-z,relro", "-Wl,-z,now"]

    cmd += ["-o", out_binary, c_path, "-lm"]
    return cmd


def _build_ffi_worker_binaries(codegen, out_binary):
    """Compila un binario worker por cada librería de pipe_isolated_libs
    (ffi_worker.build_worker_source, el mismo generador que usa el
    intérprete). Va después de construir el Codegen y antes de generate(),
    que embebe ffi_worker_paths en scar_ffi_worker_start_all() (Fase
    10-C).

    Con SCAR_FFI_STRICT, si un worker no compila, el build falla. Sin él,
    la librería sale de pipe_isolated_libs (cae al guard de sigsetjmp) y
    se avisa por stderr."""
    strict = ffi_worker._ffi_strict_mode()
    for lib in sorted(codegen.pipe_isolated_libs):
        try:
            ffi_worker.validar_nombre_lib(lib)
        except ValueError as e:
            raise CodegenError(str(e))
        decls = codegen.extern_fns_by_library[lib]
        source = ffi_worker.build_worker_source(lib, decls, codegen.extern_types)
        worker_c_path = f"{out_binary}.ffi_worker_{lib}.c"
        worker_bin_path = f"{out_binary}.ffi_worker_{lib}"
        with open(worker_c_path, "w", encoding="utf-8") as f:
            f.write(source)

        cc_cmd = ["cc", "-O2", "-o", worker_bin_path, worker_c_path,
                  *librerias_nativas.flags_de_enlace([lib]), f"-l{lib}"]
        try:
            result = subprocess.run(cc_cmd, capture_output=True, text=True)
        except FileNotFoundError:
            raise CodegenError(
                f"no hay compilador de C ('cc' no está en el PATH): "
                f"{librerias_nativas.INSTALAR_CC}"
            ) from None
        if result.returncode == 0:
            codegen.ffi_worker_paths[lib] = os.path.abspath(worker_bin_path)
            continue

        detail = result.stderr.strip() or result.stdout.strip() or "sin detalle"
        falta = librerias_nativas.explicar_fallo_de_enlace(detail)
        if falta is not None:
            # sin la librería el programa tampoco enlaza sin aislamiento: se
            # corta acá con la línea que dice qué instalar
            raise CodegenError(falta)
        if strict:
            raise CodegenError(
                f"SCAR_FFI_STRICT: no se pudo compilar el worker FFI aislado "
                f"para la librería '{lib}':\n{detail}"
            )
        print(
            f"[scar] aviso: no se pudo compilar el worker FFI aislado para "
            f"'{lib}' ({detail}) -- esta librería se compila SIN aislamiento "
            f"de proceso en este binario (guard de siempre). Corre con "
            f"SCAR_FFI_STRICT=1 para rechazar esto de entrada.",
            file=sys.stderr,
        )
        codegen.pipe_isolated_libs.discard(lib)


def compile_file(path, out_binary, libreria=False):
    from modulos import cargar
    program = cargar(path)  # módulos: resuelve los `use`

    errors = type_check(program)
    if errors:
        for e in errors:
            print(f"  {mensajes_error.TIPO}: {e}")
        raise CodegenError(f"{len(errors)} error(es) de tipo, no se genera código")

    codegen = Codegen(program, libreria=libreria)
    if codegen.pipe_isolated_libs:
        _build_ffi_worker_binaries(codegen, out_binary)
    c_src = codegen.generate()
    c_path = out_binary + ".c"
    with open(c_path, "w", encoding="utf-8") as f:
        f.write(c_src)

    # En Windows el ejecutable lleva .exe (el .c conserva el nombre base).
    binario = out_binary
    if ES_WINDOWS and not libreria and not binario.lower().endswith(".exe"):
        binario = binario + ".exe"

    cc_cmd = _cc_command(binario, c_path)
    if libreria:
        # una .so que otro proceso carga (ctypes, dlopen)
        cc_cmd = [f for f in cc_cmd if f not in ("-fPIE", "-pie")]
        cc_cmd[1:1] = ["-fPIC", "-shared"]
    if codegen.has_tasks or codegen.uses_chan or libreria:
        cc_cmd.append("-lpthread")
    if codegen.has_tasks:
        # El mismo SCAR_JOIN_TIMEOUT que lee el intérprete pisa el valor por
        # defecto del .c.
        cc_cmd.append(f"-DSCAR_JOIN_TIMEOUT_SECONDS={_read_join_timeout_env()}")
    # -l<lib> por cada `from "lib"` de un `extern fn` (salvo m, ya
    # presente). Una librería aislada no se linkea: vive solo en su worker.
    for lib in sorted(codegen.extern_libs - codegen.pipe_isolated_libs):
        try:
            ffi_worker.validar_nombre_lib(lib)
        except ValueError as e:
            raise CodegenError(str(e))
        flag = f"-l{lib}"
        if flag not in cc_cmd:
            cc_cmd.append(flag)
    # las librerías de SCAR que compiló instalar.sh (native/lib/)
    cc_cmd += librerias_nativas.flags_de_enlace(codegen.extern_libs - codegen.pipe_isolated_libs)
    try:
        result = subprocess.run(cc_cmd, capture_output=True, text=True)
    except FileNotFoundError:
        # sin compilador de C (Windows sin MinGW, por ejemplo): un error con
        # mensaje, no un traceback
        raise CodegenError(
            f"no hay compilador de C ('{cc_cmd[0]}' no está en el PATH): "
            f"{librerias_nativas.INSTALAR_CC}. El C generado quedó en {c_path}"
        ) from None
    if result.returncode != 0:
        # una librería que no está: una línea que dice cuál y cómo
        # conseguirla, no el error crudo del linker
        falta = librerias_nativas.explicar_fallo_de_enlace(result.stderr + result.stdout)
        if falta is not None:
            raise CodegenError(falta)
        raise CodegenError(f"gcc/cc falló:\n{result.stdout}\n{result.stderr}")

    # Windows no tiene rpath: el .dll de cada librería nativa se copia junto al
    # .exe para que el sistema lo encuentre al correr. (SDL2.dll se toma del
    # PATH de MinGW.)
    if ES_WINDOWS and not libreria:
        destino_dir = os.path.dirname(os.path.abspath(binario))
        for lib in codegen.extern_libs - codegen.pipe_isolated_libs:
            dll = librerias_nativas.ruta_local(lib)
            if dll is None:
                continue
            destino = os.path.join(destino_dir, os.path.basename(dll))
            if os.path.abspath(dll) != destino:
                try:
                    shutil.copy2(dll, destino)
                except OSError:
                    pass
    return c_path, binario


def main():
    if len(sys.argv) != 3:
        print("uso: python3 -m codegen archivo.scar salida_binario")
        sys.exit(1)
    src_path, out_path = sys.argv[1], sys.argv[2]
    try:
        c_path, binary = compile_file(src_path, out_path)
    except CodegenError as e:
        print(f"----- ERROR DE COMPILACIÓN: {e} -----")
        sys.exit(1)
    print(f"C generado: {c_path}")
    print(f"binario nativo: {binary}")

