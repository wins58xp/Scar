static char* scar_repr_str(const char* s) {
    int has_single = 0, has_double = 0;
    for (const char* p = s; *p; p++) {
        if (*p == '\'') has_single = 1;
        if (*p == '"') has_double = 1;
    }
    char quote = (has_single && !has_double) ? '"' : '\'';
    size_t len = strlen(s);
    char* buf = scar_malloc(len * 2 + 3);
    size_t j = 0;
    buf[j++] = quote;
    for (size_t i = 0; i < len; i++) {
        char c = s[i];
        if (c == quote || c == '\\') { buf[j++] = '\\'; buf[j++] = c; continue; }
        if (c == '\n') { buf[j++] = '\\'; buf[j++] = 'n'; continue; }
        if (c == '\t') { buf[j++] = '\\'; buf[j++] = 't'; continue; }
        if (c == '\r') { buf[j++] = '\\'; buf[j++] = 'r'; continue; }
        buf[j++] = c;
    }
    buf[j++] = quote;
    buf[j] = '\0';
    return buf;
}
