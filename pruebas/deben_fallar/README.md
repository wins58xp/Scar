# Programas que deben ser rechazados

Cada `.scar` de esta carpeta rompe una regla de SCAR, y `scar check` tiene que
rechazarlo. La primera línea, `# espera: ...`, es un pedazo del mensaje de
error que tiene que dar (puede haber más de una).

Los corre `./pruebas/correr.sh` (solo estos: `./pruebas/correr.sh deben_fallar`).
Si uno pasa el check, se rompió una garantía del lenguaje. Los más graves son los de propiedad y tareas
(`tarea_*`, `canal_*`, `mover_*`, `prestamo_*`): son los que impiden que dos
tareas toquen la misma memoria.

Para agregar uno: escribe el programa, mira el mensaje con `scar check` y ponlo
en `# espera:`. No pongas números de
línea en el mensaje esperado: cambian apenas se edita el archivo.
