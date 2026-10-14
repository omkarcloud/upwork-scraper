"""Upwork transport: warmed curl_cffi sessions on direct egress, with a
headful patchright browser as the last resort.

Two surfaces, both on www.upwork.com (validated 2026-10-14):

  page(path, params)            GET a public page -> its HTML. Every page is
                                a Nuxt app whose data model is in the HTML
                                (upwork/nuxt.py), so job / profile / agency /
                                catalog details and the SSR searches need no
                                JavaScript.
  graphql(app, query, vars)     POST /api/graphql/v1?alias=… with the Bearer
                                token the owning app set as a cookie. The
                                token is minted by loading one page of that
                                app (APPS[app]["warm"]) into the same cookie
                                jar; it lives 24 h and is re-minted after
                                config.UPWORK_TOKEN_TTL or on a scopes error.

Cloudflare Bot Management fronts the site and scores the exit IP first: the
GKE datacenter egress is challenged on every page (403, header cf-mitigated:
challenge), so sessions leave through sticky residential exits
(config.UPWORK_PROXY_COUNTRIES) and rotate through
config.UPWORK_IMPERSONATIONS. A call is retried on fresh
sessions up to config.UPWORK_MAX_ATTEMPTS times; when every attempt was
challenged, one headful patchright Chrome loads the page (Cloudflare's JS
challenge runs and clears) and repeats the call — a navigation for pages, an
in-page fetch with the browser's own token cookie for GraphQL. That browser
stays open for config.UPWORK_BROWSER_IDLE_SECONDS.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  UpworkUpstreamError  transport failure / 5xx / unexpected body — retryable
  UpworkBlocked        Cloudflare challenge / 403 / 429           — retryable
  UpworkBadRequest     upstream rejected the params               — never retried
  UpworkNotFound       the entity does not exist                  — never retried

Smoke test:  python upwork/fetch.py [search term]
"""
import json
import os
import random
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.upwork.com"
GRAPHQL_PATH = "/api/graphql/v1"
TIMEOUT = (10, 60)          # (connect, read) — search pages are 1-2 MB

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "upgrade-insecure-requests": "1",
}
GRAPHQL_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json",
    "origin": SITE,
    "x-upwork-accept-language": "en-US",
}

# The apps whose visitor token a GraphQL call needs: the cookie the app sets,
# a cheap public page that mints it, and the referer the app sends.
APPS = {
    # the talent page mints the same UniversalSearchNuxt token and is challenged
    # less often than the jobs page on residential exits
    "search": {"cookie": "UniversalSearchNuxt_vt", "warm": "/nx/search/talent/?q=design",
               "referer": "/nx/search/jobs/"},
    "profile": {"cookie": "profile_vv_gql_token", "warm": "/freelancers/~01d699cdd471617458",
                "referer": "/freelancers/"},
    "agency": {"cookie": "AgencyNuxt_vt", "warm": "/agencies/425249375254638592/",
               "referer": "/agencies/"},
    "catalog": {"cookie": "visitor_ui_gql_token_CatalogApp", "warm": "/services/search?q=design",
                "referer": "/services/search"},
    "catalog_details": {"cookie": "visitor_ui_gql_token_CatalogProjectDetailsNuxt",
                        "warm": "/services/product/development-it-a-data-scraping-task-within-24-48hrs-1585271712814411776",
                        "referer": "/services/product/"},
}

CHALLENGE_MARKERS = ("<title>Challenge - Upwork", "cf-mitigated", "Just a moment", "challenge-platform",
                     "cf-chl-opt")
BLOCK_STATUSES = (401, 403, 429, 503)
BROWSER_WARM_PATH = "/nx/search/jobs/?q=design"
BROWSER_SETTLE_TIMEOUT = 45
RATE_LIMIT_BACKOFF = 2.0


class UpworkUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected body — retryable."""


class UpworkBlocked(UpworkUpstreamError, Blocked):
    """Cloudflare challenge (403 / 503), 401 or rate limit (429)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class UpworkBadRequest(BadRequest):
    """Upwork answered 400 to params it does not accept."""


class UpworkNotFound(NotFound):
    """The job / freelancer / agency / service does not exist — never retried."""


class _TokenError(UpworkUpstreamError):
    """The app token was rejected (expired / wrong scopes): re-mint and retry."""


def dump_debug(name, text):
    """Write a raw response to $UPWORK_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("UPWORK_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text if isinstance(text, str) else json.dumps(text))
        except OSError:
            pass


# ---- sessions -----------------------------------------------------------------------------
# A curl_cffi Session is not thread-safe, so a session is checked OUT for the
# duration of one call and returned afterwards; idle sessions wait in `_idle`.

class _Session:
    __slots__ = ("sess", "used", "proxy", "impersonate", "minted")

    def __init__(self, sess, proxy, impersonate):
        self.sess = sess
        self.proxy = proxy
        self.impersonate = impersonate
        self.used = 0
        self.minted = {}        # app -> monotonic time its token cookie was minted

    def token(self, app):
        """The app's Bearer token from the cookie jar when it is still fresh."""
        minted = self.minted.get(app)
        if minted is None or time.monotonic() - minted > float(config.UPWORK_TOKEN_TTL):
            return None
        return self.sess.cookies.get(APPS[app]["cookie"]) or None

    def close(self):
        try:
            self.sess.close()
        except Exception:
            pass


_idle = []
_idle_lock = threading.Lock()
_fresh_count = 0


def _budget():
    return max(1, int(config.UPWORK_REQUESTS_PER_SESSION))


def _new_session():
    """A new curl session: next TLS identity in rotation, on the configured
    egress, with an empty cookie jar."""
    global _fresh_count
    from curl_cffi import requests as curl_requests
    identities = tuple(config.UPWORK_IMPERSONATIONS) or ("safari",)
    with _idle_lock:
        impersonate = identities[_fresh_count % len(identities)]
        _fresh_count += 1
    proxy = config.upwork_proxy()
    sess = curl_requests.Session(impersonate=impersonate)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return _Session(sess, proxy, impersonate)


def _checkout(fresh=False):
    if not fresh:
        with _idle_lock:
            if _idle:
                return _idle.pop()
    return _new_session()


def _checkin(session):
    session.used += 1
    if session.used >= _budget():
        session.close()
        return
    with _idle_lock:
        _idle.append(session)


def reset_sessions():
    """Drop every idle session (tests, or after a burst of blocks)."""
    with _idle_lock:
        sessions, _idle[:] = list(_idle), []
    for session in sessions:
        session.close()


# ---- classification -------------------------------------------------------------------------

def is_challenged(status, headers, text):
    if (headers or {}).get("cf-mitigated") == "challenge":
        return True
    head = (text or "")[:5000]
    return status in BLOCK_STATUSES and any(m in head for m in CHALLENGE_MARKERS)


def classify(status, headers, text, label, final_url=None):
    """Raise the failure a response represents, or return its body text."""
    text = text or ""
    if is_challenged(status, headers, text):
        dump_debug("challenged", text[:5000])
        raise UpworkBlocked(f"Cloudflare challenge (HTTP {status}) on {label}", status=status)
    if status == 403 and ("__NUXT_DATA__" in text or "window.__NUXT__" in text):
        # Upwork's own 403: a full page whose store has no entity (a private
        # job, visible to invited freelancers only) — the parser reports it
        return text
    if status in BLOCK_STATUSES:
        dump_debug("blocked", text[:5000])
        raise UpworkBlocked(f"HTTP {status} on {label}", status=status)
    if status in (404, 410):
        raise UpworkNotFound(f"Upwork has nothing at {label}")
    if status == 400:
        dump_debug("bad_request", text[:5000])
        raise UpworkBadRequest(f"Upwork rejected {label}")
    if status != 200:
        raise UpworkUpstreamError(f"HTTP {status} on {label}")
    if "/nx/signup" in (final_url or "") or "/ab/account-security/login" in (final_url or ""):
        raise UpworkBlocked(f"login wall on {label}", status=403)
    return text


def _parse_json(text, label):
    try:
        return json.loads(text) if text.strip() else None
    except ValueError:
        dump_debug("non_json", text)
        if any(m in text[:5000] for m in CHALLENGE_MARKERS):
            raise UpworkBlocked(f"challenge page on {label}")
        raise UpworkUpstreamError(f"non-JSON body on {label}")


# ---- browser fallback -------------------------------------------------------------------------

class _Browser:
    """One headful patchright Chrome, opened on demand, reused while busy
    and closed after config.UPWORK_BROWSER_IDLE_SECONDS unused."""

    def __init__(self):
        self.lock = threading.Lock()
        self.driver = None
        self.last_used = 0.0
        self.closer = None

    def _open(self):
        from chrome_manager import create_scope
        from patchright_driver import PatchrightDriver
        with create_scope():
            driver = PatchrightDriver(proxy_url=config.upwork_proxy(), headless=False, geoip_timezone=True)
        try:
            self._nav(driver, SITE + BROWSER_WARM_PATH)
        except Exception:
            driver.close()
            raise
        return driver

    @staticmethod
    def _nav(driver, url):
        """Navigate and wait for a real Upwork page (one carrying Nuxt state)."""
        result = driver.nav(url, referer="https://www.google.com/", mode="blocked")
        html = (result or {}).get("html") or ""
        deadline = time.monotonic() + BROWSER_SETTLE_TIMEOUT
        while "__NUXT_DATA__" not in html and "window.__NUXT__" not in html:
            if time.monotonic() > deadline:
                raise UpworkBlocked("browser never cleared the Cloudflare challenge")
            time.sleep(1.5)
            try:
                html = driver.content() or ""
            except Exception:
                html = ""
        return html, (result or {}).get("status") or 200, (result or {}).get("url") or url

    def _close_if_idle(self):
        while True:
            time.sleep(30)
            with self.lock:
                if self.driver is None:
                    self.closer = None
                    return
                if time.time() - self.last_used > config.UPWORK_BROWSER_IDLE_SECONDS:
                    self._drop()
                    self.closer = None
                    return

    def _drop(self):
        if self.driver is not None:
            try:
                self.driver.close()
            except Exception:
                pass
        self.driver = None

    def _ensure(self):
        if self.driver is None:
            self.driver = self._open()
        if self.closer is None:
            self.closer = threading.Thread(target=self._close_if_idle, daemon=True)
            self.closer.start()
        self.last_used = time.time()

    def page(self, url, label):
        with self.lock:
            self._ensure()
            try:
                html, status, final_url = self._nav(self.driver, url)
            except UpworkNotFound:
                raise
            except Exception:
                self._drop()
                raise
        return classify(status if status else 200, {}, html, label, final_url)

    def _token(self, app):
        name = APPS[app]["cookie"]
        for cookie in self.driver.cookies():
            if cookie.get("name") == name and cookie.get("value"):
                return cookie["value"]
        return None

    def graphql(self, app, alias, body, label):
        from patchright_driver import _FETCH_JS, FETCH_TIMEOUT_MS
        with self.lock:
            self._ensure()
            try:
                token = self._token(app)
                if not token:
                    self._nav(self.driver, SITE + APPS[app]["warm"])
                    token = self._token(app)
                if not token:
                    raise UpworkUpstreamError(f"browser has no {APPS[app]['cookie']} cookie for {label}")
                headers = {"accept": "*/*", "content-type": "application/json",
                           "authorization": f"Bearer {token}", "x-upwork-accept-language": "en-US"}
                res = self.driver.call(lambda page: page.evaluate(_FETCH_JS, {
                    "url": f"{SITE}{GRAPHQL_PATH}?alias={alias}", "method": "POST", "headers": headers,
                    "body": json.dumps(body, separators=(",", ":")), "referrer": SITE + APPS[app]["referer"],
                    "timeoutMs": FETCH_TIMEOUT_MS}))
            except Exception:
                self._drop()
                raise
        if not res or (not res.get("status") and res.get("error")):
            raise UpworkUpstreamError(f"browser fetch failed on {label}: {(res or {}).get('error')}")
        status = int(res.get("status") or 0)
        text = res.get("body") or ""
        if status in BLOCK_STATUSES:
            with self.lock:
                self._drop()
        return classify(status, res.get("headers") or {}, text, label)


_browser = _Browser()


# ---- requests -----------------------------------------------------------------------------------

def _url(path, params):
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    return SITE + path + (("?" + urlencode(query, doseq=True)) if query else "")


def _curl_page(session, url, label):
    try:
        resp = session.sess.get(url, headers=PAGE_HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        raise UpworkUpstreamError(f"request failed on {label}: {type(e).__name__}: {e}")
    return classify(resp.status_code, dict(resp.headers), resp.text, label, str(resp.url))


def _mint(session, app):
    """Load the app's warm page into this session so its token cookie exists."""
    name = APPS[app]["cookie"]
    _curl_page(session, SITE + APPS[app]["warm"], f"{app} token page")
    if not session.sess.cookies.get(name):
        raise UpworkUpstreamError(f"the {app} page set no {name} cookie")
    session.minted[app] = time.monotonic()


def _curl_graphql(session, app, alias, body, label):
    token = session.token(app)
    if not token:
        _mint(session, app)
        token = session.token(app)
    headers = {**GRAPHQL_HEADERS, "authorization": f"Bearer {token}", "referer": SITE + APPS[app]["referer"]}
    try:
        resp = session.sess.post(f"{SITE}{GRAPHQL_PATH}?alias={alias}", headers=headers,
                                 data=json.dumps(body, separators=(",", ":")), timeout=TIMEOUT)
    except Exception as e:
        raise UpworkUpstreamError(f"request failed on {label}: {type(e).__name__}: {e}")
    if resp.status_code == 401:
        session.minted.pop(app, None)
        raise _TokenError(f"token rejected (401) on {label}")
    return classify(resp.status_code, dict(resp.headers), resp.text, label)


def _with_sessions(curl_call, browser_call, label):
    """Run curl_call(session) on pooled sessions (fresh ones after a failure),
    then browser_call() when every attempt was challenged."""
    last = None
    blocked_only = True
    attempts = max(1, int(config.UPWORK_MAX_ATTEMPTS))
    for attempt in range(1, attempts + 1):
        session = None
        rate_limited = False
        try:
            session = _checkout(fresh=attempt > 1)
            out = curl_call(session)
            _checkin(session)
            return out
        except UpworkBlocked as e:
            last = e
            rate_limited = e.status == 429
            if session is not None:
                session.close()
        except (UpworkNotFound, UpworkBadRequest):
            if session is not None:
                _checkin(session)
            raise
        except _TokenError as e:
            last, blocked_only = e, False
            if session is not None:
                _checkin(session)        # the session is fine, only the token was stale
        except UpworkUpstreamError as e:
            last, blocked_only = e, False
            if session is not None:
                session.close()
        except Exception as e:
            last, blocked_only = UpworkUpstreamError(f"{label}: {type(e).__name__}: {e}"), False
            if session is not None:
                session.close()
        print(f"upwork: attempt {attempt}/{attempts} on {label} failed: {last}")
        if attempt < attempts:
            time.sleep(RATE_LIMIT_BACKOFF * attempt if rate_limited else 0.4 * attempt)
    if blocked_only and config.UPWORK_BROWSER_FALLBACK and browser_call is not None:
        print(f"upwork: every curl attempt on {label} was challenged; trying the browser")
        try:
            return browser_call()
        except (UpworkNotFound, UpworkBadRequest):
            raise
        except Exception as e:
            print(f"upwork: browser fallback failed on {label}: {type(e).__name__}: {e}")
            raise UpworkBlocked(f"{label}: challenged on {attempts} sessions and in a browser") from e
    raise last


def page(path, params=None, label=None):
    """GET a public www.upwork.com page -> HTML (after redirects)."""
    url = _url(path, params)
    label = label or path
    return _with_sessions(lambda s: _curl_page(s, url, label), lambda: _browser.page(url, label), label)


def _graphql_errors(payload, label):
    if not isinstance(payload, dict):
        raise UpworkUpstreamError(f"unexpected body on {label}")
    errors = payload.get("errors") or []
    data = payload.get("data")
    if errors:
        details = json.dumps(errors)[:800]
        messages = "; ".join(str((e or {}).get("message") or e) for e in errors)[:300]
        if "oauth2 permissions" in details or "Unauthorized" in details or "invalid_token" in details:
            raise _TokenError(f"{label}: {messages}")
        if data is None or not any(v is not None for v in (data.values() if isinstance(data, dict) else [data])):
            dump_debug("graphql_error", details)
            if "validation" in details.lower() or "Invalid" in details or "must" in details.lower():
                raise UpworkBadRequest(f"Upwork rejected the {label} input: {messages}")
            raise UpworkUpstreamError(f"{label}: {messages}")
    return data if isinstance(data, dict) else {}


def graphql(app, query, variables=None, alias=None, label=None):
    """POST one GraphQL operation as the given app -> its `data` object."""
    alias = alias or app
    label = label or alias
    body = {"query": query, "variables": variables or {}}

    def via_curl(session):
        payload = _parse_json(_curl_graphql(session, app, alias, body, label), label)
        try:
            return _graphql_errors(payload, label)
        except _TokenError:
            session.minted.pop(app, None)     # a 200 with an auth error: the pooled token is stale too
            raise

    def via_browser():
        payload = _parse_json(_browser.graphql(app, alias, body, label), label)
        return _graphql_errors(payload, label)

    return _with_sessions(via_curl, via_browser, label)


# ---- memo + fan-out -------------------------------------------------------------------------------
# Resolutions (vanity url -> person id, pagination cursors) are reused across calls.

_memo = OrderedDict()
_memo_lock = threading.Lock()
MEMO_TTL = 3600
MEMO_MAX = 2048


def memoized(key, fn, ttl=MEMO_TTL):
    now = time.monotonic()
    with _memo_lock:
        hit = _memo.get(key)
        if hit and now - hit[0] < ttl:
            _memo.move_to_end(key)
            return hit[1]
    value = fn()
    with _memo_lock:
        _memo[key] = (now, value)
        _memo.move_to_end(key)
        while len(_memo) > MEMO_MAX:
            _memo.popitem(last=False)
    return value


def run_parallel(fns, workers=None):
    """Run zero-arg callables in parallel; results align with `fns`. Each
    result is ("ok", value) or ("error", exception)."""
    def guard(fn):
        try:
            return ("ok", fn())
        except Exception as e:
            return ("error", e)
    if not fns:
        return []
    workers = workers or int(config.UPWORK_WORKERS)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(fns)))) as ex:
        return list(ex.map(guard, fns))


if __name__ == "__main__":
    from upwork import queries
    term = sys.argv[1] if len(sys.argv) > 1 else "python"
    data = graphql("search", queries.JOB_SEARCH, {"requestVariables": {
        "userQuery": term, "sort": "recency", "highlight": False, "paging": {"offset": 0, "count": 5}}},
        alias="visitorJobSearch")
    res = data["search"]["universalSearchNuxt"]["visitorJobSearchV1"]
    print(res["paging"], [r["title"] for r in res["results"]])
