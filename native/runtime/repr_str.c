static char* scar_repr_str(const char* s) {
    /* Un str adentro de otro valor (Vec, Map, Some/Ok/Err, struct), como se
       escribe en SCAR: siempre entre comillas dobles, con las cinco secuencias
       de escape del lexer (\\, \", \n, \t, \r). Igual que scar_repr_str del
       intérprete. */
    size_t len = strlen(s);
    char* buf = scar_malloc(len * 2 + 3);
    size_t j = 0;
    buf[j++] = '"';
    for (size_t i = 0; i < len; i++) {
        char c = s[i];
        if (c == '"' || c == '\\') { buf[j++] = '\\'; buf[j++] = c; continue; }
        if (c == '\n') { buf[j++] = '\\'; buf[j++] = 'n'; continue; }
        if (c == '\t') { buf[j++] = '\\'; buf[j++] = 't'; continue; }
        if (c == '\r') { buf[j++] = '\\'; buf[j++] = 'r'; continue; }
        buf[j++] = c;
    }
    buf[j++] = '"';
    buf[j] = '\0';
    return buf;
}
