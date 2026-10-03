"""Анализ: спектр, точка среза, громкость по ITU-R BS.1770-4, тру-пик."""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter, resample_poly

FFT_SIZE = 8192


# --------------------------------------------------------------------------
# спектр
# --------------------------------------------------------------------------

def average_spectrum(x: np.ndarray, sr: int, n: int = FFT_SIZE,
                     max_frames: int = 240) -> tuple[np.ndarray, np.ndarray]:
    """Усреднённая спектральная мощность по всему треку.

    Тихие окна выбрасываются: паузы между частями не должны
    занижать верх и сдвигать точку среза вниз.
    """
    mono = x.mean(axis=1) if x.ndim > 1 else x
    if mono.size < n:
        mono = np.pad(mono, (0, n - mono.size))

    span = mono.size - n
    hop = max(n // 2, span // max_frames if max_frames else n)
    starts = np.arange(0, span + 1, hop, dtype=int)[:max_frames]
    if starts.size == 0:
        starts = np.array([0])

    idx = starts[:, None] + np.arange(n)[None, :]
    frames = mono[idx]

    rms = np.sqrt((frames ** 2).mean(axis=1))
    thr = 0.25 * np.sqrt((mono ** 2).mean() + 1e-30)
    keep = rms > thr
    if keep.sum() < 4:
        keep = rms > 0
    if keep.sum() == 0:
        keep = np.ones_like(rms, dtype=bool)

    win = np.hanning(n)
    spec = np.fft.rfft(frames[keep] * win, axis=1)
    power = (np.abs(spec) ** 2).mean(axis=0)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    return freqs, power


def smooth_octave(power: np.ndarray, freqs: np.ndarray, frac: float = 1 / 12) -> np.ndarray:
    """Сглаживание по доле октавы — иначе кривая читается как шум."""
    binhz = freqs[1] - freqs[0]
    k = 2 ** (frac / 2)
    csum = np.concatenate([[0.0], np.cumsum(power)])
    lo = np.clip(np.floor(freqs / k / binhz), 1, len(power) - 1).astype(int)
    hi = np.clip(np.ceil(freqs * k / binhz), 1, len(power) - 1).astype(int)
    hi = np.maximum(hi, lo)
    out = (csum[hi + 1] - csum[lo]) / (hi - lo + 1)
    out[0] = out[1]
    return out


def to_db(power: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(power + 1e-20)


def band_reference(db: np.ndarray, freqs: np.ndarray) -> float:
    """Опорный уровень — 80-й перцентиль в полосе 1–5 кГц."""
    sel = db[(freqs >= 1000) & (freqs <= 5000)]
    if sel.size == 0:
        return -60.0
    return float(np.percentile(sel, 80))


def detect_cutoff(db: np.ndarray, freqs: np.ndarray, sr: int,
                  drop_db: float = 45.0) -> dict:
    """Ищем обрыв: сверху вниз, первая частота, где три бина подряд
    поднимаются над порогом."""
    nyq = sr / 2
    ref = band_reference(db, freqs)
    thr = ref - drop_db

    top = int(np.searchsorted(freqs, nyq * 0.995)) - 1
    bottom = int(np.searchsorted(freqs, 6000))
    cut_i = top
    for i in range(top, bottom + 2, -1):
        if db[i] > thr and db[i - 1] > thr and db[i - 2] > thr:
            cut_i = i
            break

    hz = float(np.clip(freqs[cut_i], 7000.0, nyq * 0.985))

    # Крутизна обрыва: перепад за треть октавы над точкой среза.
    above = db[(freqs > hz) & (freqs < min(hz * 1.26, nyq * 0.99))]
    steep = float(ref - above.mean()) if above.size else 0.0

    return {
        "hz": hz,
        "ref_db": ref,
        "full_range": hz > nyq * 0.9,
        "steepness_db": steep,
    }


def band_energy_db(db: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    sel = (freqs >= lo) & (freqs <= hi)
    if not sel.any():
        return -120.0
    return float(10 * np.log10(np.mean(10 ** (db[sel] / 10)) + 1e-20))


def mud_excess_db(db: np.ndarray, freqs: np.ndarray,
                  mud_lo: float = 250.0, mud_hi: float = 400.0,
                  ref_lo: float = 600.0, ref_hi: float = 2500.0) -> float:
    """Насколько полоса 250–400 Гц реально выпирает над серединой (600–2500 Гц).

    Положительное значение — там правда лишнее; ноль или отрицательное —
    резать нечего, бить туда фиксированным −2.5 дБ вслепую значит просто
    портить бас там, где мути не было.
    """
    mud = band_energy_db(db, freqs, mud_lo, mud_hi)
    ref = band_energy_db(db, freqs, ref_lo, ref_hi)
    return mud - ref


def stereo_width_ratio(x: np.ndarray) -> float:
    """Сколько в треке уже есть стерео-информации: RMS(side) / RMS(mid).

    0 — чистое моно, ~1 и выше — уже широкий материал. Нужно, чтобы не
    досыпать ширину туда, где она и так на пределе (риск фазовых проблем
    в моно-совместимости), и не жалеть её там, где сигнал почти моно.
    """
    if x.ndim < 2 or x.shape[1] < 2:
        return 0.0
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5
    mid_rms = np.sqrt(np.mean(mid ** 2) + 1e-20)
    side_rms = np.sqrt(np.mean(side ** 2) + 1e-20)
    return float(side_rms / (mid_rms + 1e-20))


# --------------------------------------------------------------------------
# громкость
# --------------------------------------------------------------------------

def _k_filters(sr: int):
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / sr)
    vh = 10 ** (gain / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    b1 = np.array([(vh + vb * k / q + k * k) / a0,
                   2 * (k * k - vh) / a0,
                   (vh - vb * k / q + k * k) / a0])
    a1 = np.array([1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0])

    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / sr)
    a0 = 1 + k / q + k * k
    b2 = np.array([1.0, -2.0, 1.0]) / a0
    a2 = np.array([1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0])
    return (b1, a1), (b2, a2)


def loudness_lufs(x: np.ndarray, sr: int) -> float:
    """Интегральная громкость по ITU-R BS.1770-4 с двойным гейтингом."""
    x = np.atleast_2d(x.T).T if x.ndim > 1 else x[:, None]
    (b1, a1), (b2, a2) = _k_filters(sr)

    block = int(round(0.4 * sr))
    hop = int(round(0.1 * sr))
    if x.shape[0] < block:
        return -70.0

    total = None
    for c in range(x.shape[1]):
        z = lfilter(b2, a2, lfilter(b1, a1, x[:, c]))
        cs = np.concatenate([[0.0], np.cumsum(z * z)])
        starts = np.arange(0, x.shape[0] - block + 1, hop)
        mean_sq = (cs[starts + block] - cs[starts]) / block
        total = mean_sq if total is None else total + mean_sq

    if total is None or total.size == 0:
        return -70.0

    lk = -0.691 + 10 * np.log10(total + 1e-20)

    sel = total[lk > -70.0]
    if sel.size == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(sel.mean() + 1e-20) - 10.0
    sel = sel[(-0.691 + 10 * np.log10(sel + 1e-20)) > rel]
    if sel.size == 0:
        return -70.0
    return float(-0.691 + 10 * np.log10(sel.mean() + 1e-20))


def true_peak_db(x: np.ndarray, sr: int, oversample: int = 4) -> float:
    """Тру-пик с передискретизацией. Кусок подбирается под кратность,
    чтобы память не росла: 30 секунд при 4x, 15 при 8x и так далее."""
    x = np.atleast_2d(x.T).T if x.ndim > 1 else x[:, None]
    peak = 0.0
    step = max(sr, sr * 120 // oversample)
    for s in range(0, x.shape[0], step):
        seg = x[s:s + step + 64]
        up = resample_poly(seg, oversample, 1, axis=0)
        peak = max(peak, float(np.abs(up).max()))
    return 20 * np.log10(peak + 1e-20)
