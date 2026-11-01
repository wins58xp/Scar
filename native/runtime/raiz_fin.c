@@PAD@@scar_cancel_children(&__scar_root);
@@PAD@@pthread_mutex_destroy(&__scar_root.children_mu);
@@PAD@@pthread_mutex_destroy(&__scar_root.wait_lock);
@@PAD@@free(__scar_root.children);
@@PAD@@free(__scar_root.panic_msg);
@@PAD@@scar_arena_free(&__scar_root.arena);

