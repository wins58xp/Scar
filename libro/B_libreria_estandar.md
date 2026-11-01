# Apéndice B. La librería estándar

Las librerías de `lib/` vienen con SCAR y se traen con `use` (capítulo 10):
`use "texto"` y después `texto.dividir(...)`. Están escritas en SCAR, así que
corren igual en el intérprete y en el binario.

Esta lista sale del código: cada función pública de cada librería, con su firma
real y el comentario que tiene encima en el `.scar`. El comentario del principio
de cada archivo de `lib/` cuenta además cómo usarla, con ejemplos.

35 librerías, 1105 funciones públicas: [`algebra`](#algebra) (24), [`animacion`](#animacion) (27), [`ansi`](#ansi) (27), [`audio`](#audio) (21), [`autodiff`](#autodiff) (20), [`buffer`](#buffer) (45), [`codigos`](#codigos) (34), [`colecciones`](#colecciones) (56), [`colores`](#colores) (58), [`config`](#config) (23), [`csv`](#csv) (20), [`editor`](#editor) (22), [`estadistica`](#estadistica) (41), [`fecha`](#fecha) (29), [`fisica`](#fisica) (20), [`grafico`](#grafico) (30), [`grafos`](#grafos) (29), [`gui`](#gui) (97), [`https`](#https) (10), [`imagen`](#imagen) (11), [`json`](#json) (69), [`juego`](#juego) (51), [`lienzo`](#lienzo) (37), [`mate`](#mate) (78), [`motor3d`](#motor3d) (17), [`neuronalgames`](#neuronalgames) (34), [`pantalla`](#pantalla) (2), [`parlante`](#parlante) (5), [`patron`](#patron) (31), [`prueba`](#prueba) (12), [`senal`](#senal) (33), [`tablero`](#tablero) (24), [`texto`](#texto) (31), [`web`](#web) (28), [`zlib`](#zlib) (9).

## `algebra`

matrices de cualquier tamaño y álgebra lineal (use "algebra").

Tipos: `algebra.Matriz`, `algebra.Propios`.

- `algebra.matriz(filas: i32, columnas: i32) -> Matriz`
- `algebra.identidad(n: i32) -> Matriz`
- `algebra.filas(m: Matriz) -> i32`
- `algebra.columnas(m: Matriz) -> i32`
- `algebra.get(m: Matriz, i: i32, j: i32) -> f64` — get(m, i, j) -> f64: el número de la fila i y la columna j (desde 0).
- `algebra.poner(m: Matriz, i: i32, j: i32, x: f64)`
- `algebra.copia(m: Matriz) -> Matriz`
- `algebra.desde_texto(s: str) -> Result<Matriz>` — desde_texto(s) -> Result<Matriz>: "1 2 3; 4 5 6" es una matriz de 2 x 3 (los números se separan con espacios o comas, las filas con ';' o con saltos de línea). Todas las filas tienen que tener la misma cantidad de números.
- `algebra.a_texto_mat(m: Matriz, n: i32) -> str` — a_texto_mat(m, decimales) -> str: "1.00 2.00; 3.00 4.00".
- `algebra.decimales(x: f64, n: i32) -> str` — decimales(x, n) -> str: x con n decimales redondeados ("3.14"), para mostrar un número suelto.
- `algebra.suma(a: Matriz, b: Matriz) -> Matriz`
- `algebra.resta(a: Matriz, b: Matriz) -> Matriz`
- `algebra.escala(a: Matriz, k: f64) -> Matriz`
- `algebra.producto(a: Matriz, b: Matriz) -> Matriz` — producto(a, b): a * b (a de m x n, b de n x p).
- `algebra.transpuesta(a: Matriz) -> Matriz`
- `algebra.traza(a: Matriz) -> f64`
- `algebra.norma(a: Matriz) -> f64` — norma de Frobenius: raíz de la suma de los cuadrados (para un vector, su largo)
- `algebra.iguales_casi(a: Matriz, b: Matriz, tol: f64) -> bool` — iguales_casi(a, b, tol) -> bool: misma forma y cada número a menos de tol del otro.
- `algebra.determinante(a: Matriz) -> f64` — determinante(a) -> f64 (0 si la matriz es singular según el umbral). Panic si no es cuadrada.
- `algebra.resolver(a: Matriz, b: Matriz) -> Result<Matriz>` — resolver(a, b) -> Result<Matriz>: el x con a * x = b (a cuadrada de n x n, b de n x k). Err si a es singular.
- `algebra.inversa(a: Matriz) -> Result<Matriz>` — inversa(a) -> Result<Matriz>. Err si a es singular.
- `algebra.rango(a: Matriz) -> i32` — rango(a) -> i32: cuántas filas (o columnas) independientes tiene.
- `algebra.minimos_cuadrados(a: Matriz, b: Matriz) -> Result<Matriz>` — minimos_cuadrados(a, b) -> Result<Matriz>: el x (n x k) que minimiza |a x - b| con a de m x n, m >= n. Err si hay menos ecuaciones que incógnitas o si las columnas de a no son independientes.
- `algebra.propios(a: Matriz) -> Result<Propios>` — propios(a) -> Result<Propios>: los valores propios de menor a mayor (una columna de n) y los vectores propios como columnas de una matriz de n x n, cada uno de largo 1 y con su número de mayor valor absoluto positivo (así el resultado no depende de un signo arbitrario). Err si a no es simétrica.

## `animacion`

valores que cambian con suavidad en el tiempo (use "animacion").

Tipos: `animacion.Tween`.

- `animacion.lineal() -> i32`
- `animacion.entrada_cuad() -> i32`
- `animacion.salida_cuad() -> i32`
- `animacion.entrada_salida_cuad() -> i32`
- `animacion.entrada_cubica() -> i32`
- `animacion.salida_cubica() -> i32`
- `animacion.entrada_salida_cubica() -> i32`
- `animacion.entrada_cuarta() -> i32`
- `animacion.salida_cuarta() -> i32`
- `animacion.entrada_salida_cuarta() -> i32`
- `animacion.suave() -> i32`
- `animacion.mas_suave() -> i32`
- `animacion.rebote() -> i32`
- `animacion.entrada_rebote() -> i32`
- `animacion.entrada_retroceso() -> i32`
- `animacion.salida_retroceso() -> i32`
- `animacion.entrada_salida_retroceso() -> i32`
- `animacion.suave_en(t0: f64, curva: i32) -> f64` — suave_en(t, curva) -> f64: la curva evaluada en t (t se recorta a [0, 1]).
- `animacion.entre(a: f64, b: f64, t: f64, curva: i32) -> f64` — entre(a, b, t, curva) -> f64: de a (t = 0) a b (t = 1) por la curva.
- `animacion.tween(desde: f64, hasta: f64, duracion: i32, curva: i32) -> Tween`
- `animacion.repetir(tw: Tween, si: bool)` — repetir(tw, si): al llegar al final empieza de nuevo.
- `animacion.ida_vuelta(tw: Tween, si: bool)` — ida_vuelta(tw, si): al llegar al final vuelve hacia atrás, y así sigue.
- `animacion.reiniciar(tw: Tween)`
- `animacion.avanzar(tw: Tween, dt: i32)` — avanzar(tw, dt_ms): pasó ese tiempo. Un dt negativo se toma como 0.
- `animacion.progreso(tw: Tween) -> f64` — progreso(tw) -> f64: cuánto del recorrido va, de 0 a 1 (ya con la ida y vuelta, sin la curva).
- `animacion.valor(tw: Tween) -> f64` — valor(tw) -> f64: el valor de ahora.
- `animacion.terminado(tw: Tween) -> bool` — terminado(tw) -> bool: llegó al final (los que repiten no terminan nunca).

## `ansi`

color y estilos en la terminal con secuencias ANSI (use "ansi").

- `ansi.esc() -> str` — El carácter de escape (27).
- `ansi.reiniciar() -> str` — Vuelve todo a lo normal.
- `ansi.fg(c: i32) -> str` — El color del texto en 24 bits (rojo, verde y azul).
- `ansi.bg(c: i32) -> str` — El color de fondo en 24 bits.
- `ansi.fg_256(i: i32) -> str` — El color del texto de la paleta de 256 (0 a 255).
- `ansi.bg_256(i: i32) -> str`
- `ansi.fg_16(i: i32) -> str` — El color del texto de la paleta de 16 (0 a 7 normales, 8 a 15 brillantes).
- `ansi.bg_16(i: i32) -> str`
- `ansi.rgb_de_16(i: i32) -> i32` — Un color de la paleta de 16 de xterm (los valores por omisión; cada terminal puede cambiarlos).
- `ansi.rgb_de_256(i: i32) -> i32` — El color de la paleta de 256 (16 a 231: el cubo de 6 x 6 x 6; 232 a 255: grises; 0 a 15: los de `rgb_de_16`).
- `ansi.a_256(c: i32) -> i32` — El número (16 a 255) de la paleta de 256 que más se parece al color: el mejor entre el cubo y la rampa de grises, por distancia en RGB (a igual distancia, el cubo).
- `ansi.a_16(c: i32) -> i32` — El número (0 a 15) de la paleta de 16 que más se parece al color (a igual distancia, el de número más bajo).
- `ansi.pintar(s: str, c: i32) -> str` — El texto con ese color (24 bits); al terminar se vuelve al color de antes.
- `ansi.pintar_fondo(s: str, c: i32) -> str` — El texto con ese color de fondo.
- `ansi.pintar_256(s: str, c: i32) -> str` — Lo mismo con la paleta de 256, para terminales que no entienden los 24 bits.
- `ansi.pintar_16(s: str, c: i32) -> str` — Lo mismo con la paleta de 16.
- `ansi.negrita(s: str) -> str`
- `ansi.tenue(s: str) -> str`
- `ansi.cursiva(s: str) -> str`
- `ansi.subrayado(s: str) -> str`
- `ansi.invertido(s: str) -> str` — Intercambia el color del texto y el del fondo.
- `ansi.tachado(s: str) -> str`
- `ansi.degradado_texto(s: str, a: i32, b: i32) -> str` — El texto con cada carácter de un color, de `a` (el primero) a `b` (el último), mezclados en Oklab. Los espacios no llevan colores.
- `ansi.barra(fraccion: f64, ancho: i32, a: i32, b: i32) -> str` — Una barra de progreso de `ancho` casillas llena hasta `fraccion` (0 a 1), con el color pasando de `a` a `b` a lo largo de todo el ancho; lo que falta es una trama gris.
- `ansi.quitar(s: str) -> str` — El texto sin las secuencias de escape de color y estilo (ESC [ parámetros letra, como define ECMA-48). Una secuencia que no termina bien se deja como está.
- `ansi.largo_visible(s: str) -> i32` — Cuántos caracteres se ven (sin contar las secuencias de escape).
- `ansi.rellenar_der(s: str, ancho: i32) -> str` — Rellena con espacios a la derecha hasta `ancho` caracteres visibles (para alinear columnas de texto con color).

## `audio`

generar, mezclar y guardar sonido (use "audio").

Tipos: `audio.Sonido`, `audio.Bytes`.

- `audio.silencio(canales: i32, tasa: i32, duracion: f64) -> Sonido` — Silencio: `duracion` segundos con `canales` canales.
- `audio.largo(s: Sonido) -> i32` — Cuántas muestras tiene cada canal.
- `audio.duracion(s: Sonido) -> f64`
- `audio.muestra(s: Sonido, i: i32, c: i32) -> f64` — La muestra i del canal c.
- `audio.poner(s: Sonido, i: i32, c: i32, v: f64)`
- `audio.seno(f: f64, a: f64, dur: f64, tasa: i32) -> Sonido` — Una onda de frecuencia f (Hz), amplitud a (0 a 1) y `dur` segundos, mono.
- `audio.cuadrada(f: f64, a: f64, dur: f64, tasa: i32) -> Sonido`
- `audio.sierra(f: f64, a: f64, dur: f64, tasa: i32) -> Sonido`
- `audio.triangulo(f: f64, a: f64, dur: f64, tasa: i32) -> Sonido`
- `audio.ruido(a: f64, dur: f64, tasa: i32, semilla: i32) -> Sonido` — Ruido blanco de amplitud a; la misma semilla da el mismo ruido.
- `audio.envolvente(t: f64, dur: f64, ataque: f64, decaimiento: f64, sostenido: f64, liberacion: f64) -> f64` — La envolvente ADSR en el momento t de un sonido de `dur` segundos: sube de 0 a 1 en `ataque`, baja a `sostenido` en `decaimiento`, se queda ahí y baja a 0 en los últimos `liberacion` segundos (si el sonido es más corto que todo eso, la liberación arranca desde donde esté).
- `audio.adsr(s: Sonido, ataque: f64, decaimiento: f64, sostenido: f64, liberacion: f64)` — Le aplica la envolvente ADSR a s (en el lugar, a todos los canales).
- `audio.ganancia(s: Sonido, k: f64)` — Multiplica todo por k (en el lugar).
- `audio.mezclar(a: Sonido, b: Sonido) -> Sonido` — La suma de a y b, recortada a [-1, 1]; dura lo que el más largo. Tienen que tener los mismos canales y la misma tasa.
- `audio.concatenar(a: Sonido, b: Sonido) -> Sonido` — a y después b.
- `audio.estereo(izq: Sonido, der: Sonido) -> Sonido` — Un sonido estéreo con izq en el canal izquierdo y der en el derecho (dos sonidos mono de la misma tasa; dura lo que el más largo).
- `audio.a_16(x: f64) -> i32` — Una muestra como entero de 16 bits.
- `audio.a_wav(s: Sonido) -> Vec<i32>` — Los bytes de un WAV PCM de 16 bits con el sonido s.
- `audio.guardar_wav(s: Sonido, ruta: str) -> Result<i32>` — Guarda s como WAV; devuelve cuántos bytes escribió.
- `audio.de_wav(bytes: Vec<i32>) -> Result<Sonido>` — El sonido de los bytes de un WAV PCM de 16 bits (mono o estéreo; los chunks que no son fmt ni data se saltan). Como toda fn que recibe un Vec, se queda con él.
- `audio.leer_wav(ruta: str) -> Result<Sonido>` — Lee un WAV PCM de 16 bits.

## `autodiff`

derivadas automáticas (use "autodiff").

Tipos: `autodiff.Cinta`.

- `autodiff.cinta() -> Cinta` — Una cinta vacía.
- `autodiff.limpiar(c: Cinta)` — Vacía la cinta (para el paso siguiente de un entrenamiento).
- `autodiff.largo(c: Cinta) -> i32` — Cuántos valores tiene la cinta.
- `autodiff.valor(c: Cinta, i: i32) -> f64` — El valor de `i`.
- `autodiff.gradiente(c: Cinta, i: i32) -> f64` — La derivada del último resultado pasado a `derivar` respecto de `i`.
- `autodiff.variable(c: Cinta, v: f64) -> i32` — Un número del que se quiere la derivada (un peso, una entrada).
- `autodiff.constante(c: Cinta, v: f64) -> i32` — Un número fijo. Es lo mismo que una variable: su derivada se calcula igual, solo que nadie la mira.
- `autodiff.suma(c: Cinta, a: i32, b: i32) -> i32`
- `autodiff.resta(c: Cinta, a: i32, b: i32) -> i32`
- `autodiff.mul(c: Cinta, a: i32, b: i32) -> i32`
- `autodiff.div(c: Cinta, a: i32, b: i32) -> i32` — a / b (b = 0 da infinito o NaN, como en f64).
- `autodiff.neg(c: Cinta, a: i32) -> i32`
- `autodiff.escalar(c: Cinta, a: i32, k: f64) -> i32` — a * k, con k un número fijo.
- `autodiff.cuadrado(c: Cinta, a: i32) -> i32`
- `autodiff.exponencial(c: Cinta, a: i32) -> i32`
- `autodiff.logaritmo(c: Cinta, a: i32) -> i32` — Logaritmo natural (a tiene que ser positivo).
- `autodiff.tanh(c: Cinta, a: i32) -> i32`
- `autodiff.sigmoide(c: Cinta, a: i32) -> i32`
- `autodiff.relu(c: Cinta, a: i32) -> i32`
- `autodiff.derivar(c: Cinta, salida: i32)` — Calcula la derivada de `salida` respecto de cada valor de la cinta. Los gradientes de una llamada anterior se borran antes.

## `buffer`

lib/buffer.scar -- el texto de un editor: líneas, cursor, selección, deshacer y colores para SCAR.

Tipos: `buffer.Buffer`, `buffer.Bytes`, `buffer.Pareja`, `buffer.Historial`.

- `buffer.n_lineas(b: Buffer) -> i32`
- `buffer.linea(b: Buffer, i: i32) -> str` — buffer.linea(b, i) -> str: la línea i ("" si no existe).
- `buffer.contenido(b: Buffer) -> str` — buffer.contenido(b) -> str: todo el texto, con \n entre líneas.
- `buffer.nuevo(t: str) -> Buffer` — buffer.nuevo(texto) -> Buffer
- `buffer.poner(b: Buffer, t: str)` — buffer.poner(b, texto): cambia todo el texto (sin poder deshacer), cursor al principio.
- `buffer.marcar_guardado(b: Buffer)` — buffer.marcar_guardado(b): el texto de ahora es el del archivo.
- `buffer.hay_sel(b: Buffer) -> bool` — buffer.hay_sel(b) -> bool: hay texto seleccionado.
- `buffer.sel_f1(b: Buffer) -> i32` — El principio (f1, c1) y el fin (f2, c2) de la selección; sin selección, los dos son el cursor.
- `buffer.sel_c1(b: Buffer) -> i32`
- `buffer.sel_f2(b: Buffer) -> i32`
- `buffer.sel_c2(b: Buffer) -> i32`
- `buffer.sel_texto(b: Buffer) -> str` — buffer.sel_texto(b) -> str: lo seleccionado ("" si no hay).
- `buffer.mover_a(b: Buffer, f: i32, c: i32, extender: bool)` — buffer.mover_a(b, fila, col, extender): lleva el cursor a esa posición (ajustada al texto).
- `buffer.izquierda(b: Buffer, extender: bool, palabra: bool)`
- `buffer.derecha(b: Buffer, extender: bool, palabra: bool)`
- `buffer.arriba(b: Buffer, extender: bool)`
- `buffer.abajo(b: Buffer, extender: bool)`
- `buffer.pagina(b: Buffer, delta: i32, extender: bool)` — buffer.pagina(b, delta, extender): sube o baja `delta` líneas (RePág / AvPág).
- `buffer.inicio(b: Buffer, extender: bool, doc: bool)` — Inicio: al primer carácter que no es espacio; otra vez, al principio de la línea. Con `doc`, al principio del texto.
- `buffer.fin(b: Buffer, extender: bool, doc: bool)` — Fin: al final de la línea; con `doc`, al final del texto.
- `buffer.seleccionar_todo(b: Buffer)`
- `buffer.seleccionar_palabra(b: Buffer)` — buffer.seleccionar_palabra(b): selecciona la palabra (o el signo) donde está el cursor.
- `buffer.insertar(b: Buffer, s: str)` — buffer.insertar(b, s): escribe s en el cursor (reemplaza la selección).
- `buffer.escribir(b: Buffer, s: str)` — buffer.escribir(b, s): lo que escribe la persona con el teclado. Igual que insertar, salvo que una } escrita en una línea que solo tiene espacios antes se corre 4 lugares a la izquierda.
- `buffer.pegar(b: Buffer, s: str)` — buffer.pegar(b, s): como insertar, para un texto que viene del portapapeles (varias líneas, tabuladores, \r\n); es un solo paso para deshacer.
- `buffer.borrar_sel(b: Buffer)` — buffer.borrar_sel(b): borra lo seleccionado.
- `buffer.enter(b: Buffer)` — buffer.enter(b): salto de línea con la sangría de la línea; después de una { suma 4 espacios, y entre { y } deja la } en su propia línea.
- `buffer.tab(b: Buffer, atras: bool)` — buffer.tab(b, atras): Tab pone espacios hasta la próxima columna múltiplo de 4; con varias líneas seleccionadas las sangra; con atras (Mayús + Tab) quita la sangría.
- `buffer.borrar_atras(b: Buffer, palabra: bool)` — buffer.borrar_atras(b, palabra): Retroceso (con Ctrl, borra la palabra de atrás).
- `buffer.borrar_adelante(b: Buffer, palabra: bool)` — buffer.borrar_adelante(b, palabra): Supr (con Ctrl, borra la palabra que sigue).
- `buffer.deshacer(b: Buffer) -> bool` — buffer.deshacer(b) -> bool: deshace el último paso (false si no hay nada que deshacer).
- `buffer.rehacer(b: Buffer) -> bool` — buffer.rehacer(b) -> bool: vuelve a hacer lo último que se deshizo.
- `buffer.buscar(b: Buffer, aguja: str, adelante: bool, sensible: bool) -> bool` — buffer.buscar(b, aguja, adelante, sensible) -> bool: selecciona la próxima aparición de `aguja` (después de la selección, o antes si adelante es false), dando la vuelta al texto. false si no hay ninguna. `sensible`: distingue mayúsculas de minúsculas.
- `buffer.reemplazar_todo(b: Buffer, aguja: str, nuevo: str) -> i32` — buffer.reemplazar_todo(b, aguja, nuevo) -> i32: cambia todas las apariciones (distinguiendo mayúsculas) y dice cuántas eran. Es un solo paso para deshacer.
- `buffer.ajustar(b: Buffer, cols: i32)` — buffer.ajustar(b, cols): parte las líneas de más de `cols` caracteres en varias, y cada continuación empieza con "… " (para mostrar una salida larga sin que se corte). Borra el historial de deshacer y deja el cursor al principio: es para textos que solo se miran.
- `buffer.ir_a_linea(b: Buffer, n: i32)` — buffer.ir_a_linea(b, n): el cursor al principio de la línea n (se cuenta desde 1).
- `buffer.clases(s: str) -> Vec<i32>` — buffer.clases(linea) -> Vec<i32>: la clase de cada carácter (0 común, 1 palabra clave, 2 tipo, 3 texto entre comillas, 4 número, 5 comentario, 6 nombre de función).
- `buffer.poner_bytes(b: Buffer, bytes: Vec<i32>)` — buffer.poner_bytes(b, bytes): lo mismo que poner(b, texto) con el contenido de un archivo (los bytes que da json.bytes_de_archivo).
- `buffer.cerrar_pares(b: Buffer, si: bool)` — buffer.cerrar_pares(b, si): con true, escribir ( [ { o " pone también el que cierra y deja el cursor en el medio (si lo que sigue es un espacio, el final de la línea o algo que cierra; las comillas, además, si lo de antes no es parte de una palabra ni otra comilla); escribir el que cierra justo delante de uno igual solo lo saltea; y Retroceso entre un par vacío borra los dos. Apagado de entrada.
- `buffer.comentar(b: Buffer)` — buffer.comentar(b): pone o saca "# " en las líneas de la selección (o en la del cursor). Si todas las que no están en blanco ya empiezan con #, se los saca (con el espacio que siga); si no, pone "# " en la sangría más chica. Las líneas en blanco no se tocan. Es un solo paso para deshacer.
- `buffer.duplicar(b: Buffer)` — buffer.duplicar(b): copia las líneas de la selección (o la del cursor) justo debajo, y lleva el cursor (y la selección) a la copia. Es un solo paso para deshacer.
- `buffer.pareja(b: Buffer) -> Pareja` — buffer.pareja(b) -> Pareja: la pareja de la llave que está en el cursor o, si no hay, justo antes. Las que están dentro de textos y comentarios no cuentan.
- `buffer.historial_vacio() -> Historial`
- `buffer.historial(b: Buffer) -> Historial` — buffer.historial(b) -> Historial: una copia de lo que hay para deshacer y rehacer. (Las listas se copian elemento por elemento acá mismo: pasar un campo a otra función lo entregaría.)
- `buffer.poner_historial(b: Buffer, h: Historial)` — buffer.poner_historial(b, h): cambia lo que hay para deshacer y rehacer por una copia de h (que tiene que ser del mismo texto que tiene b: se usa después de buffer.poner con ese texto).

## `codigos`

codificar y firmar datos (use "codigos").

Tipos: `codigos.Datos`, `codigos.Estado`.

- `codigos.datos(v: Vec<i32>) -> Datos`
- `codigos.vacio() -> Datos`
- `codigos.largo(d: Datos) -> i32`
- `codigos.byte(d: Datos, i: i32) -> i32`
- `codigos.agregar(d: Datos, b: i32)`
- `codigos.copia(d: Datos) -> Datos`
- `codigos.unir(a: Datos, b: Datos) -> Datos` — `a` seguido de `b`, como un Datos nuevo.
- `codigos.son_iguales(a: Datos, b: Datos) -> bool`
- `codigos.de_texto(s: str) -> Datos` — Los bytes UTF-8 de un texto.
- `codigos.a_cadena(d: Datos) -> Result<str>` — El texto que escriben esos bytes en UTF-8. Err si no es UTF-8 válido (con la misma regla estricta de Python: sin sustitutos ni formas largas de más).
- `codigos.de_archivo(ruta: str) -> Result<Datos>` — Los bytes de un archivo.
- `codigos.aleatorios(n: i32) -> Result<Datos>` — `n` bytes al azar del sistema operativo (/dev/urandom).
- `codigos.hex(d: Datos) -> str` — Los bytes como texto hexadecimal en minúsculas, dos cifras por byte.
- `codigos.de_hex(s: str) -> Result<Datos>` — Lo contrario: acepta mayúsculas y minúsculas, y falla con un largo impar o un carácter que no es una cifra.
- `codigos.base64(d: Datos) -> str` — Base64 (RFC 4648) con el alfabeto de + y / y el relleno con =.
- `codigos.base64_url(d: Datos, relleno: bool) -> str` — Base64 seguro para URL y nombres de archivo: usa - y _ en vez de + y /. Con `relleno` falso se omiten los = del final.
- `codigos.de_base64(s: str) -> Result<Datos>` — Decodifica base64 normal. Falla con caracteres de otro alfabeto, espacios, relleno mal puesto o bits sobrantes (es estricto, como b64decode con validate=True).
- `codigos.de_base64_url(s: str) -> Result<Datos>` — Decodifica el base64 de URL; el relleno con = es opcional.
- `codigos.sha256(d: Datos) -> Datos` — El SHA-256 de los bytes: 32 bytes.
- `codigos.sha1(d: Datos) -> Datos` — El SHA-1 de los bytes: 20 bytes. Ya no es seguro contra ataques: solo para comprobar archivos o firmas que lo piden.
- `codigos.md5(d: Datos) -> Datos` — El MD5 de los bytes: 16 bytes. Roto desde hace años: solo para comprobar archivos que lo publican, nunca para firmar.
- `codigos.sha256_hex(d: Datos) -> str`
- `codigos.sha1_hex(d: Datos) -> str`
- `codigos.md5_hex(d: Datos) -> str`
- `codigos.resumen(algoritmo: str, d: Datos) -> Result<Datos>` — El resumen con el algoritmo por nombre: "sha256", "sha1" o "md5".
- `codigos.hmac(algoritmo: str, clave: Datos, mensaje: Datos) -> Result<Datos>` — HMAC (RFC 2104) con "sha256", "sha1" o "md5": la firma de `mensaje` con `clave`.
- `codigos.hmac_sha256(clave: Datos, mensaje: Datos) -> Datos`
- `codigos.hmac_hex(algoritmo: str, clave: Datos, mensaje: Datos) -> Result<str>` — La firma en hexadecimal (la forma en que la piden la mayoría de las APIs).
- `codigos.crc32(d: Datos) -> i64` — CRC-32 (zlib, PNG, gzip), como número sin signo de 32 bits (zlib.crc32 de Python).
- `codigos.adler32(d: Datos) -> i64` — Adler-32 (zlib), como número sin signo de 32 bits.
- `codigos.uuid4_de(d: Datos) -> Result<str>` — Un UUID versión 4 hecho con esos 16 bytes (se les pone la versión y la variante de la RFC 4122): "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx". Err si no son 16 bytes.
- `codigos.uuid4() -> Result<str>` — Un UUID versión 4 al azar (con los bytes del sistema operativo).
- `codigos.url_codificar(s: str, espacio_mas: bool) -> str` — Codifica un texto para ir dentro de una URL (RFC 3986): se quedan sin tocar las letras, cifras, - . _ ~ y todo lo demás pasa a %XX con los bytes UTF-8, en mayúsculas. Con `espacio_mas`, el espacio se escribe + (el formato de formularios).
- `codigos.url_decodificar(s: str, espacio_mas: bool) -> Result<str>` — Lo contrario. Err con un % sin dos cifras hexadecimales o si el resultado no es UTF-8. Con `espacio_mas`, un + vale espacio.

## `colecciones`

pila, cola, mapa y conjunto con orden de inserción, y ordenar (use "colecciones").

Tipos: `colecciones.Pila`, `colecciones.Cola`, `colecciones.Mapa`, `colecciones.MapaEnt`, `colecciones.Conjunto`, `colecciones.ConjuntoEnt`, `colecciones.Tramo`, `colecciones.Indices`.

- `colecciones.pila<T>(ejemplo: T) -> Pila<T>` — Una pila vacía. El argumento no se guarda: solo dice de qué tipo es.
- `colecciones.apilar<T>(p: Pila<T>, x: T)`
- `colecciones.desapilar<T>(p: Pila<T>) -> Option<T>`
- `colecciones.tope<T>(p: Pila<T>) -> Option<T>` — El de arriba, sin sacarlo (None si está vacía).
- `colecciones.pila_largo<T>(p: Pila<T>) -> i32`
- `colecciones.pila_vacia<T>(p: Pila<T>) -> bool`
- `colecciones.cola<T>(ejemplo: T) -> Cola<T>`
- `colecciones.encolar<T>(c: Cola<T>, x: T)`
- `colecciones.desencolar<T>(c: Cola<T>) -> Option<T>`
- `colecciones.frente<T>(c: Cola<T>) -> Option<T>` — El primero, sin sacarlo (None si está vacía).
- `colecciones.cola_largo<T>(c: Cola<T>) -> i32`
- `colecciones.cola_vacia<T>(c: Cola<T>) -> bool`
- `colecciones.comparar(a: str, b: str) -> i32` — -1, 0 o 1: a antes, igual o después que b (por códigos de carácter, como Python: "Z" < "a" < "ñ"; un prefijo va antes).
- `colecciones.menor_texto(a: str, b: str) -> bool`
- `colecciones.mapa<V>(ejemplo: V) -> Mapa<V>`
- `colecciones.poner<V>(m: Mapa<V>, k: str, v: V)`
- `colecciones.obtener<V>(m: Mapa<V>, k: str) -> Option<V>`
- `colecciones.contiene<V>(m: Mapa<V>, k: str) -> bool`
- `colecciones.quitar<V>(m: Mapa<V>, k: str) -> bool`
- `colecciones.sumar<V: Numeric>(m: Mapa<V>, k: str, d: V)` — Suma d al valor de k (si no estaba, lo pone en d): para contar.
- `colecciones.largo<V>(m: Mapa<V>) -> i32`
- `colecciones.clave<V>(m: Mapa<V>, i: i32) -> str` — La clave número i, en orden de inserción (0 <= i < largo(m)).
- `colecciones.valor<V>(m: Mapa<V>, i: i32) -> Option<V>`
- `colecciones.claves<V>(m: Mapa<V>) -> Vec<str>` — Las claves en orden de inserción (una copia).
- `colecciones.mapa_ent<V>(ejemplo: V) -> MapaEnt<V>`
- `colecciones.poner_ent<V>(m: MapaEnt<V>, k: i32, v: V)`
- `colecciones.obtener_ent<V>(m: MapaEnt<V>, k: i32) -> Option<V>`
- `colecciones.contiene_ent<V>(m: MapaEnt<V>, k: i32) -> bool`
- `colecciones.quitar_ent<V>(m: MapaEnt<V>, k: i32) -> bool`
- `colecciones.sumar_ent<V: Numeric>(m: MapaEnt<V>, k: i32, d: V)`
- `colecciones.largo_ent<V>(m: MapaEnt<V>) -> i32`
- `colecciones.clave_ent<V>(m: MapaEnt<V>, i: i32) -> i32`
- `colecciones.valor_ent<V>(m: MapaEnt<V>, i: i32) -> Option<V>`
- `colecciones.claves_ent<V>(m: MapaEnt<V>) -> Vec<i32>`
- `colecciones.conjunto() -> Conjunto`
- `colecciones.agregar(c: Conjunto, x: str)`
- `colecciones.tiene(c: Conjunto, x: str) -> bool`
- `colecciones.sacar(c: Conjunto, x: str) -> bool`
- `colecciones.cardinal(c: Conjunto) -> i32`
- `colecciones.elemento(c: Conjunto, i: i32) -> str` — El elemento número i, en orden de inserción.
- `colecciones.union(a: Conjunto, b: Conjunto) -> Conjunto`
- `colecciones.interseccion(a: Conjunto, b: Conjunto) -> Conjunto`
- `colecciones.diferencia(a: Conjunto, b: Conjunto) -> Conjunto`
- `colecciones.conjunto_ent() -> ConjuntoEnt`
- `colecciones.agregar_ent(c: ConjuntoEnt, x: i32)`
- `colecciones.tiene_ent(c: ConjuntoEnt, x: i32) -> bool`
- `colecciones.sacar_ent(c: ConjuntoEnt, x: i32) -> bool`
- `colecciones.cardinal_ent(c: ConjuntoEnt) -> i32`
- `colecciones.elemento_ent(c: ConjuntoEnt, i: i32) -> i32`
- `colecciones.union_ent(a: ConjuntoEnt, b: ConjuntoEnt) -> ConjuntoEnt`
- `colecciones.interseccion_ent(a: ConjuntoEnt, b: ConjuntoEnt) -> ConjuntoEnt`
- `colecciones.diferencia_ent(a: ConjuntoEnt, b: ConjuntoEnt) -> ConjuntoEnt`
- `colecciones.ordenar<T: Numeric>(v: Vec<T>) -> Vec<T>` — Ordena de menor a mayor (quicksort, no estable).
- `colecciones.ordenar_desc<T: Numeric>(v: Vec<T>) -> Vec<T>` — Igual, de mayor a menor.
- `colecciones.ordenar_textos(v: Vec<str>) -> Vec<str>` — Ordena textos por código de carácter (quicksort, no estable).
- `colecciones.ordenar_por<T>(v: Vec<T>, menor: fn(T, T) -> bool) -> Vec<T>` — Ordena con menor(a, b) ("a va antes que b"), estable: los que empatan quedan en el orden en que estaban. Mergesort de abajo hacia arriba sobre los índices; después cada elemento se mueve a su lugar siguiendo los ciclos de la permutación, sin copiar ninguno.

## `colores`

colores, espacios de color, paletas y mapas de color (use "colores").

Tipos: `colores.Hsv`, `colores.Hsl`, `colores.Lab`, `colores.Oklab`, `colores.Lista`, `colores.Paleta`, `colores.Mapa`.

- `colores.rgb(r: i32, g: i32, b: i32) -> i32` — Un color opaco con rojo, verde y azul de 0 a 255 (lo que pase de ahí se recorta).
- `colores.rgba(r: i32, g: i32, b: i32, a: i32) -> i32` — Un color con alfa (0 transparente, 255 opaco).
- `colores.canal_r(c: i32) -> i32`
- `colores.canal_g(c: i32) -> i32`
- `colores.canal_b(c: i32) -> i32`
- `colores.canal_a(c: i32) -> i32`
- `colores.a_gui(c: i32) -> i32` — El color sin alfa, para gui (0xRRGGBB).
- `colores.de_gui(c: i32) -> i32` — Un color opaco a partir de un 0xRRGGBB.
- `colores.a_hex(c: i32) -> str` — "#rrggbb" en minúsculas.
- `colores.a_hex_a(c: i32) -> str` — "#rrggbbaa" (CSS), con el alfa al final.
- `colores.de_hex(s: str) -> Result<i32>` — Lee "#rgb", "#rgba", "#rrggbb" o "#rrggbbaa" (el # es opcional; mayúsculas o minúsculas).
- `colores.a_hsv(c: i32) -> Hsv` — Tono (0 a 360), saturación y valor (0 a 1), como colorsys.rgb_to_hsv.
- `colores.de_hsv(h: f64, s: f64, v: f64) -> i32` — De tono (en grados, cualquier valor: da la vuelta), saturación y valor (0 a 1) a colores.
- `colores.de_hsv_a(h: f64, s: f64, v: f64, a: i32) -> i32`
- `colores.a_hsl(c: i32) -> Hsl` — Tono (0 a 360), saturación y luz (0 a 1), como colorsys.rgb_to_hls.
- `colores.de_hsl(h: f64, s: f64, l: f64) -> i32`
- `colores.de_hsl_a(h: f64, s: f64, l: f64, a: i32) -> i32`
- `colores.a_lab(c: i32) -> Lab` — L (0 a 100), a y b, como skimage.colores.rgb2lab.
- `colores.de_lab(l: f64, a: f64, b: f64) -> i32` — Lo contrario (lo que no cabe en sRGB se recorta), como skimage.colores.lab2rgb.
- `colores.de_lab_a(l: f64, a: f64, b: f64, alfa: i32) -> i32`
- `colores.a_oklab(c: i32) -> Oklab` — L (0 a 1), a y b (Björn Ottosson, 2020): una distancia entre colores casi pareja y degradados sin los grises sucios de mezclar en sRGB.
- `colores.de_oklab(l: f64, a: f64, b: f64) -> i32`
- `colores.de_oklab_a(l: f64, a: f64, b: f64, alfa: i32) -> i32`
- `colores.mezclar(a: i32, b: i32, t: f64) -> i32` — Mezcla `a` con `b`: t = 0 da a, t = 1 da b (en sRGB, canal por canal, alfa incluido).
- `colores.mezclar_oklab(a: i32, b: i32, t: f64) -> i32` — Lo mismo en Oklab: el degradado pasa por colores parejos en luz y sin oscurecerse a mitad de camino.
- `colores.aclarar(c: i32, t: f64) -> i32` — Mezcla con blanco: t de 0 (igual) a 1 (blanco).
- `colores.oscurecer(c: i32, t: f64) -> i32` — Mezcla con negro: t de 0 (igual) a 1 (negro).
- `colores.saturar(c: i32, factor: f64) -> i32` — Multiplica la saturación (en HSL) por `factor` (0 apaga, 2 duplica, con tope en 1).
- `colores.girar_tono(c: i32, grados: f64) -> i32` — Gira el tono esos grados (en HSL).
- `colores.complementario(c: i32) -> i32`
- `colores.invertir(c: i32) -> i32` — El negativo: 255 menos cada canal (el alfa queda).
- `colores.luminancia(c: i32) -> f64` — La luminancia relativa de WCAG 2: 0 (negro) a 1 (blanco).
- `colores.gris(c: i32) -> i32` — El gris con la misma luminancia (opaco no: conserva el alfa).
- `colores.contraste(a: i32, b: i32) -> f64` — La relación de contraste de WCAG entre dos colores: de 1 (iguales) a 21 (negro sobre blanco). 4.5 es el mínimo para texto normal (AA) y 7, para AAA.
- `colores.texto_sobre(fondo: i32) -> i32` — Negro o blanco, el que se lee mejor sobre ese fondo.
- `colores.mate_pi() -> f64`
- `colores.delta_e(a: i32, b: i32) -> f64` — La diferencia CIEDE2000 (ΔE) entre dos colores: 0 son iguales, 1 casi no se nota, más de 5 se distinguen a simple vista (skimage.colores.deltaE_ciede2000).
- `colores.simular(c: i32, tipo: str, severidad: f64) -> Result<i32>` — Cómo ve el color alguien con esa deficiencia (modelo de Machado, Oliveira y Fernandes 2009, sobre sRGB lineal). `tipo`: "protanopia" (sin rojo), "deuteranopia" (sin verde), "tritanopia" (sin azul) o "acromatopsia" (solo luz). `severidad` de 0 (ve normal) a 1 (ausencia total); los valores de en medio mezclan las matrices en línea recta. Err si el tipo no existe.
- `colores.lista() -> Lista`
- `colores.lista_agregar(l: Lista, c: i32)`
- `colores.lista_largo(l: Lista) -> i32`
- `colores.lista_color(l: Lista, i: i32) -> i32`
- `colores.degradado(l: Lista, t: f64, oklab: bool) -> i32` — El color en la posición t (0 a 1) de un degradado con esos colores repartidos parejo. Con `oklab` mezcla en Oklab (mejor para el ojo); si no, en sRGB. Con la lista vacía, negro.
- `colores.paleta_n(n: i32, i: i32) -> i32` — El color i de n colores bien repartidos en el círculo de tonos de Oklab, con la misma luz y el mismo croma: n colores distintos para n series de datos. n y los índices arrancan en 0 y dan la vuelta (i % n).
- `colores.con_nombre(nombre: str) -> Result<i32>` — Un color de la tabla de nombres de CSS (148), sin importar mayúsculas. Err si no existe.
- `colores.cantidad_nombres() -> i32`
- `colores.nombre_en(i: i32) -> str` — El nombre número i (de 0 a 147, en orden alfabético).
- `colores.color_en(i: i32) -> i32`
- `colores.nombre_mas_cercano(c: i32) -> str` — El nombre de CSS del color más parecido (la menor diferencia CIEDE2000).
- `colores.paleta(nombre: str) -> Result<Paleta>` — Una paleta de colores distintos por nombre: "tab10", "tab20", "set1", "set2", "set3", "dark2", "paired", "accent", "pastel1", "pastel2" u "okabe_ito". Err si no existe.
- `colores.paleta_largo(p: Paleta) -> i32`
- `colores.paleta_color(p: Paleta, i: i32) -> i32` — El color i de la paleta (da la vuelta cuando i pasa del largo).
- `colores.cantidad_paletas() -> i32`
- `colores.nombre_paleta(i: i32) -> str`
- `colores.mapa(nombre: str) -> Result<Mapa>` — Un mapa de color continuo de 256 pasos por nombre: "viridis", "magma", "inferno", "plasma", "cividis", "turbo", "coolwarm", "rdbu", "spectral", "ylgnbu", "greys" o "hot". Err si no existe.
- `colores.mapa_en(m: Mapa, t: f64) -> i32` — El color del mapa en t (de 0 a 1; fuera de ese rango se recorta), con el mismo paso que matplotlib: el casillero int(t * 256).
- `colores.cantidad_mapas() -> i32`
- `colores.nombre_mapa(i: i32) -> str`

## `config`

archivos de configuración (use "config"). Escrita entera en SCAR; probada contra configparser y tomllib de Python.

Tipos: `config.Sal`, `config.Ls`, `config.T`, `config.Clave`.

- `config.entero_de(s: str, defecto: i64) -> i64` — Un entero como lo lee int() de Python (espacios, signo, guiones bajos entre cifras). Si no es un entero o no cabe en un i64, `defecto`.
- `config.decimal_de(s: str, defecto: f64) -> f64` — Un número con decimales (texto.a_f64); si no lo es, `defecto`.
- `config.booleano_de(s: str, defecto: bool) -> bool` — Un booleano como getboolean de configparser: 1 yes true on / 0 no false off (sin importar mayúsculas, y sin quitar espacios: un valor de varias líneas no es un booleano). Si no es ninguno, `defecto`.
- `config.guardar(ruta: str, s: str) -> Result<i32>` — Guarda un texto en un archivo. Devuelve cuántos bytes escribió.
- `config.leer_ini(contenido: str) -> Result<json.Doc>` — Lee un INI como RawConfigParser().read_string. Árbol: la raíz es un objeto con una sección por clave (cada una un objeto de texto).
- `config.leer_ini_archivo(ruta: str) -> Result<json.Doc>`
- `config.ini_tiene(d: json.Doc, seccion: str, clave: str) -> bool` — ¿Está la clave en la sección (o en [DEFAULT])?
- `config.ini_texto(d: json.Doc, seccion: str, clave: str, defecto: str) -> str` — El valor de la clave, o `defecto` si no está.
- `config.ini_entero(d: json.Doc, seccion: str, clave: str, defecto: i64) -> i64`
- `config.ini_decimal(d: json.Doc, seccion: str, clave: str, defecto: f64) -> f64`
- `config.ini_booleano(d: json.Doc, seccion: str, clave: str, defecto: bool) -> bool`
- `config.ini_secciones(d: json.Doc) -> Vec<str>` — Los nombres de las secciones, sin DEFAULT, en el orden del archivo.
- `config.ini_claves(d: json.Doc, seccion: str) -> Vec<str>` — Las claves de la sección (las suyas primero y después las de [DEFAULT] que no repite, como items() de configparser, pero con las de DEFAULT al final).
- `config.escribir_ini(d: json.Doc) -> Result<str>` — Escribe el árbol como RawConfigParser.write: primero [DEFAULT] (si no está vacía), después las secciones, "clave = valor", los saltos de línea (\n, \r\n o \r) de un valor se escriben como salto y tab.
- `config.leer_lineas(contenido: str) -> json.Doc` — Lee el texto: cada línea es una clave y el resto de la línea; las líneas en blanco y las que empiezan con # no cuentan. La raíz es un objeto con un arreglo de textos por clave (una clave puede repetirse: "estacion").
- `config.leer_lineas_archivo(ruta: str) -> Result<json.Doc>`
- `config.ultima(d: json.Doc, clave: str, defecto: str) -> str` — El resto de la última línea con esa clave (la que manda cuando se repite), o `defecto`.
- `config.todas(d: json.Doc, clave: str) -> Vec<str>` — El resto de todas las líneas con esa clave, en orden.
- `config.campo(s: str, i: i32) -> str` — La palabra número `i` (desde 0) de un texto separado por espacios ("" si no hay).
- `config.escribir_lineas(d: json.Doc) -> Result<str>`
- `config.leer_toml(contenido: str) -> Result<json.Doc>` — Lee un TOML como tomllib.loads (sin fechas ni horas). Árbol: la raíz es un objeto.
- `config.leer_toml_archivo(ruta: str) -> Result<json.Doc>`
- `config.escribir_toml(d: json.Doc) -> Result<str>` — Escribe el árbol como TOML: primero los valores sueltos de cada tabla, después sus subtablas ([a.b]) y los arreglos de tablas ([[a]]); los demás arreglos y las tablas dentro de arreglos, en una línea. Lo que escribe lo lee leer_toml (y tomllib) igual.

## `csv`

CSV completo (use "csv"): leer y escribir con comillas, separador configurable, encabezados y columnas por nombre. Probada contra el módulo csv de Python.

Tipos: `csv.Tabla`.

- `csv.nueva() -> Tabla`
- `csv.agregar_celda(t: Tabla, valor: str)`
- `csv.cerrar_fila(t: Tabla)` — Termina la fila con las celdas agregadas desde la anterior (puede quedar sin celdas).
- `csv.agregar_fila(t: Tabla, valores: Vec<str>)` — Una fila entera de una vez.
- `csv.filas(t: Tabla) -> i32`
- `csv.columnas(t: Tabla, fila: i32) -> i32` — Cuántas celdas tiene la fila (0 si no existe).
- `csv.celda(t: Tabla, fila: i32, columna: i32) -> str` — La celda (fila, columna), o "" si no existe.
- `csv.existe(t: Tabla, fila: i32, columna: i32) -> bool`
- `csv.indice(t: Tabla, nombre: str) -> i32` — La columna cuyo encabezado (fila 0) se llama así; -1 si no hay.
- `csv.dato(t: Tabla, fila: i32, nombre: str) -> str` — La celda de la fila de datos número `fila` (0 es la primera después del encabezado) en la columna de ese nombre; "" si no existe.
- `csv.dato_numero(t: Tabla, fila: i32, nombre: str, defecto: f64) -> f64`
- `csv.numero(t: Tabla, fila: i32, columna: i32, defecto: f64) -> f64` — La celda como número ("3.25", "-1e3", ".5", con espacios alrededor); `defecto` si no es un número.
- `csv.analizar(b: Vec<i32>, separador: str) -> Result<Tabla>` — Lee los bytes UTF-8 de un CSV. `separador` es un solo carácter ("," ";" "\t" "|").
- `csv.bytes_de(s: str) -> Vec<i32>` — Los bytes UTF-8 de un str.
- `csv.analizar_texto(s: str, separador: str) -> Result<Tabla>`
- `csv.bytes_de_archivo(ruta: str) -> Result<Vec<i32>>`
- `csv.leer_archivo(ruta: str, separador: str) -> Result<Tabla>`
- `csv.escribir_con(t: Tabla, separador: str, terminador: str) -> str` — La tabla como texto, con `terminador` al final de cada fila.
- `csv.escribir(t: Tabla, separador: str) -> str` — Como csv.writer: filas terminadas en \r\n.
- `csv.guardar(t: Tabla, ruta: str, separador: str) -> Result<i32>`

## `editor`

lib/editor.scar -- un editor de texto de varias líneas para lib/gui, pensado para código.

Tipos: `editor.Editor`.

- `editor.nuevo(t: str) -> Editor` — editor.nuevo(texto) -> Editor
- `editor.enfocar(e: Editor)` — editor.enfocar(e): el próximo cuadro, las teclas van a este editor.
- `editor.marcar_linea(e: Editor, n: i32)` — editor.marcar_linea(e, n): pinta la línea n (desde 1) como línea con un error; 0 la quita.
- `editor.limpiar_errores(e: Editor)` — editor.limpiar_errores(e) y editor.agregar_error(e, n): las líneas con un error (n desde 1) llevan un punto rojo en el margen y una línea ondulada debajo. Para marcar lo que dice el compilador.
- `editor.agregar_error(e: Editor, n: i32)`
- `editor.cerrar_pares(e: Editor, si: bool)` — editor.cerrar_pares(e, si): cerrar solo paréntesis, corchetes, llaves y comillas (ver buffer.cerrar_pares).
- `editor.comentar(e: Editor)` — editor.comentar(e) y editor.duplicar(e): lo mismo que Ctrl+/ y Ctrl+D (buffer.comentar, buffer.duplicar).
- `editor.duplicar(e: Editor)`
- `editor.ir_a_linea(e: Editor, n: i32)` — editor.ir_a_linea(e, n): lleva el cursor a la línea n (desde 1) y la muestra en el medio.
- `editor.mostrar_cursor(e: Editor)` — editor.mostrar_cursor(e): la próxima vez que se dibuje, la vista incluye el cursor.
- `editor.solo_lectura(e: Editor, si: bool)` — editor.solo_lectura(e, si): con true, el editor solo deja mirar, seleccionar y copiar.
- `editor.numeros(e: Editor, si: bool)` — editor.numeros(e, si): mostrar (o no) los números de línea.
- `editor.colorear(e: Editor, si: bool)` — editor.colorear(e, si): pintar (o no) el texto con los colores de SCAR.
- `editor.modificadores() -> i32` — editor.modificadores() -> i32: las teclas modificadoras apretadas ahora, sumadas: 1 Mayús, 2 Ctrl, 4 Alt (para atajos como Ctrl+S).
- `editor.seleccionar_todo(e: Editor)` — editor.seleccionar_todo(e), editor.copiar(e), editor.cortar(e), editor.pegar(e), editor.deshacer(e), editor.rehacer(e): lo mismo que hacen Ctrl+A, C, X, V, Z e Y adentro del editor, para llamarlas desde un menú o un botón. Cortar, pegar, deshacer y rehacer no hacen nada si el editor es de solo lectura.
- `editor.copiar(e: Editor)`
- `editor.cortar(e: Editor)`
- `editor.pegar(e: Editor)`
- `editor.deshacer(e: Editor)`
- `editor.rehacer(e: Editor)`
- `editor.tamano(e: Editor, tam: i32)` — editor.tamano(e, tam): el tamaño de la letra (13, 16 o 20).
- `editor.dibujar(ui: gui.Ui, e: Editor, ancho: i32, alto: i32) -> bool` — editor.dibujar(ui, e, ancho, alto) -> bool: dibuja el editor y atiende el teclado y el ratón. ancho 0: todo el que queda. Devuelve true si el texto cambió en este cuadro.

## `estadistica`

estadística descriptiva, correlación y regresión (use "estadistica"). Probada contra statistics y numpy de Python.

Tipos: `estadistica.Serie`, `estadistica.Par`, `estadistica.Recta`, `estadistica.Matriz`.

- `estadistica.serie(datos: Vec<f64>) -> Serie`
- `estadistica.nueva() -> Serie`
- `estadistica.agregar(s: Serie, x: f64)`
- `estadistica.cantidad(s: Serie) -> i32`
- `estadistica.dato(s: Serie, i: i32) -> f64`
- `estadistica.ordenada(s: Serie) -> Serie` — Los datos de menor a mayor, en una serie nueva.
- `estadistica.suma(s: Serie) -> f64` — La suma, compensada (Neumaier): el error de redondeo no se acumula.
- `estadistica.media(s: Serie) -> f64`
- `estadistica.minimo(s: Serie) -> f64`
- `estadistica.maximo(s: Serie) -> f64`
- `estadistica.rango(s: Serie) -> f64`
- `estadistica.mediana(s: Serie) -> f64`
- `estadistica.moda(s: Serie) -> f64` — El valor que más se repite; si hay empate, el que apareció primero (statistics.mode).
- `estadistica.varianza(s: Serie) -> f64` — Varianza con n - 1 (statistics.variance). Con menos de 2 datos, NaN.
- `estadistica.varianza_poblacion(s: Serie) -> f64` — Varianza con n (statistics.pvariance).
- `estadistica.desviacion(s: Serie) -> f64`
- `estadistica.desviacion_poblacion(s: Serie) -> f64`
- `estadistica.coeficiente_variacion(s: Serie) -> f64` — Cuánto se aleja la media de la media, relativo a ella: desviación / |media|.
- `estadistica.mad(s: Serie) -> f64` — Desviación mediana absoluta: la mediana de |x - mediana|.
- `estadistica.cuantil(s: Serie, p: f64) -> f64` — El cuantil p (de 0 a 1) con interpolación lineal, como numpy.quantile.
- `estadistica.cuantil_ordenado(o: Serie, p: f64) -> f64` — Lo mismo, para datos que ya están ordenados (se ahorra el orden si se piden varios).
- `estadistica.percentil(s: Serie, p: f64) -> f64` — El percentil p (de 0 a 100), como numpy.percentile.
- `estadistica.iqr(s: Serie) -> f64` — Rango intercuartil: percentil 75 menos percentil 25.
- `estadistica.covarianza(x: Serie, y: Serie) -> f64` — Covarianza con n - 1 (numpy.cov). x e y con el mismo largo, o NaN.
- `estadistica.correlacion(x: Serie, y: Serie) -> f64` — Correlación de Pearson, de -1 a 1 (numpy.corrcoef). NaN si un lado no varía.
- `estadistica.rangos(s: Serie) -> Serie` — Los rangos de los datos (1 es el menor); los empatados reciben el promedio de sus rangos (scipy.stats.rankdata).
- `estadistica.correlacion_spearman(x: Serie, y: Serie) -> f64` — Correlación de Spearman: la de Pearson entre los rangos.
- `estadistica.regresion_lineal(x: Serie, y: Serie) -> Recta` — La recta y = pendiente·x + intercepto que mejor se ajusta (mínimos cuadrados), con su r² (1 - suma de residuos² / suma total²; 1 si y no varía y la recta la acierta).
- `estadistica.predecir(r: Recta, x: f64) -> f64`
- `estadistica.minimos_cuadrados(a: Serie, filas: i32, cols: i32, y: Serie) -> Serie` — Mínimos cuadrados de A·c ≈ y con A de `filas` x `cols` (por filas, dentro de una Serie), con reflexiones de Householder (estable aunque las columnas se parezcan). Devuelve los `cols` coeficientes.
- `estadistica.ajustar_polinomio(x: Serie, y: Serie, grado: i32) -> Serie` — Los coeficientes del polinomio de ese grado que mejor ajusta (x, y), del término independiente al de mayor grado: c[0] + c[1]·x + c[2]·x² ... (numpy.polyfit, pero en el otro orden). Por dentro centra y escala x para que sea estable.
- `estadistica.evaluar_polinomio(c: Serie, x: f64) -> f64` — El valor del polinomio (coeficientes del independiente al de mayor grado) en x.
- `estadistica.bordes(s: Serie, cajas: i32) -> Serie` — `cajas` + 1 bordes entre el mínimo y el máximo (numpy.linspace).
- `estadistica.histograma(s: Serie, cajas: i32) -> Vec<i32>` — Cuántos datos caen en cada caja (numpy.histogram: la última incluye el máximo).
- `estadistica.movil_media(s: Serie, ancho: i32) -> Serie` — Cada ventana de `ancho` datos seguidos da un valor: salen n - ancho + 1 valores.
- `estadistica.movil_desviacion(s: Serie, ancho: i32) -> Serie`
- `estadistica.movil_percentil(s: Serie, ancho: i32, p: f64) -> Serie` — El percentil p (0 a 100) de cada ventana. Mantiene la ventana ordenada y le saca y le pone un dato por paso (n·ancho en total), en vez de ordenar de nuevo cada vez.
- `estadistica.movil_mediana(s: Serie, ancho: i32) -> Serie`
- `estadistica.zscore(s: Serie) -> Serie` — (x - media) / desviación de cada dato (con n - 1, como scipy.stats.zscore(ddof=1)).
- `estadistica.acumulada(s: Serie) -> Serie` — La suma acumulada: el dato i es la suma de los i + 1 primeros.
- `estadistica.normalizar(s: Serie) -> Serie` — Cada dato llevado al rango 0..1.

## `fecha`

fechas, horas, zonas y formato (use "fecha").

Tipos: `fecha.Fecha`, `fecha.Zona`.

- `fecha.fecha(anio: i32, mes: i32, dia: i32, hora: i32, minuto: i32, segundo: i32) -> Fecha`
- `fecha.es_bisiesto(anio: i32) -> bool`
- `fecha.dias_del_mes(anio: i32, mes: i32) -> i32`
- `fecha.dias_desde_civil(anio: i32, mes: i32, dia: i32) -> i64` — Días desde el 1970-01-01 del año, mes y día dados (days_from_civil).
- `fecha.civil_desde_dias(z0: i64) -> Fecha` — La fecha (a las 00:00) de un número de días desde 1970 (civil_from_days).
- `fecha.dia_semana(f: Fecha) -> i32` — 0 domingo, 1 lunes ... 6 sábado.
- `fecha.dia_del_anio(f: Fecha) -> i32` — 1 para el 1 de enero.
- `fecha.de_segundos(s: i64) -> Fecha` — La fecha en UTC de un instante.
- `fecha.a_segundos(f: Fecha) -> i64` — El instante de una fecha leída en UTC.
- `fecha.sumar_segundos(f: Fecha, n: i64) -> Fecha` — La misma fecha corrida n segundos, días, horas o minutos (en el reloj, sin zona: una fecha local más un día es la misma hora del día siguiente).
- `fecha.sumar_dias(f: Fecha, n: i32) -> Fecha`
- `fecha.sumar_meses(f: Fecha, n: i32) -> Fecha` — n meses después (o antes, si es negativo); si el día no existe en ese mes (31 de enero más un mes), queda el último del mes.
- `fecha.diferencia_segundos(a: Fecha, b: Fecha) -> i64` — b - a en segundos y en días enteros (hacia abajo).
- `fecha.diferencia_dias(a: Fecha, b: Fecha) -> i64`
- `fecha.utc() -> Zona`
- `fecha.fija(minutos: i32) -> Zona` — Un desfase fijo en minutos (-180 es UTC−3).
- `fecha.chile() -> Zona`
- `fecha.magallanes() -> Zona`
- `fecha.pascua() -> Zona`
- `fecha.verano_chile(s: i64) -> bool` — Si en el instante s es verano en Chile.
- `fecha.desfase(z: Zona, s: i64) -> i32` — Los minutos que la zona le suma a UTC en el instante s.
- `fecha.local(s: i64, z: Zona) -> Fecha` — La fecha que muestra un reloj en la zona z en el instante s.
- `fecha.instante(f: Fecha, z: Zona) -> i64` — El instante de una fecha local de la zona z. Si esa hora pasa dos veces (cuando termina el verano) es la primera; si no existe (cuando empieza) se usa el desfase de antes del cambio: como zoneinfo de Python con fold=0.
- `fecha.iso(s: i64) -> str` — "2026-10-26T19:30:00Z": el instante en UTC, en ISO 8601.
- `fecha.iso_local(s: i64, z: Zona) -> str` — "2026-10-26T16:30:00-03:00": el instante en la zona z, con su desfase.
- `fecha.de_iso(t0: str) -> Result<i64>` — El instante de un texto ISO 8601: "2026-10-26", "2026-10-26T16:30", "2026-10-26 16:30:05", con fracción de segundo (se descarta), y con "Z", "+HH:MM", "-HH:MM" o "-HHMM" al final; sin zona, se toma como UTC.
- `fecha.nombre_dia(d: i32) -> str`
- `fecha.nombre_mes(m: i32) -> str`
- `fecha.formato(f: Fecha, plantilla: str) -> str` — La fecha con una plantilla, como strftime: %Y año, %m mes, %d día, %H hora, %M minuto, %S segundo (con dos cifras), %j día del año (tres), %A el día de la semana y %B el mes en español ("lunes", "octubre"), %a y %b sus tres primeras letras ("lun", "oct"), %% un %. Lo demás va tal cual.

## `fisica`

cuerpos rígidos en 2D, con gravedad y choques (use "fisica").

Tipos: `fisica.Mundo`, `fisica.Contacto`, `fisica.Rayo`.

- `fisica.mundo(gx: f64, gy: f64) -> Mundo`
- `fisica.circulo(m: Mundo, x: f64, y: f64, r: f64, masa: f64) -> i32` — Un círculo de radio r con centro en (x, y); masa 0 lo deja fijo. Devuelve su número.
- `fisica.caja(m: Mundo, x: f64, y: f64, ancho: f64, alto: f64, masa: f64) -> i32` — Una caja de ancho x alto con centro en (x, y); masa 0 la deja fija.
- `fisica.cuerpos(m: Mundo) -> i32`
- `fisica.x(m: Mundo, c: i32) -> f64`
- `fisica.y(m: Mundo, c: i32) -> f64`
- `fisica.vx(m: Mundo, c: i32) -> f64`
- `fisica.vy(m: Mundo, c: i32) -> f64`
- `fisica.posicion(m: Mundo, c: i32, x: f64, y: f64)`
- `fisica.velocidad(m: Mundo, c: i32, vx: f64, vy: f64)`
- `fisica.restitucion(m: Mundo, c: i32, e: f64)` — Cuánto rebota (0 a 1).
- `fisica.friccion(m: Mundo, c: i32, mu: f64)` — Cuánto frena al rozar (0 nada).
- `fisica.masa(m: Mundo, c: i32) -> f64`
- `fisica.energia_cinetica(m: Mundo) -> f64` — La energía cinética de todos los cuerpos que se mueven.
- `fisica.paso(m: Mundo, dt: f64)` — Avanza el mundo dt segundos.
- `fisica.se_tocan(m: Mundo, i: i32, j: i32) -> bool` — Si dos cuerpos se están tocando ahora.
- `fisica.impulso(m: Mundo, c: i32, jx: f64, jy: f64)` — impulso(m, c, jx, jy): le da un empujón instantáneo al cuerpo (cambia su velocidad en j / masa). Los cuerpos fijos no se mueven.
- `fisica.cuerpo_en(m: Mundo, px: f64, py: f64) -> i32` — cuerpo_en(m, x, y) -> i32: el primer cuerpo (el de número menor) que tiene adentro ese punto, o -1.
- `fisica.contactos_de(m: Mundo, c: i32) -> Vec<i32>` — contactos_de(m, c) -> Vec<i32>: los cuerpos que están tocando a c ahora, en orden.
- `fisica.rayo(m: Mundo, ox: f64, oy: f64, dx0: f64, dy0: f64, maximo: f64) -> Rayo` — rayo(m, ox, oy, dx, dy, maximo) -> Rayo: tira un rayo desde (ox, oy) en la dirección (dx, dy) (no hace falta que sea unitaria; si es (0, 0) no da en nada) hasta `maximo` de distancia, y devuelve el primer cuerpo que toca (si dos están a la misma distancia, el de número menor). Si el origen está adentro de un cuerpo, da en él con t = 0 y la normal opuesta al rayo.

## `grafico`

gráficos de líneas, barras, dispersión e histograma (use "grafico").

Tipos: `grafico.Grafico`, `grafico.Diseno`, `grafico.Datos`.

- `grafico.nuevo(ancho: i32, alto: i32, titulo: str) -> Grafico`
- `grafico.paleta(i: i32) -> i32` — Diez colores bien distintos (los de siempre en gráficos), por número.
- `grafico.color_rgb(r: i32, g: i32, b: i32) -> i32` — Un color a partir de rojo, verde y azul (0 a 255).
- `grafico.color_hex(s: str) -> Result<i32>` — Un color a partir de "#rrggbb" (o "#rgb"). Err si el texto no es un color.
- `grafico.color_nombre(nombre: str) -> Result<i32>` — Un color a partir de su nombre de CSS ("tomato", "navy"...). Err si no existe.
- `grafico.colores_paleta(nombre: str, n: i32) -> Result<Vec<i32>>` — Los n primeros colores de una paleta de lib/colores ("tab10", "tab20", "set1", "set2", "dark2", "paired", "okabe_ito"...), dando la vuelta si n pasa de su largo. "tab10" es la misma de `paleta(i)`. Err si la paleta no existe.
- `grafico.colores_mapa(nombre: str, n: i32) -> Result<Vec<i32>>` — n colores repartidos parejo a lo largo de un mapa continuo de lib/colores ("viridis", "magma", "turbo", "coolwarm"...), de punta a punta (con n = 1, el del medio): sirven para teñir n líneas o barras que siguen un orden. Err si el mapa no existe.
- `grafico.ejes(g: Grafico, etiqueta_x: str, etiqueta_y: str)`
- `grafico.limites(g: Grafico, xmin: f64, xmax: f64, ymin: f64, ymax: f64)` — Fija los límites de los ejes en vez de calcularlos (mínimo y máximo de cada uno).
- `grafico.series(g: Grafico) -> i32`
- `grafico.linea(g: Grafico, nombre: str, xs: Vec<f64>, ys: Vec<f64>, color: i32)` — Una línea que une los puntos (xs[i], ys[i]). Un NaN en ys corta la línea.
- `grafico.puntos(g: Grafico, nombre: str, xs: Vec<f64>, ys: Vec<f64>, color: i32)` — Puntos sueltos (dispersión).
- `grafico.categorias(g: Grafico, nombres: Vec<str>)` — Los nombres de las categorías del eje x de las barras.
- `grafico.barras(g: Grafico, nombre: str, valores: Vec<f64>, color: i32)` — Una serie de barras: valores[i] es la altura en la categoría i.
- `grafico.histograma(g: Grafico, nombre: str, datos: Vec<f64>, cajas: i32, color: i32)` — Un histograma de los datos en `cajas` cajas.
- `grafico.marcas(minimo: f64, maximo: f64, objetivo: i32) -> Vec<f64>` — Las marcas de un eje que cubre de `minimo` a `maximo`: pasos de 1, 2 o 5 por una potencia de 10, desde la marca de abajo hasta la de arriba, con unas `objetivo` marcas. Si el rango es un solo valor, se abre a su alrededor.
- `grafico.etiquetas(m: Vec<f64>) -> Vec<str>` — Las marcas escritas, todas con los mismos decimales ("0.5", "1.0", "1.5").
- `grafico.bordes(datos: Vec<f64>, cajas: i32) -> Vec<f64>` — Los bordes de las cajas: `cajas` + 1 valores entre el mínimo y el máximo (como numpy.linspace).
- `grafico.cuentas(datos: Vec<f64>, cajas: i32) -> Vec<i32>` — Cuántos datos caen en cada caja, como numpy.histogram(datos, bins=cajas).
- `grafico.diseno(g: Grafico) -> Diseno` — Rectángulo del gráfico, rangos de los ejes y marcas, calculados de las series.
- `grafico.px(d: Diseno, x: f64) -> i32` — El píxel (columna) de un valor de x, y el (fila) de un valor de y.
- `grafico.py(d: Diseno, y: f64) -> i32`
- `grafico.marcas_x(d: Diseno) -> i32` — Cuántas marcas tiene cada eje y dónde está la número i.
- `grafico.marcas_y(d: Diseno) -> i32`
- `grafico.marca_x(d: Diseno, i: i32) -> f64`
- `grafico.marca_y(d: Diseno, i: i32) -> f64`
- `grafico.etiqueta_y(d: Diseno, i: i32) -> str` — La etiqueta de la marca número i de y (o de x) del diseño.
- `grafico.etiqueta_x(d: Diseno, i: i32) -> str`
- `grafico.dibujar(g: Grafico) -> lienzo.Lienzo` — Dibuja el gráfico entero en un lienzo nuevo del tamaño de `nuevo`.
- `grafico.guardar_png(g: Grafico, ruta: str) -> Result<i32>` — Dibuja y guarda como PNG. Devuelve los bytes escritos.

## `grafos`

grafos con pesos y búsqueda de caminos (use "grafos").

Tipos: `grafos.Grafo`, `grafos.Conjuntos`, `grafos.Monticulo`, `grafos.Caminos`, `grafos.Grilla`.

- `grafos.grafo(n: i32, dirigido: bool) -> Grafo`
- `grafos.agregar_nodo(g: Grafo) -> i32` — Agrega un nodo y devuelve su número.
- `grafos.nodos(g: Grafo) -> i32`
- `grafos.aristas(g: Grafo) -> i32`
- `grafos.arista(g: Grafo, a: i32, b: i32, peso: f64) -> i32` — arista(g, a, b, peso): une a con b (y b con a si el grafo no es dirigido). Devuelve el número de la arista. Si a o b no son nodos del grafo es un panic.
- `grafos.arista_desde(g: Grafo, e: i32) -> i32`
- `grafos.arista_hasta(g: Grafo, e: i32) -> i32`
- `grafos.arista_peso(g: Grafo, e: i32) -> f64`
- `grafos.vecinos(g: Grafo, v: i32) -> Vec<i32>` — Los vecinos de v (a donde se puede ir desde v), en el orden en que se agregaron.
- `grafos.bfs(g: Grafo, origen: i32) -> Vec<i32>` — bfs(g, origen) -> Vec<i32>: cuántas aristas hay que cruzar como mínimo para llegar a cada nodo (-1 si no se llega).
- `grafos.recorrido_ancho(g: Grafo, origen: i32) -> Vec<i32>` — recorrido_ancho(g, origen) -> Vec<i32>: los nodos alcanzables, en el orden en que los visita una búsqueda en anchura.
- `grafos.recorrido_profundo(g: Grafo, origen: i32) -> Vec<i32>` — recorrido_profundo(g, origen) -> Vec<i32>: los nodos alcanzables en el orden en que los visita una búsqueda en profundidad (el mismo de la versión recursiva, pero sin recursión: no se queda sin pila con grafos grandes).
- `grafos.componentes(g: Grafo) -> Vec<i32>` — componentes(g) -> Vec<i32>: para cada nodo, el número de su grupo conectado. Los grupos se numeran desde 0 en el orden de su nodo más chico. En un grafo dirigido no se mira la dirección.
- `grafos.cantidad_componentes(g: Grafo) -> i32` — cuántos grupos conectados hay
- `grafos.orden_topologico(g: Grafo) -> Result<Vec<i32>>` — orden_topologico(g) -> Result<Vec<i32>>: los nodos de modo que cada arista vaya de uno anterior a uno posterior (entre los que están listos sale primero el que se liberó antes, y al principio el de número menor). Error si el grafo tiene un ciclo (o si no es dirigido y tiene alguna arista).
- `grafos.dijkstra(g: Grafo, origen: i32) -> Caminos` — dijkstra(g, origen) -> Caminos. Los pesos negativos no están permitidos (es un panic).
- `grafos.alcanza(c: Caminos, v: i32) -> bool` — alcanza(c, v) -> bool: se puede llegar a v desde el origen.
- `grafos.distancia(c: Caminos, v: i32) -> f64` — distancia(c, v) -> f64: el largo del camino más corto hasta v (-1.0 si no se llega).
- `grafos.camino(c: Caminos, v: i32) -> Vec<i32>` — camino(c, v) -> Vec<i32>: los nodos del camino más corto desde el origen hasta v, los dos incluidos (vacío si no se llega).
- `grafos.arbol_minimo(g: Grafo) -> Vec<i32>` — arbol_minimo(g) -> Vec<i32>: los números de las aristas del árbol (o bosque) de expansión mínima, en el orden en que se eligieron (de menor a mayor peso). Mira las aristas sin dirección.
- `grafos.peso_total(g: Grafo, lista: Vec<i32>) -> f64` — peso_total(g, lista) -> f64: la suma de los pesos de esas aristas.
- `grafos.grilla(ancho: i32, alto: i32) -> Grilla` — grilla(ancho, alto) -> Grilla: todas las casillas libres. La casilla (x, y) es el número y * ancho + x.
- `grafos.pared(gr: Grilla, x: i32, y: i32)` — pared(gr, x, y) / quitar_pared(gr, x, y): fuera de la grilla no hace nada.
- `grafos.quitar_pared(gr: Grilla, x: i32, y: i32)`
- `grafos.libre(gr: Grilla, x: i32, y: i32) -> bool` — libre(gr, x, y) -> bool: adentro y sin pared.
- `grafos.casilla_x(gr: Grilla, c: i32) -> i32`
- `grafos.casilla_y(gr: Grilla, c: i32) -> i32`
- `grafos.a_estrella(gr: Grilla, x0: i32, y0: i32, x1: i32, y1: i32, diagonal: bool) -> Vec<i32>` — a_estrella(gr, x0, y0, x1, y1, diagonal) -> Vec<i32>: las casillas del camino más corto de (x0, y0) a (x1, y1), las dos incluidas (vacío si alguna está ocupada o no hay camino). Sin diagonal se mueve en 4 direcciones; con diagonal en 8, sin pasar en diagonal entre dos casillas si una de las dos de al lado es pared.
- `grafos.costo(gr: Grilla, ruta: Vec<i32>) -> f64` — costo(gr, ruta) -> f64: lo que cuesta recorrer esa lista de casillas (1 por paso recto, raíz de 2 en diagonal).

## `gui`

lib/gui.scar -- la librería gráfica de SCAR.

Tipos: `gui.Ui`, `gui.Serie`, `gui.Lista`, `gui.Onda`, `gui.Zoom`, `gui.Tabla`, `gui.Lienzo`, `gui.Menu`.

- `gui.color(r: i32, g: i32, b: i32) -> i32` — gui.color(r, g, b) -> i32: un color para gui.texto_color, gui.pintar...
- `gui.aclarar(c: i32, t: i32) -> i32` — gui.aclarar(c, t) -> i32: c mezclado con blanco (t de 1 a 100) o con negro (t de -1 a -100).
- `gui.ventana(titulo: str, ancho: i32, alto: i32) -> Ui` — gui.ventana(titulo, ancho, alto): abre la ventana. Si no se puede (no hay pantalla ni SDL2), es un panic con el motivo.
- `gui.claro(ui: Ui)` — gui.claro(ui) / gui.oscuro(ui): el tema de colores.
- `gui.oscuro(ui: Ui)`
- `gui.acento(ui: Ui, r: i32, g: i32, b: i32)` — gui.acento(ui, r, g, b): el color de los botones y lo marcado.
- `gui.abierta(ui: Ui) -> bool` — gui.abierta(ui): muestra el cuadro anterior, lee lo que pasó (clics, teclas) y empieza uno nuevo. false cuando la persona cierra la ventana: ahí la ventana ya quedó cerrada.
- `gui.margen(ui: Ui, px: i32)` — gui.cerrar(ui): cierra la ventana antes de que la cierre la persona. gui.margen(ui, px): el margen alrededor de la ventana (16 de entrada; 0 para que las piezas lleguen al borde, como en un IDE). Vale desde el próximo cuadro.
- `gui.preguntar_al_cerrar(ui: Ui, si: bool)` — gui.preguntar_al_cerrar(ui, si): con true, la X de la ventana no la cierra: gui.pidio_cerrar(ui) pasa a dar true y el programa decide (por ejemplo preguntar si guardar) y cierra con gui.cerrar. Un cierre forzado (SCAR_SDL_MAX_FRAMES en las pruebas) cierra igual.
- `gui.pidio_cerrar(ui: Ui) -> bool` — gui.pidio_cerrar(ui) -> bool: la persona apretó la X (con preguntar_al_cerrar). Queda en true hasta gui.olvidar_cierre(ui) o gui.cerrar(ui).
- `gui.olvidar_cierre(ui: Ui)`
- `gui.cerrar(ui: Ui)`
- `gui.fila(ui: Ui)` — gui.fila(ui) ... gui.fin_fila(ui): lo de adentro va lado a lado.
- `gui.fin_fila(ui: Ui)`
- `gui.ancho_libre(ui: Ui) -> i32` — gui.ancho_libre(ui) -> i32: cuánto ancho queda para la próxima pieza.
- `gui.columna(ui: Ui, ancho: i32)` — gui.columna(ui, ancho): lo que sigue va en una columna de ese ancho (0 o menos: todo lo que queda a la derecha). Otra gui.columna empieza la siguiente, a la derecha de esta y a la misma altura; gui.fin_columnas(ui) vuelve a usar todo el ancho, debajo de la columna más larga.
- `gui.fin_columnas(ui: Ui)`
- `gui.espacio(ui: Ui, px: i32)` — gui.espacio(ui, px): un hueco vertical (o horizontal, en una fila).
- `gui.separador(ui: Ui)` — gui.separador(ui): una línea de lado a lado.
- `gui.texto(ui: Ui, s: str)`
- `gui.texto_tenue(ui: Ui, s: str)`
- `gui.titulo(ui: Ui, s: str)`
- `gui.subtitulo(ui: Ui, s: str)` — gui.subtitulo(ui, s): un texto más grande que el normal, más chico que el título.
- `gui.texto_color(ui: Ui, s: str, c: i32)` — gui.texto_color(ui, s, color): un texto de otro color (gui.color(r, g, b), o uno del tema: ui.c_bien, ui.c_aviso, ui.c_mal, ui.c_acento...).
- `gui.etiqueta(ui: Ui, s: str, c: i32)` — gui.etiqueta(ui, s, color): el texto sobre un rectángulo de ese color (un estado: "EN CALMA", "DISPARADO").
- `gui.parrafo(ui: Ui, s: str)` — gui.parrafo(ui, s): un texto largo, partido en líneas para que quepa en el ancho que queda (entre palabras; "\n" corta la línea).
- `gui.boton(ui: Ui, s: str) -> bool` — gui.boton(ui, s) -> bool: true en el cuadro en que se le hizo clic.
- `gui.casilla(ui: Ui, s: str, marcada: bool) -> bool` — gui.casilla(ui, s, marcada) -> bool: la casilla con su texto; devuelve si queda marcada (cambia con un clic en la casilla o en el texto).
- `gui.campo(ui: Ui, etiqueta: str, valor: str) -> str` — gui.campo(ui, etiqueta, valor) -> str: un campo de texto de una línea. Un clic adentro lo activa; lo que se escribe se agrega, Borrar quita la última letra, Enter o Esc lo sueltan (también un clic afuera). Devuelve el texto.
- `gui.campo_largo(ui: Ui, etiqueta: str, valor: str, ancho: i32) -> str` — gui.campo_largo(ui, etiqueta, valor, ancho) -> str: un campo de texto del ancho pedido (0: todo el que queda; la etiqueta puede ser ""). Como gui.campo, pero si el texto no cabe se ve el final, y la tecla Enter no le saca el foco (se la deja al programa: `ui.foco == ui.id` justo después de llamarlo dice que tiene el foco, y gui.tecla_pulsada(ui, 40) que se apretó Enter).
- `gui.deslizador(ui: Ui, etiqueta: str, valor: f64, min_v: f64, max_v: f64) -> f64` — gui.deslizador(ui, etiqueta, valor, min, max) -> f64: arrastrando la perilla (o con un clic en la barra) el valor va de min a max.
- `gui.opciones(ui: Ui, lista: str, elegida: i32) -> i32` — gui.opciones(ui, "Rojo|Verde|Azul", elegida) -> i32: una de varias, lado a lado; devuelve la elegida (0 la primera).
- `gui.pestanas(ui: Ui, lista: str, elegida: i32) -> i32` — gui.pestanas(ui, "Uno|Dos|Tres", elegida) -> i32: una barra de pestañas de lado a lado; devuelve la elegida (0 la primera). Lo que se muestra debajo lo decide el programa según ese número.
- `gui.pestanas_cerrables(ui: Ui, lista: str, elegida: i32) -> i32` — gui.pestanas_cerrables(ui, "Uno|Dos|Tres", elegida) -> i32: lo mismo, pero cada pestaña trae una "x" a la derecha. Si se hace clic en una x, no cambia la elegida: se avisa con gui.pestana_cerrada(ui), que da el número de la pestaña (o -1 si no se cerró ninguna en este cuadro). Quitarla de la lista es cosa del programa.
- `gui.pestana_cerrada(ui: Ui) -> i32`
- `gui.menu_nuevo() -> Menu`
- `gui.menu_agregar(m: Menu, titulo: str, opciones: str)`
- `gui.menu_de(codigo: i32) -> i32`
- `gui.item_de(codigo: i32) -> i32`
- `gui.menu_cerrar(m: Menu)`
- `gui.menu_barra(ui: Ui, m: Menu)` — La barra: una tira del ancho de la ventana con los títulos. Va antes que las demás piezas.
- `gui.menu_desplegable(ui: Ui, m: Menu) -> i32` — La lista abierta, dibujada encima de todo (se llama al final del cuadro). Devuelve menu * 1000 + opción si se eligió una, y -1 si no.
- `gui.lista_nueva() -> Lista` — gui.lista_nueva() -> Lista, gui.lista_agregar(lista, s), gui.lista_vaciar(lista): las filas de una gui.lista.
- `gui.lista_agregar(l: Lista, s: str)`
- `gui.lista_vaciar(l: Lista)`
- `gui.lista(ui: Ui, l: Lista, elegida: i32, filas: i32) -> i32` — gui.lista(ui, lista, elegida, filas) -> i32: una lista de `filas` de alto donde se elige una con un clic; devuelve la elegida (-1: ninguna). Si hay más de las que caben, se recorre con la rueda del ratón o con la barra de la derecha (un clic o arrastrándola).
- `gui.progreso(ui: Ui, fraccion: f64)` — gui.progreso(ui, fraccion): una barra llena de 0.0 a 1.0.
- `gui.decimales(x: f64, n: i32) -> str` — gui.decimales(x, n) -> str: x con n decimales, redondeado ("3.14" para pi y 2). Para mostrar un f64 sin todos sus dígitos (a_texto(x) los muestra todos).
- `gui.serie() -> Serie` — gui.serie() -> Serie y gui.agregar(serie, valor): los datos de un gráfico.
- `gui.agregar(s: Serie, v: f64)`
- `gui.barras(ui: Ui, s: Serie, alto: i32)` — gui.barras(ui, serie, alto): una barra por valor (los negativos cuentan como 0).
- `gui.lineas(ui: Ui, s: Serie, alto: i32)` — gui.lineas(ui, serie, alto): los valores unidos por líneas.
- `gui.lienzo(ui: Ui, alto: i32) -> Lienzo` — gui.lienzo(ui, alto) -> Lienzo: reserva un rectángulo de ese alto y todo el ancho que queda, con el fondo del panel. Hasta la próxima pieza, lo que se dibuja con gui.pintar, gui.trazo y gui.rotular queda recortado adentro. Las coordenadas son de la ventana: el rectángulo empieza en (l.x, l.y) y mide l.ancho x l.alto.
- `gui.pintar(ui: Ui, x: i32, y: i32, w: i32, h: i32, c: i32)` — gui.pintar(ui, x, y, ancho, alto, color): un rectángulo lleno.
- `gui.trazo(ui: Ui, x1: i32, y1: i32, x2: i32, y2: i32, c: i32)` — gui.trazo(ui, x1, y1, x2, y2, color): una línea.
- `gui.rotular(ui: Ui, x: i32, y: i32, s: str, tam: i32, c: i32) -> i32` — gui.rotular(ui, x, y, s, tam, color) -> i32: un texto con la esquina de arriba a la izquierda en (x, y); tam es la altura de la letra (13, 16, 20 o 28: se usa el más cercano). Devuelve el ancho que ocupó.
- `gui.reservar(ui: Ui, w: i32, h: i32) -> Lienzo` — gui.reservar(ui, ancho, alto) -> Lienzo: deja un hueco de ese tamaño donde iría la próxima pieza (en una fila, a la derecha de la anterior) y no pinta nada: es para armar piezas propias, como las de lib/tablero.
- `gui.circulo(ui: Ui, x: i32, y: i32, radio: i32, c: i32)` — gui.circulo(ui, x, y, radio, color): un círculo lleno con el centro en (x, y).
- `gui.marco(ui: Ui, x: i32, y: i32, w: i32, h: i32, grosor: i32, c: i32)` — gui.marco(ui, x, y, ancho, alto, grosor, color): el borde de un rectángulo.
- `gui.alto_texto(tam: i32) -> i32` — gui.alto_texto(tam) -> i32: cuánto mide de alto una línea escrita con esa letra.
- `gui.ancho_texto(s: str, tam: i32) -> i32` — gui.ancho_texto(s, tam) -> i32: cuánto mide s escrito con esa letra.
- `gui.encima(ui: Ui, x: i32, y: i32, w: i32, h: i32) -> bool` — gui.encima(ui, x, y, ancho, alto) -> bool: el ratón está sobre ese rectángulo.
- `gui.apretado_en(ui: Ui, x: i32, y: i32, w: i32, h: i32) -> bool` — gui.apretado_en(ui, x, y, ancho, alto) -> bool: en este cuadro se apretó el botón del ratón adentro de ese rectángulo (no espera a que se suelte: para piezas que arrastran o ponen un cursor, como lib/editor).
- `gui.soltado(ui: Ui) -> bool` — gui.soltado(ui) -> bool: en este cuadro se soltó el botón del ratón.
- `gui.escrito(ui: Ui) -> str` — gui.escrito(ui) -> str: el texto que escribió la persona en este cuadro ("" si nada).
- `gui.pieza_id(ui: Ui) -> i32` — gui.pieza_id(ui) -> i32: un número propio para una pieza hecha a mano (para ui.foco y ui.activo).
- `gui.recortar(ui: Ui, x: i32, y: i32, w: i32, h: i32)` — gui.recortar(ui, x, y, ancho, alto): lo que se dibuje después queda adentro de ese rectángulo, hasta la próxima pieza.
- `gui.sin_recortar(ui: Ui)` — gui.sin_recortar(ui): vuelve a dibujar en toda la ventana.
- `gui.rueda(ui: Ui) -> i32` — gui.rueda(ui) -> i32: cuánto se movió la rueda del ratón en este cuadro (positivo: hacia arriba, lejos de la persona; 0: no se movió). Junto con gui.encima, para que una pieza hecha a mano responda a la rueda.
- `gui.raton_x(ui: Ui) -> i32` — gui.raton_x(ui), gui.raton_y(ui) -> i32: dónde está el ratón, en píxeles de la ventana; gui.raton_abajo(ui) -> bool: el botón está apretado ahora (para piezas hechas a mano que se arrastran, como el mapa del sismógrafo).
- `gui.raton_y(ui: Ui) -> i32`
- `gui.raton_abajo(ui: Ui) -> bool`
- `gui.tecla(ui: Ui, codigo: i32) -> bool` — gui.tecla(ui, codigo) -> bool: se pulsó esa tecla en este cuadro (el código es el scancode de SDL: Espacio=44, Enter=40, Esc=41, Tab=43, flechas: der=79 izq=80 abajo=81 arriba=82, A=4 ... Z=29, 1=30 ... 0=39). Mientras un campo de texto tiene el foco, las teclas son para el campo.
- `gui.tecla_pulsada(ui: Ui, codigo: i32) -> bool` — gui.tecla_pulsada(ui, codigo) -> bool: como gui.tecla, pero sin importar quién tiene el foco: para una pieza que toma el teclado ella misma (lib/editor).
- `gui.clic_en(ui: Ui, x: i32, y: i32, w: i32, h: i32) -> bool` — gui.clic_en(ui, x, y, ancho, alto) -> bool: se hizo clic en ese rectángulo (se apretó y se soltó adentro), como un botón invisible.
- `gui.onda_nueva(cap: i32) -> Onda` — gui.onda_nueva(cap) -> Onda: una onda centrada en cero de `cap` muestras; gui.onda_nivel(cap, maximo) -> Onda: barras de 0 a `maximo`.
- `gui.onda_nivel(cap: i32, maximo: f64) -> Onda`
- `gui.onda_agregar(o: Onda, v: f64, marcada: bool)` — gui.onda_agregar(onda, valor, marcada): una muestra más.
- `gui.onda_valor(o: Onda, k: i32) -> f64` — gui.onda_valor(onda, k) -> f64 y gui.onda_marcada(onda, k) -> bool: la muestra número k (contando desde la primera que se agregó; las visibles son de onda.n - onda.cap a onda.n - 1). Fuera de eso, 0 y false.
- `gui.onda_marcada(o: Onda, k: i32) -> bool`
- `gui.onda_pico(o: Onda) -> f64` — gui.onda_pico(onda) -> f64: el mayor |valor| visible (1.0 si todo es 0): la escala de una onda centrada.
- `gui.onda(ui: Ui, o: Onda, alto: i32, izquierda: str, derecha: str)` — gui.onda(ui, onda, alto, izquierda, derecha): la dibuja de todo el ancho que queda, con un rótulo arriba a cada lado ("" para ninguno). Cada columna de píxeles muestra el mínimo y el máximo de las muestras que le tocan, así no se pierde un pico entre dos píxeles aunque haya miles de muestras.
- `gui.zoom_nuevo() -> Zoom` — gui.zoom_nuevo() -> Zoom: sin acercar (se ve todo).
- `gui.zoom_reiniciar(z: Zoom)` — gui.zoom_reiniciar(zoom): vuelve a verse todo.
- `gui.zoom_activo(z: Zoom) -> bool` — gui.zoom_activo(zoom) -> bool: está acercado.
- `gui.zoom_desde(z: Zoom) -> f64` — gui.zoom_desde(zoom) / gui.zoom_hasta(zoom) -> f64: lo que se ve, como fracción del total (de 0 a 1).
- `gui.zoom_hasta(z: Zoom) -> f64`
- `gui.zoom_inicio(z: Zoom, inicio: f64, fin: f64) -> f64` — gui.zoom_inicio(zoom, inicio, fin) / gui.zoom_fin(zoom, inicio, fin) -> f64: si todo va de `inicio` a `fin` (una hora, un número de muestra), de dónde a dónde va lo que se ve. Para el gui.eje de abajo de las ondas.
- `gui.zoom_fin(z: Zoom, inicio: f64, fin: f64) -> f64`
- `gui.onda_zoom(ui: Ui, o: Onda, alto: i32, izquierda: str, derecha: str, z: Zoom)` — gui.onda_zoom(ui, onda, alto, izquierda, derecha, zoom): como gui.onda, pero muestra la parte que dice `zoom`, y la rueda y el arrastre sobre ella lo cambian. Una onda centrada sin escala fija se escala con lo que se ve: al acercarse a algo chico, se ve grande.
- `gui.eje(ui: Ui, inicio: f64, fin: f64, cada: f64, rotulo: fn(f64) -> str)` — gui.eje(ui, inicio, fin, cada, rotulo): una regla de todo el ancho que queda, que va de `inicio` (a la izquierda) a `fin` (a la derecha), con una marca y su texto en cada múltiplo de `cada`. `rotulo` es la fn que convierte un valor en su texto (una hora, un número con unidades). Debajo de un gui.onda del mismo ancho, las marcas caen donde corresponde.
- `gui.paso_eje(rango: f64, marcas: i32) -> f64` — gui.paso_eje(rango, marcas) -> f64: un paso "redondo" (1, 2 o 5 por una potencia de 10) para que un eje que abarca `rango` tenga más o menos `marcas` marcas. Al acercarse con un gui.Zoom el rango cambia, y las marcas también.
- `gui.tabla_nueva(titulos: str) -> Tabla` — gui.tabla_nueva("Estación|Nivel|Estado") -> Tabla; gui.tabla_fila(tabla, "ARICA|1.21 m|normal") agrega una fila; gui.tabla_color(tabla, columna, color) pinta esa celda de la última fila; gui.tabla_vaciar(tabla) la deja sin filas (para llenarla de nuevo cuando cambian los datos).
- `gui.tabla_fila(t: Tabla, fila: str)`
- `gui.tabla_color(t: Tabla, columna: i32, c: i32)`
- `gui.tabla_vaciar(t: Tabla)`
- `gui.tabla(ui: Ui, t: Tabla) -> i32` — gui.tabla(ui, tabla) -> i32: las filas con las columnas alineadas (cada una del ancho de su texto más largo; la última se estira); devuelve la fila en que se hizo clic, o -1.

## `https`

pedidos HTTP y HTTPS con la misma interfaz que lib/web (use "https").

Tipos: `https.Estado`.

- `https.enviar_con_ca(metodo: str, url: str, o: web.Opciones, cuerpo: codigos.Datos, ca: str) -> Result<web.Respuesta>` — Un pedido con el método, la URL, las opciones, un cuerpo (bytes; vacío si no hay) y el archivo de certificados de confianza `ca` ("" = los del sistema). Err solo si no hubo respuesta: un 404 o un 500 llegan como Ok con su código.
- `https.enviar(metodo: str, url: str, o: web.Opciones, cuerpo: codigos.Datos) -> Result<web.Respuesta>` — Como enviar_con_ca, con los certificados de SCAR_HTTPS_CA si esa variable de entorno existe.
- `https.obtener_con(url: str, o: web.Opciones) -> Result<web.Respuesta>`
- `https.obtener(url: str) -> Result<web.Respuesta>`
- `https.enviar_texto(url: str, tipo: str, cuerpo: str, o: web.Opciones) -> Result<web.Respuesta>` — POST de un texto con el Content-Type dado.
- `https.enviar_json(url: str, doc: json.Doc, o: web.Opciones) -> Result<web.Respuesta>` — POST de un documento de lib/json (Content-Type: application/json).
- `https.enviar_formulario(url: str, p: web.Pares, o: web.Opciones) -> Result<web.Respuesta>` — POST de un formulario (application/x-www-form-urlencoded).
- `https.cuerpo_texto(r: web.Respuesta) -> Result<str>` — El cuerpo como texto (Err si no es UTF-8).
- `https.json_de(r: web.Respuesta) -> Result<json.Doc>` — El cuerpo leído como JSON.
- `https.exito(r: web.Respuesta) -> bool` — ¿Salió bien (código 200 a 299)?

## `imagen`

leer y guardar imágenes (use "imagen").

Tipos: `imagen.Bytes`.

- `imagen.a_bmp(l: lienzo.Lienzo) -> Vec<i32>` — Los bytes de un BMP de 24 bits con la imagen de l (el alfa se pierde).
- `imagen.a_bmp32(l: lienzo.Lienzo) -> Vec<i32>` — Los bytes de un BMP de 32 bits con alfa (BITMAPV4HEADER, BI_BITFIELDS).
- `imagen.guardar_bmp(l: lienzo.Lienzo, ruta: str) -> Result<i32>` — Guarda l como BMP de 24 bits; devuelve cuántos bytes escribió.
- `imagen.guardar_bmp32(l: lienzo.Lienzo, ruta: str) -> Result<i32>` — Guarda l como BMP de 32 bits con alfa; devuelve cuántos bytes escribió.
- `imagen.leer_bytes(ruta: str) -> Result<Vec<i32>>` — Todos los bytes de un archivo.
- `imagen.de_bmp(bytes: Vec<i32>) -> Result<lienzo.Lienzo>` — La imagen de los bytes de un BMP. Como toda fn que recibe un Vec, se queda con él.
- `imagen.leer_bmp(ruta: str) -> Result<lienzo.Lienzo>` — Lee un BMP de 24 o 32 bits.
- `imagen.a_png(l: lienzo.Lienzo) -> Vec<i32>` — Los bytes de un PNG con la imagen de l.
- `imagen.guardar_png(l: lienzo.Lienzo, ruta: str) -> Result<i32>` — Guarda l como PNG; devuelve cuántos bytes escribió.
- `imagen.de_png(bytes: Vec<i32>) -> Result<lienzo.Lienzo>` — La imagen de los bytes de un PNG. Como toda fn que recibe un Vec, se queda con él.
- `imagen.leer_png(ruta: str) -> Result<lienzo.Lienzo>` — Lee un PNG (ver arriba qué tipos).

## `json`

JSON completo (use "json"): leer a un árbol, buscar por ruta, armar y escribir.

Tipos: `json.Json`, `json.Doc`, `json.Salida`.

- `json.json_byte(j: Json, i: i32) -> i32`
- `json.json_actual(j: Json) -> i32`
- `json.json_espacios(j: Json)`
- `json.json_falla(j: Json, que: str) -> bool`
- `json.json_hex(c: i32) -> i32`
- `json.json_u16(j: Json) -> i32` — 4 dígitos hex desde j.pos (-1 si no lo son).
- `json.json_cadena(j: Json) -> str` — Un str JSON (j.pos en la comilla de apertura). En `j.error` si está mal.
- `json.json_hoja(j: Json, ruta: str, valor: str)`
- `json.json_hijo(ruta: str, nombre: str) -> str`
- `json.json_es_numero(t: str) -> bool`
- `json.json_leer(bytes: Vec<i32>) -> Result<Json>` — Lee el JSON de `bytes` (cada uno 0..255) como una lista plana de hojas, con su ruta. Err con la posición si está mal. (Desde el árbol de analizar().)
- `json.json_hojas(d: Doc, nodo: i32, ruta: str, j: Json)`
- `json.json_cantidad(j: Json) -> i32`
- `json.json_ruta(j: Json, k: i32) -> str` — Ruta y valor de la hoja k ("" fuera de rango).
- `json.json_texto(j: Json, k: i32) -> str`
- `json.json_buscar(j: Json, ruta: str) -> str` — El valor de la primera hoja con esa ruta exacta ("" si no está).
- `json.json_numero(t: str) -> f64` — Un número JSON como f64 (0.0 si no es un número).
- `json.doc_i32(v: Vec<i32>, i: i32) -> i32`
- `json.doc_str(v: Vec<str>, i: i32) -> str`
- `json.doc_campo(d: Doc, campo: i32, i: i32) -> i32`
- `json.doc_nombre(d: Doc, i: i32) -> str`
- `json.doc_valor(d: Doc, i: i32) -> str`
- `json.doc_tipo(d: Doc, nodo: i32) -> i32`
- `json.doc_vacio() -> Doc`
- `json.doc_nodo(d: Doc, tipo: i32, nombre: str, valor: str) -> i32` — Un nodo nuevo, suelto (todavía no cuelga de nadie). Devuelve su número.
- `json.doc_enganchar(d: Doc, padre: i32, hijo: i32)` — `hijo` pasa a ser el último hijo de `padre`.
- `json.arbol_valor(j: Json, d: Doc, padre: i32, nombre: str, profundidad: i32) -> bool` — Un valor cualquiera en j.pos, colgado de `padre` (-1: es la raíz) con ese nombre.
- `json.analizar(bytes: Vec<i32>) -> Result<Doc>` — Lee el JSON de `bytes` (cada uno 0..255) a un árbol. Err con la posición si está mal.
- `json.bytes_de(s: str) -> Vec<i32>` — Los bytes UTF-8 de un str. (s[i] recorre el texto desde el principio: para un documento grande conviene leer los bytes de un archivo o de la red.)
- `json.analizar_texto(s: str) -> Result<Doc>`
- `json.elemento(d: Doc, nodo: i32, i: i32) -> i32` — El elemento número `i` de un arreglo, o el hijo número `i` de un objeto (-1 si no hay).
- `json.hijo(d: Doc, nodo: i32, clave: str) -> i32` — El hijo de un objeto con esa clave (-1 si no hay). Si la clave se repite, el último, como el diccionario de Python.
- `json.nodo(d: Doc, ruta: str) -> i32` — El nodo de una ruta como "sismos.0.lugar" (-1 si no existe). "" es la raíz.
- `json.existe(d: Doc, ruta: str) -> bool`
- `json.tipo(d: Doc, ruta: str) -> str` — "nulo", "booleano", "numero", "texto", "arreglo" u "objeto" ("" si la ruta no existe).
- `json.texto(d: Doc, ruta: str) -> str` — El valor de un texto, de un número (tal como vino) o de un booleano; "" si no existe, es nulo o es un arreglo o un objeto.
- `json.texto_o(d: Doc, ruta: str, defecto: str) -> str`
- `json.numero(d: Doc, ruta: str) -> f64` — Un número como f64 (0.0 si no existe o no es un número).
- `json.numero_o(d: Doc, ruta: str, defecto: f64) -> f64`
- `json.entero(d: Doc, ruta: str) -> i64` — Un número entero como i64 (0 si no existe o no es un número). Con fracción o exponente, se trunca hacia cero; más allá de ±9.2e18 queda en el extremo.
- `json.booleano(d: Doc, ruta: str) -> bool` — true solo si es el booleano true.
- `json.largo(d: Doc, ruta: str) -> i32` — Cuántos elementos tiene un arreglo o cuántas claves un objeto (0 en lo demás).
- `json.clave(d: Doc, ruta: str, i: i32) -> str` — La clave número `i` de un objeto ("" si no hay).
- `json.nuevo_objeto() -> Doc`
- `json.nuevo_arreglo() -> Doc`
- `json.poner_texto(d: Doc, padre: i32, clave: str, valor: str) -> i32` — poner_*: en un objeto, con su clave. Devuelven el número del nodo nuevo (-1 si `padre` no es un objeto ni un arreglo).
- `json.poner_numero(d: Doc, padre: i32, clave: str, valor: f64) -> i32`
- `json.poner_entero(d: Doc, padre: i32, clave: str, valor: i64) -> i32`
- `json.poner_numero_texto(d: Doc, padre: i32, clave: str, valor: str) -> i32` — Un número ya escrito (por ejemplo 1.50 o 1E5); si no es un número JSON, queda como nulo.
- `json.poner_bool(d: Doc, padre: i32, clave: str, valor: bool) -> i32`
- `json.poner_nulo(d: Doc, padre: i32, clave: str) -> i32`
- `json.poner_objeto(d: Doc, padre: i32, clave: str) -> i32`
- `json.poner_arreglo(d: Doc, padre: i32, clave: str) -> i32`
- `json.agregar_texto(d: Doc, padre: i32, valor: str) -> i32` — agregar_*: al final de un arreglo.
- `json.agregar_numero(d: Doc, padre: i32, valor: f64) -> i32`
- `json.agregar_entero(d: Doc, padre: i32, valor: i64) -> i32`
- `json.agregar_numero_texto(d: Doc, padre: i32, valor: str) -> i32`
- `json.agregar_bool(d: Doc, padre: i32, valor: bool) -> i32`
- `json.agregar_nulo(d: Doc, padre: i32) -> i32`
- `json.agregar_objeto(d: Doc, padre: i32) -> i32`
- `json.agregar_arreglo(d: Doc, padre: i32) -> i32`
- `json.entrecomillar(s: str) -> str` — Un str entre comillas, con los escapes de JSON. Con `ascii`, todo lo que no es ASCII sale como \uXXXX (los de más de 16 bits, como par sustituto).
- `json.entrecomillar_ascii(s: str) -> str`
- `json.escribir(d: Doc) -> str` — El documento en una línea, sin espacios: {"a":[1,2]}. Los str salen en UTF-8.
- `json.escribir_ascii(d: Doc) -> str` — Lo mismo con todo lo que no es ASCII como \uXXXX (json.dumps por omisión).
- `json.escribir_bonito(d: Doc, espacios: i32) -> str` — Con sangría de `espacios` por nivel (json.dumps(doc, indent=espacios, ensure_ascii=False)).
- `json.escribir_nodo(d: Doc, ruta: str) -> str` — Solo el nodo de esa ruta ("" si no existe).
- `json.bytes_de_archivo(ruta: str) -> Result<Vec<i32>>`
- `json.leer_archivo(ruta: str) -> Result<Doc>` — Lee un archivo JSON a un árbol.

## `juego`

lo que hace falta para un juego 2D (use "juego").

Tipos: `juego.Reloj`, `juego.Entrada`, `juego.Hoja`, `juego.Animacion`, `juego.Mapa`, `juego.Cuerpo`, `juego.Camara`.

- `juego.reloj(hz: i32) -> Reloj` — Un reloj de `hz` pasos por segundo (como mucho 5 pasos seguidos por cuadro).
- `juego.reloj_fijo(hz: i32) -> Reloj` — Un reloj determinista: pasos_ahora da siempre 1 paso por cuadro, sin mirar la hora (para probar con un guion, o para un juego que no quiere depender de la máquina).
- `juego.reloj_maximo(r: Reloj, pasos: i32)` — Cuántos pasos seguidos se permiten como máximo en un cuadro.
- `juego.avanzar(r: Reloj, dt_ms: i32) -> i32` — Pasa dt_ms milisegundos (los negativos cuentan 0, y más de un segundo, un segundo): devuelve cuántos pasos hay que dar ahora.
- `juego.alfa(r: Reloj) -> f64` — Lo que falta del paso siguiente, de 0.0 a 1.0 (para dibujar entre dos pasos).
- `juego.ahora() -> i32` — Milisegundos del reloj de la ventana (da la vuelta cada ~24 días).
- `juego.pasos(r: Reloj, ahora_ms: i32) -> i32` — Como avanzar, con la hora de `ahora_ms` (una lectura de ahora()). La primera vez da 0 pasos. La resta aguanta la vuelta del reloj.
- `juego.pasos_ahora(r: Reloj) -> i32` — pasos con la hora de la ventana.
- `juego.entrada(codigos: Vec<i32>) -> Entrada` — Mira estas teclas (scancodes de SDL: der 79, izq 80, abajo 81, arriba 82, espacio 44, Enter 40, Esc 41, A 4 ... Z 29).
- `juego.siguiente(e: Entrada)` — Pasa al paso siguiente: lo de ahora queda como "antes". Hay que llamarla una vez por paso de lógica, antes de fijar o leer.
- `juego.fijar(e: Entrada, codigo: i32, abajo: bool)` — Dice a mano si la tecla está apretada en este paso (sin pasar a otro paso). Las que no se miran se ignoran.
- `juego.leer(e: Entrada)` — siguiente(e) y después lee de la ventana el estado de cada tecla.
- `juego.sostenida(e: Entrada, codigo: i32) -> bool` — Está apretada en este paso.
- `juego.apretada(e: Entrada, codigo: i32) -> bool` — No estaba apretada en el paso anterior y ahora sí.
- `juego.soltada(e: Entrada, codigo: i32) -> bool` — Estaba apretada en el paso anterior y ahora no.
- `juego.eje(e: Entrada, menos: i32, mas: i32) -> i32` — -1 si está apretada la tecla `menos`, +1 si la de `mas`, 0 si las dos o ninguna (para el eje horizontal: eje(e, 80, 79)).
- `juego.hoja(img: lienzo.Lienzo, cw: i32, ch: i32) -> Hoja` — La imagen cortada en cuadros de cw x ch (lo que sobra en el borde se ignora).
- `juego.hoja_png(ruta: str, cw: i32, ch: i32) -> Result<Hoja>` — Lee un PNG y lo corta en cuadros de cw x ch.
- `juego.cuadros(h: Hoja) -> i32` — Cuántos cuadros tiene.
- `juego.dibujar(destino: lienzo.Lienzo, h: Hoja, i: i32, x: i32, y: i32)` — Pinta el cuadro i (0 es el de arriba a la izquierda) con su esquina en (x, y). Lo transparente no tapa. Un número que no existe no dibuja nada.
- `juego.dibujar_espejo(destino: lienzo.Lienzo, h: Hoja, i: i32, x: i32, y: i32)` — Lo mismo, dado vuelta de izquierda a derecha (para mirar para el otro lado).
- `juego.una_vez() -> i32`
- `juego.repetir() -> i32`
- `juego.ida_y_vuelta() -> i32`
- `juego.animacion(primero: i32, cantidad: i32, ms: i32, modo: i32) -> Animacion` — Los `cantidad` cuadros que empiezan en `primero`, cada uno `ms` milisegundos, con el modo una_vez() (se queda en el último), repetir() o ida_y_vuelta().
- `juego.cuadro(a: Animacion, t: i32) -> i32` — El número de cuadro de la hoja que toca a los t milisegundos de empezar (antes de empezar, el primero).
- `juego.terminada(a: Animacion, t: i32) -> bool` — Una animación de una_vez() ya llegó al final (las otras nunca terminan).
- `juego.duracion(a: Animacion) -> i32` — Lo que dura una pasada entera, en milisegundos.
- `juego.mapa(cols: i32, filas: i32, tam: i32) -> Mapa` — Un mapa vacío de cols x filas baldosas cuadradas de `tam` píxeles.
- `juego.mapa_texto(tam: i32, s: str) -> Mapa` — Un mapa escrito en texto, una línea por fila: '.' o ' ' es aire, '#' es la baldosa 1, '1'..'9' son esas baldosas, 'a'..'i' son adornos -1..-9 (cualquier otra cosa es aire). Las filas cortas se completan con aire.
- `juego.celda(m: Mapa, c: i32, f: i32) -> i32` — Qué hay en la baldosa (c, f); afuera del mapa, `fuera`.
- `juego.poner(m: Mapa, c: i32, f: i32, v: i32)` — Pone v en la baldosa (c, f) (afuera del mapa no hace nada).
- `juego.mapa_fuera(m: Mapa, v: i32)` — Qué vale afuera del mapa: 1 (pared, el valor de siempre) o 0 (aire: se puede caer).
- `juego.solida(m: Mapa, c: i32, f: i32) -> bool` — Se choca con la baldosa (c, f).
- `juego.ancho_mundo(m: Mapa) -> i32`
- `juego.alto_mundo(m: Mapa) -> i32`
- `juego.dibujar_mapa(destino: lienzo.Lienzo, m: Mapa, h: Hoja, cam: Camara)` — Dibuja las baldosas que se ven por la cámara, en el lienzo (la esquina del mundo que mira la cámara cae en (0, 0)). Solo las visibles: un mapa grande no cuesta más.
- `juego.caja_toca(ax: i32, ay: i32, aw: i32, ah: i32, bx: i32, by: i32, bw: i32, bh: i32) -> bool` — Las cajas (ax, ay, aw, ah) y (bx, by, bw, bh) se pisan (si solo se tocan en el borde, no).
- `juego.pisa(m: Mapa, x: i32, y: i32, w: i32, h: i32) -> bool` — La caja (x, y, w, h) pisa alguna baldosa sólida.
- `juego.cuerpo(x: i32, y: i32, w: i32, h: i32) -> Cuerpo` — Una caja de w x h con la esquina de arriba a la izquierda en (x, y) píxeles, quieta. La y crece hacia abajo.
- `juego.mover(m: Mapa, c: Cuerpo, dx: f64, dy: f64)` — Mueve el cuerpo (dx, dy) píxeles (con decimales: lo que no llega a un píxel entero se guarda en rx / ry para el paso siguiente; se redondea al más cercano, y los medios hacia arriba). Primero a lo ancho y después a lo alto. Si choca, el cuerpo queda pegado a la baldosa, y se pone en 0 el resto y la velocidad de ese eje. Después de mover: c.suelo (chocó yendo hacia abajo), c.techo (hacia arriba) y c.pared (-1 chocó a la izquierda, 1 a la derecha, 0 no chocó a lo ancho). Un cuerpo que ya empieza metido en una baldosa sólida no se saca solo.
- `juego.sobre_suelo(m: Mapa, c: Cuerpo) -> bool` — Hay suelo justo debajo del cuerpo (para saltar sin esperar al choque).
- `juego.camara(ancho: i32, alto: i32, mundo_w: i32, mundo_h: i32) -> Camara` — Una vista de ancho x alto píxeles sobre un mundo de mundo_w x mundo_h.
- `juego.mirar(c: Camara, x: i32, y: i32)` — Pone la esquina de la cámara de golpe, sin salirse del mundo.
- `juego.centrar(c: Camara, px: i32, py: i32)` — Centra la cámara en el punto (px, py) del mundo.
- `juego.suavizar(c: Camara, px: i32, py: i32, num: i32, den: i32)` — Va hacia el punto (px, py) una parte num/den de lo que falta en cada paso (siempre al menos un píxel, y sin pasarse): una cámara que sigue con suavidad.
- `juego.pantalla_x(c: Camara, x: i32) -> i32` — De coordenadas del mundo a coordenadas de la vista, y al revés.
- `juego.pantalla_y(c: Camara, y: i32) -> i32`
- `juego.mundo_x(c: Camara, x: i32) -> i32`
- `juego.mundo_y(c: Camara, y: i32) -> i32`
- `juego.visible(c: Camara, x: i32, y: i32, w: i32, h: i32) -> bool` — La caja (x, y, w, h) del mundo se ve (aunque sea un pedazo).

## `lienzo`

un lienzo de píxeles para dibujar (use "lienzo").

Tipos: `lienzo.Lienzo`, `lienzo.Marcas`.

- `lienzo.color(r: i32, g: i32, b: i32) -> i32` — Un color opaco con rojo, verde y azul de 0 a 255.
- `lienzo.color_a(r: i32, g: i32, b: i32, a: i32) -> i32` — Un color con alfa (0 transparente, 255 opaco).
- `lienzo.canal_r(c: i32) -> i32`
- `lienzo.canal_g(c: i32) -> i32`
- `lienzo.canal_b(c: i32) -> i32`
- `lienzo.canal_a(c: i32) -> i32`
- `lienzo.negro() -> i32`
- `lienzo.blanco() -> i32`
- `lienzo.rojo() -> i32`
- `lienzo.verde() -> i32`
- `lienzo.azul() -> i32`
- `lienzo.amarillo() -> i32`
- `lienzo.gris(v: i32) -> i32`
- `lienzo.transparente() -> i32`
- `lienzo.mezclar(fondo: i32, c: i32) -> i32` — c pintado encima de fondo ("over" con alfa sin premultiplicar, redondeado): con c opaco da c, con c transparente da fondo.
- `lienzo.nuevo(ancho: i32, alto: i32, fondo: i32) -> Lienzo` — Un lienzo de ancho x alto, pintado entero de fondo.
- `lienzo.ancho(l: Lienzo) -> i32`
- `lienzo.alto(l: Lienzo) -> i32`
- `lienzo.limpiar(l: Lienzo, c: i32)` — Todo el lienzo de un color (sin mezclar).
- `lienzo.adentro(l: Lienzo, x: i32, y: i32) -> bool`
- `lienzo.leer(l: Lienzo, x: i32, y: i32) -> i32` — El color del píxel (x, y); 0 (transparente) fuera del lienzo.
- `lienzo.poner(l: Lienzo, x: i32, y: i32, c: i32)` — Pone c en (x, y) tal cual, sin mezclar.
- `lienzo.pintar(l: Lienzo, x: i32, y: i32, c: i32)` — Pinta c encima de lo que hay en (x, y), mezclando por alfa.
- `lienzo.suma(l: Lienzo) -> i64` — Una suma de control del lienzo entero (para comparar dos dibujos sin mirar cada píxel): h = h·31 + píxel (como entero sin signo), módulo 2^31 - 1.
- `lienzo.linea(l: Lienzo, x0: i32, y0: i32, x1: i32, y1: i32, c: i32)` — La línea de (x0, y0) a (x1, y1), con los dos extremos (Bresenham).
- `lienzo.rect(l: Lienzo, x: i32, y: i32, w: i32, h: i32, c: i32)` — El borde de un rectángulo de w x h con la esquina de arriba a la izquierda en (x, y).
- `lienzo.rect_lleno(l: Lienzo, x: i32, y: i32, w: i32, h: i32, c: i32)` — Un rectángulo lleno de w x h con la esquina de arriba a la izquierda en (x, y).
- `lienzo.circulo(l: Lienzo, cx: i32, cy: i32, r: i32, c: i32)` — El borde de un círculo de radio r con centro en (cx, cy) (punto medio).
- `lienzo.circulo_lleno(l: Lienzo, cx: i32, cy: i32, r: i32, c: i32)` — Un círculo lleno: los píxeles (x, y) con (x-cx)² + (y-cy)² <= r².
- `lienzo.poligono(l: Lienzo, xs: Vec<i32>, ys: Vec<i32>, c: i32)` — El borde del polígono de vértices (xs[i], ys[i]), cerrado. Como toda fn que recibe un Vec, se queda con las listas.
- `lienzo.poligono_lleno(l: Lienzo, xs: Vec<i32>, ys: Vec<i32>, c: i32)` — Un polígono lleno: los píxeles cuyo centro está adentro (regla par-impar).
- `lienzo.triangulo(l: Lienzo, x0: i32, y0: i32, x1: i32, y1: i32, x2: i32, y2: i32, c: i32)`
- `lienzo.triangulo_lleno(l: Lienzo, x0: i32, y0: i32, x1: i32, y1: i32, x2: i32, y2: i32, c: i32)`
- `lienzo.copiar(destino: Lienzo, origen: Lienzo, x: i32, y: i32)` — Pinta todo el lienzo origen encima de destino, con su esquina en (x, y).
- `lienzo.texto_escala(l: Lienzo, x: i32, y: i32, s: str, c: i32, escala: i32)` — Escribe s con la fuente de 8x8 (cada carácter ocupa 8 x 8 píxeles por escala) desde (x, y), la esquina de arriba a la izquierda. Solo pinta los puntos de cada letra: el fondo queda. "\n" sigue en la línea de abajo.
- `lienzo.texto(l: Lienzo, x: i32, y: i32, s: str, c: i32)`
- `lienzo.ancho_texto(s: str, escala: i32) -> i32` — Cuánto mide s escrito con texto_escala: el ancho de la línea más larga.

## `mate`

vectores, matrices 4x4, cuaterniones, trigonometría y números al azar con semilla (use "mate").

Tipos: `mate.Vec2`, `mate.Vec3`, `mate.Vec4`, `mate.Mat4`, `mate.Menores4`, `mate.Cuat`, `mate.Azar`.

- `mate.pi() -> f64`
- `mate.radianes(grados: f64) -> f64`
- `mate.grados(radianes: f64) -> f64`
- `mate.recortar(x: f64, lo: f64, hi: f64) -> f64` — x dentro de [lo, hi].
- `mate.interpolar(a: f64, b: f64, t: f64) -> f64` — a + (b - a)·t: t = 0 da a, t = 1 da b.
- `mate.signo(x: f64) -> f64` — -1, 0 o 1.
- `mate.atan2(y: f64, x: f64) -> f64` — El ángulo de (x, y) en (-pi, pi], como atan2 de C.
- `mate.asin(x: f64) -> f64` — asin y acos en [-1, 1] (fuera de ahí, nan, como en C).
- `mate.acos(x: f64) -> f64`
- `mate.v2(x: f64, y: f64) -> Vec2`
- `mate.v2_suma(a: Vec2, b: Vec2) -> Vec2`
- `mate.v2_resta(a: Vec2, b: Vec2) -> Vec2`
- `mate.v2_escala(a: Vec2, k: f64) -> Vec2`
- `mate.v2_punto(a: Vec2, b: Vec2) -> f64`
- `mate.v2_cruz(a: Vec2, b: Vec2) -> f64` — La z del producto cruz de (a, 0) y (b, 0): positiva si b está a la izquierda de a.
- `mate.v2_largo(a: Vec2) -> f64`
- `mate.v2_normalizar(a: Vec2) -> Vec2` — Largo 1; el vector cero queda cero.
- `mate.v2_interpolar(a: Vec2, b: Vec2, t: f64) -> Vec2`
- `mate.v2_rotar(a: Vec2, ang: f64) -> Vec2` — Girado `ang` radianes en sentido antihorario.
- `mate.v3(x: f64, y: f64, z: f64) -> Vec3`
- `mate.v3_suma(a: Vec3, b: Vec3) -> Vec3`
- `mate.v3_resta(a: Vec3, b: Vec3) -> Vec3`
- `mate.v3_escala(a: Vec3, k: f64) -> Vec3`
- `mate.v3_negar(a: Vec3) -> Vec3`
- `mate.v3_punto(a: Vec3, b: Vec3) -> f64`
- `mate.v3_cruz(a: Vec3, b: Vec3) -> Vec3`
- `mate.v3_largo(a: Vec3) -> f64`
- `mate.v3_distancia(a: Vec3, b: Vec3) -> f64`
- `mate.v3_normalizar(a: Vec3) -> Vec3` — Largo 1; el vector cero queda cero.
- `mate.v3_interpolar(a: Vec3, b: Vec3, t: f64) -> Vec3`
- `mate.v4(x: f64, y: f64, z: f64, w: f64) -> Vec4`
- `mate.v4_punto(p: Vec3) -> Vec4` — (p, 1): un punto, al que le afectan las traslaciones.
- `mate.v4_direccion(d: Vec3) -> Vec4` — (d, 0): una dirección, a la que no le afectan las traslaciones.
- `mate.v4_suma(a: Vec4, b: Vec4) -> Vec4`
- `mate.v4_resta(a: Vec4, b: Vec4) -> Vec4`
- `mate.v4_escala(a: Vec4, k: f64) -> Vec4`
- `mate.v4_punto_prod(a: Vec4, b: Vec4) -> f64`
- `mate.v4_largo(a: Vec4) -> f64`
- `mate.v4_a_v3(a: Vec4) -> Vec3` — (x/w, y/w, z/w): de vuelta a 3D después de una proyección.
- `mate.m4_ceros() -> Mat4`
- `mate.m4_identidad() -> Mat4`
- `mate.m4_de_filas(a: f64, b: f64, c: f64, d: f64, e: f64, f: f64, g: f64, h: f64, i: f64, j: f64, k: f64, l: f64, m: f64, n: f64, o: f64, p: f64) -> Mat4` — Una matriz escrita por filas: a b c d / e f g h / i j k l / m n o p.
- `mate.m4_get(a: Mat4, fila: i32, columna: i32) -> f64`
- `mate.m4_set(a: Mat4, fila: i32, columna: i32, valor: f64)` — Cambia un elemento (la única función que modifica su matriz).
- `mate.m4_copia(a: Mat4) -> Mat4`
- `mate.m4_producto(a: Mat4, b: Mat4) -> Mat4` — a·b.
- `mate.m4_por_v4(a: Mat4, v: Vec4) -> Vec4` — a·v.
- `mate.m4_punto(a: Mat4, p: Vec3) -> Vec3` — Un punto transformado (con w = 1, y dividido por la w que sale: sirve también para una proyección).
- `mate.m4_direccion(a: Mat4, d: Vec3) -> Vec3` — Una dirección transformada (w = 0: sin traslación).
- `mate.m4_transpuesta(a: Mat4) -> Mat4`
- `mate.m4_determinante(a: Mat4) -> f64`
- `mate.m4_inversa(a: Mat4) -> Option<Mat4>` — La inversa, o None si la matriz es singular (determinante 0).
- `mate.m4_traslacion(x: f64, y: f64, z: f64) -> Mat4`
- `mate.m4_escala(x: f64, y: f64, z: f64) -> Mat4`
- `mate.m4_rotacion_x(ang: f64) -> Mat4`
- `mate.m4_rotacion_y(ang: f64) -> Mat4`
- `mate.m4_rotacion_z(ang: f64) -> Mat4`
- `mate.m4_rotacion(eje: Vec3, ang: f64) -> Mat4` — Rotación de `ang` radianes alrededor de `eje` (no hace falta que tenga largo 1), regla de la mano derecha (fórmula de Rodrigues, la de glRotate).
- `mate.m4_perspectiva(fovy: f64, aspecto: f64, cerca: f64, lejos: f64) -> Mat4` — Proyección en perspectiva, como gluPerspective: `fovy` es el ángulo vertical del campo de visión (radianes), `aspecto` ancho/alto, y `cerca`/`lejos` las distancias (positivas) a los planos de recorte. Lleva z = -cerca a -1 y z = -lejos a 1.
- `mate.m4_ortografica(izq: f64, der: f64, abajo: f64, arriba: f64, cerca: f64, lejos: f64) -> Mat4` — Proyección ortográfica, como glOrtho.
- `mate.m4_mirar_a(ojo: Vec3, centro: Vec3, arriba: Vec3) -> Mat4` — La matriz de vista de una cámara en `ojo` que mira a `centro`, con `arriba` como la dirección de arriba, como gluLookAt: lleva `ojo` al origen y la dirección de la mirada a -z.
- `mate.cuat(w: f64, x: f64, y: f64, z: f64) -> Cuat`
- `mate.c_identidad() -> Cuat`
- `mate.c_desde_eje_angulo(eje: Vec3, ang: f64) -> Cuat` — La rotación de `ang` radianes alrededor de `eje` (no hace falta que tenga largo 1).
- `mate.c_producto(a: Cuat, b: Cuat) -> Cuat` — a·b (producto de Hamilton): rotar con b y después con a.
- `mate.c_conjugado(a: Cuat) -> Cuat`
- `mate.c_punto(a: Cuat, b: Cuat) -> f64`
- `mate.c_largo(a: Cuat) -> f64`
- `mate.c_normalizar(a: Cuat) -> Cuat` — Largo 1; el cero queda como la identidad.
- `mate.c_a_m4(q: Cuat) -> Mat4` — La matriz de rotación de un cuaternión de largo 1.
- `mate.c_rotar_v3(q: Cuat, v: Vec3) -> Vec3` — v rotado por q (de largo 1): q·v·q*.
- `mate.c_slerp(a: Cuat, b: Cuat, t: f64) -> Cuat` — Interpolación esférica entre dos rotaciones (de largo 1), por el camino corto: t = 0 da a, t = 1 da b (o -b, que es la misma rotación).
- `mate.azar(semilla: i32) -> Azar` — Un generador con esa semilla (la semilla 0 se cambia por otra fija: con estado 0, xorshift se queda en 0 para siempre).
- `mate.azar_siguiente(a: Azar) -> i32` — El siguiente número, como i32 (todos los valores salvo el 0). Es el xorshift32 de Marsaglia (13, 17, 5); el >> de SCAR es aritmético, así que el desplazamiento lógico se hace con una máscara.
- `mate.azar_uniforme(a: Azar) -> f64` — Uniforme en (0, 1): nunca da 0 ni 1.
- `mate.azar_entre(a: Azar, lo: f64, hi: f64) -> f64` — Uniforme en (lo, hi).
- `mate.azar_entero(a: Azar, lo: i32, hi: i32) -> i32` — Un entero en [lo, hi], los dos incluidos.
- `mate.azar_normal(a: Azar, media: f64, desviacion: f64) -> f64` — Normal con esa media y desviación (Box-Muller; usa dos uniformes por número).

## `motor3d`

dibujar en 3D sobre un lienzo (use "motor3d").

Tipos: `motor3d.Malla`, `motor3d.Camara`, `motor3d.Luz`, `motor3d.Destino`, `motor3d.Poligono`.

- `motor3d.malla() -> Malla`
- `motor3d.vertice(m: Malla, x: f64, y: f64, z: f64, nx: f64, ny: f64, nz: f64) -> i32` — Agrega un vértice con su normal; devuelve su índice.
- `motor3d.triangulo(m: Malla, a: i32, b: i32, c: i32)` — Agrega el triángulo a, b, c (en sentido contrario a las agujas del reloj, mirado desde afuera).
- `motor3d.vertices(m: Malla) -> i32`
- `motor3d.triangulos(m: Malla) -> i32`
- `motor3d.cubo(lado: f64) -> Malla` — Un cubo de lado `lado` centrado en el origen: 24 vértices (4 por cara, con la normal de la cara) y 12 triángulos.
- `motor3d.esfera(radio: f64, segmentos: i32, anillos: i32) -> Malla` — Una esfera de radio `radio` centrada en el origen, con `segmentos` cortes alrededor y `anillos` de polo a polo; la normal de cada vértice apunta hacia afuera.
- `motor3d.calcular_normales(m: Malla)` — Recalcula la normal de cada vértice como el promedio de las normales de las caras que lo usan (pesadas por su área).
- `motor3d.de_obj(fuente: str) -> Result<Malla>` — Una malla de un archivo .obj (el texto): vértices (v), normales (vn) y caras (f) de tres o más vértices, con índices como 3, 3/1, 3//2 o 3/1/2 (las texturas se ignoran). Si alguna cara no trae normales, se calculan (calcular_normales). Lo demás (o, g, s, usemtl...) se ignora.
- `motor3d.camara(ojo: mate.Vec3, centro: mate.Vec3, arriba: mate.Vec3, fovy: f64, cerca: f64, lejos: f64) -> Camara` — Una cámara en `ojo` que mira a `centro` (como gluLookAt), con un campo de visión vertical `fovy` (radianes) y los planos de recorte `cerca` y `lejos`.
- `motor3d.luz(dir: mate.Vec3, ambiente: f64, difusa: f64) -> Luz` — Una luz direccional: `dir` es hacia donde va la luz (no hace falta que sea unitaria).
- `motor3d.plano() -> i32` — Cómo se pinta: plano (una luz por cara), gouraud (luz por vértice, interpolada) o alambre (solo los bordes, con el color tal cual).
- `motor3d.gouraud() -> i32`
- `motor3d.alambre() -> i32`
- `motor3d.nuevo(ancho: i32, alto: i32, fondo: i32) -> Destino`
- `motor3d.limpiar(d: Destino, fondo: i32)` — Todo de un color, y el z-buffer vacío.
- `motor3d.dibujar(d: Destino, m: Malla, modelo: mate.Mat4, cam: Camara, l: Luz, c: i32, modo: i32)` — Dibuja la malla `m`, transformada por la matriz de modelo `modelo`, vista por la cámara `cam` y con la luz `l`, del color `c`, en el modo dado (plano(), gouraud() o alambre()).

## `neuronalgames`

redes neuronales chicas para JUEGOS (use "neuronalgames"): bots, criaturas y enemigos que aprenden, con retropropagación o por neuroevolución.

Tipos: `neuronalgames.Red`, `neuronalgames.Datos`, `neuronalgames.Lector`.

- `neuronalgames.lineal() -> i32`
- `neuronalgames.relu() -> i32`
- `neuronalgames.sigmoide() -> i32`
- `neuronalgames.tanh() -> i32`
- `neuronalgames.red(entradas: i32, semilla: i32) -> Red` — red(entradas, semilla) -> Red: una red sin capas todavía.
- `neuronalgames.capa(r: Red, n: i32, activacion: i32)` — capa(r, n, activacion): agrega una capa de n neuronas al final, con pesos al azar.
- `neuronalgames.momento(r: Red, m: f64)` — momento(r, m): cuánto de la corrección anterior se repite en la siguiente (0 nada, 0,9 mucho).
- `neuronalgames.mezclar(r: Red, si: bool)` — mezclar(r, si): al entrenar, recorrer los ejemplos en otro orden al azar en cada vuelta.
- `neuronalgames.salidas(r: Red) -> i32`
- `neuronalgames.entradas(r: Red) -> i32`
- `neuronalgames.parametros(r: Red) -> i32` — cuántos números ajustables tiene (pesos más sesgos)
- `neuronalgames.peso(r: Red, k: i32) -> f64` — El peso k (en el orden en que se guardan: capa por capa, neurona por neurona, entrada por entrada) y el sesgo k, para mirarlos o cambiarlos a mano.
- `neuronalgames.poner_peso(r: Red, k: i32, v: f64)`
- `neuronalgames.sesgo(r: Red, k: i32) -> f64`
- `neuronalgames.poner_sesgo(r: Red, k: i32, v: f64)`
- `neuronalgames.pesos_totales(r: Red) -> i32`
- `neuronalgames.sesgos_totales(r: Red) -> i32`
- `neuronalgames.entrada(r: Red, i: i32, x: f64)`
- `neuronalgames.calcular(r: Red)` — calcular(r): pasa las entradas cargadas por todas las capas.
- `neuronalgames.salida(r: Red, i: i32) -> f64`
- `neuronalgames.mayor_salida(r: Red) -> i32` — la salida más grande (para clasificar: qué clase eligió la red)
- `neuronalgames.datos(n_entradas: i32, n_salidas: i32) -> Datos`
- `neuronalgames.ejemplo(d: Datos, xs: Vec<f64>, ys: Vec<f64>)` — ejemplo(d, entradas, deseadas): agrega un ejemplo. Si los largos no coinciden es un panic.
- `neuronalgames.ejemplo_entrada(d: Datos, x: f64)` — lo mismo de a un número por vez (sin armar listas): primero las entradas, después las salidas
- `neuronalgames.ejemplo_salida(d: Datos, y: f64)`
- `neuronalgames.ejemplos(d: Datos) -> i32`
- `neuronalgames.entrenar(r: Red, d: Datos, vueltas: i32, tasa: f64) -> f64` — entrenar(r, d, vueltas, tasa) -> f64: recorre todos los ejemplos `vueltas` veces corrigiendo después de cada uno, y devuelve el error al final. Si la red y los datos no tienen las mismas entradas y salidas es un panic.
- `neuronalgames.error(r: Red, d: Datos) -> f64` — error(r, d) -> f64: el promedio de (salida - deseada)^2 sobre todos los ejemplos y salidas.
- `neuronalgames.aciertos(r: Red, d: Datos) -> f64` — aciertos(r, d) -> f64: la fracción de ejemplos en que la salida más grande es la de la deseada más grande (para clasificar en varias clases). Con una sola salida: si los dos quedan del mismo lado de 0,5.
- `neuronalgames.copiar(r: Red, semilla: i32) -> Red` — copiar(r, semilla) -> Red: otra red igual (mismas capas, pesos y sesgos), con su propio generador. (Las listas se copian elemento por elemento acá mismo: pasarlas a otra función las entregaría.)
- `neuronalgames.mutar(r: Red, probabilidad: f64, fuerza: f64)` — mutar(r, probabilidad, fuerza): cada peso y cada sesgo, con esa probabilidad, se corre un número al azar entre -fuerza y fuerza (usa el generador de la red).
- `neuronalgames.cruzar(a: Red, b: Red, semilla: i32) -> Red` — cruzar(a, b, semilla) -> Red: un hijo con las capas de a, y cada peso y sesgo tomado de a o de b (mitad y mitad al azar, con esa semilla). Si a y b no tienen las mismas capas es un panic.
- `neuronalgames.a_texto_red(r: Red) -> str` — a_texto_red(r) -> str: la red en texto (capas, activaciones, pesos y sesgos), para guardarla en un archivo y leerla después con desde_texto.
- `neuronalgames.desde_texto(s: str) -> Result<Red>` — desde_texto(s) -> Result<Red>: la red guardada con a_texto_red (semilla 1 para su generador).

## `pantalla`

mostrar en la ventana de lib/gui un lienzo de lib/lienzo (use "pantalla").

- `pantalla.mostrar(ui: gui.Ui, l: lienzo.Lienzo, escala: i32)` — Muestra el lienzo como una pieza de la ventana (debajo de la anterior, o en la fila), centrado en el ancho libre, cada píxel como un cuadrado de escala x escala. Si no entra, se recorta.
- `pantalla.mostrar_en(l: lienzo.Lienzo, x: i32, y: i32, escala: i32)` — Lo mismo en un lugar fijo de la ventana, sin acomodarlo con las piezas: la esquina de arriba a la izquierda en (x, y).

## `parlante`

hacer sonar un audio.Sonido en vivo (use "parlante").

- `parlante.sonar(s: audio.Sonido) -> bool` — Pone el sonido en la cola del parlante. true si quedó sonando.
- `parlante.pendientes() -> i32` — Cuántas muestras quedan por sonar (de todos los canales; 0 si terminó).
- `parlante.sonando() -> bool`
- `parlante.esperar()` — Espera a que termine lo que está en la cola.
- `parlante.callar()` — Corta lo que está sonando.

## `patron`

expresiones regulares (use "patron").

Tipos: `patron.Patron`, `patron.Coincidencia`, `patron.Texto`, `patron.Parser`, `patron.Maq`, `patron.Calces`, `patron.Plantilla`.

- `patron.compilar_con(fuente: str, banderas: str) -> Result<Patron>` — Compila un patrón. Las banderas son letras sueltas: "i" (ignorar mayúsculas), "m" (^ y $ en cada línea), "s" (el punto también toma \n), en cualquier combinación.
- `patron.compilar(fuente: str) -> Result<Patron>`
- `patron.num_grupos(p: Patron) -> i32`
- `patron.fuente(p: Patron) -> str`
- `patron.indice_grupo(p: Patron, nombre: str) -> i32` — Número del grupo con ese nombre, o -1.
- `patron.nombre_grupo(p: Patron, k: i32) -> str`
- `patron.hay(m: Coincidencia) -> bool`
- `patron.inicio(m: Coincidencia) -> i32`
- `patron.fin(m: Coincidencia) -> i32`
- `patron.inicio_grupo(m: Coincidencia, k: i32) -> i32`
- `patron.fin_grupo(m: Coincidencia, k: i32) -> i32`
- `patron.hay_grupo(m: Coincidencia, k: i32) -> bool`
- `patron.grupo(m: Coincidencia, k: i32) -> str` — El texto del grupo k (0 = todo lo que calzó). "" si no calzó o el grupo no participó.
- `patron.grupo_nombre(p: Patron, m: Coincidencia, nombre: str) -> str` — El grupo por su nombre ((?P<nombre>...)); "" si no existe ese nombre.
- `patron.texto_de(m: Coincidencia) -> str`
- `patron.buscar(p: Patron, s: str) -> Coincidencia` — re.search: el primer calce en cualquier parte.
- `patron.buscar_desde(p: Patron, s: str, desde: i32) -> Coincidencia` — re.search(s, desde): empieza a mirar en el carácter `desde` (^ sigue siendo el principio real).
- `patron.al_inicio(p: Patron, s: str) -> Coincidencia` — re.match: tiene que calzar desde el primer carácter.
- `patron.completo(p: Patron, s: str) -> Coincidencia` — re.fullmatch: tiene que calzar todo el texto.
- `patron.coincide(p: Patron, s: str) -> bool`
- `patron.todas(p: Patron, s: str) -> Vec<Coincidencia>` — Todos los calces como Coincidencia (re.finditer).
- `patron.encontrar(p: Patron, s: str) -> Vec<str>` — Los textos de todos los calces (grupo 0 de cada uno).
- `patron.contar(p: Patron, s: str) -> i32`
- `patron.reemplazar_n(p: Patron, s: str, plantilla: str, maximo: i32) -> Result<str>` — re.sub con una plantilla: \1, \g<1>, \g<nombre>, \0 (octal), \n \t etc. Un grupo que no participó se reemplaza por "". maximo < 0 = todos (en re.sub, count=0).
- `patron.reemplazar(p: Patron, s: str, plantilla: str) -> Result<str>`
- `patron.reemplazar_texto_n(p: Patron, s: str, nuevo: str, maximo: i32) -> str` — Reemplaza por un texto tal cual, sin interpretar barras. maximo < 0 = todos.
- `patron.reemplazar_texto(p: Patron, s: str, nuevo: str) -> str`
- `patron.dividir_n(p: Patron, s: str, maximo: i32) -> Vec<str>` — re.split: el texto cortado en los calces; los grupos que capturan van en medio (un grupo que no participó da ""). maximo < 0 = sin tope de cortes.
- `patron.dividir(p: Patron, s: str) -> Vec<str>`
- `patron.escapar(s: str) -> str` — re.escape: pone una barra delante de lo que en un patrón tiene significado.
- `patron.desensamblar(p: Patron) -> str` — El programa compilado, una instrucción por línea (para depurar un patrón).

## `prueba`

un mini framework de pruebas (use "prueba").

Tipos: `prueba.Prueba`.

- `prueba.nueva(nombre: str) -> Prueba` — Un conjunto de pruebas nuevo, sin nada contado.
- `prueba.seccion(t: Prueba, nombre: str)` — Marca el comienzo de un grupo de pruebas: las fallas de acá en adelante dicen a qué sección pertenecen.
- `prueba.afirmar(t: Prueba, cond: bool, que: str)` — La condición tiene que ser verdadera.
- `prueba.afirmar_igual_i32(t: Prueba, obtenido: i32, esperado: i32, que: str)`
- `prueba.afirmar_igual_i64(t: Prueba, obtenido: i64, esperado: i64, que: str)`
- `prueba.afirmar_igual_f64(t: Prueba, obtenido: f64, esperado: f64, que: str)` — Igualdad exacta de dos f64 (para resultados que tienen que ser exactos; para cuentas con redondeo, afirmar_cerca).
- `prueba.afirmar_igual_str(t: Prueba, obtenido: str, esperado: str, que: str)`
- `prueba.afirmar_igual_bool(t: Prueba, obtenido: bool, esperado: bool, que: str)`
- `prueba.afirmar_cerca(t: Prueba, obtenido: f64, esperado: f64, tolerancia: f64, que: str)` — |obtenido - esperado| <= tolerancia. Un nan nunca está cerca de nada.
- `prueba.total(t: Prueba) -> i32` — Cuántas pruebas se contaron y cuántas fallaron.
- `prueba.fallas(t: Prueba) -> i32`
- `prueba.terminar(t: Prueba) -> i32` — Imprime el resumen y devuelve el código de salida: 0 si todo pasó, 1 si no.

## `senal`

procesamiento de señales (use "senal"). Probada contra numpy.fft y scipy.signal.

Tipos: `senal.Complejos`, `senal.Filtro`, `senal.Espectro`, `senal.C`, `senal.Zpk`.

- `senal.complejos_ceros(n: i32) -> Complejos`
- `senal.largo_c(c: Complejos) -> i32`
- `senal.parte_real(c: Complejos, i: i32) -> f64`
- `senal.parte_imag(c: Complejos, i: i32) -> f64`
- `senal.fft(x: estadistica.Serie) -> Complejos` — La transformada de Fourier de una señal real (numpy.fft.fft): n valores complejos.
- `senal.fft_c(c: Complejos) -> Complejos` — La transformada de un Complejos (numpy.fft.fft de una señal compleja).
- `senal.ifft(c: Complejos) -> Complejos` — La inversa (numpy.fft.ifft): divide por n.
- `senal.rfft(x: estadistica.Serie) -> Complejos` — Solo las n/2 + 1 frecuencias de 0 a Nyquist de una señal real (numpy.fft.rfft).
- `senal.irfft(c: Complejos, n: i32) -> estadistica.Serie` — La inversa de rfft, a una señal real de n muestras (numpy.fft.irfft).
- `senal.magnitud(c: Complejos) -> estadistica.Serie`
- `senal.fase(c: Complejos) -> estadistica.Serie`
- `senal.frecuencias(n: i32, d: f64) -> estadistica.Serie` — Las frecuencias de cada valor de fft, con muestras cada `d` segundos (numpy.fft.fftfreq).
- `senal.frecuencias_r(n: i32, d: f64) -> estadistica.Serie` — Las de rfft (numpy.fft.rfftfreq).
- `senal.convolucion(a: estadistica.Serie, b: estadistica.Serie) -> estadistica.Serie` — La convolución completa de a y b, n + m - 1 valores (numpy.convolve).
- `senal.convolucion_fft(a: estadistica.Serie, b: estadistica.Serie) -> estadistica.Serie` — Lo mismo por FFT: mucho más rápido con señales largas, con un error de redondeo del orden de 1e-16 por el tamaño de los datos.
- `senal.correlacion_cruzada(a: estadistica.Serie, b: estadistica.Serie) -> estadistica.Serie` — La correlación cruzada completa (numpy.correlate(a, b, "full")).
- `senal.ventana(nombre: str, n: i32, simetrica: bool) -> estadistica.Serie` — Una ventana de n puntos: "hann", "hamming", "blackman", "bartlett", "boxcar" o "kaiser" (con beta 8.6; para otro beta, `ventana_kaiser`). `simetrica` true: de 0 a 0 en los extremos, para diseñar filtros (get_window con fftbins=False); false: periódica, para análisis espectral (la de scipy por omisión).
- `senal.ventana_kaiser(n: i32, beta: f64, simetrica: bool) -> estadistica.Serie`
- `senal.fir(numtaps: i32, cortes: estadistica.Serie, pasa_cero: bool, win: estadistica.Serie, escalar: bool, fs: f64) -> estadistica.Serie` — Diseño de un FIR por ventanas (scipy.signal.firwin). `cortes` en Hz, estrictamente crecientes y entre 0 y fs/2. `pasa_cero` true: la banda de 0 al primer corte pasa (pasabajo, rechazabanda); false: no pasa (pasaalto, pasabanda). `win` es la ventana simétrica de `numtaps` puntos. Con `escalar`, la ganancia de la primera banda es 1.
- `senal.fir_pasabajo(numtaps: i32, corte: f64, fs: f64) -> estadistica.Serie` — Pasabajo con ventana de Hamming (como firwin(numtaps, corte, fs=fs)).
- `senal.fir_pasaalto(numtaps: i32, corte: f64, fs: f64) -> estadistica.Serie` — Pasaalto (numtaps impar).
- `senal.fir_pasabanda(numtaps: i32, bajo: f64, alto: f64, fs: f64) -> estadistica.Serie`
- `senal.fir_rechazabanda(numtaps: i32, bajo: f64, alto: f64, fs: f64) -> estadistica.Serie` — Rechazabanda (numtaps impar).
- `senal.butter(orden: i32, cortes: estadistica.Serie, tipo: str, fs: f64) -> Filtro` — Un filtro digital Butterworth de ese orden (scipy.signal.butter, forma b/a). `cortes`: un valor en Hz para "pasabajo" y "pasaalto", dos (bajo, alto) para "pasabanda" y "rechazabanda". `fs` es la frecuencia de muestreo. Con orden alto (más de 8) la forma b/a pierde precisión. Si los argumentos no sirven devuelve un filtro vacío (b y a sin coeficientes).
- `senal.filtro(b: estadistica.Serie, a: estadistica.Serie) -> Filtro`
- `senal.estado_inicial(f: Filtro) -> estadistica.Serie` — El estado inicial que deja al filtro en régimen para una entrada constante de 1 (scipy.signal.lfilter_zi): n - 1 valores.
- `senal.aplicar_con(f: Filtro, x: estadistica.Serie, zi: estadistica.Serie) -> estadistica.Serie` — Aplica el filtro a la señal, hacia adelante (scipy.signal.lfilter), con el estado inicial `zi` (n - 1 valores, o una serie vacía para ceros).
- `senal.aplicar(f: Filtro, x: estadistica.Serie) -> estadistica.Serie`
- `senal.filtfilt(f: Filtro, x: estadistica.Serie) -> estadistica.Serie` — Filtra hacia adelante y hacia atrás: sin desfase y con el doble de atenuación (scipy.signal.filtfilt con relleno impar de 3·max(len a, len b) muestras en cada punta y estado inicial de régimen). La señal tiene que ser más larga que el relleno; si no, devuelve una serie vacía.
- `senal.ganancia(f: Filtro, hz: f64, fs: f64) -> f64` — La ganancia |H| del filtro a la frecuencia `hz` (con muestreo `fs`).
- `senal.periodograma(x: estadistica.Serie, fs: f64, nombre_ventana: str) -> Espectro` — El periodograma de una señal (scipy.signal.periodogram con scaling "density", quitando la media): la potencia por Hz de 0 a Nyquist. `nombre_ventana`: "boxcar", "hann", "hamming", "blackman" o "bartlett" (en su forma periódica).
- `senal.remuestrear(x: estadistica.Serie, num: i32) -> estadistica.Serie` — Remuestrea la señal a `num` muestras por el método de Fourier (scipy.signal.resample, sin ventana): se recorta o se rellena el espectro.
- `senal.remuestrear_poly(x: estadistica.Serie, arriba: i32, abajo: i32) -> estadistica.Serie` — Remuestrea por el factor arriba/abajo con un filtro polifásico (scipy.signal.resample_poly con su ventana de Kaiser de beta 5 por omisión): sube la tasa `arriba` veces, filtra y baja `abajo` veces, sin calcular las muestras que se tiran.

## `tablero`

piezas de tablero de control (dashboard) sobre lib/gui (use "tablero"). Tarjetas de indicador (con variación y color), medidor de media luna, barra de nivel con avisos, semáforo, mini gráfico de líneas, botones grandes e interruptor. Se usan igual que las piezas de gui: una por cuadro, sin coordenadas, y en una gui.fila quedan lado a lado (tablero.ancho_celda dice cuánto mide cada una si se quieren n por fila).

- `tablero.azul() -> i32` — colores sueltos para las tarjetas (gui.color(r, g, b)); -1 = el acento del tema
- `tablero.verde() -> i32`
- `tablero.ambar() -> i32`
- `tablero.rojo() -> i32`
- `tablero.violeta() -> i32`
- `tablero.gris() -> i32`
- `tablero.fraccion(v: f64, lo: f64, hi: f64) -> f64` — Dónde cae v entre lo y hi, de 0.0 a 1.0.
- `tablero.estado(v: f64, aviso: f64, critico: f64) -> i32` — -1 sin avisos, 0 bien, 1 aviso (ámbar), 2 crítico (rojo).
- `tablero.color_estado(ui: gui.Ui, e: i32) -> i32` — El color de un estado: -1 el acento, 0 bien, 1 aviso, 2 mal, 3 apagado.
- `tablero.compacto(v: f64) -> str` — Un número corto para una tarjeta: 950 -> "950", 1234 -> "1.2k", 3400000 -> "3.4M", 2.0 -> "2", 3.14159 -> "3.1" (k, M y G desde mil, un millón y mil millones).
- `tablero.ancho_celda(ui: gui.Ui, columnas: i32) -> i32` — El ancho de cada pieza si caben `columnas` en una fila (con el espacio entre ellas). Se pide UNA vez, antes de la primera pieza de la fila: después de cada pieza queda menos lugar libre.
- `tablero.arco_x(cx: i32, r: f64, f: f64) -> i32` — El punto (x, y) del arco del medidor a la fracción f (0 = la izquierda, 1 = la derecha), a distancia r del centro (cx, cy); la media luna es la de arriba.
- `tablero.arco_y(cy: i32, r: f64, f: f64) -> i32`
- `tablero.mezclar(a: i32, b: i32, t: i32) -> i32` — a mezclado con b: t centésimos de b
- `tablero.sobre(c: i32) -> i32` — El texto que se lee sobre un fondo c.
- `tablero.tarjeta(ui: gui.Ui, ancho: i32, titulo: str, valor: str, unidad: str, nota: str, color: i32)` — gui-tablero.tarjeta(ui, ancho, titulo, valor, unidad, nota, color): un indicador. `valor` y `unidad` van como texto (tablero.compacto(x) ayuda); `nota` (puede ser "") va abajo, en gris; `color` pone una franja a la izquierda (-1: sin franja). ancho 0: todo lo que queda.
- `tablero.tarjeta_delta(ui: gui.Ui, ancho: i32, titulo: str, valor: str, unidad: str, delta: f64, decimales: i32, sube_es_bueno: bool, nota: str)` — tablero.tarjeta_delta: como tarjeta, y abajo cuánto cambió (`delta`, con `decimales` cifras) con una flecha: verde si el cambio es bueno (sube_es_bueno decide cuál lo es), rojo si es malo, gris si no cambió; `nota` sigue al cambio ("vs ayer").
- `tablero.medidor(ui: gui.Ui, ancho: i32, titulo: str, valor: f64, lo: f64, hi: f64, aviso: f64, critico: f64, unidad: str)` — tablero.medidor(ui, ancho, titulo, valor, lo, hi, aviso, critico, unidad): una media luna que se llena de lo a hi, del color del estado, con el valor en el medio y marcas en los avisos.
- `tablero.nivel(ui: gui.Ui, ancho: i32, titulo: str, valor: f64, lo: f64, hi: f64, aviso: f64, critico: f64, unidad: str)` — tablero.nivel(ui, ancho, titulo, valor, lo, hi, aviso, critico, unidad): una barra horizontal que se llena y cambia de color en los avisos (que se marcan con una raya).
- `tablero.semaforo(ui: gui.Ui, texto: str, e: i32)` — tablero.semaforo(ui, texto, e): un círculo de color y el texto. e: 0 bien, 1 aviso, 2 mal, 3 apagado (gris); -1 el acento.
- `tablero.mini_lineas(ui: gui.Ui, ancho: i32, alto: i32, s: gui.Serie, color: i32)` — tablero.mini_lineas(ui, ancho, alto, serie, color): los valores de una gui.Serie como una línea sin ejes, en un panel; el último punto va marcado (-1: el color de acento).
- `tablero.boton_grande(ui: gui.Ui, ancho: i32, alto: i32, titulo: str, detalle: str, color: i32) -> bool` — tablero.boton_grande(ui, ancho, alto, titulo, detalle, color) -> bool: un botón-tarjeta de color (-1: el acento) con un título y una línea de detalle (puede ser ""); true en el cuadro del clic.
- `tablero.interruptor(ui: gui.Ui, texto: str, encendido: bool) -> bool` — tablero.interruptor(ui, texto, encendido) -> bool: un interruptor con su texto; devuelve cómo queda (cambia con un clic en el interruptor o en el texto).
- `tablero.encabezado(ui: gui.Ui, titulo: str, subtitulo: str)` — tablero.encabezado(ui, titulo, subtitulo): el título de la página, una línea gris debajo y un separador.

## `texto`

texto (use "texto").

Tipos: `texto.Cifras`.

- `texto.subtexto(s: str, desde: i32, hasta: i32) -> str` — Los caracteres de desde a hasta (sin incluir hasta). Los índices se ajustan al texto, como s[desde:hasta] en Python con índices no negativos.
- `texto.unir(partes: Vec<str>, sep: str) -> str` — Los textos de la lista con sep entre cada uno (sep.join(partes) de Python). Como toda fn que recibe un Vec, se queda con la lista.
- `texto.caracteres(s: str) -> Vec<str>` — Cada carácter como un texto aparte.
- `texto.invertir(s: str) -> str` — Al revés.
- `texto.repetir(s: str, n: i32) -> str` — s repetido n veces ("" si n <= 0).
- `texto.buscar_desde(s: str, sub: str, desde: i32) -> i32` — La posición de la primera aparición de sub desde la posición desde, o -1 (s.find(sub, desde) de Python, con desde >= 0).
- `texto.buscar(s: str, sub: str) -> i32` — La posición de la primera aparición de sub, o -1 (s.find(sub)).
- `texto.buscar_ultimo(s: str, sub: str) -> i32` — La posición de la última aparición de sub, o -1 (s.rfind(sub)).
- `texto.contiene(s: str, sub: str) -> bool`
- `texto.empieza(s: str, prefijo: str) -> bool`
- `texto.termina(s: str, sufijo: str) -> bool`
- `texto.contar(s: str, sub: str) -> i32` — Cuántas veces aparece sub sin pisarse (s.count(sub); con sub vacío, len + 1).
- `texto.reemplazar(s: str, viejo: str, nuevo: str) -> str` — Cada aparición de viejo cambiada por nuevo (s.replace(viejo, nuevo); con viejo vacío, s queda igual).
- `texto.dividir(s: str, sep: str) -> Vec<str>` — Los pedazos entre cada sep (s.split(sep) de Python): "a,,b" da "a", "" y "b"; "" da una lista con "". Un sep vacío es un panic, como en Python.
- `texto.dividir_espacios(s: str) -> Vec<str>` — Las palabras separadas por espacios, tabs o saltos de línea, sin pedazos vacíos (s.split() de Python).
- `texto.lineas(s: str) -> Vec<str>` — Las líneas, sin el "\n" ni un "\r" antes de él; un "\n" al final no agrega una línea vacía (como s.splitlines() de Python con "\n" y "\r\n").
- `texto.es_espacio(c: str) -> bool` — Un espacio, un tab, un salto de línea... (los mismos que str.isspace()).
- `texto.recortar(s: str) -> str` — Sin los espacios del principio y del final (s.strip()).
- `texto.recortar_izq(s: str) -> str` — Sin los espacios del principio (s.lstrip()).
- `texto.recortar_der(s: str) -> str` — Sin los espacios del final (s.rstrip()).
- `texto.rellenar_izq(s: str, ancho: i32, c: str) -> str` — s con relleno a la izquierda hasta tener ancho caracteres (s.rjust(ancho, c)).
- `texto.rellenar_der(s: str, ancho: i32, c: str) -> str` — s con relleno a la derecha hasta tener ancho caracteres (s.ljust(ancho, c)).
- `texto.centrar(s: str, ancho: i32, c: str) -> str` — s centrado en ancho caracteres (s.center(ancho, c): si sobra uno, va a la izquierda cuando ancho es impar, como en Python).
- `texto.mayusculas(s: str) -> str` — En mayúsculas, también con tildes y ñ (s.upper(), ver los límites arriba).
- `texto.minusculas(s: str) -> str` — En minúsculas, también con tildes y ñ (s.lower(), ver los límites arriba).
- `texto.es_letra(c: str) -> bool` — Una letra: ASCII, Latin-1 (á, ñ, ü, ç...) o Latin extendido A (ł, ő, š...).
- `texto.es_digito(c: str) -> bool` — Un dígito del 0 al 9.
- `texto.decimales(x: f64, n: i32) -> str` — x con n decimales, redondeado como f"{x:.{n}f}" de Python: decimales(2.675, 2) es "2.67" (el f64 de 2.675 es un poco menos), decimales(0.125, 2) es "0.12" (empate exacto: al par), decimales(-0.001, 2) es "-0.00". nan e inf salen como "nan", "inf" y "-inf". Con n <= 0, sin punto.
- `texto.con_miles(n: i64, sep: str) -> str` — Un entero con separador de miles: con_miles(1234567, ".") es "1.234.567" (f"{n:,}" de Python con "," cambiada por sep).
- `texto.decimales_miles(x: f64, n: i32, sep_miles: str, sep_decimal: str) -> str` — x con n decimales y separador de miles: decimales_miles(1234567.891, 2, ".", ",") es "1.234.567,89" (f"{x:,.{n}f}" de Python, con los separadores elegidos).
- `texto.a_f64(s: str) -> Result<f64>` — Un f64 escrito en texto: "3.25", "-0.5", "1e-3", "6.02E+23", ".5", "7.", "inf", "-inf", "nan" (con espacios alrededor, como float() de Python). Cuando el número es un entero de hasta 15 cifras por 10^k con k entre -22 y 22 (lo de casi todos los archivos de datos: "0.125", "3.25e5", "-12.75") da exactamente el f64 más cercano, igual que float(); si no, puede errar en el último bit.

## `web`

URLs y un cliente HTTP (use "web"). Escrita entera en SCAR, sobre los sockets del lenguaje.

Tipos: `web.Par`, `web.Url`, `web.Lista`, `web.Pares`, `web.Respuesta`, `web.Opciones`, `web.Cabecera`.

- `web.analizar(s: str) -> Result<Url>` — Parte una URL en esquema, autoridad, ruta, consulta y fragmento (urlsplit). Err si hay un [ sin ] o al revés en la autoridad.
- `web.armar(u: Url) -> str` — Junta las partes en una URL (urlunsplit): se pierde un ? o un # sin nada detrás.
- `web.host(u: Url) -> str` — El nombre del servidor, en minúsculas y sin los [ ] de una IPv6 (u.hostname de Python). "" si no hay.
- `web.puerto(u: Url) -> i32` — El puerto: -1 si no hay, -2 si está mal escrito o pasa de 65535 (u.port de Python).
- `web.usuario(u: Url) -> str`
- `web.clave(u: Url) -> str`
- `web.unir(base: str, ref: str) -> str` — Resuelve `ref` contra `base` (urljoin): "../z" contra "http://a.cl/x/y.html" da "http://a.cl/z". No separa los ;parámetros de la ruta.
- `web.pares() -> Pares`
- `web.poner(p: Pares, nombre: str, valor: str)`
- `web.cantidad(p: Pares) -> i32`
- `web.nombre_en(p: Pares, i: i32) -> str`
- `web.valor_en(p: Pares, i: i32) -> str`
- `web.consulta_leer(qs: str, conservar_vacios: bool) -> Pares` — Los pares nombre=valor de una consulta (parse_qsl). Con `conservar_vacios`, "a=" y "a" dan un par con valor "" (sin eso se saltan).
- `web.consulta_armar(p: Pares) -> str` — nombre=valor&nombre=valor con el escape de formularios (urlencode: espacio como +).
- `web.consulta_valor(qs: str, nombre: str, defecto: str) -> str` — El primer valor de `nombre` en una consulta, o `defecto`.
- `web.con_consulta(url: str, p: Pares) -> Result<str>` — Agrega pares a la consulta de una URL: con_consulta("http://a.cl/x?y=1", p) da "http://a.cl/x?y=1&z=2" si p tiene z=2.
- `web.opciones() -> Opciones`
- `web.cabecera(o: Opciones, nombre: str, valor: str)`
- `web.cabecera_de(r: Respuesta, nombre: str) -> str`
- `web.enviar(metodo: str, url: str, o: Opciones, cuerpo: codigos.Datos) -> Result<Respuesta>` — Un pedido con el método, la URL, las opciones y un cuerpo (bytes; vacío si no hay). Sigue redirecciones y reintenta según `o`. Err solo si no hubo respuesta: un 404 o un 500 llegan como Ok con su código.
- `web.obtener_con(url: str, o: Opciones) -> Result<Respuesta>`
- `web.obtener(url: str) -> Result<Respuesta>`
- `web.enviar_texto(url: str, tipo: str, cuerpo: str, o: Opciones) -> Result<Respuesta>` — POST de un texto con el Content-Type dado.
- `web.enviar_json(url: str, doc: json.Doc, o: Opciones) -> Result<Respuesta>` — POST de un documento de lib/json (Content-Type: application/json).
- `web.enviar_formulario(url: str, p: Pares, o: Opciones) -> Result<Respuesta>` — POST de un formulario (application/x-www-form-urlencoded).
- `web.cuerpo_texto(r: Respuesta) -> Result<str>` — El cuerpo como texto (Err si no es UTF-8).
- `web.json_de(r: Respuesta) -> Result<json.Doc>` — El cuerpo leído como JSON.
- `web.exito(r: Respuesta) -> bool` — ¿Salió bien (código 200 a 299)?

## `zlib`

comprimir y descomprimir con DEFLATE (use "zlib").

Tipos: `zlib.Bytes`, `zlib.Escritor`, `zlib.Tablas`, `zlib.Lector`, `zlib.Huff`, `zlib.Salida`.

- `zlib.crc32_parte(d: Bytes, i: i32, f: i32) -> i32` — CRC-32 (el de zlib, PNG y gzip) de los bytes de d desde i hasta f (sin f), como entero de 32 bits (puede salir negativo). Para sacarlo de un pedazo sin copiarlo (como los chunks de un PNG).
- `zlib.crc32(datos: Vec<i32>) -> i32` — CRC-32 de todos los bytes.
- `zlib.adler32(datos: Vec<i32>) -> i32` — Adler-32 (el del final de un flujo zlib).
- `zlib.deflate(datos: Vec<i32>) -> Vec<i32>` — DEFLATE crudo con LZ77 y Huffman fijo, en un solo bloque.
- `zlib.deflate_guardado(datos: Vec<i32>) -> Vec<i32>` — DEFLATE crudo sin comprimir: bloques guardados de hasta 65535 bytes.
- `zlib.comprimir(datos: Vec<i32>) -> Vec<i32>` — Comprime en formato zlib (encabezado, DEFLATE y Adler-32).
- `zlib.comprimir_guardado(datos: Vec<i32>) -> Vec<i32>` — Formato zlib sin comprimir (bloques guardados).
- `zlib.inflate(datos: Vec<i32>) -> Result<Vec<i32>>` — Descomprime DEFLATE crudo (sin el encabezado de zlib).
- `zlib.descomprimir(datos: Vec<i32>) -> Result<Vec<i32>>` — Descomprime el formato zlib: comprueba el encabezado y el Adler-32.
