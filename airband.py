#!/usr/bin/env python3
"""Airband — восстановление срезанного верха в треках из Suno.

    python airband.py track.mp3
    python airband.py album/ -o mastered/ --album --target -14
    python airband.py track.wav --reference ref.flac --report
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

import audioio
from analysis import (average_spectrum, band_energy_db, band_reference,
                      detect_cutoff, loudness_lufs, mud_excess_db,
                      smooth_octave, stereo_width_ratio, to_db)
from master import album_offset, apply_offset, normalize
from restore import harmonic_air, match_reference, tone, widen


@dataclass
class Params:
    air: float = 0.70
    drive: float = 0.65
    shelf: float = 3.0
    mud: float = -2.5
    width: float = 0.35
    follow: bool = True


PRESETS = {
    "mp3-rescue": Params(air=0.75, drive=0.65, shelf=3.0, mud=-2.5, width=0.35),
    "wav-polish": Params(air=0.55, drive=0.45, shelf=2.0, mud=-1.5, width=0.25),
    "air-only":   Params(air=0.65, drive=0.50, shelf=2.5, mud=0.0,  width=0.0),
    "flat":       Params(air=0.0,  drive=0.0,  shelf=0.0, mud=0.0,  width=0.0),
}


def auto_params(x: np.ndarray, sr: int, cut: dict) -> Params:
    """Считает параметры из самого трека вместо готового набора чисел.

    Идея из oXygen (Master Assistant): проанализировать вход и написать
    настройки самому, а не заставлять человека угадывать пресет. Три вещи
    меряются по-настоящему, а не берутся с потолка:

    - крутизна обрыва (уже есть в detect_cutoff) — жёсткий MP3-срез тянет
      на агрессивное восстановление, мягкий WAV-скат — на бережное;
    - реальный избыток на 250–400 Гц против середины — чистка мути идёт
      только тогда, когда мути правда многовато, а не всегда на −2.5 дБ;
    - существующая стерео-ширина (RMS side/mid) — уже широкому треку
      досыпается меньше, почти моно — больше.
    """
    if cut["full_range"]:
        air = drive = shelf = 0.0
    else:
        steep = cut["steepness_db"]
        t = float(np.clip((steep - 25.0) / 65.0, 0.0, 1.0))
        air = 0.40 + 0.35 * t
        drive = 0.35 + 0.30 * t
        shelf = 1.5 + 1.5 * t

    f, p = average_spectrum(x, sr)
    db = to_db(smooth_octave(p, f, 1 / 12))
    excess = mud_excess_db(db, f)
    mud = -float(np.clip(excess * 0.6, 0.0, 4.0))

    width_now = stereo_width_ratio(x)
    width = float(np.clip(0.45 - 0.35 * width_now, 0.0, 0.5))

    return Params(air=air, drive=drive, shelf=shelf, mud=mud, width=width, follow=True)


# --------------------------------------------------------------------------

def analyse(x: np.ndarray, sr: int) -> dict:
    f, p = average_spectrum(x, sr)
    db = to_db(smooth_octave(p, f, 1 / 12))
    cut = detect_cutoff(db, f, sr)
    cut["_freqs"] = f
    cut["_db"] = db
    return cut


def restore(x: np.ndarray, sr: int, p: Params, cut: dict,
            reference: np.ndarray | None = None,
            ref_strength: float = 1.0) -> np.ndarray:
    y = tone(x, sr, p.mud, p.shelf)
    if p.air > 0 and not cut["full_range"]:
        y = y + harmonic_air(y, sr, cut["hz"], p.air, p.drive, follow=p.follow)
    y = widen(y, sr, p.width)
    if reference is not None:
        y = match_reference(y, sr, reference, strength=ref_strength)
    return y


def air_delta(before_db, before_f, after: np.ndarray, sr: int,
              cutoff: float) -> tuple[float, float]:
    """Прирост в полосе выше среза и её итоговый уровень
    относительно середины. Прирост сам по себе обманчив: если
    полоса была пустой, он уходит в десятки децибел и ничего
    не говорит о том, как это звучит."""
    fb, pb = average_spectrum(after, sr)
    db_ = to_db(smooth_octave(pb, fb, 1 / 12))
    top = sr / 2 * 0.97
    e_before = band_energy_db(before_db, before_f, cutoff, top)
    e_after = band_energy_db(db_, fb, cutoff, top)
    return e_after - e_before, e_after - band_reference(db_, fb)


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="airband",
        description="Восстановление срезанного верха в треках, сгенерированных в Suno.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  airband.py track.mp3\n"
            "  airband.py album/ -o mastered/ --album --target -14\n"
            "  airband.py track.wav --reference ref.flac --report\n"
        ),
    )
    ap.add_argument("inputs", nargs="+", help="файлы или папки")
    ap.add_argument("-o", "--out", default="out", help="куда класть результат (по умолчанию out/)")
    ap.add_argument("--preset", choices=sorted(PRESETS) + ["auto"], default="mp3-rescue",
                    help="auto — параметры считаются из самого трека (Master Assistant)")

    g = ap.add_argument_group("обработка")
    g.add_argument("--air", type=float, help="сколько верха достроить, 0..1.2 (1.0 — естественное продолжение спектра)")
    g.add_argument("--drive", type=float, help="плотность гармоник, 0..1")
    g.add_argument("--shelf", type=float, help="шельф воздуха от 11 кГц, дБ")
    g.add_argument("--mud", type=float, help="правка на 300 Гц, дБ (отрицательное — чистка)")
    g.add_argument("--width", type=float, help="ширина стерео выше 2.5 кГц, 0..1")
    g.add_argument("--no-follow", action="store_true",
                   help="не следить за огибающей, класть верх ровным слоем")
    g.add_argument("--cutoff", type=float, help="задать точку среза вручную, Гц")

    m = ap.add_argument_group("громкость")
    m.add_argument("--target", type=float, default=-11.0, help="целевая громкость, LUFS (по умолчанию -11)")
    m.add_argument("--ceiling", type=float, default=-1.0, help="потолок тру-пика, дБ (по умолчанию -1)")
    m.add_argument("--album", action="store_true",
                   help="общий сдвиг на весь альбом, относительные уровни сохраняются")

    r = ap.add_argument_group("эталон")
    r.add_argument("--reference", help="трек, под тональный баланс которого подгонять")
    r.add_argument("--ref-strength", type=float, default=1.0, help="0..1, насколько сильно подгонять")

    o = ap.add_argument_group("вывод")
    o.add_argument("--report", action="store_true", help="сохранить PNG со спектрами до и после")
    o.add_argument("--suffix", default=" (airband)", help="суффикс имени файла")
    o.add_argument("--analyze", action="store_true", help="только замерить, ничего не писать")
    o.add_argument("-q", "--quiet", action="store_true")
    return ap


def apply_overrides(p: Params, args) -> Params:
    for key in ("air", "drive", "shelf", "mud", "width"):
        v = getattr(args, key)
        if v is not None:
            setattr(p, key, v)
    if args.no_follow:
        p.follow = False
    return p


def resolve_params(args) -> Params | None:
    """None означает «auto» — параметры считаются позже, для каждого
    файла отдельно, а не один раз на весь запуск."""
    if args.preset == "auto":
        return None
    p = Params(**asdict(PRESETS[args.preset]))
    return apply_overrides(p, args)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    say = (lambda *a: None) if args.quiet else (lambda *a: print(*a, flush=True))

    try:
        files = audioio.collect(args.inputs)
    except audioio.AudioError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    if not files:
        print("Ошибка: не нашёл ни одного аудиофайла.", file=sys.stderr)
        return 2

    params = resolve_params(args)
    out_dir = Path(args.out)

    reference = None
    if args.reference:
        reference, _ = audioio.load(args.reference)
        say(f"Эталон: {Path(args.reference).name}")

    say(f"Пресет {args.preset}, цель {args.target:+.1f} LUFS, потолок {args.ceiling:+.1f} дБ")
    say(f"Файлов: {len(files)}\n")

    stash = tempfile.TemporaryDirectory(prefix="airband-") if args.album else None
    pending: list[dict] = []

    for i, path in enumerate(files, 1):
        say(f"[{i}/{len(files)}] {path.name}")
        try:
            x, sr = audioio.load(path)
        except audioio.AudioError as e:
            say(f"    пропускаю: {e}")
            continue

        if x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)

        cut = analyse(x, sr)
        if args.cutoff:
            cut["hz"], cut["full_range"] = args.cutoff, False

        if cut["full_range"]:
            say("    обрыва нет, спектр полный — досинтез пропускается")
        else:
            say(f"    срез на {cut['hz'] / 1000:.2f} кГц, перепад {cut['steepness_db']:.0f} дБ")

        lufs_in = loudness_lufs(x, sr)

        if args.analyze:
            say(f"    громкость {lufs_in:+.1f} LUFS\n")
            continue

        file_params = params
        if file_params is None:
            file_params = apply_overrides(auto_params(x, sr, cut), args)
            say(f"    авто: воздух {file_params.air:.2f}, драйв {file_params.drive:.2f}, "
                f"шельф {file_params.shelf:+.1f} дБ, муть {file_params.mud:+.1f} дБ, "
                f"ширина {file_params.width:.2f}")

        y = restore(x, sr, file_params, cut, reference, args.ref_strength)
        if not cut["full_range"]:
            delta, level = air_delta(cut["_db"], cut["_freqs"], y, sr, cut["hz"])
            if delta > 40:
                say(f"    полоса выше среза была пустой, теперь {level:+.0f} дБ "
                    f"относительно середины")
            else:
                say(f"    выше среза добавлено {delta:+.1f} дБ, "
                    f"уровень {level:+.0f} дБ относительно середины")

        if args.album:
            raw_lufs = loudness_lufs(y, sr)
            tmp = Path(stash.name) / f"{i:04d}.npy"
            np.save(tmp, y.astype(np.float32))
            pending.append({"path": path, "tmp": tmp, "lufs": raw_lufs,
                            "sr": sr, "cut": cut["hz"], "orig": None})
            say(f"    громкость {lufs_in:+.1f} → {raw_lufs:+.1f} LUFS, жду альбом\n")
            if args.report:
                pending[-1]["orig"] = x.astype(np.float32)
            continue

        y, stats = normalize(y, sr, args.target, args.ceiling)
        dest = out_dir / f"{path.stem}{args.suffix}.wav"
        audioio.write_wav24(dest, y, sr)
        say(f"    громкость {stats['lufs_before']:+.1f} → {stats['lufs_after']:+.1f} LUFS, "
            f"пик {stats['true_peak']:+.2f} дБ")
        say(f"    {dest}")

        if args.report:
            from report import spectrum_png
            png = out_dir / f"{path.stem}{args.suffix}.png"
            if spectrum_png(x, y, sr, cut["hz"], png, title=path.stem):
                say(f"    {png}")
            else:
                say("    отчёт пропущен: нет matplotlib")
        say("")

    if args.album and pending:
        offset = album_offset([t["lufs"] for t in pending], args.target)

        # Лимитер срезает часть прибавки, поэтому сдвиг уточняется
        # пробным прогоном самого громкого трека.
        loudest = max(pending, key=lambda t: t["lufs"])
        probe = np.load(loudest["tmp"]).astype(np.float64)
        _, pstat = apply_offset(probe, loudest["sr"], offset, args.ceiling)
        shortfall = args.target - pstat["lufs_after"]
        if abs(shortfall) > 0.1:
            offset += shortfall
        del probe

        say(f"Альбомный сдвиг: {offset:+.2f} дБ\n")
        for t in pending:
            y = np.load(t["tmp"]).astype(np.float64)
            y, stats = apply_offset(y, t["sr"], offset, args.ceiling)
            dest = out_dir / f"{t['path'].stem}{args.suffix}.wav"
            audioio.write_wav24(dest, y, t["sr"])
            say(f"{t['path'].name}: {stats['lufs_before']:+.1f} → {stats['lufs_after']:+.1f} LUFS, "
                f"пик {stats['true_peak']:+.2f} дБ")
            if args.report and t["orig"] is not None:
                from report import spectrum_png
                png = out_dir / f"{t['path'].stem}{args.suffix}.png"
                spectrum_png(t["orig"].astype(np.float64), y, t["sr"], t["cut"], png,
                             title=t["path"].stem)

    if stash:
        stash.cleanup()
    if not args.analyze:
        say(f"\nГотово: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
