"""Screenplay corpus sources for the `corpus` verification tier.

Breakdown has to survive real screenplays: dual dialogue, `CONT'D`, montages,
`OMITTED` scenes, and four different scene-numbering conventions in four different
films. Authored fixtures do not produce that mess, because whoever writes them writes
what the parser already handles.

So this fetches real ones. Three properties keep it from becoming a liability:

- **Nothing copyrighted is committed.** The config holds an address and a hash. The
  bytes live in a gitignored cache, and the application distributes no screenplays at
  all -- in production the user uploads their own.
- **A source that changed is not a source.** Studios replace a draft at the same URL
  between publication and awards night. The hash is checked on every use, and a
  mismatch raises instead of quietly handing back a different film (`BRK-006`).
- **An unavailable source never reads as a pass.** FYC postings come down after the
  season; that is their normal lifecycle, not an incident. Missing sources are
  reported and the test skips, because a green tier that checked nothing is worse
  than a red one (`BRK-008`).

This module has no product code in it and is not importable from `coverset`. The
breakdown agent takes bytes, the same in test as in production, so acquiring those
bytes is a fixture concern and stays here (`BRK-007`).
"""

from __future__ import annotations

import hashlib
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CorpusError",
    "CorpusSource",
    "CorpusUnavailable",
    "ensure_local",
    "load_sources",
]

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "fixtures" / "corpus" / "sources.toml"
LOCAL_CONFIG = ROOT / "fixtures" / "corpus" / "sources.local.toml"
CACHE = ROOT / ".cache" / "corpus"

MEDIA = {"pdf", "text"}
_REQUIRED = ("id", "url", "sha256", "media")
_TIMEOUT_SECONDS = 60


class CorpusError(Exception):
    """The corpus configuration is malformed, or a document is not what was recorded.

    Reports every problem found rather than the first, matching `load_scenes` and
    `load_constraints`: someone fixing a config file wants the whole list.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("\n".join(problems))


class CorpusUnavailable(Exception):
    """A configured source could not be fetched.

    Distinct from `CorpusError` on purpose. A malformed config is a mistake someone
    made and should fail. A 404 on a screenplay a studio pulled is the expected end
    of that document's life, and the right response is to skip and say so.
    """


@dataclass(frozen=True, slots=True)
class CorpusSource:
    """One screenplay the corpus tier may run against."""

    id: str
    url: str
    sha256: str
    media: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("a corpus source needs a stable id")
        if len(self.sha256) != 64 or not all(c in "0123456789abcdef" for c in self.sha256):
            raise ValueError(f"{self.id}: sha256 must be 64 lowercase hex characters")
        if self.media not in MEDIA:
            raise ValueError(f"{self.id}: media must be one of {', '.join(sorted(MEDIA))}")

    @property
    def cached_at(self) -> Path:
        # Keyed by hash, not by id: if the recorded hash changes the old bytes are
        # still there under their own name, so a swapped draft is visible rather than
        # overwritten.
        return CACHE / f"{self.id}-{self.sha256[:12]}.{self.media}"


def _read(path: Path, problems: list[str]) -> list[dict]:
    if not path.exists():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        problems.append(f"{path.name}: not valid TOML: {exc}")
        return []
    entries = raw.get("source", [])
    if not isinstance(entries, list):
        problems.append(f"{path.name}: 'source' must be an array of tables")
        return []
    for entry in entries:
        if isinstance(entry, dict):
            entry["_file"] = path.name
    return [e for e in entries if isinstance(e, dict)]


def load_sources(
    *,
    config: Path | None = None,
    local_config: Path | None = None,
) -> tuple[CorpusSource, ...]:
    """Load and validate corpus sources from the committed and local config files.

    The local file wins on a shared id, so a stale committed entry can be pointed at
    a working URL without editing anything the whole team shares.

    Raises:
        CorpusError: listing every problem across both files.
    """
    config = CONFIG if config is None else config
    local_config = LOCAL_CONFIG if local_config is None else local_config

    problems: list[str] = []
    merged: dict[str, dict] = {}

    for path in (config, local_config):
        for i, entry in enumerate(_read(path, problems)):
            where = f"{entry.get('_file', path.name)}[{i}]"
            if sid := entry.get("id"):
                where = f"{entry['_file']} source {sid!r}"
            if missing := [f for f in _REQUIRED if not entry.get(f)]:
                problems.append(f"{where}: missing required field(s) {', '.join(missing)}")
                continue
            merged[entry["id"]] = entry

    sources: list[CorpusSource] = []
    for entry in merged.values():
        try:
            sources.append(
                CorpusSource(
                    id=entry["id"],
                    url=entry["url"],
                    sha256=str(entry["sha256"]).strip().lower(),
                    media=str(entry["media"]).strip().lower(),
                    note=str(entry.get("note", "")),
                )
            )
        except ValueError as exc:
            problems.append(f"{entry.get('_file', '?')} source {entry['id']!r}: {exc}")

    if problems:
        raise CorpusError(problems)
    return tuple(sorted(sources, key=lambda s: s.id))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure_local(source: CorpusSource, *, fetch=None) -> Path:
    """Return a local path holding exactly the bytes `source` records.

    Cached across runs, because a test suite that re-downloads a studio's PDF on every
    invocation is rude to them and slow for us.

    The hash is verified on the cached copy too, not only on download. A cache is a
    file on a laptop; it can be truncated, half-written, or edited by someone poking
    at it. Trusting it because we wrote it once is the same mistake as trusting a
    solver because a solver produced it.

    Raises:
        CorpusUnavailable: the document could not be fetched, or no longer matches.
    """
    fetch = _fetch if fetch is None else fetch
    cached = source.cached_at

    if cached.exists():
        data = cached.read_bytes()
        if _digest(data) == source.sha256:
            return cached
        # Do not silently re-download over it: the difference is the finding.
        cached.rename(cached.with_suffix(cached.suffix + ".mismatched"))
        raise CorpusUnavailable(
            f"{source.id}: cached copy no longer matches the recorded hash. "
            f"Moved aside as {cached.name}.mismatched"
        )

    try:
        data = fetch(source.url)
    except Exception as exc:  # noqa: BLE001 -- any transport failure is unavailability
        raise CorpusUnavailable(f"{source.id}: could not fetch {source.url} -- {exc}") from exc

    actual = _digest(data)
    if actual != source.sha256:
        raise CorpusUnavailable(
            f"{source.id}: {source.url} now serves a different document "
            f"(sha256 {actual[:12]}..., recorded {source.sha256[:12]}...). "
            f"Studios replace drafts at the same URL -- check what it is now, then "
            f"update the hash deliberately rather than to make this pass."
        )

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return cached


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(  # noqa: S310 -- corpus URLs are operator-supplied
        url,
        headers={"User-Agent": "coverset-corpus/1.0 (screenplay breakdown testing)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise CorpusUnavailable(f"HTTP {exc.code} {exc.reason}") from exc
