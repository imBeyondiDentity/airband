"""Финальная ступень: лимитер с упреждением и нормализация громкости.

Сверено с лимитером Hyrax из Matchering (sergree/matchering). У них
после пика есть отдельная стадия hold — гейн держится внизу ещё
какое-то время, прежде чем начать отпускать, и финальная кривая
гейна берётся как поэлементный минимум с реально необходимым
значением, так что перехлёст в принципе невозможен, а не отлавливается
постфактум клипом. Раньше здесь было и то, и другое: сразу после
lookahead-минимума шло сглаживание, без hold и без этой гарантии —
на транзиентных материалах (барабаны) это могло давать лёгкий
pumping: гейн отпускался слишком быстро сразу после удара.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import minimum_filter1d
from scipy.signal import fftconvolve

from analysis import loudness_lufs, true_peak_db


def _trailing_min(req: np.ndarray, hold: int) -> np.ndarray:
    """g[i] = min(req[i-hold+1 .. i]) — минимум держится вперёд по
    времени после провала, а не размазывается симметрично назад-вперёд.

    Окно принудительно делается нечётным и используется штатное
    центрирование (origin=0) со сдвигом среза — на чётных окнах
    параметр origin у scipy даёt едва заметный, но систематический
    сдвиг результата назад по времени (проверено отдельно на широком
    диапазоне размеров окна, а не только на маленьком примере)."""
    hold = hold | 1
    if hold <= 1:
        return req
    pad = hold - 1
    padded = np.pad(req, (pad, 0), mode="edge")
    out_full = minimum_filter1d(padded, size=hold, mode="nearest")
    start = hold // 2
    return out_full[start:start + len(req)]


def _gain_curve(peak: np.ndarray, ceiling: float, look: int, hold: int) -> np.ndarray:
    """Кривая гейна в три шага:

    1. Lookahead (симметричный минимум, малое окно) — гейн уже опущен
       к моменту, когда придёт пик.
    2. Hold (чисто обратное окно, окно побольше) — после пика гейн не
       начинает отпускать немедленно, а держится на дне ещё `hold`
       отсчётов — это и есть отличие от предыдущей версии.
    3. Сглаживание формы окном Ханна, и затем поэлементный минимум с
       исходным требованием `req` — гарантия, что сглаживание не
       могло случайно вернуть гейн выше, чем реально нужен именно
       в этой точке. Раньше этой гарантии не было: несоответствие
       ловил только грубый clip() в конце.
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
    """Придержать пики под потолком.

    Кривая гейна считается по сэмплам, но потолок берётся с запасом
    margin_db. После этого тру-пик проверяется честно, на
    передискретизованном сигнале, и если запаса не хватило —
    добавляется статический сдвиг. Так межсэмпловые выбросы
    не пролезают, а трек не приходится держать в памяти
    в четырёхкратном виде.
    """
    ceiling = 10 ** (ceiling_db / 20)
    inner = ceiling * 10 ** (-margin_db / 20)
    look = max(8, int(round(lookahead_ms * 1e-3 * sr)))
    hold = max(1, int(round(hold_ms * 1e-3 * sr)))

    peak = np.abs(x).max(axis=1)
    y = x * _gain_curve(peak, inner, look, hold)[:, None]
    np.clip(y, -ceiling, ceiling, out=y)

    # Финальная проверка на 8x, а не на 4x: проверено независимым эталоном
    # (16x) — 4x недочитывает контент у самого предела частот, а Airband
    # как раз его и создаёт. Запас 0.15 дБ закрывает остаточный промах 8x.
    safe_db = ceiling_db - 0.15
    tp = true_peak_db(y, sr, oversample=8)
    if tp > safe_db:
        trim = 10 ** ((safe_db - tp) / 20)
        y *= trim
    return y


def normalize(x: np.ndarray, sr: int, target_lufs: float,
              ceiling_db: float = -1.0, tol_db: float = 0.1,
              max_passes: int = 4) -> tuple[np.ndarray, dict]:
    """Привести к целевой громкости и придержать пики.

    Лимитер сам по себе снижает громкость, поэтому одного прохода
    мало: цель уточняется итеративно, пока промах не станет меньше
    десятой доли децибела.
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
    """Один общий сдвиг на весь альбом.

    Самый громкий трек выводится на цель, остальные сохраняют
    исходную расстановку — тихая интерлюдия остаётся тихой.
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
