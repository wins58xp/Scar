// Una sola espera hasta el instante final, en la condvar
// propia de la task (registrada en wait_mu/wait_cond como un recv()),
// asi scar_cancel_notify() la corta en cuanto la cancelan. Antes dormia
// en pasos de 100 ms (10 despertares por segundo por task dormida) solo
// para poder ver la cancelacion. main no tiene ctx: nadie la cancela.
static void scar_sleep(double seconds) {
    scar_avance();  // dormir es avanzar: termina solo
    scar_cancel_check();
    if (!(seconds > 0)) return;
    struct timespec hasta = scar_abs_mono(seconds);
    TaskContext *ctx = __scar_ctx;
    atomic_fetch_add(&scar_durmiendo, 1);
    if (!ctx) {
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &hasta, NULL) == EINTR) {}
    } else {
        pthread_mutex_lock(&ctx->sleep_mu);
        pthread_mutex_lock(&ctx->wait_lock);
        ctx->wait_mu = &ctx->sleep_mu;
        ctx->wait_cond = &ctx->sleep_cond;
        pthread_mutex_unlock(&ctx->wait_lock);
        while (!atomic_load(&ctx->cancelled)) {
            if (scar_cond_timedwait(&ctx->sleep_cond, &ctx->sleep_mu, &hasta) == ETIMEDOUT) break;
        }
        pthread_mutex_lock(&ctx->wait_lock);
        ctx->wait_mu = NULL;
        ctx->wait_cond = NULL;
        pthread_mutex_unlock(&ctx->wait_lock);
        pthread_mutex_unlock(&ctx->sleep_mu);
    }
    atomic_fetch_sub(&scar_durmiendo, 1);
    scar_avance();
    scar_cancel_check();
}
