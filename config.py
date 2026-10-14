"""Configuration for the Upwork Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT          port the API listens on (default 8000)
    UPWORK_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                  (default: none — direct). Upwork sits behind Cloudflare, which
                  scores your IP and TLS fingerprint. A home or office IP passes
                  without a proxy; set one only if you start seeing
                  "blocked the request" errors at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# TLS identities curl_cffi impersonates, tried in order for fresh sessions.
# Safari's passes Cloudflare where Chrome's is sometimes challenged.
UPWORK_IMPERSONATIONS = ("safari", "chrome")
UPWORK_REQUESTS_PER_SESSION = 200     # retire a warmed session after this many calls
UPWORK_MAX_ATTEMPTS = 3               # fresh sessions tried per call before giving up
UPWORK_TOKEN_TTL = 20 * 3600          # re-mint a page token after this long (Upwork issues them for 24 h)
UPWORK_WORKERS = 4                    # parallel upstream calls inside one request

# This kit runs browser-free: plain HTTP with browser-grade TLS. The
# headless-browser fallback stays off.
UPWORK_BROWSER_FALLBACK = False
UPWORK_BROWSER_IDLE_SECONDS = 300

UPWORK_PROXY = os.environ.get("UPWORK_PROXY") or None


def upwork_proxy():
    """The proxy every session uses (None = direct)."""
    return os.environ.get("UPWORK_PROXY") or None
