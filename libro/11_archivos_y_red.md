# 11. Archivos y red

Todo lo que habla con el mundo de afuera puede fallar: un archivo que no
existe, una conexión rechazada, un servidor que no contesta. Por eso en SCAR
estas operaciones devuelven `Result`, y el operador `?` (capítulo 5) es tu
mejor amigo en este capítulo.

## 11.1 Archivos

`file_open(ruta, modo)` abre un archivo. El modo es `"r"` (leer), `"w"`
(escribir; si ya existía, lo vacía) o `"a"` (agregar al final):

```scar
fn guardar_y_leer(ruta: str) -> Result<str> {
    let f = file_open(ruta, "w")?
    f.write("primera línea\n")?
    f.write("segunda línea\n")?
    f.close()

    let g = file_open(ruta, "a")?
    g.write("tercera línea\n")?
    g.close()

    let h = file_open(ruta, "r")?
    let contenido = h.read_all()?
    h.close()
    return Ok(contenido)
}

fn main() {
    match guardar_y_leer("/tmp/scar_libro_11.txt") {
        Ok(texto) => print(texto)
        Err(e) => print("error:", e)
    }
}
```

```
primera línea
segunda línea
tercera línea

```

Un `File` se usa con métodos: `.write(texto)`, `.read_all()` (todo el
contenido como texto), `.read_bytes(n)` y `.write_bytes(v)` (bytes crudos, como
`Vec<i32>` de 0 a 255) y `.close()`.

Los errores del sistema no detienen el programa: llegan como `Err`.

```scar
fn main() {
    match file_open("/tmp/no_existe_de_verdad.txt", "r") {
        Ok(f) => print("abierto")
        Err(e) => print(e)
    }
}
```

```
no se pudo abrir '/tmp/no_existe_de_verdad.txt': No such file or directory
```

La entrada estándar es un archivo más: `file_open("/dev/stdin", "r")` lee lo
que le llega al programa por la terminal o por una tubería
(`echo hola | scar run programa.scar`). Para escribir en la salida de errores, `file_open("/dev/stderr",
"a")`: con `"a"`, porque `"w"` vaciaría el archivo si la salida está redirigida
a uno.

## 11.2 Leer línea por línea

`read_all` da todo el texto; con `texto.lineas` (capítulo 10) se parte en
líneas, y con `texto.dividir` cada línea en sus partes:

```scar
use "texto"

fn mostrar(linea: str) {
    let partes = texto.dividir(linea, " ")
    match partes.get(0) {
        Some(nombre) => {
            match partes.get(1) {
                Some(nota) => print(nombre, "sacó", nota)
                None => print(nombre, "no tiene nota")
            }
        }
        None => {}
    }
}

fn main() -> Result<i32> {
    let f = file_open("/tmp/scar_notas.txt", "w")?
    f.write("Ana 6.5\nLuis 5.0\nEva\n")?
    f.close()

    let g = file_open("/tmp/scar_notas.txt", "r")?
    let lineas = texto.lineas(g.read_all()?)
    g.close()
    for i in 0..lineas.len() {
        match lineas.get(i) {
            Some(l) => mostrar(l)
            None => {}
        }
    }
    return Ok(0)
}
```

```
Ana sacó 6.5
Luis sacó 5.0
Eva no tiene nota
```

## 11.3 Red: TCP

`tcp_listen(puerto)` abre un puerto para recibir conexiones, `listener.accept()`
espera una, y `tcp_connect(host, puerto)` se conecta a un servidor. Del otro
lado de cada conexión hay un `Socket`, con `.write(texto)`, `.read()` y
`.close()`:

```scar
fn conversar(puerto: i32) -> Result<str> {
    let servidor = tcp_listen(puerto)?
    let cliente = tcp_connect("127.0.0.1", puerto)?
    let conexion = servidor.accept()?

    cliente.write("hola, servidor")?
    let pedido = conexion.read()?
    conexion.write("hola, cliente")?
    let respuesta = cliente.read()?

    cliente.close()
    conexion.close()
    servidor.close()
    return Ok(pedido + " / " + respuesta)
}

fn main() {
    match conversar(19191) {
        Ok(t) => print(t)
        Err(e) => print("error:", e)
    }
    match tcp_connect("127.0.0.1", 19193) {
        Ok(s) => print("conectado")
        Err(e) => print(e)
    }
}
```

```
hola, servidor / hola, cliente
no se pudo conectar a 127.0.0.1:19193: Connection refused
```

En un programa de verdad, el servidor y los clientes corren en tareas
distintas (capítulo 9): una tarea por conexión es la forma natural de
atender a varios a la vez.

## 11.4 Nada se queda esperando para siempre

Leer de una conexión o esperar un cliente puede bloquearse indefinidamente si
del otro lado nadie hace nada. SCAR no deja que eso cuelgue el programa:

- `accept`, `read` y `read_pipe` tienen un **límite de tiempo** propio (7,5
  segundos). Si se cumple sin datos, la tarea termina con un panic que dice
  qué estaba esperando.
- Mientras espera, una tarea **se puede cancelar** (capítulo 9): si quien la
  lanzó termina, la espera se corta.

## 11.5 HTTP y HTTPS

Para hablar con servidores web están las librerías `web` (HTTP) y `https`
(también `https://`, con libcurl). Por ejemplo, con `https`:

```scar-nocheck
use "https"

fn main() {
    match https.obtener("https://example.com") {
        Ok(r) => print(r.codigo, r.motivo)
        Err(e) => print("error:", e)
    }
}
```

(No se prueba con el libro porque necesita conexión a internet y libcurl.)
El apéndice B describe cómo mandar cabeceras, formularios y JSON.

## 11.6 Ejercicios

1. Escribe un programa que cuente las líneas y las palabras de un archivo.
2. Lee números de un archivo, uno por línea, y escribe en otro su suma y su
   promedio.
3. Cambia el ejemplo del capítulo para que el servidor atienda a dos
   clientes, cada uno en su propia tarea.
4. ¿Qué pasa si haces `accept()` y nadie se conecta? Pruébalo.

El programa de este capítulo está en `ejemplos/11_archivos_y_red.scar`.
