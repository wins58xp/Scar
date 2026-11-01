"""lib/https (HTTPS sobre libcurl) contra un servidor HTTPS escrito en Python.

    python3 pruebas/test_https_python.py

Levanta un servidor con certificado propio en 127.0.0.1 (y otro con un certificado de nombre
equivocado, y uno sin TLS) y corre pruebas/https_cliente_python.scar con lib/https. Se comprueba:
GET con cabeceras y consulta, POST de JSON con tildes, un cuerpo binario con los 256 valores de byte
(ida y vuelta), las redirecciones 301, 302, 303, 307 y 308 (qué método y qué cuerpo quedan), una cadena
de redirecciones, no seguirlas (0), el bucle infinito cortado, respuesta por trozos, gzip abierto por
curl, 404, 204, HEAD, reintentos (503, 503, 200 en un GET; un POST no se repite; sin `reintentos` no
se repite), 3 MB de cuerpo, certificado de otra autoridad, nombre que no coincide, archivo de
certificados que no existe, certificado propio sin darlo (todos fallan: se verifica SIEMPRE), una URL
http:// (pasa a lib/web), de https a http por redirección, conexión rechazada, cabecera con salto de
línea (rechazada) y esquema ftp. Necesita gcc y los archivos de desarrollo de libcurl (curl/curl.h);
sin eso se omite. Variables opcionales: SCAR_CURL_CFLAGS y SCAR_CURL_LIBS (por si libcurl está en un lugar
raro). Una autocomprobación estropea un resultado y el comparador lo tiene que notar.
"""

import gzip
import http.server
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def omitir(motivo):
    print(f"OK: test_https_python se omite ({motivo})")
    return 0


def hacer_certificado(carpeta, nombre, cn, san):
    clave, cert = os.path.join(carpeta, nombre + ".key"), os.path.join(carpeta, nombre + ".pem")
    r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", clave, "-out", cert,
                        "-days", "2", "-subj", f"/CN={cn}", "-addext", f"subjectAltName={san}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("openssl: " + r.stderr[-300:])
    return clave, cert


class Estado:
    def __init__(self):
        self.cuentas = {}
        self.plano_puerto = 0
        self.lock = threading.Lock()

    def contar(self, k):
        with self.lock:
            self.cuentas[k] = self.cuentas.get(k, 0) + 1
            return self.cuentas[k]


def hacer_manejador(estado):
    class M(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def responder(self, codigo, cuerpo=b"", tipo="text/plain", extra=(), enviar_cuerpo=True, largo=None):
            self.send_response(codigo)
            if codigo != 204:
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo) if largo is None else largo))
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            if enviar_cuerpo and codigo != 204:
                self.wfile.write(cuerpo)

        def cuerpo_pedido(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def atender(self):
            cuerpo = self.cuerpo_pedido()
            ruta = self.path
            base = ruta.split("?")[0]
            if base == "/eco":
                tipo_pedido = self.headers.get("Content-Type", "")
                texto = ""
                if tipo_pedido.startswith("application/json") and cuerpo:
                    d = json.loads(cuerpo.decode("utf-8"))
                    texto = f"{d['nombre']}|{d['n']}"
                else:
                    texto = cuerpo.decode("utf-8", "replace")
                doc = {"metodo": self.command, "ruta": ruta, "x_prueba": self.headers.get("X-Prueba", ""),
                       "tipo": tipo_pedido, "cuerpo": texto}
                datos = json.dumps(doc, ensure_ascii=False).encode("utf-8")
                if self.command == "HEAD":
                    return self.responder(200, b"", "application/json; charset=utf-8", [("X-Servidor", "scar-test")],
                                          enviar_cuerpo=False, largo=1234)
                return self.responder(200, datos, "application/json; charset=utf-8", [("X-Servidor", "scar-test")])
            if base == "/binario":
                return self.responder(200, cuerpo, "application/octet-stream")
            redir = {"/r301": 301, "/r302": 302, "/r303": 303, "/r307": 307, "/r308": 308}
            if base in redir:
                return self.responder(redir[base], b"", extra=[("Location", f"/eco?ok={redir[base]}")])
            if base == "/cadena":
                return self.responder(302, b"", extra=[("Location", "/r301")])
            if base == "/bucle":
                return self.responder(302, b"", extra=[("Location", "/bucle")])
            if base == "/a_http":
                return self.responder(302, b"", extra=[("Location", f"http://127.0.0.1:{estado.plano_puerto}/eco?via=a_http")])
            if base == "/trozos":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for parte in (b"uno", b"-", b"dos", b"-tres"):
                    self.wfile.write(f"{len(parte):x}\r\n".encode() + parte + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
                return
            if base == "/gzip":
                return self.responder(200, gzip.compress("texto comprimido ñ".encode("utf-8")), "text/plain; charset=utf-8",
                                      [("Content-Encoding", "gzip")])
            if base == "/nada":
                return self.responder(404, b"no hay")
            if base == "/vacio":
                return self.responder(204)
            if base == "/inestable":
                n = estado.contar("inestable")
                if n <= 2:
                    return self.responder(503, b"ocupado")
                return self.responder(200, b"por fin")
            if base == "/inestable_post":
                estado.contar("inestable_post")
                return self.responder(503, b"ocupado")
            if base == "/inestable_sin":
                estado.contar("inestable_sin")
                return self.responder(503, b"ocupado")
            if base == "/grande":
                return self.responder(200, bytes((i * 7) % 251 for i in range(3000000)), "application/octet-stream")
            if base == "/cabeceras":
                return self.responder(200, b"x", extra=[("X-Uno", "1"), ("X-Dos", "2"), ("X-Uno", "3")])
            return self.responder(404, b"?")

        do_GET = do_POST = do_PUT = do_HEAD = do_DELETE = atender

    return M


def servidor(estado, cert=None, clave=None):
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), hacer_manejador(estado))
    s.daemon_threads = True
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, clave)
        s.socket = ctx.wrap_socket(s.socket, server_side=True)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def esperado(p, pp, ppo, cerrado_ok=True):
    u = f"https://127.0.0.1:{p}"
    suma = 0
    n = 0
    for i in range(3000000):
        suma = (suma * 31 + (i * 7) % 251) % 1000003
    binario = bytes(range(256)) * 3
    e = {
        "1": f"200 OK | application/json; charset=utf-8 | GET /eco?a=1&b=dos%20tres hola mundo | scar-test",
        "2": "200 OK | POST application/json añejo ñandú|42",
        "3": f"200 OK {len(binario)} application/octet-stream {binario.hex()}",
        "4a": f"200 OK | GET /eco?ok=301 [] | loc= | {u}/eco?ok=301",
        "4b": f"200 OK | GET /eco?ok=302 [] | loc= | {u}/eco?ok=302",
        "4c": f"200 OK | GET /eco?ok=303 [] | loc= | {u}/eco?ok=303",
        "4d": f"200 OK | POST /eco?ok=307 [datos] | loc= | {u}/eco?ok=307",
        "4e": f"200 OK | PUT /eco?ok=308 [datos] | loc= | {u}/eco?ok=308",
        "4f": f"200 OK | GET /eco?ok=301 [] | loc= | {u}/eco?ok=301",
        "4g": f"301 Moved Permanently |  | loc=/eco?ok=301 | {u}/r301",
        "4h": "ERR https: demasiadas redirecciones (más de 5)",
        "5": "200 OK uno-dos-tres 12",
        "6": "200 OK texto comprimido ñ",
        "7": "404 Not Found no hay false",
        "9": "200 OK 0 cl=1234",
        "11": "204 No Content 0",
        "8a": "200 OK por fin",
        "8b": "503 Service Unavailable",
        "8c": "503 Service Unavailable",
        "10": f"200 OK 3000000 {suma}",
        "12a": "ERR tls", "12b": "ERR tls", "12c": "ERR tls", "12d": "ERR tls",
        "13": "200 OK /eco?via=web",
        "14": f"200 OK /eco?via=a_http http://127.0.0.1:{pp}/eco?via=a_http",
        "15": "ERR conexion",
        "16": "ERR https: cabecera inválida: X-Malo",
        "17": "200 OK X-Uno=1;X-Dos=2;X-Uno=3;",
        "18": "ERR https: esquema no soportado 'ftp' en ftp://127.0.0.1/x",
    }
    return e


def leer(salida):
    got = {}
    for linea in salida.splitlines():
        k, _, v = linea.partition(" ")
        if k and k[0].isdigit():
            got[k] = v
    return got


def main():
    if not shutil.which("gcc"):
        return omitir("no hay gcc")
    if not shutil.which("openssl"):
        return omitir("no hay openssl para armar los certificados")
    with tempfile.TemporaryDirectory() as tmp:
        cflags = os.environ.get("SCAR_CURL_CFLAGS", "").split()
        libs = os.environ.get("SCAR_CURL_LIBS", "-lcurl").split()
        so = os.path.join(tmp, "libscarhttp.so")
        r = subprocess.run(["gcc", "-shared", "-fPIC", "-Wall", os.path.join(RAIZ, "native", "scarhttp.c"), "-o", so, *cflags, *libs],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return omitir("no se pudo compilar native/scarhttp.c: falta libcurl con sus archivos de desarrollo; "
                          + (r.stderr.strip().splitlines() or ["?"])[0][:80])
        clave, cert = hacer_certificado(tmp, "a", "127.0.0.1", "IP:127.0.0.1,DNS:localhost")
        clave2, cert2 = hacer_certificado(tmp, "b", "otro", "DNS:otro.ejemplo")
        estado = Estado()
        s1 = servidor(estado, cert, clave)
        s2 = servidor(estado, cert2, clave2)
        s3 = servidor(estado)
        estado.plano_puerto = s3.server_address[1]
        libre = socket.socket()
        libre.bind(("127.0.0.1", 0))
        puerto_cerrado = libre.getsockname()[1]
        libre.close()
        p, po, pp = s1.server_address[1], s2.server_address[1], s3.server_address[1]
        casos = {"base": f"https://127.0.0.1:{p}", "base_otro": f"https://127.0.0.1:{po}", "plano": f"http://127.0.0.1:{pp}",
                 "cerrado": f"https://127.0.0.1:{puerto_cerrado}", "ca": cert, "ca_otro": cert2}
        with open(os.path.join(tmp, "casos.json"), "w") as f:
            json.dump(casos, f)
        env = dict(os.environ, LIBRARY_PATH=tmp + os.pathsep + os.environ.get("LIBRARY_PATH", ""),
                   LD_LIBRARY_PATH=tmp + os.pathsep + os.environ.get("LD_LIBRARY_PATH", ""), SCAR_HTTPS_CA=cert)
        binario = os.path.join(tmp, "b")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/https_cliente_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True, env=env)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_https_python: FALLA, no compila")
            return 1
        if os.environ.get("SCAR_HTTPS_ASAN"):  # opcional: el cliente con ASan (fugas y accesos malos)
            g = subprocess.run(["gcc", "-std=c11", "-g", "-O1", "-fsanitize=address,undefined", "-pthread", binario + ".c", "-o", binario,
                                "-lm", "-L" + tmp, "-lscarhttp"], capture_output=True, text=True)
            if g.returncode != 0:
                print(g.stderr[-1500:])
                return 1
            env["ASAN_OPTIONS"] = "detect_leaks=1"
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300, env=env)
        if os.environ.get("SCAR_HTTPS_ASAN") and ("ERROR: AddressSanitizer" in r.stderr or "runtime error" in r.stderr
                                                 or "LeakSanitizer" in r.stderr):
            print(r.stderr[-2500:])
            print("test_https_python: FALLA, ASan encontró algo")
            return 1
        for s in (s1, s2, s3):
            s.shutdown()
    if r.returncode != 0 or "ERROR" in r.stdout.split("\n")[0:0] or any(l.startswith("ERROR") for l in r.stdout.splitlines()):
        print(r.stdout[-2000:] + r.stderr[-2000:])
        print("test_https_python: FALLA, el programa terminó con", r.returncode)
        return 1
    esp = esperado(p, pp, po)
    got = leer(r.stdout)
    errores = []
    for k in sorted(set(esp) | set(got), key=lambda x: (int("".join(c for c in x if c.isdigit())), x)):
        if esp.get(k) != got.get(k):
            errores.append(f"{k}: lib={got.get(k)!r} esperado={esp.get(k)!r}")
    for k, n in (("inestable", 3), ("inestable_post", 1), ("inestable_sin", 1)):
        if estado.cuentas.get(k) != n:
            errores.append(f"cuenta de {k}: {estado.cuentas.get(k)} (esperado {n})")
    if errores:
        print("\n".join(errores[:15]))
        print(f"test_https_python: FALLA ({len(errores)} diferencias)")
        return 1
    malo = dict(got)
    malo["3"] += "00"
    if leer_igual(esp, malo):
        print("test_https_python: FALLA, la autocomprobación no notó un resultado estropeado")
        return 1
    print(f"OK: lib/https contra un servidor HTTPS de Python: {len(esp)} escenarios y {len(estado.cuentas)} cuentas de reintentos")
    return 0


def leer_igual(esp, got):
    return all(esp.get(k) == got.get(k) for k in set(esp) | set(got))


if __name__ == "__main__":
    sys.exit(main())
