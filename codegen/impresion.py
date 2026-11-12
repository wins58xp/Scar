"""Mixin Impresion de Codegen (paso C6): print(). El formato de cada valor
(enteros, f64, str con repr, structs, enums, Vec, Map, Option/Result) y los
helpers de C que lo escriben.
"""

from parser import Ident, Call, PrintExpr, FieldAccess, OkExpr, SomeExpr, MethodCall, TryExpr, marca_new_generico
from types_ import TypeAnn, T_I32
import lugares
import nombres_c

from .comun import (
    CHAN_MARK, CodegenError, FILE_MARK, FN_MARK, GENERIC_NAMES, LISTENER_MARK,
    MAP_MARK, PIPE_MARK, SOCKET_MARK, TASK_MARK, VEC_MARK,
)


class Impresion:
    # ---- formato de print(), igual que scar_str() del intérprete ----
    def print_fmt(self, ty: TypeAnn):
        if ty.name == "i32":
            return "%d"
        if ty.name == "i64":
            return "%lld"  # el argumento va como (long long), ver print_arg
        if ty.name == "f64":
            return "%s"  # ver scar_fmt_f64: %g de C no agrega ".0" como Python
        if ty.name == "str":
            return "%s"
        if ty.name == "bool":
            return "%s"
        if ty.name in ("Result", "Option"):
            return "%s"
        if ty.name in self.structs:
            return "%s"
        if ty.name in (VEC_MARK, MAP_MARK):  # también un Map
            return "%s"
        if ty.name == CHAN_MARK:
            return "%s"  # "<canal>", igual que el intérprete
        if ty.name == PIPE_MARK:
            return "%s"  # "<pipe>", igual que el intérprete
        if ty.name == FN_MARK:
            return "<fn %s>"  # "<fn doble>", igual que el intérprete
        if ty.name == TASK_MARK:
            return "%s"  # "<task cuadrado>", igual que el intérprete
        raise CodegenError(f"print() no soporta el tipo {ty} en el backend de C")

    def _value_fmt(self, ty: TypeAnn, code: str, pre: list, post: list):
        """Formato de printf y expresión de C para un valor dentro de un
        Ok/Some/struct/Vec, como scar_repr() del intérprete: en la forma de SCAR
        (str entre comillas dobles, bool true/false).

        pre/post: líneas de C (sin sangría) para antes y después del snprintf
        que usa el valor. Los formateadores que reservan un texto nuevo
        (scar_fmt_f64, scar_repr_str, scar_fmt_<X>) se guardan en un temporal
        (pre) y se liberan después de usarlos (post), en vez de quedar sueltos
        como argumento del snprintf."""
        if ty.name == "i32":
            return "%d", code
        if ty.name == "i64":
            return "%lld", f"(long long)({code})"
        if ty.name == "f64":
            self.needs_fmt_f64 = True
            tmp = self._new_tmp()
            pre.append(f"char* {tmp} = scar_fmt_f64({code});")
            post.append(f"scar_free({tmp});")
            return "%s", tmp
        if ty.name == "str":
            self.needs_repr_str = True
            tmp = self._new_tmp()
            pre.append(f"char* {tmp} = scar_repr_str({code});")
            post.append(f"scar_free({tmp});")
            return "%s", tmp
        if ty.name == "bool":
            return "%s", f'({code} ? "true" : "false")'
        if ty.name == "void":
            # Result<()>: el valor se imprime "None" (sale Ok(None), como en el
            # intérprete); el bool que lo representa no se muestra
            return "%s", '"None"'
        if ty.name in self.structs:
            c_name = self._ensure_struct_fmt_helper(ty)
            tmp = self._new_tmp()
            pre.append(f"char* {tmp} = scar_fmt_{c_name}({code});")
            post.append(f"scar_free({tmp});")
            return "%s", tmp
        if ty.name == FILE_MARK:
            # un texto fijo, como ScarFile.__repr__ del intérprete (no la dirección):
            # la salida tiene que ser idéntica en los dos backends
            return "%s", '"<file>"'
        if ty.name == SOCKET_MARK:
            # como ScarSocket.__repr__ del intérprete
            return "%s", '"<socket>"'
        if ty.name == LISTENER_MARK:
            return "%s", '"<listener>"'
        if ty.name == CHAN_MARK:
            # un texto fijo, como ScarChan.__repr__ del intérprete (la dirección del
            # canal cambia en cada corrida)
            return "%s", '"<canal>"'
        if ty.name == PIPE_MARK:
            # como ScarPipe.__repr__ del intérprete
            return "%s", '"<pipe>"'
        if ty.name == FN_MARK:
            # "<fn doble>", como el intérprete: el nombre sale de la tabla de las fn
            # usadas como valor (scar_fn_nombre)
            self._imprime_fns = True
            return "<fn %s>", f"scar_fn_nombre((ScarFnCualquiera)({code}))"
        if ty.name == TASK_MARK:
            return "%s", self._texto_task(ty)
        if ty.name in (VEC_MARK, MAP_MARK):
            # un Vec o un Map dentro de un Option/Result/struct/Vec
            c_name = self._ensure_fmt_helper(ty)
            tmp = self._new_tmp()
            pre.append(f"char* {tmp} = scar_fmt_{c_name}({code});")
            post.append(f"scar_free({tmp});")
            return "%s", tmp
        if ty.name in GENERIC_NAMES:
            # un Option/Result dentro de otro: su propio scar_fmt_<c_name>, que se
            # arma recursivamente
            c_name = self._ensure_fmt_helper(ty)
            tmp = self._new_tmp()
            pre.append(f"char* {tmp} = scar_fmt_{c_name}({code});")
            post.append(f"scar_free({tmp});")
            return "%s", tmp
        raise CodegenError(f"formato de {ty!r} dentro de Result/Option no soportado")

    def _ensure_struct_fmt_helper(self, ty: TypeAnn) -> str:
        """Genera una vez scar_fmt_<Name>(Name* v), como StructInstance.__repr__
        del intérprete: 'Name(campo=repr(valor), ...)'."""
        name = ty.name
        if name in self.struct_fmt_registered:
            return name
        self.struct_fmt_registered.add(name)
        if name in self.enums:
            return self._enum_fmt_helper(name)
        fields = self.structs[name]
        field_fmts = []
        field_exprs = []
        pre, post = [], []
        for fname, fty in fields.items():
            fmt, expr = self._value_fmt(fty, f"v->{fname}", pre, post)
            field_fmts.append(f"{self.nombres.mostrar(fname)}={fmt}")
            field_exprs.append(expr)
        fmt_str = ", ".join(field_fmts)
        args = ", ".join(field_exprs)
        snprintf_args = f', {args}' if args else ''
        self.fmt_protos.append(f"static char* scar_fmt_{name}({name}* v);")
        body = [f"static char* scar_fmt_{name}({name}* v) {{"]
        body += [f"    {line}" for line in pre]
        # sin tope de largo
        body.append(f'    char* buf = scar_aprintf("{self.nombres.mostrar(name)}({fmt_str})"{snprintf_args});')
        body += [f"    {line}" for line in post]
        body.append("    return buf;")
        body.append("}")
        self.fmt_defs.append("\n".join(body))
        return name

    def _enum_fmt_helper(self, name):
        """scar_fmt_<Name> de un enum: `Variante` o `Variante(d1, d2)` según el
        tag, cada dato con repr(), como el intérprete."""
        fields = self.structs[name]
        tag = nombres_c.nombre_c(nombres_c.CAMPO, "tag")
        self.fmt_protos.append(f"static char* scar_fmt_{name}({name}* v);")
        body = [f"static char* scar_fmt_{name}({name}* v) {{", "    char* buf;"]
        for idx, (var, n) in enumerate(self.enums[name]):
            kw = "if" if idx == 0 else "} else if"
            body.append(f"    {kw} (v->{tag} == {idx}) {{")
            if n == 0:
                body.append(f'        buf = scar_aprintf("{var}");')
                continue
            pre, post, fmts, exprs = [], [], [], []
            for j in range(n):
                campo = nombres_c.nombre_c(nombres_c.CAMPO, f"{var}_{j}")
                fmt, expr = self._value_fmt(fields[campo], f"v->{campo}", pre, post)
                fmts.append(fmt)
                exprs.append(expr)
            body += [f"        {line}" for line in pre]
            body.append(f'        buf = scar_aprintf("{var}({", ".join(fmts)})", {", ".join(exprs)});')
            body += [f"        {line}" for line in post]
        body += ["    } else {", '        buf = scar_aprintf("?");', "    }", "    return buf;", "}"]
        self.fmt_defs.append("\n".join(body))
        return name

    def _ensure_fmt_helper(self, ty: TypeAnn) -> str:
        c_name = self.c_type(ty)
        if c_name in self.fmt_registered:
            return c_name
        self.fmt_registered.add(c_name)
        self.fmt_protos.append(f"static char* scar_fmt_{c_name}({c_name} v);")
        if ty.name == VEC_MARK:
            return self._vec_fmt_helper(ty, c_name)
        if ty.name == MAP_MARK:
            return self._map_fmt_helper(ty, c_name)
        inner = ty.args[0] if ty.args else T_I32
        pre, post = [], []
        ok_fmt, ok_expr = self._value_fmt(inner, "v.value", pre, post)
        pre_lines = [f"        {line}" for line in pre]
        post_lines = [f"        {line}" for line in post]
        if ty.name == "Result":
            self.needs_repr_str = True
            body = [
                f"static char* scar_fmt_{c_name}({c_name} v) {{",
                "    char* buf;",
                "    if (v.tag == 1) {",
            ]
            body += pre_lines
            body.append(f'        buf = scar_aprintf("Ok({ok_fmt})", {ok_expr});')
            body += post_lines
            body += [
                "    } else {",
                "        char* __scar_err_repr = scar_repr_str(v.err);",
                '        buf = scar_aprintf("Err(%s)", __scar_err_repr);',
                "        scar_free(__scar_err_repr);",
                "    }",
                "    return buf;",
                "}",
            ]
            self.fmt_defs.append("\n".join(body))
        else:  # Option
            body = [
                f"static char* scar_fmt_{c_name}({c_name} v) {{",
                "    char* buf;",
                "    if (v.tag == 1) {",
            ]
            body += pre_lines
            body.append(f'        buf = scar_aprintf("Some({ok_fmt})", {ok_expr});')
            body += post_lines
            body += [
                "    } else {",
                '        buf = scar_aprintf("None");',
                "    }",
                "    return buf;",
                "}",
            ]
            self.fmt_defs.append("\n".join(body))
        return c_name

    def _map_fmt_helper(self, ty: TypeAnn, c_name: str) -> str:
        """scar_fmt_Map_<K>_<V>, como ScarMap.__repr__ del intérprete (un dict de
        Python): `{k1: v1, k2: v2}` en orden de inserción. Cada entrada guarda
        cuándo entró su clave (`orden`): actualizar una clave no la mueve, y
        sacarla y volver a ponerla la deja al final, como en un dict."""
        entry, suffix, key_ty, val_ty = self.map_nombres[c_name]
        if val_ty.name not in ("i32", "i64", "f64", "str", "bool", CHAN_MARK, VEC_MARK, MAP_MARK, "Option", "Result",
                               PIPE_MARK, FN_MARK, TASK_MARK) and val_ty.name not in self.structs:
            raise CodegenError(f"print() todavía no soporta {ty!r} en el backend de C")
        pre, post = [], []
        kfmt, kexpr = self._value_fmt(key_ty, "__scar_e->key", pre, post)
        vfmt, vexpr = self._value_fmt(val_ty, "__scar_e->value", pre, post)
        body = [
            f"static int scar_map_cmp_{suffix}(const void* a, const void* b) {{",
            f"    int64_t x = (*(const {entry}* const*)a)->orden;",
            f"    int64_t y = (*(const {entry}* const*)b)->orden;",
            "    return (x > y) - (x < y);",
            "}",
            f"static char* scar_fmt_{c_name}({c_name} m) {{",
            "    ScarSb sb = {0};",
            '    scar_sb_add(&sb, "{");',
            f"    const {entry}** __scar_orden = malloc(sizeof(*__scar_orden) * (size_t)(m->count > 0 ? m->count : 1));",
            "    int32_t __scar_n = 0;",
            "    for (int32_t __scar_i = 0; __scar_i < m->cap; __scar_i++) {",
            "        if (m->entries[__scar_i].state == 1) __scar_orden[__scar_n++] = &m->entries[__scar_i];",
            "    }",
            f"    qsort(__scar_orden, (size_t)__scar_n, sizeof(*__scar_orden), scar_map_cmp_{suffix});",
            "    for (int32_t __scar_i = 0; __scar_i < __scar_n; __scar_i++) {",
            f"        const {entry}* __scar_e = __scar_orden[__scar_i];",
            '        if (__scar_i > 0) scar_sb_add(&sb, ", ");',
        ]
        body += [f"        {line}" for line in pre]
        body.append(f'        char* __scar_t = scar_aprintf("{kfmt}: {vfmt}", {kexpr}, {vexpr});')
        body += [f"        {line}" for line in post]
        body += [
            "        scar_sb_add(&sb, __scar_t);",
            "        scar_free(__scar_t);",
            "    }",
            "    free(__scar_orden);",
            '    scar_sb_add(&sb, "}");',
            "    return scar_sb_fin(&sb);",
            "}",
        ]
        self.fmt_defs.append("\n".join(body))
        return c_name

    def _vec_fmt_helper(self, ty: TypeAnn, c_name: str) -> str:
        """scar_fmt_Vec_<T>, como ScarVec.__repr__ del intérprete: `[e1, e2]`, cada
        elemento con _value_fmt. Arma el texto en un ScarSb, que crece (un Vec no
        tiene largo máximo). Los structs están por valor en data[] y su
        formateador recibe un puntero."""
        inner = ty.args[0] if ty.args else T_I32
        # también Vec<Vec<T>> (_value_fmt formatea el de adentro)
        if inner.name not in ("i32", "i64", "f64", "str", "bool", CHAN_MARK, VEC_MARK, "Option", "Result", MAP_MARK,
                              PIPE_MARK, FN_MARK, TASK_MARK) and inner.name not in self.structs:
            raise CodegenError(f"print() todavía no soporta {ty!r} en el backend de C")
        elem = "&v.data[__scar_i]" if inner.name in self.structs else "v.data[__scar_i]"
        pre, post = [], []
        fmt, expr = self._value_fmt(inner, elem, pre, post)
        body = [
            f"static char* scar_fmt_{c_name}({c_name} v) {{",
            "    ScarSb sb = {0};",
            '    scar_sb_add(&sb, "[");',
            "    for (int32_t __scar_i = 0; __scar_i < v.len; __scar_i++) {",
            '        if (__scar_i > 0) scar_sb_add(&sb, ", ");',
        ]
        body += [f"        {line}" for line in pre]
        body.append(f'        char* __scar_e = scar_aprintf("{fmt}", {expr});')
        body += [f"        {line}" for line in post]
        body += [
            "        scar_sb_add(&sb, __scar_e);",
            "        scar_free(__scar_e);",
            "    }",
            '    scar_sb_add(&sb, "]");',
            "    return scar_sb_fin(&sb);",
            "}",
        ]
        self.fmt_defs.append("\n".join(body))
        return c_name

    def print_arg(self, expr, ty: TypeAnn, env, out, pad):
        """Devuelve (código C para el argumento del printf, nombre del
        temporal a liberar o None). f64/Result/Option/struct pasan por
        scar_fmt_* (ver _value_fmt/_ensure_*_fmt_helper), que siempre
        malloc(256) un buffer nuevo -- ese buffer se asigna a un temporal
        acá para que gen_print pueda hacerle free() después del printf
        (si no, print() perdería ese buffer)."""
        code = self.gen_expr(expr, env, out, pad)
        if ty.name == "i64":
            return f"(long long)({code})", None
        if ty.name == "bool":
            return f'({code} ? "true" : "false")', None
        if ty.name == "f64":
            self.needs_fmt_f64 = True
            return self._malloc_fmt_tmp(f"scar_fmt_f64({code})", out, pad)
        if ty.name == "Option":
            owned_kind = self._option_fresh_owned_kind(expr, env)
            if owned_kind is not None:
                # Ver _option_fresh_owned_kind: v.get()/.pop()/.remove()
                # entrega un Option<T> fresco, sin alias en ningún otro
                # lado -- captura el Option ENTERO en un temporal (antes
                # de formatearlo) para poder liberar el valor que envuelve
                # una vez que scar_fmt_Option_* ya terminó de leerlo. No
                # se puede liberar dentro del propio scar_fmt_Option_*
                # generado (_ensure_fmt_helper): esa función
                # también se usa para imprimir un Option<T> que sigue
                # siendo una variable dueña normal, y liberar el valor ahí
                # sería un double-free contra el free() que le toca a esa
                # variable al cerrar su scope -- por eso el free acá va
                # condicionado al sitio de uso puntual (mismo criterio que
                # ya aplica _capture_fresh_str_concat_arg para 'str').
                c_ty = self.c_type(ty)
                val_tmp = self._new_tmp()
                out.append(f"{pad}{c_ty} {val_tmp} = {code};")
                c_name = self._ensure_fmt_helper(ty)
                fmt_tmp, _ = self._malloc_fmt_tmp(f"scar_fmt_{c_name}({val_tmp})", out, pad)
                if owned_kind == "str":
                    out.append(f"{pad}if ({val_tmp}.tag == 1) scar_free((char*){val_tmp}.value);")
                elif owned_kind in (VEC_MARK, MAP_MARK, "Option", "Result"):
                    # (también un Option/Result guardado en un Vec/Map)
                    # Vec<Vec<T>>: el Vec de adentro, propio, se suelta entero
                    out.extend(self._lineas_liberar_dueno(ty, val_tmp, pad))
                else:
                    out.append(f"{pad}if ({val_tmp}.tag == 1) {owned_kind}_free({val_tmp}.value);")
                return fmt_tmp, fmt_tmp
        if ty.name in ("Result", "Option"):
            c_name = self._ensure_fmt_helper(ty)
            return self._malloc_fmt_tmp(f"scar_fmt_{c_name}({code})", out, pad)
        if ty.name in self.structs:
            # `print(P { .. })` o `print(mk())`: el struct fresco se
            # libera al terminar la sentencia (antes se perdía, con lo que
            # tuviera adentro).
            code = self._capture_fresh_owned_arg(expr, code, env, out, pad)
            c_name = self._ensure_struct_fmt_helper(ty)
            return self._malloc_fmt_tmp(f"scar_fmt_{c_name}({code})", out, pad)
        if ty.name in (VEC_MARK, MAP_MARK):  # también un Map
            code = self._capture_fresh_owned_arg(expr, code, env, out, pad)
            c_name = self._ensure_fmt_helper(ty)
            return self._malloc_fmt_tmp(f"scar_fmt_{c_name}({code})", out, pad)
        if ty.name == PIPE_MARK:
            return '"<pipe>"', None
        if ty.name == TASK_MARK:
            return self._texto_task(ty), None
        if ty.name == FN_MARK:
            self._imprime_fns = True
            return f"scar_fn_nombre((ScarFnCualquiera)({code}))", None
        if ty.name == CHAN_MARK:
            # El canal no se lee, solo se muestra un placeholder
            # fijo. Si es fresco (`print(chan_new())`) se captura para que se
            # suelte al terminar la sentencia, igual que un Vec fresco.
            if self._can_capture_arg_temps and self._let_creates_fresh_owner(
                    expr, marca_new_generico(expr), env):
                drop = self._vivo_drop_fn(ty, "plain")
                if drop is not None:
                    tmp = self._new_tmp()
                    out.append(f"{pad}{self.c_type(ty)} {tmp} = {code};")
                    self.pending_expr_temps.append(f"dropfree:{drop}:{tmp}")
                    return '"<canal>"', None
            if not self._RE_C_IDENT.fullmatch(code):
                out.append(f"{pad}(void)({code});")  # que la expresión se evalúe
            return '"<canal>"', None
        if ty.name == "str" and (self._is_fresh_str_concat_expr(expr, env) or self._is_fresh_str_call(expr)):
            # print(a + b) o print(f(x)) con un str fresco: va a un temporal que se
            # libera después del printf (como scar_fmt_*). char* y no const char*, para
            # liberarlo sin cast.
            tmp = self._new_tmp()
            out.append(f"{pad}char* {tmp} = (char*){code};")
            return tmp, tmp
        if ty.name == "str":
            # bajo ASan el str impreso se lee con strlen() (que ASan revisa): ver
            # SCAR_SAN_STR en el preámbulo
            return f"SCAR_SAN_STR({code})", None
        return code, None

    def _malloc_fmt_tmp(self, call_code: str, out, pad):
        """Guarda en un temporal char* el resultado de un scar_fmt_*() (siempre un
        texto nuevo) para liberarlo después de usarlo. Devuelve (temporal,
        temporal): el segundo le dice a gen_print que hace falta el free."""
        tmp = self._new_tmp()
        out.append(f"{pad}char* {tmp} = {call_code};")
        return tmp, tmp

    def gen_print(self, expr: PrintExpr, env, out, pad):
        arg_tys = [self.infer(a, env) for a in expr.args]
        fmt = " ".join(self.print_fmt(t) for t in arg_tys) + r"\n"
        arg_codes = []
        tmps_to_free = []
        # Un Result fresco impreso directo (sin let) se captura en un temporal
        # dueño con el origen que le daría un let (_print_fresh_result_origin),
        # se imprime y se libera después del printf.
        owned_tmps = {}
        tmp_env = None
        args_print = list(expr.args)
        formateados = {}  # índice -> (código, temporal) ya formateado en orden
        # un campo seguido de un argumento que llama a una fn del usuario (que
        # lo puede reasignar) se lee antes, en su lugar
        lugares = {i for i, a in enumerate(expr.args)
                   if self._es_lugar(a) and any(self._alcanza_lugar(b, a) for b in expr.args[i + 1:])}
        # Y al revés: una llamada que reasigna un campo que se lee más a la
        # derecha (`print(c.n + sube(c), c.n)`) va antes, a su temporal. En
        # línea, gcc evalúa los argumentos de printf de derecha a izquierda
        llamada_antes = any(self._es_lugar(b) and self._alcanza_lugar(a, b)
                            for i, a in enumerate(expr.args) if not self._expr_simple(a)
                            for b in expr.args[i + 1:])
        # Lo que no es i32/i64/bool/str se formatea a un temporal antes del
        # printf: si a su izquierda hay una llamada, esa llamada va primero,
        # para que el valor formateado vea sus efectos.
        formato_despues = any(
            not self._expr_simple(a) and any(t.name not in ("i32", "i64", "bool", "str")
                                             for t in arg_tys[i + 1:])
            for i, a in enumerate(expr.args))
        if (sum(1 for a in expr.args if not self._expr_simple(a)) >= 2 or lugares or llamada_antes
                or formato_despues):
            # El orden de evaluación de los argumentos de printf no está fijado en
            # C (ver _secuenciar): con dos o más que no son simples, cada uno se
            # evalúa antes, en orden, a un temporal (con dueña si es fresco).
            tmp_env = dict(env)
            for i, (a, t) in enumerate(zip(expr.args, arg_tys)):
                if i in lugares:
                    code = self._fijar_lugar(a, self.gen_expr(a, env, out, pad), env, out, pad, t)
                    tmp_env[code] = t
                    args_print[i] = Ident(code)
                    continue
                if self._expr_simple(a):
                    # `print(w, f(w).x, g())`: una variable se imprime con el valor que
                    # tiene en su lugar. Si un argumento de la derecha se la lleva (un Vec
                    # que f consume), formatearla al final leía memoria liberada: se
                    # formatea ya.
                    if (t.name not in ("i32", "i64", "f64", "bool", "str")
                            and any(not self._expr_simple(b) for b in expr.args[i + 1:])):
                        formateados[i] = self.print_arg(a, t, env, out, pad)
                    continue
                origin = self._print_fresh_result_origin(a, t, env)
                code = self.gen_expr(a, env, out, pad)
                if t.name == "str":
                    code = self._capture_fresh_str_concat_arg(a, code, env, out, pad)
                if self._RE_C_IDENT.fullmatch(code) and code in tmp_env:
                    args_print[i] = Ident(code)
                    continue
                rtmp = self._new_tmp()
                out.append(f"{pad}{self.c_type(t)} {rtmp} = {code};")
                tmp_env[rtmp] = t
                if origin is not None:
                    owned_tmps[rtmp] = origin
                elif (t.name != "str" and self._is_ownable_type(t)
                        and self._let_creates_fresh_owner(a, marca_new_generico(a), env)):
                    drop = self._vivo_drop_fn(t, "plain")
                    if drop is not None:
                        self.pending_expr_temps.append(f"dropfree:{drop}:{rtmp}")
                args_print[i] = Ident(rtmp)
        for i, (a, t) in enumerate(zip(args_print, arg_tys)):
            if i in formateados:
                code, tmp = formateados[i]
                arg_codes.append(code)
                if tmp is not None:
                    tmps_to_free.append(tmp)
                continue
            if tmp_env is not None and isinstance(a, Ident) and a.name in tmp_env and a.name not in env:
                code, tmp = self.print_arg(a, t, tmp_env, out, pad)
                arg_codes.append(code)
                if tmp is not None:
                    tmps_to_free.append(tmp)
                continue
            origin = self._print_fresh_result_origin(a, t, env)
            if origin is not None:
                val_code = self.gen_expr(a, env, out, pad)
                rtmp = self._new_tmp()
                out.append(f"{pad}{self.c_type(t)} {rtmp} = {val_code};")
                if tmp_env is None:
                    tmp_env = dict(env)
                tmp_env[rtmp] = t
                owned_tmps[rtmp] = origin
                code, tmp = self.print_arg(Ident(rtmp), t, tmp_env, out, pad)
            else:
                code, tmp = self.print_arg(a, t, env, out, pad)
            arg_codes.append(code)
            if tmp is not None:
                tmps_to_free.append(tmp)
        args = ", ".join(arg_codes)
        if args:
            if getattr(expr, "a_stderr", False):
                # el error de un main -> Result (ver enum_match.bajar_main_result)
                out.append(f'{pad}fflush(stdout);')
                out.append(f'{pad}fprintf(stderr, "{fmt}", {args});')
            else:
                out.append(f'{pad}printf("{fmt}", {args});')
        else:
            out.append(f'{pad}printf("{fmt}");')
        # Cada scar_fmt_* usado arriba reservó un buffer: se liberan.
        for tmp in tmps_to_free:
            out.append(f"{pad}scar_free({tmp});")
        if owned_tmps:
            self._emit_owner_frees(owned_tmps, tmp_env, out, pad)

    def _print_fresh_result_origin(self, a, t, env):
        """Origen de dueño (el mismo que le daría un let) para un argumento de
        print() que es un valor fresco; None si no aplica."""
        # `print(f()?)`, `print(arch.read_all()?)`: lo que deja el `?` es nuevo
        # si lo sería en `let x = algo?` (el mismo criterio, _is_fresh_try_value)
        if (isinstance(a, TryExpr) and self._is_ownable_type(t)
                and self._is_fresh_try_value(a, env)):
            return "plain"
        # `print(t.join())` con una task `-> str`: el str de la caja es siempre
        # propio (ver _gen_task_support), como en `let s = t.join()`.
        if t.name == "str" and isinstance(a, MethodCall) and a.method == "join":
            return "plain"
        # Lo que sale de cualquier join es de malloc ({T}_moveout en el
        # wrapper de la task): se libera como en `let x = t.join()`.
        if isinstance(a, MethodCall) and a.method == "join" and self._is_ownable_type(t):
            return "plain"
        if self._option_payload_is_malloc(a, t, env):
            # `print(m.get("a"))` imprime una copia: mismo origen que en un let
            return "opt_malloc"
        if (t.name == "Result" and t.args and t.args[0].name == "str" and isinstance(a, FieldAccess)
                and self._campo_de_temporal(a, env) is not None):
            # `print(mk().r)`: el Result sacado del temporal trae su .value propio
            return "result_str:plain"
        if (((t.name == "Option" and isinstance(a, (Call, SomeExpr)))
                 or (t.name == "Result" and isinstance(a, OkExpr)))
                and self._is_ownable_type(t)
                and self._let_creates_fresh_owner(a, marca_new_generico(a), env)):
            # `print(devolver())` o `print(Some("a" + "b"))`: el mismo origen que
            # en `let o = ...`.
            return "plain"
        if (t.name == "Result" and isinstance(a, MethodCall) and self._is_ownable_type(t)
                and self._is_fresh_result_producer(a, env)):
            # `print(f.read_all())`, `print(s.read())`, `print(l.accept())`: el
            # Result de un método de File/Socket/Listener es nuevo
            # (_is_fresh_result_producer).
            return "result_str:plain" if t.args and t.args[0].name == "str" else "plain"
        if t.name != "Result" or not isinstance(a, Call) or not isinstance(a.callee, Ident):
            return None
        if not self._is_ownable_type(t):
            return None
        if not self._let_creates_fresh_owner(a, marca_new_generico(a), env):
            return None
        if t.args and t.args[0].name == "str":
            if a.callee.name in self.result_str_value_origin:
                return f"result_str:{self.result_str_value_origin[a.callee.name]}"
            if a.callee.name in self.extern_sigs:
                return "result_str:plain"
        return "plain"
