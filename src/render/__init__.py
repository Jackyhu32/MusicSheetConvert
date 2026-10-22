"""Rendering layer: MusicXML / jianpu -> PNG / PDF / SVG via MuseScore.

Supported renderers:
    * ``MuseScore 4`` (Windows default: ``D:\\Program Files (x86)\\MuseScore 4\\bin\\MuseScore4.exe``)
    * ``MuseScore 3`` (Linux/macOS legacy; older ``--export-image`` interface)

The output format is inferred from the file extension: ``.png`` / ``.pdf`` /
``.svg`` / ``.musicxml`` / ``.mid``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import music21

from src.music_convert.model import ScoreModel

PathLike = str | Path

# Default MuseScore 4 install location (this machine).
_MSCORE_DEFAULT_WIN = r"D:\Program Files (x86)\MuseScore 4\bin\MuseScore4.exe"


def find_musescore(custom_path: str | None = None) -> str | None:
    """Locate the MuseScore executable. Returns an absolute path or ``None``."""
    if custom_path and Path(custom_path).exists():
        return custom_path
    # 1) Environment variable.
    env = os.environ.get("MUSESCORE_EXE")
    if env and Path(env).exists():
        return env
    # 2) Search PATH for known names.
    for name in (
        "MuseScore4",
        "MuseScore4.exe",
        "musescore",
        "musescore.exe",
        "mscore",
        "mscore.exe",
    ):
        found = shutil.which(name)
        if found:
            return found
    # 3) Windows default install path.
    if Path(_MSCORE_DEFAULT_WIN).exists():
        return _MSCORE_DEFAULT_WIN
    return None


def musicxml_to_jianpu_text_file(
    xml_path: PathLike,
    out_path: PathLike,
    *,
    mode: str = "movable",
    tonic: str | None = None,
) -> Path:
    """MusicXML -> auditable Jianpu JSONL text file."""
    from src.music_convert.musicxml_io import load_musicxml

    return score_model_to_jianpu_text_file(
        load_musicxml(xml_path), out_path, mode=mode, tonic=tonic
    )


def score_model_to_jianpu_text_file(
    score: ScoreModel,
    out_path: PathLike,
    *,
    mode: str = "movable",
    tonic: str | None = None,
) -> Path:
    """Write auditable Jianpu JSONL directly from a parsed score model."""
    from src.music_convert.core import score_model_to_jianpu_text

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        score_model_to_jianpu_text(score, mode=mode, tonic=tonic), encoding="utf-8"
    )
    return out_path


def render_via_musescore(
    source: PathLike,
    out_path: PathLike,
    *,
    mscore_exe: str | None = None,
    extra_args: list[str] | None = None,
) -> Path:
    """Convert ``source`` to ``out_path`` via MuseScore (format determined by extension).

    Supports: ``.png`` / ``.pdf`` / ``.svg`` / ``.musicxml`` / ``.mid``.
    """
    source = Path(source)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bin_name = find_musescore(mscore_exe)
    if not bin_name:
        raise RuntimeError(
            "MuseScore 4 executable not found. "
            "Install it from https://musescore.org/download "
            "or set the environment variable MUSESCORE_EXE to its path."
        )
    cmd = [bin_name, "-o", str(out_path)]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(source))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as e:
        raise RuntimeError(f"MuseScore binary not found: {bin_name}") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"MuseScore conversion failed: {e.stderr or e.stdout}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("MuseScore conversion timed out") from e

    # MuseScore 4 may emit the artifact next to ``out_path`` with a different
    # name (e.g. ``<basename>-1.png``) depending on how it parses ``-o``.
    # Try a handful of candidate locations before declaring failure.
    if out_path.suffix.lower() in (".png", ".pdf", ".svg"):
        candidates = [
            out_path,  # the expected location
            out_path.parent / f"{source.stem}-1{out_path.suffix}",  # legacy v3 naming
            out_path.with_name(f"{source.stem}-1{out_path.suffix}"),
            out_path.with_name(f"{source.stem}{out_path.suffix}"),
        ]
        for cand in candidates:
            if cand.exists() and cand != out_path:
                shutil.move(str(cand), str(out_path))
                break
        # Diagnostic when nothing was produced.
        if not out_path.exists():
            files = [p.name for p in out_path.parent.iterdir() if p.is_file()]
            raise RuntimeError(
                f"MuseScore did not produce the expected output: {out_path}. "
                f"Files in output dir: {files}"
            )

    if not out_path.exists():
        raise RuntimeError(f"MuseScore did not produce the expected output: {out_path}")
    return out_path


def musicxml_to_png(
    xml_path: PathLike, out_path: PathLike, mscore_exe: str | None = None
) -> Path:
    """MusicXML -> PNG."""
    return render_via_musescore(xml_path, out_path, mscore_exe=mscore_exe)


def musicxml_to_pdf(
    xml_path: PathLike, out_path: PathLike, mscore_exe: str | None = None
) -> Path:
    """MusicXML -> PDF."""
    return render_via_musescore(xml_path, out_path, mscore_exe=mscore_exe)


def midi_to_musicxml(
    midi_path: PathLike, out_path: PathLike, mscore_exe: str | None = None
) -> Path:
    """MIDI -> MusicXML via MuseScore. Generally more accurate than music21's built-in converter."""
    return render_via_musescore(midi_path, out_path, mscore_exe=mscore_exe)


def render_score_to_text(score: music21.stream.Score) -> str:
    """Use music21's built-in text renderer to produce a textual score outline."""
    return score.show("text")
