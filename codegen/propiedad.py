"""Mixin Propiedad de Codegen (paso C6): quién libera cada valor. El registro
de dueñas por scope, los frees al cerrar un scope o al salir con return/break,
los movimientos (let, argumentos, campos, push/send), los flags de propiedad
y el registro de vivas para panic/cancelación. Si un valor es nuevo (y se
puede entregar sin copiar) lo decide Frescura.
"""

import re

from parser import (marca_new_generico, 
    Ident, Call, AssignStmt, FieldAccess, StructLit, TryExpr, OkExpr, ErrExpr,
    SomeExpr, NoneExpr, MethodCall, hijos,
)
from types_ import TypeAnn, T_I32, T_STR, mensaje_movida
import lugares

from .comun import (
    panic_c,
    BUILTIN_SIGS, CHAN_MARK, CodegenError, _expr_mentions_path, _field_path, literal_c,
    MAP_MARK, VEC_MARK,
)


class Propiedad:
    # ---- Registro de dueñas vivas (runtime) ----
    #
    # Una task cancelada (o que hace panic) salta con siglongjmp hasta su
    # envoltorio y se saltea los free() que el codegen emite al cerrar cada
    # scope. Para no perder lo vivo, cada dueña de owner_stack se refleja en un
    # registro por hilo (alta al nacer, baja al morir) y scar_vivos_soltar()
    # suelta todo antes del salto.
    #
    # Cuándo:
    #   - después de cada sentencia y al empezar cada bloque se reconcilia con
    #     owner_stack (_vivos_sync);
    #   - un movimiento (spawn, send, push, una fn que consume...) da de baja en
    #     el acto, antes de la llamada que se queda con el valor (si no, al
    #     cancelar se soltaría dos veces);
    #   - al cerrar un scope, baja de todo lo que se registró en él;
    #   - un return trunca el registro a lo que había al entrar a la función.
    # Alta y baja son idempotentes, así que dos caminos (if/else) nunca
    # duplican una entrada.

    def _new_tmp(self) -> str:
        self.tmp_counter += 1
        return f"__scar_tmp{self.tmp_counter}"

    def _flush_pending_expr_temps(self, out, pad):
        """Libera cada temporal de pending_expr_temps y vacía la lista.

        Se llama solo cuando el código que usa esos temporales ya se emitió
        (asignado, impreso, devuelto): antes sería un use-after-free. Por eso
        solo desde las sentencias que se evalúan una vez (let, asignación,
        return, expresión suelta), nunca desde la condición de un if/while/for:
        C la vuelve a evaluar en cada vuelta."""
        self._vivos_temps(out, pad)
        self._emit_pending_temp_frees(self.pending_expr_temps, out, pad)
        self.pending_expr_temps = []

    def _emit_pending_temp_frees(self, temps, out, pad):
        """Libera cada temporal de `temps` (el formato de pending_expr_temps) sin
        tocar la lista: al terminar la sentencia, y en la salida anticipada de un
        `?`."""
        for tmp in temps:
            if tmp.startswith("optfree:"):
                # una copia Option<Struct> de get()/pop()/recv() pasada directo como
                # argumento (ver _capture_fresh_option_arg)
                _, struct_name, name = tmp.split(":", 2)
                out.append(f"{pad}if ({name}.tag == 1) {struct_name}_free({name}.value);")
                continue
            if tmp.startswith("structfree:"):
                # un struct fresco usado sin dueña (ver _capture_fresh_struct_temp)
                _, free_fn, name = tmp.split(":", 2)
                out.append(f"{pad}{free_fn}({name});")
                continue
            if tmp.startswith("structfree_si_no:"):
                # un argumento fresco que la fn podía devolver: se suelta solo si no es
                # lo que devolvió
                _, free_fn, name, res = tmp.split(":", 3)
                out.append(f"{pad}if ({name} != {res}) {free_fn}({name});")
                continue
            if tmp.startswith("anular:"):
                # una variable de afuera cuya propiedad pasó al resultado (ya se soltó
                # arriba si no volvió)
                out.append(f"{pad}{tmp[len('anular:'):]} = NULL;")
                continue
            if tmp.startswith("dropfree:"):
                # un Vec/Map fresco usado sin dueña (ver _gen_method_call)
                _, drop, name = tmp.split(":", 2)
                out.append(f"{pad}{drop}(&{name});")
                continue
            out.append(f"{pad}scar_free((char*){tmp});")

    def _struct_free_fn(self, ty):
        """Nombre de la función que libera un struct de usuario de tipo `ty`, o
        None."""
        if ty is None:
            return None
        if ty.name in self.structs:
            return f"{ty.name}_free"
        if ty.name in self.generic_structs:
            return f"{self._ensure_generic_struct_instance(ty.name, ty.args)}_free"
        return None

    def _valor_transferible(self, expr, env, origen_destino=None) -> bool:
        """True si quien recibe `expr` en una asignación se puede quedar con él sin
        copiarlo: un valor fresco, una variable dueña (o la raíz dueña de su
        alias), o un campo de una dueña (se saca y queda vacío). Un Some/Ok con
        un str adentro, solo si ese str es fresco: con una variable, el str
        seguía siendo de ella y se liberaba al cerrar su bloque."""
        if origen_destino == "anidado":
            # el destino es dueño de todo lo de adentro (_es_anidado): se queda con
            # otra dueña, con un campo que se saca de una dueña o con un valor propio;
            # lo demás se copia
            if isinstance(expr, Ident):
                return self._is_owner(expr.name)
            if not isinstance(expr, FieldAccess):
                try:
                    ty = self.infer(expr, env)
                except CodegenError:
                    return False
                return self._valor_compuesto_propio(expr, ty, env)
        if isinstance(expr, (SomeExpr, OkExpr)):
            try:
                inner_ty = self.infer(expr.expr, env)
            except CodegenError:
                inner_ty = None
            if inner_ty is not None and inner_ty.name == "str":
                return self._let_creates_fresh_owner(expr.expr, marca_new_generico(expr.expr), env)
        if origen_destino is not None and origen_destino.startswith("result_str:"):
            # el destino libera también el .value: recibe un Err (lo deja en NULL),
            # una dueña con el mismo contrato o una llamada que entrega su .value
            # propio; lo demás se copia
            if isinstance(expr, ErrExpr):
                return True
            if isinstance(expr, Ident):
                if not self._is_owner(expr.name):
                    return False
                return (self._owner_origin(expr.name) or "").startswith("result_str:")
            if isinstance(expr, (Call, MethodCall)):
                try:
                    ty = self.infer(expr, env)
                except CodegenError:
                    return False
                return (self._print_fresh_result_origin(expr, ty, env) or "").startswith("result_str:")
        if self._let_creates_fresh_owner(expr, marca_new_generico(expr), env):
            return True
        if isinstance(expr, NoneExpr):
            return True
        if isinstance(expr, Ident):
            return self._is_owner(expr.name) or self._is_owner(self._resolve_alias_root(expr.name))
        if isinstance(expr, FieldAccess):
            raiz = expr
            while isinstance(raiz, FieldAccess):
                raiz = raiz.obj
            return isinstance(raiz, Ident) and self._is_owner(raiz.name)
        return False

    def _struct_moved_into(self, arg_expr, ty, code, env, out, pad) -> str:
        """El C de un struct que pasa a ser de otro (lo mueve
        scar_chan_send_<T>, que además suelta su bloque). Si quien llama es su
        dueño (un valor fresco, una variable dueña, un parámetro consumido), se
        entrega tal cual; un campo de un struct vivo sale y queda NULL; lo demás
        (un alias, el contenido de un Option ajeno) va como copia completa
        (_clone), para no quitárselo a su dueño."""
        if self._let_creates_fresh_owner(arg_expr, marca_new_generico(arg_expr), env):
            return code
        if isinstance(arg_expr, Ident):
            root = self._resolve_alias_root(arg_expr.name)
            if self._is_owner(arg_expr.name) or self._is_owner(root):
                self._note_owner_transfer(arg_expr, ty)
                return code
        if (isinstance(arg_expr, FieldAccess) and isinstance(arg_expr.obj, Ident)
                and self._is_owner(arg_expr.obj.name)):
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
            self._try_neutralize_extracted_field(arg_expr, ty, env, out, pad)
            return tmp
        return f"{ty.name}_clone({code})"

    # ---- propiedad: qué tipos tienen dueño, y el registro de dueñas ----
    def _is_ownable_type(self, ty: TypeAnn) -> bool:
        """True si un valor de este tipo puede tener un dueño que lo libera: un
        struct de usuario (también genérico), Vec, Map, str, Result (su .err es
        siempre un str propio), Option<struct | str | Vec | Map> y los
        Option/Result anidados (_es_anidado).

        Es una propiedad del tipo: si una variable puntual es dueña lo decide
        quien la marca (_let_creates_fresh_owner, LetStmt, gen_fn...). No tienen
        dueño los números, un Option de números (struct por valor sin nada en el
        heap), Pipe, Chan (una referencia compartida, con su contador) ni Task
        (su vida la lleva el runtime de tareas)."""
        return (
            ty.name in self.structs
            # struct genérico: `ty.name` puede ser el nombre crudo ('Caja')
            or ty.name in self.generic_structs
            or ty.name in (VEC_MARK, MAP_MARK, "str", "Result")
            or self._es_anidado(ty)
            or (
                ty.name == "Option"
                and ty.args
                and (ty.args[0].name in self.structs
                     or ty.args[0].name in ("str", VEC_MARK, MAP_MARK))
            )
        )

    def _es_anidado(self, ty) -> bool:
        """Un Option/Result de otro Option/Result/Chan con algo propio adentro
        (Option<Result<str>>, Option<Option<str>>, Option<Chan<T>>...). Una
        variable o un campo de estos tipos es dueña de todo lo de adentro: al
        construirla se toma lo propio y se copia lo prestado, y se libera entera
        con el origen "anidado"."""
        return (ty is not None and ty.name in ("Option", "Result") and bool(ty.args)
                and ty.args[0].name in ("Option", "Result", CHAN_MARK)
                and self._necesita_clonar(ty))

    def _str_owned_flag_name(self, param_name: str) -> str:
        """Nombre del bool oculto que acompaña a cada parámetro str de una task:
        dice si en este spawn puntual la hija recibió el str como dueña (ver
        _gen_spawn). Se decide en runtime, porque depende de quién lanzó la
        task."""
        return f"__scar_owned_{param_name}"

    def _push_owner_scope(self):
        self.owner_stack.append({})

    def _pop_owner_scope(self):
        """Saca y devuelve el frame más interno: {nombre: origen} de las dueñas
        que siguen siéndolo al cerrar ese scope (las que _emit_owner_frees
        libera)."""
        frame = self.owner_stack.pop()
        # los alias de liberación de un shadowing entre bloques valen solo
        # mientras el bloque que sombrea siga abierto
        if self._shadow_free_alias:
            depth = len(self.owner_stack)
            self._shadow_free_alias = {k: v for k, v in self._shadow_free_alias.items()
                                       if v[1] < depth}
        return frame

    def _vivos_temps(self, out, pad):
        """Los temporales de una sentencia (str frescos, copias de get()) también
        se registran: alta justo después de declararlos, baja justo antes de su
        free."""
        if not self._vivos_activo() or not self.pending_expr_temps:
            return
        altas, bajas = [], []
        for tmp in self.pending_expr_temps:
            if tmp.startswith("structfree_si_no:") or tmp.startswith("anular:"):
                # puede ser el mismo objeto que el resultado, que ya tiene dueña
                # registrada: no se registra (un panic en el medio lo pierde, nunca lo
                # suelta dos veces)
                continue
            if tmp.startswith("optfree:"):
                _, struct_name, name = tmp.split(":", 2)
                drop = self._vivo_drop_temp_opt(struct_name)
            elif tmp.startswith("structfree:"):
                _, free_fn, name = tmp.split(":", 2)
                drop = self._vivo_drop_temp_struct(free_fn)
            elif tmp.startswith("dropfree:"):
                _, drop, name = tmp.split(":", 2)
            else:
                name = tmp
                drop = self._vivo_drop_fn(T_STR, "plain")
            if drop is None or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                continue
            decl = re.compile(r"^\s*[A-Za-z_][\w\s\*]*\b" + re.escape(name) + r"\s*=")
            idx = next((i for i in range(len(out) - 1, -1, -1) if decl.match(out[i])), None)
            if idx is None:
                continue  # declarado en otra lista (condición de loop): no se registra
            altas.append((idx, f"{pad}scar_vivo_push(&{name}, {drop}, NULL);"))
            bajas.append(f"{pad}scar_vivo_baja(&{name}, __scar_vbase);")
        # cada alta va justo después de su declaración: entre un temporal y el
        # siguiente hay una llamada, y si la task se cancela ahí el primero tiene
        # que estar registrado
        for idx, alta in sorted(altas, key=lambda t: t[0], reverse=True):
            out.insert(idx + 1, alta)
        if altas:
            out.extend(reversed(bajas))

    def _vivo_drop_temp_struct(self, free_fn):
        """Drop de un temporal struct (_capture_fresh_struct_temp): `Nombre*`,
        liberado con Nombre_free."""
        key = ("tmp_struct", free_fn)
        if key in self._vivos_drop_cache:
            return self._vivos_drop_cache[key]
        ct = free_fn[:-len("_free")] + "*"
        fname = f"scar_drop_{len(self._vivos_drop_defs)}"
        self._vivos_drop_defs.append(
            f"static void {fname}(void *__scar_slot) {{\n"
            f"    {free_fn}(*({ct}*)__scar_slot);\n"
            f"}}"
        )
        self._vivos_drop_fwd.append(f"static void {fname}(void *__scar_slot);")
        self._vivos_drop_cache[key] = fname
        return fname

    def _vivo_drop_temp_opt(self, struct_name):
        key = ("tmp_opt", struct_name)
        if key in self._vivos_drop_cache:
            return self._vivos_drop_cache[key]
        fname = f"scar_drop_{len(self._vivos_drop_defs)}"
        self._vivos_drop_defs.append(
            f"static void {fname}(void *__scar_slot) {{\n"
            f"    Option_{struct_name} __scar_dv = *(Option_{struct_name}*)__scar_slot;\n"
            f"    if (__scar_dv.tag == 1) {struct_name}_free(__scar_dv.value);\n"
            f"}}"
        )
        self._vivos_drop_fwd.append(f"static void {fname}(void *__scar_slot);")
        self._vivos_drop_cache[key] = fname
        return fname

    def _vivos_activo(self):
        return self._vivos_fn_on

    def _vivo_c_name(self, name):
        c = name
        return c if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c) else None

    def _vivo_drop_fn(self, ty, origin):
        """Función de C `void drop(void* slot)` que suelta el valor de una
        variable de tipo `ty` con ese origen, con la misma lógica que
        _emit_owner_frees. None si no hay nada que soltar."""
        if origin.startswith("cond:"):
            # el origen de antes del break (ver _cond_base)
            base = getattr(self, "_cond_base", {}).get(origin[len("cond:"):], "plain")
        else:
            base = origin
        key = (repr(ty), base)
        cache = self._vivos_drop_cache
        if key in cache:
            return cache[key]
        lines = []
        saved = self._shadow_free_alias
        self._shadow_free_alias = {}
        prev_on = self._vivos_fn_on
        self._vivos_fn_on = False
        try:
            self._emit_owner_frees({"__scar_dv": base}, {"__scar_dv": ty}, lines, "    ")
        finally:
            self._shadow_free_alias = saved
            self._vivos_fn_on = prev_on
        if not lines:
            cache[key] = None
            return None
        fname = f"scar_drop_{len(self._vivos_drop_defs)}"
        ct = self.c_type(ty)
        self._vivos_drop_defs.append(
            f"static void {fname}(void *__scar_slot) {{\n"
            f"    {ct} __scar_dv = *({ct}*)__scar_slot;\n"
            + "\n".join(lines) + "\n}"
        )
        self._vivos_drop_fwd.append(f"static void {fname}(void *__scar_slot);")
        cache[key] = fname
        return fname

    def _vivos_sync(self, env, out, pad):
        if not self._vivos_activo():
            return
        vivos = {}
        for frame in self.owner_stack:
            for name, origin in frame.items():
                vivos[(id(frame), name)] = (origin, frame)
        pub = self._vivos_pub
        for key in list(pub):
            if key not in vivos and key[0] in self._vivos_frames_abiertos():
                c = self._vivo_c_name(key[1])
                if c is not None:
                    out.append(f"{pad}scar_vivo_baja(&{c}, __scar_vbase);")
                del pub[key]
        for key, (origin, frame) in vivos.items():
            if pub.get(key) == origin:
                continue
            name = key[1]
            if name in self._vivos_excluir:
                continue
            ty = env.get(name)
            c = self._vivo_c_name(name)
            if ty is None or c is None:
                continue
            drop = self._vivo_drop_fn(ty, origin)
            if drop is None:
                continue
            flag = f"&{origin[len('cond:'):]}" if origin.startswith("cond:") else "NULL"
            hist = self._vivos_hist.setdefault(id(frame), [])
            if name not in hist and frame is self.owner_stack[-1]:
                # primera vez en este scope (el más interno): en runtime no puede estar
                # registrada (cada cierre de scope la da de baja)
                out.append(f"{pad}scar_vivo_push(&{c}, {drop}, {flag});")
            else:
                out.append(f"{pad}scar_vivo_alta(&{c}, {drop}, {flag}, __scar_vbase);")
            pub[key] = origin
            if name not in hist:
                hist.append(name)

    def _vivos_frames_abiertos(self):
        return {id(f) for f in self.owner_stack}

    def _vivo_baja_inmediata(self, frame, name):
        if not self._vivos_activo() or self._vivos_out is None:
            return
        key = (id(frame), name)
        if key not in self._vivos_pub:
            return
        out, pad = self._vivos_out
        c = self._vivo_c_name(name)
        if c is not None:
            out.append(f"{pad}scar_vivo_baja(&{c}, __scar_vbase);")
        del self._vivos_pub[key]

    def _vivos_cerrar(self, frame, out, pad):
        """Al cerrar el scope de `frame` (ya sacado de owner_stack): baja de todo
        lo que alguna vez se registró en él, siga o no siendo dueña."""
        if not self._vivos_activo():
            return
        fid = id(frame)
        for name in reversed(self._vivos_hist.pop(fid, [])):
            c = self._vivo_c_name(name)
            if c is not None:
                out.append(f"{pad}scar_vivo_baja(&{c}, __scar_vbase);")
        for key in [k for k in self._vivos_pub if k[0] == fid]:
            del self._vivos_pub[key]

    def _mark_owner(self, name: str, origin: str):
        """Registra `name` como dueña de su valor en el scope más interno, con su
        origen, que dice cómo liberarlo:
          "plain": propio, se libera con su free de siempre ({T}_free sabe si el
                    bloque es de la arena o de malloc);
          "cond:<flag>": dueña solo si el flag de C es true (un parámetro
                    consumido, un str recibido por una task, una dueña
                    condicional);
          "chan": un Chan: se resta su referencia;
          "anidado": un Option/Result anidado, se libera entero;
          "result_str:plain": un Result<str> cuyo .value también es propio.

        También anota en _decl_frame el frame donde nació: una reasignación
        tiene que escribir ahí, no en el frame más interno del momento (ver
        _decl_frame_of)."""
        if self.owner_stack:
            self.owner_stack[-1][name] = origin
            self._decl_frame[name] = len(self.owner_stack) - 1

    def _decl_frame_of(self, name: str):
        """El índice en owner_stack del frame donde `name` se declaró por última
        vez (no cambia aunque pierda y recupere la propiedad), o None. Un alias
        de struct no pasa por _mark_owner: se sigue hasta su raíz, que sí tiene
        frame (si no, una reasignación del alias dentro de un if en un loop
        escribía en el frame del if y se liberaba en cada vuelta)."""
        frame = self._decl_frame.get(name)
        if frame is not None:
            return frame
        root = self._resolve_alias_root(name)
        if root != name:
            return self._decl_frame.get(root)
        return None

    def _unmark_owner(self, name: str, emitir: bool = True):
        """Quita a `name` de dueña, buscando el scope de adentro hacia afuera
        (como mark_moved del checker). Se usa cuando la propiedad se transfiere
        (_note_owner_transfer)."""
        for scope in reversed(self.owner_stack):
            if name in scope:
                del scope[name]
                # una variable que dejó de ser dueña (se movió) vuelve a serlo de lo que
                # se le asigne después
                self._desmarcadas.add(name)
                if emitir:
                    self._vivo_baja_inmediata(scope, name)
                return

    def _is_owner(self, name: str) -> bool:
        """True si `name` es dueña en algún frame de owner_stack, sin sacarla.
        Una asignación consulta con esto y nunca llama a _mark_owner: marcarla
        en el frame de un while (donde se reasigna) haría que se libere al
        cerrar cada vuelta."""
        for scope in reversed(self.owner_stack):
            if name in scope:
                return True
        return False

    def _owner_origin(self, name: str):
        """El origen guardado para `name` (ver _mark_owner), o None si no es
        dueña. Una asignación lo usa para saber cómo liberar el valor viejo."""
        for scope in reversed(self.owner_stack):
            if name in scope:
                return scope[name]
        return None

    def _struct_clone_def(self, name, fields):
        """Copia profunda de un struct con dueño propio de todo: bloque nuevo, str
        copiados, structs anidados clonados y Vec/Map clonados (_clone_fn). Es
        para los que copian (Vec.get(), Map.get()): original y copia se liberan
        cada uno por su lado. {T}_deepcopy queda para los que mueven."""
        lines = [f"    {name}* copy = scar_blk_heap(sizeof({name}));", "    *copy = *src;"]
        for fname, fty in fields.items():
            if fty.name in self.structs:
                lines.append(f"    if (src->{fname}) copy->{fname} = {fty.name}_clone(src->{fname});")
            elif fty.name == "str":
                self.needs_str_concat = True
                lines.append(f'    copy->{fname} = scar_str_concat(src->{fname}, "");')
            elif fty.name in (VEC_MARK, MAP_MARK):
                lines.append(f"    copy->{fname} = {self._clone_fn(fty)}(src->{fname});")
            elif self._campo_compuesto_con_dueno(fty):
                # Option/Result/Chan
                lines.append(f"    copy->{fname} = {self._clone_value_expr(fty, f'src->{fname}')};")
        lines.append("    return copy;")
        return f"static {name}* {name}_clone({name}* src) {{\n" + "\n".join(lines) + "\n}"

    def _clone_value_expr(self, ty, src):
        """C que copia con dueño propio un valor `src` de tipo `ty` (un elemento de
        Vec, una clave o un valor de Map)."""
        if ty.name == "str":
            self.needs_str_concat = True
            return f'scar_str_concat({src}, "")'
        if ty.name in self.structs:
            return f"{ty.name}_clone({src})"
        if ty.name in (VEC_MARK, MAP_MARK) or self._is_option_struct(ty):
            return f"{self._clone_fn(ty)}({src})"
        if ty.name in ("Option", "Result", CHAN_MARK) and self._necesita_clonar(ty):
            return f"{self._clone_fn(ty)}({src})"
        return src

    def _necesita_clonar(self, ty) -> bool:
        """True si una copia de un valor de `ty` tiene algo que duplicar (o, para
        un Chan, una referencia que contar)."""
        if ty.name == "str" or ty.name in self.structs or ty.name in (VEC_MARK, MAP_MARK, CHAN_MARK):
            return True
        if ty.name == "Result":
            return True  # el mensaje de Err es siempre un str propio
        if ty.name == "Option":
            return bool(ty.args) and self._necesita_clonar(ty.args[0])
        return False

    def _lineas_liberar_valor(self, ty, lvalue, pad="    "):
        """Las líneas que liberan un valor `lvalue` de tipo `ty`: las mismas que
        _emit_owner_frees emite para una dueña "plain" de ese tipo (con una
        variable de mentira que después se reemplaza por el lugar real)."""
        lines = []
        saved = self._shadow_free_alias
        self._shadow_free_alias = {}
        prev_on = self._vivos_fn_on
        self._vivos_fn_on = False
        try:
            self._emit_owner_frees({"__scar_fv": "plain"}, {"__scar_fv": ty}, lines, pad)
        finally:
            self._shadow_free_alias = saved
            self._vivos_fn_on = prev_on
        return [l.replace("__scar_fv", f"({lvalue})") for l in lines]

    def _lineas_liberar_dueno(self, ty, lv, pad="    "):
        """Las líneas que liberan un valor `lv` de tipo `ty` que es propio de
        quien lo guarda (un campo, el contenido de un Option/Result propio): se
        suelta el miembro en uso, recursivamente. A diferencia de una variable
        Result<str> (que puede traer el valor prestado), acá todo es propio."""
        if ty.name == "Option":
            sub = self._lineas_liberar_dueno(ty.args[0], f"({lv}).value", pad + "    ") if ty.args else []
            return ([f"{pad}if (({lv}).tag == 1) {{"] + sub + [f"{pad}}}"]) if sub else []
        if ty.name == "Result":
            inner = ty.args[0] if ty.args else T_I32
            sub = self._lineas_liberar_dueno(inner, f"({lv}).value", pad + "    ")
            lines = ([f"{pad}if (({lv}).tag == 1) {{"] + sub + [f"{pad}}}"]) if sub else []
            return lines + [f"{pad}scar_free((char*)({lv}).err);"]
        if ty.name == CHAN_MARK:
            ci = ty.args[0] if ty.args else T_I32
            return [f"{pad}scar_chan_decref_{self._mangled_name(ci)}({lv});"]
        if ty.name == "str":
            return [f"{pad}scar_free((char*)({lv}));"]
        free_fn = self._struct_free_fn(ty)
        if free_fn is not None:
            return [f"{pad}{free_fn}({lv});"]
        if ty.name in (VEC_MARK, MAP_MARK):
            return self._lineas_liberar_valor(ty, lv, pad)
        return []

    def _campo_compuesto_con_dueno(self, ty) -> bool:
        """Un campo Option/Result/Chan cuyo valor el struct posee: lo libera su
        {T}_free, lo copia su {T}_clone y, al construir o asignar, se toma lo
        propio y se copia lo prestado."""
        if ty.name not in ("Option", "Result", CHAN_MARK) or not self._necesita_clonar(ty):
            return False
        # también un Option/Result anidado: se saca del campo y se
        # libera con la misma regla
        return bool(self._lineas_liberar_dueno(ty, "x"))

    def _clone_fn(self, ty):
        """Nombre de `T scar_clone_N(T)` para un Vec/Map/Option/Result/Chan,
        generado una vez por tipo."""
        c_t = self.c_type(ty)
        fname = self._clone_names.get(c_t)
        if fname is not None:
            return fname
        fname = f"scar_clone_{len(self._clone_names)}"
        self._clone_names[c_t] = fname
        self.clone_protos.append(f"static {c_t} {fname}({c_t} src);")
        if ty.name == VEC_MARK:
            inner = ty.args[0] if ty.args else T_I32
            elem_c = self.c_type(inner) if inner.name not in self.structs else inner.name
            body = [
                f"    {c_t} out;",
                "    out.len = src.len;",
                "    out.cap = src.len;",
                f"    out.data = src.len ? malloc(sizeof({elem_c}) * (size_t)src.len) : NULL;",
                "    for (int32_t i = 0; i < src.len; i++) {",
            ]
            if inner.name in self.structs:
                body += [
                    f"        {inner.name}* __c = {inner.name}_clone(&src.data[i]);",
                    "        out.data[i] = *__c;",
                    "        scar_blk_release(__c);",
                ]
            elif inner.name == CHAN_MARK:
                ci = inner.args[0] if inner.args else T_I32
                body += [f"        out.data[i] = src.data[i];", f"        scar_chan_incref_{self._mangled_name(ci)}(src.data[i]);"]
            else:
                body.append(f"        out.data[i] = {self._clone_value_expr(inner, 'src.data[i]')};")
            body += ["    }", "    return out;"]
        elif self._is_option_struct(ty):
            # un Option<Struct>: contenido clonado
            inner = ty.args[0]
            body = [f"    if (src.tag == 1) src.value = {inner.name}_clone(src.value);",
                    "    return src;"]
        elif ty.name == "Option":
            # Option<str>, Option<Vec<..>>, Option<Chan<..>>...
            inner = ty.args[0]
            body = [f"    if (src.tag == 1) src.value = {self._clone_value_expr(inner, 'src.value')};",
                    "    return src;"]
        elif ty.name == "Result":
            # Result: el miembro en uso (Ok: value; Err: el mensaje)
            inner = ty.args[0] if ty.args else T_I32
            self.needs_str_concat = True
            body = [f"    if (src.tag == 1) src.value = {self._clone_value_expr(inner, 'src.value')};",
                    '    else if (src.err) src.err = scar_str_concat(src.err, "");',
                    "    return src;"]
        elif ty.name == CHAN_MARK:
            # un Chan es una referencia compartida: copiarlo es contar una más
            ci = ty.args[0] if ty.args else T_I32
            body = [f"    scar_chan_incref_{self._mangled_name(ci)}(src);", "    return src;"]
        else:
            key_ty = ty.args[0] if ty.args else T_STR
            val_ty = ty.args[1] if len(ty.args) > 1 else T_I32
            suffix = f"{key_ty.name}_{self._mangled_name(val_ty)}"
            if val_ty.name == CHAN_MARK:
                ci = val_ty.args[0] if val_ty.args else T_I32
                val_line = [f"        scar_chan_incref_{self._mangled_name(ci)}(src->entries[i].value);",
                            "        __typeof__(src->entries[i].value) __v = src->entries[i].value;"]
            else:
                val_line = [f"        __typeof__(src->entries[i].value) __v = "
                            f"{self._clone_value_expr(val_ty, 'src->entries[i].value')};"]
            body = [
                f"    {c_t} out = scar_map_new_{suffix}();",
                "    for (int32_t i = 0; i < src->cap; i++) {",
                "        if (src->entries[i].state != 1) continue;",
                f"        __typeof__(src->entries[i].key) __k = {self._clone_value_expr(key_ty, 'src->entries[i].key')};",
            ] + val_line + [
                f"        scar_map_set_{suffix}(out, __k, __v);",
                "    }",
                "    return out;",
            ]
        self.clone_defs.append(f"static {c_t} {fname}({c_t} src) {{\n" + "\n".join(body) + "\n}")
        return fname

    def _retval_free_fn(self, ret):
        """Nombre de un liberador `void f(void*)` para la caja del valor que
        devuelve una task sin join, de tipo Vec/Map/str: saca el T de adentro,
        lo libera como una dueña "plain" de ese tipo y después libera la caja."""
        c_t = self.c_type(ret)
        fname = self._retval_free_names.get(c_t)
        if fname is not None:
            return fname
        fname = f"scar_retval_free_{len(self._retval_free_names)}"
        self._retval_free_names[c_t] = fname
        body = []
        self._emit_owner_frees({"__scar_rv": "plain"}, {"__scar_rv": ret}, body, "    ")
        self.retval_free_defs.append(
            f"static void {fname}(void *box) {{\n"
            f"    {c_t} __scar_rv = *({c_t}*)box;\n"
            + "\n".join(body) + ("\n" if body else "")
            + f"    free(box);\n"
            f"}}"
        )
        return fname

    def _while_let_binds_chan_owner(self, expr, env) -> bool:
        """True si `expr` es .pop() de un Vec<Chan<T>> o .remove() de un
        Map<K,Chan<V>>: entrega la referencia que el contenedor contaba (sin
        incref nuevo), así que la variable que la recibe queda dueña con origen
        "chan" y la resta al cerrar su scope. get() no saca la referencia del
        contenedor: no es esto."""
        # `while let Some(ch) = extra` con extra una variable de
        # `let ... = accept_chan()`: accept_chan() entrega la referencia que
        # inject_chan() ya contó, así que la ligada también es dueña. Ninguna otra
        # variable se reconoce (seguiría siendo un préstamo).
        if isinstance(expr, Ident) and expr.name in getattr(self, "_accept_chan_vars", ()):
            return True
        if not isinstance(expr, MethodCall):
            return False
        obj_ty = self.infer(expr.obj, env)
        if expr.method == "pop" and obj_ty.name == VEC_MARK:
            inner = obj_ty.args[0] if obj_ty.args else T_I32
            return inner.name == CHAN_MARK
        if expr.method == "remove" and obj_ty.name == MAP_MARK:
            val_ty = obj_ty.args[1] if len(obj_ty.args) > 1 else T_I32
            return val_ty.name == CHAN_MARK
        if expr.method in ("recv", "try_recv") and obj_ty.name == CHAN_MARK:
            # Chan<Chan<T>>: recv() entrega la referencia que contó send()
            inner = obj_ty.args[0] if obj_ty.args else T_I32
            return inner.name == CHAN_MARK
        return False

    def _try_neutralize_extracted_field(self, expr, ty: TypeAnn, env, out, pad) -> bool:
        """`a = b.campo` con b una dueña viva y el campo un Vec, Map, struct u
        Option/Result con dueño: el campo se deja vacío ({0} para Vec/Map/
        Option/Result, NULL para un struct: {T}_free(NULL) no hace nada) en vez
        de desmarcar a b entera, así b se libera entera al cerrar su scope y el
        valor queda en `a`. Un str no pasa por acá. Devuelve True si
        lo vació (quien llama no debe llamar a _note_owner_transfer), False si
        no aplica."""
        compuesto = ty.name in ("Option", "Result") and self._campo_compuesto_con_dueno(ty)
        if ty.name not in (VEC_MARK, MAP_MARK) and ty.name not in self.structs and not compuesto:
            return False
        if not (isinstance(expr, FieldAccess) and isinstance(expr.obj, Ident)):
            return False
        container_name = expr.obj.name
        if not self._is_owner(container_name):
            # b ya no es dueña: no hay contenedor vivo que preservar
            return False
        if compuesto:
            # un Option/Result que el struct posee: {0} es None / un Err sin mensaje
            obj_code = self.gen_expr(expr.obj, env, out, pad)
            out.append(f"{pad}{obj_code}->{expr.field} = ({self.c_type(ty)}){{0}};")
            return True
        obj_code = self.gen_expr(expr.obj, env, out, pad)
        if ty.name in self.structs:
            # un struct de usuario es un puntero: vacío es NULL
            out.append(f"{pad}{obj_code}->{expr.field} = NULL;")
        else:
            c_ty = self.c_type(ty)
            out.append(f"{pad}{obj_code}->{expr.field} = ({c_ty}){{0}};")
        return True

    def _puede_tomar_campo(self, f_expr, f_ty) -> bool:
        if f_ty is None:
            return False
        compuesto = f_ty.name in ("Option", "Result") and self._campo_compuesto_con_dueno(f_ty)
        if f_ty.name not in (VEC_MARK, MAP_MARK) and f_ty.name not in self.structs and not compuesto:
            return False
        return (isinstance(f_expr, FieldAccess) and isinstance(f_expr.obj, Ident)
                and self._is_owner(f_expr.obj.name))

    @staticmethod
    def _es_lugar(e) -> bool:
        """El campo (o el campo de un campo) de una variable. Su valor lo puede
        cambiar una fn del usuario que recibe esa variable: si lo que se evalúa
        después llama a una, el lugar se lee antes (_fijar_lugar)."""
        if not isinstance(e, FieldAccess):
            return False
        while isinstance(e, FieldAccess):
            e = e.obj
        return isinstance(e, Ident)

    def _alcanza_lugar(self, expr, lugar) -> bool:
        """True si evaluar `expr` puede cambiar lo que vale `lugar`: solo una
        fn/task del usuario (también a través de un valor fn) que recibe un
        prefijo propio del camino (`s` o `s.red` para `s.red.actual`) y puede
        reasignar lo que falta (lugares.py). No hay variables globales. Con solo
        la raíz no alcanzaba: `agregar(s.ev, analizar(s.red.actual))` copiaba
        `s.ev` y agregar modificaba la copia."""
        raiz = lugar
        while isinstance(raiz, FieldAccess):
            raiz = raiz.obj
        if not isinstance(raiz, Ident):
            return False
        r = self._resolve_alias_root(raiz.name)
        if self._reasignaciones is None:
            conocidas = set(BUILTIN_SIGS) | set(self.extern_sigs)
            self._reasignaciones = (lugares.reasignaciones(self.program.items, conocidas), conocidas)
        efecto, conocidas = self._reasignaciones
        return lugares.puede_reemplazar(
            efecto, conocidas, expr, lugar,
            lambda n: n == raiz.name or self._resolve_alias_root(n) == r) is not None

    def _fijar_lugar(self, expr, code, env, out, pad, ty=None):
        """Lee ya el lugar `expr`, antes de lo que se evalúa después: el
        intérprete lee cada operando, argumento o campo de izquierda a derecha,
        en su momento. Un número va a un temporal; algo con dueño (str, struct,
        Vec...) se copia entero y la copia se suelta al terminar la sentencia
        (guardar solo el puntero no alcanza: la fn libera el valor viejo al
        reasignar el campo). Si quien llama ya transformó el código (una copia,
        un temporal), se guarda tal cual."""
        if ty is None:
            try:
                ty = self.infer(expr, env)
            except CodegenError:
                return code
        if ty is None or ty.name == "void":
            return code
        crudo = self.gen_expr(expr, env, [], pad)
        tmp = self._new_tmp()
        if code == crudo and self._necesita_clonar(ty):
            out.append(f"{pad}{self.c_type(ty)} {tmp} = {self._clone_value_expr(ty, code)};")
            if ty.name == "str":
                self.pending_expr_temps.append(tmp)
            else:
                drop = self._vivo_drop_fn(ty, "plain")
                if drop is not None:
                    self.pending_expr_temps.append(f"dropfree:{drop}:{tmp}")
        else:
            out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
        return tmp

    def _secuenciar(self, exprs, codes, env, out, pad, tys=None, bufs=None):
        """Evalúa los argumentos de izquierda a derecha, como el intérprete (C no
        fija el orden: gcc los evalúa de derecha a izquierda en x86-64). En
        orden, las sentencias previas de cada argumento y, si después viene algo
        que se evalúa, su valor a un temporal. Devuelve los códigos nuevos. Las
        sentencias de un argumento no pueden correr antes que las de uno
        anterior (`Dato { a: traza(4), b: s[9] }`)."""
        if bufs is None:
            bufs = [[] for _ in exprs]
        n = len(exprs)
        codes = list(codes)

        def simple(i):
            return self._expr_simple(exprs[i]) or self._RE_C_IDENT.fullmatch(codes[i])

        for i in range(n):
            out.extend(bufs[i])
            if (self._es_lugar(exprs[i]) and not self._RE_C_IDENT.fullmatch(codes[i])
                    and any(self._alcanza_lugar(exprs[j], exprs[i]) for j in range(i + 1, n))):
                # un campo, antes de una llamada que lo puede reasignar
                ty = tys[i] if tys is not None and i < len(tys) and tys[i] is not None else None
                codes[i] = self._fijar_lugar(exprs[i], codes[i], env, out, pad, ty)
                continue
            if simple(i):
                continue
            # también si más a la derecha se lee un campo que esta llamada puede
            # reasignar (`f(c.n + sube(c), c.n)`)
            if not any(bufs[j] or not simple(j)
                       or (self._es_lugar(exprs[j]) and self._alcanza_lugar(exprs[i], exprs[j]))
                       for j in range(i + 1, n)):
                continue
            ty = tys[i] if tys is not None and i < len(tys) and tys[i] is not None else None
            if ty is None:
                try:
                    ty = self.infer(exprs[i], env)
                except CodegenError:
                    ty = None
            if ty is None or ty.name == "void":
                continue
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(ty)} {tmp} = {codes[i]};")
            codes[i] = tmp
        return codes

    def _restaurar_duenas(self, nombres, owner_snapshot):
        """Vuelve a marcar como dueñas (con su origen de antes del if) las
        variables de `nombres` que consumió una rama que siempre retorna. En
        orden fijo: el orden decide el de los scar_vivo_alta, y un set lo hacía
        depender de PYTHONHASHSEED."""
        for n in sorted(nombres):
            for frame, copia in zip(self.owner_stack, owner_snapshot):
                if n in copia:
                    frame[n] = copia[n]

    def _take_owned_field(self, f_expr, f_ty, code, env, out, pad):
        """`c.campo` (Vec/Map/struct) de una dueña viva, usado donde se mueve (un
        campo de un struct literal, `B { v: a.v }`, o un `return a.v`): se saca
        a un temporal y el campo queda vacío, así `c` se libera entera más tarde
        sin tocar lo que se llevó. Devuelve el temporal, o None si no aplica."""
        if not self._puede_tomar_campo(f_expr, f_ty):
            return None
        tmp = self._new_tmp()
        out.append(f"{pad}{self.c_type(f_ty)} {tmp} = {code};")
        self._try_neutralize_extracted_field(f_expr, f_ty, env, out, pad)
        return tmp

    def _is_moved_container_type(self, ty) -> bool:
        """Vec, Map y Option de uno de ellos: los tipos que una fn o task recibe
        siempre como dueña."""
        if ty.name in (VEC_MARK, MAP_MARK):
            return True
        return (ty.name == "Option" and bool(ty.args)
                and ty.args[0].name in (VEC_MARK, MAP_MARK))

    def _moves_owned_field(self, arg_expr, ty) -> bool:
        return (ty is not None and ty.name in (VEC_MARK, MAP_MARK)
                and isinstance(arg_expr, FieldAccess) and isinstance(arg_expr.obj, Ident)
                and self._is_owner(arg_expr.obj.name))

    def _capture_args_reading_moved_fields(self, args, tys, args_code, env, out, pad):
        """_move_arg_out vacía el campo antes de la llamada: si otro argumento de
        la misma llamada lo lee (`f(c.data.len(), c.data)`), se evalúa antes en
        un temporal."""
        paths = [_field_path(a) for a, t in zip(args, tys) if self._moves_owned_field(a, t)]
        if not paths:
            return
        for k, (a, t) in enumerate(zip(args, tys)):
            if self._moves_owned_field(a, t):
                continue
            if any(_expr_mentions_path(a, pth) for pth in paths):
                try:
                    a_ty = self.infer(a, env)
                except CodegenError:
                    continue
                tmp = self._new_tmp()
                out.append(f"{pad}{self.c_type(a_ty)} {tmp} = {args_code[k]};")
                args_code[k] = tmp

    def _move_arg_out(self, arg_expr, ty, code, env, out, pad) -> str:
        """Mueve un Vec/Map/Option<Vec|Map> pasado a una fn o un spawn (que pasa
        a ser su dueño). Si es el campo de un struct vivo (`f(c.data)`), el
        valor se saca a un temporal y el campo queda vacío, así el struct se
        libera entero."""
        if self._moves_owned_field(arg_expr, ty):
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
            self._try_neutralize_extracted_field(arg_expr, ty, env, out, pad)
            return tmp
        self._note_owner_transfer(arg_expr, ty)
        return code

    def _gen_field_assign_move(self, stmt, target_code, expr_code, env, out, pad) -> bool:
        """`obj.campo = valor` con un campo que el struct posee (Vec, Map, struct,
        str). El checker lo trata como un movimiento: el campo recibe un valor
        propio y la raíz de origen deja de ser dueña, como al construir el
        struct. Orden: (1) el valor nuevo a un temporal (puede leer el viejo:
        `c.nombre = c.nombre + "x"`), (2) liberar el viejo, (3) asignar, (4)
        transferir la propiedad.

        Si el valor nuevo menciona el mismo campo (`c.data = f(c.data)`), el
        viejo se movió a la llamada y no se libera acá (sería double free); si
        f solo lo lee, queda una pérdida, nunca un free inválido.

        Devuelve False si el campo no es de un tipo que el struct posea (quien
        llama emite el `=` de siempre)."""
        fty = self.infer(stmt.target, env)
        if fty is None:
            return False
        if self._campo_compuesto_con_dueno(fty):
            # Option/Result/Chan que el struct posee: lo propio se entrega, lo
            # prestado se copia (un Chan cuenta una referencia más). Mismo orden que
            # arriba.
            if self._valor_compuesto_propio(stmt.expr, fty, env):
                val = expr_code
            else:
                val = self._clone_value_expr(fty, expr_code)
            tmp = self._new_tmp()
            out.append(f"{pad}{self.c_type(fty)} {tmp} = {val};")
            self._flush_pending_expr_temps(out, pad)
            out.extend(self._lineas_liberar_dueno(fty, target_code, pad))
            out.append(f"{pad}{target_code} = {tmp};")
            return True
        is_generic = fty.name in self.generic_structs
        if not (fty.name in self.structs or is_generic
                or fty.name in (VEC_MARK, MAP_MARK, "str")):
            return False
        if fty.name == "str":
            # str: el campo queda con un str propio; una dueña local "plain" se
            # transfiere, lo fresco se entrega y todo lo demás (literal, prestado) se
            # copia
            simple_env = env
            if (self._is_fresh_str_concat_expr(stmt.expr, simple_env)
                    or self._is_fresh_str_call(stmt.expr)):
                val = expr_code
            elif (isinstance(stmt.expr, Ident) and self._is_owner(stmt.expr.name)
                    and self._owner_origin(stmt.expr.name) == "plain"):
                val = expr_code
                self._unmark_owner(stmt.expr.name)
            else:
                self.needs_str_concat = True
                val = f'scar_str_concat({expr_code}, "")'
            tmp = self._new_tmp()
            out.append(f"{pad}const char* {tmp} = {val};")
            self._flush_pending_expr_temps(out, pad)
            out.append(f"{pad}scar_free((char*){target_code});")
            out.append(f"{pad}{target_code} = {tmp};")
            return True
        # el valor viejo se libera con {S}_free, que sabe si el bloque es de
        # malloc o de la arena, y el nuevo se guarda tal cual
        c_ty = self.c_type(fty)
        tmp = self._new_tmp()
        out.append(f"{pad}{c_ty} {tmp} = {expr_code};")
        self._flush_pending_expr_temps(out, pad)
        path = _field_path(stmt.target)
        if path is None or not _expr_mentions_path(stmt.expr, path):
            self._emit_field_value_free(fty, target_code, out, pad)
        out.append(f"{pad}{target_code} = {tmp};")
        if not self._try_neutralize_extracted_field(stmt.expr, fty, env, out, pad):
            self._note_owner_transfer(stmt.expr, fty)
        return True

    def _emit_field_value_free(self, fty, code, out, pad):
        """Libera el valor que tiene ahora un campo Vec/Map/struct, como lo haría
        {S}_free del contenedor. Un campo ya extraído quedó vacío y liberarlo no
        hace nada."""
        if fty.name == VEC_MARK:
            inner = fty.args[0] if fty.args else T_I32
            out.append(f"{pad}scar_vec_free_{self._mangled_name(inner)}({code});")
        elif fty.name == MAP_MARK:
            key_ty = fty.args[0] if fty.args else T_I32
            val_ty = fty.args[1] if len(fty.args) > 1 else T_I32
            out.append(f"{pad}scar_map_free_{key_ty.name}_{self._mangled_name(val_ty)}({code});")
        else:
            sname = (self._ensure_generic_struct_instance(fty.name, fty.args)
                     if fty.name in self.generic_structs else fty.name)
            out.append(f"{pad}{sname}_free({code});")

    def _note_owner_transfer(self, arg_expr, arg_ty: TypeAnn):
        """Si arg_expr es (la raíz de) una dueña de algo con dueño, deja de serlo:
        su valor pasa a otro (spawn, send, push, una fn que lo consume, un
        campo). No emite C para quitarla de owner_stack; sí da de baja en el
        registro de vivas."""
        if not self._is_ownable_type(arg_ty):
            return
        root_name = self._ident_root_name(arg_expr)
        if root_name is None:
            return
        if isinstance(arg_expr, Ident) and root_name in self._opt_payload_of:
            # p es el contenido de una dueña Option<Struct> (_opt_payload_of):
            # moverlo deja al Option en None, así su free no libera nada
            self._pending_takes.append(self._opt_payload_of[root_name])
            return
        # Mover un alias de struct (`let b = a; xs.push(b)`) mueve el objeto de
        # su raíz: se desmarca a `a` (desmarcar solo a b dejaba a `a` liberándose
        # mientras el contenedor también lo liberaba). Solo structs: un Vec/Map no
        # se aliasa (`let b = a` lo mueve).
        if arg_ty.name in self.structs:
            root_name = self._resolve_alias_root(root_name)
        flag = self._consume_flags.get(root_name)
        if flag is None or self._owner_origin(root_name) != f"cond:{flag}":
            # una variable de afuera de un loop que el cuerpo mueve: se apaga su
            # flag de loop
            flag = self._flag_de_loop(root_name) if self._loop_frames else None
        if flag is not None and self._owner_origin(root_name) == f"cond:{flag}":
            # un parámetro consumido con flag: no se desmarca (eso valdría para
            # todos los caminos); se apaga el flag en runtime al terminar la sentencia
            self._pending_flag_clears.append(flag)
            # el registro de vivas no espera al fin de la sentencia: la fn llamada
            # es dueña desde su entrada (se registra sola).
            for scope in reversed(self.owner_stack):
                if root_name in scope:
                    self._vivo_baja_inmediata(scope, root_name)
                    break
            return
        self._apagar_flag_de_loop(root_name, arg_ty)
        self._unmark_owner(root_name)

    def _gen_break(self, env, out, pad):
        """`break`: antes de saltar libera lo vivo en los scopes de adentro del
        loop (como un return libera los de la función) y lo da de baja del
        registro de vivas. No toca owner_stack: los caminos que no pasan por el
        break siguen viéndolas vivas. Una variable de afuera que este camino ya
        movió queda con su flag en false, y al cerrar el loop su free depende
        del flag (_fin_de_loop)."""
        loop = self._loop_frames[-1]
        depth = loop["depth"]
        live = {}
        for idx, scope in enumerate(self.owner_stack):
            if idx < depth:
                continue
            for name, origin in scope.items():
                alias = self._shadow_free_alias.get((idx, name))
                live[alias[0] if alias is not None else name] = origin
        self._emit_owner_frees(live, env, out, pad)
        if self._vivos_activo():
            for frame in reversed(self.owner_stack[depth:]):
                for name in reversed(self._vivos_hist.get(id(frame), [])):
                    c = self._vivo_c_name(name)
                    if c is not None:
                        out.append(f"{pad}scar_vivo_baja(&{c}, __scar_vbase);")
        ahora = self._duenas_ahora()
        for n in sorted(loop["duenas"]):
            i = self._decl_frame_of(n)
            if n in ahora or i is None or i >= depth:
                continue
            flag = self._flag_de_loop(n)
            if flag is None:
                continue
            out.append(f"{pad}{flag} = false;")
            loop.setdefault("salen_movidas", {})[n] = flag
        out.append(f"{pad}break;")

    def _fin_de_loop(self, loop):
        """Al cerrar un loop: las variables de afuera que algún `break` dejó
        movidas siguen siendo dueñas en los caminos que no pasaron por él, así
        que su free pasa a depender del flag, con el origen que tenían."""
        for n, flag in loop.get("salen_movidas", {}).items():
            scope = next((sc for sc in reversed(self.owner_stack) if n in sc), None)
            if scope is None:
                # el codegen la ve movida porque el cuerpo siempre sale por un break,
                # pero si el loop no dio ninguna vuelta sigue siendo de acá: vuelve a su
                # frame, con flag
                i = self._decl_frame_of(n)
                if i is None or i >= len(self.owner_stack):
                    continue
                scope = self.owner_stack[i]
                origen = loop["duenas"].get(n, "plain")
            else:
                origen = scope[n]
            if origen != f"cond:{flag}":
                if origen.startswith("cond:"):
                    origen = self._cond_base.get(origen[len("cond:"):], "plain")
                self._cond_base[flag] = origen
                scope[n] = f"cond:{flag}"

    def _duenas_con_flag(self, stmt):
        """Al entrar a un loop, una variable de afuera que el cuerpo mueve
        (stmt.mueve_de_afuera, del checker) pasa a ser dueña según su flag de
        loop (origen "cond:<flag>"), como un parámetro consumido: moverla apaga
        el flag, darle otro valor libera el viejo solo si el flag dice que es
        suyo y lo prende, y el free del final de su alcance depende del flag.
        Hace falta porque el cuerpo se genera una sola vez: al ver `v = nuevo()`
        no se sabe que más abajo se mueve."""
        for nodo in getattr(stmt, "mueve_de_afuera", ()) or ():
            n = self._resolve_alias_root(nodo.name)
            i = self._decl_frame_of(n)
            if i is None or i >= len(self.owner_stack) or n not in self.owner_stack[i]:
                continue
            origen = self.owner_stack[i][n]
            if origen.startswith("cond:"):
                continue
            flag = self._flag_de_loop(n)
            if flag is None:
                continue
            self._cond_base[flag] = origen
            self.owner_stack[i][n] = f"cond:{flag}"

    def _verificar_movida(self, expr, out, pad):
        """Un uso de una variable que una vuelta anterior pudo mover en una sola
        rama de un if (lo marca el checker): su flag de dueña dice en runtime si
        todavía es suya; si no, panic con el mismo mensaje que el intérprete."""
        raiz = self._resolve_alias_root(expr.name)
        flag = self._consume_flags.get(raiz)
        if flag is None or self._owner_origin(raiz) != f"cond:{flag}":
            flag = self._flag_de_loop(raiz)
        if flag is None:
            return
        texto = mensaje_movida(self.nombres.mostrar(expr.name))
        texto = texto.replace("%", "%%")
        fn_panic = panic_c(self.has_tasks)
        out.append(f'{pad}if (!{flag}) {fn_panic}({literal_c(texto)});')

    def _apagar_flag_de_loop(self, root_name, ty):
        """`for .. { xs.push(v); v = nuevo }`: moverla dentro del loop apaga su
        flag (que se crea acá si la asignación, más abajo en el cuerpo, todavía
        no lo creó). Si no, la asignación de la vuelta siguiente liberaba lo que
        ya tenía el Vec."""
        if not (ty.name in self.structs or ty.name in (VEC_MARK, MAP_MARK)):
            return
        flag = self._flag_de_loop(root_name)
        if flag is not None:
            self._pending_flag_clears.append(flag)

    def _flag_de_loop(self, root_name):
        """El flag de loop de `root_name`, uno por variable: vive en el
        loop más externo de los que están dentro del alcance de la variable, se
        declara al principio de la función (_flags_de_fn, así lo ve el free del
        final de su alcance) y se reinicia antes de ese loop. None si la
        variable es del cuerpo del loop más interno."""
        i = self._decl_frame_of(root_name)
        if i is None:
            return None
        frame = next((f for f in self._loop_frames if f.get("depth", 0) > i), None)
        if frame is None:
            return None
        flag = frame["flags"].get(root_name)
        if flag is None:
            flag = self._new_tmp()
            frame["flags"][root_name] = flag
            self._flags_de_fn.append(flag)
            # al entrar al loop la variable es dueña si ya lo era antes (un `let` de
            # afuera): si el loop no da ninguna vuelta, el free del final igual la
            # libera. Un parámetro prestado no es dueño: false.
            inicial = "true" if root_name in frame.get("duenas", ()) else "false"
            frame["out"].insert(frame["idx"], f'{frame["pad"]}{flag} = {inicial};')
            self._flag_var[flag] = root_name
        return flag

    def _flag_si_hay(self, root_name):
        """El flag de loop que ya tiene `root_name`, sin crearlo; None si no
        tiene."""
        i = self._decl_frame_of(root_name)
        if i is None:
            return None
        frame = next((f for f in self._loop_frames if f.get("depth", 0) > i), None)
        if frame is None:
            return None
        return frame["flags"].get(root_name)

    def _apagar_flags(self, nombres, out, pad):
        """Después del free sintético de la rama que no movió una variable, la
        variable ya no es dueña en ningún camino: si tiene flag de loop, esta
        rama también lo apaga (la que la movió ya lo hace). Si no, una
        reasignación después del if liberaba de nuevo (`if hay { xs.push(a) };
        a = nuevo()` en un loop: double free)."""
        for n in sorted(nombres):
            flag = self._flag_si_hay(n)
            if flag is not None:
                out.append(f"{pad}{flag} = false;")

    def _duenas_ahora(self):
        """Las variables que en este punto son dueñas de su valor (en cualquier
        frame), con su origen (nombre -> origen; sirve también como conjunto)."""
        return {n: o for scope in self.owner_stack for n, o in scope.items()}

    def _resolve_alias_root(self, name: str) -> str:
        """Sigue la cadena de _alias_root hasta la raíz ('let b = a; let c = b':
        c -> a). Si `name` no es un alias, lo devuelve tal cual, así que se
        puede llamar sobre cualquier nombre. Protegida contra ciclos (no
        deberían formarse: cada entrada apunta a una variable anterior)."""
        seen = set()
        while name in self._alias_root and name not in seen:
            seen.add(name)
            name = self._alias_root[name]
        return name

    def _live_owners_at_return(self, exclude_names):
        """Las dueñas vivas en todos los frames de owner_stack ({nombre:
        origen}): las que un `return` libera. No modifica owner_stack: los
        caminos que no pasan por este return siguen viéndolas vivas.

        `exclude_names`: las que el return entrega (devueltas tal cual o
        puestas en un struct literal, _returned_owner_names). Se calcula antes
        de generar la expresión y tiene que coincidir con lo que después
        transfiere gen_expr: si queda corto, se libera algo ya entregado
        (use-after-free)."""
        live = {}
        for idx, scope in enumerate(self.owner_stack):
            for name, origin in scope.items():
                # Una dueña de un frame de afuera que un `let` interno sombrea con el
                # mismo nombre no es alcanzable por su nombre (en C ese nombre ya es la
                # variable nueva): se libera por la temporal que guardó su valor.
                alias = self._shadow_free_alias.get((idx, name))
                if alias is not None:
                    live[alias[0]] = origin
                else:
                    live[name] = origin
        if exclude_names:
            for name in exclude_names:
                live.pop(name, None)
        return live

    def _transferencias_del_return(self, live, excluir, out, pad):
        """Generar la expresión de un return puede transferir dueñas (un argumento
        que la fn llamada se queda, un Some/Ok que se lleva su contenido), y
        `live` se calculó antes. Los flags y los take que esa transferencia deja
        pendientes se escriben acá, antes de liberar, y `live` pierde lo que ya
        no es de este scope."""
        for flag in dict.fromkeys(self._pending_flag_clears):
            out.append(f"{pad}{flag} = false;")
        self._pending_flag_clears = []
        for o in dict.fromkeys(self._pending_takes):
            self._emit_take(o, out, pad)
        self._pending_takes = []
        sigue = self._live_owners_at_return(excluir)
        return {n: origen for n, origen in live.items() if n in sigue}

    def _returned_owner_name(self, expr):
        """La dueña que un `return` devuelve tal cual, en las dos formas que no
        construyen nada (`return x`, `return Ok(x)` / `return Some(x)`: el
        envoltorio no copia x), o None. Con None, el resultado se captura en un
        temporal antes de liberar. Para saber qué excluir de `live` está
        _returned_owner_names."""
        if isinstance(expr, Ident):
            return expr.name
        if isinstance(expr, (OkExpr, SomeExpr)) and isinstance(expr.expr, Ident):
            return expr.expr.name
        return None

    def _returned_owner_names(self, expr, env=None) -> set:
        """Las dueñas que un `return` entrega a quien llama: la variable devuelta
        (y la raíz de su alias), lo que entrega un Ok/Some y cada campo de un
        struct literal. Tienen que ser exactamente las que gen_expr transfiere
        al generar la misma expresión: si no coinciden, use-after-free o
        pérdida. Cualquier otra forma no aporta nada."""
        if isinstance(expr, Ident):
            # si la variable es un alias de struct, su raíz también se entrega
            return {expr.name, self._resolve_alias_root(expr.name)}
        if isinstance(expr, (OkExpr, SomeExpr)):
            return self._returned_owner_names(expr.expr, env)
        if isinstance(expr, StructLit):
            campos = self._campos_concretos(expr, env)
            names = set()
            for f_name, f_expr in expr.fields.items():
                f_ty = campos.get(f_name)
                if f_ty is not None and f_ty.name == "str" and not getattr(f_expr, "se_mueve", True):
                    # el checker no la movió: el campo recibe una copia y la variable se
                    # libera como siempre
                    continue
                if (f_ty is not None and self._campo_compuesto_con_dueno(f_ty)
                        and not self._valor_compuesto_propio(f_expr, f_ty, env)):
                    # un campo Option/Result/Chan se copia de lo prestado: la variable sigue
                    # siendo dueña de lo suyo
                    continue
                names |= self._returned_owner_names(f_expr, env)
            return names
        return set()

    def _campos_concretos(self, expr, env):
        """{campo: tipo concreto} del struct que arma el literal `expr` (su
        instancia si es genérico), como lo resuelve StructLit en gen_expr; {} si
        no se puede saber."""
        if expr.name in self.generic_structs:
            if env is None:
                return {}
            try:
                args = self._generic_struct_concrete_args(expr, env, self.cur_ret_ty)
                return self.structs.get(self._ensure_generic_struct_instance(expr.name, args), {})
            except CodegenError:
                return {}
        return self.structs.get(expr.name, {})

    def _is_vecmap_consumed_by_call(self, expr, var_name):
        """True si `expr` (destapando un `?`) es una llamada directa a una fn/task
        que recibe `var_name` como argumento Vec/Map: la fn ya lo libera al
        cerrar su scope, así que quien llama no tiene que liberar nada
        (liberarlo sería double free). Solo el patrón exacto: un falso negativo
        deja una pérdida, un falso positivo la reabriría."""
        while isinstance(expr, TryExpr):
            expr = expr.expr
        if not isinstance(expr, Call) or not isinstance(expr.callee, Ident):
            return False
        sig = self.fn_sigs.get(expr.callee.name) or self.task_sigs.get(expr.callee.name)
        if sig is None:
            return False
        param_types, _ret = sig
        for arg, pty in zip(expr.args, param_types):
            if isinstance(arg, Ident) and arg.name == var_name and pty.name in (VEC_MARK, MAP_MARK):
                return True
        return False

    def _while_let_slot_diferido(self, stmt, val_ty, env, out, pad):
        """`while let Some(e) = o { o = None ... e ... }`: e es una vista del
        contenido de o (o sigue siendo la dueña). Si el cuerpo reasigna o,
        liberar el valor viejo deja a e colgando (el intérprete la mantiene viva
        hasta el final de la vuelta). El valor viejo va a un slot diferido,
        dueño en el scope de afuera del loop (así lo liberan un return y un
        panic), que se libera al empezar la vuelta siguiente y al salir. None
        si no hace falta."""
        if not isinstance(stmt.expr, Ident):
            return None
        src = stmt.expr.name
        if not (self._is_ownable_type(val_ty) and self._is_owner(src)):
            return None
        if not self._asigna_a(stmt.body, src):
            return None
        origin = self._owner_origin(src)
        nombre = self._new_tmp()
        c_name = self.c_type(val_ty)
        out.append(f"{pad}{c_name} {nombre} = {c_name}_None();  // slot diferido de '{src}'")
        env[nombre] = val_ty
        self._mark_owner(nombre, origin)
        self._vivos_sync(env, out, pad)
        d = {"nombre": nombre, "origen": origin, "src": src, "prev": self._wl_diferido}
        self._wl_diferido = dict(self._wl_diferido)
        self._wl_diferido[src] = d
        return d

    def _liberar_slot_diferido(self, d, env, out, pad):
        nombre = d["nombre"]
        self._emit_owner_frees({nombre: d["origen"]}, env, out, pad)
        out.append(f"{pad}{nombre}.tag = 0;")

    @staticmethod
    def _asigna_a(nodo, nombre):
        """True si en `nodo` (recorrido completo) hay un `nombre = ...`."""
        if isinstance(nodo, AssignStmt) and isinstance(nodo.target, Ident) and nodo.target.name == nombre:
            return True
        return any(Propiedad._asigna_a(h, nombre) for h in hijos(nodo))

    def _emit_take(self, src, out, pad):
        """El contenido de la dueña `src` se movió (spawn, return). Si src tiene
        slot diferido y ya se reasignó en esta vuelta, el contenido que ve la
        ligada está en el slot."""
        d = self._wl_diferido.get(src)
        if src in self._take_result:
            # un Result<Struct> se libera sin mirar el tag (el .value de un Err es
            # NULL): además del tag, el .value queda en NULL
            out.append(f"{pad}{src}.value = NULL;")
        if d is None:
            out.append(f"{pad}{src}.tag = 0;  // el contenido se movió")
        else:
            n = d["nombre"]
            out.append(f"{pad}if ({n}.tag == 1) {n}.tag = 0; else {src}.tag = 0;  // el contenido se movió")

    def _emit_owner_frees(self, names, env, out, pad):
        """Libera cada dueña de `names` ({nombre: origen}) según su tipo (de
        `env`), en orden alfabético (son reservas independientes):
          - struct: {Name}_free, que libera los campos con dueño y decide por el
            encabezado si el bloque es de malloc o de la arena;
          - Vec/Map: scar_vec_free_<T> / scar_map_free_<K>_<V>;
          - str: scar_free;
          - Result: su .err (siempre propio, NULL en un Ok) y, si es dueño, su
            .value;
          - Option: {c_name}_free (libera el contenido si tag == 1);
          - Chan: decref;
          - anidado: entero, recursivamente.
        Un origen "cond:<flag>" envuelve el free en `if (flag)`."""
        for name in sorted(names):
            ty = env.get(name)
            if ty is None:
                continue
            origen_c = names[name]
            if origen_c == "anidado" or (self._es_anidado(ty) and not origen_c.startswith("cond:")):
                # dueña de todo lo de adentro (_es_anidado): un valor anidado es siempre
                # entero propio, así que también un temporal fresco que llega con "plain"
                # se suelta entero
                out.extend(self._lineas_liberar_dueno(ty, name, pad))
                continue
            if (origen_c.startswith("cond:")
                    and not (ty.name in self.structs or ty.name in (VEC_MARK, MAP_MARK, "str"))):
                # una variable de afuera de un loop que un `break` pudo dejar movida es
                # dueña solo si su flag lo dice: para los tipos que no liberan con flag
                # solos, su liberación normal va dentro de un if
                flag = origen_c[len("cond:"):]
                base = getattr(self, "_cond_base", {}).get(flag, "plain")
                internas = []
                self._emit_owner_frees({name: base}, env, internas, pad + "    ")
                if internas:
                    out.append(f"{pad}if ({flag}) {{")
                    out.extend(internas)
                    out.append(f"{pad}}}")
                continue
            if ty.name in self.structs:
                origin = names[name]
                if origin.startswith("cond:"):
                    # struct con flag (de loop o de parámetro consumido): solo el flag sabe
                    # en runtime si la variable ya tiene un valor propio
                    flag = origin[len("cond:"):]
                    out.append(f"{pad}if ({flag}) {{ {ty.name}_free({name}); }}")
                else:
                    # un único caso: {T}_free decide por el encabezado
                    out.append(f"{pad}{ty.name}_free({name});")
            elif ty.name in self.generic_structs:
                # struct genérico: 'ty.name' es el nombre crudo; se usa su instancia (ya
                # calculada por el pre-pase)
                origin = names[name]
                if origin.startswith("cond:"):
                    continue
                mangled = self._ensure_generic_struct_instance(ty.name, ty.args)
                out.append(f"{pad}{mangled}_free({name});")
            elif ty.name == VEC_MARK:
                inner = ty.args[0] if ty.args else T_I32
                origin = names[name]
                if origin.startswith("cond:"):
                    # Vec/Map con flag de loop: si el loop no corrió, la variable sigue con
                    # el valor original, que no es suyo
                    flag = origin[len("cond:"):]
                    out.append(f"{pad}if ({flag}) {{ scar_vec_free_{self._mangled_name(inner)}({name}); }}")
                else:
                    out.append(f"{pad}scar_vec_free_{self._mangled_name(inner)}({name});")
            elif ty.name == MAP_MARK:
                key_ty = ty.args[0] if ty.args else T_I32
                val_ty = ty.args[1] if len(ty.args) > 1 else T_I32
                origin = names[name]
                if origin.startswith("cond:"):
                    flag = origin[len("cond:"):]
                    out.append(f"{pad}if ({flag}) {{ scar_map_free_{key_ty.name}_{self._mangled_name(val_ty)}({name}); }}")
                else:
                    out.append(f"{pad}scar_map_free_{key_ty.name}_{self._mangled_name(val_ty)}({name});")
            elif ty.name == "str":
                origin = names[name]
                if origin.startswith("cond:"):
                    # parámetro str de task: dueño solo si este spawn se lo pasó siéndolo
                    # (el flag oculto)
                    flag = origin[len("cond:"):]
                    out.append(f"{pad}if ({flag}) {{ scar_free((char*){name}); }}")
                else:
                    out.append(f"{pad}scar_free((char*){name});")
            elif ty.name == "Result":
                # Result: el .err es siempre un str propio (NULL en un Ok): se libera
                # sin mirar el tag
                out.append(f"{pad}scar_free((char*){name}.err);")
                origin = names[name]
                if origin.startswith("result_str:"):
                    # el .value de un Result<str> cuyo Ok es propio (contrato único de str):
                    # NULL en un Err, así que también sin mirar el tag
                    out.append(f"{pad}scar_free((char*){name}.value);")
                elif ty.args and ty.args[0].name in self.structs:
                    # el .value de un Result<Struct>: {Struct}_free, con o sin tasks (el
                    # encabezado decide)
                    out.append(f"{pad}{ty.args[0].name}_free({name}.value);")
                elif ty.args and ty.args[0].name in (VEC_MARK, MAP_MARK):
                    # Result<Vec<T>>/Result<Map<K,V>>: el contenido es siempre malloc; en un
                    # Err es {0}/NULL
                    inner = ty.args[0]
                    if inner.name == VEC_MARK:
                        elem = inner.args[0] if inner.args else T_I32
                        out.append(f"{pad}if ({name}.tag == 1) scar_vec_free_{self._mangled_name(elem)}({name}.value);")
                    else:
                        k_ty = inner.args[0] if inner.args else T_I32
                        v_ty = inner.args[1] if len(inner.args) > 1 else T_I32
                        out.append(f"{pad}if ({name}.tag == 1) scar_map_free_{k_ty.name}_{self._mangled_name(v_ty)}({name}.value);")
            elif ty.name == "Option":
                # Option con dueño: {c_name}_free (ver _generic_c_type), que libera el
                # contenido si tag == 1
                c_name = self._generic_c_type(ty)
                # el contenido de recv()/get()/pop() ya no necesita un origen aparte:
                # {c_name}_free lo libera y el encabezado decide el bloque
                out.append(f"{pad}{c_name}_free({name});")
            elif ty.name == CHAN_MARK:
                # Chan: siempre decref. El origen "chan" garantiza que esta variable
                # tiene una referencia contada (creada en su `let`, o el parámetro de una
                # task, contado en el spawn).
                inner = ty.args[0] if ty.args else T_I32
                out.append(f"{pad}scar_chan_decref_{self._mangled_name(inner)}({name});")

    def _alias_return_guards(self, expr, env) -> dict:
        """{raíz: variable} para cada variable que este `return` devuelve (tal
        cual, en Ok/Some o como campo de un struct literal) y que es alias de
        otra dueña comparable por identidad (_same_object_cond). Esas raíces
        se liberan solo si en runtime no son el objeto devuelto."""
        if isinstance(expr, Ident):
            root = self._resolve_alias_root(expr.name)
            ty = env.get(root)
            if root != expr.name and ty is not None and \
                    self._same_object_cond(ty, root, expr.name) is not None:
                return {root: expr.name}
            return {}
        if isinstance(expr, (OkExpr, SomeExpr)):
            return self._alias_return_guards(expr.expr, env)
        if isinstance(expr, StructLit):
            out = {}
            for f_expr in expr.fields.values():
                out.update(self._alias_return_guards(f_expr, env))
            return out
        return {}

    def _emit_alias_return_guards(self, guarded, alias_guards, env, out, pad):
        for root, origin in guarded.items():
            same = self._same_object_cond(env[root], root, alias_guards[root])
            out.append(f"{pad}if (!({same})) {{")
            self._emit_owner_frees({root: origin}, env, out, pad + "    ")
            out.append(f"{pad}}}")

    def _same_object_cond(self, ty, a, b):
        """Condición de C verdadera si `a` y `b` (del tipo ownable `ty`) son el
        mismo objeto. Vec es por valor (se compara .data); struct y Map son
        punteros. Para otros tipos devuelve None: decide el llamador."""
        if ty.name == VEC_MARK:
            return f"(void*){a}.data == (void*){b}.data"
        if ty.name in self.structs or ty.name == MAP_MARK:
            return f"(void*){a} == (void*){b}"
        return None

    def _handoff_shadowed_owner(self, name, shadow_tmp):
        """La dueña sombreada `name` (si lo sigue siendo en un frame de afuera)
        pasa a registrarse como `shadow_tmp`, que guarda el mismo valor. Lo
        mismo los alias que apuntaban a ella (_alias_root), que si no
        apuntarían a la variable nueva."""
        for idx in range(len(self.owner_stack) - 2, -1, -1):
            frame = self.owner_stack[idx]
            if name in frame:
                frame[shadow_tmp] = frame.pop(name)
                self._decl_frame[shadow_tmp] = idx
                break
        for alias, root in list(self._alias_root.items()):
            if root == name and alias != name:
                self._alias_root[alias] = shadow_tmp
