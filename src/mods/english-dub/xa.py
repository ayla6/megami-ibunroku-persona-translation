"""CD-XA ADPCM: encode 4-bit stereo/mono sound groups for Form 2 audio sectors.

A Form 2 audio sector carries 18 sound groups of 128 bytes (then 20 zero
bytes). A 4-bit group is 16 header bytes - the parameter byte of each of its
8 sound units, laid out [0 1 2 3 0 1 2 3 4 5 6 7 4 5 6 7] - and 112 data
bytes: 28 words, word i holding sample i of every unit, unit 2j in the low
nibble of byte j and unit 2j+1 in the high one. In stereo the even units are
left and the odd units right. A parameter byte is filter << 4 | range; a
sample decodes as

    s = (nibble << 12 as int16) >> range  +  (s1*K0 + s2*K1 + 32) >> 6

with (K0, K1) = (0, 0), (60, 0), (115, -52), (98, -55), clamped to int16,
and the history runs on across units, groups and sectors per channel.

The encoder picks each unit's filter and range open loop (the smallest range
that holds the prediction residual of the source), then quantises closed
loop against the decoder's own history, so the error never accumulates.
"""
import numpy as np

FILTERS = ((0, 0), (60, 0), (115, -52), (98, -55))
UNIT = 28
GROUP_UNITS = 8
SECTOR_GROUPS = 18
GROUP_BYTES = 128
SECTOR_DATA = 2324           # Form 2 user data
HEADER_ORDER = (0, 1, 2, 3, 0, 1, 2, 3, 4, 5, 6, 7, 4, 5, 6, 7)


def samples_per_sector(channels):
    """Samples per channel one audio sector holds."""
    return SECTOR_GROUPS * GROUP_UNITS * UNIT // channels


def _choose(units):
    """(filter, range) per unit of a (n, 28) float block, open loop."""
    x = units.astype(np.float64)
    prev1 = np.concatenate(([0.0], x[:-1, -1]))
    prev2 = np.concatenate(([0.0], x[:-1, -2]))
    s1 = np.concatenate((prev1[:, None], x[:, :-1]), axis=1)
    s2 = np.concatenate((prev2[:, None], s1[:, :-1]), axis=1)
    peaks = np.stack([np.abs(x - (s1 * k0 + s2 * k1) / 64).max(axis=1)
                      for k0, k1 in FILTERS], axis=1)
    filt = peaks.argmin(axis=1)
    peak = peaks[np.arange(len(x)), filt]
    # nibble range is -8..7 at a step of 2**(12 - range): 7 * step >= peak
    need = np.ceil(np.log2(np.maximum(peak, 1) / 7))
    rng = np.clip(12 - need, 0, 12).astype(np.int64)
    return filt, rng


def encode_channel(pcm):
    """int16 samples (length a multiple of 28) -> (params, nibbles) per unit."""
    units = pcm.reshape(-1, UNIT)
    filt, rng = _choose(units)
    nibbles = np.zeros(units.shape, dtype=np.uint8)
    s1 = s2 = 0
    for u in range(len(units)):
        k0, k1 = FILTERS[filt[u]]
        r = int(rng[u])
        step = 1 << (12 - r)
        row = units[u].tolist()
        out = nibbles[u]
        for i in range(UNIT):
            pred = (s1 * k0 + s2 * k1 + 32) >> 6
            q = int(round((row[i] - pred) / step))
            q = -8 if q < -8 else 7 if q > 7 else q
            v = ((q << 12) if q >= 0 else ((q << 12) & 0xFFFF) - 0x10000) >> r
            v += pred
            v = -32768 if v < -32768 else 32767 if v > 32767 else v
            out[i] = q & 0xF
            s2, s1 = s1, v
    return (filt << 4 | rng).astype(np.uint8), nibbles


def encode_sectors(pcm, channels):
    """int16 (n, channels) -> list of 2324-byte Form 2 sector payloads.

    The input length must fill the sectors exactly."""
    per = samples_per_sector(channels)
    if len(pcm) % per:
        raise ValueError(f'{len(pcm)} samples do not fill whole sectors of {per}')
    coded = [encode_channel(np.ascontiguousarray(pcm[:, c])) for c in range(channels)]
    n_units = len(pcm) // UNIT
    params = np.zeros((n_units * channels,), dtype=np.uint8)
    nibs = np.zeros((n_units * channels, UNIT), dtype=np.uint8)
    for c, (p, n) in enumerate(coded):
        params[c::channels] = p
        nibs[c::channels] = n
    groups = len(params) // GROUP_UNITS
    params = params.reshape(groups, GROUP_UNITS)
    nibs = nibs.reshape(groups, GROUP_UNITS, UNIT)
    block = np.zeros((groups, GROUP_BYTES), dtype=np.uint8)
    block[:, :16] = params[:, list(HEADER_ORDER)]
    data = nibs[:, 0::2, :] | (nibs[:, 1::2, :] << 4)          # (groups, 4, 28)
    block[:, 16:] = data.transpose(0, 2, 1).reshape(groups, 112)
    block = block.reshape(-1, SECTOR_GROUPS * GROUP_BYTES)
    pad = bytes(SECTOR_DATA - SECTOR_GROUPS * GROUP_BYTES)
    return [bytes(b) + pad for b in block]
