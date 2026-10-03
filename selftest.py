#!/usr/bin/env python3
"""Самопроверка DSP. Запускать после любых правок:

    python selftest.py

Синтезирует сигнал, режет его как кодек, восстанавливает
и сравнивает результат с тем, что было до обрезки.
"""

from __future__ import annotations

import sys

import numpy as np
from scipy.signal import firwin, fftconvolve

from analysis import (average_spectrum, band_reference, detect_cutoff,
                      loudness_lufs, smooth_octave, to_db, true_peak_db)
from master import _gain_curve, limit, normalize
from restore import harmonic_air, tone

SR = 48000
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "ок  " if ok else "СБОЙ"
    print(f"  [{mark}] {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


# --------------------------------------------------------------------------

def test_loudness() -> None:
    print("Измеритель громкости (ITU-R BS.1770-4)")
    n = SR * 5
    t = np.arange(n) / SR

    mono = np.sin(2 * np.pi * 997 * t)[:, None]
    v = loudness_lufs(mono, SR)
    check("калибровка 997 Гц, 0 dBFS, один канал", abs(v + 3.01) < 0.15,
          f"{v:+.2f} LUFS при эталоне -3.01")

    stereo = np.repeat(np.sin(2 * np.pi * 997 * t)[:, None], 2, axis=1)
    v2 = loudness_lufs(stereo, SR)
    check("два канала дают ровно +3.01 дБ", abs((v2 - v) - 3.01) < 0.1,
          f"разница {v2 - v:+.2f} дБ")

    v3 = loudness_lufs(stereo * 0.1, SR)
    check("линейность по усилению", abs((v3 - v2) + 20.0) < 0.1,
          f"-20 дБ дали {v3 - v2:+.2f}")

    check("тишина уходит в пол", loudness_lufs(np.zeros((n, 2)), SR) <= -70)


def test_limiter() -> None:
    print("\nЛимитер")
    n = SR * 3
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.15, (n, 2))
    for pos in range(SR // 2, n, SR // 2):
        x[pos] = 2.4

    y = limit(x, ceiling_db=-1.0, sr=SR)
    tp = true_peak_db(y, SR)
    check("тру-пик под потолком", tp <= -0.99, f"{tp:+.3f} дБ при потолке -1.00")

    ceiling = 10 ** (-1.0 / 20)
    over = np.abs(y) > ceiling + 1e-9
    check("жёсткий clip() почти не нужен", over.sum() < 5,
          f"сработал на {over.sum()} из {y.size} сэмплов")

    # Hold-стадия: после одиночного транзиента гейн должен держаться
    # у дна ~40 мс (сверено с подходом Hyrax из Matchering), а не
    # отпускать сразу же.
    peak = np.zeros(n)
    peak[SR] = 2.0
    inner = ceiling * 10 ** (-0.4 / 20)
    look = max(8, round(2.0e-3 * SR))
    hold = max(1, round(40.0e-3 * SR))
    g = _gain_curve(peak, inner, look, hold)
    floor = g[SR:SR + 5].min()
    held = int(np.sum(g[SR:] <= floor * 1.05))
    for i, v in enumerate(g[SR:]):
        if v > floor * 1.05:
            held = i
            break
    check("гейн держится после пика, не отпускает сразу",
          30 < held / SR * 1000 < 55, f"держится {held / SR * 1000:.1f} мс, ожидаю ~40")

    quiet = np.abs(x).max(axis=1) < 0.5
    ratio = np.abs(y[quiet]).mean() / np.abs(x[quiet]).mean()
    check("тихие места почти не тронуты", ratio > 0.93, f"осталось {ratio * 100:.1f}%")


def test_normalize() -> None:
    print("\nНормализация")
    n = SR * 6
    t = np.arange(n) / SR
    rng = np.random.default_rng(2)
    x = (0.2 * np.sin(2 * np.pi * 120 * t) + rng.normal(0, 0.05, n))[:, None]
    x = np.repeat(x, 2, axis=1)

    for target in (-14.0, -11.0, -8.0):
        y, st = normalize(x, SR, target)
        check(f"попадание в {target:+.0f} LUFS", abs(st["lufs_after"] - target) < 0.15,
              f"получилось {st['lufs_after']:+.2f} за {st['passes']} прохода(ов)")
        check(f"потолок при цели {target:+.0f}", st["true_peak"] <= -0.99,
              f"{st['true_peak']:+.3f} дБ")


def _material(secs: float = 8.0) -> np.ndarray:
    n = int(SR * secs)
    t = np.arange(n) / SR
    rng = np.random.default_rng(5)
    x = np.zeros(n)
    for f, a in [(82.4, .5), (123.5, .35), (164.8, .3), (246.9, .22), (493.9, .12)]:
        x += a * np.sin(2 * np.pi * f * t + rng.random())
    for k in range(int(secs * 4)):
        s = int(k * 0.25 * SR)
        L = int(0.06 * SR)
        x[s:s + L] += rng.normal(0, 1, L) * np.exp(-np.linspace(0, 9, L)) * 0.5
    x *= 0.45 / np.abs(x).max()
    return np.stack([x, np.roll(x, 7) * 0.97], axis=1)


def _brickwall(x: np.ndarray, hz: float) -> np.ndarray:
    h = firwin(1025, hz, fs=SR)
    return np.stack([fftconvolve(x[:, c], h, mode="same") for c in range(x.shape[1])], axis=1)


def test_restoration() -> None:
    print("\nВосстановление верха")
    truth = _material()
    cut_hz = 16000.0
    cut_material = _brickwall(truth, cut_hz)

    f, p = average_spectrum(cut_material, SR)
    db = to_db(smooth_octave(p, f, 1 / 12))
    found = detect_cutoff(db, f, SR)
    err = abs(found["hz"] - cut_hz) / cut_hz
    check("детектор находит срез", err < 0.06,
          f"нашёл {found['hz'] / 1000:.2f} кГц, срезано на {cut_hz / 1000:.1f}")

    y = tone(cut_material, SR, 0.0, 0.0)
    y = y + harmonic_air(y, SR, found["hz"], amount=1.0, drive=0.65)

    def profile(sig):
        ff, pp = average_spectrum(sig, SR)
        dd = to_db(smooth_octave(pp, ff, 1 / 12))
        return ff, dd - band_reference(dd, ff)

    f0, s0 = profile(truth)
    f1, s1 = profile(cut_material)
    f2, s2 = profile(y)

    worst = 0.0
    print("    частота   правда   срезано  восстановлено")
    for hz in (17000, 18000, 19000, 20000, 21000):
        i0 = int(np.argmin(abs(f0 - hz)))
        i1 = int(np.argmin(abs(f1 - hz)))
        i2 = int(np.argmin(abs(f2 - hz)))
        worst = max(worst, abs(s2[i2] - s0[i0]))
        print(f"    {hz:>7} {s0[i0]:+8.1f} {s1[i1]:+9.1f} {s2[i2]:+13.1f}")

    check("восстановленный верх близок к оригиналу", worst < 6.0,
          f"худшее расхождение {worst:.1f} дБ")

    i_mid = (f2 > 200) & (f2 < 4000)
    j_mid = (f0 > 200) & (f0 < 4000)
    drift = abs(s2[i_mid].mean() - s0[j_mid].mean())
    check("середина не поехала", drift < 1.0, f"сдвиг {drift:.2f} дБ")


def test_auto_params() -> None:
    print("\nАвто-параметры (Master Assistant)")
    from airband import analyse, auto_params

    truth = _material()

    # Полный диапазон — досинтез должен быть выключен целиком.
    cut_full = analyse(truth, SR)
    p_full = auto_params(truth, SR, cut_full)
    check("полный диапазон -> без досинтеза", p_full.air == 0.0 and p_full.drive == 0.0,
          f"air={p_full.air:.2f} drive={p_full.drive:.2f}")

    # Жёсткий обрыв (16 кГц, кирпичная стена) -> заметно более
    # агрессивные значения, чем мягкий скат.
    hard = _brickwall(truth, 16000.0)
    cut_hard = analyse(hard, SR)
    p_hard = auto_params(hard, SR, cut_hard)
    check("жёсткий обрыв -> досинтез включён", p_hard.air > 0.5,
          f"air={p_hard.air:.2f}")

    # Пропорция: чем мягче скат, тем меньше агрессия. Сравниваю жёсткий
    # обрыв с более мягким (тот же метод _brickwall, но ниже порядок —
    # эмулирую через второй, менее жёсткий фильтр вручную).
    from scipy.signal import butter, sosfilt
    h = butter(2, 16000, "lowpass", fs=SR, output="sos")
    soft = np.stack([sosfilt(h, truth[:, c]) for c in range(truth.shape[1])], axis=1)
    cut_soft = analyse(soft, SR)
    p_soft = auto_params(soft, SR, cut_soft)
    check("мягкий скат мягче жёсткого обрыва (или не детектится вовсе)",
          p_soft.air <= p_hard.air,
          f"мягкий air={p_soft.air:.2f}, жёсткий air={p_hard.air:.2f}")

    # Мутный тест: берём сам материал _material() как есть — в нём есть
    # тон на 246.9 Гц, который объективно даёт подъём в полосе 250–400 Гц
    # (это не баг измерения, а реальное свойство синтетики). Проверяю
    # обратное: широкополосный шум без тонов в этой полосе не должен
    # давать ложного срабатывания.
    rng = np.random.default_rng(3)
    flat_noise = rng.normal(0, 1, SR * 4)
    flat_noise = np.stack([flat_noise, flat_noise], axis=1) * 0.2
    f_flat, p_flat = average_spectrum(flat_noise, SR)
    db_flat = to_db(smooth_octave(p_flat, f_flat, 1 / 12))
    from analysis import mud_excess_db
    excess_flat = mud_excess_db(db_flat, f_flat)
    check("широкополосный шум без тона -> избыток мути около нуля",
          abs(excess_flat) < 3.0, f"избыток {excess_flat:+.1f} дБ")

    # А вот material() с её тоном на 246.9 Гц ДОЛЖНА показать реальный
    # избыток — это подтверждает, что измерение вообще что-то различает,
    # а не всегда возвращает одно и то же.
    excess_material = mud_excess_db(cut_hard["_db"], cut_hard["_freqs"])
    check("тон на 246.9 Гц в material() даёт реальный избыток",
          excess_material > 5.0, f"избыток {excess_material:+.1f} дБ")


def _shimmer_material(secs=8.0):
    """Чистый материал с полосой 4.5–14 кГц (хэты, «воздух» тарелок,
    мелодия с обертонами) и отдельно — синтетический шиммер: узкие
    мерцающие тона 5–13 кГц, вспышки 20–60 мс, в основном в боковом канале."""
    from scipy.signal import butter, sosfilt
    r = np.random.default_rng(5); n = int(SR * secs); t = np.arange(n) / SR
    x = np.zeros(n)
    for f, a in [(82.4, .5), (123.5, .35), (246.9, .22), (987.8, .08)]:
        x += a * np.sin(2 * np.pi * f * t + r.random())
    for k in range(int(secs * 4)):
        s0 = int(k * 0.25 * SR); L = int(0.06 * SR)
        x[s0:s0 + L] += r.normal(0, 1, L) * np.exp(-np.linspace(0, 9, L)) * 0.5
    bed = sosfilt(butter(2, 3000, 'highpass', fs=SR, output='sos'), r.normal(0, 1, n)) * 0.03
    x += bed
    nl = int(0.4 * SR)
    for j, f0 in enumerate([880, 1047, 1175, 1319] * int(secs)):
        s0 = j * nl
        if s0 >= n: break
        L = min(nl, n - s0); tt = np.arange(L) / SR
        env = np.minimum(1, tt / 0.01) * np.exp(-tt * 2)
        x[s0:s0 + L] += sum((0.6 / h) * np.sin(2 * np.pi * f0 * h * tt) for h in range(1, 15) if f0 * h < 13500) * env * 0.05
    clean = np.stack([x + 0.2 * bed, np.roll(x, 7) * 0.97 - 0.2 * bed], axis=1)
    clean = clean / np.abs(clean).max() * 0.5
    art = np.zeros((n, 2)); ra = np.random.default_rng(9)
    for _ in range(14):
        f = ra.uniform(5000, 13000); env = np.zeros(n); pos = 0
        while pos < n:
            L = int(ra.uniform(0.02, 0.06) * SR)
            if L <= n - pos: env[pos:pos + L] = ra.uniform(0.5, 1.0) * np.hanning(L)
            pos += L + int(ra.uniform(0.02, 0.15) * SR)
        tone = np.sin(2 * np.pi * f * t + ra.random() * 6.28) * env * 0.012
        mp = ra.uniform(0.15, 0.4)
        art[:, 0] += tone; art[:, 1] += tone * (-1 + 2 * mp)
    return clean, art


def test_deshimmer() -> None:
    print("\nДе-шиммер")
    from deshimmer import _stft, _istft, deshimmer, shimmer_amount
    rng = np.random.default_rng(1)
    z = rng.normal(0, 0.3, SR * 2)
    Z, pl = _stft(z)
    err = np.max(np.abs(_istft(Z, pl, len(z)) - z))
    check("STFT без обработки восстанавливает сигнал", err < 1e-9, f"ошибка {err:.1e}")

    clean, art = _shimmer_material()
    x = clean + art

    def band(sig, lo=4500, hi=14000):
        S = np.fft.rfft(sig, axis=0); f = np.fft.rfftfreq(sig.shape[0], 1 / SR)
        m = (f >= lo) & (f <= hi)
        return 10 * np.log10(np.sum(np.abs(S[m]) ** 2) + 1e-20)

    y = deshimmer(x, SR, strength=1.0)
    red = band(x - clean) - band(y - clean)
    check("шиммер подавляется", red > 5.0, f"ушло {red:.1f} дБ")

    yc = deshimmer(clean, SR, strength=1.0)
    dmg = band(yc - clean) - band(clean)
    check("чистая музыка почти не тронута", dmg < -25.0, f"ущерб {dmg:+.1f} дБ к музыке")
    S = np.fft.rfft(yc - clean, axis=0); f = np.fft.rfftfreq(clean.shape[0], 1 / SR)
    lowmax = np.max(np.abs(S[f < 3500])) / np.max(np.abs(np.fft.rfft(clean, axis=0)[f < 3500]))
    check("низ ниже 3.5 кГц не тронут", lowmax < 1e-4, f"отн. изменение {lowmax:.1e}")

    a_clean, a_dirty = shimmer_amount(clean, SR), shimmer_amount(x, SR)
    check("оценка шиммера различает чистый и мерцающий трек", a_dirty > a_clean + 1.0,
          f"чистый {a_clean:.2f} дБ, с шиммером {a_dirty:.2f} дБ")


def main() -> int:
    print(f"Airband — самопроверка, {SR} Гц\n")
    test_loudness()
    test_limiter()
    test_normalize()
    test_restoration()
    test_auto_params()
    test_deshimmer()

    print()
    if fails:
        print(f"Провалено: {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("Всё прошло.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
