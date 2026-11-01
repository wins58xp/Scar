"""
Servidor de Language Server Protocol para SCAR.

Habla JSON-RPC sobre stdin/stdout con el framing de LSP (headers
"Content-Length") y hace el handshake (initialize / initialized / shutdown /
exit).

Diagnósticos en vivo: cuando el editor abre o edita un archivo
(textDocument/didOpen / didChange) corre el mismo camino que `scar check`
(parse + type_checker.check) sobre el contenido en memoria del editor --
NUNCA sobre el archivo en disco, que puede estar desactualizado -- y publica
el resultado con textDocument/publishDiagnostics. La línea y la columna de
LexError/ParseError se pasan a 0-based. Un error de tipos sin posición no se
esconde: se publica en la línea 1 (ver _make_diagnostic).

Autocompletado (textDocument/completion): las palabras clave del lexer
(lexer.KEYWORDS, así nunca se desincroniza), los nombres de nivel de módulo
(fn/task, struct, enum), las variables y parámetros visibles en el cursor
(scope_resolver) y los campos y métodos tras un '.' (dot_completion). Se
completa contra el ÚLTIMO Program que parseó bien para ese archivo
(`self.last_good_ast[uri]`): mientras se escribe, el buffer casi siempre
tiene un error de sintaxis, y completar contra el último AST válido es
mejor que no completar nada.

No depende de librerías externas (sin pygls/lsprotocol) a propósito: es
poco código y evita agregar una dependencia nueva al proyecto solo para
esto.

Uso: un editor lo invoca como proceso hijo y le habla por stdin/stdout
(`python3 lsp_server.py`). No usar la terminal interactivamente -- espera
el framing exacto de LSP, no líneas sueltas.
"""
import json
import sys
import urllib.parse

from lexer import LexError, KEYWORDS
from parser import parse, ParseError, StructDecl, FnDecl, EnumDecl
from modulos import cargar, ErrorDeModulo
from version import VERSION
from type_checker import check
from scope_resolver import resolve_scope
from dot_completion import extract_dot_chain, resolve_dot_completions


# CompletionItemKind de LSP que usamos -- Keyword para las palabras clave
# del lexer, Function para fn/task, Struct para los tipos, Variable
# (`let`/parámetros, ver resolve_scope), Field y Method
# (campos de struct / métodos fijos del lenguaje tras un '.', ver
# dot_completion.resolve_dot_completions).
_KIND_KEYWORD = 14
_KIND_FUNCTION = 3
_KIND_STRUCT = 22
_KIND_VARIABLE = 6
_KIND_FIELD = 5
_KIND_METHOD = 2


# Severidad LSP (DiagnosticSeverity.Error) -- todo lo que reportamos acá
# (parse + type-check) es un error que impide compilar/correr, no
# un warning ni un hint, así que no hace falta parametrizarla todavía.
_SEVERITY_ERROR = 1



def _ruta_de_uri(uri):
    """`file:///proyecto/a.scar` -> `/proyecto/a.scar` (módulos: los `use` se
    buscan desde la carpeta del archivo abierto)."""
    if uri.startswith("file://"):
        return urllib.parse.unquote(uri[len("file://"):])
    return uri

class LSPServer:
    def __init__(self, infile=None, outfile=None):
        self.infile = infile if infile is not None else sys.stdin.buffer
        self.outfile = outfile if outfile is not None else sys.stdout.buffer
        self.shutdown_received = False
        # uri -> texto en memoria del editor. Nunca se lee del
        # disco: el editor puede tener cambios sin guardar, y es sobre eso
        # que hay que reportar diagnostics.
        self.open_docs = {}
        # uri -> último Program que parseó sin error. No se
        # borra cuando el buffer actual tiene un error de sintaxis a medio
        # escribir -- completar contra el último AST válido es mejor que
        # no completar nada mientras el usuario termina la línea.
        self.last_good_ast = {}

    # ---- framing: header "Content-Length: N\r\n\r\n" + N bytes de JSON ----

    # Un cliente LSP defectuoso, una extensión rota o un mensaje corrupto no
    # deben bloquear ni derribar el servidor: se exige
    # 0 < N <= _MAX_MESSAGE_BYTES, se valida que readline()/read() no
    # cortaron antes de tiempo (stdin cerrado a mitad de mensaje), y un
    # header o body inválido se reporta como un mensaje "saltado"
    # (_ReadError) en vez de propagar la excepción -- el server sigue
    # vivo para el próximo mensaje.
    _MAX_MESSAGE_BYTES = 16 * 1024 * 1024  # 16 MiB, generoso para JSON-RPC de LSP

    class _ReadError(Exception):
        """Mensaje LSP malformado -- no es un crash, es un mensaje descartado."""

    def _read_message(self):
        try:
            return self._read_message_unsafe()
        except LSPServer._ReadError as e:
            print(f"[lsp] mensaje descartado: {e}", file=sys.stderr)
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[lsp] JSON invalido, mensaje descartado: {e}", file=sys.stderr)
            return {}
        except RecursionError:
            # Un JSON anidado 100.000 niveles
            # agotaba la recursión del decodificador: traceback y el servidor
            # se caía. Se descarta el mensaje, como cualquier JSON inválido.
            print("[lsp] JSON demasiado anidado, mensaje descartado", file=sys.stderr)
            return {}

    def _read_message_unsafe(self):
        headers = {}
        while True:
            line = self.infile.readline()
            if not line:
                return None  # stdin cerrado -> el cliente se fue
            try:
                line = line.decode("ascii").rstrip("\r\n")
            except UnicodeDecodeError:
                raise LSPServer._ReadError("header con bytes no-ASCII")
            if line == "":
                break
            key, sep, value = line.partition(":")
            if not sep:
                raise LSPServer._ReadError(f"header sin ':': {line!r}")
            headers[key.strip().lower()] = value.strip()
        raw_length = headers.get("content-length")
        if raw_length is None:
            raise LSPServer._ReadError("falta el header Content-Length")
        try:
            length = int(raw_length)
        except ValueError:
            raise LSPServer._ReadError(f"Content-Length no numerico: {raw_length!r}")
        if length <= 0 or length > LSPServer._MAX_MESSAGE_BYTES:
            raise LSPServer._ReadError(
                f"Content-Length fuera de rango (0 < N <= "
                f"{LSPServer._MAX_MESSAGE_BYTES}): {length}"
            )
        body = self.infile.read(length)
        if len(body) != length:
            raise LSPServer._ReadError(
                f"body truncado: se esperaban {length} bytes, llegaron {len(body)} "
                "(stdin cerrado a mitad de mensaje)"
            )
        return json.loads(body.decode("utf-8"))

    def _write_message(self, obj):
        body = json.dumps(obj).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.outfile.write(header)
        self.outfile.write(body)
        self.outfile.flush()

    def _respond(self, msg_id, result=None, error=None):
        resp = {"jsonrpc": "2.0", "id": msg_id}
        if error is not None:
            resp["error"] = error
        else:
            resp["result"] = result
        self._write_message(resp)

    def _notify(self, method, params):
        # Notification saliente del servidor hacia el editor: sin "id",
        # a diferencia de _respond (que siempre responde a un request del
        # editor). publishDiagnostics es la única que emitimos por ahora.
        self._write_message({"jsonrpc": "2.0", "method": method, "params": params})

    # ---- handlers ----

    def _handle_initialize(self, msg_id, params):
        # textDocumentSync: 1 (Full) -- el editor manda el
        # documento entero en cada didChange, no rangos incrementales; más
        # simple y alcanza para lo que hace el checker (necesita el archivo
        # completo de todos modos, no puede type-checkear un fragmento).
        # triggerCharacters: ['.'] -- completion específico al tipear el punto (ver
        # _handle_completion: resuelve scope local con
        # scope_resolver.resolve_scope y, si el cursor queda justo tras
        # un '.', campos/métodos con dot_completion.resolve_dot_completions).
        self._respond(msg_id, {
            "capabilities": {
                "textDocumentSync": 1,
                "completionProvider": {"triggerCharacters": ["."]},
            },
            "serverInfo": {"name": "scar-lsp", "version": VERSION},
        })

    def _handle_shutdown(self, msg_id, params):
        self.shutdown_received = True
        self._respond(msg_id, None)

    # ---- diagnostics ----

    def _make_diagnostic(self, line, col, message):
        """Arma un Diagnostic de LSP a partir de una posición 1-based (la que
        usan LexError/ParseError/TypeError_) o sin posición.

        - line=None (un TypeError_ sin línea): aproxima a la línea 1.
        - col=None (TypeError_ nunca trae col; a veces tampoco LexError/
          ParseError): aproxima a la columna 0.
        Convierte a 0-based (LSP) y arma un rango de un carácter -- no hay
        length de token acá, así que no se puede subrayar el token entero,
        pero un rango de largo 0 no lo renderizan todos los editores.
        """
        lsp_line = (line - 1) if line else 0
        lsp_col = (col - 1) if col else 0
        return {
            "range": {
                "start": {"line": lsp_line, "character": lsp_col},
                "end": {"line": lsp_line, "character": lsp_col + 1},
            },
            "severity": _SEVERITY_ERROR,
            "source": "scar",
            "message": message,
        }

    def _diagnostics_for_source(self, uri, text):
        """Corre el mismo camino que `scar check` sobre `text` y
        devuelve una lista de Diagnostic. Nunca deja escapar una excepción:
        un bug nuestro no debe tirar abajo la sesión de LSP del editor, en
        el peor caso el editor se queda sin diagnostics para ese archivo.

        De paso actualiza self.last_good_ast[uri] cuando el
        parseo sale bien -- se hace acá y no en un segundo parse aparte
        para completion, ya que parsear es la parte cara y ya la estamos
        pagando en cada didOpen/didChange de todos modos."""
        try:
            # módulos: los `use` se resuelven desde la carpeta del archivo
            program = cargar(_ruta_de_uri(uri), text)
        except (LexError, ParseError, ErrorDeModulo) as e:
            if getattr(e, "archivo", None):
                # el error está en un módulo: se marca al principio del
                # archivo abierto, con el archivo y la línea en el mensaje
                return [self._make_diagnostic(None, None, f"{e} (en {e.archivo})")]
            return [self._make_diagnostic(
                getattr(e, "line", None), getattr(e, "col", None), str(e)
            )]
        except Exception:
            return []

        self.last_good_ast[uri] = program
        try:
            errors = check(program)
        except Exception:
            return []
        return [
            # un error de un módulo va al principio del archivo abierto, con
            # el archivo y la línea en el mensaje (str(e) los trae)
            self._make_diagnostic(None, None, str(e)) if getattr(e, "archivo", None)
            else self._make_diagnostic(getattr(e, "line", None), None, e.msg)
            for e in errors
        ]

    def _publish_diagnostics(self, uri, text):
        self._notify("textDocument/publishDiagnostics", {
            "uri": uri,
            "diagnostics": self._diagnostics_for_source(uri, text),
        })

    # ---- autocompletado ----
    #
    # Keywords + nombres top-level (fn/task/struct/enum), y dos cosas más,
    # ambas basadas en el ÚLTIMO AST válido
    # (self.last_good_ast, ver _diagnostics_for_source) y NUNCA en un
    # re-parseo del buffer actual (que puede estar roto a medio
    # escribir -- razón de ser de scope_resolver.py/dot_completion.py,
    # ver sus docstrings):
    #   (a) variables locales visibles en la posición del cursor
    #       (scope_resolver.resolve_scope) -- sumadas a la lista de
    #       siempre, no la reemplazan: el editor las filtra igual por
    #       lo que el usuario ya tecleó.
    #   (b) si el cursor queda justo después de un '.' de una cadena de
    #       identificadores (dot_completion.extract_dot_chain detecta
    #       esto sobre el texto crudo de la línea, sin parsear), se
    #       responde SOLO con los campos/métodos de esa cadena --
    #       mezclar eso con keywords/nombres top-level no tendría
    #       sentido para el usuario en ese punto.
    def _handle_completion(self, msg_id, params):
        uri = params["textDocument"]["uri"]
        program = self.last_good_ast.get(uri)
        pos = params["position"]
        # LSP es 0-based; line/col de nuestro AST (Token/Node, ver
        # parser.py) son 1-based -- misma conversión que _make_diagnostic
        # hace al revés.
        line = pos["line"] + 1
        col = pos["character"] + 1

        text = self.open_docs.get(uri, "")
        lines = text.split("\n")
        line_text = lines[pos["line"]] if pos["line"] < len(lines) else ""
        prefix = line_text[: pos["character"]]
        chain = extract_dot_chain(prefix)

        if chain is not None and program is not None and len(chain) == 1 \
                and any(getattr(it, "name", "").startswith(chain[0] + ".") for it in program.items):
            # módulos: `gui.` -> lo público del módulo (sin lo que empieza con _)
            pre = chain[0] + "."
            res = []
            for it in program.items:
                nombre = getattr(it, "name", "")
                if not nombre.startswith(pre) or nombre[len(pre):].startswith("_"):
                    continue
                kind = _KIND_STRUCT if isinstance(it, (StructDecl, EnumDecl)) else _KIND_FUNCTION
                res.append({"label": nombre[len(pre):], "kind": kind})
                if isinstance(it, EnumDecl):
                    res.extend({"label": v.name[len(pre):], "kind": _KIND_FUNCTION} for v in it.variants)
            self._respond(msg_id, res)
            return

        if chain is not None and program is not None:
            symbols = resolve_scope(program, line, col)
            dot_items = resolve_dot_completions(program, symbols, chain)
            kind_map = {"field": _KIND_FIELD, "method": _KIND_METHOD}
            self._respond(msg_id, [
                {"label": name, "kind": kind_map[kind]}
                for name, kind in dot_items
            ])
            return

        items = [
            {"label": kw, "kind": _KIND_KEYWORD}
            for kw in sorted(KEYWORDS)
        ]
        if program is not None:
            for item in program.items:
                if isinstance(item, FnDecl):
                    items.append({"label": item.name, "kind": _KIND_FUNCTION})
                elif isinstance(item, StructDecl):
                    items.append({"label": item.name, "kind": _KIND_STRUCT})
            for sym in resolve_scope(program, line, col):
                items.append({"label": sym.name, "kind": _KIND_VARIABLE})
        self._respond(msg_id, items)

    def _handle_did_open(self, params):
        doc = params["textDocument"]
        uri, text = doc["uri"], doc["text"]
        self.open_docs[uri] = text
        self._publish_diagnostics(uri, text)

    def _handle_did_change(self, params):
        uri = params["textDocument"]["uri"]
        # textDocumentSync=1 (Full, ver _handle_initialize): cada evento
        # trae el documento entero como único elemento de contentChanges,
        # sin "range" -- no hay parches incrementales que aplicar.
        text = params["contentChanges"][-1]["text"]
        self.open_docs[uri] = text
        self._publish_diagnostics(uri, text)

    def _handle_did_close(self, params):
        uri = params["textDocument"]["uri"]
        self.open_docs.pop(uri, None)
        self.last_good_ast.pop(uri, None)
        # Limpia los diagnostics en el editor al cerrar -- si no, quedan
        # errores "fantasma" de la última versión que se vio.
        self._notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})

    def _handle_unknown_request(self, msg_id, method):
        # Cualquier request que todavía no implementamos: error estándar de
        # JSON-RPC ("method not found"), no un crash. Las notifications
        # desconocidas (sin "id") simplemente se ignoran, ver run().
        self._respond(msg_id, error={
            "code": -32601,
            "message": f"método no soportado todavía: {method}",
        })

    # ---- loop principal ----

    def run(self):
        while True:
            msg = self._read_message()
            if msg is None:
                return 0 if self.shutdown_received else 1
            if not isinstance(msg, dict):
                print("[lsp] el mensaje no es un objeto JSON, se descarta", file=sys.stderr)
                continue
            method = msg.get("method")
            msg_id = msg.get("id")  # ausente en notifications
            params = msg.get("params", {})
            if params is None:
                params = {}
            if not isinstance(params, dict):
                # Params de otro tipo (un string,
                # una lista) hacían reventar al handler con un traceback.
                print(f"[lsp] params inválidos en {method!r}: se esperaba un objeto", file=sys.stderr)
                if msg_id is not None:
                    self._respond(msg_id, error={"code": -32602, "message": "params debe ser un objeto"})
                continue
            try:
                if self._despachar(method, msg_id, params) == "salir":
                    return 0 if self.shutdown_received else 1
            except Exception as e:  # un handler que falla no tumba el servidor
                print(f"[lsp] error interno en {method!r}: {type(e).__name__}: {e}", file=sys.stderr)
                if msg_id is not None:
                    self._respond(msg_id, error={"code": -32603, "message": f"error interno: {type(e).__name__}"})

    def _despachar(self, method, msg_id, params):
        if method == "exit":
            return "salir"
        if method == "initialize":
            self._handle_initialize(msg_id, params)
            return
        if method == "shutdown":
            self._handle_shutdown(msg_id, params)
            return
        if method == "initialized":
            return  # notification, nada que responder

        if method == "textDocument/didOpen":
            self._handle_did_open(params)
            return
        if method == "textDocument/didChange":
            self._handle_did_change(params)
            return
        if method == "textDocument/didClose":
            self._handle_did_close(params)
            return
        if method == "textDocument/completion":
            self._handle_completion(msg_id, params)
            return

        if msg_id is None:
            # notification que no reconocemos: se ignora, no se responde
            # nunca a una notification (ni siquiera con error, ver spec).
            return
        self._handle_unknown_request(msg_id, method)


def main():
    sys.exit(LSPServer().run())


if __name__ == "__main__":
    main()
