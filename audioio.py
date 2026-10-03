"""Reading and writing audio.

soundfile is used if it's installed, otherwise ffmpeg.
The 24-bit WAV writer is pure numpy, so exporting needs no
third-party libraries at all.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

WORK_SR = 48000

AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma"}


class AudioError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def _read_soundfile(path: Path):
    try:
        import soundfile as sf
    except ImportError:
        return None
    try:
        data, sr = sf.read(str(path), always_2d=True, dtype="float64")
    except Exception:
        return None
    return data, sr


def _ffprobe_channels(path: Path) -> int:
    if not shutil.which("ffprobe"):
        return 2
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "a:0", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
        info = json.loads(out)
        return int(info["streams"][0].get("channels", 2))
    except Exception:
        return 2


def _read_ffmpeg(path: Path, sr: int):
    if not shutil.which("ffmpeg"):
        raise AudioError(
            "ffmpeg or the soundfile package is needed to read this file.\n"
            "  brew install ffmpeg   |   apt install ffmpeg   |   pip install soundfile"
        )
    ch = _ffprobe_channels(path)
    ch = 2 if ch > 2 else ch
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-f", "f32le", "-acodec", "pcm_f32le",
         "-ac", str(ch), "-ar", str(sr), "-"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise AudioError(f"ffmpeg could not read {path.name}: {msg[-1] if msg else 'empty output'}")
    data = np.frombuffer(proc.stdout, dtype="<f4").astype(np.float64)
    return data.reshape(-1, ch), sr


def load(path: str | Path, sr: int = WORK_SR) -> tuple[np.ndarray, int]:
    """Return (samples [n, ch] as float64, sample rate).

    Everything is brought to the working rate. For Suno material this is a
    deliberate upsample: above a 16 kHz cutoff it leaves room
    for the resynthesised harmonics.
    """
    path = Path(path)
    if not path.exists():
        raise AudioError(f"No such file: {path}")

    got = _read_soundfile(path)
    if got is None:
        return _read_ffmpeg(path, sr)

    data, src_sr = got
    if src_sr != sr:
        g = np.gcd(int(src_sr), int(sr))
        data = resample_poly(data, sr // g, src_sr // g, axis=0)
    return np.ascontiguousarray(data, dtype=np.float64), sr


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def write_wav24(path: str | Path, x: np.ndarray, sr: int, dither: bool = True) -> None:
    """24-bit WAV with TPDF dither. numpy only."""
    x = np.atleast_2d(x)
    if x.shape[0] < x.shape[1]:
        x = x.T
    n, ch = x.shape

    q = 2 ** 23 - 1
    y = x.copy()
    if dither:
        rng = np.random.default_rng()
        y += (rng.random(y.shape) + rng.random(y.shape) - 1.0) / q
    np.clip(y, -1.0, 1.0, out=y)

    xi = np.rint(y * q).astype("<i4")
    np.clip(xi, -q - 1, q, out=xi)
    raw = xi.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()

    header = b"RIFF" + struct.pack("<I", 36 + len(raw)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, ch, sr, sr * ch * 3, ch * 3, 24)
    header += b"data" + struct.pack("<I", len(raw))

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(header)
        f.write(raw)


# --------------------------------------------------------------------------
# finding files
# --------------------------------------------------------------------------

def collect(inputs: list[str]) -> list[Path]:
    found: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            found += sorted(q for q in p.rglob("*") if q.suffix.lower() in AUDIO_EXT)
        elif p.is_file():
            found.append(p)
        else:
            raise AudioError(f"Not found: {item}")
    seen, out = set(), []
    for p in found:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            out.append(p)
    return out
