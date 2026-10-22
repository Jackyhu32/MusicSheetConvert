"""OCR adapter: invokes Audiveris (open-source OMR engine) to transcribe images
into MusicXML. Raises a clear error when Audiveris is unavailable.

Audiveris installation & usage:
    1. Download: https://github.com/Audiveris/audiveris/releases (Windows .msi / .zip)
    2. Add the directory containing ``Audiveris.exe`` to PATH, or pass an
       explicit path in the config. The default install location on this
       machine is ``D:\\Program Files (x86)\\Audiveris\\Audiveris.exe``.
    3. CLI: ``Audiveris -batch -export -output <out_dir> <input_image>``
       Produces ``<input_stem>.mxl`` (compressed MusicXML) in ``out_dir``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PathLike = str | Path


# Default Windows install path (this machine).
_AUDIVERIS_DEFAULT_WIN = r"D:\Program Files (x86)\Audiveris\Audiveris.exe"


def find_audiveris(custom_path: str | None = None) -> str | None:
    """Locate the Audiveris executable. Returns an absolute path or ``None``."""
    if custom_path and Path(custom_path).exists():
        return custom_path
    env = os.environ.get("AUDIVERIS_EXE")
    if env and Path(env).exists():
        return env
    for name in ("Audiveris", "Audiveris.exe", "audiveris", "audiveris.exe"):
        found = shutil.which(name)
        if found:
            return found
    if Path(_AUDIVERIS_DEFAULT_WIN).exists():
        return _AUDIVERIS_DEFAULT_WIN
    return None


@dataclass
class AudiverisConfig:
    """Configuration for invoking Audiveris."""

    bin_path: str | None = None  # empty = auto-discover
    java_opts: tuple[str, ...] = ("-Xms512m", "-Xmx2g")
    extra_args: tuple[str, ...] = ()   # extra arguments forwarded to Audiveris
    timeout: int = 600  # seconds; per-image recognition limit


def is_audiveris_available(cfg: AudiverisConfig | None = None) -> bool:
    """Check whether Audiveris is available on this system."""
    cfg = cfg or AudiverisConfig()
    return find_audiveris(cfg.bin_path) is not None


def image_to_musicxml(image_path: PathLike, out_dir: PathLike,
                      cfg: AudiverisConfig | None = None) -> Path:
    """Invoke Audiveris to transcribe a sheet image into MusicXML.

    Returns:
        Path to the exact generated page output (``.mxl``, ``.musicxml``, or ``.xml``).
    """
    cfg = cfg or AudiverisConfig()
    image_path = Path(image_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bin_name = find_audiveris(cfg.bin_path)
    if not bin_name:
        raise RuntimeError(
            "Audiveris is not installed or not on PATH. "
            "Install it from https://github.com/Audiveris/audiveris/releases "
            "or set the environment variable AUDIVERIS_EXE=<path>."
        )
    cmd = [bin_name, "-batch", "-export",
           "-output", str(out_dir)]
    if cfg.extra_args:
        cmd.extend(cfg.extra_args)
    cmd.append(str(image_path))
    expected_paths = [
        out_dir / f"{image_path.stem}{suffix}"
        for suffix in (".mxl", ".musicxml", ".xml")
    ]
    # Never mistake an output from an earlier run for this transcription.
    for expected_path in expected_paths:
        if expected_path.is_file():
            expected_path.unlink()

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       timeout=cfg.timeout)
    except FileNotFoundError as e:
        raise RuntimeError(f"Audiveris binary not found: {bin_name}") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Audiveris invocation failed (exit={e.returncode}):\n"
            f"stdout: {e.stdout[:500]}\nstderr: {e.stderr[:500]}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"Audiveris timed out (>{cfg.timeout}s); the image may be too complex "
            "or you may need to raise the timeout."
        ) from e

    for expected_path in expected_paths:
        if expected_path.is_file():
            return expected_path
    files = [p.name for p in out_dir.iterdir() if p.is_file()]
    raise FileNotFoundError(
        f"Audiveris ran successfully but did not create the expected MusicXML "
        f"for {image_path.name} in {out_dir}. Files present: {files}"
    )
