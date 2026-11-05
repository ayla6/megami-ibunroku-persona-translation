;; =============================================================
;; S2D.BIN - rev1 bugfix port: label search must not init the banner
;; =============================================================
;; rev0's area-label search (0x80089FB4) calls banner-init with a hardcoded
;; "empty" entry on two paths: key NULL (0x8008A014 -> 0x8008A048) and slot
;; holds -1 (0x8008A030 falls into 0x8008A038). That "empty" entry is really
;; the Yin&Yan entry (+2), so loading a save inside the tree banners
;; Yin + Yan (translated) / ＹＩＮ＆ＹＡＮ (rev0 retail) - a genuine rev0
;; retail bug. rev1's search (0x80089B30) returns without init on both
;; paths, so the load shows nothing until the first area transition.
;; Ported here as the same two words:
.org 0x8008A014
    beqz    a0, 0x8008A058
.org 0x8008A038
    j       0x8008A058
