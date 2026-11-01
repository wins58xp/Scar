"""
Verificador estático de tipos para SCAR.

Camina el AST ANTES de ejecutar nada y rechaza programas inválidos. Esto es lo que
separa "un prototipo que corre" de un lenguaje con garantías reales: hasta ahora,
SCAR descubría sus errores de tipo en runtime (como Python). Este módulo los atrapa
en tiempo de compilación.

Alcance de este primer verificador (deliberadamente honesto, no completo):
  - tipos de parámetros y retorno de funciones/tareas
  - operaciones binarias (+, -, *, /, comparaciones) requieren tipos numéricos
    compatibles; comparar str con str o bool con bool está permitido para ==/!=
  - llamadas a función: aridad y tipos de argumentos
  - acceso a campos de struct: el struct debe existir y el campo también
  - construcción de struct literal: todos los campos requeridos, tipos correctos
  - el operador `?` solo es válido dentro de una función que devuelve Result<T>,
    y el tipo interno debe coincidir con el T declarado
  - `return` debe coincidir con el tipo de retorno declarado de la función
  - variables no declaradas antes de usarse

Inferencia de T para `None` fuera de un `let` con anotación (en `return
None` y como argumento de función): `_infer` acepta un `expected_ty`
opcional que el llamador pasa cuando el tipo esperado en ese sitio se conoce
de antemano (`ret_ty` de la función en un `return`, o el tipo declarado del
parámetro en una llamada); `NoneExpr` lo usa si es un `Option<T>` concreto.
Sin `expected_ty`, o si no es un `Option<T>` con parámetro, queda
`Option<i32>`, como en un `let` sin anotación.
"""

from parser import (marca_new_generico, elemento_de_pop,
    Program, StructDecl, FnDecl, ExternFnDecl, ExternTypeDecl, ExternLibDecl, Block, LetStmt, ReturnStmt, ExprStmt, IfStmt,
    WhileStmt, WhileLetStmt, ForStmt, AssignStmt, NumLit, StrLit, BoolLit, Ident,
    BinOp, UnaryOp, Call, MethodCall, FieldAccess, IndexExpr, StructLit, SpawnExpr, ArrayLit, IfExpr, es_panic,
    TryExpr, OkExpr, ErrExpr, SomeExpr, NoneExpr, PrintExpr, block_always_returns,
    BreakStmt, ContinueStmt, block_never_falls_through, Node, hijos,
)
from types_ import (TypeAnn, T_I32, T_I64, T_F64, T_STR, T_BOOL, T_VOID,
                    int_literal_type, numeric_result, numeric_mix_ok,
                    RESULT, OPTION_MARK, TASK_MARK, CHAN_MARK, VEC_MARK, MAP_MARK, PIPE_MARK,
                    FILE_MARK, SOCKET_MARK, FN_MARK, LISTENER_MARK, FFI_SUPPORTED_TYPES)
from fresh_owned import resolve_consumed_option_params, resolve_consumed_params, resolve_returned_params
from enum_match import bajar_enums, bajar_main_result
from if_expr import bajar as bajar_if_expr, hay_if_expr
from continuar import bajar as bajar_continue
import lugares
import re
import types_

# El i32 más grande. Un literal entero mayor es un error.
_I32_MAX = 2147483647


class TypeError_(Exception):
    """Error de tipo detectado en tiempo de compilación."""
    def __init__(self, msg, line=None, col=None, archivo=None):
        self.msg = msg
        self.line = line
        self.col = col
        # módulos: el archivo, si el error está en un módulo
        self.archivo = archivo
        if archivo:
            loc = f" ({archivo}, línea {line})" if line else f" ({archivo})"
        else:
            loc = f" (línea {line})" if line else ""
        super().__init__(f"{msg}{loc}")


# Las marcas de los tipos especiales (Option, Task, Chan, Vec, Map, Pipe, File,
# Socket, Listener, fn) viven en types_.py.

# Bounds conocidos sobre un parámetro de tipo abstracto (ej. la 'T' de
# 'fn sumar<T: Numeric>(...)') -> qué operadores binarios habilitan sobre un
# valor de ese tipo dentro del cuerpo de la función. No hay bounds
# "definidos por el usuario": un nombre que no aparece acá no habilita nada
# y T se comporta como opaco. '==' / '!=' quedan afuera a propósito: ya
# funcionan sobre un 'T' sin bound (dos valores del mismo T son "tipos
# idénticos" para _compatible, que no exige numérico). '%' también queda
# afuera: 'Numeric' cubre i32 y f64 por igual, y el módulo de punto flotante
# no tiene un operador nativo en C (a diferencia de scar_imod, de i32);
# agregarlo exige decidir esa semántica primero.
BOUND_OPS = {
    "Numeric": {"+", "-", "*", "/", "<", ">", "<=", ">="},
}

# FFI_SUPPORTED_TYPES y la regla de qué cruza una extern fn: types_.ffi_tipo_ok.

BUILTIN_FN_TYPES = {
    # nombre -> (tipos de parámetros, tipo de retorno)
    "sqrt": ([T_F64], T_F64),
    # rand(): sin argumentos, f64 en [0.0, 1.0) -- mismo criterio que sqrt()
    # (mapea directo a una función matemática de libc, sin genéricos ni
    # marca de tipo). Ver BUILTIN_SIGS en codegen/ y BUILTINS en
    # interpreter.py para el mapeo real a rand()/srand() de C y a
    # random.random() del intérprete.
    "rand": ([], T_F64),
    # seed(n): fija la semilla de rand() de la tarea actual (las
    # tasks que cree después derivan la suya de esta). Mismo generador en
    # los dos backends, así que con la misma semilla dan los mismos números.
    "seed": ([T_I32], T_VOID),
    # to_i32(x)/to_f64(n): conversión explícita entre
    # los dos números. to_i32 trunca hacia cero (como `as i32` en C/Rust);
    # NaN o un valor que no entra en i32 es un panic, no un número inventado.
    # Funciones de libm sobre f64 (filtro del sismógrafo), con la
    # semántica de C en los dos backends: ln(0) = -inf, ln(-1) = nan, exp
    # de algo grande = inf (Python lanza excepciones en esos casos).
    "sin": ([T_F64], T_F64),
    "cos": ([T_F64], T_F64),
    "tan": ([T_F64], T_F64),
    "atan": ([T_F64], T_F64),
    "exp": ([T_F64], T_F64),
    "ln": ([T_F64], T_F64),
    "log10": ([T_F64], T_F64),
    "pow": ([T_F64, T_F64], T_F64),
    "floor": ([T_F64], T_F64),
    # abs/min/max: de cualquier número; los revisa su
    # propio bloque en _infer/Call. abs de un entero es un entero (exacto), y
    # abs del mínimo (que no tiene positivo) es un panic.
    "abs": ([T_F64], T_F64),
    "min": ([T_F64, T_F64], T_F64),
    "max": ([T_F64, T_F64], T_F64),
    # to_i32/to_i64/to_f64 aceptan cualquier número (i32, i64 o f64);
    # el argumento lo revisa su propio bloque en _infer/Call (NUMERIC_CONVERSIONS).
    # Un valor que no cabe en el destino es un panic, nunca un número truncado.
    "to_i32": ([T_F64], T_I32),
    "to_i64": ([T_F64], T_I64),
    "to_f64": ([T_I32], T_F64),
    # chr(n): el carácter de código Unicode n, como str (propio); ord(s): el
    # código del primer carácter de s. Código inválido (0, sustituto o mayor
    # que 0x10FFFF) o un str vacío son un panic.
    "chr": ([T_I32], T_STR),
    # a_texto(x): un número, un bool o un str como texto, con el
    # mismo formato que print (a_texto(2.5) es "2.5", a_texto(true) "true").
    # Su propio bloque en _infer/Call revisa el tipo. El str es propio.
    "a_texto": ([T_STR], T_STR),
    "ord": ([T_STR], T_I32),
    # now(): sin argumentos, f64 -- segundos de un reloj MONOTÓNICO (no reloj
    # de pared), pensado para restar dos llamadas y medir una duración, no
    # para timestamps absolutos ni para persistir/comparar entre corridas.
    # Ver BUILTIN_SIGS en codegen/ (scar_now(), helper propio e
    # independiente de scar_monotonic_now()/tasks) y BUILTINS en
    # interpreter.py (time.monotonic()).
    "now": ([], T_F64),
    # arg(i): el i-ésimo argumento del programa en la línea de
    # comandos, contando desde 0 (el nombre del programa no es un argumento:
    # `scar run f.scar -- 1000` y `./f 1000` dan arg(0) = Some("1000") en los
    # dos backends). Fuera de rango (o negativo) es None, como .get(). El str
    # es PRESTADO del proceso (argv vive hasta que el programa termina, igual
    # que un literal): nadie lo libera, así que a propósito NO figura en
    # _is_str_owned_call. Un argumento que no es UTF-8 válido es un panic.
    "arg": ([T_I32], TypeAnn(OPTION_MARK, [T_STR])),
    "len": ([T_STR], T_I32),
    "int": ([T_STR], TypeAnn(RESULT, [T_I32])),
    # int64(s), misma regla que int(s) pero con el rango de i64.
    "int64": ([T_STR], TypeAnn(RESULT, [T_I64])),
    # chan_new NO vive acá a propósito -- ver el bloque dedicado en
    # _infer/Call. Es la única builtin de aridad variable (0 o 1
    # argumentos: capacidad opcional del canal), y este dict solo modela
    # aridad fija (ver el chequeo `len(arg_types) != len(param_types)`
    # más abajo) -- forzarla acá exigiría o bien mentir con una entrada
    # de aridad fija (rompe uno de los dos casos) o enseñarle aridad
    # variable a TODO este mecanismo para un solo caso. Más sano: sacarla
    # del mecanismo genérico y darle su propio bloque, igual que 'None'
    # ya tiene el suyo unas líneas más abajo por el mismo motivo de fondo
    # (sin argumentos de los que inferir T).
    # vec_new tampoco vive acá, por el mismo motivo que chan_new (ver la
    # nota de arriba): pasó a aceptar 0 o 1 argumento (capacidad inicial
    # opcional del buffer, ver scar_vec_new_<T> en codegen/) y este dict
    # solo modela aridad fija -- su propio bloque dedicado vive en
    # _infer/Call, justo debajo del de chan_new.
    "map_new": ([], TypeAnn(MAP_MARK, [T_I32, T_I32])),
    "sleep": ([T_F64], T_VOID),
    # panic(msg) termina la tarea (y en cascada, como cualquier
    # panic de runtime). Marca un camino imposible por invariante: cuenta como
    # salida para "todos los caminos terminan en return" (ver
    # parser.block_always_returns).
    "panic": ([T_STR], T_VOID),
    "read_pipe": ([T_I32], TypeAnn(RESULT, [T_STR])),
    "pipe_new": ([], TypeAnn(PIPE_MARK)),
    "file_open": ([T_STR, T_STR], TypeAnn(RESULT, [TypeAnn(FILE_MARK)])),
    "tcp_connect": ([T_STR, T_I32], TypeAnn(RESULT, [TypeAnn(SOCKET_MARK)])),
    "tcp_listen": ([T_I32], TypeAnn(RESULT, [TypeAnn(LISTENER_MARK)])),
}


# Todos los nombres que una llamada `nombre(...)` resuelve
# como builtin. Los de aridad variable o con reglas propias (chan_new,
# vec_new, inject_chan, accept_chan) tienen su bloque en _infer y no viven en
# BUILTIN_FN_TYPES. Son nombres reservados para todo lo que se puede llamar:
# una fn, task o extern con uno de estos nombres, o un parámetro o variable de
# tipo fn, es un error. Antes el builtin ganaba en silencio en los backends
# (y no siempre en los dos: `fn abs<T>` corría la del usuario en el nativo y
# el builtin en el intérprete). scripts/test_builtins_sync.py verifica que el
# intérprete y codegen implementen exactamente estos nombres.
NOMBRES_BUILTIN = frozenset(BUILTIN_FN_TYPES) | frozenset(
    {"chan_new", "vec_new", "inject_chan", "accept_chan"})


class TypeEnv:
    def __init__(self, parent=None):
        self.vars = {}
        self.moved = set()   # nombres movidos (transferidos a una tarea) EN ESTE scope
        # nombres que son dueños de un buffer de heap real EN ESTE scope --
        # p. ej. 'let x = a + b' (concatenación). Mismo
        # rol que owner_stack en codegen/, pero del lado del checker: acá
        # no se decide a quién liberar, se decide a quién hay que exigirle
        # la regla de movimiento en _move_if_needed pese a que
        # TypeAnn.is_copy() diga que str es Copy (is_copy() solo no alcanza:
        # es una propiedad del tipo, no de esta variable).
        self.owned_alloc = set()
        # nombres que son un PRÉSTAMO (alias a un slot que sigue viviendo
        # dentro de un Vec<T>/Map<K,V> ajeno) EN ESTE scope:
        # scar_vec_get_*/scar_map_get_* (codegen/) devuelven el MISMO
        # puntero que sigue en v.data[index]/el slot del Map, nunca una
        # copia (ver _let_creates_fresh_owner, que por eso YA excluye
        # a propósito a `.get()` de "fresco" del lado de codegen). Pero
        # nada de este lado impedía que ese alias se tratara como un
        # valor recién nacido y se "moviera" (push/set/spawn/chan.send)
        # a un SEGUNDO dueño mientras el contenedor original seguía
        # siendo el primero -- exactamente el aliasing que reprodujo
        # snake_completo.scar (`cuerpo.get(j)` -> `recortado.push(e)`)
        # bajo ASan como `Freed heap region`. `borrowed` es el tercer
        # estado que faltaba junto a `moved`/`owned_alloc`: ver
        # `_is_borrowing_get`/`_move_if_needed`.
        self.borrowed = set()
        # En `while let Some(p) = o`, p es el CONTENIDO de o
        # (p -> o): mover p mueve o (el nativo lo saca de o, como
        # Option::take; sin esto el intérprete seguiría viendo a o lleno).
        self.payload_of = {}
        # Nombres marcados movidos porque se movió el contenido de un
        # `while let Some(x) = o` (o queda en None, no colgando): la regla de
        # los loops (_check_loop_body) no los cuenta.
        self.moved_por_payload = set()
        # Nombres que NO se pueden reasignar EN ESTE scope, con el
        # tipo de declaración para el mensaje ('let', 'param', 'for', 'while let').
        self.inmutables = {}
        self.parent = parent

    def define(self, name, ty, mut=True, kind="let"):
        self.vars[name] = ty
        if mut:
            self.inmutables.pop(name, None)
        else:
            self.inmutables[name] = kind
        self.moved.discard(name)  # una nueva declaración siempre empieza sin mover
        # también los campos movidos de una declaración anterior
        self.moved = {m for m in self.moved if not m.startswith(name + ".")}
        self.owned_alloc.discard(name)  # ídem: sin dueña de heap hasta que se marque
        self.borrowed.discard(name)  # ídem: sin marca de préstamo hasta que se marque

    def get(self, name, node=None):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise TypeError_(
            f"variable no declarada: '{name}'",
            getattr(node, "line", None),
            getattr(node, "col", None),
            getattr(node, "archivo", None),
        )

    def inmutable_kind(self, name):
        """None si 'name' se puede reasignar; si no, cómo se declaró."""
        dueno = self._owner(name)
        if dueno is None:
            return None
        return dueno.inmutables.get(name)

    def _owner(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env
            env = env.parent
        return None

    def mark_moved(self, name):
        owner = self._owner(name)
        if owner is not None:
            owner.moved.add(name)
        env = self
        while env is not None:
            if name in env.payload_of:
                src = env.payload_of[name]
                self.mark_moved(src)  # ver payload_of
                dueno = self._owner(src)
                if dueno is not None:
                    dueno.moved_por_payload.add(src)
                break
            if name in env.vars:
                break
            env = env.parent

    def is_moved(self, name):
        owner = self._owner(name)
        return owner is not None and name in owner.moved

    # movimiento de un CAMPO. `let x = r.campo` mueve solo
    # ese campo: `r.otro` se sigue pudiendo usar, `r.campo` y `r` entero no
    # (hasta reasignar `r.campo` o `r`). Se guarda como "r.campo" en el
    # mismo conjunto `moved` del scope dueño de `r`.
    def mark_moved_path(self, path):
        owner = self._owner(path.split(".")[0])
        if owner is not None:
            owner.moved.add(path)

    def moved_paths_under(self, root):
        owner = self._owner(root)
        if owner is None:
            return []
        return sorted(m for m in owner.moved if m.startswith(root + "."))

    def moved_conflict(self, path):
        """El camino movido que impide leer `path` ("r.a.b"): el propio,
        uno que lo contiene ("r.a"), o None."""
        partes = path.split(".")
        owner = self._owner(partes[0])
        if owner is None:
            return None
        for i in range(2, len(partes) + 1):
            pre = ".".join(partes[:i])
            if pre in owner.moved:
                return pre
        return None

    def revive_path(self, path):
        owner = self._owner(path.split(".")[0])
        if owner is not None:
            owner.moved = {m for m in owner.moved if m != path and not m.startswith(path + ".")}

    def mark_owned_alloc(self, name):
        """Registra `name` como dueña de un buffer de heap real (hoy: el
        resultado de una concatenación de str) en el scope donde fue
        declarada. Calcado de mark_moved(), mismo motivo para buscar
        _owner() en vez de asumir el scope actual: LetStmt llama a esto
        justo después de env.define(), así que _owner(name) siempre
        encuentra el scope correcto (el que acaba de definir el nombre)."""
        owner = self._owner(name)
        if owner is not None:
            owner.owned_alloc.add(name)

    def is_owned_alloc(self, name):
        owner = self._owner(name)
        return owner is not None and name in owner.owned_alloc

    def mark_borrowed(self, name):
        """Registra `name` como un préstamo (alias a un valor que sigue
        viviendo dentro de un Vec<T>/Map<K,V> ajeno) en el scope donde fue
        declarada. Ver el comentario largo junto a `self.borrowed` en
        __init__ para el bug real que esto cierra."""
        owner = self._owner(name)
        if owner is not None:
            owner.borrowed.add(name)

    def is_borrowed(self, name):
        owner = self._owner(name)
        return owner is not None and name in owner.borrowed

    def child(self):
        return TypeEnv(self)


_NOMBRE_LIB_OK = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.+-]{0,63}$')


class Checker:
    _registrar_tipos = False
    def __init__(self):
        self.structs = {}     # nombre -> {campo: TypeAnn}
        # Los structs que son un enum bajado (enum_match.py), con
        # sus variantes [(nombre, cantidad de datos)].
        self.enums = {}
        self._match_reportados = set()
        self._mut_reportados = set()   # (nombre, posición del match)
        self.struct_type_params = {}  # nombre -> [str, ...], ej. {"Caja": ["T"]}
        # Nombre -> [str, ...], ej. {"identidad_debil": ["T"]}.
        # El cuerpo de una fn/task
        # genérica no necesita ningún camino especial en _infer porque un
        # TypeAnn("T") ya se comporta como un tipo opaco por construcción
        # (is_numeric()/self.structs.get()/etc. simplemente no lo reconocen,
        # así que 'x + 1' o 'x.campo' sobre un x:T ya se rechazan con los
        # mismos chequeos genéricos que rechazarían cualquier otro tipo
        # incompatible -- no hace falta un caso especial "es T, prohibir
        # operación"). Cada sitio de llamada fija el T concreto
        # (_check_call_args) y el codegen genera una copia por tipo.
        self.fn_type_params = {}
        self.functions = {}   # nombre -> FnDecl
        self.extern_functions = {}  # nombre -> ExternFnDecl
        self.extern_types = {}  # nombre -> ExternTypeDecl (FFI: ownership en la frontera)
        self.errors = []
        # nombres de fn/task con return_type Result<str> cuyo `return Ok(...)`
        # se resolvió como fresco -- ver _resolve_fresh_result_str_fns() y
        # su uso en _is_fresh_try_str().
        self.fresh_result_str_fns = set()
        self._mov_condicional = set()  # (id(env), nombre) movidos en una sola rama de un if
        # La segunda pasada por el cuerpo de un loop (ver
        # _check_vuelta_siguiente): None fuera de ella.
        self._vuelta = None
        # un frame por loop abierto: los envs de afuera del loop y el
        # estado de ellos en cada `break` (ver _check_loop_body)
        self._loops = []
        # Ver el branch de accept_chan() en
        # _infer y su prendido/apagado en _check_stmt/LetStmt.
        self._accept_chan_ok = False

    def check_program(self, program: Program):
        # Dos declaraciones con el mismo nombre.
        # Antes se aceptaban: el intérprete corría la ÚLTIMA y el nativo no
        # compilaba (dos backends, dos significados).
        vistos = {}
        for item in program.items:
            if isinstance(item, (FnDecl, ExternFnDecl, StructDecl)):
                clase = "struct" if isinstance(item, StructDecl) else "función"
                previo = vistos.get((clase, item.name))
                if previo is not None:
                    linea = getattr(previo, "line", None)
                    donde = f" (la primera está en la línea {linea})" if linea else ""
                    self._fail(f"'{item.name}' ya está declarada{donde}: dos {'structs' if clase == 'struct' else 'funciones'} "
                               f"no pueden llamarse igual", item)
                else:
                    vistos[(clase, item.name)] = item
        for item in program.items:
            if isinstance(item, StructDecl):
                self.structs[item.name] = dict(item.fields)
                self.struct_type_params[item.name] = list(item.type_params)
                if getattr(item, "enum_variantes", None):
                    self.enums[item.name] = item.enum_variantes
            elif isinstance(item, FnDecl):
                if item.name in NOMBRES_BUILTIN:
                    tipo = "task" if item.is_task else "fn"
                    self._fail(
                        f"'{item.name}' es una función builtin: una {tipo} no puede "
                        f"llamarse así (elige otro nombre)",
                        item,
                    )
                self.functions[item.name] = item
                self.fn_type_params[item.name] = list(item.type_params)
            elif isinstance(item, ExternFnDecl):
                self.extern_functions[item.name] = item
            elif isinstance(item, ExternTypeDecl):
                self._register_extern_type(item)
        self._check_extern_libs(program)
        self._check_handles_no_escapan(program)

        # Antes de chequear ningún cuerpo (el orden de declaración en el
        # archivo no debería importar -- 'orquestar' puede aparecer ANTES
        # que 'producir_str' en el source): resuelve qué fn/task devuelven
        # siempre un Result<str> fresco. Ver _resolve_fresh_result_str_fns.
        self._resolve_fresh_result_str_fns(program)

        # Qué parámetros struct consume cada fn normal (ver
        # fresh_owned.resolve_consumed_params, la MISMA tabla que usa
        # codegen/). En el llamador, el argumento de un parámetro consumido
        # queda movido -- ver el bloque de Call en _infer.
        fns = {
            item.name: (item, [p.type_ann or T_I32 for p in item.params])
            for item in program.items
            if isinstance(item, FnDecl) and not item.is_task and not item.type_params
        }
        self.consumed_motivos = {}
        self.consumed_params = resolve_consumed_params(fns, lambda t: t.name in self.structs, self.structs,
                                                       motivos=self.consumed_motivos)
        # Dónde y por qué se movió cada variable (la última vez), para
        # que el error de usarla después (o en la vuelta siguiente de un
        # loop) señale esa línea y diga el motivo.
        self._donde_mov = {}
        self._motivo_mov = None
        # Lo mismo para un parámetro Option<Struct> cuyo CONTENIDO
        # la fn puede quedarse (la misma tabla que usa codegen/).
        self.consumed_option_params = resolve_consumed_option_params(
            fns, lambda t: t.name == "Option" and bool(t.args) and t.args[0].name in self.structs)
        # qué parámetros struct puede devolver cada fn como el mismo
        # objeto (ver fresh_owned.resolve_returned_params y _move_if_needed).
        self.returned_params = resolve_returned_params(fns, lambda t: t.name in self.structs)

        for item in program.items:
            if isinstance(item, FnDecl):
                self._check_fn(item)
            elif isinstance(item, ExternFnDecl):
                self._check_extern_fn(item)
        if not self.errors:
            self._revisar_orden_de_lugares(program)

        return self.errors

    def _es_referencia(self, ty) -> bool:
        """Un valor que el intérprete comparte entre quien lo tiene
        y quien lo recibe (un struct, un Vec, un Map, un handle), al que una
        fn le puede cambiar lo de adentro sin reemplazarlo."""
        if ty is None:
            return False
        if ty.name in ("Vec", "Map", "Chan", "Task", "File", "Pipe", "Socket", "Listener"):
            return True
        if ty.name in self.structs and ty.name not in self.enums:
            return True
        if ty.name in ("Option", "Result"):
            return any(self._es_referencia(a) for a in ty.args)
        return False

    def _revisar_orden_de_lugares(self, program):
        """Un campo que es un struct, un Vec o un Map (`d.s`) y,
        más a la derecha en la misma expresión, una llamada que puede
        reasignar ese campo (`g(d.s, f(d))` con una f que hace `p.s = ...`).

        El intérprete lee `d.s` primero: si f reemplaza el campo, g recibe el
        objeto viejo, que ya no está en `d`; si f solo cambia lo de adentro
        (o no llega a reemplazarlo), g recibe el mismo objeto que sigue en
        `d`. El nativo libera el objeto viejo al reasignar el campo, así que
        no puede hacer las dos cosas: copiarlo antes pierde los cambios del
        segundo caso, y no copiarlo lee memoria liberada en el primero. Es
        un error en los dos backends; con un número o un str no lo es (se lee
        antes, y vale lo mismo en los dos). Qué fn puede reasignar qué campo
        lo dice lugares.py, el mismo análisis que usa el codegen."""
        conocidas = set(NOMBRES_BUILTIN) | set(self.extern_functions)
        efecto = lugares.reasignaciones(program.items, conocidas)
        for item in program.items:
            if not isinstance(item, FnDecl):
                continue
            for n in lugares._recorrer(item.body):
                partes = lugares.en_orden(n)
                for i, h in enumerate(partes):
                    c = lugares.camino(h)
                    if c is None or not c[1] or not self._es_referencia(getattr(h, "tipo_lugar", None)):
                        continue
                    for j in range(i + 1, len(partes)):
                        quien = lugares.puede_reemplazar(efecto, conocidas, partes[j], h, lambda x: x == c[0])
                        if quien is None:
                            continue
                        texto = ".".join((c[0],) + c[1])
                        self._fail(
                            f"'{texto}' se usa antes de una llamada a '{quien}' que puede reasignarlo, "
                            f"en la misma expresión: no queda claro si se usa el valor de antes o el de "
                            f"después. Haz la llamada antes, en su propia línea (let x = ...)",
                            h,
                        )
                        break

    def _resolve_fresh_result_str_fns(self, program: Program):
        """Contrato único de str (ver codegen._str_return_propio): toda
        fn/task que devuelve `Result<str>` entrega un str propio en su `Ok`,
        así que `let x = f()?` siempre deja a `x` dueña."""
        self.fresh_result_str_fns = {
            item.name for item in program.items
            if isinstance(item, FnDecl) and not item.type_params
            and item.return_type is not None and item.return_type.name == "Result"
            and item.return_type.args and item.return_type.args[0] == T_STR
        }

    def _is_str_owned_call(self, expr, ty) -> bool:
        """Contrato único de str: el `str` que devuelve una fn/task de
        usuario (también una instancia genérica con T=str), una extern fn o
        `.join()` sobre una Task<str> es siempre propio de quien llama -- el
        mismo criterio que usa codegen para hacerlo dueño. Así el checker
        no deja usar el valor después de moverlo a un spawn/send/push."""
        if ty != T_STR:
            return False
        if isinstance(expr, Call) and isinstance(expr.callee, Ident):
            n = expr.callee.name
            return n in self.functions or n in self.extern_functions or n in ("chr", "a_texto")
        # el str que devuelve vec.replace() salió del Vec: es propio
        return isinstance(expr, MethodCall) and expr.method in ("join", "replace")

    def _no_tapar_builtin(self, nombre, ty, node):
        """Una variable o parámetro de tipo fn no puede
        llamarse como un builtin. El checker resolvía `len(x)` a la variable
        y los dos backends al builtin: el programa compilaba y hacía otra
        cosa. Una variable común con ese nombre no se puede llamar, así que
        no es ambigua y sigue permitida."""
        if ty is not None and ty.name == FN_MARK and nombre in NOMBRES_BUILTIN:
            self._fail(
                f"'{nombre}' es una función builtin: una variable de tipo fn no "
                f"puede llamarse así (elige otro nombre)",
                node,
            )

    def _fail(self, msg, node=None):
        """Registra un error de tipo. `node` es el nodo AST más específico
        disponible en el sitio de la falla (todo nodo pasa
        por `.at()` en el parser y trae `.line`/`.col`, 1-based). Si `node`
        es None o nunca pasó por `.at()` (line/col en None), el error queda
        sin ubicación, igual que antes -- `cli.py`/`_source_context` ya
        saben caer de vuelta al mensaje plano en ese caso."""
        self.errors.append(
            TypeError_(msg, getattr(node, "line", None), getattr(node, "col", None),
                       getattr(node, "archivo", None))
        )

    def _register_extern_type(self, decl: ExternTypeDecl):
        """FFI, ownership en la frontera: registra un
        tipo opaco respaldado por void*. Choque de nombres con structs/
        primitivos/otro extern type se rechaza acá mismo -- un 'ZStream'
        que colisionara con un struct de usuario dejaría ambiguo qué regla
        de ownership aplica (¿la de struct, con deepcopy/free recursivo, o
        la de FFI, sin ninguna de las dos?), así que no se permite."""
        if decl.name in self.extern_types:
            self._fail(f"extern type '{decl.name}' ya fue declarado", decl)
            return
        if decl.name in self.structs:
            self._fail(
                f"extern type '{decl.name}' choca con un 'struct' del mismo nombre",
                decl,
            )
            return
        _RESERVED = ({"i32", "i64", "f64", "str", "bool", "void", "Option", "Result"}
                     | {TASK_MARK, CHAN_MARK, VEC_MARK, MAP_MARK, PIPE_MARK,
                        FILE_MARK, SOCKET_MARK, LISTENER_MARK})
        if decl.name in _RESERVED:
            self._fail(
                f"extern type '{decl.name}' choca con un tipo integrado de SCAR",
                decl,
            )
            return
        self.extern_types[decl.name] = decl

    def _pipe_ok(self, ty):
        """Tipos que el pipe del worker aislado sabe llevar (misma regla que
        Codegen._pipe_type_ok y ffi_worker.library_pipe_eligible)."""
        if ty is None:
            return False
        if ty.name in ("i32", "i64", "f64", "bool", "str"):
            return True
        if ty.name == VEC_MARK and ty.args and ty.args[0].name in ("i32", "i64", "f64", "bool"):
            return True  # viaja por el pipe (y vuelve)
        return ty.name in self.extern_types and not ty.args

    def _check_extern_libs(self, program):
        """el modo de cada librería se declara, no se deduce. Por
        defecto las extern fn de una librería corren en un proceso worker
        aislado; con `extern lib "x" en_proceso` corren dentro del proceso.
        Antes, una librería pasaba a correr en el proceso sin aviso apenas
        UNA de sus funciones recibía un callback o un struct por valor (el
        pipe no los lleva): agregar una función le cambiaba el aislamiento
        a todas las demás."""
        self.en_proceso = {}
        usadas = {}
        # El nombre va al comando del
        # compilador (-l<nombre>) y al código C del worker FFI. Solo se acepta
        # un nombre de librería simple (letras, dígitos, _ . + -, sin espacios,
        # comillas, barras ni un '-' al principio): así no se puede colar C ni
        # flags del compilador.
        for item in program.items:
            lib = getattr(item, "library", None) if isinstance(item, (ExternLibDecl, ExternFnDecl)) else None
            if lib is not None and not _NOMBRE_LIB_OK.match(lib):
                self._fail(f"nombre de librería inválido \"{lib}\": solo letras, dígitos y _ . + - "
                           f"(sin espacios, comillas, barras ni un '-' al principio), por ejemplo from \"m\"", item)
                item.library = "_invalida_"
        for item in program.items:
            if isinstance(item, ExternLibDecl):
                if item.library in self.en_proceso:
                    self._fail(f"la librería \"{item.library}\" ya está declarada con 'extern lib'", item)
                self.en_proceso[item.library] = item
            elif isinstance(item, ExternFnDecl) and item.library is not None:
                usadas.setdefault(item.library, []).append(item)
        for lib, decl in self.en_proceso.items():
            if lib not in usadas:
                self._fail(
                    f"'extern lib \"{lib}\" en_proceso': ninguna extern fn usa "
                    f"from \"{lib}\"", decl)
        for lib, decls in usadas.items():
            if lib in self.en_proceso:
                continue
            for d in decls:
                motivo = None
                for p in d.params:
                    if p.type_ann is not None and p.type_ann.name == VEC_MARK:
                        continue  # un Vec que no cruza lo dice _check_extern_fn
                    if p.type_ann is not None and not self._pipe_ok(p.type_ann):
                        if p.type_ann.name == FN_MARK:
                            motivo = f"recibe un callback ('{p.name}')"
                        else:
                            motivo = f"recibe {p.type_ann!r} por valor ('{p.name}')"
                        break
                ret = d.return_type
                inner = ret.args[0] if ret is not None and ret.name == "Result" and ret.args else ret
                if motivo is None and inner is not None and inner.name != "void" and not self._pipe_ok(inner):
                    motivo = f"devuelve {ret!r}"
                if motivo is not None:
                    self._fail(
                        f"extern '{d.name}' {motivo}, y eso no puede cruzar al proceso "
                        f"aislado donde corren por defecto las librerías -- declárala "
                        f"para que corra dentro del proceso: extern lib \"{lib}\" en_proceso",
                        d)
                    break

    def _cruza_ffi(self, ty):
        """types_.ffi_tipo_ok con los structs del programa; un struct genérico o
        un enum no cruza."""
        excluidos = {n for n in self.structs if self.struct_type_params.get(n)} | set(self.enums)
        return types_.ffi_tipo_ok(ty, self.structs, self.extern_types, excluidos)

    def _check_extern_fn(self, decl: ExternFnDecl):
        # Sin cuerpo que recorrer -- solo se valida la firma en sí.
        if decl.abi != "C":
            self._fail(
                f"extern '{decl.name}': ABI {decl.abi!r} no soportada, "
                "solo \"C\" por ahora",
                decl,
            )
        if decl.name in self.functions:
            self._fail(
                f"extern '{decl.name}' choca con una función 'fn' del mismo nombre",
                decl,
            )
        if decl.name in NOMBRES_BUILTIN:
            self._fail(
                f"extern '{decl.name}' choca con una función builtin del mismo nombre",
                decl,
            )
        for p in decl.params:
            # Un callback que C invoca no puede devolver str. C no
            # tiene cómo liberar un str de SCAR, así que el valor quedaría
            # sin dueño (el nativo lo perdía). Se rechaza acá, igual en los
            # dos backends, con un mensaje que dice qué hacer.
            if (p.type_ann is not None and p.type_ann.name == FN_MARK
                    and p.type_ann.args and p.type_ann.args[-1].name == "str"):
                self._fail(
                    f"extern '{decl.name}': el callback '{p.name}' devuelve str, "
                    f"y C no tiene cómo liberar un str de SCAR (quedaría sin "
                    f"dueño) -- devuelve un valor escalar, o escribe en un "
                    f"buffer de C con otra extern fn",
                    p,
                )
            if p.type_ann is not None and p.type_ann.name == VEC_MARK:
                # Un Vec de escalares pasa a
                # C como puntero + largo (int64_t), prestado durante la
                # llamada; lo que C cambie en los elementos vuelve al Vec.
                elem = p.type_ann.args[0] if p.type_ann.args else T_I32
                if elem.name not in ("i32", "i64", "f64", "bool"):
                    self._fail(
                        f"extern '{decl.name}': el parámetro '{p.name}' es {p.type_ann!r}; "
                        f"a C solo cruza un Vec de i32, i64, f64 o bool (como puntero + largo)",
                        p,
                    )
                elif p.consumes:
                    self._fail(
                        f"extern '{decl.name}': 'own' no va en un Vec: C lo recibe prestado "
                        f"durante la llamada y no se lo queda",
                        p,
                    )
                continue
            if p.type_ann is None or not self._cruza_ffi(p.type_ann):
                self._fail(
                    f"extern '{decl.name}': el parámetro '{p.name}' tiene tipo "
                    f"{p.type_ann!r}, no soportado en la frontera FFI "
                    f"(soportados: {sorted(FFI_SUPPORTED_TYPES)}, o un tipo "
                    f"declarado con 'extern type')",
                    p,
                )
            # 'own' solo tiene sentido sobre un handle opaco:
            # 'own i32' no significa nada (i32 es Copy, nunca se mueve), y
            # permitirlo sin más generaría una expectativa de ownership que
            # _move_if_needed nunca cumpliría para un tipo Copy.
            if p.consumes and p.type_ann is not None and p.type_ann.name not in self.extern_types:
                self._fail(
                    f"extern '{decl.name}': 'own' en el parámetro '{p.name}' "
                    f"no es válido sobre {p.type_ann!r} -- 'own' solo aplica "
                    f"a un tipo declarado con 'extern type'",
                    p,
                )
        ret = decl.return_type
        if ret is not None and ret.name != "void":
            if ret.name == "Result":
                # NULL de C -> Err(...). Acá solo se exige que T sea
                # FFI-válido en general (mismo criterio que un parámetro o
                # un retorno simple, vía _cruza_ffi) -- si T además tiene
                # una representación con NULL (lo único que el backend de
                # C puede convertir en Err automáticamente) es un chequeo
                # más estricto que hace codegen/ con su propio criterio,
                # igual que ya pasa con el resto de la validación FFI.
                inner = ret.args[0] if ret.args else None
                if inner is None or not self._cruza_ffi(inner):
                    self._fail(
                        f"extern '{decl.name}': el tipo de retorno "
                        f"Result<T> necesita un T soportado en la "
                        f"frontera FFI (soportados: "
                        f"{sorted(FFI_SUPPORTED_TYPES)}, o un tipo "
                        f"declarado con 'extern type'), se dio {inner!r}",
                        decl,
                    )
            elif not self._cruza_ffi(ret):
                self._fail(
                    f"extern '{decl.name}': el tipo de retorno {ret!r} "
                    f"no soportado en la frontera FFI (soportados: "
                    f"{sorted(FFI_SUPPORTED_TYPES)}, un tipo declarado con "
                    f"'extern type', Result<T> de uno de esos tipos, o "
                    f"vacío para 'void')",
                    decl,
                )

    def _contiene_task(self, ty, vistos=None):
        """si `ty` lleva adentro el handle de una tarea (Task<T, t>),
        a cualquier profundidad: Option/Result/Vec/Map/Chan y campos de struct."""
        if not isinstance(ty, TypeAnn):
            return False
        if ty.name == TASK_MARK:
            return True
        vistos = set() if vistos is None else vistos
        if ty.name in self.structs and ty.name not in vistos:
            vistos.add(ty.name)
            if any(self._contiene_task(f, vistos) for f in self.structs[ty.name].values()):
                return True
        return any(self._contiene_task(a, vistos) for a in ty.args)

    def _chan_con_task(self, ty, vistos=None):
        """Un Chan cuyo elemento lleva un handle de tarea, a cualquier profundidad."""
        if not isinstance(ty, TypeAnn) or ty.name == TASK_MARK:
            return False
        vistos = set() if vistos is None else vistos
        if ty.name == CHAN_MARK and ty.args and self._contiene_task(ty.args[0]):
            return True
        if ty.name in self.structs and ty.name not in vistos:
            vistos.add(ty.name)
            if any(self._chan_con_task(f, vistos) for f in self.structs[ty.name].values()):
                return True
        return any(self._chan_con_task(a, vistos) for a in ty.args)

    def _check_handles_no_escapan(self, program: Program):
        """una tarea lanzada es de la región de quien la lanzó, que la
        espera o la cancela al terminar (concurrencia estructurada). Su handle no
        puede salir de esa región: ni devuelto por una task (su región ya terminó
        cuando alguien lo recibe) ni por un canal (puede llegar a otra región).
        Sí puede ir en Option/Vec/Map/structs locales y pasarse a fns o a tareas
        hijas, que terminan antes que la región dueña."""
        motivo = ("la tarea lanzada es de la región que la lanzó, que la espera o "
                  "la cancela al terminar")
        for item in program.items:
            if isinstance(item, StructDecl):
                for campo, fty in item.fields:
                    if self._chan_con_task(fty):
                        self._fail(f"campo '{item.name}.{campo}': un canal no puede llevar el "
                                   f"handle de una tarea ({fty!r}): {motivo}", item)
            elif isinstance(item, FnDecl):
                if item.is_task and self._contiene_task(item.return_type):
                    self._fail(f"'task {item.name}' no puede devolver el handle de una tarea "
                               f"({item.return_type!r}): {motivo}, así que cuando alguien "
                               f"lo recibiera esa región ya habría terminado", item)
                tys = [p.type_ann for p in item.params] + list(item.accepts) + [item.return_type]
                for t in tys:
                    if self._chan_con_task(t):
                        self._fail(f"'{item.name}': un canal no puede llevar el handle de una "
                                   f"tarea ({t!r}): {motivo}", item)
                        break

    def _check_fn(self, decl: FnDecl):
        antes = set(types_.PARAMS_COPIA)
        types_.PARAMS_COPIA.clear()
        types_.PARAMS_COPIA.update(t for t, b in (getattr(decl, "type_bounds", None) or {}).items()
                                   if b == "Numeric")
        try:
            self._check_fn_cuerpo(decl)
        finally:
            types_.PARAMS_COPIA.clear()
            types_.PARAMS_COPIA.update(antes)

    def _check_fn_cuerpo(self, decl: FnDecl):
        # 'accepts' solo tiene sentido en una 'task' (una 'fn'
        # normal no es un handle vivo al que se le pueda inyectar nada en
        # runtime -- termina y retorna antes de que exista una segunda
        # oportunidad de recibir algo), y cada tipo declarado tiene que
        # ser Chan<T> de verdad (es la única forma de mutación en runtime:
        # 'accepts i32' o 'accepts Vec<T>' no tienen mecanismo de
        # entrega detrás, inject_chan()/accept_chan() son específicos de
        # Chan<T>).
        # `main` devuelve nada (sale con 0) o un i32, que es el
        # código de salida del proceso en los dos backends. Cualquier otro
        # tipo (f64, str...) no tiene una salida que los dos den igual.
        if (decl.name == "main" and not decl.is_task and decl.return_type is not None
                and decl.return_type not in (T_VOID, T_I32)):
            self._fail(
                f"'main' devuelve nada, un i32 o un Result<i32> (el código de "
                f"salida del programa), no {decl.return_type!r}",
                decl,
            )
        if getattr(decl, "exportada", False):
            self._check_exportada(decl)
        if decl.accepts and not decl.is_task:
            self._fail(
                f"'{decl.name}': la cláusula 'accepts' solo es válida en una "
                f"'task', no en una 'fn'",
                decl,
            )
        for acc_ty in decl.accepts:
            if acc_ty.name != CHAN_MARK or not acc_ty.args:
                self._fail(
                    f"'{decl.name}': 'accepts' solo admite tipos Chan<T>, se "
                    f"declaró {acc_ty!r}",
                    decl,
                )
        env = TypeEnv()
        for p in decl.params:
            self._no_tapar_builtin(p.name, p.type_ann or T_I32, p if getattr(p, "line", None) else decl)
            env.define(p.name, p.type_ann or T_I32, mut=False, kind="param")  # sin anotación -> asume i32 (prototipo)
        ret_ty = decl.return_type or T_VOID
        try:
            self._check_block(decl.body, env, decl, ret_ty)
        except TypeError_ as e:
            self.errors.append(e)
        # Una fn/task con tipo de retorno que podía llegar al
        # final sin `return` devolvía None en el intérprete (y lo imprimía como
        # si fuera un i32) y basura en C (la función se caía del final:
        # comportamiento indefinido).
        if ret_ty != T_VOID and not block_always_returns(decl.body):
            self.errors.append(TypeError_(
                f"'{decl.name}' declara que devuelve {ret_ty!r} pero puede llegar al final sin "
                f"'return' (falta un 'return' al final, o un 'else' que también retorne)",
                getattr(decl, "line", None), getattr(decl, "col", None), getattr(decl, "archivo", None)))

    def _check_block(self, block: Block, env: TypeEnv, fn: FnDecl, ret_ty: TypeAnn):
        for stmt in block.stmts:
            self._check_stmt(stmt, env, fn, ret_ty)

    def _chequear_contrato_fn_valor(self, expr, target):
        """el tipo `fn(...)` tiene un contrato fijo, porque quien
        llama a través de él no sabe a qué fn llama: un Vec/Map que recibe se
        mueve (como en toda fn), un struct se PRESTA, y lo que devuelve es
        nuevo. Una fn que se queda con un struct que recibe, o que devuelve un
        struct que recibió, hace otra cosa según cuál sea: no se puede usar
        como valor (en una llamada directa el checker sí sabe y mueve el
        argumento)."""
        nombre = target.name
        consumidos = set(getattr(self, "consumed_params", {}).get(nombre, ()))
        consumidos |= set(getattr(self, "consumed_option_params", {}).get(nombre, ()))
        devueltos = set(getattr(self, "returned_params", {}).get(nombre, ()))
        for k in sorted(consumidos | devueltos):
            if k >= len(target.params):
                continue
            p = target.params[k]
            if k in devueltos:
                porque = f"devuelve su parámetro '{p.name}'"
            else:
                motivo = getattr(self, "consumed_motivos", {}).get(nombre, {}).get(k)
                porque = f"se queda con su parámetro '{p.name}'" + (f" ({motivo})" if motivo else "")
            self._fail(
                f"'{nombre}' no se puede usar como valor: {porque}. Una función guardada en "
                f"una variable presta los structs que recibe y devuelve algo nuevo; llámala "
                f"directo (`{nombre}(...)`), o haz que devuelva una copia",
                expr,
            )
            return

    @staticmethod
    def _es_contenedor_movido(ty):
        if ty.name in (VEC_MARK, MAP_MARK):
            return True
        return ty.name == OPTION_MARK and bool(ty.args) and ty.args[0].name in (VEC_MARK, MAP_MARK)

    def _param_contenedor(self, nombre, k):
        """Para lugares.ligada_se_mueve: ¿el parámetro k de la fn de usuario
        `nombre` es un Vec/Map (que la fn se queda)? None si no es de usuario."""
        decl = self.functions.get(nombre)
        if decl is None:
            return None if nombre not in NOMBRES_BUILTIN else False
        if k >= len(decl.params):
            return False
        t = decl.params[k].type_ann
        return t is None or self._es_contenedor_movido(t)

    def _ramas_excluyentes(self, env, ramas):
        """Chequea ramas que se excluyen entre sí (las de un if/else, también
        las de un if que da un valor): cada función de `ramas` recibe un env
        hijo, chequea su rama y devuelve True si la rama nunca sigue de largo.

        Ejemplo: un if/else donde CADA rama hace .push(elem) en una variable
        distinta (exactamente una rama corre). mark_moved()/mark_borrowed()/
        mark_owned_alloc() escriben en el scope DUEÑO (ver TypeEnv._owner()),
        no en el child env de la rama que se está chequeando, así que se
        registra un snapshot de
        moved/borrowed/owned_alloc de TODA la cadena de ancestros antes de
        la primera rama, restaurarlo antes de cada rama siguiente, y al final
        fusionar con unión (si una rama mueve 'x' y la otra no, 'x' queda
        movida para el código que sigue -- conservador y correcto, porque no
        se sabe estáticamente cuál rama corrió).

        Una rama que nunca sigue
        de largo (`return`, `break`) no llega al código que sigue, así que
        lo que movió no cuenta después. Lo que se mueve solo en
        algunas ramas es un movimiento condicional (ver _check_loop_body)."""
        # Solo los scopes que declaran variables
        # pueden cambiar (mark_moved/mark_borrowed/mark_owned_alloc escriben
        # en el scope DUEÑO del nombre). Una cadena de 3.000 else-if apila
        # miles de scopes vacíos: copiar los conjuntos de TODOS en cada nivel
        # era cuadrático en memoria y tiempo (90 s y sin memoria).
        ancestors = []
        e = env
        while e is not None:
            if e.vars:
                ancestors.append(e)
            e = e.parent
        snapshot = [(set(a.moved), set(a.borrowed), set(a.owned_alloc)) for a in ancestors]
        estados = []
        for i, rama in enumerate(ramas):
            if i > 0:
                for a, (mv, br, oa) in zip(ancestors, snapshot):
                    a.moved, a.borrowed, a.owned_alloc = set(mv), set(br), set(oa)
            corta = rama(env.child())
            estado = [(set(a.moved), set(a.borrowed), set(a.owned_alloc)) for a in ancestors]
            estados.append(snapshot if corta else estado)
        for j, a in enumerate(ancestors):
            base_mv, base_br, base_oa = snapshot[j]
            movidas = [est[j][0] for est in estados]
            todas = set().union(*movidas)
            comunes = set.intersection(*[set(m) for m in movidas]) if movidas else set()
            for n in (todas - comunes) - base_mv:
                self._mov_condicional.add((id(a), n))
            a.moved = base_mv | todas
            a.borrowed = base_br | set().union(*[est[j][1] for est in estados])
            a.owned_alloc = base_oa | set().union(*[est[j][2] for est in estados])

    def _infer_if_expr(self, expr, env, fn, ret_ty, expected_ty):
        """`if c { .. a } else { .. b }` como expresión. Cada rama es un bloque cuya última sentencia es la
        expresión que da el valor; las de antes se chequean como siempre, en
        su propio scope, y las dos ramas se excluyen (como en un IfStmt). El
        tipo sale de lo que espera el lugar o de la primera rama con valor;
        enteros mezclados con f64 se amplían a f64. Una rama que termina en
        panic(..) no da valor. Adentro de las ramas no va `return` ni un
        `break` del loop de afuera: el valor tiene que salir del if."""
        self._sin_arreglo(expr.cond, "la condición de un if")
        cond_ty = self._infer(expr.cond, env, fn, ret_ty)
        if cond_ty != T_BOOL:
            self._fail(f"la condición de 'if' debe ser bool, no {cond_ty!r}", expr.cond)
        valores = []  # (expr, tipo) por rama con valor

        def rama(block):
            def chequear(child):
                stmts = block.stmts
                if stmts and isinstance(stmts[-1], (ReturnStmt, BreakStmt)):
                    self._sin_salidas(stmts)
                    return True
                if not stmts or not isinstance(stmts[-1], ExprStmt):
                    self._fail("cada rama de un if que da un valor termina en la expresión "
                               "que da ese valor (por ejemplo `if c { 1 } else { 2 }`)",
                               stmts[-1] if stmts else block)
                    for st in stmts:
                        self._check_stmt(st, child, fn, ret_ty)
                    return False
                self._sin_salidas(stmts)
                for st in stmts[:-1]:
                    self._check_stmt(st, child, fn, ret_ty)
                ultima = stmts[-1]
                if es_panic(ultima):
                    self._check_stmt(ultima, child, fn, ret_ty)
                    return True
                anotado = (expected_ty if expected_ty is not None and expected_ty != T_VOID
                           else (valores[0][1] if valores else None))
                t = self._infer(ultima.expr, child, fn, ret_ty, expected_ty=anotado)
                valores.append((ultima.expr, t))
                return False
            return chequear

        self._ramas_excluyentes(env, [rama(expr.then_block), rama(expr.else_block)])
        if not valores:
            self._fail("las dos ramas de este if terminan en panic: no da ningún valor", expr)
            return T_VOID
        tipo = expected_ty if expected_ty is not None and expected_ty != T_VOID else None
        if tipo is None:
            tipo = valores[0][1]
            for _e, t in valores[1:]:
                if (tipo != t and tipo.name in ("i32", "i64", "f64") and t.name in ("i32", "i64", "f64")
                        and numeric_mix_ok(tipo, t)):
                    tipo = numeric_result(tipo, t)
        if tipo == T_VOID:
            self._fail("las ramas de este if no dan ningún valor (terminan en algo que "
                       "devuelve void)", expr)
            return T_VOID
        for e, t in valores:
            if not self._compatible(tipo, t, e):
                self._fail(f"las dos ramas de un if que da un valor tienen que dar el mismo "
                           f"tipo: se esperaba {tipo!r}, se dio {t!r}{self._pista(tipo, t)}", e)
        expr.tipo_if = tipo
        return tipo

    def _sin_salidas(self, stmts, en_loop=False):
        """Un `return`, o un `break` que saldría del loop de afuera, no puede
        ir en una rama de un if que da un valor."""
        for st in stmts:
            if isinstance(st, ReturnStmt):
                self._fail("un if que da un valor no puede tener `return` adentro: el valor "
                           "sale por la última expresión de cada rama (para salir de la fn, "
                           "usa un if normal)", st)
            elif isinstance(st, BreakStmt) and not en_loop:
                self._fail("un if que da un valor no puede tener un `break` del loop de afuera "
                           "(usa un if normal)", st)
            elif isinstance(st, ContinueStmt) and not en_loop:
                self._fail("un if que da un valor no puede tener un `continue` del loop de afuera "
                           "(usa un if normal)", st)
            elif isinstance(st, IfStmt):
                self._sin_salidas(st.then_block.stmts, en_loop)
                if st.else_block is not None:
                    self._sin_salidas(st.else_block.stmts, en_loop)
            elif isinstance(st, (WhileStmt, WhileLetStmt, ForStmt)):
                self._sin_salidas(st.body.stmts, True)

    def _sin_arreglo(self, expr, donde):
        """Un arreglo [..] arma un Vec nuevo con varias sentencias; en la
        cabecera de un if/while/for no hay dónde ponerlas ni dónde soltar el
        Vec (en un while se evaluaría una vez por vuelta). Se pide guardarlo
        en una variable antes, como haría uno a mano con vec_new()."""
        pila = [expr]
        while pila:
            n = pila.pop()
            if isinstance(n, ArrayLit):
                self._fail(f"un arreglo [..] no puede ir en {donde}: guárdalo antes "
                           f"en una variable (let v = [..])", n)
                return
            if isinstance(n, IfExpr):
                self._fail(f"un if que da un valor no puede ir en {donde}: guárdalo antes "
                           f"en una variable (let x = if ..)", n)
                return
            if isinstance(n, (Node, list, tuple, dict)):
                pila.extend(x for x in hijos(n) if isinstance(x, (Node, list, tuple, dict)))

    def _check_stmt(self, stmt, env: TypeEnv, fn: FnDecl, ret_ty: TypeAnn):
        if isinstance(stmt, LetStmt):
            if stmt.declared_type is not None and self._chan_con_task(stmt.declared_type):
                self._fail(f"un canal no puede llevar el handle de una tarea "
                           f"({stmt.declared_type!r}): la tarea lanzada es de la región que "
                           f"la lanzó, que la espera o la cancela al terminar", stmt)
            new_mark = marca_new_generico(stmt.expr)
            if (
                stmt.declared_type is not None
                and new_mark in (CHAN_MARK, VEC_MARK)
                and stmt.expr.args
            ):
                # Camino CON anotación (`let ch: Chan<T> = chan_new(cap)` /
                # `let v: Vec<T> = vec_new(cap)`): a diferencia del camino
                # sin anotación (que sí pasa por _infer/Call, más abajo en
                # el 'else' final, y ahí valida 'cap' -- de ahí el
                # 'stmt.declared_type is not None' acá, para no validar dos
                # veces lo mismo), este branch entero nunca llama a
                # _infer(stmt.expr, ...) -- toma el tipo directo de la
                # anotación (ver 'ty = stmt.declared_type' más abajo) porque
                # de ahí sale el T real, no de inferir la llamada. Sin esta
                # rama, 'let ch: Chan<Punto> = chan_new("no es i32")'
                # typechequearía limpio: el argumento de capacidad quedaría
                # sin validar en el único camino que de verdad usan los
                # programas con anotación explícita (el que ya prueban
                # test_chan_struct_pending.scar y 40_chan_struct_minimo.scar).
                # vec_new(cap) se suma al mismo branch (Fase de capacidad
                # inicial de Vec, ver _vec_c_type en codegen/): mismo
                # motivo de fondo, mismo chequeo, 'cap' es un hint de
                # runtime (arranca el buffer en ese tamaño en vez de en 0),
                # no algo de lo que se infiera T.
                cap_ty = self._infer(stmt.expr.args[0], env, fn, ret_ty, expected_ty=T_I32)
                if cap_ty != T_I32:
                    self._fail(
                        f"'{stmt.name}': la capacidad de {stmt.expr.callee.name}() "
                        f"debe ser i32, se dio {cap_ty!r}",
                        stmt.expr.args[0],
                    )
            if stmt.declared_type is not None and new_mark is not None:
                # chan_new()/vec_new() no toman argumentos, así que a diferencia
                # de Ok(x)/Some(x) no hay valor del que inferir T -- por eso
                # ambos quedan fijos a i32 en BUILTIN_FN_TYPES si no hay
                # anotación. Una anotación explícita en el 'let' es el único
                # punto donde el programa puede decir qué T quiere.
                if stmt.declared_type.name != new_mark or not stmt.declared_type.args:
                    self._fail(
                        f"'{stmt.name}': la anotación de {stmt.expr.callee.name}() "
                        f"debe ser {new_mark}<T>, se dio {stmt.declared_type!r}",
                        stmt,
                    )
                    ty = TypeAnn(new_mark, [T_I32])
                else:
                    ty = stmt.declared_type
            elif stmt.declared_type is not None and isinstance(stmt.expr, NoneExpr):
                # Mismo problema de fondo que chan_new()/vec_new()/map_new(): 'None'
                # tampoco trae ningún valor del que inferir T, así que sin esta rama
                # quedaba fijo a Option<i32> (ver docstring del módulo). Una
                # anotación explícita en el 'let' es, igual que en esos casos, el
                # único punto donde el programa puede decir qué T quiere.
                if stmt.declared_type.name != OPTION_MARK or not stmt.declared_type.args:
                    self._fail(
                        f"'{stmt.name}': la anotación de None debe ser Option<T>, "
                        f"se dio {stmt.declared_type!r}",
                        stmt,
                    )
                    ty = TypeAnn(OPTION_MARK, [T_I32])
                else:
                    ty = stmt.declared_type
            elif (
                stmt.declared_type is not None
                and isinstance(stmt.expr, Call)
                and isinstance(stmt.expr.callee, Ident)
                and stmt.expr.callee.name == "accept_chan"
            ):
                # Mismo problema de fondo que None/chan_new() de
                # arriba -- accept_chan() no tiene de qué inferir el T de
                # Chan<T>, así que la anotación del 'let' es la única
                # fuente. A diferencia de esos dos casos, acá SÍ hace falta
                # una validación extra: T tiene que ser uno de los tipos
                # que la propia task declaró en su 'accepts' (si no, el
                # programa está pidiendo un canal que el runtime nunca va
                # a poder entregarle -- mejor rechazarlo en compilación que
                # dejar que 'accept_chan()' bloquee para siempre).
                # Flag temporal que le avisa al
                # branch de 'accept_chan' en _infer que ESTA llamada puntual
                # viene del único lugar bendecido (este 'let' anotado) --
                # ver el chequeo inverso en _infer, que rechaza en cualquier
                # otro sitio (ExprStmt suelto, 'while let', anidado como
                # argumento de otra llamada, etc.) donde no hay ninguna
                # anotación de la que sacar T, y antes de este cambio el
                # runtime terminaba adivinando (o, con más de un tipo
                # aceptado, no tenía cómo elegir el slot correcto).
                self._accept_chan_ok = True
                self._infer(stmt.expr, env, fn, ret_ty)  # valida aridad/contexto (ver bloque dedicado en _infer)
                self._accept_chan_ok = False
                bad_shape = (
                    stmt.declared_type.name != OPTION_MARK
                    or not stmt.declared_type.args
                    or stmt.declared_type.args[0].name != CHAN_MARK
                )
                if bad_shape:
                    self._fail(
                        f"'{stmt.name}': la anotación de accept_chan() debe "
                        f"ser Option<Chan<T>>, se dio {stmt.declared_type!r}",
                        stmt,
                    )
                    ty = TypeAnn(OPTION_MARK, [TypeAnn(CHAN_MARK, [T_I32])])
                else:
                    if stmt.declared_type.args[0] not in fn.accepts:
                        self._fail(
                            f"'{stmt.name}': la task '{fn.name}' no declaró "
                            f"aceptar {stmt.declared_type.args[0]!r} (agregar "
                            f"'accepts {stmt.declared_type.args[0]!r}' a su "
                            f"firma)",
                            stmt,
                        )
                    ty = stmt.declared_type
            else:
                # `let r: Result<str> = Err(...)` toma el tipo
                # anotado (ver ErrExpr en _infer)
                # (también un Some/Ok, que bajan el tipo a lo de
                # adentro: `let o: Option<Result<str>> = Some(Err("x"))`)
                esperado = (stmt.declared_type
                            if isinstance(stmt.expr, (ErrExpr, SomeExpr, OkExpr, ArrayLit, IfExpr)) else None)
                ty = self._infer(stmt.expr, env, fn, ret_ty, expected_ty=esperado)
                if stmt.declared_type is not None and not self._compatible(stmt.declared_type, ty, stmt.expr):
                    self._fail(
                        f"'{stmt.name}': se anotó {stmt.declared_type!r} pero "
                        f"el valor es de tipo {ty!r}{self._pista(stmt.declared_type, ty)}",
                        stmt,
                    )
                if stmt.declared_type is not None:
                    # La variable es del tipo anotado, no del valor inicial:
                    # `let mut x: f64 = 19` (i32 promovido a f64) es f64, y
                    # `x = 1.5` vale, como en el intérprete y el nativo.
                    ty = stmt.declared_type
            self._no_tapar_builtin(stmt.name, ty, stmt)
            env.define(stmt.name, ty, mut=bool(stmt.mutable),
                       kind="match" if getattr(stmt, "dato_de_match", False) else "let")
            if (self._is_fresh_str_concat(stmt.expr, ty)
                    or self._is_fresh_try_str(stmt.expr, env, fn, ret_ty)
                    or self._is_str_owned_call(stmt.expr, ty)):
                env.mark_owned_alloc(stmt.name)
            # 'let elem = cuerpo.get(j)' (caso directo) o
            # 'let elem2 = elem' con 'elem' ya marcada (re-alias simple,
            # ej. reordenar el patrón del snake) propagan `borrowed` --
            # un préstamo lo sigue siendo aunque se lo copie a otro
            # nombre, ver `_is_borrowing_get`/`_move_if_needed`.
            if self._is_borrowing_get(stmt.expr, env, fn, ret_ty) or (
                isinstance(stmt.expr, Ident) and env.is_borrowed(stmt.expr.name)
            ):
                env.mark_borrowed(stmt.name)
            else:
                # `let b = a` con un
                # valor no-Copy MUEVE `a`, igual que `b = a`, push, set, send y
                # spawn (`let x = r.campo` mueve solo ese campo). Antes el
                # `let` no movía: quedaban dos nombres para el mismo objeto, y
                # al mover uno (`xs.push(a)`) el otro apuntaba a un bloque ya
                # soltado (use-after-free en el nativo). Vale también para el
                # resultado de una fn que devuelve su parámetro (ver
                # _move_if_needed y fresh_owned.resolve_returned_params).
                self._move_if_needed(stmt.expr, ty, env)
            if isinstance(stmt.expr, Ident) and ty.name == "str":
                # `let s = t` con t str. Si acá se movió (t era dueña
                # de un texto propio), el codegen le pasa la propiedad a s; si
                # no, t sigue viva y s recibe una copia. La misma decisión en
                # los dos: el codegen lee esta marca en vez de recalcularla.
                stmt.expr.se_mueve = env.is_moved(stmt.expr.name)
            return
        if isinstance(stmt, ReturnStmt):
            # ret_ty es exactamente el tipo esperado en este sitio -- se lo pasamos
            # a _infer para que, si stmt.expr es 'None', pueda resolver Option<T>
            # en vez de defaultear a Option<i32> (ver nota en _infer/NoneExpr).
            actual = self._infer(stmt.expr, env, fn, ret_ty, expected_ty=ret_ty) if stmt.expr is not None else T_VOID
            if not self._compatible(ret_ty, actual, stmt.expr):
                self._fail(
                    f"'{fn.name}' declara retorno {ret_ty!r} pero hace return de tipo {actual!r}"
                    f"{self._pista(ret_ty, actual)}",
                    stmt,
                )
            # Un `return` también pasa su valor por _move_if_needed (como
            # AssignStmt y los 'let'/'while let' de arriba), no solo valida
            # el TIPO: 'while let Some(e) = v.get(0) { return e }' devolvería
            # un préstamo al slot de un Vec LOCAL a esta función, que se
            # libera al volver (use-after-free), el mismo caso que .push()/
            # spawn/chan.send() rechazan. Un return sin valor no mueve nada.
            if stmt.expr is not None:
                self._move_if_needed(stmt.expr, actual, env)
            return
        if isinstance(stmt, ExprStmt):
            self._infer(stmt.expr, env, fn, ret_ty)
            return
        if isinstance(stmt, AssignStmt):
            # Un target Ident simple ('cuerpo = ...') no
            # es una lectura -- se le va a dar un valor nuevo, así que su
            # tipo se busca directo (env.get) sin pasar por el chequeo de
            # 'moved' de _infer. Un target FieldAccess ('obj.campo = ...')
            # sí sigue el camino normal: ahí el OBJETO se lee de verdad
            # (para ubicar el campo), y si ese objeto ya fue movido es un
            # error real, distinto al de reasignar la variable completa.
            camino_destino = self._camino_campo(stmt.target) if isinstance(stmt.target, FieldAccess) else None
            if isinstance(stmt.target, Ident):
                expected = env.get(stmt.target.name, stmt.target)
                _k = env.inmutable_kind(stmt.target.name)
                if _k is not None:
                    _n = stmt.target.name
                    _como = {
                        "param": f"'{_n}' es un parámetro y los parámetros no son mut: "
                                 f"cópialo a una variable (let mut {_n}2 = {_n}) y asigna a esa",
                        "for": f"'{_n}' es la variable de un 'for' y no se puede reasignar",
                        "while let": f"'{_n}' viene de un 'while let' y no se puede reasignar",
                        "match": f"'{_n}' es un dato de un brazo del match y no se puede "
                                 f"reasignar (cópialo: let mut {_n}2 = {_n})",
                    }.get(_k, f"'{_n}' no es mut: declárala con 'let mut {_n} = ...'")
                    _pos_match = getattr(stmt, "match_pos", None)
                    if _pos_match is None:
                        self._fail(f"no se puede asignar a {_n!r}: {_como}", stmt)
                    elif (_n, _pos_match) not in self._mut_reportados:
                        # `x = match ...`: una sola vez, en la línea del match
                        self._mut_reportados.add((_n, _pos_match))
                        self.errors.append(TypeError_(
                            f"no se puede asignar a {_n!r}: {_como}", _pos_match[0], _pos_match[1],
                            getattr(stmt, "archivo", None)))
            elif camino_destino is not None:
                # asignar a un campo movido lo vuelve a llenar (no es una
                # lectura); el resto de la cadena sí tiene que estar vivo.
                expected = self._tipo_sin_movidos(stmt.target, env, fn, ret_ty)
                padre = camino_destino.rsplit(".", 1)[0]
                if "." in padre:
                    conflicto = env.moved_conflict(padre)
                    if conflicto is not None:
                        self._fail(f"uso de '{padre}' después de haber movido '{conflicto}'", stmt.target)
            else:
                expected = self._infer(stmt.target, env, fn, ret_ty)
            # Bug (reasignar None a un Option<T> con T != i32): 'expected'
            # ya se calculó arriba pero nunca se pasaba como expected_ty acá
            # -- 'c = None' con c: Option<str> inferia el None como
            # Option<i32> (default histórico de NoneExpr) y fallaba contra
            # 'expected' aunque la asignación es válida. Mismo mecanismo que
            # ya usan LetStmt/ReturnStmt/argumentos de Call (ver NoneExpr en
            # _infer), aplicado acá por primera vez a la asignación simple.
            actual = self._infer(stmt.expr, env, fn, ret_ty, expected_ty=expected)
            if not self._compatible(expected, actual, stmt.expr):
                if getattr(stmt, "brazo_de_match", False):
                    self._fail(f"un brazo del match da un {actual!r}, pero el match tiene "
                               f"que dar un {expected!r}", stmt)
                else:
                    self._fail(f"asignación inválida: se esperaba {expected!r}, se dio {actual!r}"
                               f"{self._pista(expected, actual)}", stmt)
            # 'a = b' con b: Vec<T>/Map<K,V>/struct mueve b: 'a' y 'b'
            # compartirían el mismo buffer (codegen copia el struct/puntero
            # tal cual en un '=' de C), y un uso posterior de 'b' mutaría por
            # debajo de 'a' -- el alias invisible que la regla de
            # exclusividad prohíbe. Mismo criterio que spawn/chan.send/
            # vec.push(struct)/map.set(value) (is_copy() + owned_alloc para
            # str).
            self._move_if_needed(stmt.expr, actual, env)
            # Gemelo de la marca en LetStmt: 'elem = cuerpo.get(...)'
            # reasignando una variable ya declarada tiene que actualizar su marca de
            # préstamo igual que 'let' la fija la primera vez -- si no,
            # una 'elem' que arrancó prestada seguía viéndose prestada para
            # siempre (inofensivo pero podía enmascarar un error real más
            # adelante), o una reasignación a un valor prestado nunca
            # quedaba marcada. Solo aplica a un target simple (Ident) --
            # un campo de struct (obj.campo = ...) queda fuera a propósito,
            # ese alias es un caso más complejo.
            if isinstance(stmt.target, Ident):
                if self._is_borrowing_get(stmt.expr, env, fn, ret_ty) or (
                    isinstance(stmt.expr, Ident) and env.is_borrowed(stmt.expr.name)
                ):
                    env.mark_borrowed(stmt.target.name)
                else:
                    owner = env._owner(stmt.target.name)
                    if owner is not None:
                        owner.borrowed.discard(stmt.target.name)
                # Gemelo de env.define() (que limpia 'moved' para un
                # 'let' nuevo) para la reasignación -- 'x = expr' le da a 'x'
                # un valor NUEVO, así que cualquier marca 'moved' que 'x'
                # arrastrara de ANTES de esta línea queda obsoleta. Sin esto,
                # una variable que se movió una vez (ej. al pasarla a una fn
                # que la devuelve) quedaría marcada 'movida' PARA SIEMPRE
                # aunque se le reasigne un valor fresco, y no andaría el
                # idioma "x = fn_que_devuelve_x(x)".
                owner = env._owner(stmt.target.name)
                if owner is not None:
                    owner.moved.discard(stmt.target.name)
                    owner.moved = {m for m in owner.moved if not m.startswith(stmt.target.name + ".")}
            elif camino_destino is not None:
                env.revive_path(camino_destino)
            return
        if isinstance(stmt, ContinueStmt):
            # los de un loop ya se bajaron (continuar.py): este está afuera
            self._fail("'continue' fuera de un loop: solo se puede usar dentro de un "
                       "while, while let o for", stmt)
            return
        if isinstance(stmt, BreakStmt):
            if not self._loops:
                self._fail("'break' fuera de un loop: solo se puede usar dentro de un "
                           "while, while let o for", stmt)
                return
            # el estado de afuera del loop en este punto: es uno de los
            # estados con que se puede llegar a lo que sigue al loop
            loop = self._loops[-1]
            loop["salidas"].append([(set(a.moved), set(a.borrowed), set(a.owned_alloc))
                                    for a in loop["ancestros"]])
            return
        if isinstance(stmt, IfStmt):
            self._sin_arreglo(stmt.cond, "la condición de un 'if'")
            cond_ty = self._infer(stmt.cond, env, fn, ret_ty)
            if cond_ty != T_BOOL:
                self._fail(f"la condición de 'if' debe ser bool, no {cond_ty!r}", stmt.cond)
            # Las dos ramas se excluyen (ver _ramas_excluyentes).
            def rama_then(child):
                self._check_block(stmt.then_block, child, fn, ret_ty)
                return block_never_falls_through(stmt.then_block)

            def rama_else(child):
                if stmt.else_block is None:
                    return False
                self._check_block(stmt.else_block, child, fn, ret_ty)
                return block_never_falls_through(stmt.else_block)

            self._ramas_excluyentes(env, [rama_then, rama_else])
            return
        if isinstance(stmt, WhileStmt):
            self._sin_arreglo(stmt.cond, "la condición de un 'while'")
            cond_ty = self._infer(stmt.cond, env, fn, ret_ty)
            if cond_ty != T_BOOL:
                self._fail(f"la condición de 'while' debe ser bool, no {cond_ty!r}", stmt.cond)
            self._check_loop_body(stmt, stmt.body, env, env.child(), fn, ret_ty)
            return
        if isinstance(stmt, WhileLetStmt):
            self._sin_arreglo(stmt.expr, "la cabecera de un 'while let'")
            val_ty = self._infer(stmt.expr, env, fn, ret_ty)
            # el match sobre un Result se baja a un while let Ok(x)
            # (patron "Ok", solo lo pone enum_match; el usuario no lo escribe)
            esperado_wl = RESULT if getattr(stmt, "patron", "Some") == "Ok" else OPTION_MARK
            if val_ty.name != esperado_wl:
                if getattr(stmt, "patron", None) is None:
                    self._fail(f"'while let Some(...)' requiere un Option, se dio {val_ty!r}", stmt.expr)
                # (de un match: el error ya lo dio su condición, ver match_sobre)
                return
            inner_env = env.child()
            inner_ty = val_ty.args[0] if val_ty.args else T_I32
            self._no_tapar_builtin(stmt.pattern, inner_ty, stmt)
            inner_env.define(stmt.pattern, inner_ty, mut=False, kind="while let")
            # Un Vec/Map prestado de una variable que el cuerpo mueve
            # se liga como copia propia (los dos backends leen esta marca)
            stmt.copia_ligada = bool(
                isinstance(stmt.expr, Ident) and self._es_contenedor_movido(inner_ty)
                and lugares.ligada_se_mueve(stmt.pattern, stmt.body.stmts, self._param_contenedor))
            if isinstance(stmt.expr, Ident) and inner_ty.name in self.structs:
                inner_env.payload_of[stmt.pattern] = stmt.expr.name
            # Para simetría de lenguaje con struct/spawn: si lo
            # que desestructura este 'while let' es un chan.recv() sobre
            # Chan<str>, `stmt.pattern` queda dueña de un buffer de heap
            # real (la copia que _chan_c_type fuerza en send(), ver
            # ahí) -- marcarla owned_alloc hace que, si el cuerpo la
            # reenvía (spawn/otro chan.send()), _move_if_needed la trate
            # como movida en vez de dejarla reusable, igual que ya pasa con
            # cualquier otro str fresco (concat/index, ver
            # _is_fresh_str_concat).
            # Mismo mark_owned_alloc de arriba, ahora también
            # para 'while let Some(x) = v.pop()' sobre Vec<str> (ver
            # parser.elemento_de_pop) -- sin esto, 'x' quedaba con el mismo
            # hueco de sonido que _is_fresh_chan_str_recv ya había
            # cerrado para Chan<str>.recv().
            if inner_ty == T_STR and (
                self._is_fresh_chan_str_recv(stmt.expr, env, fn, ret_ty)
                or elemento_de_pop(stmt.expr, lambda e: self._infer(e, env, fn, ret_ty)) is not None
            ):
                inner_env.mark_owned_alloc(stmt.pattern)
            # 'while let Some(e) = cuerpo.get(j)' (caso directo) o
            # 'while let Some(e) = elem' con 'elem' ya marcada 'borrowed'
            # (el patrón real de snake_completo.scar: 'elem' se llenó
            # antes con 'cuerpo.get(...)') -- en cualquiera de los dos
            # casos, 'e' es el mismo alias que sigue viviendo dentro de
            # 'cuerpo', no un valor nuevo. Ver _is_borrowing_get/
            # _move_if_needed para dónde se usa esta marca.
            if self._is_ownable_inner(inner_ty) and (
                self._is_borrowing_get(stmt.expr, env, fn, ret_ty)
                or (isinstance(stmt.expr, Ident) and env.is_borrowed(stmt.expr.name))
            ):
                inner_env.mark_borrowed(stmt.pattern)
            self._check_loop_body(stmt, stmt.body, env, inner_env, fn, ret_ty)
            return
        if isinstance(stmt, ForStmt):
            self._sin_arreglo(stmt.start, "el rango de un 'for'")
            self._sin_arreglo(stmt.end, "el rango de un 'for'")
            start_ty = self._infer(stmt.start, env, fn, ret_ty)
            end_ty = self._infer(stmt.end, env, fn, ret_ty)
            var_ty = T_I32
            if not (start_ty.is_integer() and end_ty.is_integer()):
                self._fail(f"el rango de 'for' debe ser de enteros (i32 o i64), se dio {start_ty!r}..{end_ty!r}", stmt)
            else:
                # i32..i32 da i32; si un extremo es i64, la variable es
                # i64 y el otro extremo se amplía.
                var_ty = numeric_result(start_ty, end_ty)
                self._compatible(var_ty, start_ty, stmt.start)
                self._compatible(var_ty, end_ty, stmt.end)
            stmt.tipo_var = var_ty.name
            inner_env = env.child()
            inner_env.define(stmt.var, var_ty, mut=False, kind="for")
            self._check_loop_body(stmt, stmt.body, env, inner_env, fn, ret_ty)
            return
        self._fail(f"statement no soportado por el checker: {type(stmt).__name__}", stmt)

    # los tipos que cruzan la frontera de una librería (los mismos
    # de una extern fn)
    _TIPOS_EXPORTABLES = ("i32", "i64", "f64", "bool", "str")
    # los elementos de un Vec que cruza la frontera
    _ELEMENTOS_VEC_EXPORTABLES = ("i32", "i64", "f64", "bool")

    def _exportable(self, ty):
        """Además de los escalares y str, un struct como el de una
        extern fn (no genérico, con campos i32/i64/f64/bool: cruza por valor)
        y un Vec de i32/i64/f64/bool (cruza como {datos, n})."""
        if ty.name in self._TIPOS_EXPORTABLES:
            return not ty.args
        if ty.name == VEC_MARK:
            return (len(ty.args) == 1 and not ty.args[0].args
                    and ty.args[0].name in self._ELEMENTOS_VEC_EXPORTABLES)
        if ty.name in self.structs and not ty.args and ty.name not in self.enums:
            return self._cruza_ffi(ty)
        return False

    _EXPORTABLES_TEXTO = ("i32, i64, f64, bool, str, un struct con campos i32/i64/f64/bool "
                          "o un Vec de i32/i64/f64/bool")

    def _check_exportada(self, decl):
        """Una `export fn` se llama desde otro lenguaje (C, Python
        con ctypes): sus parámetros y su retorno son i32, i64, f64, bool o
        str (o no devuelve nada), un struct de campos escalares o un Vec de
        escalares; no es genérica y no es main."""
        if decl.name == "main":
            self._fail("'main' no se exporta: una librería no tiene main", decl)
            return
        if decl.type_params:
            self._fail(f"'{decl.name}' es genérica: una fn exportada tiene tipos fijos "
                       f"(otro lenguaje no puede elegir el T)", decl)
            return
        permitidos = self._EXPORTABLES_TEXTO
        for p in decl.params:
            if p.type_ann is None or not self._exportable(p.type_ann):
                self._fail(f"'{decl.name}': el parámetro '{p.name}' es {p.type_ann!r}; una fn "
                           f"exportada solo recibe {permitidos}", p)
        rt = decl.return_type
        if rt is not None and rt != T_VOID and not self._exportable(rt):
            self._fail(f"'{decl.name}' devuelve {rt!r}; una fn exportada devuelve {permitidos} "
                       f"o nada", decl)

    def _check_loop_body(self, stmt, body, env, inner_env, fn, ret_ty):
        """El cuerpo de un loop se revisa una sola vez, pero corre muchas:
        mover adentro una variable de AFUERA del loop (`for i in 0..3 {
        xs.push(v) }`) metería el mismo objeto tres veces (un alias en el
        intérprete, use-after-free en el nativo). La regla: lo que una vuelta deja movido (y no volvió a asignar) es de
        afuera, así que la vuelta siguiente lo volvería a usar: error. Una
        rama que siempre hace `return` no cuenta (no hay vuelta siguiente), y
        el contenido sacado de un `while let Some(x) = o` tampoco (o queda en
        None). Tampoco un loop que corre una sola vez (`while let Some(x) = o
        { o = None ... }`).

        Límite conocido: un PARÁMETRO movido dentro de un `if` del loop (solo
        en una de las ramas) no se rechaza, porque no se puede saber sin
        ejecutar cuántas vueltas lo toman: el reservoir de 83_ (`if j ==
        elegido { b.data.push(m) }`) es correcto y lo usan programas del
        usuario, y el nativo sigue ese parámetro con un flag de dueño en
        tiempo de ejecución. Una variable local en la misma
        situación sí es un error: el nativo no la sigue así (la liberaba en
        la otra rama y la vuelta siguiente la usaba liberada)."""
        ancestros = []
        e = env
        while e is not None:
            ancestros.append(e)
            e = e.parent
        antes = [(set(a.moved), set(a.moved_por_payload)) for a in ancestros]
        entrada = [(set(a.moved), set(a.borrowed), set(a.owned_alloc)) for a in ancestros]
        self._loops.append({"ancestros": ancestros, "salidas": []})
        try:
            self._check_block(body, inner_env, fn, ret_ty)
        finally:
            loop = self._loops.pop()
        sigue = not block_never_falls_through(body)
        if sigue and not self._corre_una_vez(stmt):
            self._check_vuelta_siguiente(stmt, ancestros, antes, fn, ret_ty, body, inner_env)
        # Después del loop se puede llegar (1) sin haber corrido
        # ninguna vuelta, (2) al terminar una vuelta (si el cuerpo llega a
        # su final) o (3) por cada `break`. Lo movido en cualquiera de esos
        # caminos queda movido (lo mismo que con las ramas de un if). Antes
        # solo contaba (2): `xs.push(d); while c { d = D {} }; print(d.a)`
        # pasaba el checker y, con c falso de entrada, el nativo leía d ya
        # liberada.
        estados = [entrada] + loop["salidas"]
        if sigue:
            estados.append([(set(a.moved), set(a.borrowed), set(a.owned_alloc)) for a in ancestros])
        for k, a in enumerate(ancestros):
            a.moved = set().union(*(est[k][0] for est in estados))
            a.borrowed = set().union(*(est[k][1] for est in estados))
            a.owned_alloc = set().union(*(est[k][2] for est in estados))

    def _check_vuelta_siguiente(self, stmt, ancestros, antes, fn, ret_ty=None, body=None, inner_env=None):
        """Lo que una vuelta deja movido es de afuera, así
        que la vuelta siguiente empieza con eso movido. Se sigue el estado de
        cada variable a lo largo del cuerpo con una segunda pasada que arranca
        con eso movido (la vuelta siguiente):
        - si la segunda pasada lo usa antes de darle otro valor, la vuelta
          siguiente lo usaría ya movido: error, en la línea donde lo usa
          (`for .. { xs.push(v) }`);
        - si le da otro valor antes de usarlo, cada vuelta mueve lo que le
          acaba de dar y está bien (`while c { v = nuevo(); xs.push(v) }`);
        - si en la primera pasada se movió solo en una rama de un `if`
          (movimiento condicional), cuántas vueltas lo mueven depende de los
          datos: se acepta, y cada uso que puede encontrarlo movido lleva
          una comprobación en tiempo de ejecución (`verificar_movida`, un
          panic igual en los dos backends)."""
        params = {pp.name for pp in fn.params} if fn is not None else set()
        # un campo movido ("v.x") sigue con la regla simple (error, salvo
        # el de un parámetro en una sola rama); la segunda pasada es para
        # variables enteras
        self._error_vuelta_simple(stmt, ancestros, antes, params, solo_campos=self._vuelta is None and body is not None)
        nuevos = {}
        for a, (mv, pp) in zip(ancestros, antes):
            for n in a.moved - mv:
                if n in a.moved_por_payload or "." in n:
                    continue
                nuevos[n] = (id(a), n) in self._mov_condicional
        if not nuevos or body is None or self._vuelta is not None:
            return
        # para el codegen: las variables de afuera que el cuerpo mueve (un nodo
        # que las nombra; sobrevive al renombre de nombres_c). Su dueña pasa a
        # depender de un flag en tiempo de ejecución durante el loop.
        stmt.mueve_de_afuera = [self._donde_mov[n][0] for n in sorted(nuevos)
                                if n in self._donde_mov and isinstance(self._donde_mov[n][0], Ident)]
        # la segunda pasada: misma cadena de ancestros, con lo nuevo movido
        guardado = [(set(a.moved), set(a.borrowed), set(a.owned_alloc)) for a in ancestros]
        n_errores = len(self.errors)
        self._vuelta = {"cond": {n for n, c in nuevos.items() if c},
                        "defi": {n for n, c in nuevos.items() if not c},
                        "errores": [], "vistas": set(), "loop": stmt}
        self._loops.append({"ancestros": ancestros, "salidas": []})
        try:
            if isinstance(stmt, WhileStmt):
                self._infer(stmt.cond, inner_env.parent, fn, ret_ty)
            self._check_block(body, inner_env.child() if inner_env is not None else ancestros[0].child(), fn, ret_ty)
        finally:
            self._loops.pop()
            vuelta = self._vuelta
            self._vuelta = None
            del self.errors[n_errores:]
            for a, (mv, br, oa) in zip(ancestros, guardado):
                a.moved, a.borrowed, a.owned_alloc = mv, br, oa
        self.errors.extend(vuelta["errores"])

    def _error_vuelta_simple(self, stmt, ancestros, antes, params, solo_campos=False):
        """La regla simple: lo que la vuelta deja movido (salvo un
        parámetro movido en una sola rama) es un error. Con `solo_campos`,
        solo para los campos movidos ("v.x"); las variables enteras las
        sigue la segunda pasada (_check_vuelta_siguiente)."""
        for a, (mv, pp) in zip(ancestros, antes):
            nuevos = sorted(n for n in a.moved - mv
                            if n not in a.moved_por_payload
                            and (not solo_campos or "." in n)
                            and not ((id(a), n) in self._mov_condicional and n.split(".")[0] in params))
            for n in nuevos:
                nodo, motivo = self._donde_mov.get(n.split(".")[0], (stmt, None))
                if nodo is None:
                    nodo = stmt
                donde = ""
                if nodo is not stmt and getattr(stmt, "line", None):
                    donde = f" del loop de la línea {stmt.line}"
                self._fail(
                    f"'{n}' se mueve acá, adentro{donde}, pero es de afuera: la "
                    f"vuelta siguiente lo volvería a usar ya movido"
                    + (f" ({motivo})." if motivo else ".")
                    + " Se arregla moviéndolo una sola vez fuera del loop, "
                    f"guardando una copia, o reasignándolo antes de terminar la vuelta",
                    nodo,
                )
                a.moved.discard(n)  # un solo error por variable

    def _uso_en_vuelta(self, nombre, expr):
        """En la segunda pasada de un loop, `nombre` se usa estando
        movido por la vuelta anterior. True si eso se resolvió acá (error de
        la vuelta, o comprobación en tiempo de ejecución) y el llamador no
        tiene que dar el error de siempre."""
        v = self._vuelta
        if v is None:
            return False
        if nombre in v["cond"]:
            expr.verificar_movida = True
            return True
        if nombre in v["defi"]:
            if nombre not in v["vistas"]:
                v["vistas"].add(nombre)
                nodo, motivo = self._donde_mov.get(nombre, (None, None))
                linea = getattr(nodo, "line", None)
                loop_l = getattr(v["loop"], "line", None)
                del_loop = f" del loop de la línea {loop_l}" if loop_l else ""
                if linea is None or linea == getattr(expr, "line", None):
                    # se mueve y se vuelve a usar en el mismo lugar (`xs.push(v)`)
                    texto = (f"'{nombre}' se mueve acá, adentro{del_loop}, pero es de afuera: la "
                             f"vuelta siguiente lo volvería a usar ya movido")
                else:
                    texto = (f"'{nombre}' se mueve en la línea {linea}, adentro{del_loop}, y en la "
                             f"vuelta siguiente se usa acá antes de darle otro valor")
                v["errores"].append(TypeError_(
                    texto + (f" ({motivo})." if motivo else ".")
                    + " Se arregla moviéndolo una sola vez fuera del loop, guardando una "
                    f"copia, o dándole otro valor antes de usarlo en cada vuelta",
                    getattr(expr, "line", None), getattr(expr, "col", None), getattr(expr, "archivo", None)))
            return True
        return False

    @staticmethod
    def _corre_una_vez(stmt):
        """`while let Some(x) = o { ... }` cuyo cuerpo hace `o = None` fuera de
        cualquier if: la condición de la vuelta siguiente es falsa."""
        if not (isinstance(stmt, WhileLetStmt) and isinstance(stmt.expr, Ident)):
            return False
        return any(isinstance(st, AssignStmt) and isinstance(st.target, Ident)
                   and st.target.name == stmt.expr.name and isinstance(st.expr, NoneExpr)
                   for st in stmt.body.stmts)

    @staticmethod
    def _pista(esperado, dado):
        """La conversión que hay que escribir cuando un
        número no calza donde va (nunca se hace sola si puede perder algo)."""
        if esperado is None or dado is None:
            return ""
        par = (esperado.name, dado.name)
        if par == ("i32", "i64"):
            return " (convierte con to_i32(...), que es un panic si el valor no cabe)"
        if par == ("i32", "f64"):
            return " (convierte con to_i32(...), que trunca hacia cero)"
        if par == ("i64", "f64"):
            return " (convierte con to_i64(...), que trunca hacia cero)"
        if par == ("f64", "i64"):
            return " (convierte con to_f64(...); de i64 a f64 se puede perder precisión)"
        return ""

    def _fallo_i64_f64(self, expr):
        self._fail(
            f"'{expr.op}' entre i64 y f64: convierte uno de los dos con to_f64() o "
            f"to_i64() (de i64 a f64 se puede perder precisión)", expr)

    def _resultado_numerico(self, expr, l, r):
        """Tipo de una cuenta entre dos números (ver numeric_result).
        Se anota en el nodo (tipo_int) cuando es entera: el intérprete y el
        nativo desbordan con el rango de ESE tipo."""
        ty = numeric_result(l, r)
        if ty is None:
            self._fallo_i64_f64(expr)
            return T_I64
        if ty.is_integer():
            expr.tipo_int = ty.name
        return ty

    def _compatible(self, expected: TypeAnn, actual: TypeAnn, expr=None) -> bool:
        if expected == actual:
            return True
        # i32 se puede usar donde se espera f64 (promoción numérica, como en la mayoría
        # de lenguajes de sistemas)
        if expected == T_I64 and actual == T_I32:
            # i32 -> i64 es una ampliación sin pérdida, como i32 -> f64.
            # C la hace sola; el intérprete marca el valor como i64 (para que
            # una cuenta posterior desborde en 64 bits y no en 32).
            if expr is not None:
                expr.promover_i64 = True
            return True
        if expected == T_F64 and actual == T_I32:
            # C convierte solo; el intérprete
            # guardaba el entero de Python en un lugar f64 (imprimía `0` en vez
            # de `0.0`, y una división posterior podía ser entera). Se marca
            # la expresión y el intérprete la convierte al evaluarla.
            if expr is not None:
                expr.promover_f64 = True
            return True
        # La misma ampliación adentro de un Some/Ok recién armado
        # (`let o: Option<i64> = Some(5)`, `return Ok(0)` en una fn -> Result<f64>):
        # lo que se amplía es el valor de adentro, y el Some/Ok toma el tipo
        # esperado (el codegen lo lee de la marca, ver Codegen.infer).
        if (isinstance(expr, (SomeExpr, OkExpr)) and expected.name == actual.name
                and expected.name in (OPTION_MARK, RESULT)
                and len(expected.args) == 1 and len(actual.args) == 1):
            return self._compatible(expected.args[0], actual.args[0], expr.expr)
        # void tolera cualquier cosa que no se usa (permisivo a propósito en el prototipo)
        if expected == T_VOID:
            return True
        return False

    def _type_param_bound_ops(self, ty: TypeAnn, fn) -> set:
        """Si 'ty' es un parámetro de tipo abstracto
        de 'fn' (ej. 'T' dentro del cuerpo de 'fn sumar<T: Numeric>(...)')
        y ese parámetro declara un bound conocido (ver BOUND_OPS más
        arriba), devuelve el set de operadores binarios que ese bound
        habilita sobre él. Devuelve un set vacío en cualquier otro caso
        -- tipo concreto, parámetro sin bound, bound desconocido, o 'fn'
        sin 'type_params'/'type_bounds' (structs, o contextos sin cuerpo
        de función) -- en todos esos casos T sigue opaco. 'ty.args' no vacío también descarta el camino (un
        parámetro de tipo puro nunca lleva argumentos, ej. 'T' sí pero
        'Vec<T>' no es 'T' mismo)."""
        if fn is None or ty.args:
            return set()
        if ty.name not in getattr(fn, "type_params", ()):
            return set()
        bound = getattr(fn, "type_bounds", {}).get(ty.name)
        return BOUND_OPS.get(bound, set())

    def _bind_type_params(self, fty: TypeAnn, actual: TypeAnn, type_params, bindings, expr, fname) -> None:
        """Unifica el tipo declarado de un campo
        ('fty', puede mencionar un parámetro de tipo del struct como 'T',
        posiblemente anidado dentro de Vec<T>/Map<K,T>) contra 'actual'
        (el tipo ya inferido del valor real pasado en el StructLit),
        fijando bindings[T] cuando corresponde. Reemplaza el chequeo
        original (solo 'fty.name in type_params and not fty.args', es
        decir, únicamente un campo T puro) por una unificación recursiva
        sobre '.args' en paralelo -- así 'items: Vec<T>' con un valor
        real 'Vec<i32>' también fija T=i32, sin que Vec<T> tenga que
        aparecer como caso especial acá (mismo mecanismo sirve para
        cualquier contenedor genérico ya existente, Map<K,V> incluido).
        Un campo T puro es el caso base de esta recursión (fty.args vacío)."""
        if fty.name in type_params and not fty.args:
            if fty.name in bindings and bindings[fty.name] != actual:
                self._fail(
                    f"'{expr.name}<{fty.name}>' inconsistente: el campo '{fname}' "
                    f"da {actual!r}, pero otro campo con el mismo parámetro "
                    f"'{fty.name}' ya fijó {bindings[fty.name]!r}",
                    expr,
                )
            else:
                bindings.setdefault(fty.name, actual)
            return
        if fty.args and actual.args and fty.name == actual.name and len(fty.args) == len(actual.args):
            for fa, aa in zip(fty.args, actual.args):
                self._bind_type_params(fa, aa, type_params, bindings, expr, fname)

    def _bind_fn_type_params(self, fty: TypeAnn, actual: TypeAnn, type_params, bindings, call_node, fname, target_name) -> None:
        """Gemelo de `_bind_type_params` (ver ahí, un
        poco más arriba) pero para un sitio de LLAMADA a una fn/task
        genérica en vez de un campo de StructLit -- mismo mecanismo de
        unificación recursiva (un parámetro 'T' puro, o anidado en
        Vec<T>/Map<K,T>, contra el tipo YA inferido del argumento real
        en ESTE call puntual). No se reusa `_bind_type_params` tal cual
        porque esa arma su mensaje de error con `expr.name` (el nombre
        de un StructLit) -- un `Call` no tiene `.name` (tiene `.callee`),
        así que reusarla haría un AttributeError apenas se disparara una
        inconsistencia real. Mismo motivo por el que codegen/ mantiene
        gemelos separados por concepto en vez de una sola función
        compartida entre StructLit/Call."""
        if fty.name in type_params and not fty.args:
            if fty.name in bindings and bindings[fty.name] != actual:
                self._fail(
                    f"'{target_name}<{fty.name}>' inconsistente: el parámetro "
                    f"'{fname}' da {actual!r}, pero otro parámetro con el mismo "
                    f"tipo genérico '{fty.name}' ya fijó {bindings[fty.name]!r}",
                    call_node,
                )
            else:
                bindings.setdefault(fty.name, actual)
            return
        if fty.args and actual.args and fty.name == actual.name and len(fty.args) == len(actual.args):
            for fa, aa in zip(fty.args, actual.args):
                self._bind_fn_type_params(fa, aa, type_params, bindings, call_node, fname, target_name)

    def _substitute_type_params_list(self, ty: TypeAnn, type_params, bindings) -> TypeAnn:
        """Gemelo de `_substitute_type_params` (ver justo abajo) pero
        indexado por `type_params`/`bindings` directo en vez de derivar
        la lista de parámetros desde `self.struct_type_params[nombre]`
        -- una fn/task genérica no tiene una entrada en esa tabla (es
        solo para structs, ver `self.struct_type_params` en el
        constructor), así que no puede reusar `_substitute_type_params`
        tal cual. Un tipo sin binding (T que solo aparece en el retorno,
        nunca en ningún parámetro) se deja tal cual -- 'T' opaco, mismo
        default seguro que ya usa `_generic_struct_concrete_args` en
        codegen/ para ese caso."""
        if ty.name in type_params:
            return bindings.get(ty.name, ty)
        if ty.args:
            return TypeAnn(
                ty.name,
                [self._substitute_type_params_list(a, type_params, bindings) for a in ty.args],
            )
        return ty

    def _substitute_type_params(self, ty: TypeAnn, struct_name: str, concrete_args) -> TypeAnn:
        """Dado un TypeAnn tal como quedó guardado en
        self.structs[struct_name] (que puede mencionar un parámetro de tipo
        del struct, ej. 'T', posiblemente anidado como Option<T>/Vec<T>),
        sustituye cada parámetro por el argumento concreto que le
        corresponde por posición en concrete_args (mismo orden que
        self.struct_type_params[struct_name]). Para un struct no genérico
        (sin parámetros registrados) es una identidad barata. Recorre
        recursivamente .args por si el campo es a su vez un genérico
        anidado -- mismo patrón que usa _generic_c_type en codegen/."""
        params = self.struct_type_params.get(struct_name, [])
        if not params:
            return ty
        if ty.name in params:
            idx = params.index(ty.name)
            if idx < len(concrete_args):
                return concrete_args[idx]
            return ty
        if ty.args:
            return TypeAnn(
                ty.name,
                [self._substitute_type_params(a, struct_name, concrete_args) for a in ty.args],
            )
        return ty

    def _is_fresh_str_concat(self, expr, ty) -> bool:
        """True si `expr` (el lado derecho de un 'let') reserva un buffer
        de heap NUEVO para un str -- hoy dos formas reconocibles sin
        análisis interprocedural: un BinOp '+' cuyo resultado ya se
        infirió como str (A1, scar_str_concat() del lado de codegen), o
        un IndexExpr (s[i] -- scar_str_index() del lado de
        codegen, mismo motivo, otro buffer nuevo de un solo carácter).
        'let d = c' (un identificador, o una cadena de FieldAccess) NO es
        fresco aunque `c` ya sea dueña -- a propósito: es la misma regla
        que _let_creates_fresh_owner() en codegen/ ya aplica para
        struct/Vec/Map (un alias no hereda la propiedad, solo la sigue
        teniendo la variable original), y mantener las dos reglas
        idénticas es lo que evita que checker y codegen terminen en
        desacuerdo sobre quién es la dueña de cada valor. Un literal
        ('let d = "x"') tampoco es fresco: sigue siendo Copy de verdad,
        vive en el binario, no en el heap."""
        if isinstance(expr, IndexExpr):
            return True
        if isinstance(expr, FieldAccess) and ty == T_STR:
            # Un campo str de un struct temporal
            # (`mk().s`, `E { .. }.s`) se saca de la raíz y queda fresco en
            # el codegen (_campo_de_temporal): quien lo recibe es su dueña,
            # así que moverlo y usarlo después es un error, igual que con
            # una concatenación. Gemelo de codegen._is_fresh_str_concat_expr.
            raiz = expr
            while isinstance(raiz, FieldAccess):
                raiz = raiz.obj
            return not isinstance(raiz, Ident)
        return isinstance(expr, BinOp) and expr.op == "+" and ty == T_STR

    def _is_fresh_try_str(self, expr, env, fn, ret_ty, resolve=None) -> bool:
        """Gemelo de `_is_fresh_str_concat`, para 'let x = algo?' cuyo
        `.value` desenvuelto es un str NUEVO -- mismo criterio que
        `_is_fresh_try_value` del lado de codegen/ (ver ahí el porqué
        completo). `Socket.read()`/`read_pipe()`/`File.read_all()` son
        las tres fuentes reconocidas: los tres devuelven un buffer nuevo,
        dueño único, sin alias en ningún otro lado -- misma pregunta que
        resuelve `_is_fresh_try_value`.

        A diferencia de codegen/, acá NO hace falta distinguir CON QUÉ
        se libera cada uno (`scar_free()` para Socket.read()/read_pipe(),
        `free()` de libc para File.read_all() -- ver
        `_try_needs_libc_free` allá): el checker no emite código, `mark_owned_alloc`
        es puro bookkeeping para decisiones de movimiento/copia (ver
        `is_owned_alloc` más abajo), no dispara ningún `free()` real,
        así que las tres fuentes son igual de "frescas" desde acá aunque
        codegen/ sí tenga que tratarlas distinto para no repetir el
        heap-buffer-overflow que ASan encontró en 30_file_io.scar.

        `Ok(x)?` no se asume fresco por default: `x` tiene que ser
        independientemente fresco (recursa sobre esta misma función y
        sobre `_is_fresh_str_concat`), igual que en codegen/.

        Además de `read_pipe()`, una llamada directa (`Call` de un `Ident`,
        no un `MethodCall`) a otra `fn`/`task` PROPIA cuenta como fresca si
        `_resolve_fresh_result_str_fns` ya la resolvió como tal
        (`self.fresh_result_str_fns`, poblado UNA vez antes de chequear
        ningún cuerpo -- ver check_program), con el mismo criterio que
        codegen/. Así `productor()?` pasado a `spawn`/`chan.send()` queda
        movido.

        Como en su gemelo de codegen/ (`_result_str_terminal_origin`),
        `self.fresh_result_str_fns`
        recién queda completo DESPUÉS de que `_resolve_fresh_result_str_
        fns` termina de resolver TODAS las fn -- así que si `productor`
        llama a OTRA fn `Result<str>` con `?` (`contar` llamando a
        `leer_texto`), en el momento en que se resuelve `contar` el
        nombre `leer_texto` todavía no está en `self.fresh_result_str_fns`
        (se está resolviendo en el mismo pre-pase). `resolve` (inyectado
        por `resolve_result_str_origins`, con su propio orden
        topológico + guarda de recursión) es justo el mecanismo para
        preguntar "¿y esta otra fn, ya resuelta o resoluble?" sin
        depender de ese orden -- opcional porque este método también se
        llama después, en el chequeo real de cada cuerpo (`_check_fn`),
        cuando `self.fresh_result_str_fns` ya está completo y no hace
        falta ningún `resolve`."""
        if not isinstance(expr, TryExpr):
            return False
        inner = expr.expr
        if isinstance(inner, OkExpr):
            inner_ty = self._infer(inner.expr, env, fn, ret_ty)
            return self._is_fresh_str_concat(inner.expr, inner_ty) or self._is_fresh_try_str(
                inner.expr, env, fn, ret_ty, resolve
            )
        if isinstance(inner, Call) and isinstance(inner.callee, Ident):
            if inner.callee.name == "read_pipe" or inner.callee.name in self.fresh_result_str_fns:
                return True
            if resolve is not None:
                return bool(resolve(inner.callee.name))
            return False
        if isinstance(inner, MethodCall):
            obj_ty = self._infer(inner.obj, env, fn, ret_ty)
            if obj_ty.name == SOCKET_MARK and inner.method == "read":
                return True
            if obj_ty.name == FILE_MARK and inner.method == "read_all":
                return True
        return False

    def _is_fresh_chan_str_recv(self, expr, env, fn, ret_ty) -> bool:
        """True si `expr` es un `chan.recv()` sobre
        un `Chan<str>` -- gemelo de `_is_fresh_str_concat` pero para el
        único productor de un str fresco que no es un BinOp '+'/IndexExpr.
        No hace falta análisis interprocedural: `.recv()` tiene una sola
        implementación posible en este backend (ver
        `_while_let_binds_fresh_value` en codegen/, que aplica el mismo
        chequeo del lado del codegen). Necesita `fn`/`ret_ty` solo porque
        `_infer` los pide para poder seguir la recursión si `expr.obj`
        resultara ser algo más que un Ident/FieldAccess simple (mismo
        motivo por el que el call site de MethodCall en `_infer` ya se los
        pasa)."""
        if not (isinstance(expr, MethodCall) and expr.method in ("recv", "try_recv")):
            return False
        obj_ty = self._infer(expr.obj, env, fn, ret_ty)
        return obj_ty.name == CHAN_MARK and obj_ty.args and obj_ty.args[0] == T_STR

    def _is_ownable_inner(self, ty: TypeAnn) -> bool:
        """True si `ty` es un tipo cuyo valor vive en el heap detrás de un
        único puntero real -- struct de usuario o str. Son exactamente los
        dos casos en que scar_vec_get_*/scar_map_get_* (codegen/)
        devuelven el mismo puntero que sigue viviendo en el slot del
        contenedor, en vez de copiar (i32/f64/bool sí se copian tal
        cual -- ahí no hay nada que prestar, `.get()` es inofensivo)."""
        return ty.name in self.structs or ty.name == "str"

    def _is_borrowing_get(self, expr, env, fn, ret_ty) -> bool:
        """True si `expr` es `.get()` sobre un Vec<T>/Map<K,V> con
        T/V ownable (ver _is_ownable_inner) -- el Option<T> que resulta
        envuelve un ALIAS al slot del contenedor, nunca una copia (gemelo,
        del lado del checker, de por qué `_let_creates_fresh_owner` en
        codegen/ excluye `.get()` a propósito de "fresco"). El
        contenedor original sigue siendo dueño de ese valor; la variable
        que este 'let'/'while let' declara no lo es, aunque el tipo
        estático (Struct, no-Copy) sugiera lo contrario."""
        if not (isinstance(expr, MethodCall) and expr.method == "get"):
            return False
        obj_ty = self._infer(expr.obj, env, fn, ret_ty)
        if obj_ty.name == VEC_MARK:
            inner = obj_ty.args[0] if obj_ty.args else T_I32
        elif obj_ty.name == MAP_MARK:
            inner = obj_ty.args[1] if len(obj_ty.args) > 1 else T_I32
        else:
            return False
        # get() sobre un Vec<Struct>/Map<K,Struct>
        # devuelve una COPIA propia en los dos backends (el codegen la hace
        # dueña: diseño A, {S}_clone), así que no es un préstamo y se puede
        # mover como cualquier valor propio. El resto (ej. Vec<str>) sigue
        # siendo un préstamo del slot.
        if inner.name in self.structs:
            return False
        return self._is_ownable_inner(inner)

    def _metodo_result_option(self, expr, obj_ty, arg_types):
        """Mirar un Result/Option sin `?` ni `while
        let` -- r.is_ok(), r.is_err(), r.err() (el mensaje, o "" si es Ok),
        o.is_some(), o.is_none() y x.unwrap_or(valor) para un T escalar.
        Ninguno mueve ni consume el valor: se puede seguir usando."""
        es_result = obj_ty.name == RESULT
        inner = obj_ty.args[0] if obj_ty.args else T_I32
        m = expr.method
        nombre = "Result" if es_result else "Option"
        sin_args = {"is_ok": es_result, "is_err": es_result, "err": es_result,
                    "is_some": not es_result, "is_none": not es_result}
        if sin_args.get(m):
            if arg_types:
                self._fail(f"{nombre}.{m}() no lleva argumentos", expr)
            return T_STR if m == "err" else T_BOOL
        if m == "unwrap_or":
            if inner.name not in ("i32", "i64", "f64", "bool") and not (
                    not inner.args and inner.name in types_.PARAMS_COPIA):
                self._fail(
                    f"{nombre}.unwrap_or() solo está para un valor i32, i64, f64 o bool "
                    f"(acá es {inner!r}): para uno con dueña, usa `?` o `while let`", expr)
                return inner
            if len(arg_types) != 1 or not self._compatible(inner, arg_types[0], expr.args[0] if expr.args else None):
                self._fail(f"{nombre}.unwrap_or espera un {inner!r}, se dio {arg_types}", expr)
            return inner
        self._fail(f"{nombre} no tiene método '.{m}()'", expr)
        return T_I32

    def _check_write_bytes(self, expr, arg_types, que):
        """`.write_bytes(v)` escribe los valores de
        un Vec<i32> como bytes (cada uno tiene que estar en 0..255, si no es
        un panic). El Vec se presta: sigue siendo de quien llama."""
        if len(arg_types) != 1 or arg_types[0] != TypeAnn(VEC_MARK, [T_I32]):
            self._fail(f"{que}.write_bytes espera un Vec<i32> de bytes (0..255), se dio {arg_types}", expr)

    def _check_read_bytes(self, expr, arg_types, quien):
        """`.read_bytes(n)` sobre File/Socket, n: i32.
        Devuelve Result<Vec<i32>> con bytes 0..255 (ver interpreter.py)."""
        if len(arg_types) != 1 or arg_types[0] != T_I32:
            self._fail(f"{quien}.read_bytes espera un i32 (cantidad de bytes), se dio {arg_types}", expr)

    def _envolver_mueve(self, inner_expr, inner_ty, env, fn):
        """`Some(x)` y `Ok(x)` guardan `x` adentro, igual que un
        campo de un struct literal: con un valor no-Copy lo MUEVEN, con la
        misma regla (_campo_mueve): si `let r = Ok(v)` dejara seguir usando
        `v`, el intérprete compartiría la misma lista entre los dos (rompe la
        semántica de valor) y el nativo liberaría el Vec dos veces."""
        if self._campo_mueve(inner_expr, inner_ty, env, fn):
            self._move_if_needed(inner_expr, inner_ty, env)

    def _campo_mueve(self, fexpr, actual, env, fn) -> bool:
        """True si guardar `fexpr` en un campo de un struct literal
        mueve su raíz -- exactamente cuando el codegen le transfiere la
        propiedad al struct (que después la libera). Antes no se movía
        nada, y `C { v: v }` dejaba seguir usando `v`: use-after-free si el
        struct se liberaba o se movía primero. Un valor Copy se copia (un
        `T` con cota Numeric siempre es un número), y un str que no es
        dueño lo copia el codegen al campo; un str dueño pasado por nombre
        sí se transfiere."""
        if actual is None:
            return False
        if actual.name == "str":
            return isinstance(fexpr, Ident) and env.is_owned_alloc(fexpr.name)
        if actual.is_copy() or self._type_param_bound_ops(actual, fn):
            return False
        return True

    def _texto_donde_mov(self, nombre):
        """". Se movió en la línea N: <motivo>" (o "" si no se sabe)."""
        nodo, motivo = self._donde_mov.get(nombre, (None, None))
        linea = getattr(nodo, "line", None)
        if linea is None:
            return ""
        s = f". Se movió en la línea {linea}"
        if motivo:
            s += f": {motivo}"
        return s

    def _move_if_needed(self, arg_expr, arg_ty, env):
        """Marca la raíz de arg_expr como movida si corresponde: se usa tanto para
        argumentos de 'spawn' como para 'chan.send()', porque ambos son vías por
        las que un valor cruza el límite de una tarea hacia un thread distinto —
        la misma regla de ownership aplica a las dos (ver la nota larga en
        SpawnExpr más abajo para el razonamiento completo).

        `arg_ty.is_copy()` alcanza para decidir esto en casi todos los casos
        (structs de usuario no son Copy, se mueven; i32/f64/bool sí lo son,
        se duplican) -- pero es una propiedad puramente del TIPO ESTÁTICO, y
        eso deja de alcanzar para 'str': is_copy() dice True siempre (str es
        primitivo), pero una variable puntual puede ser dueña de un buffer
        real de heap si viene de una concatenación (A1, ver
        _is_fresh_str_concat/owned_alloc en TypeEnv). Sin este segundo
        chequeo, 'spawn(move c)' o 'ch.send(c)' con esa `c` dejarían tanto al
        emisor como al thread nuevo con acceso al mismo puntero -- exactamente
        la carrera de datos que esta función existe para evitar en structs."""
        # el resultado de una fn que puede devolver su parámetro struct
        # k ES ese argumento (mismo objeto). Moverlo (guardarlo en una
        # variable, en un contenedor, mandarlo...) mueve el argumento: si
        # no, quedaban dos nombres para el mismo objeto y, al mover uno, el
        # otro apuntaba a un bloque ya soltado (use-after-free en el nativo).
        llamada = arg_expr
        while type(llamada).__name__ == "TryExpr":
            llamada = llamada.expr
        if isinstance(llamada, Call) and isinstance(llamada.callee, Ident):
            target = self.functions.get(llamada.callee.name)
            devueltos = getattr(self, "returned_params", {}).get(llamada.callee.name, ())
            if target is not None:
                for k in devueltos:
                    if k < len(llamada.args) and k < len(target.params):
                        p_ty = target.params[k].type_ann or T_I32
                        self._move_if_needed(llamada.args[k], p_ty, env)
        root_name = self._lvalue_root_name(arg_expr)
        if root_name is None:
            return
        if arg_ty.name in (CHAN_MARK, TASK_MARK):
            return
        camino = self._camino_campo(arg_expr) if isinstance(arg_expr, FieldAccess) else None
        if camino is not None and not env.is_borrowed(root_name):
            if not arg_ty.is_copy():
                env.mark_moved_path(camino)
                self._donde_mov[root_name] = (arg_expr, self._motivo_mov)
            return
        # Un préstamo (ver `borrowed`/`_is_borrowing_get`) nunca
        # puede "moverse" -- moverlo transferiría la propiedad a un
        # SEGUNDO dueño (la task, el chan, el Vec/Map destino) mientras el
        # Vec/Map original de donde salió sigue siendo el primero, mismo
        # puntero en los dos lados. Antes esto compilaba silencioso y
        # reventaba en runtime (snake_completo.scar, ASan "Freed heap
        # region"); ahora es un error de compilación, igual que cualquier
        # otro uso indebido que este checker ya rechaza.
        if env.is_borrowed(root_name):
            self._fail(
                f"no se puede mover '{root_name}': es un préstamo de .get() "
                f"sobre un Vec/Map (el contenedor original sigue siendo su "
                f"dueño), no un valor propio que se pueda pasar a spawn/"
                f".push()/.set()/chan.send()/una asignación/return. Para "
                f"entregarlo, sácalo del contenedor: de un Vec con .pop() o "
                f".replace(i, otro), de un Map con .remove(k)",
                arg_expr,
            )
            return
        if not arg_ty.is_copy() or (arg_ty.name == "str" and env.is_owned_alloc(root_name)):
            env.mark_moved(root_name)
            self._donde_mov[root_name] = (arg_expr, self._motivo_mov)
            if (self._vuelta is not None and root_name in self._vuelta["cond"]
                    and isinstance(arg_expr, Ident)):
                # el nativo apaga el flag de dueña; el intérprete
                # deja la variable marcada como movida
                arg_expr.registra_mov = True

    @staticmethod
    def _esperados_de_metodo(obj_ty: TypeAnn, metodo: str) -> list:
        """El tipo esperado de cada argumento de un método que guarda
        un valor (push/set/replace de Vec, set de Map, send de Chan). Sin
        tipo esperado (None) en lo demás."""
        args = obj_ty.args or []
        if obj_ty.name == VEC_MARK and args:
            if metodo == "push":
                return [args[0]]
            if metodo in ("set", "replace"):
                return [T_I32, args[0]]
        if obj_ty.name == MAP_MARK and len(args) > 1 and metodo == "set":
            return [args[0], args[1]]
        if obj_ty.name == CHAN_MARK and args and metodo == "send":
            return [args[0]]
        return []

    def _infer(self, expr, env: TypeEnv, fn: FnDecl, ret_ty: TypeAnn, expected_ty: TypeAnn = None) -> TypeAnn:
        ty = self._infer_nodo(expr, env, fn, ret_ty, expected_ty)
        if isinstance(expr, FieldAccess):
            expr.tipo_lugar = ty        # ver _revisar_orden_de_lugares
        if self._registrar_tipos:
            # if_expr.bajar anota con esto los temporales
            # que saca para no cambiar el orden de evaluación
            expr.tipo_visto = ty
        return ty

    def _infer_nodo(self, expr, env: TypeEnv, fn: FnDecl, ret_ty: TypeAnn, expected_ty: TypeAnn = None) -> TypeAnn:
        if expected_ty is not None and isinstance(expr, Call):
            # vec_new()/map_new()/chan_new() toman su T de donde van (el
            # campo de un struct literal, un parámetro, un return), no solo
            # de la anotación de un `let`: `Caja { items: vec_new() }` con
            # `items: Vec<P>` es un Vec<P>.
            marca = marca_new_generico(expr)
            if marca is not None and expected_ty.name == marca and expected_ty.args:
                self._infer(expr, env, fn, ret_ty)  # valida los argumentos
                return expected_ty
        if isinstance(expr, NumLit):
            if isinstance(expr.value, float):
                return T_F64
            # Un literal entero es i32 si cabe y si no i64. Uno
            # que no entra en ningún entero no se acepta (el nativo lo
            # truncaría en silencio). El i64 más chico
            # (-9223372036854775808) solo se escribe detrás de un '-': lo
            # resuelve la rama de UnaryOp.
            ty = int_literal_type(expr.value)
            if ty is None:
                self._fail(
                    f"literal entero fuera de rango: {expr.value} no entra en un "
                    f"i64 (va de -9223372036854775808 a 9223372036854775807); si es "
                    f"un número real, escríbelo como f64: {expr.value}.0", expr)
                ty = T_I64
            expr.tipo_int = ty.name
            return ty
        if isinstance(expr, StrLit):
            return T_STR
        if isinstance(expr, BoolLit):
            return T_BOOL
        if isinstance(expr, Ident):
            if env.is_moved(expr.name) and not self._uso_en_vuelta(expr.name, expr):
                self._fail(
                    f"uso de '{expr.name}' después de haber sido movida (al cruzar "
                    f"el límite de una tarea con 'spawn'/'chan.send()', al guardarla "
                    f"en un contenedor, o al pasarla a otra variable con 'let'/'=') "
                    f"— una vez que algo se mueve, el "
                    f"dueño original pierde acceso (así se evita la carrera de "
                    f"datos / el alias invisible)" + self._texto_donde_mov(expr.name),
                    expr,
                )
            sueltos = env.moved_paths_under(expr.name)
            if sueltos:
                self._fail(
                    f"uso de '{expr.name}' después de haber movido '{sueltos[0]}' "
                    f"-- reasigna ese campo antes de usar '{expr.name}' entero"
                    + self._texto_donde_mov(expr.name),
                    expr,
                )
            try:
                return env.get(expr.name, expr)
            except TypeError_:
                # Valor función sin captura: 'expr.name' no es una variable
                # -- antes de darlo por no declarado (el error que 'env.get'
                # ya iba a lanzar), probar si es el nombre de una 'fn'
                # top-level ya declarada. Dos guardas, necesarias porque
                # self.functions
                # mezcla 'fn' y 'task' bajo el mismo dict: una 'task' no es
                # un valor función válido (no encaja en 'fn(T)->U', corre en
                # otro hilo vía spawn/TaskHandle), y una fn GENÉRICA tampoco
                # (sus params/return_type todavía tienen TypeAnn("T") sin
                # resolver -- construir un FN_MARK con eso no significa nada
                # fuera de una instanciación concreta). Si ninguna coincide,
                # re-lanza exactamente el error original: ningún cambio de
                # comportamiento para un nombre que de verdad no está
                # declarado en ningún lado.
                target = self.functions.get(expr.name)
                if target is not None and not target.is_task and not target.type_params:
                    param_types = [p.type_ann or T_I32 for p in target.params]
                    ret_type = target.return_type or T_VOID
                    self._chequear_contrato_fn_valor(expr, target)
                    return TypeAnn(FN_MARK, param_types + [ret_type])
                raise
        if isinstance(expr, NoneExpr):
            # Mismo problema de fondo que en 'let' (ver docstring del módulo):
            # None no trae ningún valor del que inferir T. Fuera de un 'let',
            # no hay anotación local -- pero el tipo esperado puede venir de
            # 'afuera' (el ret_ty de la función en un 'return', o el
            # param.type_ann/param_types[i] en un argumento), pasado aquí
            # explícitamente por el llamador vía `expected_ty`. Si ese tipo
            # esperado es un Option<T> concreto, lo usamos; si no hay
            # expected_ty (la mayoría de las 22 llamadas a _infer no lo
            # pasan) o no es un Option<T> con parámetro, mantenemos el
            # default histórico Option<i32> -- ningún cambio de
            # comportamiento para el código existente.
            if (
                expected_ty is not None
                and expected_ty.name == OPTION_MARK
                and expected_ty.args
            ):
                return expected_ty
            return TypeAnn(OPTION_MARK, [T_I32])
        if isinstance(expr, SomeExpr):
            # Lo de adentro toma el T del Option esperado
            # (Some(Err("x")) donde va un Option<Result<str>>, Some(None)
            # donde va un Option<Option<str>>); si no, lo de adentro quedaría
            # con su default (Option<i32>/Result<i32>) y sería un error de tipo.
            esperado_adentro = (expected_ty.args[0] if expected_ty is not None
                                and expected_ty.name == OPTION_MARK and expected_ty.args
                                else None)
            inner = self._infer(expr.expr, env, fn, ret_ty, expected_ty=esperado_adentro)
            self._envolver_mueve(expr.expr, inner, env, fn)
            return TypeAnn(OPTION_MARK, [inner])
        if isinstance(expr, OkExpr):
            esperado_adentro = (expected_ty.args[0] if expected_ty is not None
                                and expected_ty.name == RESULT and expected_ty.args
                                else None)
            inner = self._infer(expr.expr, env, fn, ret_ty, expected_ty=esperado_adentro)
            self._envolver_mueve(expr.expr, inner, env, fn)
            return TypeAnn(RESULT, [inner])
        if isinstance(expr, ErrExpr):
            self._infer(expr.expr, env, fn, ret_ty)  # se evalúa, tipo de error no forzado (prototipo)
            # Como None, un Err toma el tipo
            # esperado cuando lo hay (`let r: Result<str> = Err(...)`, `r =
            # Err(...)`, un argumento); si no, el del return de la fn.
            if expected_ty is not None and expected_ty.name == RESULT and expected_ty.args:
                return expected_ty
            if ret_ty.name == RESULT:
                return TypeAnn(RESULT, ret_ty.args)
            return TypeAnn(RESULT, [T_I32])

        if isinstance(expr, UnaryOp):
            if (expr.op == "-" and isinstance(expr.expr, NumLit)
                    and not isinstance(expr.expr.value, float)):
                # `-N` con N literal se pliega a un solo literal
                # negativo, con su tipo propio: -2147483648 es i32 (aunque
                # 2147483648 solo cabe en i64) y -9223372036854775808 es i64.
                v = -expr.expr.value
                ty = int_literal_type(v)
                if ty is None:
                    self._fail(
                        f"literal entero fuera de rango: {v} no entra en un i64 (va de "
                        f"-9223372036854775808 a 9223372036854775807)", expr)
                    ty = T_I64
                expr.literal_plegado = v
                expr.tipo_int = ty.name
                expr.expr.tipo_int = ty.name
                return ty
            ty = self._infer(expr.expr, env, fn, ret_ty)
            if expr.op == "-":
                if not ty.is_numeric():
                    self._fail(f"operador unario '-' requiere numérico, se dio {ty!r}", expr)
                if ty.is_integer():
                    expr.tipo_int = ty.name
                return ty
            if expr.op == "not":
                if ty != T_BOOL:
                    self._fail(f"operador 'not' requiere bool, se dio {ty!r}", expr)
                return T_BOOL

        if isinstance(expr, BinOp):
            l = self._infer(expr.left, env, fn, ret_ty)
            r = self._infer(expr.right, env, fn, ret_ty)
            if expr.op in ("and", "or"):
                if l != T_BOOL or r != T_BOOL:
                    self._fail(f"'{expr.op}' requiere bool a ambos lados, se dio {l!r} y {r!r}", expr)
                return T_BOOL
            if expr.op in ("&", "|", "^", "<<", ">>"):
                # Operadores de bits: solo enteros, sin mezcla con
                # f64 -- operan en complemento a dos, igual en los dos
                # backends. Para bool están and/or/not. También i64;
                # & | ^ con un i32 y un i64 dan i64; un corrimiento tiene el
                # tipo de la izquierda (la cantidad puede ser i32 o i64).
                if not (l.is_integer() and r.is_integer()):
                    self._fail(f"'{expr.op}' requiere enteros (i32 o i64) a ambos lados, se dio {l!r} y {r!r}", expr)
                    return T_I32
                ty = l if expr.op in ("<<", ">>") else numeric_result(l, r)
                expr.tipo_int = ty.name
                return ty
            if expr.op in ("==", "!="):
                if l.name in self.enums or r.name in self.enums:
                    enum = l.name if l.name in self.enums else r.name
                    self._fail(f"un enum no se compara con '{expr.op}' ('{enum}'): para saber "
                               f"qué variante es, usa match", expr)
                    return T_BOOL
                if not self._compatible(l, r) and not self._compatible(r, l):
                    self._fail(f"comparación entre tipos incompatibles: {l!r} vs {r!r}", expr)
                return T_BOOL
            if expr.op in ("<", ">", "<=", ">="):
                if l.is_numeric() and r.is_numeric():
                    if not numeric_mix_ok(l, r):
                        self._fallo_i64_f64(expr)
                    return T_BOOL
                # Mismo mecanismo que '+'/'-': un 'T' abstracto con bound
                # Numeric habilita comparar dos valores del MISMO T. Sin
                # bound, o con T distintos, se rechaza.
                if l == r and expr.op in self._type_param_bound_ops(l, fn):
                    return T_BOOL
                self._fail(f"'{expr.op}' requiere operandos numéricos, se dio {l!r} y {r!r}", expr)
                return T_BOOL
            if expr.op == "+" and l == T_STR and r == T_STR:
                # Concatenación de strings. Único caso no-numérico de
                # '+' — el resto de los operadores aritméticos (-, *, /)
                # siguen exclusivos de i32/f64, str no los soporta (no hay
                # "resta" de strings). Ver codegen/ (scar_str_concat) para
                # cómo se materializa esto en el backend de C, e
                # interpreter.py (apply_binop) para el intérprete, donde
                # 'l + r' ya concatena gratis vía el operador nativo de
                # Python — no requirió cambios.
                return T_STR
            if expr.op in ("+", "-"):
                if l.is_numeric() and r.is_numeric():
                    return self._resultado_numerico(expr, l, r)
                # 'T' abstracto con bound Numeric
                # habilita '+'/'-' entre dos valores del MISMO T (sin
                # bound, o con tipos T distintos, se rechaza). El resultado
                # es 'l' -- el propio T, no i32/f64 -- porque el tipo
                # concreto recién se conoce en el sitio de llamada; acá solo
                # hace falta que 'return a + b' sea compatible con un
                # retorno declarado 'T'.
                if l == r and expr.op in self._type_param_bound_ops(l, fn):
                    return l
                self._fail(f"'{expr.op}' requiere operandos numéricos, se dio {l!r} y {r!r}", expr)
                return T_I32
            if expr.op in ("*", "/", "%"):
                if l.is_numeric() and r.is_numeric():
                    return self._resultado_numerico(expr, l, r)
                # Mismo mecanismo que '+'/'-' para '*'/'/' -- '%' se deja afuera a propósito (ver
                # el comentario de BOUND_OPS), así que sigue rechazado
                # para un T abstracto igual que antes de esta etapa,
                # tenga bound o no.
                if expr.op != "%" and l == r and expr.op in self._type_param_bound_ops(l, fn):
                    return l
                self._fail(f"'{expr.op}' requiere operandos numéricos, se dio {l!r} y {r!r}", expr)
                return T_I32

        if isinstance(expr, TryExpr):
            inner_ty = self._infer(expr.expr, env, fn, ret_ty)
            if inner_ty.name != RESULT:
                self._fail(f"el operador '?' solo aplica sobre Result, se dio {inner_ty!r}", expr)
                return T_I32
            if ret_ty.name != RESULT:
                self._fail(
                    f"'?' usado dentro de '{fn.name}', que no devuelve Result "
                    f"(devuelve {ret_ty!r}) — el error no tiene a dónde propagarse",
                    expr,
                )
            return inner_ty.args[0] if inner_ty.args else T_I32

        if isinstance(expr, IfExpr):
            return self._infer_if_expr(expr, env, fn, ret_ty, expected_ty)

        if isinstance(expr, ArrayLit):
            # [a, b, c]: un Vec nuevo. El
            # tipo de los elementos sale de la anotación (`let v: Vec<f64> =
            # [1, 2]`, un parámetro, un return) o, si no hay, del primero; si
            # se mezclan enteros con f64 (`[1, 2.5]`) se amplía a f64, como
            # una cuenta. Cada elemento se trata como el argumento de un
            # push: se amplía si hace falta y, si no es Copy, se mueve.
            anotado = (expected_ty.args[0] if expected_ty is not None
                       and expected_ty.name == VEC_MARK and expected_ty.args else None)
            if not expr.elems:
                if anotado is None:
                    self._fail("un arreglo vacío [] necesita saber su tipo: anótalo "
                               "(let v: Vec<i32> = []) o usa vec_new()", expr)
                    return TypeAnn(VEC_MARK, [T_I32])
                expr.tipo_elem = anotado
                return TypeAnn(VEC_MARK, [anotado])
            inner = anotado
            tipos = []
            for e in expr.elems:
                t = self._infer(e, env, fn, ret_ty, expected_ty=inner)
                tipos.append(t)
                if inner is None:
                    inner = t
                elif (anotado is None and inner != t and inner.name in ("i32", "i64", "f64")
                      and t.name in ("i32", "i64", "f64") and numeric_mix_ok(inner, t)):
                    inner = numeric_result(inner, t)
            for e, t in zip(expr.elems, tipos):
                if not self._compatible(inner, t, e):
                    self._fail(f"los elementos de un arreglo tienen que ser todos del mismo "
                               f"tipo: se esperaba {inner!r}, se dio {t!r}{self._pista(inner, t)}", e)
                else:
                    self._move_if_needed(e, t, env)
            expr.tipo_elem = inner
            return TypeAnn(VEC_MARK, [inner])

        if isinstance(expr, StructLit):
            if expr.name not in self.structs:
                self._fail(f"struct no definido: '{expr.name}'", expr)
                return TypeAnn(expr.name)
            if expr.name in self.enums and not getattr(expr, "interno_enum", False):
                variantes = ", ".join(v for v, _ in self.enums[expr.name])
                self._fail(f"'{expr.name}' es un enum: no se construye con {{ }}, sino con "
                           f"una de sus variantes ({variantes})", expr)
                return TypeAnn(expr.name)
            decl_fields = self.structs[expr.name]
            type_params = self.struct_type_params.get(expr.name, [])

            if not type_params:
                # Camino no genérico, sin cambios de comportamiento.
                for fname, fexpr in expr.fields.items():
                    if fname not in decl_fields:
                        self._fail(f"'{expr.name}' no tiene campo '{fname}'", fexpr)
                        continue
                    expected = decl_fields[fname]
                    actual = self._infer(fexpr, env, fn, ret_ty, expected_ty=expected)
                    if not self._compatible(expected, actual, fexpr):
                        self._fail(
                            f"campo '{expr.name}.{fname}' espera {expected!r}, se dio {actual!r}"
                            f"{self._pista(expected, actual)}",
                            fexpr,
                        )
                    mueve = self._campo_mueve(fexpr, actual, env, fn)
                    if isinstance(fexpr, Ident):
                        # El codegen le entrega al campo una variable
                        # str solo si acá se movió (si no, la copia): la misma
                        # decisión en los dos.
                        fexpr.se_mueve = mueve
                    if mueve:
                        self._move_if_needed(fexpr, actual, env)
                for fname in decl_fields:
                    if fname not in expr.fields:
                        self._fail(f"falta el campo '{fname}' al construir '{expr.name}'", expr)
                return TypeAnn(expr.name)

            # Struct genérico: 'plantilla + instanciación perezosa'. Sin sintaxis explícita de instanciación (no hay 'Foo<i32>{...}'),
            # cada parámetro de tipo T se infiere de algún campo cuyo tipo
            # declarado lo menciona -- 'T' puro, o anidado dentro de un
            # contenedor (Vec<T>/Map<K,T>). '_bind_type_params' de
            # abajo unifica recursivamente el tipo declarado contra el tipo
            # ya inferido del valor real.
            actual_by_field = {}
            for fname, fexpr in expr.fields.items():
                if fname not in decl_fields:
                    self._fail(f"'{expr.name}' no tiene campo '{fname}'", fexpr)
                    continue
                actual_by_field[fname] = self._infer(fexpr, env, fn, ret_ty)
                if self._campo_mueve(fexpr, actual_by_field[fname], env, fn):
                    self._move_if_needed(fexpr, actual_by_field[fname], env)

            bindings = {}
            for fname, fty in decl_fields.items():
                if fname in actual_by_field:
                    self._bind_type_params(
                        fty, actual_by_field[fname], type_params, bindings, expr, fname
                    )

            concrete_args = [bindings.get(tp, TypeAnn(tp)) for tp in type_params]

            for fname, fexpr in expr.fields.items():
                if fname not in decl_fields:
                    continue  # ya se reportó arriba
                expected = self._substitute_type_params(decl_fields[fname], expr.name, concrete_args)
                actual = actual_by_field[fname]
                if not self._compatible(expected, actual, fexpr):
                    self._fail(
                        f"campo '{expr.name}.{fname}' espera {expected!r}, se dio {actual!r}"
                        f"{self._pista(expected, actual)}",
                        fexpr,
                    )
            for fname in decl_fields:
                if fname not in expr.fields:
                    self._fail(f"falta el campo '{fname}' al construir '{expr.name}'", expr)

            return TypeAnn(expr.name, concrete_args)

        if isinstance(expr, FieldAccess):
            camino = self._camino_campo(expr)
            if camino is not None and not env.is_moved(camino.split(".")[0]):
                conflicto = env.moved_conflict(camino)
                if conflicto is not None:
                    self._fail(
                        f"uso de '{camino}' después de haber movido '{conflicto}' "
                        f"(al guardarlo en otra variable, un contenedor, un canal o "
                        f"una task)" + self._texto_donde_mov(camino.split(".")[0]),
                        expr,
                    )
                obj_ty = self._tipo_sin_movidos(expr.obj, env, fn, ret_ty)
            else:
                obj_ty = self._infer(expr.obj, env, fn, ret_ty)
            if self._campo_de_enum(expr, obj_ty):
                return T_I32
            if obj_ty.name not in self.structs:
                self._fail(f"'{obj_ty!r}' no es un struct, no se puede acceder a '.{expr.field}'", expr)
                return T_I32
            fields = self.structs[obj_ty.name]
            if expr.field not in fields:
                self._fail(f"'{obj_ty.name}' no tiene campo '{expr.field}'", expr)
                return T_I32
            return self._substitute_type_params(fields[expr.field], obj_ty.name, obj_ty.args)

        if isinstance(expr, IndexExpr):
            # (ver docstring de IndexExpr en parser.py): solo 'str'
            # es indexable, y siempre por posición i32 -- el resultado es otro
            # str (un carácter, como str[i:i+1], no un tipo 'char' propio).
            # Mismo criterio que FieldAccess sobre un tipo sin ese campo: no es
            # un error "esperable" (no hay Option/Result de por medio), así que
            # se rechaza en el checker en vez de dejar que explote en runtime.
            obj_ty = self._infer(expr.obj, env, fn, ret_ty)
            idx_ty = self._infer(expr.index, env, fn, ret_ty)
            if obj_ty != T_STR:
                self._fail(f"'{obj_ty!r}' no es indexable con '[...]' (por ahora solo 'str' lo es)", expr)
                return T_STR
            if idx_ty != T_I32:
                self._fail(f"el índice de '[...]' debe ser i32, se dio {idx_ty!r}{self._pista(T_I32, idx_ty)}", expr.index)
            return T_STR

        if isinstance(expr, SpawnExpr):
            call = expr.call
            if not isinstance(call, Call) or not isinstance(call.callee, Ident):
                self._fail("'spawn' requiere una llamada directa a una tarea", expr)
                return TypeAnn(TASK_MARK, [T_I32])
            target = self.functions.get(call.callee.name)
            if target is None or not target.is_task:
                self._fail(f"'spawn' requiere una 'task', '{call.callee.name}' no lo es", expr)
                return TypeAnn(TASK_MARK, [T_I32])
            # para una task genérica, _check_call_args devuelve el
            # retorno ya sustituido (T -> el tipo concreto de esta llamada).
            # Antes se usaba target.return_type tal cual, y `h.join()` de un
            # `spawn juntar(1, 2)` era Vec<T>, no Vec<i32>.
            ret_generico = self._check_call_args(target, call.args, env, fn, ret_ty, call_node=expr)
            # Regla de ownership (invariante de región): todo argumento no-Copy que se
            # pasa a spawn cruza el límite de la tarea y su propiedad se transfiere.
            # El padre no puede seguir usándolo — así se evita la carrera de datos que
            # demuestra 06_ataque_region.scar sin esta regla.
            for arg_expr in call.args:
                # La raíz puede ser la variable misma (c) o, para permitir pasar
                # campos de struct como argumento, una cadena de accesos a campo
                # que arranca en una variable (o.inner). Si no hay variable raíz
                # (ej. el resultado de una llamada), es un valor temporal sin
                # dueño al que rastrear — no hay nada que mover, y no hace falta
                # re-inferir su tipo (ya se chequeó en _check_call_args de arriba).
                root_name = self._lvalue_root_name(arg_expr)
                if root_name is None:
                    continue
                arg_ty = self._infer(arg_expr, env, fn, ret_ty)
                self._move_if_needed(arg_expr, arg_ty, env)
            inner = ret_generico if ret_generico is not None else (target.return_type or T_VOID)
            # El segundo elemento de args NO es un tipo de SCAR de
            # verdad -- es el nombre de la 'task' spawneada, envuelto en un
            # TypeAnn solo para viajar adentro del marcador TASK_MARK sin
            # inventar un campo nuevo en TypeAnn (types_.py). Único consumidor:
            # inject_chan(), que necesita saber a qué 'task' le está
            # inyectando un canal para validar su 'accepts' (ver más abajo,
            # bloque 'if fname == "inject_chan"'). Nunca se compara con
            # '==' contra un TypeAnn real ni se le pide a _compatible() que
            # lo entienda -- se lee el .name a mano en el único sitio que lo
            # usa, así que no hace falta que sea un tipo "legítimo".
            return TypeAnn(TASK_MARK, [inner, TypeAnn(call.callee.name)])

        if isinstance(expr, PrintExpr):
            for a in expr.args:
                self._infer(a, env, fn, ret_ty)
            return T_VOID

        if isinstance(expr, Call):
            if not isinstance(expr.callee, Ident):
                self._fail("llamada inválida", expr)
                return T_I32
            fname = expr.callee.name
            # Valor función sin captura: si 'fname' resuelve
            # como VARIABLE (no como nombre de fn/task) con tipo FN_MARK --
            # ej. 'f(x)' donde 'f: fn(i32) -> i32' es un parámetro -- es una
            # invocación de valor función, no una llamada directa por
            # nombre. Se prueba primero y aparte de todo el resto de este
            # bloque (builtins/extern/self.functions), que sigue exactamente
            # igual que antes para toda llamada directa existente: si
            # 'fname' no es una variable (el caso de siempre, env.get()
            # lanza TypeError_) o es una variable de otro tipo, se sigue de
            # largo sin tocar nada. Mismo criterio de scoping que en Ident
            # (ver más abajo, "5.2 §6"): una variable local siempre gana
            # sobre el nombre de una fn/task, así que esto nunca compite con
            # el camino de siempre.
            try:
                callee_ty = env.get(fname, expr.callee)
            except TypeError_:
                callee_ty = None
            if callee_ty is not None and callee_ty.name == FN_MARK:
                # El codegen renombra según a qué resolvió la
                # llamada (ver nombres_c.py); una variable común con el
                # nombre de una fn no se puede llamar, así que solo este
                # caso es una variable.
                expr.callee.es_valor_fn = True
                # el codegen necesita saber qué devuelve (un str
                # devuelto es propio, como el de cualquier fn: hay que liberarlo)
                expr.callee.retorno_valor_fn = callee_ty.args[-1]
                if env.is_moved(fname):
                    self._fail(
                        f"uso de '{fname}' después de haber sido movida",
                        expr.callee,
                    )
                param_types = callee_ty.args[:-1]
                ret_type = callee_ty.args[-1]
                if len(expr.args) != len(param_types):
                    self._fail(
                        f"'{fname}' espera {len(param_types)} argumento(s), "
                        f"se dieron {len(expr.args)}",
                        expr,
                    )
                    return ret_type
                arg_types = [
                    self._infer(a, env, fn, ret_ty, expected_ty=pt)
                    for a, pt in zip(expr.args, param_types)
                ]
                for i, (pt, at) in enumerate(zip(param_types, arg_types)):
                    if not self._compatible(pt, at, expr.args[i]):
                        self._fail(
                            f"'{fname}' argumento {i+1}: se esperaba {pt!r}, se dio {at!r}"
                            f"{self._pista(pt, at)}",
                            expr.args[i],
                        )
                # un Vec/Map que se pasa a través de un valor
                # fn se mueve, igual que en una llamada directa (la fn que lo recibe
                # es su dueña). Antes `f(v)` dejaba seguir usando `v`.
                for pt, arg_expr in zip(param_types, expr.args):
                    if pt.name in (VEC_MARK, MAP_MARK):
                        self._motivo_mov = f"'{fname}' (una función) se queda con lo que recibe"
                        self._move_if_needed(arg_expr, pt, env)
                        self._motivo_mov = None
                return ret_type
            if fname == "chan_new":
                # Única builtin de aridad variable: 0 args (sin límite,
                # comportamiento de siempre) o 1 arg (capacidad del
                # canal). El arg de capacidad acepta CUALQUIER expresión
                # que resuelva a i32 -- no solo un literal -- porque
                # restringir a literal exigiría una segunda categoría de
                # chequeo (¿es esta expr un IntLit?) que no da nada a
                # cambio: la capacidad es un dato de runtime del lado de
                # C (un campo `cap` en la struct del canal, no algo que
                # el backend necesite resolver en tiempo de compilación),
                # así que 'chan_new(config.buffer_size)' es tan válido
                # como 'chan_new(4)'.
                if len(expr.args) not in (0, 1):
                    self._fail(
                        f"'chan_new' espera 0 o 1 argumento(s) (capacidad "
                        f"opcional del canal), se dieron {len(expr.args)}",
                        expr,
                    )
                elif len(expr.args) == 1:
                    cap_ty = self._infer(expr.args[0], env, fn, ret_ty, expected_ty=T_I32)
                    if cap_ty != T_I32:
                        self._fail(
                            f"'chan_new': la capacidad debe ser i32, se dio {cap_ty!r}",
                            expr.args[0],
                        )
                # Chan<i32> por default -- igual que siempre, T real lo
                # da la anotación del 'let' que lo recibe (ver
                # marca_new_generico), no esta llamada.
                return TypeAnn(CHAN_MARK, [T_I32])
            if fname == "inject_chan":
                # inject_chan(handle, ch) entrega 'ch' a una 'task' YA
                # corriendo, atada por 'handle' (TaskHandle devuelto por
                # 'spawn'). Las tres condiciones ("handle sigue
                # Activa", "la task destino declaró aceptar Chan<U>",
                # "nadie más es emisor de ese endpoint") son de runtime --
                # acá el checker solo puede probar la segunda (información
                # 100% estática, la firma de la task) y el resto de la
                # disciplina de tipos de siempre; por eso el retorno es
                # Result<()>, nunca falla en silencio si alguna de las
                # otras dos falla en runtime.
                if len(expr.args) != 2:
                    self._fail(
                        f"'inject_chan' espera 2 argumentos (handle, canal), "
                        f"se dieron {len(expr.args)}",
                        expr,
                    )
                    return TypeAnn(RESULT, [T_VOID])
                handle_ty = self._infer(expr.args[0], env, fn, ret_ty)
                chan_ty = self._infer(expr.args[1], env, fn, ret_ty)
                # El intérprete es dinámico a
                # propósito y un ScarChan no guarda su T en runtime (mismo
                # criterio que Vec/Map) -- pero para rutear la inyección al
                # slot correcto cuando la task acepta más de un tipo,
                # alguien tiene que saber el T de ESTE 'chan' en runtime.
                # En vez de agregarle un tag de tipo a todo ScarChan (un
                # cambio de arquitectura mucho más grande, innecesario para
                # este único mecanismo), se deja acá la única pieza de
                # información que hace falta: el T que este 'chan_ty' ya
                # infirió de forma 100% estática, anotado en el propio nodo
                # Call para que interpreter.py lo lea en _eval_Call (ver
                # 'expr.chan_ty' ahí) sin tener que re-inferir tipos en
                # tiempo de ejecución.
                expr.chan_ty = chan_ty
                if handle_ty.name != TASK_MARK:
                    self._fail(
                        f"'inject_chan': el primer argumento debe ser un "
                        f"TaskHandle (resultado de 'spawn'), se dio {handle_ty!r}",
                        expr.args[0],
                    )
                    return TypeAnn(RESULT, [T_VOID])
                if chan_ty.name != CHAN_MARK:
                    self._fail(
                        f"'inject_chan': el segundo argumento debe ser "
                        f"Chan<T>, se dio {chan_ty!r}",
                        expr.args[1],
                    )
                    return TypeAnn(RESULT, [T_VOID])
                # handle_ty.args[1] es el nombre de la task spawneada (ver
                # el comentario en SpawnExpr, más arriba) -- si por algún
                # motivo no está (ej. 'spawn' con error previo, que ya
                # devuelve TypeAnn(TASK_MARK, [T_I32]) sin segundo elemento),
                # no hay task concreta contra la cual validar 'accepts':
                # ya se reportó un error aparte en ese 'spawn', no hace
                # falta uno más acá.
                if len(handle_ty.args) >= 2:
                    task_name = handle_ty.args[1].name
                    target = self.functions.get(task_name)
                    if target is not None and chan_ty not in target.accepts:
                        self._fail(
                            f"'inject_chan': la task '{task_name}' no declaró "
                            f"aceptar {chan_ty!r} por inyección (agregar "
                            f"'accepts {chan_ty!r}' a su firma)",
                            expr.args[1],
                        )
                # Mismo motivo que chan.send()/spawn: el canal cruza el
                # límite de la task destino, así que el emisor no puede
                # seguir usándolo -- de lo contrario dos tasks terminarían
                # compartiendo el mismo extremo emisor, la clase de ataque
                # que 06/08_ataque_region.scar prueban para otros casos.
                self._move_if_needed(expr.args[1], chan_ty, env)
                return TypeAnn(RESULT, [T_VOID])
            if fname == "accept_chan":
                # Contraparte de inject_chan(), llamada DESDE ADENTRO de la
                # propia task para recibir lo que le inyectaron. Sin
                # argumentos -- igual que chan_new()/vec_new(), no hay de
                # dónde inferir T sin la anotación del 'let' que la recibe
                # (ver marca_new_generico y el branch dedicado en
                # _check_stmt/LetStmt). Devuelve Option<Chan<T>>, no
                # Chan<T> directo ni Result<Chan<T>>: el mismo criterio que
                # ya usa chan.recv() (Option<T>, no Result<T>) -- que
                # todavía no haya llegado ninguna inyección no es un error,
                # es el estado normal de una task que arrancó sin
                # 'accepts' pendientes de resolver todavía.
                if not self._accept_chan_ok:
                    # El único sitio donde T tiene de
                    # dónde salir es la anotación de un 'let' (ver el branch
                    # dedicado en _check_stmt/LetStmt, que prende
                    # '_accept_chan_ok' justo antes de esta llamada). Fuera
                    # de eso -- 'while let Some(x) = accept_chan()', un
                    # 'accept_chan();' suelto, o anidado como argumento de
                    # otra llamada -- no hay forma honesta de saber T, así
                    # que antes esto devolvía Option<Chan<i32>> por default
                    # (i32 inventado) sin siquiera validar contra 'accepts'.
                    # Con más de un tipo aceptado eso ya no es solo
                    # cosmético: el runtime no tendría de qué slot drenar.
                    # Se rechaza en compilación en vez de adivinar.
                    self._fail(
                        "'accept_chan()' solo puede usarse como la expresión "
                        "de un 'let' anotado, ej. "
                        "'let x: Option<Chan<T>> = accept_chan()' -- no hay "
                        "otra forma de que el compilador sepa qué T se "
                        "espera",
                        expr,
                    )
                    return TypeAnn(OPTION_MARK, [TypeAnn(CHAN_MARK, [T_I32])])
                if expr.args:
                    self._fail(
                        f"'accept_chan' no toma argumentos, se dieron "
                        f"{len(expr.args)}",
                        expr,
                    )
                if not fn.is_task:
                    self._fail(
                        "'accept_chan' solo puede usarse dentro de una 'task'",
                        expr,
                    )
                elif not fn.accepts:
                    self._fail(
                        f"'accept_chan': la task '{fn.name}' no declaró "
                        f"ningún tipo con 'accepts' en su firma",
                        expr,
                    )
                return TypeAnn(OPTION_MARK, [TypeAnn(CHAN_MARK, [T_I32])])
            if fname == "vec_new":
                # Mismo mecanismo que chan_new() de arriba: aridad variable
                # (0 args de siempre, o 1 arg de capacidad inicial del
                # buffer -- ver scar_vec_new_<T> en codegen/). El caso
                # CON anotación (`let v: Vec<T> = vec_new(cap)`) lo maneja
                # el branch dedicado de _check_stmt/LetStmt, que valida
                # 'cap' ahí (de ahí que acá no haga falta duplicar el
                # chequeo si YA hay anotación -- pero sí es el único camino
                # que valida 'cap' para un 'vec_new(cap)' SIN anotación
                # alrededor, ej. pasado directo como argumento de otra
                # función).
                if len(expr.args) not in (0, 1):
                    self._fail(
                        f"'vec_new' espera 0 o 1 argumento(s) (capacidad "
                        f"inicial opcional del buffer), se dieron "
                        f"{len(expr.args)}",
                        expr,
                    )
                elif len(expr.args) == 1:
                    cap_ty = self._infer(expr.args[0], env, fn, ret_ty, expected_ty=T_I32)
                    if cap_ty != T_I32:
                        self._fail(
                            f"'vec_new': la capacidad debe ser i32, se dio {cap_ty!r}",
                            expr.args[0],
                        )
                # Vec<i32> por default -- igual que chan_new(), T real lo
                # da la anotación del 'let' que lo recibe (ver
                # marca_new_generico), no esta llamada.
                return TypeAnn(VEC_MARK, [T_I32])
            if fname in ("abs", "min", "max"):
                # abs/min/max de cualquier número,
                # exactos para enteros. abs(x) es del tipo de x; min/max siguen
                # la regla de una suma (i32 con i64 da i64, i32 con f64 da f64,
                # i64 con f64 es un error), y el argumento que se amplía se
                # marca igual que en una asignación.
                n_args = 1 if fname == "abs" else 2
                if len(expr.args) != n_args:
                    self._fail(f"'{fname}' espera {n_args} argumento(s), se dieron {len(expr.args)}", expr)
                    return T_F64
                tys = [self._infer(a, env, fn, ret_ty) for a in expr.args]
                for a, t in zip(expr.args, tys):
                    if not t.is_numeric():
                        self._fail(f"'{fname}' espera un número (i32, i64 o f64), se dio {t!r}", a)
                        return T_F64
                if fname == "abs":
                    res = tys[0]
                else:
                    res = numeric_result(tys[0], tys[1])
                    if res is None:
                        self._fail(
                            f"'{fname}' entre i64 y f64: convierte uno de los dos con to_f64() o "
                            f"to_i64() (de i64 a f64 se puede perder precisión)", expr)
                        return T_I64
                    for a, t in zip(expr.args, tys):
                        self._compatible(res, t, a)
                if res.is_integer():
                    expr.tipo_int = res.name
                return res
            if fname == "a_texto":
                if len(expr.args) != 1:
                    self._fail(f"'a_texto' espera 1 argumento, se dieron {len(expr.args)}", expr)
                    return T_STR
                at = self._infer(expr.args[0], env, fn, ret_ty)
                if at.name not in ("i32", "i64", "f64", "bool", "str") or at.args:
                    self._fail(f"'a_texto' convierte un número, un bool o un str; se dio {at!r}",
                               expr.args[0])
                return T_STR
            if fname in ("to_i32", "to_i64", "to_f64"):
                # Conversiones explícitas entre los tres números.
                destino = {"to_i32": T_I32, "to_i64": T_I64, "to_f64": T_F64}[fname]
                if len(expr.args) != 1:
                    self._fail(f"'{fname}' espera 1 argumento, se dieron {len(expr.args)}", expr)
                    return destino
                at = self._infer(expr.args[0], env, fn, ret_ty)
                if not at.is_numeric():
                    self._fail(f"'{fname}' espera un número (i32, i64 o f64), se dio {at!r}", expr.args[0])
                expr.tipo_origen = at.name
                return destino
            if fname in BUILTIN_FN_TYPES:
                param_types, ret = BUILTIN_FN_TYPES[fname]
                # zip corta en el más corto -- si sobran args (aridad ya mal),
                # esos quedan sin expected_ty (None), que es el mismo default
                # seguro que ya tenía todo el código antes de este cambio.
                arg_types = [
                    self._infer(a, env, fn, ret_ty, expected_ty=pt)
                    for a, pt in zip(expr.args, param_types)
                ]
                arg_types += [
                    self._infer(a, env, fn, ret_ty)
                    for a in expr.args[len(param_types):]
                ]
                if len(arg_types) != len(param_types):
                    self._fail(f"'{fname}' espera {len(param_types)} argumento(s), se dieron {len(arg_types)}", expr)
                else:
                    for i, (pt, at) in enumerate(zip(param_types, arg_types)):
                        if not self._compatible(pt, at, expr.args[i]):
                            self._fail(
                                f"'{fname}' argumento {i+1}: se esperaba {pt!r}, se dio {at!r}"
                                f"{self._pista(pt, at)}",
                                expr.args[i],
                            )
                return ret
            extern_target = self.extern_functions.get(fname)
            if extern_target is not None:
                # Misma forma que FnDecl para lo que _check_call_args necesita
                # (.params con .type_ann, .name) -- se reutiliza tal cual, sin
                # duplicar la lógica de aridad/tipos de argumentos.
                self._check_call_args(extern_target, expr.args, env, fn, ret_ty, call_node=expr)
                # FFI: un parámetro 'own T' TOMA POSESIÓN del handle
                # -- mismo mecanismo de _move_if_needed que ya usan spawn/
                # chan.send()/Vec.push()/Map.set() para lo mismo. Un
                # parámetro SIN 'own' es préstamo (no se mueve), así que
                # 'zc_stream_write(s, ...)' se puede llamar varias veces,
                # pero 'zc_stream_free(s)' (con 's: own ZStream' en su
                # firma) deja 's' movida -- un segundo uso, incluyendo un
                # segundo .free(), se rechaza como cualquier otro
                # use-after-move, cerrando double-free/use-after-close en
                # tiempo de compilación en vez de dejarlo como UB de C.
                for p, arg_expr in zip(extern_target.params, expr.args):
                    if p.consumes:
                        self._move_if_needed(arg_expr, p.type_ann, env)
                    if (p.type_ann is not None and p.type_ann.name == VEC_MARK
                            and self._lvalue_root_name(arg_expr) is None):
                        # Lo que C cambie vuelve al Vec, así que tiene
                        # que ser de alguien (y el nativo no tiene a quién
                        # devolverle un temporal para liberarlo).
                        self._fail(
                            f"'{fname}': el Vec del parámetro '{p.name}' se presta a C y lo que C "
                            f"cambie vuelve a él: pasa una variable (o un campo), no un valor "
                            f"armado en la llamada",
                            arg_expr,
                        )
                return extern_target.return_type or T_VOID
            target = self.functions.get(fname)
            if target is None:
                self._fail(f"función no definida: '{fname}'", expr)
                return T_I32
            generic_ret = self._check_call_args(target, expr.args, env, fn, ret_ty, call_node=expr)
            # Mismo mecanismo que usan spawn/chan.send()/.push()/.set()
            # (_move_if_needed) -- una `fn`/`task` normal (llamada directa,
            # sin `spawn`) también recibe sus parámetros por valor real en
            # el backend de C (ver gen_fn/_note_owner_transfer), así que un
            # Vec<T>/Map<K,V> pasado así deja de ser del llamador. Acotado a
            # Vec<T>/Map<K,V> a propósito: los structs de usuario siguen
            # recibiéndose por ALIAS en una `fn` normal (salvo los que la fn
            # consume, ver `consumed` abajo).
            consumed = getattr(self, "consumed_params", {}).get(fname, ())
            for j, (p, arg_expr) in enumerate(zip(target.params, expr.args)):
                p_ty = p.type_ann or T_I32
                if p_ty.name in (VEC_MARK, MAP_MARK):
                    self._move_if_needed(arg_expr, p_ty, env)
                elif (j in getattr(self, "consumed_option_params", {}).get(fname, ())
                        and p_ty.name == "Option" and p_ty.args and p_ty.args[0].name in self.structs):
                    # Gemelo para Option<Struct> (la fn se queda con
                    # el contenido en algún camino): el argumento se mueve.
                    self._move_if_needed(arg_expr, p_ty, env)
                elif j in consumed and p_ty.name in self.structs:
                    # Esta fn se queda con el struct (lo mete en un contenedor,
                    # lo embebe, lo devuelve envuelto...): el argumento se
                    # mueve, igual que un Vec/Map, para que el llamador no lo
                    # siga usando ni liberando mientras el contenedor lo tiene.
                    porque = self.consumed_motivos.get(fname, {}).get(j)
                    self._motivo_mov = (f"{fname}() se queda con su parámetro '{p.name}'"
                                        + (f" porque {porque}" if porque else ""))
                    self._move_if_needed(arg_expr, p_ty, env)
                    self._motivo_mov = None
            # Para una fn no genérica, `_check_call_args`
            # devuelve None (camino de siempre, sin cambios) y este 'or'
            # cae exactamente al mismo `target.return_type or T_VOID` de
            # antes -- para una fn genérica, ya viene sustituido (ver
            # `_check_generic_call_args`).
            return generic_ret if generic_ret is not None else (target.return_type or T_VOID)

        if isinstance(expr, MethodCall):
            obj_ty = self._infer(expr.obj, env, fn, ret_ty)
            esperado_match = getattr(expr, "match_sobre", None)
            if esperado_match is not None and obj_ty.name != esperado_match:
                # la condición que arma enum_match para un match
                # sobre un Option/Result; el error habla del match, no del
                # método que el usuario no escribió
                if getattr(expr, "match_error_ya_dado", False):
                    return T_STR
                pats = "Some/None" if esperado_match == OPTION_MARK else "Ok/Err"
                self._fail(f"un match con {pats} es sobre un {esperado_match}, y el valor es "
                           f"de tipo {obj_ty!r}", expr)
                return T_BOOL
            # El valor que entra a un Vec, Map o Chan toma el tipo
            # del elemento, como un argumento de fn: v.push(None) en un
            # Vec<Option<str>> o m.set(k, Err("x")) en un Map<K, Result<str>>.
            esperados = self._esperados_de_metodo(obj_ty, expr.method)
            arg_types = [
                self._infer(a, env, fn, ret_ty,
                            expected_ty=esperados[i] if i < len(esperados) else None)
                for i, a in enumerate(expr.args)
            ]
            if obj_ty.name == TASK_MARK:
                if expr.method == "join":
                    return obj_ty.args[0] if obj_ty.args else T_VOID
                self._fail(f"Task no tiene método '.{expr.method}()'", expr)
                return T_I32
            if obj_ty.name == CHAN_MARK:
                inner = obj_ty.args[0] if obj_ty.args else T_I32
                if expr.method == "send":
                    if len(arg_types) == 1:
                        if not self._compatible(inner, arg_types[0], expr.args[0]):
                            self._fail(f"chan.send espera {inner!r}, se dio {arg_types[0]!r}"
                                       f"{self._pista(inner, arg_types[0])}", expr.args[0])
                        else:
                            # Mismo motivo que en 'spawn': un canal es la vía
                            # sancionada para cruzar el límite de una tarea, y
                            # ScarChan.send() en el intérprete NO copia — pasa la
                            # misma referencia al thread receptor. Si el valor no
                            # es Copy, hay que moverlo (que el emisor no lo pueda
                            # seguir usando), o dos threads terminan compartiendo
                            # el mismo struct mutable por esta puerta en vez de la
                            # de 'spawn'.
                            self._move_if_needed(expr.args[0], arg_types[0], env)
                    return T_VOID
                if expr.method in ("recv", "try_recv"):
                    # try_recv(): no espera; None
                    # si en este momento no hay nada encolado
                    return TypeAnn(OPTION_MARK, [inner])
                if expr.method == "close":
                    return T_VOID
                if expr.method in ("sender", "receiver"):
                    return obj_ty
                self._fail(f"Chan no tiene método '.{expr.method}()'", expr)
                return T_I32
            if obj_ty.name == PIPE_MARK:
                if expr.method in ("read_fd", "write_fd"):
                    return T_I32
                self._fail(f"Pipe no tiene método '.{expr.method}()'", expr)
                return T_I32
            if obj_ty.name == FILE_MARK:
                if expr.method == "read_all":
                    return TypeAnn(RESULT, [T_STR])
                if expr.method == "read_bytes":
                    self._check_read_bytes(expr, arg_types, "file")
                    return TypeAnn(RESULT, [TypeAnn(VEC_MARK, [T_I32])])
                if expr.method == "write":
                    if len(arg_types) == 1 and not self._compatible(T_STR, arg_types[0]):
                        self._fail(f"file.write espera str, se dio {arg_types[0]!r}", expr.args[0])
                    return TypeAnn(RESULT, [T_I32])
                if expr.method == "write_bytes":
                    self._check_write_bytes(expr, arg_types, "file")
                    return TypeAnn(RESULT, [T_I32])
                if expr.method == "close":
                    return T_VOID
                self._fail(f"File no tiene método '.{expr.method}()'", expr)
                return T_I32
            if obj_ty.name == SOCKET_MARK:
                if expr.method == "read":
                    return TypeAnn(RESULT, [T_STR])
                if expr.method == "read_bytes":
                    self._check_read_bytes(expr, arg_types, "socket")
                    return TypeAnn(RESULT, [TypeAnn(VEC_MARK, [T_I32])])
                if expr.method == "write":
                    if len(arg_types) == 1 and not self._compatible(T_STR, arg_types[0]):
                        self._fail(f"socket.write espera str, se dio {arg_types[0]!r}", expr.args[0])
                    return TypeAnn(RESULT, [T_I32])
                if expr.method == "write_bytes":
                    self._check_write_bytes(expr, arg_types, "socket")
                    return TypeAnn(RESULT, [T_I32])
                if expr.method == "close":
                    return T_VOID
                self._fail(f"Socket no tiene método '.{expr.method}()'", expr)
                return T_I32
            if obj_ty.name == LISTENER_MARK:
                if expr.method == "accept":
                    return TypeAnn(RESULT, [TypeAnn(SOCKET_MARK)])
                if expr.method == "close":
                    return T_VOID
                self._fail(f"Listener no tiene método '.{expr.method}()'", expr)
                return T_I32
            if obj_ty.name in (RESULT, OPTION_MARK):
                return self._metodo_result_option(expr, obj_ty, arg_types)
            if obj_ty.name == VEC_MARK:
                inner = obj_ty.args[0] if obj_ty.args else T_I32
                if expr.method == "push":
                    if len(arg_types) == 1:
                        if not self._compatible(inner, arg_types[0], expr.args[0]):
                            self._fail(f"vec.push espera {inner!r}, se dio {arg_types[0]!r}"
                                       f"{self._pista(inner, arg_types[0])}", expr.args[0])
                        else:
                            # Mismo razonamiento que chan.send(): empujar un
                            # valor no-Copy al Vec le transfiere la propiedad
                            # (ScarVec.push() en el intérprete guarda la misma
                            # referencia, no una copia) — si el emisor pudiera
                            # seguir usando la variable original, dos lugares
                            # (el Vec y la variable) apuntarían al mismo struct
                            # mutable, la misma clase de ataque que 06/08.
                            self._move_if_needed(expr.args[0], arg_types[0], env)
                    else:
                        self._fail(f"vec.push espera 1 argumento, se dieron {len(arg_types)}", expr)
                    return T_VOID
                if expr.method == "get":
                    if len(arg_types) != 1 or arg_types[0] != T_I32:
                        self._fail(f"vec.get espera un índice i32, se dio {arg_types}", expr)
                    return TypeAnn(OPTION_MARK, [inner])
                if expr.method == "pop":
                    return TypeAnn(OPTION_MARK, [inner])
                if expr.method == "set":
                    # Mutación indexada (la usa el tape de Grad<T>), a
                    # diferencia de push() no cambia len -- el índice tiene
                    # que existir ya (chequeado en runtime, ver ScarVec.set()
                    # en el intérprete / scar_vec_set_<T> en codegen/).
                    if len(arg_types) != 2:
                        self._fail(f"vec.set espera 2 argumentos (índice, valor), se dieron {len(arg_types)}", expr)
                    else:
                        if arg_types[0] != T_I32:
                            self._fail(f"vec.set espera un índice i32, se dio {arg_types[0]!r}", expr.args[0])
                        if not self._compatible(inner, arg_types[1], expr.args[1]):
                            self._fail(f"vec.set espera {inner!r}, se dio {arg_types[1]!r}"
                                       f"{self._pista(inner, arg_types[1])}", expr.args[1])
                        else:
                            # Mismo razonamiento que vec.push(): el valor que
                            # entra al Vec le transfiere la propiedad al Vec.
                            self._move_if_needed(expr.args[1], arg_types[1], env)
                    return T_VOID
                if expr.method == "replace":
                    # v.replace(i, x) pone x en el lugar i y devuelve
                    # el que estaba, sin copiarlo (pasa a ser de quien llama).
                    # x entra al Vec como en set() (se mueve).
                    if len(arg_types) != 2:
                        self._fail(f"vec.replace espera 2 argumentos (índice, valor), se dieron {len(arg_types)}", expr)
                    else:
                        if arg_types[0] != T_I32:
                            self._fail(f"vec.replace espera un índice i32, se dio {arg_types[0]!r}", expr.args[0])
                        if not self._compatible(inner, arg_types[1], expr.args[1]):
                            self._fail(f"vec.replace espera {inner!r}, se dio {arg_types[1]!r}"
                                       f"{self._pista(inner, arg_types[1])}", expr.args[1])
                        else:
                            self._move_if_needed(expr.args[1], arg_types[1], env)
                    # el nativo libera el str que devuelve si nadie se queda
                    # con él (no sabe el tipo sin el entorno)
                    expr.devuelve_str = inner == T_STR
                    # en una fn genérica inner puede ser T: el codegen lo
                    # resuelve en cada instancia (Vec<T> con T = str)
                    expr.tipo_replace = inner
                    return inner
                if expr.method == "len":
                    return T_I32
                self._fail(f"Vec no tiene método '.{expr.method}()'", expr)
                return T_I32
            if obj_ty.name == MAP_MARK:
                key_ty = obj_ty.args[0] if obj_ty.args else T_I32
                val_ty = obj_ty.args[1] if len(obj_ty.args) > 1 else T_I32
                if expr.method == "set":
                    if len(arg_types) != 2:
                        self._fail(f"map.set espera 2 argumentos (key, value), se dieron {len(arg_types)}", expr)
                    else:
                        if not self._compatible(key_ty, arg_types[0], expr.args[0]):
                            self._fail(f"map.set espera key {key_ty!r}, se dio {arg_types[0]!r}", expr.args[0])
                        if not self._compatible(val_ty, arg_types[1], expr.args[1]):
                            self._fail(f"map.set espera value {val_ty!r}, se dio {arg_types[1]!r}", expr.args[1])
                        else:
                            # Mismo razonamiento que vec.push()/chan.send(): guardar
                            # un valor no-Copy en el Map le transfiere la propiedad
                            # (ScarMap.set() en el intérprete guarda la misma
                            # referencia, no una copia).
                            self._move_if_needed(expr.args[1], arg_types[1], env)
                    return T_VOID
                if expr.method == "get":
                    if len(arg_types) != 1 or not self._compatible(key_ty, arg_types[0], expr.args[0]):
                        self._fail(f"map.get espera una key {key_ty!r}, se dio {arg_types}", expr)
                    return TypeAnn(OPTION_MARK, [val_ty])
                if expr.method == "remove":
                    if len(arg_types) != 1 or not self._compatible(key_ty, arg_types[0], expr.args[0]):
                        self._fail(f"map.remove espera una key {key_ty!r}, se dio {arg_types}", expr)
                    return TypeAnn(OPTION_MARK, [val_ty])
                if expr.method == "len":
                    return T_I32
                self._fail(f"Map no tiene método '.{expr.method}()'", expr)
                return T_I32
            if obj_ty.name == "str":
                # Métodos de solo lectura sobre str. A diferencia de la
                # concatenación, ninguno de estos aloca memoria nueva --
                # .len() cuenta, .contains()/.starts_with()/.ends_with() solo
                # comparan -- así que no interactúan con el ownership
                # tracking. .len() está TANTO como función global (len(s))
                # como método (s.len()).
                if expr.method == "len":
                    if arg_types:
                        self._fail(f"'.len()' no toma argumentos, se dieron {len(arg_types)}", expr)
                    return T_I32
                if expr.method in ("contains", "starts_with", "ends_with"):
                    if len(arg_types) != 1 or arg_types[0] != T_STR:
                        self._fail(
                            f"'.{expr.method}()' espera un argumento str, se dio {arg_types}",
                            expr,
                        )
                    return T_BOOL
                self._fail(f"str no tiene método '.{expr.method}()'", expr)
                return T_I32
            self._fail(f"tipo '{obj_ty!r}' no tiene método '.{expr.method}()'", expr)
            return T_I32

        self._fail(f"expresión no soportada por el checker: {type(expr).__name__}", expr)
        return T_I32

    def _camino_campo(self, expr):
        """"r.a.b" para una cadena de campos que arranca en una
        variable; None si no."""
        partes = []
        while isinstance(expr, FieldAccess):
            partes.append(expr.field)
            expr = expr.obj
        if not isinstance(expr, Ident) or not partes:
            return None
        return ".".join([expr.name] + list(reversed(partes)))

    def _tipo_sin_movidos(self, expr, env, fn, ret_ty):
        """Tipo de una variable o cadena de campos sin el chequeo de
        'movido' del Ident (el camino ya se chequeó entero en FieldAccess)."""
        if isinstance(expr, Ident):
            if env.is_moved(expr.name):
                return self._infer(expr, env, fn, ret_ty)  # reporta el error de siempre
            return env.get(expr.name, expr)
        if isinstance(expr, FieldAccess):
            obj_ty = self._tipo_sin_movidos(expr.obj, env, fn, ret_ty)
            if (obj_ty.name not in self.structs or expr.field not in self.structs[obj_ty.name]
                    or obj_ty.name in self.enums):
                return self._infer(expr, env, fn, ret_ty)
            return self._substitute_type_params(
                self.structs[obj_ty.name][expr.field], obj_ty.name, obj_ty.args)
        return self._infer(expr, env, fn, ret_ty)

    def _campo_de_enum(self, expr, obj_ty):
        """Un acceso a campo que toca un enum. Los que arma
        enum_match (marcados con `interno_enum`) leen el tag y los datos: ahí
        se chequea que el valor del match sea del enum de sus brazos (una
        sola vez por match). Uno escrito por el usuario es un error: un enum
        no tiene campos. True si hubo error (el llamador devuelve i32)."""
        enum = getattr(expr, "interno_enum", None)
        if enum is not None:
            if obj_ty.name == enum:
                return False
            clave = (getattr(expr.obj, "line", None), getattr(expr.obj, "col", None), enum)
            if clave not in self._match_reportados:
                self._match_reportados.add(clave)
                self._fail(f"el match es sobre un valor de tipo '{obj_ty!r}', pero sus "
                           f"brazos son variantes del enum '{enum}'", expr.obj)
            return True
        if obj_ty.name in self.enums:
            self._fail(f"'{obj_ty.name}' es un enum: no tiene campos; lo que trae cada "
                       f"variante se lee con match", expr)
            return True
        return False

    def _lvalue_root_name(self, expr):
        """Si expr es una variable, o una cadena de accesos a campo que arranca en
        una variable (ej. o.inner.valor -> 'o'), devuelve el nombre de esa variable
        raíz. Si no (es el resultado de una llamada, un literal, etc. -- un valor
        temporal que no tiene una variable dueña a la que rastrear), devuelve None.
        """
        while isinstance(expr, FieldAccess):
            expr = expr.obj
        if isinstance(expr, Ident):
            return expr.name
        return None

    def _check_call_args(self, target: FnDecl, arg_exprs, env, fn, ret_ty, call_node=None):
        # Si 'target' es una fn/task genérica
        # (`target.type_params` no vacío), el camino de abajo NO sirve
        # tal cual -- comparar un argumento real contra un TypeAnn('T')
        # declarado siempre fallaría. Se delega a `_check_generic_call_args`, que infiere y unifica T
        # contra los argumentos reales de ESTE sitio de llamada en vez
        # de exigir una coincidencia literal. `getattr` con default:
        # un ExternFnDecl (que también pasa por acá, ver el llamador de
        # más arriba) no tiene `.type_params` -- nunca es genérico, cae
        # directo al camino de siempre.
        type_params = getattr(target, "type_params", None) or []
        if type_params:
            return self._check_generic_call_args(target, type_params, arg_exprs, env, fn, ret_ty, call_node)
        # Mismo criterio que en BUILTIN_FN_TYPES: pasamos el tipo declarado de
        # cada parámetro como expected_ty, para que un 'None' como argumento
        # pueda resolver Option<T> en vez de quedar fijo a Option<i32>.
        arg_types = [
            self._infer(a, env, fn, ret_ty, expected_ty=(p.type_ann or T_I32))
            for a, p in zip(arg_exprs, target.params)
        ]
        arg_types += [
            self._infer(a, env, fn, ret_ty)
            for a in arg_exprs[len(target.params):]
        ]
        if len(arg_types) != len(target.params):
            self._fail(
                f"'{target.name}' espera {len(target.params)} argumento(s), se dieron {len(arg_types)}",
                call_node,
            )
            return None
        for i, (p, at) in enumerate(zip(target.params, arg_types)):
            expected = p.type_ann or T_I32
            if not self._compatible(expected, at, arg_exprs[i]):
                self._fail(
                    f"'{target.name}' argumento {i+1} ('{p.name}'): se esperaba {expected!r}, se dio {at!r}"
                    f"{self._pista(expected, at)}",
                    arg_exprs[i],
                )
        return None

    def _bound_satisfied(self, bound_name: str, ty: TypeAnn) -> bool:
        """Valida un tipo concreto ya inferido para un
        parámetro de tipo contra el nombre de un bound (ej. 'Numeric').
        Mismo pragmatismo que BOUND_OPS: un bound que no está en esta
        tabla no rechaza nada (se comporta como si no tuviera bound) --
        no hay bounds "definidos por el usuario"."""
        if bound_name == "Numeric":
            return ty.is_numeric()
        return True

    def _bound_forwarded(self, bound_name: str, ty: TypeAnn, fn) -> bool:
        """`fn f<T: Numeric>` que llama
        a `fn g<U: Numeric>` reenviando su propio `T`. Dentro de `f`, el
        tipo del argumento es el placeholder `T` (todavía no hay tipo
        concreto -- se sustituye recién al monomorfizar, ver
        _ensure_generic_fn_instance), y `TypeAnn('T').is_numeric()` es
        False, así que `_bound_satisfied` lo rechazaría aunque `f` ya
        declare el mismo bound sobre `T`. Acá: si `ty` es un parámetro de
        tipo PURO de la función que hace la llamada (`fn`) y esa función
        le declara un bound que implica el exigido, se acepta -- toda
        instancia concreta de `f` ya fue validada contra ese bound en SU
        propio sitio de llamada, así que el tipo que llegue a `g` lo
        cumple por construcción. Como el único bound es 'Numeric' (ver
        BOUND_OPS), implicar es tener el mismo nombre."""
        if fn is None or ty.args:
            return False
        if ty.name not in getattr(fn, "type_params", ()):
            return False
        caller_bound = getattr(fn, "type_bounds", {}).get(ty.name)
        return caller_bound is not None and caller_bound == bound_name

    def _check_generic_call_args(self, target: FnDecl, type_params, arg_exprs, env, fn, ret_ty, call_node):
        """Llamar a una fn/task genérica con argumentos concretos. Infiere el tipo real de cada argumento sin ninguna
        pista (`expected_ty=None`: pasar el 'T' declarado no ayudaría,
        es un placeholder opaco, no un `Option<T>`/etc. real del que
        valga la pena propagar el interior), unifica cada parámetro
        declarado (puede mencionar 'T', posiblemente anidado en
        Vec<T>/Map<K,T>) contra ese tipo real vía `_bind_fn_type_params`
        (fija `bindings[T]`), y recién con los bindings ya fijos valida
        aridad/compatibilidad -- mismo criterio que `_check_call_args`
        de siempre, pero comparando contra el tipo YA sustituido en vez
        del 'T' crudo. Devuelve el tipo de retorno de la función, con
        cualquier 'T' que aparezca ahí también sustituido por su binding
        (identidad si el retorno no menciona ningún type_param, ej.
        `-> i32` fijo) -- el llamador
        (`_infer`/Call) lo usa en vez de `target.return_type` a secas."""
        arg_types = [self._infer(a, env, fn, ret_ty) for a in arg_exprs]
        if len(arg_types) != len(target.params):
            self._fail(
                f"'{target.name}' espera {len(target.params)} argumento(s), se dieron {len(arg_types)}",
                call_node,
            )
            return target.return_type or T_VOID
        bindings = {}
        for p, at in zip(target.params, arg_types):
            p_ty = p.type_ann or T_I32
            self._bind_fn_type_params(p_ty, at, type_params, bindings, call_node, p.name, target.name)
        # Con los bindings ya fijos, valida que cada
        # 'T' con bound (ej. 'T: Numeric') se haya atado a un tipo
        # concreto que en verdad lo satisface -- 'sumar<T: Numeric>'
        # llamado con T=str debe rechazarse ACÁ (checker), nunca llegar
        # a codegen//C. Un type_param sin bound (`target.type_bounds`
        # no lo menciona) no pasa por este chequeo.
        for tp, bound in getattr(target, "type_bounds", {}).items():
            bound_ty = bindings.get(tp)
            if bound_ty is not None and not self._bound_satisfied(bound, bound_ty) and not self._bound_forwarded(bound, bound_ty, fn):
                self._fail(
                    f"'{target.name}': '{tp}' requiere el bound '{bound}', se dio {bound_ty!r}",
                    call_node,
                )
        for i, (p, at) in enumerate(zip(target.params, arg_types)):
            p_ty = p.type_ann or T_I32
            expected = self._substitute_type_params_list(p_ty, type_params, bindings)
            if not self._compatible(expected, at, arg_exprs[i]):
                self._fail(
                    f"'{target.name}' argumento {i+1} ('{p.name}'): se esperaba {expected!r}, se dio {at!r}"
                    f"{self._pista(expected, at)}",
                    arg_exprs[i],
                )
        return self._substitute_type_params_list(target.return_type or T_VOID, type_params, bindings)


def check(program: Program):
    """Devuelve la lista de errores de tipo (vacía si el programa es válido).

    Antes baja los enum y match (enum_match.py) en el lugar; el
    programa que reciben después el intérprete y el codegen es el bajado. Un
    error de enum/match se devuelve solo, sin correr el resto del checker
    (ver el docstring de enum_match)."""
    # main -> Result<i32> se baja antes (su envoltorio usa un match)
    errores = bajar_main_result(program) or bajar_enums(program, NOMBRES_BUILTIN)
    if errores:
        return [TypeError_(e.msg, e.line, e.col, getattr(e, "archivo", None)) for e in errores]
    # `continue` se baja a if (continuar.py): el resto no lo ve
    bajar_continue(program)
    # Un `if` que da un valor se baja
    # (if_expr.bajar) después de un primer pase, que da los errores y el tipo
    # de cada uno; el checker vuelve a correr sobre el programa bajado, que es
    # el que reciben el intérprete y el codegen. Sin ningún if así, un solo
    # pase, como siempre.
    hay_if = hay_if_expr(program)
    checker = Checker()
    checker._registrar_tipos = hay_if
    errores = checker.check_program(program)
    if hay_if and not errores:
        errores_if = bajar_if_expr(program)
        if errores_if:
            return [TypeError_(e.msg, e.line, e.col, e.archivo) for e in errores_if]
        errores = Checker().check_program(program)
    # El valor de un match se lee una vez por brazo en el código
    # bajado; si está movido, el error sería el mismo varias veces.
    vistos = set()
    unicos = []
    for e in errores:
        clave = (str(e), getattr(e, "line", None), getattr(e, "col", None))
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(e)
    return unicos
