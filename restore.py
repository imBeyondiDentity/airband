"""Восстановление верха и тональная коррекция.

Главное отличие от браузерной версии — слежение за огибающей.
Новый верх не просто подмешивается ровным слоем: его уровень
в каждый момент выводится из наклона спектра под точкой среза,
поэтому воздух дышит вместе с музыкой, а не шипит поверх неё.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import firwin, firwin2, resample_poly, sosfilt, stft, fftconvolve

from analysis import average_spectrum, smooth_octave, to_db


# --------------------------------------------------------------------------
# фильтры
# --------------------------------------------------------------------------

def _fir(taps: int, cuts, sr: int, pass_zero):
    return firwin(taps | 1, cuts, fs=sr, pass_zero=pass_zero, window="blackmanharris")


def _apply_fir(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Линейная фаза: свёртка с обрезкой по центру, задержка компенсируется."""
    out = np.empty_like(x)
    for c in range(x.shape[1]):
        out[:, c] = fftconvolve(x[:, c], h, mode="same")
    return out


def _rbj(kind: str, f0: float, q: float, gain_db: float, sr: int) -> np.ndarray:
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / sr
    cw, sw = np.cos(w), np.sin(w)
    alpha = sw / (2 * q)

    if kind == "peaking":
        b = [1 + alpha * a, -2 * cw, 1 - alpha * a]
        aa = [1 + alpha / a, -2 * cw, 1 - alpha / a]
    elif kind == "highshelf":
        t = 2 * np.sqrt(a) * alpha
        b = [a * ((a + 1) + (a - 1) * cw + t),
             -2 * a * ((a - 1) + (a + 1) * cw),
             a * ((a + 1) + (a - 1) * cw - t)]
        aa = [(a + 1) - (a - 1) * cw + t,
              2 * ((a - 1) - (a + 1) * cw),
              (a + 1) - (a - 1) * cw - t]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        aa = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(kind)

    b = np.asarray(b, float) / aa[0]
    aa = np.asarray(aa, float) / aa[0]
    return np.concatenate([b, aa])[None, :]


def _biquad(x: np.ndarray, sos: np.ndarray) -> np.ndarray:
    return sosfilt(sos, x, axis=0)


# --------------------------------------------------------------------------
# досинтез верха
# --------------------------------------------------------------------------

def _saturate(u: np.ndarray, drive: float) -> np.ndarray:
    """Мягкое несимметричное насыщение: нечётные гармоники дают яркость,
    чётные — теплоту. Без асимметрии верх звучит стеклянно."""
    v = np.tanh(u * drive)
    return v * (1.0 + 0.25 * v)


def _envelope_gain(x: np.ndarray, synth: np.ndarray, sr: int, cutoff: float,
                   n: int = 2048, hop: int = 512) -> np.ndarray:
    """Во сколько раз усилить синтезированную полосу в каждый момент.

    Наклон спектра меряется по двум полосам под срезом и
    экстраполируется выше него — так получается уровень,
    который был бы у материала, если бы его не обрезали.
    """
    mono_x = x.mean(axis=1)
    mono_s = synth.mean(axis=1)

    nyq = sr / 2
    f = np.fft.rfftfreq(n, 1.0 / sr)
    b1 = (f >= cutoff * 0.35) & (f < cutoff * 0.60)
    b2 = (f >= cutoff * 0.60) & (f < cutoff * 0.95)
    bf = (f > cutoff) & (f < nyq * 0.94)
    if not (b1.any() and b2.any() and bf.any()):
        return np.ones(mono_x.size)

    # Кадры считаются пачками и сразу сворачиваются в средние по полосам —
    # полная спектрограмма трека в памяти не нужна. Окно Ханна периодическое,
    # как у scipy.signal.stft; масштаб окна сокращается в разности уровней.
    win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)
    nf = 1 + (mono_x.size - n) // hop if mono_x.size >= n else 0
    if nf <= 0:
        return np.ones(mono_x.size)
    l1, l2, ls = (np.empty(nf) for _ in range(3))
    for a in range(0, nf, 2048):
        b = min(nf, a + 2048)
        idx = (np.arange(a, b) * hop)[:, None] + np.arange(n)[None, :]
        px = np.abs(np.fft.rfft(mono_x[idx] * win, axis=1)) ** 2
        ps = np.abs(np.fft.rfft(mono_s[idx] * win, axis=1)) ** 2
        l1[a:b] = 10 * np.log10(px[:, b1].mean(axis=1) + 1e-20)
        l2[a:b] = 10 * np.log10(px[:, b2].mean(axis=1) + 1e-20)
        ls[a:b] = 10 * np.log10(ps[:, bf].mean(axis=1) + 1e-20)

    c1 = float(np.sqrt(cutoff * 0.35 * cutoff * 0.60))
    c2 = float(np.sqrt(cutoff * 0.60 * cutoff * 0.95))
    cf = float(np.sqrt(cutoff * min(nyq * 0.94, cutoff * 1.5)))

    slope = (l2 - l1) / np.log2(c2 / c1)
    slope = np.clip(slope, -30.0, -2.0)
    target = l2 + slope * np.log2(cf / c2)

    gain_db = np.clip(target - ls, -30.0, 18.0)

    # Кадры, где в опорной полосе почти тишина, не должны
    # раздувать шум: гасим их.
    quiet = l2 < (np.percentile(l2, 95) - 45)
    gain_db[quiet] = -60.0

    # Сглаживание по времени, окно около 25 мс.
    k = max(3, int(round(0.025 * sr / hop)) | 1)
    ker = np.hanning(k)
    ker /= ker.sum()
    gain_db = np.convolve(gain_db, ker, mode="same")

    g = 10 ** (gain_db / 20)
    frame_pos = np.arange(g.size) * hop + n / 2
    return np.interp(np.arange(mono_x.size), frame_pos, g,
                     left=float(g[0]), right=float(g[-1]))


def harmonic_air(x: np.ndarray, sr: int, cutoff: float, amount: float,
                 drive: float, follow: bool = True,
                 oversample: int = 4, taps: int = 1025) -> np.ndarray:
    """Синтезировать содержимое выше точки среза. Возвращает только новый
    материал, без исходного сигнала."""
    nyq = sr / 2
    if amount <= 0 or cutoff >= nyq * 0.93:
        return np.zeros_like(x)

    lo = max(2500.0, cutoff * 0.42)
    hi = min(cutoff * 0.94, nyq * 0.96)
    if hi <= lo * 1.1:
        return np.zeros_like(x)

    band = _apply_fir(x, _fir(taps, [lo, hi], sr, pass_zero=False))

    # Насыщение на 4-кратной частоте — кусками с запасом: на всём треке
    # разом передискретизованный массив и копии внутри кривой занимали
    # гигабайты (четырёхминутный трек падал по памяти). Фильтру
    # передискретизации нужно лишь несколько десятков отсчётов контекста,
    # так что запаса в 4096 хватает с лихвой — результат тот же.
    n = x.shape[0]
    chunk, margin = sr * 10, 4096
    synth = np.empty_like(band)
    for a in range(0, n, chunk):
        b = min(n, a + chunk)
        s0, s1 = max(0, a - margin), min(n, b + margin)
        up = resample_poly(band[s0:s1], oversample, 1, axis=0)
        dn = resample_poly(_saturate(up, 1.0 + drive * 14.0), 1, oversample, axis=0)
        synth[a:b] = dn[a - s0:b - s0]
    # постоянная составляющая: среднее после понижения частоты равно
    # среднему до него — вычитаем его здесь, как раньше до понижения
    synth -= synth.mean(axis=0, keepdims=True)

    top = min(cutoff * 0.99, nyq * 0.9)
    synth = _apply_fir(synth, _fir(taps, [top, nyq * 0.94], sr, pass_zero=False))

    if follow:
        g = _envelope_gain(x, synth, sr, cutoff)
        synth *= g[:, None]
    else:
        ref = np.sqrt((x ** 2).mean() + 1e-20)
        cur = np.sqrt((synth ** 2).mean() + 1e-20)
        synth *= (ref / cur) * 0.02

    return synth * amount


# --------------------------------------------------------------------------
# тональная коррекция и стерео
# --------------------------------------------------------------------------

def tone(x: np.ndarray, sr: int, mud_db: float, shelf_db: float,
         rumble_hz: float = 26.0) -> np.ndarray:
    y = _biquad(x, _rbj("highpass", rumble_hz, 0.6, 0.0, sr))
    if abs(mud_db) > 0.01:
        y = _biquad(y, _rbj("peaking", 300.0, 0.9, mud_db, sr))
    if abs(shelf_db) > 0.01:
        y = _biquad(y, _rbj("highshelf", 11000.0, 0.7, shelf_db, sr))
    return y


def widen(x: np.ndarray, sr: int, amount: float, split_hz: float = 2500.0,
          taps: int = 513) -> np.ndarray:
    """Расширение только выше split_hz. Низ остаётся моно —
    иначе на клубной системе бас разъезжается."""
    if amount <= 0 or x.shape[1] < 2:
        return x
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5
    hi = fftconvolve(side, _fir(taps, split_hz, sr, pass_zero=False), mode="same")
    side = side + hi * amount * 1.2
    return np.stack([mid + side, mid - side], axis=1)


def match_reference(x: np.ndarray, sr: int, ref: np.ndarray,
                    strength: float = 1.0, max_db: float = 6.0,
                    taps: int = 2049) -> np.ndarray:
    """Подогнать тональный баланс под эталонный трек.

    Считается сглаженное отношение спектров, из него вычитается
    средний уровень в 200–2000 Гц — правится форма, а не громкость.
    Коррекция ограничена и применяется фильтром с линейной фазой.
    """
    fx, px = average_spectrum(x, sr)
    fr, pr = average_spectrum(ref, sr)
    dx = to_db(smooth_octave(px, fx, 1 / 6))
    dr = to_db(smooth_octave(pr, fr, 1 / 6))

    corr = dr - dx
    anchor = (fx >= 200) & (fx <= 2000)
    corr -= corr[anchor].mean()
    corr = np.clip(corr, -max_db, max_db) * strength

    nyq = sr / 2
    freq = np.clip(fx / nyq, 0, 1)
    freq[0], freq[-1] = 0.0, 1.0
    gain = 10 ** (corr / 20)
    gain[-1] = gain[-2]

    # Прореживаем сетку — firwin2 не любит тысячи точек.
    keep = np.unique(np.linspace(0, freq.size - 1, 512).astype(int))
    h = firwin2(taps | 1, freq[keep], gain[keep], window="hann")
    return _apply_fir(x, h)
