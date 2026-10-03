"""De-shimmer: suppressing "shimmer" — narrow, flickering generation artefacts
in roughly the 4.5–14 kHz range, left behind by Suno and similar models.

An original implementation. The ideas were checked against the public
descriptions of two projects: deshimmer (TheApeMachine) — a median baseline
across frequency, a threshold above it with a soft knee, protection of
broadband events, bypassing transients; Shimmer (henricksmedia) — "clean
first, master second", leave the low end alone entirely, treat the centre of
the mix more gently than the sides. No code from either project was used.

Why Airband needs this: the exciter draws on exactly the band where shimmer
lives. Without cleaning, it would build new harmonics upwards out of the
artefacts.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

N = 2048          # STFT window
HOP = 512         # hop: 75% overlap, a periodic Hann window
W = 12            # half-width of the median across frequency (25 bins ≈ 590 Hz at 48 kHz)
THR = 8.0         # threshold above the baseline, dB
KNEE = 3.0        # soft knee, dB
TARGET = 1.0      # where to bring an outlier down to: the surrounding floor plus 1 dB
MAX_RED = 30.0    # never cut more than this
DENS_LO, DENS_HI = 0.05, 0.25    # share of outliers in a frame: above this it's music, leave it alone
FL_LO, FL_HI = 2.5, 5.0   # mean frame-to-frame jump of a bin's level, dB: below — a note, above — flicker
FL_WIN = 5                # half-window of the flicker estimate, frames (±~50 ms)
FLUX_DB = 6.0     # jump in the band's energy — a transient
HOLD_S = 0.07     # transient protection
REL_S = 0.05      # smoothness of the suppression's release
MID_STRENGTH = 0.6    # the centre (vocals, the main material) — gentler than the sides
EDGE_HZ = 200.0       # smooth band edges


def _win():
    i = np.arange(N)
    return 0.5 - 0.5 * np.cos(2 * np.pi * i / N)


def _stft(x):
    w = _win()
    xp = np.concatenate([np.zeros(N), x, np.zeros(N)])
    nf = 1 + (len(xp) - N) // HOP
    idx = np.arange(nf)[:, None] * HOP + np.arange(N)[None, :]
    return np.fft.rfft(xp[idx] * w, axis=1), len(xp)


def _istft(X, plen, n):
    w = _win()
    frames = np.fft.irfft(X, n=N, axis=1) * w
    y = np.zeros(plen)
    for f in range(frames.shape[0]):
        y[f * HOP:f * HOP + N] += frames[f]
    return (y / 1.5)[N:N + n]   # the sum of w² for a Hann window with hop N/4 is exactly 1.5


def shimmer_gains(mag_db, sr, lo, hi, strength):
    """The suppression mask in dB (frames × bins), 0 — leave alone."""
    nf, nb = mag_db.shape
    binhz = sr / N
    k0, k1 = int(np.ceil(lo / binhz)), int(np.floor(hi / binhz))
    if k1 - k0 < 2 * W + 3 or strength <= 0:
        return np.zeros_like(mag_db)
    a, b = max(0, k0 - W), min(nb, k1 + W + 1)
    seg = mag_db[:, a:b]
    padded = np.pad(seg.astype(np.float32), ((0, 0), (W, W)), mode='edge')
    base = np.median(sliding_window_view(padded, 2 * W + 1, axis=1), axis=-1).astype(np.float64)
    band = slice(k0 - a, k1 - a + 1)
    ex = seg[:, band] - base[:, band]

    # An outlier that has crossed the threshold is brought down to the surrounding
    # floor (the local median) rather than "cut by a percentage" — otherwise the
    # birdie stays louder than the music in its bin. Entry into suppression is
    # through a soft knee around the threshold.
    t = np.clip((ex - (THR - KNEE)) / (2 * KNEE), 0, 1)
    red = (t * t * (3 - 2 * t)) * np.clip(ex - TARGET, 0, MAX_RED)

    # Flicker versus note: shimmer trembles — a bin's level jumps by 10–20 dB
    # from frame to frame, while a note decays smoothly after its attack, by 1–2 dB
    # a frame. Only the trembling outliers are suppressed. (The first attempt — a
    # spectral flatness gate — didn't work: the birdies themselves make the band
    # look "tonal". The second — outlier length — didn't either: a 43 ms window
    # glues fast flashes together into a "long note".)
    ec = np.clip(ex, 0.0, 40.0)
    d = np.abs(np.diff(ec, axis=0, prepend=ec[:1]))
    cs = np.concatenate([np.zeros((1, d.shape[1])), np.cumsum(d, axis=0)])
    lo_i = np.clip(np.arange(nf) - FL_WIN, 0, nf)
    hi_i = np.clip(np.arange(nf) + FL_WIN + 1, 0, nf)
    fluct = (cs[hi_i] - cs[lo_i]) / (hi_i - lo_i)[:, None]
    flick = np.clip((fluct - FL_LO) / (FL_HI - FL_LO), 0, 1)
    red = red * flick

    # per-frame gates
    frac = (ex > THR).mean(axis=1)
    dens = np.clip((DENS_HI - frac) / (DENS_HI - DENS_LO), 0, 1)
    p = 10 ** (seg[:, band] / 10)
    flatf = 1.0
    e = 10 * np.log10(p.sum(axis=1) + 1e-20)
    hold_n = int(np.ceil(HOLD_S * sr / HOP))
    trans = np.ones(nf); h = 0
    for f in range(nf):
        if f > 0 and e[f] - e[f - 1] > FLUX_DB:
            h = hold_n
        if h > 0:
            trans[f] = 0.0; h -= 1
    gdb = -red * (strength * dens * flatf * trans)[:, None]

    # along frequency — the mask is widened onto neighbouring bins (that's the
    # same tone's "skirt" from the analysis window) rather than averaged: averaging
    # cut the suppression depth at the tone's centre by a third. Then a smooth
    # release over time.
    gp = np.pad(gdb, ((0, 0), (1, 1)), mode='edge')
    gdb = np.minimum(np.minimum(gp[:, :-2], gp[:, 1:-1]), gp[:, 2:])
    r = np.exp(-HOP / (sr * REL_S))
    for f in range(1, nf):
        gdb[f] = np.minimum(gdb[f], gdb[f - 1] * r)

    # smooth band edges
    fk = np.arange(k0, k1 + 1) * binhz
    edge = np.clip(np.minimum(fk - lo, hi - fk) / EDGE_HZ, 0, 1)
    out = np.zeros_like(mag_db)
    out[:, k0:k1 + 1] = gdb * edge[None, :]
    return out


CHUNK_S = 10.0   # processing chunk length, s
MARGIN_S = 1.0   # margin on each side of a chunk, s — every dependency in the algorithm
                 # is shorter than 0.1 s, so the result matches processing the whole track at once


def deshimmer(x, sr, strength=0.6, cutoff=None, lo=4500.0, hi=14000.0,
              return_removed=False):
    """x: [n, 2]. Works in mid/side: the sides at full strength,
    the centre at MID_STRENGTH. Leaves everything below lo and above min(hi, cutoff) alone.

    A long track is processed in chunks with a margin: the median across
    frequency on the whole track at once needed gigabytes of memory (on four
    minutes the process crashed)."""
    if cutoff is not None:
        hi = min(hi, cutoff * 0.97)
    if strength <= 0 or hi <= lo + 500:
        return (x.copy(), np.zeros_like(x)) if return_removed else x.copy()
    x = np.atleast_2d(x.T).T if x.ndim > 1 else x[:, None]
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    n = x.shape[0]
    chunk = int(CHUNK_S * sr) // HOP * HOP
    margin = int(MARGIN_S * sr) // HOP * HOP
    if n <= chunk + 2 * margin:
        y = _process(x, sr, strength, lo, hi)
    else:
        y = np.empty_like(x)
        for a in range(0, n, chunk):
            b = min(n, a + chunk)
            s0, s1 = max(0, a - margin), min(n, b + margin)
            part = _process(x[s0:s1], sr, strength, lo, hi)
            y[a:b] = part[a - s0:b - s0]
    return (y, x - y) if return_removed else y


def _process(x, sr, strength, lo, hi):
    n = x.shape[0]
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5
    outs = []
    for sig, s in ((mid, strength * MID_STRENGTH), (side, strength)):
        X, plen = _stft(sig)
        mag_db = 20 * np.log10(np.abs(X) + 1e-12)
        g = 10 ** (shimmer_gains(mag_db, sr, lo, hi, s) / 20)
        outs.append(_istft(X * g, plen, n))
    m2, s2 = outs
    return np.stack([m2 + s2, m2 - s2], axis=1)


def shimmer_amount(x, sr, cutoff=None, lo=4500.0, hi=14000.0) -> float:
    """How much of the band's energy the de-shimmer would have removed at full strength, dB.
    Needed by auto mode: a clean track gets a light clean-up, a flickering one a stronger one."""
    if cutoff is not None:
        hi = min(hi, cutoff * 0.97)
    if hi <= lo + 500:
        return 0.0
    x = np.atleast_2d(x.T).T if x.ndim > 1 else x[:, None]
    side = (x[:, 0] - x[:, -1]) * 0.5 if x.shape[1] > 1 else x[:, 0]
    mid = (x[:, 0] + x[:, -1]) * 0.5
    tot, kept = 0.0, 0.0
    k0, k1 = int(np.ceil(lo * N / sr)), int(np.floor(hi * N / sr))
    chunk = int(CHUNK_S * sr) // HOP * HOP
    for a in range(0, len(mid), chunk):
        for sig, s in ((mid[a:a + chunk], MID_STRENGTH), (side[a:a + chunk], 1.0)):
            if len(sig) < N:
                continue
            X, _ = _stft(sig)
            P = np.abs(X) ** 2
            g = 10 ** (shimmer_gains(10 * np.log10(P + 1e-24), sr, lo, hi, s) / 10)
            tot += P[:, k0:k1 + 1].sum(); kept += (P * g)[:, k0:k1 + 1].sum()
    return float(10 * np.log10(tot / max(kept, 1e-24)))
