"""lib/codigos contra hashlib, hmac, base64, zlib, uuid y urllib.

    python3 pruebas/test_codigos_python.py

Python inventa datos al azar (largos justo en los bordes del relleno de los hashes: 0, 1,
55, 56, 57, 63, 64, 65, 119, 120, 128 bytes y otros de miles) y los escribe en casos.json.
pruebas/codigos_python.scar los procesa con lib/codigos y Python los repite por su cuenta:

  - hexadecimal y base64 (normal y de URL, con y sin relleno), y su ida y vuelta;
  - SHA-256, SHA-1 y MD5 (hashlib), HMAC con los tres con claves cortas, de 64 bytes
    exactos y más largas que el bloque (hmac), CRC-32 y Adler-32 (zlib);
  - decodificación de base64 y hexadecimal buenos y malos (relleno mal puesto, caracteres
    de otro alfabeto, espacios, bits de sobra): se espera la misma decisión que una
    referencia estricta armada con base64 y una comparación canónica;
  - escape de URL (urllib.parse.quote y quote_plus con safe="") con textos en español,
    emojis y símbolos, y su inversa (unquote), incluidos % mal formados y UTF-8 inválido;
  - UTF-8 (encode y decode estricto) y UUID versión 4 (uuid.UUID con version=4).

Los resultados son cadenas exactas: se piden iguales letra por letra. También se mira que
dos UUID al azar tengan el formato de la versión 4 y sean distintos.
"""

import base64
import hashlib
import hmac
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import uuid
import zlib
from urllib.parse import quote, quote_plus, unquote, unquote_plus

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def referencia_b64(t, url):
    """Decodificación estricta y canónica: None si debe fallar."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]*={0,2}" if url else r"[A-Za-z0-9+/]*={0,2}", t):
        return None
    sin = t.rstrip("=")
    quitados = len(t) - len(sin)
    if quitados and (len(sin) + quitados) % 4 != 0:
        return None
    if not url and len(t) % 4 != 0:
        return None
    if len(sin) % 4 == 1:
        return None
    pad = sin + "=" * (-len(sin) % 4)
    try:
        d = base64.urlsafe_b64decode(pad) if url else base64.b64decode(pad, validate=True)
    except Exception:
        return None
    vuelta = base64.urlsafe_b64encode(d).decode() if url else base64.b64encode(d).decode()
    if vuelta.rstrip("=") != sin:
        return None
    return d


def referencia_hex(t):
    if not re.fullmatch(r"([0-9a-fA-F]{2})*", t):
        return None
    return bytes.fromhex(t)


def referencia_url(t, plus):
    if re.search(r"%(?![0-9a-fA-F]{2})", t):
        return None
    try:
        return unquote_plus(t, errors="strict") if plus else unquote(t, errors="strict")
    except UnicodeDecodeError:
        return None


def casos_al_azar(rng):
    def bytes_(n):
        return bytes(rng.randrange(256) for _ in range(n))

    c = dict(datos=[], decodificar=[], textos=[], urls=[], utf8=[], uuid=[])
    largos = [0, 1, 2, 3, 4, 5, 55, 56, 57, 63, 64, 65, 111, 112, 119, 120, 121, 127, 128, 129, 191, 192, 255, 256, 1000, 4096, 10000]
    claves = [0, 1, 8, 20, 32, 63, 64, 65, 100, 200]
    for i, n in enumerate(largos):
        c["datos"].append(dict(x=bytes_(n).hex(), clave=bytes_(claves[i % len(claves)]).hex()))
    # los vectores clásicos: "abc", "" y la clave de RFC 4231
    c["datos"].append(dict(x=b"abc".hex(), clave=b"Jefe".hex()))
    c["datos"].append(dict(x=b"what do ya want for nothing?".hex(), clave=b"Jefe".hex()))
    c["datos"].append(dict(x=(b"a" * 1000).hex(), clave=(b"\xaa" * 131).hex()))
    c["datos"].append(dict(x=bytes(range(256)).hex(), clave=bytes(range(256)).hex()))
    for _ in range(30):
        c["datos"].append(dict(x=bytes_(rng.randint(0, 200)).hex(), clave=bytes_(rng.randint(0, 150)).hex()))

    # decodificar: textos buenos (de verdad codificados) y malos
    for _ in range(40):
        d = bytes_(rng.randint(0, 40))
        c["decodificar"].append(dict(t=base64.b64encode(d).decode()))
        c["decodificar"].append(dict(t=base64.urlsafe_b64encode(d).decode().rstrip("=")))
        c["decodificar"].append(dict(t=d.hex().upper() if rng.random() < 0.5 else d.hex()))
    malos = ["QR==", "QQ=", "QQ", "Q", "QUJD=", "QUJD====", "QU JD", "QUJD\n", "====", "=", "QQ==QQ==", "AA==A", "a+/b",
             "a-_b", "a+_b", "zz", "0", "abc", "abcd", "ab=c", "é", "YQ==", "YWI=", "YWJj", "YQ", "YWI", "gg", "0g", "A", "",
             " 61", "61 62", "6162 ", "G1", "0x61", "+61"]
    for t in malos:
        c["decodificar"].append(dict(t=t))

    textos = ["", "a", "hola mundo", "año 2026 / niño & niña = ¿qué? ¡sí!", "a+b=c&d=e", "100% seguro", "~._-", "ñandú", "日本語のテキスト",
              "emoji 😀 y 🇨🇱", "tab\ty salto\nde línea", "caracteres reservados :/?#[]@!$&'()*+,;=", "ÁÉÍÓÚ áéíóú ü Ü", " espacio duro", "€ 5",
              "😀" * 5, "a" * 300]
    for _ in range(40):
        alfabeto = "abcXYZ 019%&=+/?#ñáé日😀~._-"
        textos.append("".join(rng.choice(alfabeto) for _ in range(rng.randint(0, 25))))
    c["textos"] = textos

    urls = ["", "abc", "a%20b", "a+b", "%41%42%43", "%c3%b1", "%C3%B1", "100%", "%", "%4", "%zz", "%e6%97%a5%e6%9c%ac", "%ff", "%c3", "%c0%80",
            "%ed%a0%80", "%f4%90%80%80", "a%2Bb+c", "ñ%C3%B1", "x%00y", "%25%32%35"]
    c["urls"] = [u for u in urls if "\x00" not in u and "%00" not in u]

    utf8 = ["", "61", "c3b1", "e697a5", "f09f9880", "c3", "c328", "c0af", "e080af", "eda080", "f4908080", "f8888080", "80", "ff", "e282", "f09f98",
            "61c3b162", "efbbbf61", "f48fbfbf", "e0a080", "ed9fbf", "ee8080"]
    for _ in range(40):
        utf8.append(bytes_(rng.randint(1, 8)).hex())
    # sin el byte cero, que SCAR no guarda dentro de un texto
    c["utf8"] = [u for u in utf8 if u == "" or "00" not in [u[i:i + 2] for i in range(0, len(u), 2)]]

    for _ in range(30):
        c["uuid"].append(bytes_(16).hex())
    c["uuid"].append(("00" * 16))
    c["uuid"].append(("ff" * 16))
    c["uuid"].append(bytes_(15).hex())
    c["uuid"].append(bytes_(17).hex())
    return c


def leer(stdout):
    r = {}
    for linea in stdout.splitlines():
        p = linea.split(" ", 2)
        if len(p) == 3 and p[0].isupper() and p[1].isdigit():
            r[(p[0], int(p[1]))] = p[2]
        elif len(p) == 2 and p[0].isupper() and p[1].isdigit():
            r[(p[0], int(p[1]))] = ""
    return r


def ok(b):
    return "ERR" if b is None else "OK:" + (b.hex() if isinstance(b, bytes) else b)


def main():
    rng = random.Random(21)
    casos = casos_al_azar(rng)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "casos.json"), "w", encoding="utf-8") as f:
            json.dump(casos, f)
        binario = os.path.join(tmp, "c")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/codigos_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_codigos_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or "ERROR" in r.stdout:
            print(r.stdout[-2000:] + r.stderr)
            print("test_codigos_python: FALLA, el programa terminó con", r.returncode)
            return 1
    got = leer(r.stdout)
    errores = []
    comparaciones = 0

    def igual(etiqueta, k, esperado):
        nonlocal comparaciones
        comparaciones += 1
        g = got.get((etiqueta, k))
        if g != esperado:
            errores.append(f"{etiqueta} {k}: salió {g!r:.80} y se esperaba {esperado!r:.80}")

    for k, c in enumerate(casos["datos"]):
        x, clave = bytes.fromhex(c["x"]), bytes.fromhex(c["clave"])
        igual("HEX", k, x.hex())
        igual("B64", k, base64.b64encode(x).decode())
        igual("B64U", k, base64.urlsafe_b64encode(x).decode())
        igual("B64UN", k, base64.urlsafe_b64encode(x).decode().rstrip("="))
        igual("SHA256", k, hashlib.sha256(x).hexdigest())
        igual("SHA1", k, hashlib.sha1(x).hexdigest())
        igual("MD5", k, hashlib.md5(x).hexdigest())
        igual("CRC", k, str(zlib.crc32(x)))
        igual("ADLER", k, str(zlib.adler32(x)))
        igual("HMAC256", k, "OK:" + hmac.new(clave, x, hashlib.sha256).hexdigest())
        igual("HMAC1", k, "OK:" + hmac.new(clave, x, hashlib.sha1).hexdigest())
        igual("HMACM", k, "OK:" + hmac.new(clave, x, hashlib.md5).hexdigest())
        igual("VUELTAB64", k, "OK:" + x.hex())
        igual("VUELTAB64U", k, "OK:" + x.hex())
        igual("VUELTAHEX", k, "OK:" + x.hex())

    for k, c in enumerate(casos["decodificar"]):
        t = c["t"]
        igual("DB64", k, ok(referencia_b64(t, False)))
        igual("DB64U", k, ok(referencia_b64(t, True)))
        igual("DHEX", k, ok(referencia_hex(t)))

    for k, t in enumerate(casos["textos"]):
        igual("UTF8", k, t.encode("utf-8").hex())
        igual("URL", k, quote(t, safe=""))
        igual("URLP", k, quote_plus(t, safe=""))
        igual("VUELTAURL", k, "OK:" + t.encode("utf-8").hex())
        igual("VUELTAURLP", k, "OK:" + t.encode("utf-8").hex())
        igual("ACADENA", k, "OK:" + t.encode("utf-8").hex())

    for k, t in enumerate(casos["urls"]):
        igual("UNQ", k, ok(referencia_url(t, False)))
        igual("UNQP", k, ok(referencia_url(t, True)))

    for k, h in enumerate(casos["utf8"]):
        try:
            esperado = "OK:" + bytes.fromhex(h).decode("utf-8")
        except UnicodeDecodeError:
            esperado = "ERR"
        igual("DEC", k, esperado)

    for k, h in enumerate(casos["uuid"]):
        b = bytes.fromhex(h)
        igual("UUID", k, "OK:" + str(uuid.UUID(bytes=b, version=4)) if len(b) == 16 else "ERR")

    u0, u1 = got.get(("UUIDAZAR", 0), ""), got.get(("UUIDAZAR", 1), "")
    patron = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    if not (re.fullmatch(patron, u0) and re.fullmatch(patron, u1)) or u0 == u1:
        errores.append(f"uuid4 al azar: {u0!r} y {u1!r}")

    if errores:
        print("\n".join(errores[:15]))
        print(f"test_codigos_python: FALLA ({len(errores)} diferencias)")
        return 1
    n = sum(len(casos[k]) for k in casos)
    print(f"OK: lib/codigos contra hashlib, hmac, base64, zlib, uuid y urllib: {n} casos, {comparaciones} comparaciones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
