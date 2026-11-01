"""lib/fecha contra datetime y zoneinfo de Python.

    python3 pruebas/test_fecha_python.py

Compila y corre pruebas/fecha_python.scar y compara:
- 400 días al azar del año 1 al 9999: la fecha, el día de la semana, el día
  del año y la vuelta (date.fromordinal);
- 300 instantes al azar (unos 2000 años a cada lado de 1970): los campos en
  UTC, la vuelta, ISO 8601 y formato (strftime, con los nombres en español);
- Chile continental, Isla de Pascua, Magallanes, un desfase fijo y UTC en 300
  instantes al azar entre 2019 y 2040 y cada 3,5 horas durante los 16 días
  alrededor de cada cambio de hora de esos años (con zoneinfo:
  America/Santiago, Pacific/Easter, America/Punta_Arenas): la fecha local, el
  desfase, ISO con desfase y la vuelta a UTC;
- fechas locales alrededor de cada cambio, incluidas las que no existen y las
  que pasan dos veces, a UTC (zoneinfo con fold=0);
- 200 textos ISO 8601 de seis formas y 9 mal escritos;
- sumar meses (el día se queda en el último del mes si no existe).

Sin la base de zonas del sistema (zoneinfo), se omite la parte de zonas.
"""

import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
EPOCA = datetime(1970, 1, 1, tzinfo=timezone.utc)


def utc_de(s):
    return EPOCA + timedelta(seconds=s)


def main():
    try:
        from zoneinfo import ZoneInfo
        zonas = [ZoneInfo("America/Santiago"), ZoneInfo("Pacific/Easter"), ZoneInfo("America/Punta_Arenas"),
                 timezone(timedelta(minutes=330)), timezone.utc]
    except Exception:
        zonas = None

    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "f")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/fecha_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("test_fecha_python: FALLA, no compila")
            return 1
        r = subprocess.run([binario], cwd=RAIZ, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            print("test_fecha_python: FALLA, el programa terminó con", r.returncode)
            return 1

    malas, n = [], 0
    cuenta = {}

    def igual(etq, a, b):
        nonlocal n
        n += 1
        if a != b:
            malas.append(f"{etq}: SCAR {a!r}, Python {b!r}")

    for linea in r.stdout.splitlines():
        p = linea.split(" ")
        etq = p[0]
        cuenta[etq] = cuenta.get(etq, 0) + 1
        if etq == "DIA":
            d = int(p[1])
            esp = date.fromordinal(d + 719163)
            igual(f"DIA {d}", tuple(int(x) for x in p[2:5]), (esp.year, esp.month, esp.day))
            igual(f"DIA {d} semana", int(p[8]), (esp.weekday() + 1) % 7)
            igual(f"DIA {d} del año", int(p[9]), esp.timetuple().tm_yday)
            igual(f"DIA {d} vuelta", int(p[10]), d)
        elif etq == "SEG":
            s = int(p[1])
            esp = utc_de(s)
            igual(f"SEG {s}", tuple(int(x) for x in p[2:8]),
                  (esp.year, esp.month, esp.day, esp.hour, esp.minute, esp.second))
            igual(f"SEG {s} vuelta", int(p[8]), s)
            igual(f"SEG {s} iso", p[9], f"{esp.year:04d}-{esp.month:02d}-{esp.day:02d}T{esp:%H:%M:%S}Z")
        elif etq == "FMT":
            s = int(p[1])
            esp = utc_de(s)
            dia, mes = DIAS[esp.weekday()], MESES[esp.month - 1]
            quiero = (f"{dia}|{dia[:3]}|{esp.day:02d}|{mes}|{mes[:3]}|{esp.year:04d}|{esp.month:02d}|"
                      f"{esp:%H:%M:%S}|{esp.timetuple().tm_yday:03d}|%")
            igual(f"FMT {s}", " ".join(p[2:]), quiero)
        elif etq == "LOC" and zonas is not None:
            s, z = int(p[1]), int(p[2])
            esp = utc_de(s).astimezone(zonas[z])
            igual(f"LOC {s} zona {z}", tuple(int(x) for x in p[3:9]),
                  (esp.year, esp.month, esp.day, esp.hour, esp.minute, esp.second))
            desf = int(esp.utcoffset().total_seconds() // 60)
            igual(f"LOC {s} zona {z} desfase", int(p[9]), desf)
            signo = "-" if desf < 0 else "+"
            igual(f"LOC {s} zona {z} iso", p[10],
                  f"{esp:%Y-%m-%dT%H:%M:%S}{signo}{abs(desf) // 60:02d}:{abs(desf) % 60:02d}")
            # la vuelta a UTC con fold=0: en la hora que pasa dos veces, la primera
            ida = datetime(esp.year, esp.month, esp.day, esp.hour, esp.minute, esp.second, tzinfo=zonas[z], fold=0)
            igual(f"LOC {s} zona {z} vuelta", int(p[11]), int(ida.timestamp()))
        elif etq == "INST" and zonas is not None:
            a, m, d, h, mi, se = (int(x) for x in p[1:7])
            for k, zona in enumerate(zonas[:2]):
                esp = int(datetime(a, m, d, h, mi, se, tzinfo=zona, fold=0).timestamp())
                igual(f"INST {a}-{m}-{d} {h}:{mi} zona {k}", int(p[7 + k]), esp)
        elif etq == "ISO":
            forma, off = int(p[1]), int(p[2])
            a, m, d, h, mi, se = (int(x) for x in p[3:9])
            if forma == 0:
                h = mi = se = 0
                off = 0
            elif forma == 1:
                se = 0
                off = 0
            elif forma == 2:
                off = 0
            elif forma == 5:
                off = (abs(off) // 60) * 60 * (-1 if off < 0 else 1)
            esp = int((datetime(a, m, d, h, mi, se, tzinfo=timezone.utc) - timedelta(minutes=off)).timestamp())
            igual(f"ISO {' '.join(p[10:])}", p[9], str(esp))
            texto = " ".join(p[10:])
            if sys.version_info >= (3, 11):
                igual(f"ISO {texto} fromisoformat", int(p[9]),
                      int(datetime.fromisoformat(texto).replace(tzinfo=datetime.fromisoformat(texto).tzinfo
                                                                or timezone.utc).timestamp()))
        elif etq == "ISOMAL":
            igual(f"ISOMAL {p[1]}", p[2], "true")
        elif etq == "MES":
            a, m, d = (int(x) for x in p[1:4])
            k = int(p[7])
            total = a * 12 + (m - 1) + k
            na, nm = total // 12, total % 12 + 1
            ultimo = (date(na + (nm == 12), nm % 12 + 1, 1) - timedelta(days=1)).day
            igual(f"MES {a}-{m}-{d} + {k}", tuple(int(x) for x in p[8:11]), (na, nm, min(d, ultimo)))

    faltan = [e for e in ("DIA", "SEG", "FMT", "LOC", "INST", "ISO", "ISOMAL", "MES") if cuenta.get(e, 0) == 0]
    if malas or faltan:
        for m in malas[:15]:
            print("  ", m)
        print(f"test_fecha_python: FALLA, {len(malas)} diferencias en {n} comparaciones (faltan: {faltan})")
        return 1
    extra = "" if zonas is not None else " (sin zoneinfo: sin la parte de zonas)"
    print(f"OK: fecha igual a datetime/zoneinfo en {n} comparaciones (calendario del año 1 al 9999, UTC, "
          f"Chile, Pascua y Magallanes de 2019 a 2040 con cada cambio de hora, ISO 8601, formato, meses){extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
