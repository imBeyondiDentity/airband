"""Dynamics and stereo stages for the final polish: multiband compression,
mono bass and a soft clipper.

All three are off by default (amount 0 returns the input untouched, the very
same array), so existing output stays bit-identical until a stage is asked for.

The chain design follows the stages that Sony's ITO-Master predicts
parameters for (EQ, multiband compressor, imager, limiter). Only the idea is
borrowed: no weights and no code, everything here is plain DSP written for
Airband.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, lfilter, sosfiltfilt

# --- multiband compressor ---------------------------------------------------
MB_SPLITS = (150.0, 1500.0, 6000.0)     # Hz, four bands
MB_RATIO = (2.0, 2.0, 1.8, 1.6)         # at amount 1.0; the ratio scales with amount
MB_ATTACK_MS = (30.0, 15.0, 8.0, 4.0)
MB_RELEASE_MS = (250.0, 160.0, 110.0, 80.0)
MB_PERCENTILE = 60.0                    # threshold: where the band's own level sits 60 % of the time
MB_MAX_GR_DB = 6.0                      # never take off more than this
MB_DETECT_MS = 20.0                     # RMS window of the level detector
MB_DECIMATE = 64                        # level analysis keeps every 64th sample
CHUNK_S = 10.0
MARGIN_S = 1.0

# --- mono bass --------------------------------------------------------------
MONO_BASS_HZ = 120.0

# --- soft clipper -----------------------------------------------------------
CLIP_MAX_KNEE_DB = 3.0                  # at amount 1.0 the knee sits 3 dB below the ceiling


def _lp(x: np.ndarray, hz: float, sr: int, order: int = 2) -> np.ndarray:
    """A zero-phase low-pass: a Butterworth run forwards and backwards, which
    makes it a Linkwitz-Riley-shaped split (−6 dB at the corner) with no
    phase shift. A low band made this way and the remainder (input minus
    low) add back to the input exactly."""
    sos = butter(order, hz, fs=sr, output="sos")
    return sosfiltfilt(sos, x, axis=0)


def _split(x: np.ndarray, sr: int) -> list[np.ndarray]:
    bands, rest = [], x
    for hz in MB_SPLITS:
        low = _lp(rest, hz, sr)
        bands.append(low)
        rest = rest - low
    bands.append(rest)
    return bands


def _one_pole(x: np.ndarray, ms: float, sr: int) -> np.ndarray:
    a = np.exp(-1.0 / max(1.0, ms * 1e-3 * sr))
    return lfilter([1.0 - a], [1.0, -a], x)


def _band_level_db(band: np.ndarray, sr: int) -> np.ndarray:
    power = np.mean(band * band, axis=1)
    return 10.0 * np.log10(_one_pole(power, MB_DETECT_MS, sr) + 1e-12)


def _gain_reduction(level_db: np.ndarray, thr_db: float, ratio: float,
                    attack_ms: float, release_ms: float, sr: int) -> np.ndarray:
    """Static curve first, then asymmetric smoothing in two vectorised passes:
    a fast and a slow one-pole, and the larger of the two. A rising reduction
    follows the fast one (attack), a falling one is held by the slow one
    (release)."""
    gr = np.maximum(level_db - thr_db, 0.0) * (1.0 - 1.0 / ratio)
    gr = np.minimum(gr, MB_MAX_GR_DB)
    fast = _one_pole(gr, attack_ms, sr)
    slow = _one_pole(gr, release_ms, sr)
    return np.maximum(fast, slow)


def _mb_chunk(xc: np.ndarray, sr: int, amount: float, thr: list[float] | None):
    """One chunk: returns the compressed signal and, for the analysis pass,
    each band's decimated level curve."""
    bands = _split(xc, sr)
    out = np.zeros_like(xc)
    levels = []
    for i, b in enumerate(bands):
        lv = _band_level_db(b, sr)
        levels.append(lv[::MB_DECIMATE].copy())
        if thr is not None:
            ratio = 1.0 + amount * (MB_RATIO[i] - 1.0)
            gr = _gain_reduction(lv, thr[i], ratio, MB_ATTACK_MS[i], MB_RELEASE_MS[i], sr)
            b = b * (10.0 ** (-gr / 20.0))[:, None]
        out += b
    return out, levels


def _chunks(n: int, sr: int):
    size = int(CHUNK_S * sr)
    margin = int(MARGIN_S * sr)
    for start in range(0, n, size):
        stop = min(n, start + size)
        lo, hi = max(0, start - margin), min(n, stop + margin)
        yield start, stop, lo, hi


def multiband(x: np.ndarray, sr: int, amount: float) -> np.ndarray:
    """Four-band gentle compression, thresholds taken from the track itself.

    Pass one measures each band's level over the whole track and puts the
    threshold at its 60th percentile, so the compressor works on the louder
    passages of every band whatever the overall level. Pass two compresses.
    Both passes run in chunks of ten seconds with a one-second margin,
    so a four-minute track needs the memory of a ten-second one.
    """
    if amount <= 0:
        return x
    amount = float(min(amount, 1.0))
    n = len(x)

    pools: list[list[np.ndarray]] = [[] for _ in range(len(MB_SPLITS) + 1)]
    for start, stop, lo, hi in _chunks(n, sr):
        _, levels = _mb_chunk(x[lo:hi], sr, amount, None)
        s0 = (start - lo) // MB_DECIMATE
        s1 = s0 + max(1, (stop - start) // MB_DECIMATE)
        for i, lv in enumerate(levels):
            pools[i].append(lv[s0:s1])
    thr = [float(np.percentile(np.concatenate(p), MB_PERCENTILE)) for p in pools]

    y = np.empty_like(x)
    for start, stop, lo, hi in _chunks(n, sr):
        yc, _ = _mb_chunk(x[lo:hi], sr, amount, thr)
        y[start:stop] = yc[start - lo:start - lo + (stop - start)]
    return y


def mono_bass(x: np.ndarray, sr: int, amount: float, hz: float = MONO_BASS_HZ) -> np.ndarray:
    """Takes the side signal out of the low end, so the bass stays centred and
    stays solid on a club system or a phone speaker. At amount 1.0 the side
    signal is gone below about half of `hz` (−48 dB at 60 Hz for 120 Hz) and
    fades out towards the corner; 0 leaves the input as it was."""
    if amount <= 0 or x.shape[1] < 2:
        return x
    amount = float(min(amount, 1.0))
    low = _lp(x, hz, sr, order=4)      # steeper, so the side is gone well below the corner
    side = 0.5 * (low[:, 0] - low[:, 1]) * amount
    y = x.copy()
    y[:, 0] -= side
    y[:, 1] += side
    return y


def soft_clip(x: np.ndarray, ceiling_lin: float, amount: float) -> np.ndarray:
    """Rounds the very tops of the peaks before the limiter sees them.

    Below the knee the signal is untouched. Above it, a tanh curve bends the
    peak smoothly towards `ceiling_lin` and never past it, so the limiter has
    almost nothing left to grab and pumps less. The knee sits up to 3 dB
    below the ceiling, depending on `amount`.
    """
    if amount <= 0:
        return x
    amount = float(min(amount, 1.0))
    knee = ceiling_lin * 10.0 ** (-CLIP_MAX_KNEE_DB * amount / 20.0)
    span = ceiling_lin - knee
    a = np.abs(x)
    over = a > knee
    if not over.any():
        return x
    y = x.copy()
    shaped = knee + span * np.tanh((a[over] - knee) / span)
    y[over] = np.sign(x[over]) * shaped
    return y
