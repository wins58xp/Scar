# SCAR

**SCAR** es un lenguaje de programación donde **una tarea y una región de
memoria son la misma cosa**. Todo lo que una tarea crea es suyo, y se libera
solo cuando la tarea termina: sin recolector de basura y sin liberar nada a
mano. Las tareas corren en paralelo y no pueden pisarse, porque ninguna ve la
memoria de otra; lo que tienen que compartir, se lo mandan por canales. Si una
tarea falla, cancela a las que creó y el error sube hasta quien la espera:
nada queda corriendo suelto (concurrencia estructurada).

Las tareas son livianas: el programa reparte todas las que lances entre los
núcleos del procesador, así que puede tener cien mil vivas a la vez.

Cada programa corre de dos maneras, con la misma salida: con un intérprete
(`scar run`) o compilado a C y a un binario nativo (`scar build`).

> **Esto es un alfa (0.2.0).** El lenguaje funciona y está probado, pero
> todavía puede cambiar. Qué trae y qué no: [`SCAR_0.1.0.md`](SCAR_0.1.0.md);
> lo que cambió después: [`CHANGELOG.md`](CHANGELOG.md).

## Instalar

Necesitas Linux, Python 3.12 o más nuevo, y gcc o clang.

```
git clone https://github.com/wins58xp/scar
cd scar
./instalar.sh
scar --version
```

`instalar.sh` revisa que esté todo, dice qué falta si algo falta, y deja el
comando `scar` disponible desde cualquier carpeta. No instala nada del sistema
ni pide contraseña. Para las interfaces gráficas y para HTTPS hacen falta SDL2 y
libcurl (en Debian o Ubuntu: `sudo apt install libsdl2-dev
libcurl4-openssl-dev`, y después `./instalar.sh` otra vez).

## Hola, SCAR

```scar
task saludar(nombre: str) -> str {
    return "hola, " + nombre
}

fn main() {
    let a = spawn saludar("mundo")
    let b = spawn saludar("SCAR")
    print(a.join())
    print(b.join())
}
```

```
scar run hola.scar          # con el intérprete
scar build hola.scar -o hola
./hola                      # compilado
```

```
hola, mundo
hola, SCAR
```

## Aprender

- [**El libro de SCAR**](libro/README.md): el lenguaje desde cero, en 17
  capítulos, de lo básico a las tareas, las interfaces gráficas y la IA.
- [**Ejemplos**](ejemplos/): un programa completo por capítulo.
  `./ejemplos/probar.sh` los corre todos con el intérprete y compilados, y
  compara.
- [**La librería estándar**](libro/B_libreria_estandar.md): las librerías de
  `lib/` (texto, JSON, fechas, matemática, gráficos, red, `gui`, `autodiff`…).

- [**Un motor de juego**](juegos/ENGINE.md): un raycaster estilo DOOM escrito
  en SCAR, paso a paso (`juegos/paso1` a `paso5_mundo.scar`).

## Quiénes lo hacen

- **wins58xp**: el lenguaje, el compilador, el runtime, la librería estándar
  y el libro.
- **[ManiacPC](https://github.com/ManiacPC)**: el motor raycaster de `juegos/` y la compilación en
  Windows con MinGW-w64.

## Licencia

MIT (ver [`LICENSE`](LICENSE)). El código de terceros que incluye, con sus
licencias, está en [`NOTICE.md`](NOTICE.md).

El código es libre, pero el nombre SCAR identifica al proyecto oficial: si
publicas una versión modificada, ponle otro nombre (ver [`MARCA.md`](MARCA.md)).

## El repositorio oficial

El único repositorio oficial de SCAR es
[github.com/wins58xp/scar](https://github.com/wins58xp/scar). Las versiones
oficiales son las que se publican ahí como *releases*.
