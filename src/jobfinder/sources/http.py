"""The one HTTP client every source goes through — polite by construction.

§8 of the master plan: requests to one host are spaced out and jittered, every
fetched page is cached on disk for a day, a run has a total request budget,
`Retry-After` is honoured, and the User-Agent says who we are. Adapters never
open sockets themselves.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = (
    "JobFinder/0.1 (personal job search; +https://github.com/MiladBahariQaragoz/JobFinderV2)"
)

RETRYABLE_STATUSES = {429, 503}
CACHE_TTL_SECONDS = 24 * 60 * 60


class RequestBudgetExhausted(Exception):
    """The run's total request budget is spent — stop making calls."""


class SourceUnavailable(Exception):
    """A host refused us past the retry limit — one source, not the run."""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: dict[str, str]
    from_cache: bool = False

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def _real_opener(request, timeout):
    return urllib.request.urlopen(request, timeout=timeout)


class PoliteClient:
    """Throttled, cached, budgeted GET client with injected time for tests."""

    def __init__(
        self,
        *,
        cache_dir: Path | None,
        budget: int = 200,
        min_delay: float = 3.0,
        jitter: float = 1.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        ttl_seconds: int = CACHE_TTL_SECONDS,
        user_agent: str = USER_AGENT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[float, float], float] = random.uniform,
        opener: Callable = _real_opener,
        timeout: float = 30.0,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.budget = budget
        self.min_delay = min_delay
        self.jitter = jitter
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.ttl_seconds = ttl_seconds
        self.user_agent = user_agent
        self.timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self._rng = rng
        self._opener = opener
        self._next_allowed: dict[str, float] = {}
        self.network_calls = 0

    # -- public API ---------------------------------------------------------

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None) -> Response:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params, doseq=True)
        full_url = url + query
        if (cached := self._from_cache(full_url)) is not None:
            return cached

        host = urllib.parse.urlsplit(full_url).netloc
        for attempt in range(self.max_retries + 1):
            response = self._network_get(full_url, host, headers)
            failed = isinstance(response, Exception)
            if not failed and response.status not in RETRYABLE_STATUSES:
                self._to_cache(full_url, response)
                return response
            if attempt == self.max_retries:
                break
            self._wait_before_retry(response, attempt)
        raise SourceUnavailable(
            f"{host} kept refusing requests (status {getattr(response, 'status', 'error')}) "
            f"after {self.max_retries + 1} attempts."
        )

    def get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None):
        return self.get(url, params=params, headers=headers).json()

    # -- internals ----------------------------------------------------------

    def _network_get(self, full_url: str, host: str, headers: dict | None) -> Response | Exception:
        self._throttle(host)
        if self.network_calls >= self.budget:
            raise RequestBudgetExhausted(
                f"Request budget of {self.budget} spent — the run stops rather than flood a host."
            )
        request = urllib.request.Request(
            full_url, headers={"User-Agent": self.user_agent, **(headers or {})}
        )
        self.network_calls += 1
        try:
            raw = self._opener(request, timeout=self.timeout)
        except urllib.error.HTTPError as err:
            raw = err  # an HTTP status is an answer, not an exception, for our purposes
        except Exception as err:  # URLError, timeouts — retryable transport failures
            return err
        try:
            status = int(getattr(raw, "status", None) or getattr(raw, "code", 200) or 200)
            body = raw.read()
            header_obj = getattr(raw, "headers", None)
            flat = {str(k): str(v) for k, v in header_obj.items()} if header_obj else {}
        finally:
            close = getattr(raw, "close", None)
            if close is not None:
                close()
        return Response(status=status, body=body, headers=flat)

    def _throttle(self, host: str) -> None:
        now = self._clock()
        next_allowed = self._next_allowed.get(host)
        if next_allowed is not None and now < next_allowed:
            self._sleep(next_allowed - now)
            now = next_allowed
        self._next_allowed[host] = now + self.min_delay + self._rng(0, self.jitter)

    def _wait_before_retry(self, response: Response | Exception, attempt: int) -> None:
        retry_after = None
        if not isinstance(response, Exception):
            retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                self._sleep(float(retry_after))
                return
            except ValueError:
                pass
        self._sleep(self.backoff_base * (2**attempt))

    # -- on-disk cache ------------------------------------------------------

    def _cache_path(self, full_url: str) -> Path:
        digest = hashlib.sha1(full_url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _from_cache(self, full_url: str) -> Response | None:
        if self.cache_dir is None:
            return None
        path = self._cache_path(full_url)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - envelope["fetched_at"] > self.ttl_seconds:
            return None
        return Response(
            status=envelope["status"],
            body=base64.b64decode(envelope["body_b64"]),
            headers=envelope["headers"],
            from_cache=True,
        )

    def _to_cache(self, full_url: str, response: Response) -> None:
        if self.cache_dir is None or response.status != 200:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        envelope = {
            "url": full_url,
            "status": response.status,
            "headers": response.headers,
            "body_b64": base64.b64encode(response.body).decode("ascii"),
            "fetched_at": time.time(),
        }
        tmp = self._cache_path(full_url).with_suffix(".tmp")
        tmp.write_text(json.dumps(envelope), encoding="utf-8")
        tmp.replace(self._cache_path(full_url))
