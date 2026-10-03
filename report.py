"""An image of the spectra before and after. matplotlib is optional.

The palette is the same set of tokens as in the browser version of Airband and
in iDentity Prompt Engine (Music DNA): a warm near-black background,
muted grey for "before", an orange accent for "after".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from analysis import average_spectrum, band_reference, smooth_octave, to_db

BG = "#0F1313"
PANEL = "#151A1D"
LINE = "#232019"
SPINE = "#3A362E"
ACCENT = "#FF7F44"
MUTED = "#B7B0A7"
DIM = "#6E695E"
TEXT = "#E8E6E3"

# DejaVu Sans Mono — the closest monospace font to JetBrains Mono
# that's actually available in the environment.
MONO = ["DejaVu Sans Mono", "monospace"]


def spectrum_png(before: np.ndarray, after: np.ndarray, sr: int,
                 cutoff: float, path: str | Path, title: str = "") -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    plt.rcParams["font.family"] = MONO

    fa, pa = average_spectrum(before, sr)
    fb, pb = average_spectrum(after, sr)
    da = to_db(smooth_octave(pa, fa, 1 / 12))
    db_ = to_db(smooth_octave(pb, fb, 1 / 12))
    da -= band_reference(da, fa)
    db_ -= band_reference(db_, fb)

    fig, ax = plt.subplots(figsize=(11, 4.4), dpi=130)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)

    m = fa >= 30
    ax.fill_between(fa[m], da[m], -90, color=MUTED, alpha=0.10)
    ax.plot(fa[m], da[m], color=MUTED, lw=1.3, label="before")
    ax.plot(fb[m], db_[m], color=ACCENT, lw=1.8, label="after")
    ax.axvline(cutoff, color=ACCENT, ls="--", lw=1, alpha=0.55)
    ax.annotate(f"cutoff {cutoff / 1000:.1f} kHz", (cutoff, 2),
                color=ACCENT, fontsize=9, xytext=(6, 0),
                textcoords="offset points")

    ax.set_xscale("log")
    ax.set_xlim(30, sr / 2)
    ax.set_ylim(-84, 8)
    ax.set_xticks([100, 1000, 5000, 10000, 15000, 20000])
    ax.set_xticklabels(["100", "1k", "5k", "10k", "15k", "20k"])
    ax.set_xlabel("Hz", color=DIM, fontsize=10)
    ax.set_ylabel("dB relative to 1–5 kHz", color=DIM, fontsize=10)
    if title:
        ax.set_title(title, color=TEXT, fontsize=12, loc="left", fontweight="medium")

    for s in ax.spines.values():
        s.set_color(SPINE)
    ax.tick_params(colors=DIM, labelsize=9)
    ax.grid(True, which="both", color=LINE, lw=0.7)
    leg = ax.legend(frameon=False, labelcolor=DIM, fontsize=9, loc="lower left")
    for t in leg.get_texts():
        t.set_color(DIM)

    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return True
