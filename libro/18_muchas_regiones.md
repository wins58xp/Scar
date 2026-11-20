# 18. Un cerebro de miles de regiones

En el capítulo 17 una región cognitiva era una tarea con un modelo adentro. Este
capítulo da el paso siguiente: **muchas** regiones vivas a la vez, cientos, miles,
cien mil, cada una con su modelo y aprendiendo su propia parte del problema, y un
programa que les reparte el trabajo. Es lo que SCAR puede hacer y casi ningún
otro lenguaje: una tarea pesa unos 13 kB, así que cien mil regiones caben en la
memoria de un computador común, y ninguna puede pisar a otra.

## 18.1 Una región y un router

Hacen falta dos piezas:

- **La región**: una tarea que recibe muestras por su canal, aprende con cada una
  y contesta qué tan bien le fue (su pérdida).
- **El router**: el que reparte. En cada paso le manda una muestra a cada región y
  espera las respuestas de todas.

Aquí van ocho regiones. Cada una aprende con la cinta de vectores de
`lib/autodiff` (§17.3) a separar puntos en dos clases; las pares con una regla y
las impares con otra:

```scar
use "autodiff"

struct Muestra {
    x: Vec<f32>
    y: f32
}

struct Respuesta {
    region: i32
    perdida: f32
}

task region(id: i32, entrada: Chan<Muestra>, salida: Chan<Respuesta>) -> i32 {
    let c = autodiff.cinta_v()
    let w = autodiff.v_parametro(c, 1, 2, [0.0, 0.0])
    let b = autodiff.v_parametro(c, 1, 1, [0.0])
    let mut n = 0
    while let Some(m) = entrada.recv() {
        autodiff.v_reiniciar(c)
        let x = autodiff.v_constante(c, m.x)
        let z = autodiff.v_sigmoide(c, autodiff.v_suma(c, autodiff.v_matvec(c, w, x), b))
        let objetivo = autodiff.v_constante(c, [m.y])
        let perdida = autodiff.v_ecm(c, z, objetivo)
        autodiff.v_derivar(c, perdida)
        autodiff.v_aprender(c, 2.0)
        salida.send(Respuesta { region: id, perdida: autodiff.v_valor_en(c, perdida, 0) })
        n = n + 1
    }
    return n
}

# la muestra del paso p para la región r: un punto (a, b) y su clase
fn muestra(r: i32, p: i32) -> Muestra {
    let a = to_f32((p * 37 + r * 11) % 41) / 20.0 - 1.0
    let b = to_f32((p * 53 + r * 7) % 43) / 21.0 - 1.0
    let mut y: f32 = 0.0
    if r % 2 == 0 and a > b {
        y = 1.0
    }
    if r % 2 == 1 and a + b > 0.0 {
        y = 1.0
    }
    return Muestra { x: [a, b], y: y }
}

fn main() {
    let regiones = 8
    let pasos = 60
    let salida: Chan<Respuesta> = chan_new()
    let mut canales: Vec<Chan<Muestra>> = vec_new()
    let mut tareas: Vec<Task<i32>> = vec_new()
    for r in 0..regiones {
        let e: Chan<Muestra> = chan_new(2)
        tareas.push(spawn region(r, e, salida))
        canales.push(e)
    }
    let mut perdidas: Vec<f32> = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    for p in 0..pasos {
        for r in 0..regiones {
            match canales.get(r) {
                Some(e) => e.send(muestra(r, p)),
                None => {}
            }
        }
        for k in 0..regiones {
            match salida.recv() {
                Some(resp) => { perdidas[resp.region] = resp.perdida }
                None => {}
            }
        }
        if p == 0 or p == pasos - 1 {
            print("vuelta", p, "pérdida media:", perdidas.suma() / to_f32(regiones))
        }
    }
    for r in 0..regiones {
        match canales.get(r) {
            Some(e) => e.close(),
            None => {}
        }
    }
    let mut total = 0
    while let Some(t) = tareas.pop() {
        total = total + t.join()
    }
    print("muestras aprendidas:", total)
}
```

```
vuelta 0 pérdida media: 0.25
vuelta 59 pérdida media: 0.0770717
muestras aprendidas: 480
```

Fíjate en tres cosas:

- **Cada región es dueña de todo lo suyo.** La cinta `c`, con sus pesos `w` y `b`
  adentro como parámetros (§17.3), nace dentro de la tarea y nadie de afuera la
  puede nombrar. La cinta se
  presta a cada función de `autodiff` (capítulo 8): la función la cambia y la
  región la sigue teniendo.
- **Las muestras viajan movidas.** `e.send(muestra(r, p))` entrega la muestra a la
  región; el router ya no la tiene. Es lo que hace imposible que dos regiones
  toquen el mismo dato.
- **Un canal común para las respuestas.** Las ocho regiones mandan por `salida`, y
  el router no sabe en qué orden van a llegar: por eso cada respuesta trae su
  `region`, y la pérdida se guarda en su lugar (`perdidas[resp.region]`).

## 18.2 Canales con tope

Los canales de entrada se crean con `chan_new(2)`: caben dos muestras, y un
`send` a un canal lleno espera. Sin tope, si el router manda más rápido de lo que
una región aprende, la cola de esa región crece sin parar y se come la memoria.
Con tope, el router se frena solo al ritmo de la región más lenta. El canal de
respuestas puede ir sin tope: el router lee todo lo que llega en cada paso.

## 18.3 De ocho a cien mil

El programa no cambia para tener más regiones: cambia un número.
Con el mismo esquema, una red de verdad en cada región (4 entradas, 4 neuronas
ocultas, una salida) y el número de regiones como argumento, lo medimos con 1.000,
10.000 y 100.000.
En un Ryzen de 12 hilos, compilado:

| regiones | un paso (mediana) | por muestra | memoria | por región |
|---|---|---|---|---|
| 1.000 | 0,46 ms | 0,73 µs | 17 MB | 15,2 kB |
| 10.000 | 5,7 ms | 0,84 µs | 135 MB | 13,6 kB |
| 100.000 | 78 ms | 1,05 µs | 1,3 GB | 13,4 kB |

Un **paso** es el cerebro entero: cien mil muestras repartidas, cien mil redes que
aprenden y cien mil respuestas. El costo por muestra casi no cambia de mil a cien
mil regiones (en una máquina de 2 núcleos, todo es unas cuatro veces más lento,
pero igual de parejo), y cada región pesa lo mismo: crece en línea recta.

Con redes más grandes, el costo lo pone la red, no el número de regiones. En el
mismo Ryzen, con el router mandándole a cada región 4 muestras por paso
(`medir.py --redes ... --lotes 4`):

| red de cada región | regiones | un paso | por muestra | por región |
|---|---|---|---|---|
| 64 x 64 | 10.000 | 36 ms | 0,95 µs | 43 kB |
| 256 x 256 | 1.000 | 24 ms | 7,8 µs | 401 kB |

Una red de 256 x 256 tiene 65.536 pesos (256 kB en `f32`), y cada región ocupa poco
más que eso. Tres cosas hacen que una red así quepa y vaya rápido, y ninguna cambia lo
que aprende:

- **Los pesos viven en la cinta como parámetros** (§17.3), en vez de cargarse de nuevo
  en cada paso.
- **El gradiente de una matriz que se usa una sola vez no se arma entero:**
  `v_aprender` lo calcula fila por fila al momento de aprender.
- **Cada región aprende varias muestras seguidas** (un lote), mientras sus pesos
  siguen en la caché de su núcleo, en vez de traerlos de la memoria para cada muestra.

Antes de esas tres, la misma red de 256 x 256 tardaba 109 µs por muestra y cada región
ocupaba 1,3 MB.

Las pilas de las tareas se piden de a muchas juntas, así que 100.000 regiones
vivas caben sin tocar nada del sistema: Linux las ve como unas pocas zonas de
memoria, no como dos por tarea.

## 18.4 Tareas livianas o hilos

Por defecto, las tareas de SCAR son **livianas**: el programa reparte todas las
que lances entre unos pocos hilos, uno por núcleo (capítulo 9). Con la variable
de ambiente `SCAR_TAREAS=hilos`, cada tarea es un hilo del sistema operativo. El
programa y la salida son los mismos; el costo no:

| regiones | livianas: por muestra, por región | hilos: por muestra, por región |
|---|---|---|
| 1.000 | 0,73 µs, 15,2 kB | 1,7 µs, 84 kB |
| 10.000 | 0,84 µs, 13,6 kB | 2,7 µs, 84 kB |
| 100.000 | 1,05 µs, 13,4 kB | no se puede lanzar |

Con hilos, cada región cuesta seis veces más memoria (la pila de un hilo del
sistema) y cada muestra de dos a tres veces más tiempo, que además crece con las
regiones: el sistema operativo tiene que repartir el procesador entre decenas de
miles de hilos. Y con 100.000 ni siquiera parte: el sistema no da tantos hilos
(`no se pudo lanzar la tarea`). Con tareas livianas el costo casi no cambia de
mil a cien mil: por eso son el modo por defecto.

## 18.5 Ejercicios

1. Cambia `chan_new(2)` por `chan_new()` (sin tope) y haz que la región 0 duerma
   un poco en cada muestra (`sleep(0.01)`). ¿Qué pasa con la memoria si el router
   manda 1.000 pasos sin esperar respuestas?
2. Agrega un tercer tipo de región que aprenda `a > 0`, y reparte las regiones en
   tres grupos.
3. Corre `ejemplos/18_muchas_regiones.scar` compilado con 1.000 y con 10.000
   regiones (`scar build`, y el número como argumento). ¿Cuánto tarda cada paso?
   Repite con `SCAR_TAREAS=hilos`.
4. Haz que el router no espere a todas en cada paso: que mande el paso siguiente
   a una región apenas contesta. ¿Qué cambia en el tiempo total y qué en la
   pérdida?
5. Intenta usar los pesos `w` de una región desde `main`. ¿Qué dice el
   compilador? ¿Y si la región se los manda por un canal?
