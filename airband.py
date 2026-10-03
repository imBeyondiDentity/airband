#!/usr/bin/env python3
"""Airband — restoring the top end cut from tracks generated in Suno.

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
from deshimmer import deshimmer, shimmer_amount


@dataclass
class Params:
    air: float = 0.70
    drive: float = 0.65
    shelf: float = 3.0
    mud: float = -2.5
    width: float = 0.35
    follow: bool = True
    deshimmer: float = 0.6


PRESETS = {
    "mp3-rescue": Params(air=0.75, drive=0.65, shelf=3.0, mud=-2.5, width=0.35, deshimmer=0.6),
    "wav-polish": Params(air=0.55, drive=0.45, shelf=2.0, mud=-1.5, width=0.25, deshimmer=0.5),
    "air-only":   Params(air=0.65, drive=0.50, shelf=2.5, mud=0.0,  width=0.0,  deshimmer=0.5),
    "flat":       Params(air=0.0,  drive=0.0,  shelf=0.0, mud=0.0,  width=0.0,  deshimmer=0.0),
}


def auto_params(x: np.ndarray, sr: int, cut: dict) -> Params:
    """Works out the parameters from the track itself rather than from a ready-made set of numbers.

    The idea is from oXygen (Master Assistant): analyse the input and write the
    settings yourself, rather than make a person guess a preset. Three things
    are actually measured rather than plucked out of thin air:

    - cutoff steepness (already in detect_cutoff) — a hard MP3 cliff calls
      for aggressive restoration, a soft WAV rolloff for a gentle one;
    - the real excess at 250–400 Hz against the mids — mud is cleaned only
      when there's genuinely quite a lot of it, not always at −2.5 dB;
    - the existing stereo width (RMS side/mid) — an already wide track
      gets less added, a near-mono one gets more.
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

    # Shimmer cleanup by the measured amount: how much of the band's energy the
    # de-shimmer would have removed at full strength. A clean track gets only a
    # light safety pass.
    amt = shimmer_amount(x, sr, None if cut["full_range"] else cut["hz"])
    desh = float(np.clip(0.3 + 0.25 * amt, 0.3, 0.8))

    return Params(air=air, drive=drive, shelf=shelf, mud=mud, width=width,
                  follow=True, deshimmer=desh)


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
    # Clean first, rebuild second: the exciter draws on the same band where the
    # shimmer lives, and without cleaning would build new harmonics out of it.
    # The dry path is cleaned at the chosen strength, the exciter's feed at twice
    # that (capped at 1.0): the exciter needs only the band's musical structure,
    # not its "beauty". In testing that's another −1.1 dB of debris in the air band.
    c = None if cut["full_range"] else cut["hz"]
    feed = x
    if p.deshimmer > 0:
        feed_s = min(1.0, 2 * p.deshimmer)
        feed = deshimmer(x, sr, strength=feed_s, cutoff=c)
        x = feed if feed_s == p.deshimmer else deshimmer(x, sr, strength=p.deshimmer, cutoff=c)
    y = tone(x, sr, p.mud, p.shelf)
    if p.air > 0 and not cut["full_range"]:
        src = y if feed is x else tone(feed, sr, p.mud, p.shelf)
        y = y + harmonic_air(src, sr, cut["hz"], p.air, p.drive, follow=p.follow)
    y = widen(y, sr, p.width)
    if reference is not None:
        y = match_reference(y, sr, reference, strength=ref_strength)
    return y


def air_delta(before_db, before_f, after: np.ndarray, sr: int,
              cutoff: float) -> tuple[float, float]:
    """The gain in the band above the cutoff and its final level
    relative to the mids. The gain on its own is misleading: if the
    band was empty, it runs to tens of decibels and says nothing
    about how it sounds."""
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
        description="Restoring the top end cut from tracks generated in Suno.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  airband.py track.mp3\n"
            "  airband.py album/ -o mastered/ --album --target -14\n"
            "  airband.py track.wav --reference ref.flac --report\n"
        ),
    )
    ap.add_argument("inputs", nargs="+", help="files or folders")
    ap.add_argument("-o", "--out", default="out", help="where to put the results (default: out/)")
    ap.add_argument("--preset", choices=sorted(PRESETS) + ["auto"], default="mp3-rescue",
                    help="auto — parameters are worked out from the track itself (Master Assistant)")

    g = ap.add_argument_group("processing")
    g.add_argument("--air", type=float, help="how much top end to rebuild, 0..1.2 (1.0 is the natural continuation of the spectrum)")
    g.add_argument("--drive", type=float, help="harmonic density, 0..1")
    g.add_argument("--shelf", type=float, help="air shelf from 11 kHz, dB")
    g.add_argument("--mud", type=float, help="adjustment at 300 Hz, dB (negative cuts)")
    g.add_argument("--width", type=float, help="stereo width above 2.5 kHz, 0..1")
    g.add_argument("--deshimmer", type=float,
                   help="Suno shimmer cleanup before resynthesis, 0..1 (0 — off)")
    g.add_argument("--no-follow", action="store_true",
                   help="don't follow the envelope, lay the top end down as a flat layer")
    g.add_argument("--cutoff", type=float, help="set the cutoff point by hand, Hz")

    m = ap.add_argument_group("loudness")
    m.add_argument("--target", type=float, default=-11.0, help="target loudness, LUFS (default -11)")
    m.add_argument("--ceiling", type=float, default=-1.0, help="true-peak ceiling, dB (default -1)")
    m.add_argument("--album", action="store_true",
                   help="one shared offset for the whole album, relative levels are kept")

    r = ap.add_argument_group("reference")
    r.add_argument("--reference", help="a track whose tonal balance to match")
    r.add_argument("--ref-strength", type=float, default=1.0, help="0..1, how strongly to match")

    o = ap.add_argument_group("output")
    o.add_argument("--report", action="store_true", help="save a PNG of the spectra before and after")
    o.add_argument("--suffix", default=" (airband)", help="file name suffix")
    o.add_argument("--analyze", action="store_true", help="measure only, write nothing")
    o.add_argument("-q", "--quiet", action="store_true")
    return ap


def apply_overrides(p: Params, args) -> Params:
    for key in ("air", "drive", "shelf", "mud", "width", "deshimmer"):
        v = getattr(args, key)
        if v is not None:
            setattr(p, key, v)
    if args.no_follow:
        p.follow = False
    return p


def resolve_params(args) -> Params | None:
    """None means "auto" — the parameters are worked out later, for each
    file separately, rather than once for the whole run."""
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
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if not files:
        print("Error: no audio files found.", file=sys.stderr)
        return 2

    params = resolve_params(args)
    out_dir = Path(args.out)

    reference = None
    if args.reference:
        reference, _ = audioio.load(args.reference)
        say(f"Reference: {Path(args.reference).name}")

    say(f"Preset {args.preset}, target {args.target:+.1f} LUFS, ceiling {args.ceiling:+.1f} dB")
    say(f"Files: {len(files)}\n")

    stash = tempfile.TemporaryDirectory(prefix="airband-") if args.album else None
    pending: list[dict] = []

    for i, path in enumerate(files, 1):
        say(f"[{i}/{len(files)}] {path.name}")
        try:
            x, sr = audioio.load(path)
        except audioio.AudioError as e:
            say(f"    skipping: {e}")
            continue

        if x.shape[1] == 1:
            x = np.repeat(x, 2, axis=1)

        cut = analyse(x, sr)
        if args.cutoff:
            cut["hz"], cut["full_range"] = args.cutoff, False

        if cut["full_range"]:
            say("    no cutoff, the spectrum is full — resynthesis skipped")
        else:
            say(f"    cutoff at {cut['hz'] / 1000:.2f} kHz, drop of {cut['steepness_db']:.0f} dB")

        lufs_in = loudness_lufs(x, sr)

        if args.analyze:
            say(f"    loudness {lufs_in:+.1f} LUFS\n")
            continue

        file_params = params
        if file_params is None:
            file_params = apply_overrides(auto_params(x, sr, cut), args)
            say(f"    auto: air {file_params.air:.2f}, drive {file_params.drive:.2f}, "
                f"shelf {file_params.shelf:+.1f} dB, mud {file_params.mud:+.1f} dB, "
                f"width {file_params.width:.2f}, de-shimmer {file_params.deshimmer:.2f}")

        y = restore(x, sr, file_params, cut, reference, args.ref_strength)
        if not cut["full_range"]:
            delta, level = air_delta(cut["_db"], cut["_freqs"], y, sr, cut["hz"])
            if delta > 40:
                say(f"    the band above the cutoff was empty, now {level:+.0f} dB "
                    f"relative to the mids")
            else:
                say(f"    {delta:+.1f} dB added above the cutoff, "
                    f"level {level:+.0f} dB relative to the mids")

        if args.album:
            raw_lufs = loudness_lufs(y, sr)
            tmp = Path(stash.name) / f"{i:04d}.npy"
            np.save(tmp, y.astype(np.float32))
            pending.append({"path": path, "tmp": tmp, "lufs": raw_lufs,
                            "sr": sr, "cut": cut["hz"], "orig": None})
            say(f"    loudness {lufs_in:+.1f} → {raw_lufs:+.1f} LUFS, waiting for the album\n")
            if args.report:
                pending[-1]["orig"] = x.astype(np.float32)
            continue

        y, stats = normalize(y, sr, args.target, args.ceiling)
        dest = out_dir / f"{path.stem}{args.suffix}.wav"
        audioio.write_wav24(dest, y, sr)
        say(f"    loudness {stats['lufs_before']:+.1f} → {stats['lufs_after']:+.1f} LUFS, "
            f"peak {stats['true_peak']:+.2f} dB")
        say(f"    {dest}")

        if args.report:
            from report import spectrum_png
            png = out_dir / f"{path.stem}{args.suffix}.png"
            if spectrum_png(x, y, sr, cut["hz"], png, title=path.stem):
                say(f"    {png}")
            else:
                say("    report skipped: matplotlib isn't installed")
        say("")

    if args.album and pending:
        offset = album_offset([t["lufs"] for t in pending], args.target)

        # The limiter takes off part of the gain, so the offset is refined
        # with a trial run of the loudest track.
        loudest = max(pending, key=lambda t: t["lufs"])
        probe = np.load(loudest["tmp"]).astype(np.float64)
        _, pstat = apply_offset(probe, loudest["sr"], offset, args.ceiling)
        shortfall = args.target - pstat["lufs_after"]
        if abs(shortfall) > 0.1:
            offset += shortfall
        del probe

        say(f"Album offset: {offset:+.2f} dB\n")
        for t in pending:
            y = np.load(t["tmp"]).astype(np.float64)
            y, stats = apply_offset(y, t["sr"], offset, args.ceiling)
            dest = out_dir / f"{t['path'].stem}{args.suffix}.wav"
            audioio.write_wav24(dest, y, t["sr"])
            say(f"{t['path'].name}: {stats['lufs_before']:+.1f} → {stats['lufs_after']:+.1f} LUFS, "
                f"peak {stats['true_peak']:+.2f} dB")
            if args.report and t["orig"] is not None:
                from report import spectrum_png
                png = out_dir / f"{t['path'].stem}{args.suffix}.png"
                spectrum_png(t["orig"].astype(np.float64), y, t["sr"], t["cut"], png,
                             title=t["path"].stem)

    if stash:
        stash.cleanup()
    if not args.analyze:
        say(f"\nDone: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
