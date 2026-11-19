# Airband

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Русская версия](ABOUT_ru.md)

A browser tool for restoring the top end cut from tracks generated in Suno.

Runs entirely client-side via the Web Audio API. No backend, no uploads — files never leave the device. Deploys to GitHub Pages as static files.

## Why

Suno hands back material with a hard spectral cliff: around 15.5–16 kHz for MP3, a touch higher for WAV. There's no signal at all above that line, so a regular EQ can't help — it just raises the level where there's nothing to raise, pulling up codec noise instead.

Airband takes a different route: it takes the band right under the cliff, runs it through gentle asymmetric saturation, and gets second and third harmonics out of it. Those land exactly in the empty zone. Everything that fell below the cutoff point gets filtered out of that new material, and what's left gets mixed back into the original. Real energy appears in the top end, correlated with the source signal, rather than a raised noise floor.

## What it does

- Finds the cutoff point automatically, from the spectrum of the whole track rather than a single window
- Resynthesises harmonics above it (adjustable amount and density)
- An "air" shelf from 11 kHz
- Low-mid cleanup at 300 Hz
- Stereo widening above 2.5 kHz only, in mid/side — everything below 2.5 kHz is left exactly as it was
- Optional compressor glue
- Reference matching: drop in a track you like and the tonal balance follows it
- Multiband compression, mono bass below 120 Hz and a soft clipper ahead of the limiter, all off until you ask for them
- Loudness measurement per ITU-R BS.1770-4 with gating, normalised to a target
- A 2 ms lookahead limiter with a 40 ms hold stage, −1 dB ceiling (−1.5 dB when the file is going to MP3/AAC)
- 24-bit WAV export with TPDF dithering
- Batch processing: drop a whole album in, get everything back at matching loudness
- Instant A/B at the same playhead position, with a level-matching option so "louder" doesn't read as "better"
- **Suno shimmer cleanup** — before resynthesis, narrow flickering artefacts in the 5–14 kHz range are suppressed so the exciter doesn't build new harmonics out of them. The low end is untouched, and the centre of the mix is cleaned more gently than the sides
- **Auto** — instead of a fixed preset, analyse the actual track and get parameters worked out from it (cutoff steepness, real mud excess, existing stereo width) rather than guessed blind

The loudness meter has been checked against the standard's calibration test: a 997 Hz sine at 0 dBFS in a single channel reads as −3.05 LUFS against a −3.01 reference.

## Presets

| Preset | What it's for |
|---|---|
| Auto | parameters worked out from analysing the actual track (cutoff, mud, width, amount of shimmer) — becomes available once a file is loaded |
| MP3 restoration | 128 kbps exports, cutoff around 15.8 kHz |
| WAV polish | Pro/Premier exports, higher and softer cutoff |
| Top end only | top end and width, no mid cleanup |
| Full master | MP3 restoration plus the master polish: multiband 50, mono bass 100, soft clipper 40 |
| Loudness only | normalisation and limiting, no spectral processing |

## What each control does

Processing runs in this order:

1. The cutoff is found from the average spectrum of the whole track.
2. Suno shimmer cleanup.
3. The dry path: a 26 Hz high-pass (sub-sonic rumble), then the cut at 300 Hz.
4. The new top end is synthesised from the band below the cutoff and mixed in.
5. The shelf from 11 kHz (it affects the original and the new top end alike).
6. The compressor, if it's switched on.
7. Stereo width.
8. Reference match, if a reference track is loaded.
9. Multiband compression, then mono bass.
10. Loudness: the soft clipper, if it's on, then the limiter.

| Control | Range | Default | Python option |
|---|---|---|---|
| Suno shimmer cleanup | 0–100 | 60 | `--deshimmer` |
| How much top end to rebuild | 0–100 | 70 | `--air` |
| Harmonic density | 0–100 | 65 | `--drive` |
| Air shelf from 11 kHz | 0 to +6 dB | +3.0 | `--shelf` |
| Mud cleanup at 300 Hz | 0 to −6 dB | −2.5 | `--mud` |
| Stereo width above 2.5 kHz | 0–100 | 35 | `--width` |
| Compressor glue | 0–100 | off | — |
| Match strength (reference) | 0–100 | 100 | `--ref-strength` (with `--reference`) |
| Multiband compression | 0–100 | off | `--multiband` |
| Mono bass below 120 Hz | 0–100 | off | `--mono-bass` |
| Soft clipper before limiter | 0–100 | off | `--clip` |
| Target loudness | −18 to −7 LUFS | −11.0 | `--target` |
| Going to MP3/AAC | off / on | off | `--format lossy` |

### Suno shimmer cleanup
Suppresses the narrow, flickering artefacts Suno leaves between 4.5 and 14 kHz (the upper edge sits just under the cutoff). The track is analysed in short frames; a bin that sticks out more than about 8 dB above the median of its neighbouring frequencies is brought down to that floor, but only if its level also jumps about from frame to frame, which is how shimmer behaves and an instrument's note doesn't. Transients and broadband events are left alone, and so is everything below 4.5 kHz. The sides are cleaned at the full strength of the slider, the centre (vocals, the main material) at 60% of it. The exciter is fed a version cleaned twice as hard (capped at 100): it needs the musical structure of the band, not its beauty, and without that it would build new harmonics out of the artefacts. Zero switches it off.

### How much top end to rebuild
The level of the synthesised top end. It's built from the band just under the cutoff, and its level is set frame by frame from the spectral slope below the cutoff, extrapolated above it, so the new top end breathes with the music rather than sitting as a flat layer. 100 is the natural continuation of the spectrum; 50 is half the amplitude of that (−6 dB). If the track has no cutoff (a full-range file), there's nothing to rebuild and this control does nothing.

### Harmonic density
How hard the signal is driven into the saturator that generates the harmonics. The gain in front of it is 1 + 14 × the value: ×1 at zero, ×15 at 100. Low values give a few clean harmonics, high values many dirtier ones. The curve is slightly asymmetric: odd harmonics add brightness, even ones warmth. If the cymbals start to hiss, lower this before lowering the top-end amount. Saturation runs at 4× oversampling, and the new material above the cutoff is isolated with a linear-phase filter.

### Air shelf from 11 kHz
A smooth high shelf: half of the set gain at 11 kHz, the full gain towards 16–20 kHz, and barely audible below about 6 kHz. 0 to +6 dB. It comes after the new top end is mixed in, so it lifts both the original material and the rebuilt part.

### Mud cleanup at 300 Hz
A bell-shaped cut centred on 300 Hz, roughly one and a half octaves wide (about 180–500 Hz), 0 to −6 dB. It's applied to the dry path and to the exciter's feed, so a boomy low end doesn't drive the saturator. The 26 Hz high-pass that removes sub-sonic rumble sits on the same path. Auto mode sets this in proportion to the real excess at 250–400 Hz, and leaves it alone if there isn't one.

### Stereo width above 2.5 kHz
Works in mid/side. The side signal above 2.5 kHz is boosted by a factor of 1 + 1.2 × the value (×2.2, or +6.9 dB, at 100); the mid signal and everything below 2.5 kHz are left exactly as they were. At zero the stage is bypassed. High values push the top end out wide but make it fold down to mono less cleanly, so check in mono.

### Compressor glue
A gentle compressor over the whole mix: threshold −20 dB, soft knee, attack 20 ms, release 250 ms. The ratio rises from 1:1 to 3.5:1 across the slider, with make-up gain of up to +2.5 dB. Off at zero.

### Reference track
Optional. Load a track whose sound you like and Airband matches the tonal balance to it. Both average spectra are smoothed to a sixth of an octave and subtracted. The mean difference across 200–2000 Hz is taken off first, so the shape is corrected and the overall loudness is not (loudness belongs to the target). The correction is capped at ±6 dB and applied with a linear-phase filter of 2049 taps. The slider scales the correction in decibels: 100 is the full capped correction, 50 is half of it, 0 switches matching off. It runs after the stereo width and before the multiband compressor, so the compressor sees the finished balance. With no reference loaded the slider does nothing. Browser and Python use the same maths; on a test with a strong correction their filter curves agreed to within 0.12 dB. Python: `--reference`, `--ref-strength`.

### Multiband compression
Gentle compression in four bands: below 150 Hz, 150 Hz–1.5 kHz, 1.5–6 kHz and above 6 kHz. The bands are split with zero-phase filters and add back to the original exactly, so with the compressor idle nothing changes. In each band the threshold sits where that band's own level is 60% of the time, so the compressor works on the louder passages of every band whatever the overall level. At 100 the ratios are 2:1, 2:1, 1.8:1 and 1.6:1; the slider scales the ratio, and the reduction never exceeds 6 dB. Attack and release get quicker towards the top: 30 ms and 250 ms in the lows, 4 ms and 80 ms in the highs. There is no make-up gain; the loudness stage after it brings the level back to the target. It is gentle by design, so judge it by ear. Off at zero. Python: `--multiband`. The browser runs it in ten-second chunks and gives the page a breath between them; on the same signal it agrees with Python to within 0.05% of the peak.

### Mono bass below 120 Hz
Takes the side signal (left minus right) out of the low end so the bass sits in the centre and stays solid on club systems, phone speakers and in mono. A fourth-order zero-phase low-pass at 120 Hz picks out the lows; half of their left-minus-right difference, times the slider, is taken from the left channel and added to the right. The mid signal and everything above the corner are left as they were. At 100 the side signal is 48 dB down at 60 Hz and fades out towards 120 Hz. Off at zero. Python: `--mono-bass`. The first and last twenty milliseconds of a file differ slightly between browser and Python, because the two filters start up differently; elsewhere they match.

### Soft clipper before limiter
Rounds the very tops of the peaks before the limiter sees them. Below a knee the signal is untouched; above it a tanh curve bends the peak towards the ceiling and never past it. At 100 the knee sits 3 dB under the ceiling; at 0 the stage is off. The limiter then has less to grab and breathes less. It sits inside the loudness loop, after the gain, so the target is still hit within 0.1 dB and the true-peak check afterwards is unchanged. It is not oversampled and can add a little aliasing. In the browser, switching it on makes each loudness pass recompute the true-peak envelope, which costs extra time on long tracks. Python: `--clip`.

### Target loudness
Integrated loudness per ITU-R BS.1770-4 (with gating), from −18 to −7 LUFS. The gain is found iteratively (the secant method, up to 8 passes) until the result is within 0.1 dB of the target, and a lookahead limiter (2 ms lookahead, 40 ms hold, smooth release) keeps the true peak under −1 dBTP. The ceiling is −1 dBTP (−1.5 dBTP with the "Going to MP3/AAC" switch, below), and the true peak is measured with 4× oversampling plus a 0.7 dB safety margin. If a track can't reach the target without distortion at that ceiling, the readout says "Loudness after — max without distortion" instead of quietly falling short. −14 LUFS suits Spotify and Apple Music; −11 gives a denser sound for your own sets.

### Going to MP3/AAC
A switch under the target loudness. Off, the ceiling is −1 dBTP. On, it drops to −1.5 dBTP: if the master will be encoded to MP3, AAC or Opus afterwards, the encoder adds overshoot of its own and needs the extra headroom. The file is still exported as 24-bit WAV; only the headroom changes. Python: `--format lossy`, or any value with `--ceiling`.

The Python version follows the same logic; where it differs is described in [`python/README.md`](python/README.md).

## Running it locally

You can open `en.html` (or `ru.html`) straight from the file, but serving it is more reliable:

```
python3 -m http.server 8080
```

Then visit `http://localhost:8080`.

## Publishing to GitHub Pages

1. Create a repository and push the folder's contents to the root
2. Settings → Pages → Source: Deploy from a branch
3. Branch: `main`, folder `/ (root)`
4. Within a minute you'll have an address like `https://<username>.github.io/airband/`

No build step, no dependencies.

## Local Python version

The `python/` folder holds a command-line version. It does the same job to a higher standard, and can do things the browser can't:

- envelope following — the level of the new top end is derived from the spectral slope below the cutoff and moves with the music
- linear-phase filters instead of biquads
- album-wide normalisation: one shared offset instead of levelling each track on its own
- batch processing of whole folders, PNG reports, a DSP self-test

```
cd python
python3 -m venv .venv && source .venv/bin/activate
pip install numpy scipy
python airband.py album/ -o mastered/ --album --target -14
```

The virtual environment is needed on modern Debian and Ubuntu, which refuse a bare `pip install` (see the installation notes in `python/README.md`). Details are in `python/README.md`.

The browser version is for a quick check and for seeing the cliff with your own eyes. Python is for albums and final mastering.

## Structure

```
index.html   language picker (modelled on iDentity Prompt Engine)
en.html      the whole tool in English — markup, styles and DSP in one file
ru.html      the whole tool in Russian, same thing
python/      the command-line version
```

Each HTML file is self-contained: CSS and JS are inlined, no external links. The browser part used to be three files (`index.html` + `app.css` + `app.js`) — opened any way other than through a real web server, relative links don't always resolve (a preview inside a chat interface, for instance, opens files separately and the styles never load), so now every page is a single file with no exceptions.

The `index.html` router scheme only works in full when all three files sit together on real hosting (GitHub Pages, any web server) — that's what lets the links to `en.html`/`ru.html` resolve. A file opened on its own (through a chat preview, say) will still open and work by itself, but following a link to another file in that context may not work — that's a limitation of how it's being previewed, not of the file itself.

For GitHub Pages: drop all three files in the repository root, visit `username.github.io/repo/`, and you'll land on the language picker.

## Limitations

- You can't get back what was never there. The harmonics are a plausible reconstruction, not the original recording.
- On tracks longer than six or seven minutes, processing on a phone can take half a minute or more.
- Safari needs version 14.1 or newer.
- Dithering on export uses `Math.random()`. Fine for mastering, not for metrology.

## How to tune it

Start with the **Auto** preset — it shows up once a file is loaded and works out its parameters from the track itself: cutoff steepness, real mud excess at 250–400 Hz, existing stereo width. The idea comes from the Master Assistant in the open-source plugin [oXygen](https://github.com/Wamphyre/oXygen): it listens to the input and writes its own settings rather than asking you to guess a preset. From there, tweak any control by hand as a starting point.

If it sounds too aggressive or too gentle, switch to a fixed preset and compare. If the top end starts to hiss or the cymbals get a "foam" on them, pull back harmonic density before amount. Density controls how dirty the harmonics get; amount only controls their level.

Target loudness: −14 LUFS for Spotify and Apple Music, −11 for your own sets and a denser sound.

## Licence

MIT — see [`LICENCE`](LICENSE). Use it, fork it, change it, sell a version
you've built on top of it if someone's buying. The only condition is
keeping the copyright notice and licence text in copies.

On the hold-stage limiter: the implementation is written from scratch,
but the idea (a plateau after the peak, plus a guarantee against
overshoot) was checked against the Hyrax limiter from
[Matchering](https://github.com/sergree/matchering) (itself GPLv3
licensed). No code was copied — only the concept, which copyright
doesn't cover — so Airband's MIT licence isn't compromised by that.
