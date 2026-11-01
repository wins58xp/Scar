"""Parser recursivo descendente para SCAR. Produce un AST de dicts/nodos simples."""

from lexer import tokenize, Token
from types_ import TypeAnn, FN_MARK, CHAN_MARK, VEC_MARK, MAP_MARK, T_I32


class ParseError(Exception):
    def __init__(self, msg, line=None, col=None):
        super().__init__(msg)
        self.line = line
        self.col = col


# ---- Nodos AST (clases simples, sin librerías externas) ----

class Node:
    # Ubicación de origen de este nodo en el source
    # .scar. `line`/`col` son 1-based, igual que Token (ver lexer.py), y
    # valen None si el nodo nunca pasó por `.at()` (nodos construidos a mano
    # en tests, por ejemplo). Atributos de clase como default para no tener
    # que tocar los ~30 `__init__` de las subclases de abajo -- `.at()` los
    # pisa por instancia después de construir el nodo.
    line = None
    col = None
    # Módulos: el archivo de donde viene el nodo, si no es el
    # programa principal (lo pone modulos.cargar; los errores lo muestran).
    archivo = None
    # El checker lo pone en True en una expresión i32 usada donde
    # se espera f64 (ver TypeChecker._compatible); el intérprete la convierte.
    promover_f64 = False
    # Lo mismo para un i32 usado donde se espera i64; el intérprete lo
    # marca como i64 (para que una cuenta posterior desborde en 64 bits).
    promover_i64 = False
    # El checker anota el tipo entero ("i32"/"i64") de un literal y de
    # cada cuenta entera (BinOp, '-' unario), y el valor de un `-N` plegado.
    tipo_int = None
    literal_plegado = None
    # Un uso de una variable que una vuelta anterior del loop pudo
    # mover (en una sola rama de un if): se comprueba en tiempo de ejecución
    # (verificar_movida); y un movimiento de esa variable, que lo anota
    # (registra_mov). Los pone el checker; ver TypeChecker._uso_en_vuelta.
    verificar_movida = False
    registra_mov = False
    # En un loop, las variables de afuera que su cuerpo mueve (una
    # lista de nodos Ident; ver TypeChecker._check_vuelta_siguiente).
    mueve_de_afuera = ()

    def at(self, tok):
        """Marca este nodo con la posición de `tok` (un Token, ver lexer.py).
        Se llama en el sitio de construcción, no en __init__, para no tener
        que agregar line/col como parámetro a cada constructor. Devuelve
        self para poder encadenar: `return FnDecl(...).at(start_tok)`."""
        self.line = tok.line
        self.col = tok.col
        return self

    def __repr__(self):
        fields = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
        return f"{type(self).__name__}({fields})"


class Program(Node):
    def __init__(self, items, usos=None):
        self.items = items
        # Módulos: los `use "ruta"` del principio del archivo, que
        # resuelve modulos.cargar (antes del checker). Un Program armado con
        # parse() suelto los trae sin resolver.
        self.usos = usos or []


class UseDecl(Node):
    """`use "gui"` / `use "comun/json"`: trae el módulo; sus nombres se usan
    con el prefijo `gui.` (la última parte de la ruta)."""
    def __init__(self, ruta, nombre): self.ruta = ruta; self.nombre = nombre

class StructDecl(Node):
    def __init__(self, name, fields, type_params=None, type_bounds=None):
        # fields: lista de (nombre, TypeAnn)
        # type_params: lista de str, ej. ["T"] para struct Foo<T> { ... }
        self.name = name; self.fields = fields
        self.type_params = type_params or []
        # Dict nombre -> nombre del bound, ej.
        # {"T": "Numeric"} para struct Foo<T: Numeric> { ... }. Vacío para
        # 'struct Foo<T>' sin bound. El checker lo usa para saber qué
        # operaciones admite T (ver _type_param_bound_ops).
        self.type_bounds = type_bounds or {}

class FnDecl(Node):
    def __init__(self, name, params, body, is_task=False, return_type=None, accepts=None, type_params=None, type_bounds=None):
        self.name = name; self.params = params; self.body = body
        self.is_task = is_task; self.return_type = return_type
        # Lista de str, ej. ["T"] para fn bar<T>(...).
        # Igual que StructDecl.type_params -- [] para toda
        # fn/task que no use la cláusula.
        self.type_params = type_params or []
        # Gemelo de StructDecl.type_bounds (ver ahí),
        # ej. {"T": "Numeric"} para 'fn sumar<T: Numeric>(...)'. Vacío por
        # defecto.
        self.type_bounds = type_bounds or {}
        # Lista de TypeAnn (siempre
        # Chan<T>, validado en type_checker._check_fn) que esta 'task'
        # declara aceptar por inyección en runtime -- ver 'accepts' en
        # lexer.py y parse_fn de más abajo. [] para toda 'fn'/'task' que
        # no use la cláusula (el 100% del código existente): opt-in,
        # ninguna garantía estática de hoy cambia si esto queda vacío.
        self.accepts = accepts or []

class Param(Node):
    def __init__(self, name, type_ann=None, consumes=False):
        self.name = name; self.type_ann = type_ann
        # `consumes` (FFI): True solo si el parámetro se declaró
        # como `own T` en una firma `extern fn` -- ver ExternTypeDecl y
        # parse_extern_fn. Para Param normal (fn/task) siempre False, no
        # se parsea 'own' ahí. Marca que esta llamada TOMA POSESIÓN del
        # handle FFI (lo mueve, ver _move_if_needed en type_checker.py) en
        # vez de solo pedirlo prestado por la duración de la llamada.
        self.consumes = consumes

class ExternFnDecl(Node):
    """Declaración FFI: `extern "C" fn nombre(params) -> T from "lib"`.
    Sin cuerpo -- nunca se parsea un Block para esto, es solo una firma.
    `abi` es el string literal después de 'extern' (hoy solo se acepta "C",
    validado en el type checker; el parser solo guarda el string tal cual
    llegó). `library` es opcional (`from "m"` -> -lm al
    linkear); None significa "ya linkeado por defecto" (ej. libc)."""
    def __init__(self, name, params, return_type=None, abi="C", library=None):
        self.name = name; self.params = params; self.return_type = return_type
        self.abi = abi; self.library = library

class ExternLibDecl(Node):
    """`extern lib "nombre" en_proceso`: las extern fn de esa
    librería corren dentro del proceso de SCAR, con la guardia de señales
    (un crash en C se vuelve panic), en vez de en el proceso worker aislado
    que se usa por defecto. Hace falta para una librería que
    recibe un callback o un struct por valor (el pipe del worker no los
    puede llevar), o para una que se llama miles de veces por segundo (una
    GUI: cada llamada por el pipe cuesta decenas de microsegundos). `modo`
    es hoy siempre "en_proceso"."""
    def __init__(self, library, modo="en_proceso"):
        self.library = library; self.modo = modo

class ExternTypeDecl(Node):
    """FFI, ownership en la frontera: `extern type Nombre`.

    Declara un tipo opaco respaldado por un `void*` de C -- un handle que
    viene de una librería C (un stream de compresión, un handle de driver,
    etc.), NUNCA un struct de SCAR. A diferencia de struct/Vec/Map, este
    tipo:
      - no se registra como dueño de ninguna Region,
      - nunca participa del _free()/_emit_owner_frees sintetizado,
      - se mueve como cualquier tipo no-Copy (TypeAnn.is_copy() ya da
        False para nombres no primitivos, sin cambios ahí), y
      - solo se mueve EXPLÍCITAMENTE al pasarlo a un parámetro `own T` de
        una `extern fn` (ver Param.consumes) -- pasarlo a un parámetro sin
        `own` es un préstamo por la duración de la llamada, la variable
        sigue viva después.
    Sin cuerpo, sin campos, sin biblioteca propia (la biblioteca se declara
    por cada `extern fn` que opera sobre este tipo, con `from "lib"`)."""
    def __init__(self, name):
        self.name = name

class EnumDecl(Node):
    """`enum Forma { Circulo(f64)  Rect(f64, f64)  Nada }`.
    `variants` es una lista de EnumVariant. No llega al checker ni a los
    backends: enum_match.bajar_enums lo reemplaza por un struct con tag y una
    fn constructora por variante."""
    def __init__(self, name, variants): self.name = name; self.variants = variants

class EnumVariant(Node):
    def __init__(self, name, types): self.name = name; self.types = types

class MatchExpr(Node):
    """`match x { Circulo(r) => ...  Nada => ...  _ => ... }`.
    `es_sentencia` es True cuando el match es una sentencia (sus brazos pueden
    ser bloques); si no, da un valor. enum_match.bajar_enums lo baja a una
    cadena de if/else; nunca llega al checker ni a los backends."""
    def __init__(self, scrutinee, arms, es_sentencia=False):
        self.scrutinee = scrutinee; self.arms = arms; self.es_sentencia = es_sentencia

class MatchArm(Node):
    """Un brazo: `pattern => body`. body es un Block o una expresión."""
    def __init__(self, pattern, body): self.pattern = pattern; self.body = body

class Patron(Node):
    """`_` (name='_', binds=None), `Nada` (binds=None) o `Rect(w, _)` (binds:
    lista de Ident; un '_' no liga nada)."""
    def __init__(self, name, binds): self.name = name; self.binds = binds

class Block(Node):
    def __init__(self, stmts): self.stmts = stmts

# Statements
class LetStmt(Node):
    def __init__(self, name, expr, mutable=False, declared_type=None):
        self.name = name; self.expr = expr; self.mutable = mutable
        self.declared_type = declared_type

class ReturnStmt(Node):
    def __init__(self, expr): self.expr = expr

class BreakStmt(Node):
    """`break`: sale del loop más interno (while, while let o for).
    El checker rechaza un break fuera de un loop."""
    def __init__(self): pass

class ContinueStmt(Node):
    """`continue`: salta a la vuelta siguiente del loop más interno. No llega
    al checker ni a los backends: continuar.bajar lo reescribe con if (ver
    ahí). Fuera de un loop, el checker lo rechaza."""
    def __init__(self): pass

class ExprStmt(Node):
    def __init__(self, expr): self.expr = expr

class IfStmt(Node):
    def __init__(self, cond, then_block, else_block): self.cond = cond; self.then_block = then_block; self.else_block = else_block

class WhileStmt(Node):
    def __init__(self, cond, body): self.cond = cond; self.body = body

class WhileLetStmt(Node):
    def __init__(self, pattern, expr, body): self.pattern = pattern; self.expr = expr; self.body = body

class ForStmt(Node):
    def __init__(self, var, start, end, body): self.var = var; self.start = start; self.end = end; self.body = body

class AssignStmt(Node):
    def __init__(self, target, expr): self.target = target; self.expr = expr

# Expressions
class NumLit(Node):
    def __init__(self, value): self.value = value

class StrLit(Node):
    def __init__(self, value): self.value = value

class BoolLit(Node):
    def __init__(self, value): self.value = value

class Ident(Node):
    def __init__(self, name): self.name = name

class BinOp(Node):
    def __init__(self, op, left, right): self.op = op; self.left = left; self.right = right

class UnaryOp(Node):
    def __init__(self, op, expr): self.op = op; self.expr = expr

class Call(Node):
    def __init__(self, callee, args): self.callee = callee; self.args = args

class MethodCall(Node):
    def __init__(self, obj, method, args): self.obj = obj; self.method = method; self.args = args

class FieldAccess(Node):
    def __init__(self, obj, field): self.obj = obj; self.field = field

class IndexExpr(Node):
    """s[i]: indexado por posición, hoy solo sobre str (indexado de
    caracteres). Fuera de rango es panic en runtime (intérprete/backend C),
    no un tipo Option/Result -- misma familia que un acceso a campo
    inexistente, no un caso "esperable" que el programa deba manejar."""
    def __init__(self, obj, index): self.obj = obj; self.index = index

class StructLit(Node):
    def __init__(self, name, fields): self.name = name; self.fields = fields

class ArrayLit(Node):
    """[a, b, c]: un Vec nuevo con esos elementos, en ese orden. Es azúcar: equivale a `vec_new()` + un
    `push` por elemento. El checker deja en `tipo_elem` el tipo de los
    elementos (el de la anotación si la hay, si no el del primero)."""
    def __init__(self, elems): self.elems = elems

class IfExpr(Node):
    """`if c { ... a } else { ... b }` en posición de expresión: da el valor de la última expresión de la rama
    que corre. El `else` es obligatorio; `else if` deja en else_block un
    Block con un solo ExprStmt(IfExpr). El checker deja en `tipo_if` el tipo
    del valor, y if_expr.bajar lo baja a una variable temporal + un IfStmt
    (como enum_match con el match): los backends nunca lo ven."""
    def __init__(self, cond, then_block, else_block):
        self.cond = cond; self.then_block = then_block; self.else_block = else_block

class SpawnExpr(Node):
    def __init__(self, call): self.call = call

class TryExpr(Node):
    def __init__(self, expr): self.expr = expr

class OkExpr(Node):
    def __init__(self, expr): self.expr = expr

class ErrExpr(Node):
    def __init__(self, expr): self.expr = expr

class SomeExpr(Node):
    def __init__(self, expr): self.expr = expr

class NoneExpr(Node):
    pass

class PrintExpr(Node):
    def __init__(self, args): self.args = args


# Un archivo que termina antes de cerrar algo (típico mientras se
# escribe) decía "expresión inesperada eof:None".
_FIN_ANTES_DE_TIEMPO = ("el archivo termina antes de tiempo, en línea {line}: falta "
                        "cerrar algo (una '}}', un ')') o terminar la última línea")


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0
        # Ver GRAMMAR.md §6.2: cuando es True, PrimaryExpr no intenta leer un
        # identificador en mayúscula seguido de '{' como literal de struct.
        # Se activa solo mientras se parsea la condición de if/while/for (donde
        # el '{' que sigue casi siempre es el del cuerpo del bloque, no el de
        # un struct), y se desactiva apenas se entra a paréntesis o argumentos
        # de una llamada, donde un struct literal vuelve a ser inequívoco.
        self.no_struct_literal = False
        self.modulos = set()  # nombres de los módulos traídos con `use`

    def parse_cond_expr(self):
        prev = self.no_struct_literal
        self.no_struct_literal = True
        try:
            return self.parse_expr()
        finally:
            self.no_struct_literal = prev

    def peek(self, offset=0):
        # Mirar más allá del final devuelve el eof (el último token).
        # `_corrimiento_adelante` mira dos tokens: con un archivo cortado
        # justo después de una expresión (`print(1)` y nada más, típico
        # mientras se escribe), peek(1) se pasaba de la lista y el parser
        # reventaba con un IndexError de Python en vez de un error de SCAR
        # (y el LSP se quedaba sin diagnóstico).
        i = self.pos + offset
        if i >= len(self.toks):
            return self.toks[-1]
        return self.toks[i]

    def advance(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def check(self, kind, value=None):
        t = self.peek()
        if t.kind != kind:
            return False
        if value is not None and t.value != value:
            return False
        return True

    def match(self, kind, value=None):
        if self.check(kind, value):
            return self.advance()
        return None

    def expect(self, kind, value=None):
        if self.check(kind, value):
            return self.advance()
        t = self.peek()
        if t.kind == "eof":
            raise ParseError(_FIN_ANTES_DE_TIEMPO.format(line=t.line), t.line, t.col)
        raise ParseError(
            f"esperaba {kind}:{value} pero encontré {t.kind}:{t.value!r} en línea {t.line}",
            t.line, t.col,
        )

    # ---- Programa ----
    def parse_program(self):
        start_tok = self.peek()
        usos = []
        while self.check("kw", "use"):
            usos.append(self.parse_use())
        items = []
        while not self.check("eof"):
            if self.check("kw", "use"):
                t = self.peek()
                raise ParseError(
                    f"'use' va al principio del archivo, antes de cualquier declaración, "
                    f"en línea {t.line}", t.line, t.col)
            items.append(self.parse_item())
        return Program(items, usos).at(start_tok)

    def parse_use(self):
        """Módulos: `use "gui"`. El nombre del módulo es la última parte de la
        ruta, y tiene que poder escribirse como nombre (`gui.boton`)."""
        start_tok = self.expect("kw", "use")
        t = self.peek()
        if t.kind != "str":
            raise ParseError(
                f"después de 'use' va la ruta del módulo entre comillas (use \"gui\"), "
                f"en línea {t.line}", t.line, t.col)
        self.advance()
        ruta = t.value
        nombre = ruta.rstrip("/").split("/")[-1]
        if nombre.endswith(".scar"):
            raise ParseError(
                f"la ruta de 'use' va sin '.scar' (use \"{ruta[:-5]}\"), en línea {t.line}",
                t.line, t.col)
        if not nombre or not (nombre[0].isalpha() or nombre[0] == "_") \
                or not all(c.isalnum() or c == "_" for c in nombre):
            raise ParseError(
                f"el módulo '{ruta}' no sirve como nombre: la última parte de la ruta se "
                f"escribe delante de lo que trae (gui.boton), así que solo puede tener "
                f"letras, dígitos y '_', en línea {t.line}", t.line, t.col)
        if nombre in self.modulos:
            raise ParseError(
                f"dos 'use' traen un módulo llamado '{nombre}', en línea {t.line}", t.line, t.col)
        self.modulos.add(nombre)
        return UseDecl(ruta, nombre).at(start_tok)

    def _nombre_de_modulo(self, primero, tok):
        """`gui.boton`: si `primero` es un módulo traído con `use` y sigue
        `.nombre`, consume el resto y devuelve "gui.boton". Lo privado (con `_`
        adelante) no se puede usar desde afuera."""
        if primero not in self.modulos or not self.check("sym", "."):
            return None
        self.advance()
        t = self.peek()
        if t.kind != "id":
            raise ParseError(
                f"después de '{primero}.' va un nombre del módulo, en línea {t.line}", t.line, t.col)
        self.advance()
        if t.value.startswith("_"):
            raise ParseError(
                f"'{primero}.{t.value}' es privado del módulo '{primero}' (empieza con '_'), "
                f"en línea {t.line}", t.line, t.col)
        return f"{primero}.{t.value}"

    def parse_item(self):
        if self.check("kw", "struct"):
            return self.parse_struct()
        if self.check("kw", "enum"):
            return self.parse_enum()
        if self.check("kw", "fn"):
            return self.parse_fn(is_task=False)
        if self.check("kw", "task"):
            return self.parse_fn(is_task=True)
        if self.check("kw", "export"):
            # `export fn nombre(...)`: se puede llamar desde otro
            # lenguaje cuando el programa se compila como librería
            t = self.advance()
            if not self.check("kw", "fn"):
                n = self.peek()
                raise ParseError(
                    f"después de 'export' va una fn (`export fn nombre(...)`), no "
                    f"{n.kind}:{n.value!r}, en línea {n.line}", n.line, n.col)
            decl = self.parse_fn(is_task=False)
            decl.exportada = True
            return decl
        if self.check("kw", "extern"):
            # 'extern type Nombre' vs 'extern "C" fn ...': se distinguen mirando el token que sigue a 'extern'
            # sin consumirlo -- 'type' es palabra clave, el ABI de una
            # extern fn siempre es un string literal, nunca colisionan.
            nxt = self.peek(1)
            if nxt.kind == "kw" and nxt.value == "type":
                return self.parse_extern_type()
            if nxt.kind == "id" and nxt.value == "lib":
                return self.parse_extern_lib()
            return self.parse_extern_fn()
        t = self.peek()
        if (t.kind == "id" and t.value in ("usar", "importar", "import", "incluir", "include", "require")
                and self.peek(1).kind == "str"):
            raise ParseError(
                f"para traer un módulo, en SCAR se escribe use \"{self.peek(1).value}\" "
                f"(no '{t.value}'), en línea {t.line}", t.line, t.col)
        raise ParseError(
            f"declaración inesperada {t.kind}:{t.value!r} en línea {t.line}", t.line, t.col
        )

    def parse_struct(self):
        start_tok = self.peek()
        self.expect("kw", "struct")
        name = self.expect("id").value
        type_params = []
        type_bounds = {}
        if self.match("sym", "<"):
            self._parse_type_param(type_params, type_bounds)
            while self.match("sym", ","):
                self._parse_type_param(type_params, type_bounds)
            self.expect("sym", ">")
        self.expect("sym", "{")
        fields = []
        while not self.check("sym", "}"):
            fname = self.expect("id").value
            self.expect("sym", ":")
            ftype = self.parse_type()
            fields.append((fname, ftype))
        self.expect("sym", "}")
        return StructDecl(name, fields, type_params, type_bounds).at(start_tok)

    def parse_enum(self):
        """`enum Nombre { A(T1, T2)  B  C(T3) }`. Las variantes van
        separadas por un salto de línea o una coma."""
        start_tok = self.peek()
        self.expect("kw", "enum")
        name = self.expect("id").value
        if self.check("sym", "<"):
            t = self.peek()
            raise ParseError(
                f"un enum genérico (enum {name}<T>) todavía no se puede declarar, en línea {t.line}",
                t.line, t.col)
        self.expect("sym", "{")
        variants = []
        while not self.check("sym", "}"):
            vtok = self.expect("id")
            types = []
            if self.match("sym", "("):
                if self.check("sym", ")"):
                    t = self.peek()
                    raise ParseError(
                        f"la variante '{vtok.value}' tiene paréntesis vacíos: una variante "
                        f"sin datos se escribe sin paréntesis, en línea {t.line}", t.line, t.col)
                types.append(self.parse_type())
                while self.match("sym", ","):
                    types.append(self.parse_type())
                self.expect("sym", ")")
            variants.append(EnumVariant(vtok.value, types).at(vtok))
            self.match("sym", ",")
        self.expect("sym", "}")
        return EnumDecl(name, variants).at(start_tok)

    def parse_match(self, es_sentencia):
        """`match expr { Patrón => cuerpo ... }`. El cuerpo de un brazo
        es un bloque o una expresión; los brazos van separados por un salto
        de línea o una coma."""
        start_tok = self.expect("kw", "match")
        scrutinee = self.parse_cond_expr()
        self.expect("sym", "{")
        arms = []
        while not self.check("sym", "}"):
            pattern = self.parse_patron()
            self.expect("sym", "=>")
            if self.check("sym", "{"):
                body = self.parse_block()
            else:
                body = self.parse_expr()
            arms.append(MatchArm(pattern, body).at(pattern))
            self.match("sym", ",")
        self.expect("sym", "}")
        return MatchExpr(scrutinee, arms, es_sentencia).at(start_tok)

    def parse_patron(self):
        t = self.peek()
        # Some/None/Ok/Err son palabras clave: se leen como nombres para que
        # el error ("todavía no se puede hacer match sobre un Option") lo dé
        # enum_match, con el resto del programa ya leído.
        nombre = t.value
        if t.kind == "id" or (t.kind == "kw" and t.value in ("Some", "None", "Ok", "Err")):
            self.advance()
            if t.kind == "id":
                nombre = self._nombre_de_modulo(t.value, t) or t.value  # gui.Rojo
        elif t.kind == "eof":
            raise ParseError(_FIN_ANTES_DE_TIEMPO.format(line=t.line), t.line, t.col)
        else:
            raise ParseError(
                f"se esperaba un patrón (una variante, como Rect(w, h) o Nada, o '_') "
                f"y se encontró {t.kind}:{t.value!r} en línea {t.line}", t.line, t.col)
        binds = None
        if self.match("sym", "("):
            binds = []
            while True:
                b = self.expect("id")
                binds.append(Ident(b.value).at(b))
                if not self.match("sym", ","):
                    break
            self.expect("sym", ")")
        return Patron(nombre, binds).at(t)

    def _parse_type_param(self, type_params, type_bounds):
        """Un parámetro de tipo dentro de '<...>',
        opcionalmente con un bound ('T' o 'T: Numeric'). Compartido por
        parse_struct y parse_fn -- mismo mecanismo, un solo lugar que lo
        parsea, para que 5b (cuando el checker empiece a usar el bound)
        no tenga que sincronizar dos copias. Solo llena `type_params`
        (lista de nombres, forma que ya consume el resto del compilador)
        y `type_bounds` (dict nombre -> nombre del bound, ausente si no
        se escribió ':'); el checker de hoy sigue sin leer `type_bounds`."""
        pname = self.expect("id").value
        type_params.append(pname)
        if self.match("sym", ":"):
            bound = self.expect("id").value
            type_bounds[pname] = bound

    def parse_fn(self, is_task):
        start_tok = self.peek()
        self.advance()  # 'fn' o 'task'
        name = self.expect("id").value
        # '<T>' opcional después del nombre, mismo
        # mecanismo ya usado para 'struct Foo<T>' -- reusado,
        # no reinventado.
        type_params = []
        type_bounds = {}
        if self.match("sym", "<"):
            self._parse_type_param(type_params, type_bounds)
            while self.match("sym", ","):
                self._parse_type_param(type_params, type_bounds)
            self.expect("sym", ">")
        self.expect("sym", "(")
        params = []
        while not self.check("sym", ")"):
            ptok = self.peek()
            pname = self.expect("id").value
            ptype = None
            if self.match("sym", ":"):
                ptype = self.parse_type()
            params.append(Param(pname, ptype).at(ptok))
            if not self.check("sym", ")"):
                self.expect("sym", ",")
        self.expect("sym", ")")
        # 'accepts Chan<T>, Chan<U>' es opcional y, si aparece, va
        # DESPUÉS de los parámetros y ANTES de '->' -- mismo lugar donde
        # una firma humana leería "qué recibe" antes de "qué devuelve".
        # Se parsea para 'fn' y 'task' por igual (gramática no distingue),
        # el type_checker es quien rechaza 'accepts' sobre una 'fn' (no
        # tiene sentido: solo una 'task' corriendo puede recibir una
        # inyección en runtime).
        accepts = []
        if self.match("kw", "accepts"):
            accepts.append(self.parse_type())
            while self.match("sym", ","):
                accepts.append(self.parse_type())
        return_type = None
        if self.match("sym", "->"):
            return_type = self.parse_type()
        body = self.parse_block()
        return FnDecl(
            name, params, body, is_task=is_task, return_type=return_type, accepts=accepts,
            type_params=type_params, type_bounds=type_bounds,
        ).at(start_tok)

    def parse_extern_fn(self):
        # extern "C" fn nombre(params) -> T from "lib"
        # Sin cuerpo -- la declaración se autodelimita por su propia gramática
        # fija (a diferencia de fn/task, que se delimitan por las llaves del
        # bloque), así que no hace falta terminador.
        start_tok = self.peek()
        self.expect("kw", "extern")
        abi_tok = self.expect("str")
        abi = abi_tok.value
        self.expect("kw", "fn")
        name = self.expect("id").value
        self.expect("sym", "(")
        params = []
        while not self.check("sym", ")"):
            ptok = self.peek()
            pname = self.expect("id").value
            self.expect("sym", ":")
            # FFI: 'own T' antes del tipo marca que esta función
            # TOMA POSESIÓN del handle (lo mueve, ver Param.consumes /
            # _move_if_needed en type_checker.py) -- sin 'own', el
            # parámetro es un préstamo por la duración de la llamada. El
            # type checker valida que 'own' solo aparezca sobre un tipo
            # declarado con 'extern type' (no tiene sentido sobre i32/str).
            consumes = bool(self.match("kw", "own"))
            ptype = self.parse_type()
            params.append(Param(pname, ptype, consumes=consumes).at(ptok))
            if not self.check("sym", ")"):
                self.expect("sym", ",")
        self.expect("sym", ")")
        return_type = None
        if self.match("sym", "->"):
            return_type = self.parse_type()
        library = None
        if self.match("kw", "from"):
            library = self.expect("str").value
        return ExternFnDecl(name, params, return_type, abi=abi, library=library).at(start_tok)

    def parse_extern_lib(self):
        # extern lib "nombre" en_proceso -- ver ExternLibDecl.
        start_tok = self.peek()
        self.expect("kw", "extern")
        self.expect("id", "lib")
        library = self.expect("str").value
        modo_tok = self.peek()
        if not (modo_tok.kind == "id" and modo_tok.value == "en_proceso"):
            raise ParseError(
                f"después de 'extern lib \"{library}\"' se esperaba 'en_proceso', "
                f"se encontró {modo_tok.kind}:{modo_tok.value!r} en línea {modo_tok.line}",
                modo_tok.line, modo_tok.col,
            )
        self.advance()
        return ExternLibDecl(library).at(start_tok)

    def parse_extern_type(self):
        # extern type Nombre -- ver ExternTypeDecl para la semántica completa.
        start_tok = self.peek()
        self.expect("kw", "extern")
        self.expect("kw", "type")
        name = self.expect("id").value
        return ExternTypeDecl(name).at(start_tok)

    def parse_type(self) -> TypeAnn:
        # Valor función sin captura: 'fn(T1, T2) -> U'
        # en posición de tipo. Se distingue del resto (nombre + '<args>' de
        # abajo) por arrancar con la keyword 'fn' -- no colisiona con 'fn'
        # en posición de declaración (parse_item la consume antes de llegar
        # acá) ni con ningún nombre de tipo existente ('fn' no es un 'id',
        # nunca puede ser el nombre de un struct/genérico de usuario). El
        # tipo de retorno va SIEMPRE, al final de .args, junto a los tipos
        # de parámetro -- ver el comentario de FN_MARK en types_.py.
        if self.check("kw", "fn"):
            self.advance()
            self.expect("sym", "(")
            param_types = []
            if not self.check("sym", ")"):
                param_types.append(self.parse_type())
                while self.match("sym", ","):
                    param_types.append(self.parse_type())
            self.expect("sym", ")")
            self.expect("sym", "->")
            ret_type = self.parse_type()
            return TypeAnn(FN_MARK, param_types + [ret_type])
        # Tipos simples y genéricos tipo Result<i32>, Chan<i32>.
        # El nombre puede venir como 'id' (i32, str, Point) o como palabra
        # reservada (Result, Chan) que en SCAR también actúa como constructor de tipo.
        tok = self.advance()
        name = tok.value
        if tok.kind == "id":
            name = self._nombre_de_modulo(name, tok) or name  # módulos: gui.Ventana
        args = []
        if self.match("sym", "<"):
            args.append(self.parse_type())
            while self.match("sym", ","):
                args.append(self.parse_type())
            self.expect("sym", ">")
        return TypeAnn(name, args)

    def parse_block(self):
        start_tok = self.peek()
        self.expect("sym", "{")
        stmts = []
        while not self.check("sym", "}"):
            stmts.append(self.parse_stmt())
        self.expect("sym", "}")
        return Block(stmts).at(start_tok)

    # ---- Statements ----
    def parse_stmt(self):
        if self.check("kw", "let"):
            return self.parse_let()
        if self.check("kw", "return"):
            start_tok = self.advance()
            expr = None
            if not self.check("sym", "}"):
                expr = self.parse_expr()
            return ReturnStmt(expr).at(start_tok)
        if self.check("kw", "break"):
            return BreakStmt().at(self.advance())
        if self.check("kw", "continue"):
            return ContinueStmt().at(self.advance())
        if self.check("kw", "if"):
            return self.parse_if()
        if self.check("kw", "while"):
            return self.parse_while()
        if self.check("kw", "for"):
            return self.parse_for()
        if self.check("kw", "match"):
            # Un match al principio de una sentencia es una sentencia
            # (sus brazos pueden ser bloques), y termina en su '}': lo que sigue
            # en la línea de abajo no se pega como `match {...} - 1`.
            start_tok = self.peek()
            return ExprStmt(self.parse_match(es_sentencia=True)).at(start_tok)
        # asignación o expr-statement
        start_tok = self.peek()
        expr = self.parse_expr()
        if self.check("sym", "="):
            self.advance()
            if not self._is_place(expr):
                t = self.peek(-1)
                raise ParseError(
                    "el lado izquierdo de '=' debe ser una variable o un "
                    f"acceso a campo (ej. 'x' o 'x.campo'), no una llamada u "
                    f"otra expresión, en línea {t.line}",
                    t.line, t.col,
                )
            value = self.parse_expr()
            return AssignStmt(expr, value).at(start_tok)
        return ExprStmt(expr).at(start_tok)

    @staticmethod
    def _is_place(expr):
        """Ver GRAMMAR.md §5.1: solo Ident y cadenas de FieldAccess sobre un
        Ident son targets válidos de asignación. Antes esto era 'cualquier
        Expr' a nivel de gramática y solo fallaba en runtime, con un error
        genérico; ahora se rechaza en parse-time con un mensaje claro."""
        if isinstance(expr, Ident):
            return True
        if isinstance(expr, FieldAccess):
            return Parser._is_place(expr.obj)
        return False

    def parse_let(self):
        start_tok = self.peek()
        self.expect("kw", "let")
        mutable = bool(self.match("kw", "mut"))
        # soporte simple para `while let Some(v) = expr` se maneja aparte
        name = self.expect("id").value
        # anotación de tipo opcional (`let ch: Chan<str> = ...`) -- hoy el
        # único uso real es desambiguar el T de chan_new() (ver type_checker.py,
        # que no puede inferirlo del sitio de la llamada porque no toma
        # argumentos), pero queda disponible para cualquier `let`.
        declared_type = None
        if self.match("sym", ":"):
            declared_type = self.parse_type()
        self.expect("sym", "=")
        expr = self.parse_expr()
        return LetStmt(name, expr, mutable, declared_type).at(start_tok)

    def parse_if(self):
        start_tok = self.peek()
        self.expect("kw", "if")
        cond = self.parse_cond_expr()
        then_block = self.parse_block()
        else_block = None
        if self.match("kw", "else"):
            if self.check("kw", "if"):
                else_if_tok = self.peek()
                else_block = Block([self.parse_if()]).at(else_if_tok)
            else:
                else_block = self.parse_block()
        return IfStmt(cond, then_block, else_block).at(start_tok)

    def parse_if_expr(self):
        """`if` en posición de expresión (ver IfExpr). Adentro de las ramas un
        struct literal nunca es ambiguo, aunque el if venga de una condición."""
        start_tok = self.peek()
        self.expect("kw", "if")
        cond = self.parse_cond_expr()
        prev = self.no_struct_literal
        self.no_struct_literal = False
        try:
            then_block = self.parse_block()
            if not self.check("kw", "else"):
                t = self.peek()
                raise ParseError(
                    f"un if que da un valor necesita su 'else' (si no, ¿qué vale cuando "
                    f"la condición es falsa?), en línea {t.line}", t.line, t.col)
            self.advance()
            if self.check("kw", "if"):
                else_tok = self.peek()
                interno = self.parse_if_expr()
                else_block = Block([ExprStmt(interno).at(else_tok)]).at(else_tok)
            else:
                else_block = self.parse_block()
        finally:
            self.no_struct_literal = prev
        for blk in (then_block, else_block):
            # `if c { if d { 1 } else { 2 } } else { 3 }`: el if del final de una
            # rama empieza una línea, así que salió como sentencia; es el valor.
            if blk.stmts and isinstance(blk.stmts[-1], IfStmt) and blk.stmts[-1].else_block is not None:
                blk.stmts[-1] = ExprStmt(_if_como_expr(blk.stmts[-1])).at(blk.stmts[-1])
        return IfExpr(cond, then_block, else_block).at(start_tok)

    def parse_while(self):
        start_tok = self.peek()
        self.expect("kw", "while")
        if self.match("kw", "let"):
            self.expect("kw", "Some")
            self.expect("sym", "(")
            pattern = self.expect("id").value
            self.expect("sym", ")")
            self.expect("sym", "=")
            expr = self.parse_cond_expr()
            body = self.parse_block()
            return WhileLetStmt(pattern, expr, body).at(start_tok)
        cond = self.parse_cond_expr()
        body = self.parse_block()
        return WhileStmt(cond, body).at(start_tok)

    def parse_for(self):
        start_tok = self.peek()
        self.expect("kw", "for")
        var = self.expect("id").value
        self.expect("kw", "in")
        start = self.parse_cond_expr()
        if not self.check("sym", ".."):
            t = self.peek()
            if t.kind != "eof":
                raise ParseError(
                    f"'for' recorre un rango de enteros, como 'for i in 0..n' (línea {t.line}): "
                    "no recorre una lista ni otro valor. Para una lista, recorre sus índices "
                    "con 'for i in 0..v.len()' y lee cada uno con 'v.get(i)', o sácalos con "
                    "'while let Some(x) = v.pop()'",
                    t.line, t.col)
        self.expect("sym", "..")
        end = self.parse_cond_expr()
        body = self.parse_block()
        return ForStmt(var, start, end, body).at(start_tok)

    # ---- Expressions (precedencia ascendente) ----
    def parse_expr(self):
        return self.parse_try()

    def parse_try(self):
        start_tok = self.peek()
        expr = self.parse_or()
        while self.match("sym", "?"):
            expr = TryExpr(expr).at(start_tok)
        return expr

    def parse_or(self):
        start_tok = self.peek()
        left = self.parse_and()
        while self.check("kw", "or"):
            self.advance()
            right = self.parse_and()
            left = BinOp("or", left, right).at(start_tok)
        return left

    def parse_and(self):
        start_tok = self.peek()
        left = self.parse_equality()
        while self.check("kw", "and"):
            self.advance()
            right = self.parse_equality()
            left = BinOp("and", left, right).at(start_tok)
        return left

    def parse_equality(self):
        start_tok = self.peek()
        left = self.parse_comparison()
        while self.check("sym", "==") or self.check("sym", "!="):
            op = self.advance().value
            right = self.parse_comparison()
            left = BinOp(op, left, right).at(start_tok)
        return left

    def parse_comparison(self):
        start_tok = self.peek()
        left = self.parse_bitor()
        while self.peek().kind == "sym" and self.peek().value in ("<", ">", "<=", ">="):
            op = self.advance().value
            right = self.parse_bitor()
            left = BinOp(op, left, right).at(start_tok)
        return left

    # ---- Operadores de bits ----
    # Precedencia de Rust, no la de C: los de bits ligan más fuerte que las
    # comparaciones, así `a & b == c` es `(a & b) == c` (en C sería
    # `a & (b == c)`, una trampa clásica). De menor a mayor: | ^ & << >>.
    def _parse_binario_izq(self, ops, siguiente):
        start_tok = self.peek()
        left = siguiente()
        while self.peek().kind == "sym" and self.peek().value in ops:
            op = self.advance().value
            right = siguiente()
            left = BinOp(op, left, right).at(start_tok)
        return left

    def parse_bitor(self):
        return self._parse_binario_izq(("|",), self.parse_bitxor)

    def parse_bitxor(self):
        return self._parse_binario_izq(("^",), self.parse_bitand)

    def parse_bitand(self):
        return self._parse_binario_izq(("&",), self.parse_shift)

    def _corrimiento_adelante(self):
        """'<<' o '>>' si los dos tokens siguientes son ese par de símbolos
        PEGADOS (misma línea, columnas consecutivas); None si no. Separados
        (`a > > b`) no son un corrimiento."""
        a, b = self.peek(), self.peek(1)
        if (a.kind == b.kind == "sym" and a.value == b.value and a.value in ("<", ">")
                and a.line == b.line and a.col is not None and b.col == a.col + 1):
            return a.value * 2
        return None

    def parse_shift(self):
        start_tok = self.peek()
        left = self.parse_additive()
        while True:
            op = self._corrimiento_adelante()
            if op is None:
                return left
            self.advance()
            self.advance()
            right = self.parse_additive()
            left = BinOp(op, left, right).at(start_tok)

    def parse_additive(self):
        start_tok = self.peek()
        left = self.parse_multiplicative()
        while self.peek().kind == "sym" and self.peek().value in ("+", "-"):
            op = self.advance().value
            right = self.parse_multiplicative()
            left = BinOp(op, left, right).at(start_tok)
        return left

    def parse_multiplicative(self):
        start_tok = self.peek()
        left = self.parse_unary()
        while self.peek().kind == "sym" and self.peek().value in ("*", "/", "%"):
            op = self.advance().value
            right = self.parse_unary()
            left = BinOp(op, left, right).at(start_tok)
        return left

    def parse_unary(self):
        if self.check("sym", "-"):
            start_tok = self.advance()
            return UnaryOp("-", self.parse_unary()).at(start_tok)
        if self.check("kw", "not"):
            start_tok = self.advance()
            return UnaryOp("not", self.parse_unary()).at(start_tok)
        return self.parse_postfix()

    def parse_postfix(self):
        start_tok = self.peek()
        expr = self.parse_primary()
        while True:
            if self.check("sym", "."):
                self.advance()
                name = self.expect("id").value
                if self.check("sym", "("):
                    args = self.parse_args()
                    expr = MethodCall(expr, name, args).at(start_tok)
                else:
                    expr = FieldAccess(expr, name).at(start_tok)
            elif self.check("sym", "("):
                args = self.parse_args()
                expr = Call(expr, args).at(start_tok)
            elif self.check("sym", "["):
                self.advance()
                # Igual que "(...)": dentro de "[...]" un struct literal nunca
                # es ambiguo con un bloque, aunque la restricción venga de una
                # condición (`if "xy"[Caja { v: 1 }.v] == "y" {`). Antes daba
                # "esperaba ] pero encontré {" (lo encontró el fuzzer).
                prev = self.no_struct_literal
                self.no_struct_literal = False
                try:
                    idx = self.parse_expr()
                finally:
                    self.no_struct_literal = prev
                self.expect("sym", "]")
                expr = IndexExpr(expr, idx).at(start_tok)
            else:
                break
        return expr

    def parse_parenthesized_expr(self):
        # Igual que en parse_primary: dentro de "(" ... ")" un struct literal
        # nunca es ambiguo, aunque la restricción venga heredada de una
        # condición (ver GRAMMAR.md §6.2).
        self.expect("sym", "(")
        prev = self.no_struct_literal
        self.no_struct_literal = False
        try:
            e = self.parse_expr()
        finally:
            self.no_struct_literal = prev
        self.expect("sym", ")")
        return e

    def parse_args(self):
        self.expect("sym", "(")
        # Dentro de "(...)" un struct literal nunca es ambiguo con un bloque,
        # así que se levanta la restricción aunque venga heredada de una
        # condición de if/while/for (ver GRAMMAR.md §6.2).
        prev = self.no_struct_literal
        self.no_struct_literal = False
        try:
            args = []
            while not self.check("sym", ")"):
                args.append(self.parse_expr())
                if not self.check("sym", ")"):
                    self.expect("sym", ",")
            self.expect("sym", ")")
            return args
        finally:
            self.no_struct_literal = prev

    def parse_primary(self):
        t = self.peek()

        if t.kind == "num":
            self.advance()
            return NumLit(t.value).at(t)
        if t.kind == "str":
            self.advance()
            return StrLit(t.value).at(t)
        if self.check("kw", "true"):
            self.advance()
            return BoolLit(True).at(t)
        if self.check("kw", "false"):
            self.advance()
            return BoolLit(False).at(t)
        if self.check("kw", "spawn"):
            self.advance()
            call = self.parse_postfix()
            return SpawnExpr(call).at(t)
        if self.check("kw", "Ok"):
            self.advance()
            return OkExpr(self.parse_parenthesized_expr()).at(t)
        if self.check("kw", "Err"):
            self.advance()
            return ErrExpr(self.parse_parenthesized_expr()).at(t)
        if self.check("kw", "Some"):
            self.advance()
            return SomeExpr(self.parse_parenthesized_expr()).at(t)
        if self.check("kw", "None"):
            self.advance()
            return NoneExpr().at(t)
        if self.check("kw", "print"):
            self.advance()
            args = self.parse_args()
            return PrintExpr(args).at(t)
        if self.check("kw", "match"):
            return self.parse_match(es_sentencia=False)
        if self.check("sym", "("):
            return self.parse_parenthesized_expr()
        if self.check("kw", "if"):
            return self.parse_if_expr()
        if self.check("sym", "["):
            # [a, b, c]: dentro de los corchetes un struct literal nunca es
            # ambiguo con un bloque (como en parse_args).
            self.advance()
            prev = self.no_struct_literal
            self.no_struct_literal = False
            try:
                elems = []
                while not self.check("sym", "]"):
                    elems.append(self.parse_expr())
                    if not self.check("sym", "]"):
                        self.expect("sym", ",")
                self.expect("sym", "]")
            finally:
                self.no_struct_literal = prev
            return ArrayLit(elems).at(t)
        if t.kind == "id":
            # posible struct literal: Ident { campo: expr, ... }
            name = self.advance().value
            calificado = self._nombre_de_modulo(name, t)  # módulos: gui.boton, gui.Ventana { .. }
            if calificado is None and name in self.modulos:
                raise ParseError(
                    f"'{name}' es un módulo: lo que trae se usa con su nombre adelante "
                    f"({name}.algo), en línea {t.line}", t.line, t.col)
            corto = name
            if calificado is not None:
                name, corto = calificado, calificado.split(".", 1)[1]
            # Un nombre privado de módulo (`_Monticulo`) también es un tipo: cuenta la primera
            # letra después de los `_` (antes `struct _X` se podía declarar pero no construir)
            if self.check("sym", "{") and corto.lstrip("_")[:1].isupper() and not self.no_struct_literal:
                self.advance()
                fields = {}
                while not self.check("sym", "}"):
                    fname = self.expect("id").value
                    self.expect("sym", ":")
                    fields[fname] = self.parse_expr()
                    if not self.check("sym", "}"):
                        self.expect("sym", ",")
                self.expect("sym", "}")
                return StructLit(name, fields).at(t)
            return Ident(name).at(t)

        if t.kind == "eof":
            raise ParseError(_FIN_ANTES_DE_TIEMPO.format(line=t.line), t.line, t.col)
        raise ParseError(
            f"expresión inesperada {t.kind}:{t.value!r} en línea {t.line}", t.line, t.col
        )


def _if_como_expr(st):
    """Un IfStmt con else (y su cadena de else if) como IfExpr."""
    else_b = st.else_block
    if (len(else_b.stmts) == 1 and isinstance(else_b.stmts[0], IfStmt)
            and else_b.stmts[0].else_block is not None):
        interno = else_b.stmts[0]
        else_b = Block([ExprStmt(_if_como_expr(interno)).at(interno)]).at(else_b)
    for blk in (st.then_block, else_b):
        if blk.stmts and isinstance(blk.stmts[-1], IfStmt) and blk.stmts[-1].else_block is not None:
            blk.stmts[-1] = ExprStmt(_if_como_expr(blk.stmts[-1])).at(blk.stmts[-1])
    return IfExpr(st.cond, st.then_block, else_b).at(st)


# Los hijos de un nodo, en UN solo lugar. Los análisis
# que recorren el AST de forma genérica (sombreado, movimientos, frescura,
# qué builtins usa el programa) antes miraban solo listas y atributos de
# objeto, y `StructLit.fields` es un dict: nada de lo que va adentro de un
# struct literal (`D { a: d.a + 5 }`, `A { o: arg(0) }`) se veía. Todo
# recorrido genérico usa esta función; si un nodo nuevo guarda sus hijos de
# otra forma, se agrega acá y lo ven todos.
_ATRIBUTOS_NO_HIJOS = ("line", "col", "promover_f64", "promover_i64", "tipo_int",
                       "literal_plegado", "tipo_origen", "tipo_var", "archivo", "tipo_lugar",
                       "devuelve_str", "tipo_elem", "tipo_if", "tipo_visto", "tipo_replace")


def hijos(node):
    """Los valores que cuelgan de `node`: los elementos de una lista o tupla,
    los valores de un dict (los campos de un struct literal) o los atributos
    de un nodo (salvo su posición en el fuente). [] para una hoja (str,
    número, None)."""
    if isinstance(node, (list, tuple)):
        return list(node)
    if isinstance(node, dict):
        return list(node.values())
    attrs = getattr(node, "__dict__", None)
    if attrs is None:
        return []
    return [v for k, v in attrs.items() if k not in _ATRIBUTOS_NO_HIJOS]


def es_panic(stmt):
    """`panic("...")` como statement."""
    return (isinstance(stmt, ExprStmt) and isinstance(stmt.expr, Call)
            and isinstance(stmt.expr.callee, Ident) and stmt.expr.callee.name == "panic")


def block_always_returns(block):
    """True si TODA ejecución que entra a `block` sale por
    un `return`, sin llegar nunca a su llave de cierre. Análisis sintáctico:
      - un `return` en este nivel (lo que siga es código muerto);
      - un if/else completo cuyas dos ramas, recursivamente, siempre retornan;
      - un `panic("...")` como statement: termina la tarea, nunca sigue
        (`panic` es un nombre reservado: no puede ser una fn del usuario);
      - un `while true` (la condición es el literal true) sin un `break`
        propio: de ese loop solo se sale con un `return` (o un
        panic de runtime).
    Un `break` en este nivel sale del loop que lo contiene sin retornar: lo
    que siga es código muerto, y el bloque NO siempre retorna. Un `if` sin
    `else`, un `while` con otra condición, un `while let` o un `for` pueden
    terminar sin haber retornado. Única definición: la usan el checker (una
    fn con retorno que puede llegar al final es un error) y el codegen."""
    return _bloque_sale(block, cuenta_break=False)


def block_never_falls_through(block):
    """True si ninguna ejecución que entra a `block` llega a su llave
    de cierre: sale siempre por un `return`, un panic o un `break` (del loop
    que contiene al bloque). Es la pregunta que importa para el código que
    sigue dentro del mismo loop: una rama que sale con `break` no llega ni al
    resto del cuerpo ni a la vuelta siguiente (pero sí a lo que sigue al
    loop, ver el checker)."""
    return _bloque_sale(block, cuenta_break=True)


def _bloque_sale(block, cuenta_break):
    for stmt in block.stmts:
        if isinstance(stmt, ReturnStmt) or es_panic(stmt):
            return True
        if isinstance(stmt, BreakStmt):
            return cuenta_break
        if isinstance(stmt, IfStmt) and stmt.else_block is not None:
            if _bloque_sale(stmt.then_block, cuenta_break) and _bloque_sale(stmt.else_block, cuenta_break):
                return True
        if (isinstance(stmt, WhileStmt) and isinstance(stmt.cond, BoolLit)
                and stmt.cond.value is True and not tiene_break_propio(stmt.body)):
            return True
    return False


def tiene_break_propio(block):
    """True si `block` (el cuerpo de un loop) tiene un `break` que
    sale de ESE loop: directo o dentro de un if, no dentro de otro loop
    anidado (ese break es del loop de adentro)."""
    for stmt in block.stmts:
        if isinstance(stmt, BreakStmt):
            return True
        if isinstance(stmt, IfStmt):
            if tiene_break_propio(stmt.then_block):
                return True
            if stmt.else_block is not None and tiene_break_propio(stmt.else_block):
                return True
    return False


def parse(src: str) -> Program:
    """Un archivo suelto. Si trae `use`, los módulos los resuelve
    modulos.cargar (que es lo que usan cli.py, main.py y el codegen)."""
    tokens = tokenize(src)
    return Parser(tokens).parse_program()


def marca_new_generico(expr):
    """Si `expr` es chan_new() o vec_new() (sin argumentos o con la capacidad) o
    map_new() sin argumentos, su marca (CHAN_MARK, VEC_MARK, MAP_MARK): su T no
    sale de los argumentos sino de la anotación del `let`. Si no, None. map_new()
    no tiene capacidad: con un argumento vuelve None y el checker lo rechaza por
    aridad. La usan el checker y el backend (paso C9)."""
    if not (isinstance(expr, Call) and isinstance(expr.callee, Ident)):
        return None
    name = expr.callee.name
    if name == "chan_new":
        return CHAN_MARK if len(expr.args) in (0, 1) else None
    if name == "vec_new":
        return VEC_MARK if len(expr.args) in (0, 1) else None
    if name == "map_new" and not expr.args:
        return MAP_MARK
    return None


def elemento_de_pop(expr, infer):
    """Si `expr` es `v.pop()` sobre un Vec, el tipo de su elemento (i32 si el Vec
    no lo dice); si no, None. `infer` da el tipo de una expresión (cada lado pasa
    el suyo). pop() baja el largo antes de envolver el valor, así que el Vec deja
    de ser su dueño: si el elemento tiene dueño, el Some(...) no tiene otra dueña
    que quien lo recibe. Qué elementos tienen dueño lo decide cada lado: el
    checker solo lo usa con str (lo marca dueño de su buffer), el backend con
    todo lo que libera (paso C9)."""
    if not (isinstance(expr, MethodCall) and expr.method == "pop"):
        return None
    obj_ty = infer(expr.obj)
    if obj_ty.name != VEC_MARK:
        return None
    return obj_ty.args[0] if obj_ty.args else T_I32
