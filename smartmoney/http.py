"""Polite, rate-limited HTTP. SEC allows 10 req/s; we stay well under."""
import os
import time, threading, requests

# SEC asks automated clients to identify themselves with a contact address and
# will throttle those that don't. In CI this comes from the SEC_CONTACT
# repository variable so the address is not baked into a public repo.
_CONTACT = os.environ.get("SEC_CONTACT", "").strip()
UA = f"the-tape research tool ({_CONTACT})" if _CONTACT else \
     "the-tape research tool (contact: set SEC_CONTACT env var)"

class Throttle:
    def __init__(self, per_sec=4.0):
        self.min_gap = 1.0 / per_sec
        self.last = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            gap = time.monotonic() - self.last
            if gap < self.min_gap:
                time.sleep(self.min_gap - gap)
            self.last = time.monotonic()

_throttle = Throttle()
_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})


class BlockedError(RuntimeError):
    """Raised when the far end is clearly refusing us, not just hiccuping."""


# A shared runner IP can get throttled by SEC because of what OTHER people ran
# from it. Retrying every one of a few hundred filings through a 1+2+4s backoff
# turns that into an hour of sleeping, so we count consecutive failures and give
# up loudly instead of grinding.
_consecutive_failures = [0]
MAX_CONSECUTIVE_FAILURES = 25


def get(url, *, tries=3, timeout=30, **kw):
    last = None
    for attempt in range(tries):
        _throttle.wait()
        try:
            r = _session.get(url, timeout=timeout, **kw)
            # 403 is a decision, not a hiccup -- retrying cannot change it
            if r.status_code == 403:
                _consecutive_failures[0] += 1
                _check_blocked(url, 403)
                raise BlockedError(f"403 Forbidden from {url}")
            if r.status_code in (429, 502, 503):
                last = RuntimeError(f"{r.status_code} from {url}")
                if attempt < tries - 1:
                    time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            _consecutive_failures[0] = 0
            return r
        except BlockedError:
            raise
        except requests.RequestException as e:
            last = e
            if attempt < tries - 1:
                time.sleep(2 ** attempt)

    _consecutive_failures[0] += 1
    _check_blocked(url, last)
    raise last


def _check_blocked(url, why):
    if _consecutive_failures[0] >= MAX_CONSECUTIVE_FAILURES:
        raise BlockedError(
            f"{_consecutive_failures[0]} requests in a row failed (last: {why}).\n"
            f"The host is refusing this IP rather than throttling it. On a shared\n"
            f"CI runner this usually means SEC has rate-limited the whole IP range\n"
            f"because of other traffic. Re-run later, or run the build locally.\n"
            f"Last URL: {url}")


def get_json(url, **kw):
    return get(url, **kw).json()
