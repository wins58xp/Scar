# Cambios

## 0.4.0

Los números de todos los tamaños, los pedazos que se guardan, se devuelven y se
recorren, y tareas más livianas: 100.000 vivas a la vez sin tocar la configuración
del sistema. Todo programa que corría en 0.3.0 sigue corriendo e imprimiendo lo
mismo; lo único que deja de compilar es usar como valor algo que no devuelve nada
(abajo, en Arreglos), que antes daba un binario que no compilaba. La variable para el tamaño de las
pilas ahora es `SCAR_PILA_KB` (antes `SCAR_PILA_TAREA_KB`).

### Números

- **Nuevo: `u8`**, un entero de 0 a 255 para bytes crudos (archivos binarios, red,
  píxeles). Un `Vec<u8>` ocupa un byte por elemento. Un número escrito toma el tipo
  `u8` donde se espera uno (`let b: u8 = 200`, `b + 55`) y tiene que caber; un `u8`
  pasa solo a `i32`, `i64`, `f32` y `f64`, y al revés se pide con `to_u8(x)`.
  Pasarse de 255 o bajar de 0 es un panic, igual en los dos backends; para dar la
  vuelta están `suma_ciclica`, `resta_ciclica` y `mult_ciclica`. Cruza a C como
  `uint8_t`, también un `Vec<u8>` como `uint8_t*` + largo.
- **Nuevo: `u32`**, un entero de 0 a 4.294.967.295 para colores ARGB, hashes, CRC
  y números al azar, en los dos backends y por la FFI (`uint32_t`). Las reglas de
  `u8`: un número escrito toma el tipo, desbordar es un panic, las cíclicas dan la
  vuelta y hay `to_u32(x)`. Un `u8` pasa solo a `u32`, y un `u32` a `i64` y `f64`,
  pero no a `i32` ni a `f32`, donde puede no caber.
- **Nuevo: `u64`**, un entero de 0 a 18.446.744.073.709.551.615 para hashes de
  64 bits, identificadores, tamaños de archivo y generadores como splitmix64, en
  los dos backends y por la FFI (`uint64_t`, también por el worker aislado y en
  una `export fn`). Las reglas de `u8` y `u32`: desbordar es un panic, las
  cíclicas dan la vuelta y hay `to_u64(x)`. Un `u8` y un `u32` pasan solos a
  `u64`; un `u64` no pasa solo a nada (ni a `i64` ni a `f64`), y con un `i32` o un
  `i64` en la misma cuenta es un error que propone convertir uno al otro.
- **Nuevo: `i16`**, un entero de -32.768 a 32.767 para muestras de audio (un WAV
  de 16 bits) y datos de sensores, en los dos backends y por la FFI (`int16_t`,
  también por el worker aislado y en una `export fn`). Las reglas de `i32` en un
  rango más chico: desbordar es un panic, también negar el mínimo, dividirlo por
  -1 o pedir su `abs`; `>>` conserva el signo y hay `to_i16(x)`. Un `u8` pasa solo
  a `i16`, e `i16` pasa solo a `i32`, `i64`, `f32` y `f64`. `Vec<i16>` tiene
  `suma`, `punto`, `acumular` y pedazos. El editor lo colorea como tipo.
- **Nuevo: números en hexadecimal**, `0xFF` y `0xEDB88320`, con cifras 0-9 y
  a-f. Valen lo mismo que el decimal y siguen sus reglas: el tipo sale de dónde
  van, y si no caben es un error. El editor los colorea como números.
- **Un número escrito que no cabe en un `i64` es `u64`** (como uno que no cabe en
  un `i32` es `i64`), y se puede escribir hasta 18446744073709551615 o
  0xFFFFFFFFFFFFFFFF. `let x: i64 = 9223372036854775808` dice que el tipo sería
  `u64`.
- **Las cíclicas aceptan un `u8` con un `u32`** (da `u32`, como una suma).
- **`a.punto(b)` de dos `Vec<u64>`** revisa que la suma quepa en 128 bits, como
  en `i64` (el producto de dos `u64` no cabe en un `__int128` con signo).
- **Nuevo: `f32` cruza a C.** Un `f32` va y vuelve en una `extern fn` como
  `float`, un `Vec<f32>` como `float*` + largo, y también en los campos de un
  struct por valor, en los callbacks y en una `export fn`; con la librería en el
  proceso y en el worker aislado.
- **El editor colorea `u8`, `u32` y `f32` como tipos.**
- **El editor colorea `u64` como tipo.**

### Pedazos y recorrer

- **Nuevo: `for x in v`.** `x` es `v[i]`: un valor si la lista es de números o
  `bool`, y un lugar si es de structs o de listas (`x.campo = 1.0` cambia la
  lista). Mientras dura el bucle, `v` no cambia de largo; el compilador dice qué
  `push` lo impide y dónde. Un elemento struct (`red[i]`, `x`) se presta a una fn
  que no se lo queda.
- **Un pedazo se reasigna:** `let mut p = v[a..b]` y después `p = w[c..d]`. El
  compilador sigue a cuáles listas puede estar mirando.
- **Una fn devuelve un pedazo de un parámetro** (`fn mitad(w: Vec<f32>) ->
  Vec<f32> { return w[0..w.len() / 2] }`): el compilador deduce de cuál, y
  `let p = mitad(w)` es un pedazo de `w`, sin copiar.
- **Un pedazo se guarda adentro de un struct o de un `Vec`**
  (`Capa { w: params[a..b] }`): esa variable sigue las reglas del pedazo. Una fn
  puede devolver algo que guarda pedazos de sus parámetros (una capa, la red
  entera), y lo que devuelve una fn de pedazos se usa directo (`print(mitad(w))`).

### Tipos y tareas

- **Nuevo: `Task<T>` es cualquier tarea que da `T`.** Una lista `Vec<Task<i32>>`
  guarda tareas de distintas clases, y el handle de `spawn` (`Task<i32, a>`) pasa
  solo a `Task<i32>`. `inject_chan` sobre un handle sin nombre revisa al correr si
  la tarea acepta ese canal, y si no, da `Err` (el mismo texto que el intérprete);
  con el nombre, se sigue revisando al compilar. Todo programa que compilaba sigue
  compilando.
- **Arreglo: un struct genérico armado con `vec_new()`, `map_new()`, `None` o `[]`**
  adentro de una fn genérica (`Caja { x: x, items: vec_new() }`) ya no da "T
  inconsistente": esos campos toman su tipo de los demás campos o del tipo anotado
  (`let s: Solo<f32> = Solo { items: vec_new() }`). Y `[]` adentro de una fn
  genérica compila a binario.

### Tareas livianas y memoria

- **Mejora: cada tarea ya no ocupa dos zonas de memoria del sistema.** Las pilas se
  piden de a muchas juntas y sin página de guarda, así que 100.000 tareas vivas
  caben sin subir `vm.max_map_count` (con 2.000 tareas, de unas 4.000 zonas a 65).
  En su lugar, cada función revisa al entrar cuánta pila le queda; en las mediciones
  no se nota. Una recursión sin fin da el mismo panic de siempre, ahora también en
  una librería (`scar build --lib`), donde vuelve como error en vez de tirar al
  programa que la cargó.
- **Cambio: la pila de cada tarea es como la de `main`**, 8 MB (o `ulimit -s` si es
  más), en vez de 1 MB: aguanta recursiones más hondas. Es memoria reservada, no
  usada. La variable para cambiarla es `SCAR_PILA_KB` (antes `SCAR_PILA_TAREA_KB`,
  solo para las tareas) y vale para todas.
- **Mejora: una `extern fn` corre en una pila de C aparte**, así que una librería
  de C que usa mucha pila no se come la de una tarea.

### Archivos y red

- **Nuevo: `.read_u8(n)` en `File` y `Socket`**, que lee bytes directo en un
  `Vec<u8>`; `.read_bytes(n)` sigue igual, con su `Vec<i32>`. `.write_bytes(v)`
  acepta también un `Vec<u8>`.
- **Nuevo: `tcp_listen(0)` y `listener.puerto()`.** Con 0 el sistema elige un
  puerto libre y `.puerto()` dice cuál (-1 si el Listener ya se cerró). Los
  programas de prueba que abrían un servidor y un cliente usaban números fijos,
  y en la CI otra conexión podía tener justo ese número como su puerto de
  salida; ahora usan el 0.
- **Arreglo: un puerto fuera de 0..65535** en `tcp_listen` o `tcp_connect` es un
  `Err` en los dos backends. Antes el intérprete se caía con un error de Python
  y el binario daba la vuelta (70000 escuchaba en 4464).

### Intérprete y herramientas

- **El intérprete es un tercio más rápido** (129,8 s → 87,6 s de CPU en diez
  programas pesados), sin cambiar ninguna salida: resuelve una sola vez por nodo
  lo que antes revisaba en cada evaluación.
- **Las pruebas de GUI ya no se conectan al escritorio.** `SDL_Init` se
  conectaba a D-Bus (los buses de sesión y del sistema) aunque no hubiera
  pantalla; ahora la CI y los scripts de prueba corren sin buses.
- **La tabla de `native/runtime/LEEME.md` se revisa en la CI** (`test_runtime_c`):
  las líneas y las marcas de cada archivo. Estaban desviadas en 53 filas y
  faltaban 5 archivos.

### Arreglos

- **Arreglo: usar como valor algo que no devuelve nada** (`print(v.push(1.0))`,
  `let x = saluda()` con una fn sin `->`, `return saluda()`) ya no pasa el chequeo:
  el compilador dice que eso va solo, en su propia línea. Antes el intérprete
  imprimía `None` y el binario no compilaba.
- **Arreglo: una lista ligada con `Some(f)`** (un `Option` de un `Vec`) era en el
  binario una copia de la cabecera de la lista: si después un `push` la agrandaba,
  se soltaba memoria ya suelta. Ahora `f` es esa misma lista.
- **Arreglo: un número escrito que no entra en un `i32`** (`let a: i32 =
  3000000000`) decía que el valor era `i64` y sugería `to_i32(...)`, que con ese
  número es un panic; ahora dice que no entra y cuál es el rango.
- **El runtime de los sin signo revisa el desborde con `__builtin_add_overflow`**
  y los demás (con `u64` no hay un tipo de C más ancho donde hacer la cuenta).
  `to_i32`, `to_i64`, `to_u8` y `to_u32` de un `u64` lo revisan sin pasar por
  `int64_t`, y los mensajes de panic de los sin signo se imprimen sin signo.
  Para `u8` y `u32` el resultado y los mensajes son los mismos de antes.
- **Arreglo:** el temporal de un argumento de una cíclica o de una conversión
  tomaba el tipo de la firma fija del builtin (lo encontró el fuzzer con `u32`).
- **Los mensajes que nombran tipos** (`suma`, `acumular`, `llenar`, `export fn`,
  conversiones) salen de las familias; varios ya no nombraban `u8`.
- **Arreglo: los mensajes que nombran tipos** (los de los bits y el de un `Vec` que
  cruza a C) salen ahora de las familias de tipos, así que no se quedan viejos.

## 0.3.0

El lenguaje para IA: `f32`, `v[i]`, sumas y productos punto con SIMD, pedazos de
listas sin copiar, y una cinta de derivadas sobre vectores con la que miles de
regiones aprenden a la vez. Todo programa que corría en 0.2.1 sigue corriendo e
imprimiendo lo mismo, con una excepción en `lib/autodiff` (`v_constante`, abajo).

### Números y listas

- **Nuevo: `f32`**, un decimal de 32 bits. Ocupa la mitad que un `f64` y es el
  formato de las GPU y de las librerías de IA. Va en variables, campos de
  struct, datos de un enum, `Vec`, `Map`, `Option`, `Result`, canales, tareas y
  `fn` genéricas con `Numeric`. Un número escrito toma el tipo que se espera
  (`let x: f32 = 0.5`, `x * 2.0`); un `f32` pasa solo a `f64`, y al revés se
  pide con `to_f32(x)`. Cada cuenta se redondea a 32 bits igual en el
  intérprete y en el binario, y `print` muestra las cifras de un `f32` (`0.1`).
  Todavía no cruza a C en una `extern fn`.
- **Nuevo: `v[i]` y `v[i] = x`** sobre un `Vec` de números o `bool`. Leer da el
  elemento sin `Option`, escribir es como `v.set(i, x)`, y un índice que no existe
  es un panic. En el binario es tan rápido como C: un producto punto de un millón
  de `f32` baja de unos 3,1 s con `v.get(i)` a 2,1 s.
- **Nuevo: `v[i]` en un `Vec` de structs o de listas**, como lugar: se leen y
  escriben sus campos de números (`red[i].sesgo = x`), se indexan sus listas
  (`m[i][j]`, matrices como `Vec<Vec<f32>>`) y se llaman los métodos de lista
  (`m[i].len()`, `m[i].push(x)`), sin copiar nada. Sacar el elemento sigue siendo
  con `get` o `replace`.
- **Nuevo: `v.suma()` y `a.punto(b)`** para un `Vec` de `i32`, `i64`, `f64` o `f32`.
  Los decimales se suman en 16 grupos a la vez con un orden que es parte del
  lenguaje, así que el resultado es el mismo bit a bit en el intérprete y en el
  binario, en cualquier máquina; y el binario usa las instrucciones SIMD del
  procesador: un producto punto de un millón de `f32` es unas cinco veces más
  rápido que el mismo loop. Los enteros dan la suma exacta (panic si no cabe).
- **Nuevo: `a.acumular(b, k)`** le suma a cada `a[i]` el `b[i]` por `k`, en su
  lugar. Vale para decimales y para `i32` e `i64` (por ejemplo, para juntar
  histogramas); con enteros cada elemento es exacto, y si no cabe es un panic que
  dice en qué posición.
- **Nuevo: `v.llenar(x)`** deja cada elemento de un `Vec` de números o `bool` en `x`,
  en su lugar, sin cambiar el largo; también sobre un pedazo (`v[a..b].llenar(0.0)`)
  o un lugar (`m[i].llenar(1)`). El binario lo hace de una vez. El valor tiene que
  ser una lectura simple (sin llamadas).

### Pedazos

- **Nuevo: `w[a..b]`, el pedazo de una lista sin copiarlo.** Se lee y se escribe
  como una lista (`p[i]`, `p[i] = x`, `len`, `suma`, `punto`, `acumular`, `llenar`,
  otro pedazo) y lo que se le escribe queda en la lista original:
  `w[f * n..f * n + n].punto(x)` es una fila de una matriz.
- **Un pedazo se pasa a una función** que no le cambia el largo: `relu(w[3..6])`
  cambia esa parte de `w` en su lugar, y una función recursiva se puede pasar sus
  dos mitades. Si la función hace `push` sobre ese parámetro (o se lo pasa a otra
  que lo hace), el compilador lo rechaza y dice dónde.
- **Un pedazo se guarda en una variable**, `let fila = w[a..b]`. Mientras se usa, la
  lista no puede cambiar de largo (el compilador dice qué pedazo lo impide y dónde
  se tomó); después de la última línea que lo nombra, vuelve a ser libre.
- **Pedazos de una lista de structs, de textos o de listas**, `red[a..b]`,
  `m[1..3]`: esas capas o esas filas, no copias. Por el pedazo se lee y se escribe
  (`p[i].campo`, `p[i].pesos.push(x)`, `p.set(i, otra)`), y el compilador lo sigue:
  mientras se usa un pedazo de una fila, esa fila no cambia de largo ni se cambia
  por otra, se la nombre como `m[0]` o como `p[0]`.

### Préstamos

- **Cambio: un `Vec` o un `Map` pasado a una fn se presta**, como un struct: quien
  llama lo sigue teniendo después y ve lo que la fn le cambió (`agrega(v, 10)`).
  Solo se mueve si la fn se queda con él (lo devuelve, lo guarda en otro lado, lo
  manda a una task...), y el error dice por qué. Las task y las fn genéricas siguen
  recibiéndolo movido. Todo programa que compilaba sigue compilando e imprimiendo
  lo mismo. También se puede pasar `m[i]` o `p.lista` a una fn que lo presta.
- **Cambio: una función guardada en una variable también presta** los `Vec` y los
  `Map`, como si la llamaras directo. Por eso no se puede guardar como valor una
  función que se queda con lo que recibe; el error dice cuál parámetro y por qué.
- **Arreglos: cuatro formas de leer memoria ya soltada en el binario** con dos
  argumentos que eran el mismo `Vec`: `g(v, v)` cuando `g` toma un pedazo de un
  parámetro y agranda el otro; `f(m[0][0..2], m)` cuando `f` cambia una fila de
  `m`; `f(m[0], m)` cuando `f` agranda `m`; y `f(m, m)` cuando `f` toma un pedazo de
  una fila del primero y agranda una fila del segundo. Ahora el compilador las
  rechaza y dice por qué (el intérprete no las notaba). Y `f(c.pesos, c.sesgos)`
  ya no se rechaza por error: son dos listas distintas.
- **Arreglo: un argumento que es un campo de otro**, con una fn que reemplaza ese
  campo, podía dar otra salida en el binario (o leer memoria ya soltada si se
  reemplazaba el struct entero). Ahora se rechaza.
- **Arreglos del binario:** no compilaban un pedazo de un `Vec<bool>`,
  `m.push(vec_new())` en un `Vec` de `Vec` (o de `Map`), ni un campo prestado junto
  con un pedazo suyo en la misma llamada (`f(c.pesos, c.pesos[0..2])`).

### IA nativa (`lib/autodiff`)

- **Nuevo: la cinta de vectores**, en `f32` (`cinta_v` y las funciones `v_`): cada
  valor es un `Vec<f32>` entero o una matriz, y cada operación (suma, producto,
  matriz por vector, tanh, sigmoide, relu, error cuadrático...) es un solo nodo.
  Entrenar una red es de 5 a más de 20 veces más rápido que con la cinta de números
  en `f64`, con hasta 6 veces menos memoria.
- **Los pesos de una red viven en la cinta**: `v_parametro` los declara una sola
  vez, `v_reiniciar` bota lo calculado entre un paso y otro sin tocarlos, y
  `v_aprender` los actualiza en su lugar. Da exactamente lo mismo que volver a
  cargarlos en cada paso (eso sigue funcionando), sin copiarlos.
- **La cinta no arma el gradiente de una matriz que se usa una sola vez**: lo
  calcula fila por fila con las mismas cuentas, y **reusa sus vectores de un paso a
  otro**. Da exactamente lo mismo, con menos memoria y menos recorridos.
- **Cambia:** `v_constante` ya no lleva derivada (`v_gradiente` de una constante da
  una lista vacía); para la derivada respecto de una entrada se usa `v_variable`.
- **Un cerebro de miles de regiones** (capítulo 18 del libro): cada región es una
  tarea con su red y su cinta, alimentada por canales con tope. En un Ryzen de 12
  hilos, con 1.000 regiones de 256 x 256, cada muestra cuesta unos 8 µs y cada
  región 0,40 MB; con tareas livianas, 100.000 regiones chicas vivas pesan 1,3 GB.

### Memoria

- **Más rápido:** un struct que se suelta deja su bloque en una lista del hilo y
  el próximo struct del mismo tamaño lo reusa, sin pedirle memoria al sistema
  (los textos ya lo hacían). La lista tiene un tope y lo que sobra vuelve al
  sistema, así que la memoria de un programa que corre mucho no sube. Cada
  struct se sigue soltando en el mismo momento: no hay recolector de basura.
- **Más rápido y más parejo con tareas:** los buffers de los `Vec` también salen
  de esas listas, en vez de ir a `malloc`/`realloc`/`free` del sistema. En un
  programa con dos regiones que aprenden eran unos 23 millones de llamadas al
  sistema por corrida, y la pelea entre hilos dentro de `malloc` lo hacía tardar
  el doble o el triple en algunas corridas; ahora son unas 11.000 y tarda siempre
  lo mismo.
- **Más rápido cuando una tarea arma datos y otra los suelta:** lo que una lista
  del hilo no puede guardar pasa en lotes a un depósito común, y otro hilo lo
  toma de ahí en vez de pedirle memoria al sistema. Con un productor y un
  consumidor en hilos distintos eran 8 millones de llamadas al sistema por
  corrida; ahora son unas 1.900, y la memoria sigue acotada.

## 0.2.1

Solo arreglos; el lenguaje no cambia: todo programa que corría en 0.2.0 corre
igual.

- **Arreglo: un falso deadlock con tareas livianas.** Con dos trabajadores, un
  programa que se pasa valores paso a paso entre tareas podía terminar en
  "deadlock" sin estarlo (cerca de 1 de cada 8 corridas): el detector no veía una
  tarea que otro trabajador acababa de tomar para correrla.
- **Arreglo: con `SCAR_TAREAS=hilos`, miles de tareas esperando ya no ahogan al
  sistema.** Cada una se despertaba cada 250 ms para mirar si había un deadlock:
  4.000 tareas esperando gastaban cerca de medio segundo de procesador por cada
  segundo sin hacer nada, y con 10.000 un programa que ahora termina en unos 3 s
  tardaba de 7 s a más de un minuto (medido en una máquina de 2 núcleos). Ahora
  vigila una sola y las demás duermen hasta que pasa algo; un deadlock con miles
  de tareas se sigue informando en cerca de un segundo.

## 0.2.0

Tareas livianas. El lenguaje no cambia: los programas se escriben igual. Lo
único que puede notarse es el formato de `print` (ver el último punto).

- **Tareas livianas:** muchas tareas en pocos hilos, uno por núcleo, como en
  Go o Erlang. Cada `spawn` deja de ser un hilo del sistema. Los programas se
  escriben igual, y cancelación, panics, deadlocks, `sleep`, archivos, red y
  las `extern fn` se comportan igual; una tarea pegada en C no frena a las
  demás, y un deadlock se detecta al instante. Medido en un Ryzen de 12
  hilos contra un hilo por tarea: pasar un mensaje por una cadena de tareas
  30 a 37 veces más rápido, crear tareas 20 veces, 8 veces menos memoria
  por tarea viva (9,8 kB contra 78,9), 100.000 tareas a la vez con 86 MB en
  vez de 7,3 GB, y los canales con buffer 3 a 4 veces más rápidos; una ida
  y vuelta entre dos tareas queda igual.
  `SCAR_TAREAS=hilos` vuelve a un hilo por tarea.
- **Arreglo:** cuando el sistema no da más hilos (o, con tareas livianas, no
  hay memoria para la pila), `spawn` es un panic con la causa en vez de un
  falso "probable deadlock" a los 8 s.
- **Nuevo:** `scar build` en Windows con MinGW-w64 (sale un `.exe`, con los
  `.dll` de las librerías de SCAR al lado). `python construir_nativas.py`
  compila las librerías nativas en Windows y en Linux. En Linux nada cambia.
  En Windows cada tarea sigue siendo un hilo. Aporte de [ManiacPC](https://github.com/ManiacPC).
- **Nuevo:** un motor raycaster estilo DOOM escrito en SCAR, en `juegos/`
  (`paso1` a `paso5_mundo.scar`, explicado en `juegos/ENGINE.md`): paredes con
  textura, antorchas, cielo con ciclo de día y noche, WASD y ratón. Aporte de
  [ManiacPC](https://github.com/ManiacPC).

- **Arreglo:** una fn que devuelve el dato de un `match` sobre un `Result`
  (`Ok(r) => { return r }`) perdía memoria en el binario cuando se la llamaba con
  valores recién armados (`hmac_sha256(t("k"), t("m"))` en `lib/codigos`).
- **Arreglo:** `print(Ok(q)?)` perdía `q` en el binario, y `let r = Ok(q)?` daba
  un error de "se movió" que no correspondía.
- **Arreglo:** una `extern fn` con el nombre de una función de la libc y otra
  firma (`extern "C" fn strlen(s: str) -> i64`) no compilaba a binario.
- **Cambio de salida:** `print` muestra lo que va dentro de una lista, un mapa,
  un `Some`/`Ok`/`Err` o un struct tal como se escribe en SCAR: `[true, false]` en
  vez de `[True, False]`, y los textos siempre entre comillas dobles
  (`Some("hola")`, `{"a": 1}`, `P(nombre="Ana")`) en vez de las simples de Python.
  Un programa que compara su salida con texto guardado puede necesitar ajustarse.

## 0.1.1

Arreglos y velocidad; el lenguaje no cambia: todo programa que corría en 0.1.0
corre igual.

- **Arreglo:** `scar check` aceptaba tipos que no existen (`Vec<NoExiste>`,
  `Option<Optoin<i32>>`): el intérprete los corría y `scar build` recién fallaba
  al generar C. Ahora es un error de tipo, que sugiere el nombre parecido
  (`¿quisiste decir 'Option'?`).
- **Rendimiento: canales mucho más rápidos.** Una tarea que espera un mensaje
  (o lugar en un canal lleno) prueba unos microsegundos si llega antes de
  dormirse, porque dormir y despertar un hilo cuesta mucho más; mientras
  espera mira un aviso del canal, sin tomar su candado, para no estorbar al
  que manda. Un canal de números, textos o listas además reusa los nodos de
  su cola en vez de pedir memoria por cada mensaje. Medido en un procesador
  de 12 núcleos, contra 0.1.0 y en la misma sesión:

  | prueba | 0.1.0 | 0.1.1 |
  |---|---|---|
  | ida y vuelta entre dos tareas | 8.1 µs | 0.26 µs (31 veces más rápido) |
  | flujo por un canal acotado | 6.8 M msj/s | 11.6 M msj/s (+71 %) |
  | flujo por un canal sin límite | 7.0 M msj/s | 8.9 M msj/s (+28 %) |
  | varias tareas mandando a una | 0.60 M msj/s | 0.86 M msj/s (+43 %) |
  | un grupo de trabajadores | 0.57 M msj/s | 0.74 M msj/s (+29 %) |
  | anillo de tareas | 4.8 µs por salto | igual |
  | mensajes con texto (structs) | 2.69 M msj/s | 2.61 M msj/s (−3 %) |

  El −3 % es el precio de esperar despierto: cuando el que manda es el lento,
  las dos tareas están en núcleos distintos y nadie espera respuesta, el
  receptor se lleva cada mensaje apenas llega en vez de juntar varios. En el
  mismo núcleo esa prueba sale 70 % más rápida. El giro se adapta solo en cada
  canal, no gira si hay más tareas que núcleos, y se ajusta o apaga con la
  variable de entorno `SCAR_GIRO` (máximo en microsegundos; `0` lo apaga y
  vuelve casi a la conducta de 0.1.0).
- **Pruebas:** `./pruebas/correr.sh` también revisa 44 programas que rompen
  una regla del lenguaje (mover dos veces, compartir memoria entre tareas,
  tipos que no existen...): `scar check` tiene que rechazarlos, con el mensaje
  correcto.

## 0.1.0 — alfa

Primera versión pública.

- El lenguaje: tipos `i32`, `i64`, `f64`, `bool`, `str`; `struct`, `enum` y
  `match`; `Option`, `Result` y el operador `?`; `Vec`, `Map` y literales
  `[a, b, c]`; `if` como expresión, `while`, `for`, `break`, `continue`;
  genéricos (`struct<T>`, `fn<T>`) y funciones como valor; módulos con `use`.
- Tareas y regiones: `task`, `spawn`, `join`, canales `Chan<T>`, cancelación y
  panics en cascada, detección de deadlocks; una tarea es dueña de su memoria y
  la libera al terminar, sin recolector de basura.
- Dos maneras de correr, con la misma salida: `scar run` (intérprete) y
  `scar build` (compila a C y a un binario nativo).
- Interoperar con C (`extern`) y exportar una librería que se llama desde C o
  Python (`scar build --lib`).
- Herramientas: `scar fmt`, `scar check` y un servidor LSP para editores.
- La librería estándar (`lib/`): 35 librerías, entre ellas texto, colecciones,
  JSON, CSV, fechas, matemática y álgebra, señales, gráficos, interfaces
  gráficas (`gui`, con SDL2), web y HTTPS, derivadas automáticas (`autodiff`) y
  redes neuronales.
- El libro de SCAR (`libro/`), con 17 capítulos y un programa por capítulo en
  `ejemplos/`.

Qué incluye y qué no, en detalle: `SCAR_0.1.0.md`.
