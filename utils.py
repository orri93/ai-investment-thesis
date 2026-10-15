"""Small helpers shared by the command-line entry points."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent


def load_environment(env_file: Path | None = None) -> None:
    """Load settings from the git-ignored .env file; real environment variables win."""
    load_dotenv(env_file or ROOT_DIR / ".env", override=False)


def ticker_from_thesis_path(thesis_path: Path) -> str:
    ticker = thesis_path.stem.strip().upper()
    if not ticker:
        raise ValueError(f"Could not derive ticker from thesis file name: {thesis_path}")
    return ticker


def first_content_line(text: str) -> str:
    """Return the first non-empty line that is not a markdown heading."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return "(no content)"


def extract_json_object(text: str) -> str:
    """Return the JSON object embedded in a model response (code fences allowed).

    Raises ValueError when no object is present.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
        stripped = "\n".join(lines).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    raise ValueError("Response did not contain a JSON object.")


def pretty_json(text: str) -> str:
    """Pretty-print the JSON object in text, or return text unchanged if it is not JSON."""
    try:
        return json.dumps(json.loads(extract_json_object(text)), indent=2)
    except ValueError:
        return text


def write_text_atomic(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text so readers (and crashes) never see a partially written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def report_unexpected_error(exc: BaseException, *, verbose: bool, prefix: str = "- ") -> None:
    print(f"{prefix}Unexpected error: {exc}", file=sys.stderr)
    if verbose:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    else:
        print(f"{prefix}(run with --verbose for the full traceback)", file=sys.stderr)
