;; DNG.BIN - the controller page names the swapped buttons. With
;; run-in-dungeons on, run owns the cancel entry.
.ifdef MOD_RUN_IN_DUNGEONS
western_layout DNG_PAD_LAYOUTS, 1
.else
western_layout DNG_PAD_LAYOUTS, 0
.endif
