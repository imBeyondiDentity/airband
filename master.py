"""The final stage: a lookahead limiter and loudness normalisation.

Checked against the Hyrax limiter from Matchering (sergree/matchering). Theirs
has a separate hold stage after the peak — the gain stays down for a while
before it starts to release — and the final gain curve is taken as an
element-wise minimum with the value that's actually required, so overshoot
is impossible by construction rather than caught after the fact by a clip.
This used to have neither: smoothing came straight after the lookahead
minimum, with no hold and no such guarantee — on transient material
(drums) that could produce a slight pumping: the gain released too
quickly right after a hit.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import minimum_filter1d
from scipy.signal import fftconvolve

from analysis import loudness_lufs, true_peak_db


def _trailing_min(req: np.ndarray, hold: int) -> np.ndarray:
    """g[i] = min(req[i-hold+1 .. i]) — the minimum is held forward in
    time after a dip, rather than smeared symmetrically backwards and forwards.

    The window is forced to be odd, and the standard centring (origin=0) is
    used with a shifted slice — on even windows scipy's origin parameter gives
    a barely noticeable but systematic shift of the result backwards in time
    (checked separately across a wide range of window sizes, not just on a
    small example)."""
    hold = hold | 1
    if hold <= 1:
        return req
    pad = hold - 1
    padded = np.pad(req, (pad, 0), mode="edge")
    out_full = minimum_filter1d(padded, size=hold, mode="nearest")
    start = hold // 2
    return out_full[start:start + len(req)]


def _gain_curve(peak: np.ndarray, ceiling: float, look: int, hold: int) -> np.ndarray:
    """The gain curve in three steps:

    1. Lookahead (a symmetric minimum, a small window) — the gain is already
       down by the time the peak arrives.
    2. Hold (a purely backward window, a larger one) — after the peak the gain
       doesn't start to release immediately, but stays at the bottom for another
       `hold` samples — which is what differs from the previous version.
    3. Smoothing of the shape with a Hann window, then an element-wise
       minimum with the original requirement `req` — a guarantee that smoothing
       couldn't accidentally bring the gain back above what's actually needed
       at that exact point. This guarantee used to be missing: a mismatch was
       caught only by a blunt clip() at the end.
    """
    win = 2 * look + 1
    req = np.ones_like(peak)
    hot = peak > ceiling
    req[hot] = ceiling / peak[hot]

    g = minimum_filter1d(req, size=win, mode="nearest")
    g = _trailing_min(g, hold)

    ker = np.hanning(win)
    ker /= ker.sum()
    g = fftconvolve(g, ker, mode="same")

    g = np.minimum(g, req)
    return np.clip(g, 0.0, 1.0)


def limit(x: np.ndarray, ceiling_db: float = -1.0, sr: int = 48000,
          lookahead_ms: float = 2.0, hold_ms: float = 40.0,
          margin_db: float = 0.4) -> np.ndarray:
    """Hold the peaks under the ceiling.

    The gain curve is computed per sample, but the ceiling is taken with a
    margin of margin_db. After that the true peak is checked honestly, on the
    oversampled signal, and if the margin wasn't enough, a static offset is
    added. That way inter-sample overshoots don't get through, and the track
    doesn't have to be held in memory at four times its size.
    """
    ceiling = 10 ** (ceiling_db / 20)
    inner = ceiling * 10 ** (-margin_db / 20)
    look = max(8, int(round(lookahead_ms * 1e-3 * sr)))
    hold = max(1, int(round(hold_ms * 1e-3 * sr)))

    peak = np.abs(x).max(axis=1)
    y = x * _gain_curve(peak, inner, look, hold)[:, None]
    np.clip(y, -ceiling, ceiling, out=y)

    # The final check runs at 8x rather than 4x: an independent reference
    # (16x) shows that 4x under-reads content right at the top of the frequency
    # range, and that's exactly what Airband creates. A 0.15 dB margin covers
    # whatever 8x still misses.
    safe_db = ceiling_db - 0.15
    tp = true_peak_db(y, sr, oversample=8)
    if tp > safe_db:
        trim = 10 ** ((safe_db - tp) / 20)
        y *= trim
    return y


def normalize(x: np.ndarray, sr: int, target_lufs: float,
              ceiling_db: float = -1.0, tol_db: float = 0.1,
              max_passes: int = 4) -> tuple[np.ndarray, dict]:
    """Bring to the target loudness and hold the peaks.

    The limiter itself lowers the loudness, so one pass isn't enough:
    the target is refined iteratively until the miss is under a tenth of
    a decibel.
    """
    before = loudness_lufs(x, sr)
    if before <= -70:
        return x.copy(), {"lufs_before": before, "lufs_after": before,
                          "true_peak": true_peak_db(x, sr), "gain_db": 0.0,
                          "passes": 0}

    total = target_lufs - before
    y = limit(x * 10 ** (total / 20), ceiling_db, sr)
    after = loudness_lufs(y, sr)

    passes = 1
    while abs(target_lufs - after) > tol_db and passes < max_passes:
        total += target_lufs - after
        y = limit(x * 10 ** (total / 20), ceiling_db, sr)
        after = loudness_lufs(y, sr)
        passes += 1

    return y, {
        "lufs_before": before,
        "lufs_after": after,
        "true_peak": true_peak_db(y, sr),
        "gain_db": total,
        "passes": passes,
    }


def album_offset(loudnesses: list[float], target_lufs: float) -> float:
    """One shared offset for the whole album.

    The loudest track is brought up to the target, and the rest keep
    their original relationships — a quiet interlude stays quiet.
    """
    valid = [l for l in loudnesses if l > -70]
    if not valid:
        return 0.0
    return target_lufs - max(valid)


def apply_offset(x: np.ndarray, sr: int, offset_db: float,
                 ceiling_db: float = -1.0) -> tuple[np.ndarray, dict]:
    before = loudness_lufs(x, sr)
    y = limit(x * 10 ** (offset_db / 20), ceiling_db, sr)
    return y, {
        "lufs_before": before,
        "lufs_after": loudness_lufs(y, sr),
        "true_peak": true_peak_db(y, sr),
        "gain_db": offset_db,
    }
