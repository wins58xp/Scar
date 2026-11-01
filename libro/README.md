# El libro de SCAR

SCAR es un lenguaje de programación donde **una tarea y una región de memoria
son la misma cosa**: todo lo que una tarea crea es suyo, y se libera solo
cuando la tarea termina, sin recolector de basura y sin liberar nada a mano.
Las tareas corren en paralelo y no pueden pisarse, porque ninguna ve la memoria
de otra: lo que comparten, se lo mandan por canales.

Este libro enseña SCAR desde cero. No hace falta saber otro lenguaje, aunque si
conoces Rust, Go o Python vas a reconocer varias ideas. Cada capítulo trae su
programa completo en [`ejemplos/`](../ejemplos/), que corre igual con
`scar run` (el intérprete) y con `scar build` (un binario nativo).

## Índice

1. [Instalar y primer programa](01_instalar.md)
2. [Valores, variables y tipos](02_valores.md)
3. [Decidir y repetir](03_decidir_y_repetir.md)
4. [Funciones y structs](04_funciones_y_structs.md)
5. [Enums, `Option`, `Result` y errores](05_enums_y_errores.md)
6. [`Vec` y `Map`](06_vec_y_map.md)
7. [Texto](07_texto.md)
8. [Propiedad: quién es dueño de cada valor](08_propiedad.md)
9. [Tareas y regiones](09_tareas.md)
10. [Módulos y la librería estándar](10_modulos.md)
11. [Archivos y red](11_archivos_y_red.md)
12. [Compilar a binario nativo](12_compilar.md)
13. [Genéricos y funciones como valor](13_genericos.md)
14. [Hablar con C (y con Python)](14_hablar_con_c.md)
15. [Interfaces gráficas con `gui`](15_interfaces.md)
16. [Herramientas: formato, editor y pruebas](16_herramientas.md)
17. [IA nativa](17_ia_nativa.md)

Apéndices:

- A. [Funciones incorporadas](A_funciones_incorporadas.md)
- B. [La librería estándar](B_libreria_estandar.md)
- C. [Mensajes de error comunes](C_mensajes_de_error.md)

## Cómo leerlo

Los capítulos 1 a 7 son lo básico de cualquier lenguaje: si ya programas, puedes
leerlos rápido. Los capítulos 8 y 9 son el corazón de SCAR y conviene leerlos con
calma, en orden. Del 10 en adelante cada capítulo se puede leer por su cuenta.

Cada capítulo termina con ejercicios. Muchos te piden romper algo a propósito:
ver qué rechaza el compilador, y por qué, es la manera más rápida de entender
sus reglas.

Todos los bloques de código de este libro se prueban: compilan, y los que
muestran una salida dan exactamente esa salida, en el intérprete y en el
binario.
