"""The corpus harness, verified offline.

The harness exists to stop a screenplay corpus from lying to a test: a swapped draft,
a truncated cache, a dead link counted as a pass. Those guards are the whole value, so
they are exercised here with local bytes and a fake fetcher rather than in the tier
that needs the network.

No test in this file touches the internet.
"""

from __future__ import annotations

import hashlib
import textwrap

import pytest

from corpus import (
    CorpusError,
    CorpusSource,
    CorpusUnavailable,
    ensure_local,
    load_sources,
)

SCRIPT = b"INT. CHURCH OFFICE - DAY\n\nSarah pushes in. Elias is already there.\n"
DIGEST = hashlib.sha256(SCRIPT).hexdigest()


def _config(tmp_path, body: str, name: str = "sources.toml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _source(tmp_path, **overrides) -> CorpusSource:
    fields = dict(id="demo", url="https://example.invalid/s.txt", sha256=DIGEST, media="text")
    fields.update(overrides)
    source = CorpusSource(**fields)
    object.__setattr__(source, "id", fields["id"])
    return source


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Point the module's cache at a temp dir so runs cannot see each other."""
    import corpus

    monkeypatch.setattr(corpus, "CACHE", tmp_path / "cache")
    return tmp_path / "cache"


@pytest.mark.req("BRK-007")
def test_a_corpus_with_no_sources_is_empty_rather_than_an_error(tmp_path):
    # Shipping an empty corpus is the default state, not a misconfiguration. It has
    # to load cleanly so the tier can skip with a reason instead of erroring.
    config = _config(tmp_path, "# nothing configured\n")
    assert load_sources(config=config, local_config=tmp_path / "absent.toml") == ()


@pytest.mark.req("BRK-006")
def test_every_config_problem_is_reported_at_once(tmp_path):
    # One error per run turns fixing a corpus file into a loop. Same reason
    # load_scenes and load_constraints report in full.
    config = _config(
        tmp_path,
        f"""
        [[source]]
        id = "no-url"
        sha256 = "{DIGEST}"
        media = "text"

        [[source]]
        id = "bad-hash"
        url = "https://example.invalid/a.pdf"
        sha256 = "nope"
        media = "pdf"

        [[source]]
        id = "bad-media"
        url = "https://example.invalid/b.pdf"
        sha256 = "{DIGEST}"
        media = "fountain"
        """,
    )
    with pytest.raises(CorpusError) as caught:
        load_sources(config=config, local_config=tmp_path / "absent.toml")

    reported = "\n".join(caught.value.problems)
    assert "no-url" in reported and "url" in reported
    assert "bad-hash" in reported
    assert "bad-media" in reported
    assert len(caught.value.problems) == 3


@pytest.mark.req("BRK-007")
def test_a_local_entry_overrides_a_committed_one_with_the_same_id(tmp_path):
    # So a stale committed URL can be repointed locally without editing a file the
    # whole team shares, which is what makes committed entries survivable at all.
    committed = _config(
        tmp_path,
        f"""
        [[source]]
        id = "drama"
        url = "https://studio.invalid/old.pdf"
        sha256 = "{DIGEST}"
        media = "pdf"
        """,
    )
    local = _config(
        tmp_path,
        f"""
        [[source]]
        id = "drama"
        url = "https://studio.invalid/moved.pdf"
        sha256 = "{DIGEST}"
        media = "pdf"
        """,
        name="sources.local.toml",
    )
    (source,) = load_sources(config=committed, local_config=local)
    assert source.url == "https://studio.invalid/moved.pdf"


@pytest.mark.req("BRK-006")
def test_a_document_that_no_longer_matches_its_hash_is_refused(tmp_path, cache):
    # The failure this guard exists for: a studio replaces a draft at the same URL,
    # the download succeeds, and the corpus is now a different film. Nothing about
    # the bytes looks wrong -- only the hash knows.
    source = _source(tmp_path)
    swapped = b"INT. SOMEWHERE ELSE - NIGHT\n\nA different draft entirely.\n"

    with pytest.raises(CorpusUnavailable) as caught:
        ensure_local(source, fetch=lambda _: swapped)

    assert "different document" in str(caught.value)
    assert not source.cached_at.exists(), "a mismatched document must not be cached"


@pytest.mark.req("BRK-006")
def test_a_matching_document_is_cached_and_reused(tmp_path, cache):
    source = _source(tmp_path)
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return SCRIPT

    first = ensure_local(source, fetch=fetch)
    assert first.read_bytes() == SCRIPT

    second = ensure_local(source, fetch=fetch)
    assert second == first
    assert calls == [source.url], "a cached document must not be re-downloaded"


@pytest.mark.req("BRK-006")
def test_a_corrupted_cache_is_refused_rather_than_trusted(tmp_path, cache):
    # A cache is a file on a laptop. Trusting it because we wrote it once is the same
    # mistake as trusting a solver because a solver produced it.
    source = _source(tmp_path)
    ensure_local(source, fetch=lambda _: SCRIPT)
    source.cached_at.write_bytes(b"truncated")

    with pytest.raises(CorpusUnavailable) as caught:
        ensure_local(source, fetch=lambda _: SCRIPT)

    assert "no longer matches" in str(caught.value)
    assert source.cached_at.with_suffix(source.cached_at.suffix + ".mismatched").exists()


@pytest.mark.req("BRK-008")
def test_an_unreachable_source_raises_unavailable_not_error(tmp_path, cache):
    # The distinction the tier depends on: a dead link is the expected end of an FYC
    # posting's life and must skip, while a malformed config is someone's mistake and
    # must fail. Collapsing them means either real breakage hides or normal rot fails
    # the gate until someone deletes the test.
    source = _source(tmp_path)

    def fetch(_: str) -> bytes:
        raise OSError("Name or service not known")

    with pytest.raises(CorpusUnavailable):
        ensure_local(source, fetch=fetch)


@pytest.mark.req("BRK-010")
def test_no_screenplay_text_is_committed_to_the_repository():
    # The rights position in one assertion: the repo holds addresses and hashes, and
    # the bytes live in a gitignored cache. If a .pdf or a script-shaped file ever
    # lands under fixtures/corpus, this is the thing that notices.
    from corpus import ROOT

    corpus_dir = ROOT / "fixtures" / "corpus"
    committed = [
        p
        for p in corpus_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".pdf", ".fdx", ".fountain"}
    ]
    assert not committed, (
        "screenplay documents must not be committed -- "
        f"found {[p.name for p in committed]}"
    )

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".cache/corpus/" in gitignore
    assert "sources.local.toml" in gitignore


@pytest.mark.req("BRK-006")
def test_the_shipped_config_parses(tmp_path):
    # The committed file is documentation as much as configuration. If an entry drifts
    # out of the schema it teaches the wrong shape -- so parsing it *is* the assertion:
    # `CorpusSource` validates id, hash and media on construction.
    #
    # This asserted the shipped file was empty while it was. Now that it carries real
    # sources, the same intent is that every committed entry is well-formed and says
    # what it is there for; a source with no note is a link nobody can evaluate.
    shipped = load_sources(local_config=tmp_path / "absent.toml")
    assert shipped, "the committed corpus is empty, so the tier would skip everything"
    assert len({s.id for s in shipped}) == len(shipped), "duplicate source ids"
    for source in shipped:
        assert source.url.startswith("https://"), f"{source.id}: {source.url}"
        assert source.note.strip(), (
            f"{source.id}: a committed source must record why it is in the corpus"
        )
