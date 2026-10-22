---
name: staff-to-jianpu
description: Use when converting staff notation from MusicXML, images, or PDFs to Jianpu and source pitch, rhythm, parts, or lyrics must remain auditable.
---

# Staff to Jianpu

Convert only readable, verifiable source content. This project covers the original score; requested arrangements must remain clearly separate.

## Accuracy Rules

- Movable-do is the default. In major keys, the tonic is scale degree 1. In minor keys, the tonic is scale degree 6. For example, A minor maps A=6, B=7, C=1.
- Fixed-do is available only when explicitly requested. Its anchor is C=1 regardless of key signature. Confirm accidentals represent actual sounding-pitch changes; do not move the fixed-do anchor with the key.
- Transcribe only voices present in the source score. Never invent a melody or voice. Do not fill missing notes or add content absent from the source.
- Jianpu mapping uses sounding pitch while retaining written pitch for source audit. Clef or voice gender does not authorize changing source pitch. Preserve exact source pitches and timing; do not silently quantize or rewrite them.
- Preserve chromatic alterations relative to the spelled scale degree. Check tied notes by sounding pitch.
- A key-signature change alone does not prove modulation. Do not infer a new tonic from that change alone. Ask when active tonic or mode is ambiguous; `--tonic` is one tonic for the entire CLI run, not a per-section key-change control.
- Disclose uncertain readings; do not silently guess. For each uncertain pitch, rhythm/duration, key signature/tonality, meter, tie/slur, voice, or boundary, give the page, part, measure, and candidate readings.
- Offer review-only output when pitch reading is uncertain. If ambiguity blocks conversion, stop without a final conversion artifact; provide review status/checklist or ask for a readable crop or confirmation.
- Preserve source transcription in editable MusicXML. This means original-staff transcription, not Jianpu encoded as nonstandard MusicXML.

## Workflow

1. Confirm what source data is actually accessible. Direct MusicXML/MXL input needs no OMR. For a readable image/PDF and actual visual-reading capability, you may create structured MusicXML/transcription containing only identifiable source notes; validate it, then pass the MusicXML directly to the CLI (for example, `python -m src.main score.musicxml --skip-ocr`). The CLI's own image/PDF OMR path requires Audiveris; PDF rasterization also requires Poppler. If neither visual reading nor usable OCR/OMR is available, do not claim to have read the image/PDF; request MusicXML/MXL/MIDI, a readable crop, or note-level source data. Never invent unseen measures.
2. Inspect source parts, clefs, written and sounding pitch, key/mode, meter, lyrics, timing, ties/slurs, and page/measure boundaries. For every unresolved pitch, rhythm/duration, key signature/tonality, meter, tie/slur, voice, or boundary, record page, part, measure, and candidate readings before conversion. If the ambiguity blocks conversion, stop without final artifacts and provide review-only status/checklist or ask for clarification. Only continue with an explicitly provisional draft if the user explicitly approves the provisional reading; label it unverified.
3. Run the supported CLI below only for readable, sufficiently resolved input. Do not embed or substitute a custom renderer script.
4. Review every published output against the source. Every successfully published OMR result/bundle has `requires_review=true` and a `review.json` with state `needs_source_image_review`, even when structural checks pass. This report does not mean the source image has been checked: `publication_state=complete` means only that the bundle was published, not that its transcription was verified. `requires_review` remains true until the source image is checked. If OMR merge or rendering fails, the transaction aborts without a partially published bundle or report; report the operation error and do not claim a review report exists. MusicXML or MIDI output does not prove OMR accuracy. Report unresolved issues and limitations; never guarantee accuracy.

## Supported CLI

From repository root:

```bash
python -m src.main score.pdf --out ./output
python -m src.main score.mxl --out ./output --mode fixed --tonic C
```

- `--mode movable|fixed` selects Jianpu mapping.
- `--tonic` sets an optional single tonic for the run.
- `--formats` selects a comma-separated subset.
- `--render` additionally renders source-staff PNG via MuseScore.
- Supported modes: movable, fixed.
- Default mode: movable.
- Default tonic: none.
- Default formats: text, pdf, musicxml, midi.
- Supported formats: midi, musicxml, pdf, text.

`text` is auditable JSONL; `pdf` is Jianpu PDF; `musicxml` is editable original-staff MusicXML; `midi` is playback using sounding pitch. Direct MusicXML input is copied unchanged. OMR page merge produces editable original-staff MusicXML and may normalize vendor layout metadata. If OMR structural validation fails (including missing meter or validation issues), the CLI publishes a review-only bundle without final conversion artifacts. Every successfully published OMR result/bundle has `requires_review=true` and `review.json` state `needs_source_image_review`, regardless of structural acceptance. `publication_state=complete` means the bundle was published, not that source-image verification is complete; `requires_review` stays true until that check is done. OMR operation failures abort the transaction, so no partial bundle or report is published; report the error instead. There is no `--review-only` flag. CJK lyric PDF requires a configured `JIANPU_CJK_FONT`; missing fonts or glyphs fail rather than silently falling back. Unsupported duration, grace-note, or layout cases fail closed rather than silently quantizing.

## Limitations and Review

- Structural acceptance checks cannot establish that OMR read the source correctly. Inspect all pages/parts and compare pitches, rhythm, lyrics, ties, and boundaries to the source image.
- When a blocker remains, do not deliver final conversion artifacts. Ask for confirmation or better source material, or provide only review status and a checklist. Only an explicitly user-approved provisional reading may produce a clearly marked, unverified draft.
- Do not claim the user-provided scan is a verified gold standard, benchmark accuracy, or Gemini Spark testing unless those checks were actually performed.
