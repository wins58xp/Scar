static ScarPipe scar_pipe_new(void) {
    int __scar_fds[2];
    if (pipe(__scar_fds) != 0) {
        fflush(stdout);
        fprintf(stderr, "[PANIC] pipe_new: fallo el syscall pipe()\n");
        exit(1);
    }
    ScarPipe p;
    p.read_fd = __scar_fds[0];
    p.write_fd = __scar_fds[1];
    return p;
}
