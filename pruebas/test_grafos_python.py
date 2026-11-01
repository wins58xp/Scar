"""lib/grafos contra una referencia en Python.

    python3 pruebas/test_grafos_python.py

pruebas/grafos_python.scar arma 32 grafos al azar (8 de 60 a 160 nodos) (dirigidos y no, algunos sin ciclos, con lazos, aristas
repetidas, pesos enteros que empatan y pesos con decimales) y 40 grillas con paredes al azar (10 de hasta 60 x 40), y escribe lo
que responde lib/grafos. Acá se calcula de otra manera:
  - vecinos y recorridos: listas de adyacencia de Python; el recorrido en profundidad, recursivo;
  - distancias: Bellman-Ford (sin cola de prioridad), y cada camino se revisa arista por arista: tiene que
    existir y sumar justo la distancia;
  - componentes: búsqueda en anchura sobre el grafo sin dirección;
  - orden topológico: que sea una permutación y que toda arista vaya hacia adelante; el ciclo se detecta
    aparte, con colores (blanco, gris, negro);
  - árbol mínimo: el peso total de Prim (desde cada nodo sin visitar), que sea un bosque y que tenga
    n - componentes aristas, y que elija las mismas aristas que un Kruskal con el sorted estable de Python
    (a igual peso, la de número menor);
  - A*: Dijkstra sobre la grilla con las mismas reglas de movimiento; el camino se revisa paso a paso.
Autocomprobación: si se estropea una línea, el comparador lo tiene que notar.
"""

import heapq
import math
import os
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R2 = math.sqrt(2.0)


def cerca(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def ints(xs):
    return [int(x) for x in xs]


class G:
    def __init__(self, n, dirigido):
        self.n, self.dir = n, dirigido
        self.e = []
        self.ady = [[] for _ in range(n)]
        self.cache = {}

    def agregar(self, a, b, w):
        self.e.append((a, b, w))
        self.ady[a].append((b, w))
        if not self.dir and a != b:
            self.ady[b].append((a, w))


def bfs(g, s):
    d = [-1] * g.n
    d[s] = 0
    orden = [s]
    for v in orden:
        for w, _ in g.ady[v]:
            if d[w] < 0:
                d[w] = d[v] + 1
                orden.append(w)
    return d, orden


def dfs(g, s):
    visto, orden = set(), []

    def ir(v):
        visto.add(v)
        orden.append(v)
        for w, _ in g.ady[v]:
            if w not in visto:
                ir(w)
    ir(s)
    return orden


def bellman(g, s):
    if s in g.cache:
        return g.cache[s]
    INF = float("inf")
    d = [INF] * g.n
    d[s] = 0.0
    for _ in range(g.n):
        cambio = False
        for v in range(g.n):
            for w, p in g.ady[v]:
                if d[v] + p < d[w]:
                    d[w] = d[v] + p
                    cambio = True
        if not cambio:
            break
    g.cache[s] = d
    return d


def kruskal(g):
    """Las aristas ordenadas por peso con sorted (estable: a igual peso, por número)."""
    padre = list(range(g.n))

    def raiz(x):
        while padre[x] != x:
            x = padre[x]
        return x
    r = []
    for i in sorted(range(len(g.e)), key=lambda i: g.e[i][2]):
        a, b = raiz(g.e[i][0]), raiz(g.e[i][1])
        if a != b:
            padre[a] = b
            r.append(i)
    return r


def componentes(g):
    und = [[] for _ in range(g.n)]
    for a, b, _ in g.e:
        und[a].append(b)
        und[b].append(a)
    lab = [-1] * g.n
    k = 0
    for i in range(g.n):
        if lab[i] < 0:
            lab[i] = k
            pila = [i]
            while pila:
                v = pila.pop()
                for w in und[v]:
                    if lab[w] < 0:
                        lab[w] = k
                        pila.append(w)
            k += 1
    return k, lab


def tiene_ciclo(g):
    color = [0] * g.n
    sys.setrecursionlimit(10000)

    def ir(v):
        color[v] = 1
        for w, _ in g.ady[v]:
            if color[w] == 1:
                return True
            if color[w] == 0 and ir(w):
                return True
        color[v] = 2
        return False
    return any(color[v] == 0 and ir(v) for v in range(g.n))


def prim_total(g):
    und = [[] for _ in range(g.n)]
    for a, b, w in g.e:
        und[a].append((w, b))
        und[b].append((w, a))
    visto = [False] * g.n
    total = 0.0
    for s in range(g.n):
        if visto[s]:
            continue
        h = [(0.0, s)]
        while h:
            w, v = heapq.heappop(h)
            if visto[v]:
                continue
            visto[v] = True
            total += w
            for p, u in und[v]:
                if not visto[u]:
                    heapq.heappush(h, (p, u))
    return total


def grilla_dijkstra(w, h, muros, x0, y0, x1, y1, diag):
    libre = lambda x, y: 0 <= x < w and 0 <= y < h and muros[y * w + x] == "."
    if not libre(x0, y0) or not libre(x1, y1):
        return None
    dist = {(x0, y0): 0.0}
    pq = [(0.0, x0, y0)]
    hecho = set()
    while pq:
        d, x, y = heapq.heappop(pq)
        if (x, y) in hecho:
            continue
        hecho.add((x, y))
        if (x, y) == (x1, y1):
            return d
        movs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        if diag:
            movs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        for dx, dy in movs:
            nx, ny = x + dx, y + dy
            if not libre(nx, ny):
                continue
            if dx and dy and not (libre(x + dx, y) and libre(x, y + dy)):
                continue
            nd = d + (R2 if dx and dy else 1.0)
            if nd < dist.get((nx, ny), float("inf")) - 1e-12:
                dist[(nx, ny)] = nd
                heapq.heappush(pq, (nd, nx, ny))
    return None


def revisar(lineas):
    errores = []
    cuenta = {"dijkstra": 0, "astar_con_camino": 0, "topo_ok": 0, "topo_err": 0, "grafos": 0}
    g = None
    grilla = None
    for ln in lineas:
        p = ln.split()
        if not p:
            continue
        cab = p[0]
        if cab == "GRAFO":
            g = G(int(p[2]), p[3] == "true")
            gid = int(p[1])
            cuenta["grafos"] += 1
        elif cab == "ARISTA":
            g.agregar(int(p[1]), int(p[2]), float(p[3]))
        elif cab == "VECINOS":
            v = int(p[1])
            if ints(p[2:]) != [w for w, _ in g.ady[v]]:
                errores.append("grafo %d: vecinos de %d" % (gid, v))
        elif cab == "BFS":
            d, _ = bfs(g, int(p[1]))
            if ints(p[2:]) != d:
                errores.append("grafo %d: bfs %s != %s" % (gid, p[2:], d))
        elif cab == "ANCHO":
            _, o = bfs(g, int(p[1]))
            if ints(p[2:]) != o:
                errores.append("grafo %d: recorrido en anchura %s != %s" % (gid, p[2:], o))
        elif cab == "PROFUNDO":
            o = dfs(g, int(p[1]))
            if ints(p[2:]) != o:
                errores.append("grafo %d: recorrido en profundidad %s != %s" % (gid, p[2:], o))
        elif cab == "DIJKSTRA":
            s, v = int(p[1]), int(p[2])
            alc, dist = p[3] == "true", float(p[4])
            camino = ints(p[p.index("|") + 1:])
            ref = bellman(g, s)[v]
            cuenta["dijkstra"] += 1
            if math.isinf(ref):
                if alc or dist != -1.0 or camino:
                    errores.append("grafo %d: %d no se alcanza desde %d" % (gid, v, s))
                continue
            if not alc or not cerca(dist, ref):
                errores.append("grafo %d: distancia %d->%d es %r y dio %r" % (gid, s, v, ref, dist))
                continue
            if not camino or camino[0] != s or camino[-1] != v:
                errores.append("grafo %d: camino %d->%d mal armado: %s" % (gid, s, v, camino))
                continue
            suma = 0.0
            for a, b in zip(camino, camino[1:]):
                pesos = [w for x, w in g.ady[a] if x == b]
                if not pesos:
                    errores.append("grafo %d: el camino usa %d->%d que no existe" % (gid, a, b))
                    break
                suma += min(pesos)
            if not cerca(suma, ref):
                errores.append("grafo %d: el camino %d->%d suma %r y no %r" % (gid, s, v, suma, ref))
        elif cab == "COMPONENTES":
            k, lab = componentes(g)
            if int(p[1]) != k or ints(p[3:]) != lab:
                errores.append("grafo %d: componentes %s != %d %s" % (gid, p[1:], k, lab))
        elif cab == "TOPO":
            if len(p) > 1 and p[1] == "ERR":
                cuenta["topo_err"] += 1
                if g.dir and not tiene_ciclo(g):
                    errores.append("grafo %d: dio error de ciclo sin haber ciclo" % gid)
                if not g.dir and not g.e:
                    errores.append("grafo %d: error de ciclo en un grafo sin aristas" % gid)
                continue
            cuenta["topo_ok"] += 1
            o = ints(p[1:])
            if sorted(o) != list(range(g.n)):
                errores.append("grafo %d: el orden topológico no es una permutación" % gid)
                continue
            pos = {v: i for i, v in enumerate(o)}
            arcos = [(a, b) for a in range(g.n) for b, _ in g.ady[a]]
            if any(pos[a] >= pos[b] for a, b in arcos):
                errores.append("grafo %d: el orden topológico tiene una arista hacia atrás" % gid)
            if g.dir and tiene_ciclo(g):
                errores.append("grafo %d: había ciclo y no dio error" % gid)
        elif cab == "ARBOL":
            total = float(p[1])
            ar = ints(p[p.index("|") + 1:])
            k, _ = componentes(g)
            ref = prim_total(g)
            if not cerca(total, ref, 1e-9) or not cerca(sum(g.e[i][2] for i in ar), ref, 1e-9):
                errores.append("grafo %d: árbol mínimo pesa %r y no %r" % (gid, total, ref))
            if len(ar) != g.n - k:
                errores.append("grafo %d: árbol con %d aristas y no %d" % (gid, len(ar), g.n - k))
            padre = list(range(g.n))

            def raiz(x):
                while padre[x] != x:
                    x = padre[x]
                return x
            for i in ar:
                a, b = raiz(g.e[i][0]), raiz(g.e[i][1])
                if a == b:
                    errores.append("grafo %d: el árbol mínimo tiene un ciclo" % gid)
                    break
                padre[a] = b
            if ar != kruskal(g):
                errores.append("grafo %d: el árbol mínimo no eligió las aristas en el orden documentado" % gid)
            pesos = [g.e[i][2] for i in ar]
            if pesos != sorted(pesos):
                errores.append("grafo %d: las aristas del árbol no salen en orden de peso" % gid)
        elif cab == "GRILLA":
            grilla = (int(p[1]), int(p[2]), p[3])
        elif cab == "ASTAR":
            w, h, muros = grilla
            x0, y0, x1, y1 = ints(p[1:5])
            diag = p[5] == "true"
            cst = float(p[6])
            ruta = ints(p[p.index("|") + 1:])
            ref = grilla_dijkstra(w, h, muros, x0, y0, x1, y1, diag)
            if ref is None:
                if ruta:
                    errores.append("A*: dio camino donde no hay (%s)" % ln[:60])
                continue
            cuenta["astar_con_camino"] += 1
            if not ruta or ruta[0] != y0 * w + x0 or ruta[-1] != y1 * w + x1:
                errores.append("A*: camino mal armado (%s)" % ln[:60])
                continue
            suma = 0.0
            for a, b in zip(ruta, ruta[1:]):
                ax, ay, bx, by = a % w, a // w, b % w, b // w
                dx, dy = bx - ax, by - ay
                ok = max(abs(dx), abs(dy)) == 1 and muros[b] == "." and (diag or dx == 0 or dy == 0)
                if ok and dx and dy:
                    ok = muros[ay * w + bx] == "." and muros[by * w + ax] == "."
                if not ok:
                    errores.append("A*: paso ilegal %d->%d (%s)" % (a, b, ln[:60]))
                    break
                suma += R2 if dx and dy else 1.0
            if not cerca(suma, ref) or not cerca(cst, ref):
                errores.append("A*: costo %r (dice %r) y el óptimo es %r (%s)" % (suma, cst, ref, ln[:60]))
    return errores, cuenta


def main():
    with tempfile.TemporaryDirectory() as tmp:
        binario = os.path.join(tmp, "gr")
        b = subprocess.run([sys.executable, "cli.py", "build", "pruebas/grafos_python.scar", "-o", binario],
                           cwd=RAIZ, capture_output=True, text=True)
        if b.returncode != 0:
            print("test_grafos_python: FALLA al compilar\n" + b.stdout[-800:] + b.stderr[-800:])
            return 1
        r = subprocess.run([binario], cwd=tmp, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("test_grafos_python: FALLA, el programa terminó con", r.returncode)
        return 1
    lineas = r.stdout.strip().splitlines()
    errores, cuenta = revisar(lineas)
    if errores:
        print("test_grafos_python: FALLA\n  " + "\n  ".join(errores[:12]))
        return 1
    if cuenta["astar_con_camino"] < 40 or cuenta["topo_ok"] < 4 or cuenta["topo_err"] < 4:
        print("test_grafos_python: FALLA, poca cobertura", cuenta)
        return 1
    # autocomprobación: se estropea una línea de cada tipo
    for pref in ("BFS ", "PROFUNDO ", "DIJKSTRA ", "COMPONENTES ", "ARBOL ", "ASTAR "):
        malo = list(lineas)
        for i, l in enumerate(malo):
            if l.startswith(pref) and l.split()[-1] not in ("|",) and len(l.split()) > 3:
                q = l.split()
                if pref == "ARBOL ":
                    q[1] = str(float(q[1]) + 0.5)
                elif pref == "DIJKSTRA ":
                    if q[3] != "true" or len(q) < 8:
                        continue
                    q[4] = str(float(q[4]) + 0.5)
                elif pref == "ASTAR ":
                    if q[-1] == "|" or len(q) < 10:
                        continue
                    q = q[:-1]
                else:
                    q[-1] = str(int(q[-1]) + 1)
                malo[i] = " ".join(q)
                break
        if not revisar(malo)[0]:
            print("test_grafos_python: FALLA, la autocomprobación no notó un cambio en", pref)
            return 1
    print("test_grafos_python: OK (%d grafos, %d caminos de Dijkstra, %d A* con camino, %d órdenes "
          "topológicos y %d ciclos)" % (cuenta["grafos"], cuenta["dijkstra"], cuenta["astar_con_camino"],
                                        cuenta["topo_ok"], cuenta["topo_err"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
