"""The shared polite HTTP client — §8 etiquette, enforced here rather than hoped for."""

from __future__ import annotations

import email.message
import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from jobfinder.sources.http import (
    USER_AGENT,
    HostThrottle,
    PoliteClient,
    RequestBudgetExhausted,
    SourceUnavailable,
)


class FakeResponse:
    def __init__(self, body=b"{}", status=200, headers=None):
        self._body = body
        self.status = status
        self.headers = email.message.Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def read(self):
        return self._body

    def close(self):
        pass


class FakeOpener:
    """Records every request it serves; answers from a script of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def urls(self):
        return [request.full_url for request in self.requests]


def make_client(opener, tmp_path: Path, **overrides) -> tuple[PoliteClient, dict]:
    """A client with a fake clock, a sleep recorder and deterministic jitter.

    The fake clock advances when the client sleeps, the way real time does —
    otherwise waits stack up in ways physical time would never see.
    """
    sleeps: list[float] = []
    state = {"now": 1000.0}

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        state["now"] += seconds

    parts = dict(
        cache_dir=tmp_path / "http-cache",
        opener=opener,
        clock=lambda: state["now"],
        sleep=sleep,
        rng=lambda a, b: 0.5,
        # Its own throttle, so one test's fake clock cannot reach another's.
        # Production clients deliberately share one — see TestSharedThrottle.
        throttle=HostThrottle(),
    )
    parts.update(overrides)
    return PoliteClient(**parts), {"sleeps": sleeps, "state": state}


class TestSharedThrottle:
    """§8 rule 2: the gap belongs to the host, not to whoever is fetching it.

    Every adapter gets its own client — its own budget, its own cache handle.
    If each also kept its own idea of when the host was next free, two
    adapters pointed at one host would both think they were clear and §8
    rule 1 would be broken with nothing failing.
    """

    def pair(self, tmp_path, throttle, **overrides):
        """Two clients on one shared clock, so their waits are comparable."""
        state = {"now": 1000.0}
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            state["now"] += seconds

        def build(name):
            return PoliteClient(
                cache_dir=tmp_path / name,
                opener=FakeOpener([FakeResponse(b"{}")]),
                clock=lambda: state["now"],
                sleep=sleep,
                rng=lambda a, b: 0.5,
                throttle=throttle,
                min_delay=3.0,
                jitter=1.0,
            )

        return build("one"), build("two"), sleeps

    def test_two_clients_on_the_same_host_wait_for_each_other(self, tmp_path):
        first, second, sleeps = self.pair(tmp_path, HostThrottle())

        first.get("https://example.org/a")
        second.get("https://example.org/b")

        assert sleeps == [pytest.approx(3.5)]  # the second client waited its turn

    def test_two_clients_on_different_hosts_do_not_wait(self, tmp_path):
        first, second, sleeps = self.pair(tmp_path, HostThrottle())

        first.get("https://example.org/a")
        second.get("https://other.example/b")

        assert sleeps == []  # different hosts, no reason to queue

    def test_clients_share_one_throttle_unless_told_otherwise(self, tmp_path):
        assert PoliteClient(cache_dir=None).throttle is PoliteClient(cache_dir=None).throttle

    def test_concurrent_requests_to_one_host_are_still_spaced(self, tmp_path):
        # The reason the throttle needs a lock: without one, three threads all
        # read "the host is free" before any of them writes the next slot.
        import threading
        import time

        throttle = HostThrottle()
        stamps: list[float] = []
        guard = threading.Lock()

        def opener(request, timeout=None):
            with guard:
                stamps.append(time.monotonic())
            return FakeResponse(b"{}")

        def fetch(index: int) -> None:
            client = PoliteClient(
                cache_dir=None,
                opener=opener,
                throttle=throttle,
                min_delay=0.05,
                jitter=0.0,
            )
            client.get(f"https://example.org/{index}")

        threads = [threading.Thread(target=fetch, args=(i,)) for i in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        gaps = [b - a for a, b in zip(sorted(stamps), sorted(stamps)[1:], strict=False)]
        assert len(stamps) == 3
        assert all(gap >= 0.04 for gap in gaps), gaps


def test_first_request_to_a_host_never_waits(tmp_path):
    opener = FakeOpener([FakeResponse(b"{}")])
    client, fake = make_client(opener, tmp_path)
    client.get("https://rest.arbeitsagentur.de/pc/v6/jobs")
    assert fake["sleeps"] == []


def test_http_client_waits_between_requests_to_the_same_host(tmp_path):
    opener = FakeOpener([FakeResponse(b"{}"), FakeResponse(b"{}")])
    client, fake = make_client(opener, tmp_path, min_delay=3.0, jitter=1.0)
    client.get("https://example.org/a")
    client.get("https://example.org/b")
    # 3 s minimum + 0.5 s deterministic jitter, minus the 0 s the fake clock advanced
    assert fake["sleeps"] == [pytest.approx(3.5)]


def test_jitter_stays_within_bounds(tmp_path):
    for rng_value, expected in ((lambda a, b: a, 3.0), (lambda a, b: b, 4.0)):
        opener = FakeOpener([FakeResponse(b"{}"), FakeResponse(b"{}")])
        client, fake = make_client(opener, tmp_path / f"cache-{expected}", rng=rng_value)
        client.get("https://example.org/a")
        client.get("https://example.org/a2")
        assert fake["sleeps"] == [pytest.approx(expected)]


def test_time_that_already_passed_reduces_the_wait(tmp_path):
    opener = FakeOpener([FakeResponse(b"{}"), FakeResponse(b"{}")])
    client, fake = make_client(opener, tmp_path)
    client.get("https://example.org/a")
    fake["state"]["now"] = 1002.0  # two of the 3.5 s already elapsed
    client.get("https://example.org/b")
    assert fake["sleeps"] == [pytest.approx(1.5)]


def test_different_hosts_do_not_wait_for_each_other(tmp_path):
    opener = FakeOpener([FakeResponse(b"{}"), FakeResponse(b"{}")])
    client, fake = make_client(opener, tmp_path)
    client.get("https://example.org/a")
    client.get("https://other.example.com/a")
    assert fake["sleeps"] == []


def test_http_client_serves_second_identical_request_from_cache(tmp_path):
    opener = FakeOpener([FakeResponse(b'{"once": true}')])
    client, _ = make_client(opener, tmp_path)
    first = client.get("https://example.org/jobs", params={"was": "Kellner"})
    second = client.get("https://example.org/jobs", params={"was": "Kellner"})
    assert len(opener.requests) == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.body == b'{"once": true}'


def test_expired_cache_entry_is_refetched(tmp_path):
    opener = FakeOpener([FakeResponse(b"v1"), FakeResponse(b"v2")])
    client, _ = make_client(opener, tmp_path, ttl_seconds=0)
    client.get("https://example.org/jobs")
    assert client.get("https://example.org/jobs").body == b"v2"


def test_only_successful_responses_are_cached(tmp_path):
    opener = FakeOpener([FakeResponse(b"nope", status=500), FakeResponse(b"good")])
    client, _ = make_client(opener, tmp_path)
    client.get("https://example.org/jobs")
    assert client.get("https://example.org/jobs").body == b"good"


def test_cache_hits_do_not_count_against_the_budget(tmp_path):
    opener = FakeOpener([FakeResponse(b"1"), FakeResponse(b"2"), FakeResponse(b"3")])
    client, _ = make_client(opener, tmp_path, budget=2)
    client.get("https://example.org/a")
    client.get("https://example.org/a")  # cache, free
    client.get("https://example.org/b")  # second network call, budget now spent
    with pytest.raises(RequestBudgetExhausted):
        client.get("https://example.org/c")


def test_request_budget_is_enforced_on_retries_too(tmp_path):
    opener = FakeOpener([FakeResponse(b"slow down", status=429, headers={"Retry-After": "1"})] * 3)
    client, fake = make_client(opener, tmp_path, budget=2, max_retries=3)
    with pytest.raises(RequestBudgetExhausted):
        client.get("https://example.org/a")
    assert len(opener.requests) == 2


def test_retry_after_header_is_honoured(tmp_path):
    opener = FakeOpener(
        [
            FakeResponse(b"slow down", status=429, headers={"Retry-After": "2"}),
            FakeResponse(b"ok"),
        ]
    )
    client, fake = make_client(opener, tmp_path)
    response = client.get("https://example.org/jobs")
    assert response.status == 200
    # The site's 2 s demand is honoured, then the remaining 1.5 s of the host's
    # own 3.5 s gap — both constraints respected, total gap exactly the larger one.
    assert fake["sleeps"] == [2.0, pytest.approx(1.5)]


def test_503_is_retried_with_backoff_then_succeeds(tmp_path):
    opener = FakeOpener([FakeResponse(b"unavailable", status=503), FakeResponse(b"ok")])
    client, fake = make_client(opener, tmp_path, backoff_base=4.0)
    response = client.get("https://example.org/jobs")
    assert response.status == 200
    # A 4 s backoff already satisfies the 3.5 s host gap — no extra throttle wait.
    assert fake["sleeps"] == [pytest.approx(4.0)]


def test_exhausted_retries_raise_source_unavailable(tmp_path):
    opener = FakeOpener([FakeResponse(b"no", status=429, headers={"Retry-After": "1"})] * 3)
    client, _ = make_client(opener, tmp_path, max_retries=2)
    with pytest.raises(SourceUnavailable, match="example.org"):
        client.get("https://example.org/jobs")
    assert len(opener.requests) == 3  # initial + 2 retries


def test_connection_errors_are_retried_not_raised_immediately(tmp_path):
    opener = FakeOpener([urllib.error.URLError("connection reset"), FakeResponse(b"ok")])
    client, fake = make_client(opener, tmp_path, backoff_base=2.0)
    assert client.get("https://example.org/jobs").status == 200
    # 2 s backoff for the transport failure, then the remaining host gap.
    assert fake["sleeps"] == [pytest.approx(2.0), pytest.approx(1.5)]


def test_http_error_object_comes_back_as_a_response(tmp_path):
    error = urllib.error.HTTPError(
        "https://example.org/gone",
        404,
        "Not Found",
        email.message.Message(),
        io.BytesIO(b"nothing here"),
    )
    opener = FakeOpener([error])
    client, _ = make_client(opener, tmp_path)
    response = client.get("https://example.org/gone")
    assert response.status == 404
    assert response.body == b"nothing here"


def test_every_request_carries_the_identifying_user_agent(tmp_path):
    opener = FakeOpener([FakeResponse(b"{}")])
    client, _ = make_client(opener, tmp_path)
    client.get("https://example.org/jobs")
    sent = opener.requests[0].get_header("User-agent")
    assert sent == USER_AGENT
    assert sent.startswith("JobFinder/")


def test_params_are_percent_encoded_into_the_url(tmp_path):
    opener = FakeOpener([FakeResponse(b"{}")])
    client, _ = make_client(opener, tmp_path)
    client.get("https://example.org/jobs", params={"wo": "München", "arbeitszeit": ["mj", "tz"]})
    url = opener.urls[0]
    assert "wo=M%C3%BCnchen" in url
    assert "arbeitszeit=mj&arbeitszeit=tz" in url


def test_get_json_parses_the_body(tmp_path):
    opener = FakeOpener([FakeResponse('{"key": "wért"}'.encode())])
    client, _ = make_client(opener, tmp_path)
    assert client.get_json("https://example.org/jobs") == {"key": "wért"}


class TestPost:
    """Overpass takes its query as a POST body, and §8 applies to it identically.

    A second client beside this one would be how a source quietly stops
    honouring the spacing, the budget and the cache — so POST is the same
    machinery with a body, not a new path.
    """

    def test_a_post_sends_its_body_and_returns_the_response(self, tmp_path):
        opener = FakeOpener([FakeResponse(b'{"elements": []}')])
        client, _ = make_client(opener, tmp_path)

        response = client.post("https://overpass.example/api/interpreter", body="out tags;")

        assert response.status == 200
        assert response.json() == {"elements": []}
        request = opener.requests[0]
        assert request.get_method() == "POST"
        assert request.data == b"out tags;"

    def test_a_post_carries_the_identifying_user_agent(self, tmp_path):
        opener = FakeOpener([FakeResponse(b"{}")])
        client, _ = make_client(opener, tmp_path)

        client.post("https://overpass.example/api/interpreter", body="out;")

        assert opener.requests[0].get_header("User-agent") == USER_AGENT

    def test_a_post_waits_between_requests_to_the_same_host(self, tmp_path):
        opener = FakeOpener([FakeResponse(b"{}"), FakeResponse(b"{}")])
        client, recorded = make_client(opener, tmp_path, min_delay=3.0)

        client.post("https://overpass.example/api/interpreter", body="one")
        client.post("https://overpass.example/api/interpreter", body="two")

        assert recorded["sleeps"] == [pytest.approx(3.5)]

    def test_a_post_counts_against_the_same_request_budget(self, tmp_path):
        opener = FakeOpener([FakeResponse(b"{}"), FakeResponse(b"{}")])
        client, _ = make_client(opener, tmp_path, budget=1)

        client.post("https://overpass.example/api/interpreter", body="one")

        with pytest.raises(RequestBudgetExhausted):
            client.post("https://overpass.example/api/interpreter", body="two")

    def test_two_posts_with_different_bodies_are_cached_separately(self, tmp_path):
        """One URL, many queries: if the body is not in the cache key, the
        second tag's answer is the first tag's places."""
        opener = FakeOpener([FakeResponse(b'{"n": 1}'), FakeResponse(b'{"n": 2}')])
        client, _ = make_client(opener, tmp_path)

        first = client.post("https://overpass.example/api/interpreter", body="cafe")
        second = client.post("https://overpass.example/api/interpreter", body="bakery")

        assert first.json() == {"n": 1}
        assert second.json() == {"n": 2}

    def test_a_cached_post_is_not_sent_again(self, tmp_path):
        opener = FakeOpener([FakeResponse(b'{"n": 1}')])
        client, _ = make_client(opener, tmp_path)

        client.post("https://overpass.example/api/interpreter", body="cafe")
        again = client.post("https://overpass.example/api/interpreter", body="cafe")

        assert again.from_cache is True
        assert client.network_calls == 1

    def test_a_post_honours_retry_after(self, tmp_path):
        opener = FakeOpener(
            [
                FakeResponse(b"slow down", status=429, headers={"Retry-After": "7"}),
                FakeResponse(b"{}"),
            ]
        )
        client, recorded = make_client(opener, tmp_path, min_delay=0.0, jitter=0.0)

        client.post("https://overpass.example/api/interpreter", body="cafe")

        assert 7.0 in recorded["sleeps"]

    def test_a_post_that_keeps_failing_raises_source_unavailable(self, tmp_path):
        opener = FakeOpener([FakeResponse(b"busy", status=504) for _ in range(4)])
        client, _ = make_client(opener, tmp_path, min_delay=0.0, jitter=0.0, max_retries=3)

        with pytest.raises(SourceUnavailable) as failed:
            client.post("https://overpass.example/api/interpreter", body="cafe")

        assert "overpass.example" in str(failed.value)

    def test_a_post_json_parses_the_body(self, tmp_path):
        opener = FakeOpener([FakeResponse('{"name": "Bäckerei"}'.encode())])
        client, _ = make_client(opener, tmp_path)

        assert client.post_json("https://overpass.example/api/interpreter", body="q") == {
            "name": "Bäckerei"
        }


class TestGatewayFailuresAreRetried:
    """A 502 or a 504 means the request never completed, so retrying is right.

    Measured on Overpass 2026-08-17: the public endpoint answered `504` to every
    attempt for four minutes while its own backends served the same query in
    under a second. Treating that as a final answer hands the adapter a gateway
    error page where it expected JSON — and calls a working source dead.
    """

    @pytest.mark.parametrize("status", [502, 504])
    def test_a_gateway_failure_is_retried_and_can_succeed(self, tmp_path, status):
        opener = FakeOpener([FakeResponse(b"gateway", status=status), FakeResponse(b'{"ok": 1}')])
        client, _ = make_client(opener, tmp_path, min_delay=0.0, jitter=0.0)

        response = client.get("https://overpass.example/api/interpreter")

        assert response.json() == {"ok": 1}
        assert client.network_calls == 2

    def test_a_client_error_is_not_retried(self, tmp_path):
        """404 and 403 are answers. Retrying them wastes the budget and, on a
        board that blocks us, looks like hammering."""
        opener = FakeOpener([FakeResponse(b"nope", status=404)])
        client, _ = make_client(opener, tmp_path, min_delay=0.0, jitter=0.0)

        response = client.get("https://example.org/gone")

        assert response.status == 404
        assert client.network_calls == 1
