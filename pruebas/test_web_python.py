"""lib/web (URLs) contra urllib.parse.

    python3 pruebas/test_web_python.py

Python inventa URLs (a mano y al azar, también estropeadas con caracteres sueltos) y las
escribe en casos.json. pruebas/web_python.scar las procesa con lib/web y Python repite todo con
urllib.parse:

  - urlsplit: esquema, autoridad, ruta, consulta y fragmento (o el error de un [ sin ]);
  - hostname, port (-1 sin puerto, -2 si urllib da ValueError), username y password;
  - urlunsplit de lo que salió de urlsplit;
  - urljoin con bases y referencias de todo tipo (.., ., //otro, ?q, #f, rutas absolutas);
  - parse_qsl con y sin keep_blank_values y urlencode (quote_plus).

Y el cliente HTTP (pruebas/web_cliente_python.scar) contra un servidor de prueba en Python:
GET, POST (JSON y formulario), PUT, DELETE, HEAD, cuerpos por Content-Length, por trozos y hasta
que se cierra, redirecciones (301, 302, 307, bucles, cambio de servidor sin Authorization),
reintentos con 503 (un POST no se repite), cuerpos de 300 KB y de todos los bytes, y los errores
(conexión rechazada, https, cabecera con salto de línea, respuesta cortada, trozos mal hechos).

Las partes salen en hexadecimal UTF-8 y se piden iguales. urllib cambió de una versión a otra
(urlunsplit con // vacío, 3.12.4): por eso se compara con una copia fija de la lógica de 3.13 que
vale con cualquier Python 3.8 o más nuevo; con 3.12.4 o más nuevo se comprueba además que la copia
coincide con su urllib.
"""

import hashlib
import json
import os
import random
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.parse as up

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- referencia fija: urllib.parse de Python 3.13 ----------
# urllib cambió entre versiones (urlunsplit con // vacío, validación de IPv6, zona sin bajar a
# minúsculas), así que la prueba compara con una copia de la lógica de 3.13 y no con el urllib
# que haya instalado. Si el Python es 3.12.4 o más nuevo, además comprueba que la copia da lo
# mismo que su urllib (así se sabe que la copia está bien).

import ipaddress
import re
from collections import namedtuple

USES_NETLOC = ['', 'ftp', 'http', 'gopher', 'nntp', 'telnet', 'imap', 'wais', 'file', 'mms', 'https', 'shttp', 'snews', 'prospero', 'rtsp',
               'rtsps', 'rtspu', 'rsync', 'svn', 'svn+ssh', 'sftp', 'nfs', 'git', 'git+ssh', 'ws', 'wss', 'itms-services']
USES_RELATIVE = ['', 'ftp', 'http', 'gopher', 'nntp', 'imap', 'wais', 'file', 'https', 'shttp', 'mms', 'prospero', 'rtsp', 'rtsps', 'rtspu',
                 'sftp', 'svn', 'svn+ssh', 'ws', 'wss']
USES_PARAMS = ['', 'ftp', 'hdl', 'prospero', 'http', 'imap', 'https', 'shttp', 'rtsp', 'rtsps', 'rtspu', 'sip', 'sips', 'mms', 'sftp', 'tel']
SCHEME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-."
C0 = "".join(chr(i) for i in range(0, 33))
Partes = namedtuple("Partes", "scheme netloc path query fragment")


def _check_host(h):
    if h.startswith(("v", "V")):
        if not re.match(r"\A[vV][a-fA-F0-9]+\..+\Z", h):
            raise ValueError("IPvFuture")
    else:
        ip = ipaddress.ip_address(h)
        if isinstance(ip, ipaddress.IPv4Address):
            raise ValueError("IPv4 entre corchetes")


def _check_netloc(netloc):
    hp = netloc.rpartition("@")[2]
    antes, abre, entre = hp.partition("[")
    if abre:
        if antes:
            raise ValueError("IPv6")
        h, _, puerto = entre.partition("]")
        if puerto and not puerto.startswith(":"):
            raise ValueError("IPv6")
    else:
        h, _, puerto = hp.partition(":")
    _check_host(h)


def ref_split(url, scheme=""):
    url = url.lstrip(C0)
    scheme = scheme.strip(C0)
    for b in "\t\r\n":
        url = url.replace(b, "")
        scheme = scheme.replace(b, "")
    netloc = query = fragment = ""
    i = url.find(":")
    if i > 0 and url[0].isascii() and url[0].isalpha():
        if all(c in SCHEME_CHARS for c in url[:i]):
            scheme, url = url[:i].lower(), url[i + 1:]
    if url[:2] == "//":
        delim = len(url)
        for c in "/?#":
            w = url.find(c, 2)
            if w >= 0:
                delim = min(delim, w)
        netloc, url = url[2:delim], url[delim:]
        if ("[" in netloc and "]" not in netloc) or ("]" in netloc and "[" not in netloc):
            raise ValueError("Invalid IPv6 URL")
        if "[" in netloc and "]" in netloc:
            _check_netloc(netloc)
    if "#" in url:
        url, fragment = url.split("#", 1)
    if "?" in url:
        url, query = url.split("?", 1)
    return Partes(scheme, netloc, url, query, fragment)


def ref_unsplit(c):
    scheme, netloc, url, query, fragment = c
    if netloc:
        if url and url[:1] != "/":
            url = "/" + url
        url = "//" + netloc + url
    elif url[:2] == "//":
        url = "//" + url
    elif scheme and scheme in USES_NETLOC and (not url or url[:1] == "/"):
        url = "//" + url
    if scheme:
        url = scheme + ":" + url
    if query:
        url = url + "?" + query
    if fragment:
        url = url + "#" + fragment
    return url


def ref_parse(url, scheme=""):
    sc, netloc, path, query, fragment = ref_split(url, scheme)
    params = ""
    if sc in USES_PARAMS and ";" in path:
        i = path.find(";", path.rfind("/")) if "/" in path else path.find(";")
        if i >= 0:
            path, params = path[:i], path[i + 1:]
    return sc, netloc, path, params, query, fragment


def ref_unparse(c):
    sc, netloc, path, params, query, fragment = c
    if params:
        path = "%s;%s" % (path, params)
    return ref_unsplit((sc, netloc, path, query, fragment))


def ref_join(base, url):
    if not base:
        return url
    if not url:
        return base
    bs, bn, bp, bpar, bq, bf = ref_parse(base, "")
    sc, netloc, path, params, query, fragment = ref_parse(url, bs)
    if sc != bs or sc not in USES_RELATIVE:
        return url
    if sc in USES_NETLOC:
        if netloc:
            return ref_unparse((sc, netloc, path, params, query, fragment))
        netloc = bn
    if not path and not params:
        path = bp
        params = bpar
        if not query:
            query = bq
        return ref_unparse((sc, netloc, path, params, query, fragment))
    base_parts = bp.split("/")
    if base_parts[-1] != "":
        del base_parts[-1]
    if path[:1] == "/":
        segmentos = path.split("/")
    else:
        segmentos = base_parts + path.split("/")
        segmentos[1:-1] = filter(None, segmentos[1:-1])
    resuelto = []
    for seg in segmentos:
        if seg == "..":
            try:
                resuelto.pop()
            except IndexError:
                pass
        elif seg == ".":
            continue
        else:
            resuelto.append(seg)
    if segmentos[-1] in (".", ".."):
        resuelto.append("")
    return ref_unparse((sc, netloc, "/".join(resuelto) or "/", params, query, fragment))


def ref_hostinfo(netloc):
    _, _, hostinfo = netloc.rpartition("@")
    _, abre, entre = hostinfo.partition("[")
    if abre:
        host, _, puerto = entre.partition("]")
        _, _, puerto = puerto.partition(":")
    else:
        host, _, puerto = hostinfo.partition(":")
    return host, (puerto or None)


def ref_hostname(netloc):
    h = ref_hostinfo(netloc)[0]
    if not h:
        return None
    h, pc, zona = h.partition("%")
    return h.lower() + pc + zona


def ref_port(netloc):
    p = ref_hostinfo(netloc)[1]
    if p is not None:
        if p.isdigit() and p.isascii():
            p = int(p)
        else:
            raise ValueError("puerto")
        if not (0 <= p <= 65535):
            raise ValueError("puerto")
    return p


def ref_userinfo(netloc):
    ui, tiene, _ = netloc.rpartition("@")
    if not tiene:
        return None, None
    u, dp, p = ui.partition(":")
    return u, (p if dp else None)


def h(t):
    return t.encode("utf-8").hex()


def casos_al_azar(rng):
    urls = [
        "", "a", "http://ejemplo.cl", "http://ejemplo.cl/", "HTTP://Ejemplo.CL:8080/a/b?x=1&y=2#frag",
        "https://ana:clave@host.cl:443/p?q#f", "https://ana@host.cl/p", "https://:clave@host.cl/", "//host/ruta", "/ruta/sola",
        "ruta/relativa", "?solo=consulta", "#solo-fragmento", "mailto:ana@ejemplo.cl", "file:///etc/hosts", "file:/etc/hosts",
        "http://[::1]:8000/x", "http://[2001:db8::1]/", "http://[::1", "http://::1]/", "http://h:abc/", "http://h:99999/",
        "http://h:/", "http://h:0/", "http://h:65535/", "http://h:65536/", "http://H/", "x:y", "1x://a", "a+b-c.d://x/y",
        "ñ://x", "http:///x", "http://", "http:", "http:a", "//", "///", "////x", "http://a b/c d", "http://h/%7Euser",
        "  http://h/", "\thttp://h/\n", "http://h/a?b?c#d#e", "http://h#f?q", "http://h?q#f", "?#", "a?b#", "http://h/?", "http://h/#",
        "http://ñandú.cl/ñ?ñ=ñ#ñ", "http://usuario@@host/", "http://a@b@c:80/", "http://a:b:c@d/", "urn:isbn:0451450523",
        "javascript:alert(1)", "tel:+56912345678", "ftp://f.cl/dir/", "ws://h:1/", "wss://h/", "git+ssh://g@h/r.git",
        "http://h/a;p=1/b", "http://h/a/../b/./c", "HTTP:", "Http://x", "h t t p://x",
    ]
    esquemas = [None, "http", "https", "ftp", "file", "mailto", "X-y.z", "Ws", "data"]
    usuarios = [None, "ana", "ana:clave", ":c", "a@b", ""]
    hosts = ["ejemplo.cl", "EJEMPLO.cl", "127.0.0.1", "[::1]", "[2001:db8::1]", "a", "", "xn--80ak6aa92e.com", "h-1.org"]
    puertos = [None, "80", "8080", "0", "65535", "65536", "x", "", "007", "1_0"]
    rutas = ["", "/", "/a", "/a/b/", "a/b", "/a//b", "/a/./b/../c", "/%7Ea", "/ñ", "/a b", "//x", "/a;b", "/a:b", "a:b"]
    consultas = [None, "", "a=1", "a=1&b=2", "a=b=c", "x", "ñ=é", "q=hola+mundo", "%zz=%41"]
    fragmentos = [None, "", "f", "f g", "a/b?c#d"]
    for _ in range(400):
        s = ""
        e = rng.choice(esquemas)
        if e is not None:
            s += e + ":"
        if rng.random() < 0.7:
            s += "//"
            u = rng.choice(usuarios)
            if u is not None:
                s += u + "@"
            s += rng.choice(hosts)
            p = rng.choice(puertos)
            if p is not None:
                s += ":" + p
        s += rng.choice(rutas)
        q = rng.choice(consultas)
        if q is not None:
            s += "?" + q
        f = rng.choice(fragmentos)
        if f is not None:
            s += "#" + f
        urls.append(s)
    # las mismas, estropeadas con un carácter suelto (sin los de control que cambian de versión)
    base = list(urls)
    for _ in range(300):
        s = rng.choice(base)
        i = rng.randint(0, len(s))
        s = s[:i] + rng.choice(":/?#@[]. %&=;+") + s[i:]
        urls.append(s)
    urls = [u for u in urls if "[" not in u or ("[::1]" in u or "[2001:db8::1]" in u) or True]
    urls = [u for u in urls if "\x00" not in u]

    bases = ["http://a.cl/b/c/d;p?q=1", "http://a.cl/b/c/d", "http://a.cl/b/c/", "http://a.cl", "http://a.cl/", "https://x.org:81/p/q.html?z#f",
             "ftp://f.cl/dir/arch", "file:///a/b", "mailto:a@b", "/solo/ruta", "a/b", "http://a.cl/b/c/d?x=1#y", "//host/p/q", "urn:x:y", "ws://h/a/b"]
    refs = ["g", "./g", "g/", "/g", "//g", "?y", "g?y", "#s", "g#s", "g?y#s", "", ".", "./", "..", "../", "../g", "../..", "../../g",
            "../../../g", "../../../../g", "/./g", "/../g", "g.", ".g", "g..", "..g", "./../g", "./g/.", "g/./h", "g/../h",
            "http://x.cl/y", "https://x.cl", "ftp://f.cl/z", "mailto:x@y", "g:h", "http:g", "http:", "?", "a//b", "//a//b/../c",
            "x/y?z=1", "../x?q#r", "ñ/é", "g b", "HTTP://Y/z", "file:q", "ws:q", "wss://h/"]
    joins = [[b, r] for b in bases for r in refs]
    joins += [["", "x"], ["x", ""], ["", ""]]
    for _ in range(200):
        joins.append([rng.choice(urls), rng.choice(refs + urls)])
    joins = [j for j in joins if all("\x00" not in x for x in j)]

    qs = ["", "a=1", "a=1&b=2", "a=&b", "a&b=2", "&&a=1&&", "a=1=2", "=v", "=", "a=%41", "a=%zz", "a=%4", "a=%", "a+b=c+d", "a=%2B", "n=%C3%B1&m=%e6%97%a5",
          "a=1;b=2", "x=1&x=2", "a%20b=c%26d", "?a=1", "a=b#c", "ñ=é", "a=%2", "%=%"]
    for _ in range(120):
        alf = ["a", "b", "=", "&", "%", "+", "1", "4", "z", ";", "ñ", "%41", "%C3%B1"]
        qs.append("".join(rng.choice(alf) for _ in range(rng.randint(0, 14))))
    qs = [q for q in qs if "\x00" not in q and "%00" not in q]

    nombres = ["a", "b c", "ñ", "x&y", "p=q", "100%", "", "日本", "😀", "~._-", "+", "a+b", "/?#"]
    pares = [[], [["a", "1"]], [["a", ""]], [["", "v"]], [["a", "1"], ["a", "2"], ["b", "x y"]]]
    for _ in range(80):
        pares.append([[rng.choice(nombres), rng.choice(nombres)] for _ in range(rng.randint(1, 5))])
    return {"urls": urls, "joins": joins, "consultas": qs, "pares": pares}


def leer(stdout):
    r = {}
    for linea in stdout.splitlines():
        p = linea.split(" ", 2)
        if len(p) >= 2 and p[0].isupper() and p[1].isdigit():
            r[(p[0], int(p[1]))] = p[2] if len(p) == 3 else ""
    return r


def dividir(u):
    try:
        return ref_split(u)
    except ValueError:
        return None


def comprobar_referencia(casos):
    """Con Python 3.12.4 o más nuevo, la copia fija tiene que dar lo mismo que su urllib."""
    malas = []
    for u in casos["urls"]:
        try:
            esperado = up.urlsplit(u)
        except ValueError:
            esperado = None
        mia = dividir(u)
        if (mia is None) != (esperado is None) or (mia is not None and tuple(mia) != tuple(esperado)):
            malas.append(("split", u))
        elif mia is not None and ref_unsplit(mia) != up.urlunsplit(esperado):
            malas.append(("unsplit", u))
    for b, r in casos["joins"]:
        try:
            esperado = up.urljoin(b, r)
        except ValueError:
            esperado = r
        try:
            mia = ref_join(b, r)
        except ValueError:
            mia = r
        if mia != esperado:
            malas.append(("join", (b, r)))
    return malas


# ---------- servidor de prueba para el cliente ----------

GRANDE = random.Random(5).randbytes(300000)
BINARIO = bytes(range(256)) * 4


class Servidor(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def hacer_manejador(contadores, puerto):
    import socketserver as ss

    class M(ss.StreamRequestHandler):
        def responder(self, linea, cabeceras, cuerpo=b"", con_largo=True):
            out = linea.encode() + b"\r\n"
            for k, v in cabeceras:
                out += k.encode() + b": " + v.encode("utf-8") + b"\r\n"
            if con_largo:
                out += b"Content-Length: " + str(len(cuerpo)).encode() + b"\r\n"
            out += b"Connection: close\r\n\r\n" + cuerpo
            self.wfile.write(out)

        def handle(self):
            linea = self.rfile.readline().decode("latin-1").strip()
            if not linea:
                return
            metodo, destino, _ = linea.split(" ", 2)
            cab = {}
            while True:
                l = self.rfile.readline().decode("latin-1")
                if l in ("\r\n", "\n", ""):
                    break
                k, _, v = l.partition(":")
                cab[k.strip().lower()] = v.strip().encode("latin-1").decode("utf-8")
            cuerpo = self.rfile.read(int(cab.get("content-length", "0")))
            ruta = destino.split("?")[0]
            q = up.parse_qs(destino.partition("?")[2])
            texto = [("Content-Type", "text/plain")]
            if ruta == "/eco":
                datos = json.dumps({"metodo": metodo, "destino": destino, "cabeceras": cab, "cuerpo": cuerpo.hex()}, ensure_ascii=False).encode()
                lg = len(datos)
                if metodo == "HEAD":
                    self.wfile.write(("HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % lg).encode())
                else:
                    self.responder("HTTP/1.1 200 OK", [("Content-Type", "application/json; charset=utf-8")], datos)
            elif ruta == "/trozos":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                                 b"5;ext=1\r\nHola \r\n5\r\nmundo\r\n1\r\n!\r\n0\r\n\r\n")
            elif ruta == "/sinlargo":
                self.responder("HTTP/1.1 200 OK", texto, b"sin largo", con_largo=False)
            elif ruta.startswith("/redir/"):
                n = int(ruta.split("/")[2])
                self.responder("HTTP/1.1 302 Found", [("Location", "/redir/%d" % (n - 1) if n > 1 else "/fin")])
            elif ruta == "/fin":
                self.responder("HTTP/1.1 200 OK", texto, b"fin")
            elif ruta == "/bucle":
                self.responder("HTTP/1.1 302 Found", [("Location", "/bucle")])
            elif ruta == "/a301":
                self.responder("HTTP/1.1 301 Moved Permanently", [("Location", "/eco")])
            elif ruta == "/a307":
                self.responder("HTTP/1.1 307 Temporary Redirect", [("Location", "/eco")])
            elif ruta == "/a308":
                self.responder("HTTP/1.1 308 Permanent Redirect", [("Location", "/eco")])
            elif ruta == "/a303":
                self.responder("HTTP/1.1 303 See Other", [("Location", "/eco")])
            elif ruta == "/otro":
                self.responder("HTTP/1.1 302 Found", [("Location", "http://127.0.0.2:%d/eco" % puerto)])
            elif ruta == "/404":
                self.responder("HTTP/1.1 404 Not Found", texto, b"no existe")
            elif ruta == "/vacio":
                self.wfile.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            elif ruta == "/inestable":
                i = q["id"][0]
                contadores[i] = contadores.get(i, 0) + 1
                if contadores[i] <= 2:
                    self.responder("HTTP/1.1 503 Service Unavailable", texto, b"no")
                else:
                    self.responder("HTTP/1.1 200 OK", texto, b"ok")
            elif ruta == "/contador":
                self.responder("HTTP/1.1 200 OK", texto, str(contadores.get(q["id"][0], 0)).encode())
            elif ruta == "/grande":
                self.responder("HTTP/1.1 200 OK", [("Content-Type", "application/octet-stream")], GRANDE)
            elif ruta == "/binario":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                                 + b"".join(b"%x\r\n" % len(BINARIO[i:i + 100]) + BINARIO[i:i + 100] + b"\r\n" for i in range(0, len(BINARIO), 100))
                                 + b"0\r\n\r\n")
            elif ruta == "/json":
                self.responder("HTTP/1.1 200 OK", [("Content-Type", "application/json")], json.dumps({"a": [{"b": "ñ😀"}]}, ensure_ascii=False).encode())
            elif ruta == "/cortada":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\n0123456789")
            elif ruta == "/trozos_malos":
                self.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\nzz\r\nhola\r\n0\r\n\r\n")
            elif ruta == "/no_http":
                self.wfile.write(b"HOLA\r\n\r\n")
            else:
                self.responder("HTTP/1.1 404 Not Found", texto, b"?")

    return M


def prueba_cliente(tmp):
    contadores = {}
    srv = Servidor(("0.0.0.0", 0), None)
    puerto = srv.server_address[1]
    srv.RequestHandlerClass = hacer_manejador(contadores, puerto)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    try:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump({"puerto": puerto}, f)
        binario = os.path.join(tmp, "cliente")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/web_cliente_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            return None, b.stdout + b.stderr, puerto
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300)
        return r, "", puerto
    finally:
        srv.shutdown()


def de_hex(x):
    return bytes.fromhex(x).decode("utf-8") if x else ""


def revisar_cliente(got, puerto, errores):
    n = 0
    sha = hashlib.sha256

    def campo(k):
        return got.get(("%s" % k[0], k[1]), "")

    def eco(k, metodo, destino, ct, cl, auth, uno, host, cuerpo_ok):
        nonlocal n
        n += 1
        v = got.get(("ECO", k), "").split(" ")
        if len(v) != 10 or v[0] != "OK" or v[1] != "200":
            errores.append(f"ECO {k}: salió {got.get(('ECO', k))!r:.120}")
            return
        real = [de_hex(x) for x in v[2:9]]
        esperado = [metodo, destino, ct, cl, auth, uno, host]
        if real != esperado or not cuerpo_ok(bytes.fromhex(v[9])):
            errores.append(f"ECO {k}: salió {real} cuerpo {v[9][:40]} y se esperaba {esperado}")

    def resp(k, codigo, motivo, ct, cuerpo):
        nonlocal n
        n += 1
        v = got.get(("RESP", k), "").split(" ")
        esperado = ["OK", str(codigo), h(motivo), h(ct), cuerpo.hex()]
        if v != esperado:
            errores.append(f"RESP {k}: salió {got.get(('RESP', k))!r:.120} y se esperaba {esperado!r:.120}")

    def err(k, contiene):
        nonlocal n
        n += 1
        v = got.get(("RESP", k), "")
        if not v.startswith("ERR ") or contiene not in de_hex(v[4:]):
            errores.append(f"RESP {k}: salió {de_hex(v[4:]) if v.startswith('ERR ') else v!r:.100} y se esperaba un error con {contiene!r}")

    eco(1, "GET", "/eco?a=1&b=dos", "", "", "Bearer abc", "valor ñ", f"127.0.0.1:{puerto}", lambda c: c == b"")
    js = json.dumps({"lugar": "Calama ñ", "mag": 4}, ensure_ascii=False)
    n += 0
    v = got.get(("ECO", 2), "").split(" ")
    n += 1
    try:
        cuerpo = bytes.fromhex(v[9])
        if v[:2] != ["OK", "200"] or de_hex(v[2]) != "POST" or de_hex(v[4]) != "application/json" \
                or de_hex(v[5]) != str(len(cuerpo)) or json.loads(cuerpo.decode()) != {"lugar": "Calama ñ", "mag": 4}:
            errores.append(f"ECO 2: salió {got.get(('ECO', 2))!r:.150}")
    except Exception as e:
        errores.append(f"ECO 2: {e}: {got.get(('ECO', 2))!r:.100}")
    form = b"nombre=Ana+Mar%C3%ADa&x%26y=1%2B1%3D2"
    eco(3, "POST", "/eco", "application/x-www-form-urlencoded", str(len(form)), "", "", f"127.0.0.1:{puerto}", lambda c: c == form)
    eco(4, "PUT", "/eco", "", "4", "", "", f"127.0.0.1:{puerto}", lambda c: c == b"hola")
    eco(5, "DELETE", "/eco", "", "", "", "", f"127.0.0.1:{puerto}", lambda c: c == b"")
    resp(6, 200, "OK", "text/plain", b"Hola mundo!")
    resp(7, 200, "OK", "text/plain", b"sin largo")
    resp(8, 200, "OK", "text/plain", b"fin")
    err(9, "demasiadas redirecciones")
    resp(10, 302, "Found", "", b"")
    eco(11, "GET", "/eco", "", "", "", "", f"127.0.0.1:{puerto}", lambda c: c == b"")
    eco(12, "POST", "/eco", "text/plain", "5", "", "", f"127.0.0.1:{puerto}", lambda c: c == b"datos")
    eco(35, "POST", "/eco", "text/plain", "5", "", "", f"127.0.0.1:{puerto}", lambda c: c == b"datos")
    eco(36, "GET", "/eco", "", "", "", "", f"127.0.0.1:{puerto}", lambda c: c == b"")
    eco(13, "GET", "/eco", "", "", "", "valor ñ", f"127.0.0.2:{puerto}", lambda c: c == b"")
    resp(14, 404, "Not Found", "text/plain", b"no existe")
    resp(15, 200, "OK", "application/json; charset=utf-8", b"")
    resp(16, 204, "No Content", "", b"")
    resp(17, 200, "OK", "text/plain", b"ok")
    resp(18, 200, "OK", "text/plain", b"3")
    resp(19, 503, "Service Unavailable", "text/plain", b"no")
    resp(20, 200, "OK", "text/plain", b"1")
    resp(21, 503, "Service Unavailable", "text/plain", b"no")
    for k, datos in ((22, GRANDE), (23, BINARIO)):
        n += 1
        esperado = f"{len(datos)} {sha(datos).hexdigest()}"
        if got.get(("GRANDE", k)) != esperado:
            errores.append(f"GRANDE {k}: salió {got.get(('GRANDE', k))!r:.100} y se esperaba {esperado!r:.100}")
    n += 1
    if got.get(("JSON", 24)) != f"{h('ñ😀')} 1 true":
        errores.append(f"JSON 24: salió {got.get(('JSON', 24))!r:.100}")
    err(25, "incompleta")
    err(26, "trozo")
    err(27, "conexión:")
    err(28, "https no está disponible")
    err(29, "esquema no soportado")
    err(30, "cabecera inválida")
    err(31, "espacio")
    err(32, "esquema no soportado")
    err(33, "no es HTTP")
    n += 1
    if got.get(("URL", 34)) != h(f"http://127.0.0.1:{puerto}/eco?y=1&z=a+b"):
        errores.append(f"URL 34: salió {got.get(('URL', 34))!r:.100}")
    return n


def main():
    rng = random.Random(23)
    casos = casos_al_azar(rng)
    if sys.version_info >= (3, 12, 4):
        malas = comprobar_referencia(casos)
        if malas:
            print("la copia fija de urllib no coincide con el urllib instalado:", malas[:5])
            return 1
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(casos, f)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/web_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_web_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_web_python: FALLA, el programa terminó con", r.returncode)
            return 1
    got = leer(r.stdout)
    errores = []
    n = 0

    def igual(et, k, esperado, contexto):
        nonlocal n
        n += 1
        g = got.get((et, k))
        if g != esperado:
            errores.append(f"{et} {k} {contexto!r:.90}: salió {g!r:.70} y se esperaba {esperado!r:.70}")

    for k, u in enumerate(casos["urls"]):
        s = dividir(u)
        if s is None:
            igual("ANA", k, "ERR", u)
            continue
        igual("ANA", k, ",".join(h(x) for x in (s.scheme, s.netloc, s.path, s.query, s.fragment)), u)
        igual("HOST", k, h(ref_hostname(s.netloc) or ""), u)
        try:
            p = ref_port(s.netloc)
            p = -1 if p is None else p
        except ValueError:
            p = -2
        igual("PUERTO", k, str(p), u)
        usuario, clave = ref_userinfo(s.netloc)
        igual("USUARIO", k, h(usuario or ""), u)
        igual("CLAVE", k, h(clave or ""), u)
        igual("ARMAR", k, h(ref_unsplit(s)), u)

    for k, (base, ref) in enumerate(casos["joins"]):
        try:
            esperado = ref_join(base, ref)
        except ValueError:
            esperado = ref
        igual("UNIR", k, h(esperado), (base, ref))

    for k, q in enumerate(casos["consultas"]):
        for et, vacios in (("QSV", True), ("QSN", False)):
            esperado = "".join(h(a) + ":" + h(b) + "," for a, b in up.parse_qsl(q, keep_blank_values=vacios))
            igual(et, k, esperado, q)

    for k, ps in enumerate(casos["pares"]):
        igual("QSA", k, h(up.urlencode([tuple(p) for p in ps])), ps)

    with tempfile.TemporaryDirectory() as tmp2:
        r2, fallo, puerto = prueba_cliente(tmp2)
    if r2 is None:
        print(fallo)
        print("test_web_python: FALLA, el cliente no compila")
        return 1
    if r2.returncode != 0 or "ERROR" in r2.stdout:
        print(r2.stdout[-2000:] + r2.stderr)
        print("test_web_python: FALLA, el cliente terminó con", r2.returncode)
        return 1
    n += revisar_cliente(leer(r2.stdout), puerto, errores)

    if errores:
        print("\n".join(errores[:25]))
        print(f"test_web_python: FALLA, {len(errores)} de {n} comparaciones")
        return 1
    print(f"OK: lib/web (URLs) contra urllib.parse: {n} comparaciones (URLs y cliente)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
