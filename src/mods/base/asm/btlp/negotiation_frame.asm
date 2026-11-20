;; BtlSeqReset sets the origin for the wide three-line battle dialogue frame.
;; Use the normal dialogue inset for every line drawn in that frame, including
;; farewell lines that play after CONTACT has popped its final scene.
.org 0x8007D008
    ori     v0, zero, 0x26             ; retail x=0x20, plus six pixels
