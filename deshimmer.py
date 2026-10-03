"""Де-шиммер: подавление «шиммера» — узких мерцающих артефактов генерации
в зоне примерно 4.5–14 кГц, которые оставляют Suno и подобные модели.

Своя реализация с нуля. Идеи сверены с публичными описаниями двух
проектов: deshimmer (TheApeMachine) — медианная базовая линия по частоте,
порог над ней с мягким коленом, защита широкополосных событий, обход
транзиентов; Shimmer (henricksmedia) — «сначала чистим, потом мастерим»,
низ не трогаем вовсе, центр микса чистим бережнее, чем стороны. Код ни
одного из проектов не использовался.

Зачем это Airband: экситер питается как раз полосой, где живёт шиммер.
Без чистки он строил бы из артефактов новые гармоники наверх.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

N = 2048          # окно STFT
HOP = 512         # шаг: 75% перекрытия, периодическое окно Ханна
W = 12            # полуширина медианы по частоте (25 бинов ≈ 590 Гц при 48 кГц)
THR = 8.0         # порог над базовой линией, дБ
KNEE = 3.0        # мягкое колено, дБ
TARGET = 1.0      # куда опускать выброс: до фона вокруг плюс 1 дБ
MAX_RED = 30.0    # больше этого не срезаем никогда
DENS_LO, DENS_HI = 0.05, 0.25    # доля выбросов в кадре: выше — это музыка, не трогаем
FL_LO, FL_HI = 2.5, 5.0   # средний скачок уровня бина от кадра к кадру, дБ: ниже — нота, выше — мерцание
FL_WIN = 5                # полуокно оценки дрожания, кадров (±~50 мс)
FLUX_DB = 6.0     # скачок энергии полосы — транзиент
HOLD_S = 0.07     # защита транзиента
REL_S = 0.05      # плавность отпускания подавления
MID_STRENGTH = 0.6    # центр (вокал, рабочий) — бережнее сторон
EDGE_HZ = 200.0       # плавные края полосы


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
    return (y / 1.5)[N:N + n]   # сумма w² для Ханна с шагом N/4 — ровно 1.5


def shimmer_gains(mag_db, sr, lo, hi, strength):
    """Маска подавления в дБ (кадры × бины), 0 — не трогать."""
    nf, nb = mag_db.shape
    binhz = sr / N
    k0, k1 = int(np.ceil(lo / binhz)), int(np.floor(hi / binhz))
    if k1 - k0 < 2 * W + 3 or strength <= 0:
        return np.zeros_like(mag_db)
    a, b = max(0, k0 - W), min(nb, k1 + W + 1)
    seg = mag_db[:, a:b]
    padded = np.pad(seg, ((0, 0), (W, W)), mode='edge')
    base = np.median(sliding_window_view(padded, 2 * W + 1, axis=1), axis=-1)
    band = slice(k0 - a, k1 - a + 1)
    ex = seg[:, band] - base[:, band]

    # Выброс, перешедший порог, опускается до фона вокруг (локальной медианы),
    # а не «срезается на процент» — иначе птичка остаётся громче музыки в
    # своём бине. Вход в подавление — по мягкому колену вокруг порога.
    t = np.clip((ex - (THR - KNEE)) / (2 * KNEE), 0, 1)
    red = (t * t * (3 - 2 * t)) * np.clip(ex - TARGET, 0, MAX_RED)

    # Мерцание против ноты: шиммер дрожит — уровень бина прыгает на 10–20 дБ
    # от кадра к кадру, а нота после атаки гаснет плавно, на 1–2 дБ за кадр.
    # Подавляем только дрожащие выбросы. (Первая попытка — гейт спектральной
    # плоскости — не годилась: птички сами делают полосу «тональной». Вторая —
    # длина выброса — тоже: окно 43 мс склеивает быстрые вспышки в «длинную
    # ноту».)
    ec = np.clip(ex, 0.0, 40.0)
    d = np.abs(np.diff(ec, axis=0, prepend=ec[:1]))
    cs = np.concatenate([np.zeros((1, d.shape[1])), np.cumsum(d, axis=0)])
    lo_i = np.clip(np.arange(nf) - FL_WIN, 0, nf)
    hi_i = np.clip(np.arange(nf) + FL_WIN + 1, 0, nf)
    fluct = (cs[hi_i] - cs[lo_i]) / (hi_i - lo_i)[:, None]
    flick = np.clip((fluct - FL_LO) / (FL_HI - FL_LO), 0, 1)
    red = red * flick

    # гейты по кадрам
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

    # по частоте — расширение маски на соседние бины (это «юбка» того же
    # тона от окна анализа), а не усреднение: усреднение резало глубину
    # подавления в центре тона на треть. Затем — плавное отпускание по времени.
    gp = np.pad(gdb, ((0, 0), (1, 1)), mode='edge')
    gdb = np.minimum(np.minimum(gp[:, :-2], gp[:, 1:-1]), gp[:, 2:])
    r = np.exp(-HOP / (sr * REL_S))
    for f in range(1, nf):
        gdb[f] = np.minimum(gdb[f], gdb[f - 1] * r)

    # плавные края полосы
    fk = np.arange(k0, k1 + 1) * binhz
    edge = np.clip(np.minimum(fk - lo, hi - fk) / EDGE_HZ, 0, 1)
    out = np.zeros_like(mag_db)
    out[:, k0:k1 + 1] = gdb * edge[None, :]
    return out


def deshimmer(x, sr, strength=0.6, cutoff=None, lo=4500.0, hi=14000.0,
              return_removed=False):
    """x: [n, 2]. Работает в mid/side: стороны — в полную силу,
    центр — на MID_STRENGTH. Ниже lo и выше min(hi, cutoff) не трогает."""
    if cutoff is not None:
        hi = min(hi, cutoff * 0.97)
    if strength <= 0 or hi <= lo + 500:
        return (x.copy(), np.zeros_like(x)) if return_removed else x.copy()
    x = np.atleast_2d(x.T).T if x.ndim > 1 else x[:, None]
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
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
    y = np.stack([m2 + s2, m2 - s2], axis=1)
    return (y, x - y) if return_removed else y


def shimmer_amount(x, sr, cutoff=None, lo=4500.0, hi=14000.0) -> float:
    """Сколько энергии полосы де-шиммер снял бы на полной силе, дБ.
    Нужна авто-режиму: чистый трек — лёгкая чистка, мерцающий — сильнее."""
    if cutoff is not None:
        hi = min(hi, cutoff * 0.97)
    if hi <= lo + 500:
        return 0.0
    x = np.atleast_2d(x.T).T if x.ndim > 1 else x[:, None]
    side = (x[:, 0] - x[:, -1]) * 0.5 if x.shape[1] > 1 else x[:, 0]
    mid = (x[:, 0] + x[:, -1]) * 0.5
    tot, kept = 0.0, 0.0
    for sig, s in ((mid, MID_STRENGTH), (side, 1.0)):
        X, _ = _stft(sig)
        P = np.abs(X) ** 2
        g = 10 ** (shimmer_gains(10 * np.log10(P + 1e-24), sr, lo, hi, s) / 10)
        k0, k1 = int(np.ceil(lo * N / sr)), int(np.floor(hi * N / sr))
        tot += P[:, k0:k1 + 1].sum(); kept += (P * g)[:, k0:k1 + 1].sum()
    return float(10 * np.log10(tot / max(kept, 1e-24)))
