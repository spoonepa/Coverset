"""Offline harness for the grounding path.

Tests drive the real `parallel-web` client through a mock HTTP transport rather
than stubbing the client object. That keeps the SDK's own request serialization
and response validation inside the test: if a parameter name drifts or a response
field changes shape, these tests fail instead of passing against a fake that has
quietly diverged from the API.

The payload builders take a `dated` flag because the defect these tests were
written after was not a malformed response -- it was a perfectly well-formed one
describing the wrong day.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from parallel import Parallel

SEARCH_PATH = "/v1/search"
EXTRACT_PATH = "/v1/extract"

PERMIT_URL = "https://www.savannahga.gov/957/Filming-Regulations"
FORECAST_URL = "https://www.predictwind.com/weather/united-states/georgia/savannah"
NEWS_URL = "https://www.wjcl.com/article/lowcountry-heavy-rain"

ON_DATE_FORECAST = "### Tue, Mar 17\nPrecipitation probability 85%. Wind 12 kt.\n"
OFF_DATE_FORECAST = "### Wed, Mar 11\nPrecipitation probability 20%. Wind 6 kt.\n"
PERMIT_RULES = (
    "# Filming Regulations\n\n**Section 11.02**\n\n"
    "| Zone | Permitted hours |\n|---|---|\n| Historic District | 07:00-22:00 |\n"
)


@dataclass
class Call:
    """One request the SDK actually put on the wire."""

    path: str
    body: dict[str, Any]

    @property
    def settings(self) -> dict[str, Any]:
        return self.body.get("advanced_settings") or {}

    @property
    def source_policy(self) -> dict[str, Any]:
        return self.settings.get("source_policy") or {}


@dataclass
class Recorder:
    """Captures wire traffic so tests can assert the runtime call actually happened."""

    calls: list[Call] = field(default_factory=list)

    def paths(self) -> list[str]:
        return [c.path for c in self.calls]

    def of(self, path: str) -> list[Call]:
        return [c for c in self.calls if c.path == path]

    def only(self, path: str) -> Call:
        matching = self.of(path)
        assert len(matching) == 1, f"expected exactly one {path} call, got {len(matching)}"
        return matching[0]


def _result(url: str, excerpt: str, *, title: str | None = None, published: str | None = None):
    return {"url": url, "excerpts": [excerpt], "title": title, "publish_date": published}


def search_payload(
    *,
    results: list[dict[str, Any]] | None = None,
    search_id: str = "search_cad0a6d2dec046bd95ae900527d880e7",
    session_id: str = "sess_grounding_001",
) -> dict[str, Any]:
    """Search results whose excerpts are on-topic but carry no usable date."""
    if results is None:
        results = [
            _result(FORECAST_URL, "Current conditions in Savannah. 26%.",
                    title="Savannah Weather Forecast", published="2026-03-16"),
            _result(PERMIT_URL, "Filming is prohibited after 10:00 PM.",
                    title="Filming Regulations | Savannah, GA", published="2025-11-02"),
            _result(NEWS_URL, "Heavy rain expected across the Lowcountry.",
                    title="Lowcountry rain - WJCL", published="2026-03-16"),
        ]
    return {"results": results, "search_id": search_id, "session_id": session_id}


def permit_search_payload(**kw: Any) -> dict[str, Any]:
    """Search results as they arrive for a permit query: ordinance ranked first."""
    return search_payload(
        results=[
            _result(PERMIT_URL, "Filming is prohibited after 10:00 PM.",
                    title="Filming Regulations | Savannah, GA", published="2025-11-02"),
            _result(NEWS_URL, "Heavy rain expected across the Lowcountry.",
                    title="Lowcountry rain - WJCL", published="2026-03-16"),
        ],
        **kw,
    )


def extract_payload(
    *,
    dated: bool = True,
    urls: list[str] | None = None,
    full_content: str | None = None,
    omit_full_content: bool = False,
    session_id: str = "sess_grounding_001",
) -> dict[str, Any]:
    """Full-content results. `dated=False` returns a well-formed *wrong day*.

    `omit_full_content` models Extract succeeding but returning no page body, which
    is distinct from passing `full_content=None` (meaning "use the default").
    """
    body = None if omit_full_content else (
        full_content if full_content is not None
        else (ON_DATE_FORECAST if dated else OFF_DATE_FORECAST)
    )
    return {
        "results": [
            {
                "url": u,
                "excerpts": ["Precipitation probability for the period."],
                "full_content": body,
                "title": "Savannah Weather Forecast",
                "publish_date": "2026-03-16",
            }
            for u in (urls or [FORECAST_URL])
        ],
        "errors": [],
        "extract_id": "extract_cad0a6d2dec046bd95ae900527d880e7",
        "session_id": session_id,
    }


def permit_extract_payload(session_id: str = "sess_grounding_001") -> dict[str, Any]:
    return extract_payload(urls=[PERMIT_URL], full_content=PERMIT_RULES, session_id=session_id)


@pytest.fixture
def parallel_stub():
    """Build a real `Parallel` client whose transport is recorded, not networked."""

    def build(
        *,
        search: dict[str, Any] | None = None,
        extract: dict[str, Any] | None = None,
        search_status: int = 200,
        extract_status: int = 200,
    ) -> tuple[Parallel, Recorder]:
        recorder = Recorder()
        search_body = search if search is not None else search_payload()
        extract_body = extract if extract is not None else extract_payload()

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else {}
            recorder.calls.append(Call(path=request.url.path, body=body))
            if request.url.path == SEARCH_PATH:
                return httpx.Response(search_status, json=search_body)
            if request.url.path == EXTRACT_PATH:
                return httpx.Response(extract_status, json=extract_body)
            return httpx.Response(404, json={"error": "unrouted"})

        client = Parallel(
            api_key="test-key-not-a-real-credential",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )
        return client, recorder

    return build
