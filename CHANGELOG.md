# Changelog — Airband

A history of every refinement and fix since the first build. Grouped by
theme, in order within each.

---

## Design and layout

### One visual language with Music DNA
The first version of the browser interface was built on its own palette
(blue and amber), unrelated to the rest of the toolset. Exact values were
lifted with a pixel-picker from iDentity Prompt Engine screenshots:
background `#0F1313`, accent `#FF7F44`, selected-state colours
`#9F3E16`/`#2E211D`/`#FFC4A3`, cream text `#E8E6E3`. Fonts: Playfair
Display for the headline, JetBrains Mono for UI chrome (labels, buttons,
taglines), Inter for body copy. Result: the browser version is now
indistinguishable in style from the rest of the family, instead of
running its own look.

### Two real bugs caught by actually rendering the page
- The `[hidden]` attribute was being overridden by the page's own
  `display: grid/flex` rules — the results panel and player could show
  up before there was any data to show. Fix: `[hidden] { display: none
  !important }` added, so the attribute wins every time, not just
  sometimes.
- `−11.0 LUFS` was wrapping onto two lines because the monospace font
  is wider than assumed. Fix: the value column was widened; figures now
  stay on one line.

### Single-file build instead of three
The browser version originally shipped as three files (`index.html` +
`app.css` + `app.js`). Opened any way other than through a real web
server — a chat preview, say — the relative links didn't resolve and
the styling never loaded, which looked like "everything's broken" from
the outside even though the code was sound. Fix: CSS and JS are now
inlined directly into the HTML; each file is self-contained and works
with no exceptions, whether previewed in a chat or served for real.

### Presets renamed
"MP3 rescue" and "Air only" read as a fairly random string of words.
Now: "MP3 restoration" (paired with "WAV polish" — different words for
a genuinely different level of aggression) and "Top end only" (the same
word already used one line down in the slider label, rather than
"air" standing alone).

### A grid instead of a "staircase"
The preset chips sized themselves to their own text on a flex layout —
"MP3 restoration" and "Top end only" ended up visibly different sizes.
Now: a 2×2 grid with equal-sized cells, text centred; on narrow screens
it wraps as one uniform block rather than unevenly.

### The tracks panel no longer leaves a void
With an empty track list, the "Tracks" panel was shorter than the
"Processing" panel (`align-items: start` on the column grid wasn't
letting them stretch to match), leaving bare black space to the right
of the short one for the full height of the tall one. Fix: panels now
stretch to equal height, and the empty state ("Nothing yet" plus
buttons) centres in the space that opens up, rather than sitting
pinned to the top above a void. The moment a track is added, the
centring drops away and the list behaves as an ordinary list again.

### Before/after buttons — equal width and equally visible highlighting
Two separate problems:
- The buttons were different widths (sized to their own text —
  "after" wider than "before"). Cause: `flex: 1` inside a
  shrink-to-fit `inline-flex` container has nothing to distribute,
  so it does nothing. Fix: a fixed width sized to the longer word in
  each language.
- The selected "before" state showed as a barely-visible grey sliver,
  while "after" was bright orange. Fix: "before"'s highlight made
  just as clear (a white bar rather than a faint grey one), simply in
  a different colour.

### The spectrum legend no longer collides with the cutoff label
Both elements — the HTML "before/after" legend and the cutoff-frequency
label drawn on the canvas — gravitated to the top-right corner. Since
Suno's cutoff nearly always sits around 15–20 kHz (the right-hand
portion of the log frequency scale), the collision wasn't a one-off on
a single file — it was close to guaranteed behaviour on almost any
track. Fix: the legend moved to the bottom-left, where nothing is ever
drawn on the canvas at all — the collision is ruled out structurally,
not patched for one case.

### Small text fixes
- Eyebrow label: "Suno Audio Engine" → "Audio Restoration Engine"
  across all three files (router plus both language versions).
- The "What's actually happening" section removed from both language
  versions.
- The footer ("Everything runs in your browser…") now holds to two
  lines on any screen from 360px up — narrow phones used to get three.
  The opening phrase was also reworded for a tighter fit.

### Consistency with Music DNA — in both directions
Once Airband had been brought in line with Music DNA's design, the
reverse gap turned up: Music DNA's own `index.html` had a fixed-size
heading (44px) and a doubled-up gap before its link cards (a margin on
the h1 plus a separate margin-top on the links block). Fix: Airband's
exact parameters ported over — `clamp(44px, 12vw, 64px)` for the
heading, one single source of spacing. Checked by comparing the block's
on-screen coordinates at the same viewport width: the vertical gap went
from 11px to 2px (desktop), and what's left on mobile widths comes
down purely to the two languages' link text being different lengths,
not to the layout itself.

---

## Localisation

### An English version and a language router
A full English version (`en.html`) was built — not a literal
translation but reworded copy throughout, including the strings the
JS itself generates (processing statuses, units — kHz, dB, and so on).
An `index.html` language router was added, modelled on iDentity Prompt
Engine's own: eyebrow, serif headline, two link cards, a footer with a
dot. All three files are self-contained; a link between them only
resolves once all three sit together on real hosting (a limitation of
how the page is being previewed, not of the files themselves).

### README in both languages
`README.md` (British English, `colour`/`optimise` conventions) and
`README_ru.md` (Russian) — kept in step with every interface change,
rather than written once and left to drift. See "Documentation and code
in British English" below for how the naming works.

---

## Python version

Built from scratch as a separate tool for batch processing and a
higher ceiling on quality, not a cut-down copy of the browser version:

- **Envelope following** — the level of the new top end is derived
  from the spectral slope below the cutoff and moves with the music,
  rather than sitting as a flat layer.
- **Linear-phase filters** (FIR) instead of biquads — the top end
  doesn't smear in time.
- **Honest oversampling** — saturation is computed at 4× the sample
  rate through polyphase filters, so aliasing never reaches the
  audible range.
- **Reference-track matching** — a smoothed spectral ratio, capped at
  six decibels, applied through a linear-phase filter.
- **Album mode** — one shared loudness offset for a whole album instead
  of levelling each track on its own (which flattens the dynamic
  contrast between quiet and loud tracks).
- **Iterative normalisation** — the limiter itself reduces loudness, so
  a single pass isn't precise enough; it's refined until the result
  lands within 0.1 dB of the target.
- **A DSP self-test** (`selftest.py`) — the loudness meter checked
  against the standard's own calibration tone, plus checks on the
  limiter, the cutoff detector, and restoration quality. Run after any
  change.

---

## A survey of mastering tools, and what came out of it

A survey of open-source mastering utilities on GitHub was put together
on request (no torrents, no pirated copies of closed-source software —
either way, a cracked binary can't be adapted to the task, since
there's no access to the DSP code). Two concrete things from that
survey made it into the project:

### Master Assistant (auto parameters)
The idea comes from the plugin [oXygen](https://github.com/Wamphyre/oXygen):
it listens to the input and writes its own settings rather than asking
the person to guess a preset. Built from scratch, in both versions
(`--preset auto` in Python, an "Auto" button in the browser):

- cutoff steepness → how aggressively to rebuild the top end (a hard
  MP3 cliff gets more, a soft WAV rolloff gets less, and full-range
  material with no cutoff at all skips resynthesis entirely);
- a genuinely measured excess at 250–400 Hz against the mid band
  (600–2500 Hz) → mud gets cleaned up only where it's actually
  present, not at a blind fixed −2.5 dB every time;
- the track's existing stereo width (RMS side/mid) → an already-wide
  track gets less added, a near-mono one gets more.

Checked against three synthetic cases (a hard MP3 cliff, a middling
WAV-like rolloff, a fully smooth signal with no cutoff at all) — the
calibration genuinely tells them apart with different numbers rather
than returning the same thing regardless. A dedicated block was added
to `selftest.py`.

### A limiter with a hold stage
Checked against the Hyrax limiter from
[Matchering](https://github.com/sergree/matchering). Theirs holds the
gain down for a short while after a peak before it starts releasing —
without that, a limiter tends to "breathe" too quickly on transient
material such as drums or percussion. The previous implementation had
only a lookahead stage with no hold, and the sole safeguard against
overshoot was a blunt `clip()` after the fact. Added to both versions
(Python and browser):

- a hold plateau of roughly 40 ms after each peak;
- a mathematical guarantee that the smoothed gain can never exceed
  what's actually required at that instant — previously the only
  safeguard there was the clip; overshoot is now ruled out by
  construction.

Building the Python side turned up and fixed a genuine bug in the
existing code: the `origin` parameter of
`scipy.ndimage.minimum_filter1d` produces a systematic shift on large
windows (1920 samples) — confirmed numerically against a reference
signal, and traced to the correct fix, a deliberately odd-sized window.
The equivalent JS logic was checked in an isolated Node script before
it ever went near the browser file — it worked first time there. On a
single-transient test: the hold now lasts almost exactly the intended
~40 ms (previously untested at all), and the hard clip is needed on
close to nothing (0–10 samples out of 288,000, versus not being
measured at all before).

---

## Licence and repository housekeeping

### MIT licence
A `LICENSE` file was added at the repository root — everything is
permitted, commercial use included; the only condition is keeping the
copyright notice in copies. The README separately notes that the
limiter's hold stage was checked against Hyrax from Matchering (itself
GPLv3) for the idea only, not the code — a concept isn't copyrightable,
so Airband's MIT licence isn't compromised by it.

### An icon (favicon)
Modelled on another tool in the family (Duo) — an SVG sitting directly
inside `<link rel="icon">` as a data URI, no separate image file. Rising
equaliser bars on a dark background: three in a muted grey, the last one
in the accent orange — a nod to the tool's whole premise, the restored
band that was missing. Added to all three files (router plus both
language versions), checked by rendering at 128px and at an actual
favicon's real size of 16px — legible at both.

---

## Honest true peak (found in the second survey)

### The browser version was measuring the wrong peak
`truePeakDb` looked for peaks between samples using linear interpolation —
but a point on a straight line between two samples can never be higher
than the larger of them, so in practice it was measuring plain sample
peak. On a worst-case sine the error was 3 dB; on clipped material, close
to 6 dB. With a −1 dBTP ceiling, real peaks could reach +2 dBTP and above
— which clips once a streaming service converts the file.

Now: measurement per ITU-R BS.1770-4 — 4× oversampling through a
polyphase filter using the coefficients from the standard. The limiter
now holds back real inter-sample peaks rather than samples. The peak
envelope is computed once and scaled on every normalisation pass (the
measurement is linear in gain), so it costs about 2 seconds on a
four-minute stereo track.

### The safety margin, calibrated against an independent reference
Checking against scipy at 16× oversampling showed that even the standard
4× under-reads by up to ~0.55 dB on content right at the top of the
frequency range — which is exactly what Airband creates. Custom 8× and
16× filters were tried; short filters turned out worse than the
standard. The fix: keep the standard and give the limiter a 0.7 dB
margin. Result on real MP3s through the whole browser pipeline: −1.27 to
−1.37 dBTP by the independent reference, no overs at all.

### The Python version — same issue, smaller scale
The reference showed overs of up to 0.12 dB there too. The limiter's
final check moved from 4× to 8×, with a 0.15 dB margin. Now: −1.13 to
−1.15 dBTP by the reference, and loudness targets are still hit.

### Loudness targeting by the secant method
After the fix the limiter takes more off, and the old adjustment ("add
however much was missing") stopped converging within 4 passes. It's now
the secant method, up to 8 passes: it works out for itself how much real
loudness each added decibel buys on that particular track.

### An honest label when the target can't be reached
A limiter can't make a track louder than its own distortion-free limit.
If the target (−11 or −9 LUFS, say) can't be reached under an honest
ceiling, the readout says "Loudness after — max without distortion"
instead of quietly falling short. The previous version partly "hit" −11
by letting peaks through — loudness is no longer bought with clipping.

---

## The browser has caught up with Python on top-end restoration

The test is the same as Python's self-test: a signal is cut with a brick
wall at 16 kHz, restored, and compared with what it was before the cut,
across 17–21 kHz. Python's bar is a worst-case error of 2.2 dB.

| Step | Worst-case error | Shape of the error |
|---|---|---|
| Original browser version | 7.4 dB | steep tilt: +7 at the cutoff, +2 at the top |
| + envelope following | 3.7 dB | tilted the other way |
| + linear-phase FIR on the output | 3.3 dB | tilt remained |
| + Python's saturation curve | **2.6 dB** | flat across all frequencies |

### Envelope following
Ported from Python one-for-one (checked on identical data — 0.000 dB
difference). The new top end is now synthesised in a separate pass, then
its level is set frame by frame from the spectral slope below the cutoff.
The "how much top end to rebuild" control now means what it does in
Python: 100 is the natural continuation of the spectrum.

### An FIR filter on the exciter's output
Gentle biquads replaced by a linear-phase FIR — the same filter as in
Python (coefficients match to 4e-16). Convolution via FFT.

### The cause of the tilt — the saturation curve
The browser was running a different formula from Python: tanh(2.5x +
0.35x²), several times harsher. The hypothesis was tested separately: the
browser curve reproduced in Python gave the same tilt, and Python's curve
inside the browser-style chain gave a flat 2.2 dB. Python's curve is now
used.

### What's left
0.4 dB short of Python at the very top (−2.6 at 21 kHz) — most likely
WaveShaper's built-in oversampling, which every browser implements its
own way. A four-minute track takes about 23 seconds and the interface
freezes meanwhile — next in line for moving into a Web Worker.

### A side effect — loudness lands closer to target
The new top end now sits at a more natural level with fewer sharp peaks,
leaving the limiter more room: at a −11 LUFS target it's now −11.1 to
−11.8 rather than −11.9 to −12.8.

---

## De-shimmer: clean first, rebuild second

Suno leaves narrow, flickering artefacts — "shimmer" — in roughly the
5–14 kHz range. Airband's exciter draws on exactly that range and,
without a clean-up, built new harmonics out of the artefacts and pushed
them upwards. The numbers confirm it: without cleaning, shimmer-derived
debris in the air band sat only 5–6 dB below the music itself.

### Telling artefacts from music
An STFT; each frame gets a baseline taken as the median across
neighbouring frequencies; any outlier above the threshold is brought
down to the floor. Only what **flickers** is suppressed: a shimmer bin
jumps 10–20 dB from frame to frame, while an instrument's note decays
smoothly. Nothing below 4.5 kHz is touched, the centre of the mix is
cleaned more gently than the sides, and transients and broadband events
are left alone. The exciter's feed is cleaned twice as hard as the dry
path (capped at 1.0) — the exciter only needs the band's structure.

The flicker criterion took three attempts: a spectral-flatness gate
didn't work (the birdies themselves make the band look "tonal"), and
neither did a duration check (the analysis window glues fast bursts
together into a "note").

### Figures
Synthetic test: shimmer added to clean material with a melody up to
13 kHz.
- in the shimmer band: debris from −0.5 to −6.6 dB relative to the music;
- in the air band after the exciter: from −5.3 to −8.8 dB (browser),
  from −6.2 to −9.8 dB (Python);
- for a track with no shimmer: the air band changes by 0.03 dB, damage
  to the music is −30 dB.
What remains comes from nonlinear mixing of music and artefacts inside
the saturation stage, which cleaning the input can't remove.

### Browser and Python — the same thing
The browser port was checked against Python on identical data: a
difference of 1.5e-08 (float32 rounding), and the shimmer-amount
estimate matches to four decimal places. Strength only enters the
algorithm as a multiplier, so the gentle and the stronger versions come
out of a single analysis. A new "Suno shimmer cleanup" slider; presets
use 0.6 / 0.5 / 0.5 / off; Auto sets the strength from the measured
amount of shimmer (from 0.3 for a clean track up to 0.8).

### Licence
An original implementation; no code from other projects was used. The
ideas were checked against the public descriptions of deshimmer and
Shimmer. deshimmer's README states MIT, but there's no LICENSE file in
the repository — so no code was taken from it at all.

### Found and fixed along the way
- Python ran out of memory on a four-minute track: the de-shimmer's
  median, the 4× saturation and the envelope's spectrogram all held the
  whole track in huge arrays. All three now work in chunks; the result
  was checked against the old one (identical to float precision, the
  only difference being the first and last 40 ms of the track). Now:
  four minutes in about a minute and a half, peak memory around 2 GB.
  The previous speed estimate in the README was extrapolated from short
  tracks — it's now measured on a real long one.
- The browser median was rewritten as a sliding median over a sorted
  window, and the loops reordered for sequential memory access.

### The cost in speed
A four-minute track in the browser now takes about 38 seconds rather
than 23, and the interface freezes meanwhile — the next step is moving
the processing into a Web Worker.

---

## Documentation and code in British English

A standing convention, now applied across the whole of Airband: README and
CHANGELOG are always written in British English under the plain names
(`README.md`, `CHANGELOG.md`), and the Russian versions carry a `_ru`
suffix (`README_ru.md`, `CHANGELOG_ru.md`). Each file links to the other
language at the top. Previously it was the other way round: the Russian
file had the plain name, and the English one carried `.en`.

### What was renamed
`README.en.md` → `README.md`, `README.md` → `README_ru.md`, the same for
`CHANGELOG`, and the same pair inside `python/`. After uploading to GitHub
the old `README.en.md` and `CHANGELOG.en.md` need deleting, or duplicates
are left behind.

`ABOUT.md` (British English) and `ABOUT_ru.md` (Russian) follow the same
scheme. The old `ABOUT.md` turned out to be a snapshot of the very first
README and had fallen behind (no Auto preset, no shimmer cleanup, no licence,
and a claim that the browser has no envelope following), so both versions
were rebuilt from the current README rather than translated as they were.

### The Python version is now in English throughout
Comments, docstrings, console messages, `--help`, the labels on the PNG
report and the self-test output — everything that was in Russian across
nine files (about 330 lines) was rewritten in British English. This was a
rewrite, not a word-for-word translation: many of the comments explain
*why* something is done a certain way, and that had to survive. The
consequence for anyone using the command line: the console now speaks
English too.

### The code in `en.html` — likewise
The visible interface was already English; what remained in Russian were
the code comments (150 lines). They're now English as well. While at it, a
comment above the limiter that still described the old, lookahead-only
version was rewritten to say what the code really does: a lookahead, a hold
stage and a true-peak envelope.

### Proof that the sound didn't change
A translation has no business touching the processing, so it was checked
rather than assumed. Output arrays from before and after were compared bit
for bit: Python — 12 of 12 results identical (4 files × 3 modes), the
browser — 12 of 12 buffers identical. On top of that, the JavaScript and
the CSS of `en.html`, with comments stripped, match the old ones character
for character, and the visible markup is unchanged. The self-test gives
the same figures as before.

---

## What changed overall

| Before | After |
|---|---|
| Its own palette, unrelated to the rest of the toolset | An exact match with Music DNA — colours, fonts, structure |
| One language (Russian) | RU + EN + a language-picker router |
| Three files, broke under preview | One self-contained file per version |
| Fixed presets with hand-picked numbers | An Auto mode that works parameters out from the track itself |
| A limiter with no hold, overshoot caught only after the fact | A ~40 ms hold stage, overshoot ruled out by construction |
| Browser version only | + a Python CLI for batch processing and higher quality |
| No DSP self-test | `selftest.py` — loudness, limiter, cutoff detector, auto parameters |
| No licence | MIT, a `LICENSE` file at the root |
| A default, icon-less browser tab | An SVG favicon across all three files |
| Docs under mixed names, code comments half in Russian | README/CHANGELOG in British English, Russian versions as `_ru`; Python and `en.html` English throughout, sound bit-identical |
| Browser "true peak" actually measured samples (up to 6 dB out) | An honest BS.1770-4 measurement, checked against a 16× reference |
| Browser top-end restoration: 7.4 dB error, tilted | 2.6 dB, flat — close to Python's 2.2 |
| The exciter multiplied Suno's shimmer upwards | A de-shimmer ahead of the exciter in both versions |
