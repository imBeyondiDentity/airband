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
- Stereo widening above 2.5 kHz only, in mid/side — the low end stays mono
- Optional compressor glue
- Loudness measurement per ITU-R BS.1770-4 with gating, normalised to a target
- A 2 ms lookahead limiter with a 40 ms hold stage, −1 dB ceiling
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
| Loudness only | normalisation and limiting, no spectral processing |

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
- tonal matching against a reference track
- album-wide normalisation: one shared offset instead of levelling each track on its own
- batch processing of whole folders, PNG reports, a DSP self-test

```
cd python
pip install numpy scipy
python airband.py album/ -o mastered/ --album --target -14
```

Details are in `python/README.md`.

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
