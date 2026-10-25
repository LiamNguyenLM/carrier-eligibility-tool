"""Round 43 step 1: every data file the engine reads (the rules tables and map lines, CFIG knowledge, the Occidental
counties, the Texas county and ZIP tables) goes through open_text(). Natively it opens the file in the repo. The
browser registers the bundle's files first (register), so the engine reads them from memory and touches no file
system; with strict=True a file that was not registered is an error, never a silent read from disk."""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILES = {}
_STRICT = []


def register(files, strict=False):
    """files: {path relative to the repo root, with forward slashes: its text}."""
    _FILES.update({k.replace("\\", "/"): v for k, v in files.items()})
    _STRICT[:] = [True] if strict else []


def relpath(path):
    return os.path.relpath(os.path.abspath(path), ROOT).replace("\\", "/")


def open_text(path, encoding="utf-8"):
    """A text file object for path, as open(path, encoding=encoding) gives."""
    rel = relpath(path)
    if rel in _FILES:
        text = _FILES[rel]
        if encoding == "utf-8-sig" and text.startswith("\ufeff"):
            text = text[1:]
        return io.StringIO(text)
    if _STRICT:
        raise FileNotFoundError(f"engine data file not in the bundle: {rel}")
    return open(path, encoding=encoding)
