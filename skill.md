## name: staff-to-jianpu
description: Recognize staff sheet music (五線譜) and Chinese/English lyrics from images or PDFs, convert them into numbered musical notation (簡譜 / Jianpu), and export to PDF or user-specified formats. Use when the user asks to transcribe, read, convert, or translate sheet music, staff notation, or vocal scores into jianpu with lyrics.

# staff-to-jianpu

Translate staff sheet music (五線譜) into standard numbered musical notation (簡譜 / Jianpu), aligning Chinese and English lyrics to each note, and outputting formatted PDF or custom formats.

## Summary

This skill extracts musical notes, clefs, key signatures, dynamics, and lyrics from staff notation images or PDF files, applies music theory rules for Movable-Do mapping (including multi-voice choral conventions and mid-score modulations), and renders clean, publication-ready Jianpu scores with vector notation symbols.

## When to Use

Use this skill whenever the user:

* Requests to convert staff notation (五線譜) into numbered musical notation (簡譜 / 數碼譜).

* Uploads an image or PDF of solo or multi-part vocal/choral sheet music and asks for a Jianpu version.

* Wants lyrics (Chinese characters or English words) aligned under numbered musical notes.

* Needs an exported PDF score in Jianpu notation or requests formats such as Markdown, MusicXML, or plain text.

## Core Music Theory and Mapping Rules

### 1. Key Signatures and Movable-Do Mapping (首調唱名法)

Jianpu uses Movable-Do (首調唱名法) by default, where scale degree `1` represents the major tonic and `6` represents the relative minor tonic:

* 0 sharps/flats: C Major (`1 = C`) / A Minor (`6 = A`)

* 1 sharp (F#): G Major (`1 = G`) / E Minor (`6 = E`)

* 2 sharps (F#, C#): D Major (`1 = D`) / B Minor (`6 = B`)

* 3 sharps (F#, C#, G#): A Major (`1 = A`) / F# Minor (`6 = F#`)

* 4 sharps (F#, C#, G#, D#): E Major (`1 = E`) / C# Minor (`6 = C#`)

* 5 sharps (F#, C#, G#, D#, A#): B Major (`1 = B`) / G# Minor (`6 = G#`)

* 1 flat (Bb): F Major (`1 = F`) / D Minor (`6 = D`)

* 2 flats (Bb, Eb): Bb Major (`1 = Bb`) / G Minor (`6 = G`)

* 3 flats (Bb, Eb, Ab): Eb Major (`1 = Eb`) / C Minor (`6 = C`)

* 4 flats (Bb, Eb, Ab, Db): Ab Major (`1 = Ab`) / F Minor (`6 = F`)

* 5 flats (Bb, Eb, Ab, Db, Gb): Db Major (`1 = Db`) / Bb Minor (`6 = Bb`)

**Accidentals in Movable-Do**:

* When a chromatic accidental (`#`, `b`, `♮`) appears on the staff, convert the altered pitch relative to the active Movable-Do scale degree (e.g., in `1 = F` where `Bb` is `4`, a `♮B` on the staff raises the 4th degree by a semitone and is written as `#4`; in `1 = D` where `C#` is `7`, a `♮C` lowers the 7th degree and is written as `b7` or `♮7`).

* **Mid-Score Modulations (轉調)**: When the key signature changes mid-piece, mark `[轉 1 = X]` at the modulation point (including on anacrusis/pickup beats leading into the new key).

### 2. Clefs and Octave Dot Indications (譜號與八度規範)

* Middle octave (`octave = 0`): Digits `1 2 3 4 5 6 7` without dots.

* High octave (`+1` / `+2`): One or two dots directly above the digit (e.g. `1̇`, `1̈`).

* Low octave (`-1` / `-2`): One or two dots directly below the digit (below any duration underlines, e.g. `5̣`, `5̣̣`).

* **Multi-Voice / Choral Octave Convention (合唱譜男女聲部八度慣例)**:

  * **Female voices (Soprano / Alto, Treble Clef `G`)**: Middle octave (`0`) corresponds to the female middle register (e.g. `C4–B4` in `1 = C`, `D4–C#5` in `1 = D`).

  * **Male voices (Tenor in Octave-Treble Clef `G8`, Baritone/Bass in Bass Clef `F`)**: By standard choral Jianpu convention, male voices are notated **one octave higher than actual sounding pitch** so that the male middle register (`C3–B3` in `1 = C`, `D3–C#4` in `1 = D`) is written as middle octave (`0`, without low dots). This ensures Tenor (`G8` clef, read as written) and Baritone/Bass (`F` clef, `D3` on 3rd line = `1` in `1 = D`) share the exact same octave reference when singing in unison or crossing parts. Always add a footnote on Page 1 stating: `註：依合唱簡譜慣例，男聲部記譜音高比女聲部實際發音低一個八度。`

### 3. Rhythm and Duration Symbols

* Whole note (全音符, 4 beats in 4/4): `5 - - -` (digit + three prolongation dashes)

* Dotted half note (附點二分音符, 3 beats): `5 - -` (digit + two prolongation dashes; **never** write `5· -`)

* Half note (二分音符, 2 beats): `5 -`

* Quarter note (四分音符, 1 beat): `5`

* Dotted quarter note (附點四分音符, 1.5 beats): `5·`

* Eighth note (八分音符, 0.5 beat): `5` with single underline (減時線). **Beam grouping**: Consecutive eighth notes within the same beat or two-beat group must share a continuous horizontal underline rather than broken individual dashes.

* Sixteenth note (十六分音符, 0.25 beat): `5` with double underline.

* Quarter rest (四分休止符): `0` (in choral scores, write 4 beats of rest as `0 0 0 0` aligned to the 4 beat columns).

* Eighth rest: `0` with single underline.

### 4. Lyrics Alignment Rules

* Chinese lyrics: 1 Chinese character per sung note, centered directly below the note's horizontal coordinate. For slurred melisma (一字多音), place the character under the first note and connect the notes above with a slur arc (`連音線`).

* English lyrics / vocables (`Ah`, `du`, `la`): 1 syllable per note. Split multi-syllable words with hyphens (`Won - der - ful`).

## Steps

### Step 1: Ingest, High-Res Cropping, and Staff Calibration

1. **High-Resolution Rendering**: For PDFs, render pages at **300+ DPI** (or `pypdfium2` `scale=3.5` to `4.0`). Do not rely solely on whole-page 200 DPI screenshots for multi-stave scores, where adjacent line/space intervals compress to `<5 px`.

2. **System & Measure Cropping**: Crop each page into individual systems or 2–3 measure blocks before reading notes.

3. **Local 5-Line Staff Calibration (防線間偏移與掃描傾斜)**:

   * Scanned scores often have a slight tilt (`0.5°–1.5°`), causing staff lines on the right side of a page to shift vertically by 10–15 px relative to the left side. Always reference the 5 staff lines (`L5` down to `L1`) locally within each measure.

   * Watch stem direction carefully: when stems point **down** on high notes, the thick horizontal beam sits near the bottom/middle of the staff—do not confuse the beam with noteheads.

   * **Anti-Hallucination on Sequential Motifs (防模進誤判)**: When consecutive measures share the exact same rhythm, articulation, or vocable (e.g. repeated `"du"` or `"Ah"` figures), explicitly compare the starting notehead's staff line/space against the previous measure. Never assume exact pitch repetition without verifying whether the figure is a ascending/descending diatonic sequence (二度或三度模進).

### Step 2: Extract & Programmatically Validate Score Data

1. Represent every measure with explicit beat onsets (`start_beat`) and durations (`duration_beats`).

2. **Programmatic Beat-Sum Assertion**: Before rendering, assert in Python that every measure (and every voice in multi-part scores) sums to the exact time signature beat count (e.g. `4.0` beats in 4/4, excluding pickup bars).

3. **Cross-Barline Tie Consistency Check**: Verify that every tied note (`延音線`) across a barline or system break lands on the exact same scale degree and octave as the note it tied from, and that notes sharing the same staff line/space in adjacent measures map to the same Jianpu pitch.

### Step 3: Render Deliverable

#### Critical PDF Rendering Rules (Preventing Missing-Glyph Tofu Boxes `□` & Blank ASCII)

1. **Never Use CJK Fallback Fonts for ASCII Text**:

   * Linux fallback fonts like `DroidSansFallbackFull.ttf` contain **only CJK glyphs** and lack ASCII digits (`0–9`), Latin letters, parentheses `()`, `-`, `/`, and `=`. Drawing `"1 = F   4/4"` or `"- 1 -"` using `DroidSansFallbackFull.ttf` will result in **invisible/blank ASCII text**.

   * **Solution**: Always use `Helvetica-Bold` for Jianpu digits (`0–7`), `Times-BoldItalic` / `Times-Italic` for dynamics (`mf`, `mp`, `p`, `f`, `cresc.`), `Times-Roman` for Latin lyrics (`Ah`, `du`), and a `draw_mixed_text()` helper that splits strings into CJK runs (`DroidSansFallbackFull.ttf`) and ASCII runs (`Times-Roman` / `Times-Bold`).

2. **Never Use Unicode Text Characters for Musical Symbols (Vector-Only Rule)**:

   * Never pass Unicode symbols such as `"·"` (`U+00B7` middle dot), `"–"` (`U+2013` en-dash), `"♮"` (`U+266E` natural sign), `"♩"` (`U+2669`), or `"𝄐"` (fermata) to unembedded PDF standard fonts (`Helvetica-Bold` / `Times-Roman`). External PDF viewers (Windows, macOS, iOS) frequently fail to map these code points in Type1 standard fonts and render them as **missing-character boxes (`□` / Tofu)**.

   * **Solution**: Draw all musical symbols using **native ReportLab vector graphics**:

     * **Augmentation dot (`附點 ·`)**: `c.circle(nx + 6.2, y_note + 3.8, 1.3, stroke=0, fill=1)`

     * **Octave dots (`高低音點`)**: `c.circle(nx, y_dot, 1.15, stroke=0, fill=1)`

     * **Prolongation dash (`增時線 -`)**: `c.line(nx - 3.6, y_note + 4.0, nx + 3.6, y_note + 4.0)`

     * **Natural sign (`還原記號 ♮`)**: 4 crisp vector lines (`draw_natural_symbol`)

     * **Fermata (`延長記號`) & Slurs (`連音線`)**: Vector Bezier curves (`c.beginPath()` / `p.curveTo(...)`)

     * **Quarter-note tempo mark (`♩ = 75`)**: Filled rotated vector ellipse + vertical stem (`draw_quarter_note_tempo`)

#### Reference Vector-Safe Rendering Script (ReportLab)

```
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, json
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def setup_cjk_font():
    candidates = [
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont('CJK', path))
                return 'CJK'
            except Exception:
                continue
    return 'Helvetica'

def draw_mixed_text(c, x, y, text, size, align="left", ascii_font="Times-Roman", cjk_font="CJK"):
    """Split CJK and ASCII runs so CJK-only TTF fonts never blank out ASCII digits/symbols."""
    runs, cur_run, cur_is_cjk = [], "", None
    for ch in text:
        is_cjk = ord(ch) >= 0x2E80 or ch in "／（）：，。、；「」『』【】"
        if cur_is_cjk is None or is_cjk == cur_is_cjk:
            cur_run += ch
            cur_is_cjk = is_cjk
        else:
            runs.append((cur_run, cjk_font if cur_is_cjk else ascii_font))
            cur_run, cur_is_cjk = ch, is_cjk
    if cur_run:
        runs.append((cur_run, cjk_font if cur_is_cjk else ascii_font))

    total_w = sum(pdfmetrics.stringWidth(r, f, size) for r, f in runs)
    cur_x = x - total_w / 2.0 if align == "center" else (x - total_w if align == "right" else x)
    c.saveState()
    for r, f in runs:
        c.setFont(f, size)
        c.drawString(cur_x, y, r)
        cur_x += pdfmetrics.stringWidth(r, f, size)
    c.restoreState()
    return total_w

def draw_quarter_note_tempo(c, x, y, bpm=80, size=10.5):
    """Vector quarter-note symbol + '= bpm' (avoids missing U+2669 glyph)."""
    c.saveState()
    c.translate(x + 3, y + 2.5)
    c.rotate(25)
    c.ellipse(-3.2, -2.0, 3.2, 2.0, stroke=0, fill=1)
    c.restoreState()
    c.saveState()
    c.setLineWidth(1.0)
    c.line(x + 5.6, y + 2.5, x + 5.6, y + 11.5)
    c.setFont("Times-Bold", size)
    c.drawString(x + 9.5, y, f"= {bpm}")
    c.restoreState()

def draw_natural_symbol(c, x_right, y_bottom):
    """Vector natural sign (♮) right-aligned at x_right, baseline y_bottom."""
    c.saveState()
    c.setLineWidth(0.75)
    xl, xr = x_right - 3.6, x_right - 0.8
    c.line(xl, y_bottom + 1.0, xl, y_bottom + 8.5)
    c.line(xr, y_bottom - 1.0, xr, y_bottom + 6.5)
    c.line(xl, y_bottom + 5.2, xr, y_bottom + 6.2)
    c.line(xl, y_bottom + 1.4, xr, y_bottom + 2.4)
    c.restoreState()

def draw_accidental(c, acc, x, y):
    c.saveState()
    if acc == "#":
        c.setFont("Helvetica-Bold", 8.0)
        c.drawRightString(x, y, "#")
    elif acc == "b":
        c.setFont("Times-BoldItalic", 9.0)
        c.drawRightString(x, y, "b")
    elif acc in ["♮", "="]:
        draw_natural_symbol(c, x, y - 0.5)
    c.restoreState()

def draw_slur(c, x1, x2, y_base, height=5.5):
    if x2 - x1 < 3.0:
        return
    c.saveState()
    c.setLineWidth(0.85)
    p = c.beginPath()
    p.moveTo(x1, y_base)
    p.curveTo(x1 + (x2 - x1) * 0.22, y_base + height,
              x1 + (x2 - x1) * 0.78, y_base + height,
              x2, y_base)
    c.drawPath(p, stroke=1, fill=0)
    c.restoreState()

def draw_fermata(c, x, y):
    c.saveState()
    c.setLineWidth(1.0)
    p = c.beginPath()
    p.moveTo(x - 5.2, y)
    p.curveTo(x - 3.2, y + 5.0, x + 3.2, y + 5.0, x + 5.2, y)
    c.drawPath(p, stroke=1, fill=0)
    c.circle(x, y + 1.2, 1.05, stroke=0, fill=1)
    c.restoreState()

```

#### Beat-Proportional Horizontal Layout & Multi-Voice Alignment

* In every measure of width `m_width`, position each note at its musical beat onset `start_beat` (e.g., in 4/4 time with eighth-note grid slots `slot = start_beat * 2.0` from `0` to `7`, `nx = m_x + pad_l + ((slot + 0.45) / 8.0) * inner_w`).

* In multi-part vocal/choral scores (`SATB` / `SATBB`), render all voices within a connected system bracket `[` on the left, using the exact same `start_beat` -> `nx` formula across all voices so simultaneous beats and lyrics align in vertical columns.

* Group consecutive `8th` or `16th` notes within the same beat or two-beat half-bar under a single continuous underline (`c.line(x_first - 4.0, y_ul, x_last + 4.0, y_ul)`), breaking the underline before rests (`0`).

### Step 4: Verification and Quality Check

1. **Programmatic Beat Check**: Verify that the sum of `duration_beats` in every measure (and every voice) matches the time signature.

2. **Tie & Sequence Pitch Audit**: Confirm that all cross-barline ties connect identical pitches, and re-verify any consecutive measures with repeated vocables (`"du"`, `"Ah"`) against local staff-line coordinates to rule out 1-line parallactic shifts or sequence hallucinations.

3. **Visual PDF Inspection**: Render the output PDF pages to PNG (`pypdfium2`) and inspect them visually to confirm:

   * Zero missing-glyph boxes (`□`) or blank ASCII numbers/headers.

   * Zero collisions between fermatas (`𝄐`), dynamics (`p`, `mf`), slurs, high-octave dots, and measure numbers.

   * Clean 1:1 vertical alignment between notes and lyric syllables.

## Gotchas

* **Token Parsing Order**: When parsing shorthand tokens containing both duration suffixes (`_`, `.`) and slur/tie parentheses (`(`, `)`), strip slur parentheses before or independently of duration/octave suffixes so `)` never leaks into the rendered pitch text.

* **Pickup Measures (弱起小節)**: Anacrusis bars contain fewer beats than the time signature. Keep actual note values without padding leading rests; if a mid-score key change occurs after a pickup beat, clearly mark the pivot/modulation on the pickup beat.

* **Movable-Do vs Fixed-Do**: Jianpu uses Movable-Do by default. If a score contains a minor/modulating introduction, state the active Movable-Do tonic (`1 = X`) clearly at each section and in a footnote so singers reading Fixed-Do vs Movable-Do have an unambiguous reference.