# 17. IA nativa

En este capítulo vas a juntar casi todo el libro: las cuentas, los structs, las
tareas y los canales, para escribir programas que **aprenden**. No hace falta
ninguna librería externa: las derivadas las calcula `lib/autodiff`, escrita en
SCAR, y el resto es el lenguaje de siempre.

La idea que lo ordena todo es la del capítulo 9: **una tarea es una región**.
Un modelo que aprende vive dentro de una tarea, que es su única dueña. Le llegan
datos por un canal, aprende, y nadie más puede tocar sus pesos. A eso lo
llamamos una **región cognitiva**.

## 17.1 Derivadas automáticas

Aprender, en casi toda la IA de hoy, es ajustar números (los *pesos*) para que
un error baje. Para saber hacia dónde moverlos hace falta la **derivada** del
error respecto de cada peso. Escribirla a mano es tedioso y frágil: cada vez que
cambia el modelo, cambia la fórmula.

`lib/autodiff` la calcula sola. Armas la cuenta paso a paso sobre una **cinta**,
que recuerda cada operación, y `derivar` la recorre al revés aplicando la regla
de la cadena:

```scar
use "autodiff"

fn main() {
    let c = autodiff.cinta()
    let x = autodiff.variable(c, 3.0)
    let y = autodiff.mul(c, x, x)
    autodiff.derivar(c, y)
    print(autodiff.valor(c, y))
    print(autodiff.gradiente(c, x))
}
```

```
9.0
6.0
```

`y = x²` vale 9 en `x = 3`, y su derivada, `2x`, vale 6. Nadie escribió `2x`:
salió de la cinta.

Cada valor de la cinta es un número (`i32`) que lo identifica; las operaciones
reciben y devuelven esos números. Hay `suma`, `resta`, `mul`, `div`, `neg`,
`escalar` (multiplicar por un número fijo), `cuadrado`, `exponencial`,
`logaritmo`, `tanh`, `sigmoide` y `relu`. Una cuenta más grande se arma igual:

```scar
use "autodiff"

fn main() {
    let c = autodiff.cinta()
    let x = autodiff.variable(c, 0.5)
    let w = autodiff.variable(c, 2.0)
    # f = sigmoide(w * x) + x²
    let f = autodiff.suma(c, autodiff.sigmoide(c, autodiff.mul(c, w, x)), autodiff.cuadrado(c, x))
    autodiff.derivar(c, f)
    print("f =", autodiff.valor(c, f))
    print("df/dx =", autodiff.gradiente(c, x))
    print("df/dw =", autodiff.gradiente(c, w))
}
```

```
f = 0.9810585786300049
df/dx = 1.3932238664829637
df/dw = 0.09830596662074093
```

`derivar` calcula la derivada respecto de **todos** los valores de la cinta de
una vez, y cuesta lo mismo que hacer la cuenta: por eso este método (el *modo
reverso*) es el que usan las redes neuronales, que tienen miles de pesos y una
sola salida.

## 17.2 Aprender: descenso de gradiente

Con la derivada en la mano, aprender es repetir un paso muy simple: mover cada
peso un poquito en contra de su derivada. Supongamos que los datos siguen una
recta `y = 2x + 1` y no lo sabemos. El modelo es `pred = w * x + b`, y el error
de un ejemplo es `(pred - y)²`:

```scar
use "autodiff"

fn main() {
    let mut w = 0.0
    let mut b = 0.0
    let tasa = 0.05
    let mut vuelta = 0
    while vuelta < 300 {
        for i in 0..5 {
            let x = to_f64(i) - 2.0
            let y = 2.0 * x + 1.0
            let c = autodiff.cinta()
            let vw = autodiff.variable(c, w)
            let vb = autodiff.variable(c, b)
            let pred = autodiff.suma(c, autodiff.escalar(c, vw, x), vb)
            let error = autodiff.resta(c, pred, autodiff.constante(c, y))
            autodiff.derivar(c, autodiff.cuadrado(c, error))
            w = w - tasa * autodiff.gradiente(c, vw)
            b = b - tasa * autodiff.gradiente(c, vb)
        }
        vuelta = vuelta + 1
    }
    print("w =", floor(w * 1000.0 + 0.5) / 1000.0, "b =", floor(b * 1000.0 + 0.5) / 1000.0)
}
```

```
w = 2.0 b = 1.0
```

Cada ejemplo arma su propia cinta, que se libera sola al terminar la vuelta del
`for`, como cualquier otro valor (capítulo 8). Si prefieres reusar una sola
cinta, `autodiff.limpiar(c)` la vacía.

La **tasa de aprendizaje** decide cuánto se mueve cada peso por paso. Muy chica
y aprende lento; muy grande y salta de un lado a otro sin llegar nunca. Vas a
jugar con ella en los ejercicios.

Lo importante: si mañana el modelo es otro (una curva, una red), el paso de
aprendizaje no cambia. Cambia la cuenta que armas sobre la cinta, y la derivada
sale sola.

## 17.3 Una región cognitiva

Hasta acá el modelo era un par de variables de `main`. En un programa real
llegan datos todo el tiempo, de varios lados, y el modelo tiene que seguir
aprendiendo mientras el resto del programa hace otras cosas. En SCAR eso es una
tarea:

```scar
use "autodiff"

struct Muestra {
    x: f64
    y: f64
}

struct Modelo {
    w: f64
    b: f64
}

fn aprender(m: Modelo, x: f64, y: f64, tasa: f64) -> Modelo {
    let c = autodiff.cinta()
    let w = autodiff.variable(c, m.w)
    let b = autodiff.variable(c, m.b)
    let pred = autodiff.suma(c, autodiff.escalar(c, w, x), b)
    let error = autodiff.resta(c, pred, autodiff.constante(c, y))
    autodiff.derivar(c, autodiff.cuadrado(c, error))
    return Modelo { w: m.w - tasa * autodiff.gradiente(c, w), b: m.b - tasa * autodiff.gradiente(c, b) }
}

task region(muestras: Chan<Muestra>) -> Modelo {
    let mut m = Modelo { w: 0.0, b: 0.0 }
    while let Some(s) = muestras.recv() {
        m = aprender(m, s.x, s.y, 0.05)
    }
    return m
}

fn main() {
    let datos: Chan<Muestra> = chan_new()
    let h = spawn region(datos)
    for i in 0..1000 {
        let x = to_f64(i % 9) - 4.0
        datos.send(Muestra { x: x, y: 2.0 * x + 1.0 })
    }
    datos.close()
    let m = h.join()
    print("y =", floor(m.w * 100.0 + 0.5) / 100.0, "x +", floor(m.b * 100.0 + 0.5) / 100.0)
}
```

```
y = 2.0 x + 1.0
```

Fíjate en lo que **no** hay: ningún candado, ninguna variable compartida. El
modelo vive en la región de `region`; `main` solo le manda muestras por el canal
y, cuando cierra el canal, recibe el modelo terminado con `join`. Si quisieras
tocar `m` desde `main` mientras la región aprende, el compilador no te deja: no
hay forma de nombrarlo desde afuera.

Esto escala sin cambiar nada: diez regiones, cada una con su canal y su modelo,
aprenden a la vez en los núcleos de tu procesador, y no pueden pisarse porque
ninguna ve la memoria de otra.

## 17.4 Darle un canal a una región que ya corre

A veces hay que cambiar algo de una región **mientras corre**: darle una fuente
de datos nueva, o un ajuste. Pasarlo al lanzarla no sirve, porque todavía no
existía. Para eso están `accepts`, `inject_chan` y `accept_chan`.

La tarea declara en su firma qué canales acepta recibir en caliente:

```scar-nocheck
task region(muestras: Chan<Muestra>) accepts Chan<f64> -> Modelo {
```

Desde afuera, `inject_chan(handle, canal)` le entrega un canal a la tarea que
corre detrás de ese handle. Devuelve un `Result`: falla si la tarea ya terminó o
si ya tiene un canal de ese tipo sin recoger.

Adentro, la tarea pregunta cuando le conviene con `accept_chan()`, que no
espera: da `Some(canal)` si alguien le inyectó uno, o `None`. Va siempre en un
`let` con el tipo escrito, porque de ahí sale qué canal se pide:

```scar-nocheck
let mut nuevo: Option<Chan<f64>> = accept_chan()
while let Some(canal) = nuevo {
    nuevo = None
    while let Some(t) = canal.recv() {
        tasa = t
    }
}
```

El programa de este capítulo, `ejemplos/17_ia_nativa.scar`, lo junta todo: dos
regiones aprenden rectas distintas en paralelo, y a una de ellas `main` le
inyecta un canal con una tasa de aprendizaje nueva mientras ya está aprendiendo:

```
A: terminó con la tasa nueva, 0.05
A aprendió y = 2.0 x + 1.0
B aprendió y = -1.0 x + 3.0
```

Las dos aprenden su recta sin saber nada una de la otra. El cambio de tasa le
llega a A en algún momento de su entrenamiento (cuándo exactamente depende de
cómo el sistema reparte los núcleos), y A lo toma en la vuelta siguiente, sin
pararse.

## 17.5 Redes neuronales con `neuronalgames`

Para modelos más grandes que una recta, `lib/neuronalgames` trae redes
neuronales de capas densas listas para usar, con la retropropagación ya escrita.
Está pensada para el bucle de un juego: bots y criaturas que aprenden de
ejemplos o por evolución. El clásico es el **XOR**, que una recta no puede
aprender y una red con una capa oculta sí:

```scar
use "neuronalgames"

fn main() {
    let r = neuronalgames.red(2, 7)
    neuronalgames.capa(r, 4, neuronalgames.tanh())
    neuronalgames.capa(r, 1, neuronalgames.sigmoide())
    let d = neuronalgames.datos(2, 1)
    neuronalgames.ejemplo(d, [0.0, 0.0], [0.0])
    neuronalgames.ejemplo(d, [0.0, 1.0], [1.0])
    neuronalgames.ejemplo(d, [1.0, 0.0], [1.0])
    neuronalgames.ejemplo(d, [1.0, 1.0], [0.0])
    neuronalgames.entrenar(r, d, 3000, 0.5)
    for a in 0..2 {
        for b in 0..2 {
            neuronalgames.entrada(r, 0, to_f64(a))
            neuronalgames.entrada(r, 1, to_f64(b))
            neuronalgames.calcular(r)
            print(a, "xor", b, "≈", floor(neuronalgames.salida(r, 0) + 0.5))
        }
    }
}
```

```
0 xor 0 ≈ 0.0
0 xor 1 ≈ 1.0
1 xor 0 ≈ 1.0
1 xor 1 ≈ 0.0
```

`red(2, 7)` es una red de 2 entradas con semilla 7: la misma semilla da siempre
los mismos pesos iniciales, así que el programa da lo mismo en cada corrida, y
en el intérprete igual que en el binario. El apéndice B tiene el resto de la
librería: neuroevolución, guardar y leer una red, el error sobre un conjunto de
datos.

¿Cuándo usar cuál? `neuronalgames` cuando el modelo es una red de capas y
quieres resultados ya. `autodiff` cuando el modelo es tuyo: una fórmula física
con parámetros, una pérdida rara, algo que no es una red. Y cualquiera de los
dos vive cómodo dentro de una región cognitiva.

## 17.6 Ejercicios

1. En el programa de §17.2 prueba con `tasa = 0.001` y con `tasa = 0.5`. ¿Qué
   pasa con `w` y `b` en cada caso? ¿Por qué?
2. Cambia el modelo de §17.2 por una parábola, `pred = a * x² + b`, y los datos
   por `y = 3x² - 2`. Solo tienes que cambiar la cuenta sobre la cinta.
3. En §17.3, lanza tres regiones que aprendan rectas distintas y manda cada
   muestra a la que corresponda. Compara el tiempo con una sola región que
   aprenda las tres seguidas.
4. Intenta leer `m.w` desde `main` mientras la región de §17.3 corre. ¿Qué dice
   el compilador?
5. En `ejemplos/17_ia_nativa.scar`, inyecta un segundo `Chan<f64>` a la región A
   sin que haya recogido el primero. ¿Qué devuelve `inject_chan`?
6. Con `neuronalgames`, cambia la capa oculta de §17.5 a 2 neuronas y después a
   1. ¿Desde cuántas aprende el XOR?
