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


def get(url, *, tries=4, timeout=30, **kw):
    last = None
    for attempt in range(tries):
        _throttle.wait()
        try:
            r = _session.get(url, timeout=timeout, **kw)
            if r.status_code in (429, 503, 502):
                last = RuntimeError(f"{r.status_code} from {url}")
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(2 ** attempt)
    raise last


def get_json(url, **kw):
    return get(url, **kw).json()
