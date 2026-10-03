# Airband for the command line

The local version. It does the same job as the browser one, more precisely, and covers what the browser version doesn't: matching to a reference track, album-wide normalisation, batch processing of whole folders, and cleaning up Suno's shimmer.

## Installation

```
pip install numpy scipy
```

That's it. Everything else is optional:

- `soundfile` — reading files without ffmpeg
- `matplotlib` — for the `--report` switch

If neither `soundfile` nor ffmpeg is installed, there's nothing to read files with. Installing ffmpeg:

```
brew install ffmpeg      # macOS
apt install ffmpeg       # Debian, Ubuntu
winget install ffmpeg    # Windows
```

The 24-bit WAV writer is pure numpy, so exporting never needs a third-party library.

## Usage

A single track:

```
python airband.py track.mp3
```

The result lands in `out/track (airband).wav`.

A whole album at a shared loudness:

```
python airband.py album/ -o mastered/ --album --target -14
```

Matched to a reference track's tonal balance, with a spectrum image:

```
python airband.py track.wav --reference favourite_track.flac --report
```

Just measure the cutoff and loudness, without writing anything:

```
python airband.py album/ --analyze
```

## Options

| Option | What it does |
|---|---|
| `--preset` | `auto`, `mp3-rescue`, `wav-polish`, `air-only`, `flat` |
| `--air` | how much top end to rebuild; 1.0 is the natural continuation of the spectrum |
| `--drive` | harmonic density, 0..1 |
| `--shelf` | air shelf from 11 kHz, dB |
| `--mud` | adjustment at 300 Hz, dB |
| `--width` | stereo width above 2.5 kHz, 0..1 |
| `--deshimmer` | Suno shimmer cleanup before resynthesis, 0..1 (0 — off) |
| `--no-follow` | don't follow the envelope; lay the top end down as a flat layer |
| `--cutoff` | set the cutoff point by hand, Hz |
| `--target` | target loudness, LUFS |
| `--ceiling` | true-peak ceiling, dB |
| `--album` | one shared offset for the whole album |
| `--reference` | reference track for tonal balance |
| `--ref-strength` | 0..1, how strongly to match |
| `--report` | PNG of the spectra before and after |
| `--analyze` | measurement only |

## What's inside

Envelope following and the FIR filter on the exciter's output are now in the browser version too — it has caught up with this one almost entirely on top-end restoration quality. What remains exclusive to this version: an FIR filter on the exciter's input as well, its own oversampling for the saturation stage, reference matching, album mode, an 8× final peak check, and the de-shimmer (still being ported to the browser).

**Envelope following.** The spectral slope is measured across two bands below the cutoff and extrapolated above it. That gives the level the material would have had if it hadn't been cut off — and the new top end is set to exactly that, frame by frame. The air breathes with the music rather than sitting as a flat, hissy layer. Switch it off with `--no-follow`.

On a synthetic test where the top end is cut at 16 kHz, the restored spectrum stays within 2.2 dB of the pre-codec original across the whole 17–21 kHz band. You can check this yourself: `python selftest.py`.

**Linear-phase filters.** Bands are split with FIR filters rather than biquads. The top end doesn't smear in time, and cymbal transients stay sharp.

**Honest oversampling.** Saturation is computed at 4× the sample rate through scipy's polyphase filters — aliasing never reaches the audible range, even at maximum drive.

**Reference matching.** `--reference` takes the ratio of the two spectra smoothed to 1/6 of an octave, subtracts the average level across 200–2000 Hz (so it corrects the shape, not the loudness), caps the correction at six decibels, and applies it through a linear-phase filter. It's reference-based mastering without a separate library.

**One palette.** The PNG report (`--report`) uses the same colour tokens as the browser version and iDentity Prompt Engine: a warm near-black background, muted grey for the "before" curve, the orange accent for "after". Open the report next to the browser tool and there's no guessing which is which.

**Album mode.** Ordinary normalisation levels each track on its own and flattens an album's dynamics: a quiet interlude ends up as loud as the heaviest track. `--album` finds one shared offset, brings the loudest track up to target, and leaves the rest in their original relationship.

**Hitting the target precisely.** The limiter itself reduces loudness, so a single pass isn't enough. Normalisation is refined iteratively, to within 0.1 dB.

**Master Assistant (`--preset auto`).** Instead of a fixed set of numbers, the parameters are worked out from the track itself:

- cutoff steepness (already measured by the cutoff detector) sets how aggressive the restoration is — a hard MP3 cliff gets strong resynthesis, a soft WAV rolloff gets a gentle one, and if there's no cutoff at all, resynthesis is switched off entirely rather than mixed in blind;
- the real excess at 250–400 Hz relative to the mid band (600–2500 Hz) decides whether to clean up mud, and by how much — previously this was a fixed −2.5 dB whether there was any mud or not;
- the existing stereo width (RMS side/mid) decides how much more width to add — less for an already wide track, more for a near-mono one;
- the measured amount of shimmer sets the de-shimmer strength — a light safety pass for a clean track, stronger for a flickering one.

The idea comes from a survey of open-source mastering tools, specifically the Master Assistant in the [oXygen](https://github.com/Wamphyre/oXygen) plugin: it listens to the input and writes its own module settings rather than asking you to guess a preset.

**De-shimmer before the exciter.** Suno leaves narrow, flickering artefacts — "shimmer" — in roughly the 5–14 kHz range. Airband's exciter draws on exactly that range, so without a clean-up it would build new harmonics out of the artefacts and push them up into the air band. Now it cleans first and resynthesises second. How it works: an STFT, with a baseline for each frame taken as the median across neighbouring frequencies; any outlier above the threshold is brought down to the surrounding floor. Only what **flickers** is suppressed — a shimmer bin jumps by 10–20 dB from frame to frame, while an instrument's note decays smoothly. Nothing below 4.5 kHz is touched at all, the centre of the mix is cleaned more gently than the sides, and transients and broadband events are left alone. The exciter's feed is cleaned twice as hard as the dry path (capped at 1.0).

This is an original implementation; no code from other projects was used. The ideas were checked against the public descriptions of deshimmer (median across frequency, a threshold, protection of broadband events) and Shimmer (clean first, master second; leave the low end alone; treat the centre more gently than the sides).

Figures from a synthetic test (shimmer added to clean material containing a melody with overtones up to 13 kHz): artefacts at the input are 6.7 dB quieter, damage to clean music is −28 dB, the low end is untouched. Most importantly, in the air band after the exciter, shimmer-derived debris used to sit 6.2 dB below the music; now it sits 9.8 dB below. What remains comes from the nonlinear mixing of music and artefacts inside the saturation stage, which can't be cleaned out this way. For a track with no shimmer, the air band changes by 0.06 dB.

**A limiter with a hold stage.** Checked against the Hyrax limiter from [Matchering](https://github.com/sergree/matchering). Theirs holds the gain down for a while after a peak before it starts releasing — which stops the limiter "breathing" too quickly on transient material (drums, percussion). There used to be only a lookahead stage here, with no hold. Both have now been added: a hold (~40 ms by default), and a mathematical guarantee that the smoothed gain never exceeds what's actually required at that instant — previously the only safeguard there was a blunt `clip()` after the fact. On a single-transient test, the hard clip fires on 0 samples out of 288,000 (previously this wasn't checked at all).

**An honest peak ceiling.** The limiter's final check runs at 8× oversampling rather than 4×: an independent check against a 16× reference showed that 4× under-reads peaks right at the top of the frequency range — which is exactly where Airband creates content. A 0.15 dB margin covers what's left. By the reference, the output holds at −1.13 to −1.15 dBTP against a −1 ceiling.

## Files

```
airband.py     argument parsing, the pipeline, auto parameters (Master Assistant)
audioio.py     reading via soundfile or ffmpeg, writing 24-bit WAV
analysis.py    spectrum, cutoff detector, BS.1770-4 loudness, true peak, mud, stereo width
restore.py     top-end resynthesis, EQ, stereo, reference matching
deshimmer.py   Suno shimmer clean-up before resynthesis
master.py      lookahead limiter with a hold stage, normalisation, album offset
report.py      the spectrum image
selftest.py    the DSP self-test
```

## Self-test

```
python selftest.py
```

Checks the loudness meter's calibration against the standard's reference, linearity, the limiter and its hold stage, normalisation accuracy, the cutoff detector, restoration quality, the auto parameters, and the de-shimmer (suppression, damage to clean music, an untouched low end). Run it after any change to the DSP.

## Worth knowing

- You can't get back what was never there. The harmonics are a plausible reconstruction, not the lost recording.
- Everything is processed at 48 kHz. For Suno material that's deliberate: above a 16 kHz cutoff it leaves eight kilohertz of room for the harmonics.
- Speed is about 0.4× real time: a four-minute track takes roughly a minute and a half (measured on a single core). Peak memory on a track that length is about 2 GB. Long tracks are processed in chunks, so memory doesn't multiply with track length.
- In album mode, processed tracks sit temporarily in the system's temp folder. A ten-track album takes about two gigabytes there, and it's all deleted automatically afterwards.
- If the cymbals start to hiss, turn `--drive` down before `--air`. Drive controls how dirty the harmonics get; `--air` only controls their level.
