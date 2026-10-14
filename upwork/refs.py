"""Upwork input parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrLinkField convention, never a sibling `url`/`id` pair).
Every resolver returns a plain string so validated params stay usable as a
response-cache key, and raises ValueError with a user-facing message.

  job         ~022110260925663995874 | 2110260925663995874
              | https://www.upwork.com/jobs/Web-scraping_~022110260925663995874/
              | https://www.upwork.com/freelance-jobs/apply/Web-scraping_~022110…/
              | https://www.upwork.com/jobs/~022110260925663995874     -> "~022110260925663995874"
  freelancer  ~01d699cdd471617458 | sohaibilyas
              | https://www.upwork.com/freelancers/~01d699cdd471617458
              | https://www.upwork.com/freelancers/sohaibilyas?…        -> "~01d699cdd471617458" / "sohaibilyas"
  agency      425249375254638592 | ~01559cda955b6ac18a
              | https://www.upwork.com/agencies/425249375254638592/   -> "425249375254638592" / "~01559cda955b6ac18a"
  service     1585271712814411776 | development-it-a-data-scraping-task-within-24-48hrs-1585271712814411776
              | https://www.upwork.com/services/product/<slug>        -> the slug (bare ids become "project-<id>")
  skill       Python | python | https://www.upwork.com/hire/python-developers/
              | https://www.upwork.com/freelance-jobs/python/         -> "python" / "python-developers"
"""
import re
from urllib.parse import unquote, urlparse

_JOB_CIPHER_RE = re.compile(r"~0[12][0-9a-f]{12,30}", re.I)
_JOB_UID_RE = re.compile(r"^\d{15,22}$")
_PROFILE_CIPHER_RE = re.compile(r"^~01[0-9a-f]{12,20}$", re.I)
_VANITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,60}$")
_ORG_ID_RE = re.compile(r"^\d{12,22}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _parse_url(value):
    """-> urlparse result when `value` is an upwork.com link (schemeless
    accepted), None when it is not a link, ValueError for another site."""
    raw = (value or "").strip()
    low = raw.lower()
    if low.startswith("//"):
        raw = "https:" + raw
    elif not low.startswith(("http://", "https://")):
        head = low.split("/", 1)[0]
        if not head.endswith("upwork.com"):
            return None
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not (host == "upwork.com" or host.endswith(".upwork.com")):
        raise ValueError("Must be an upwork.com link.")
    return parsed


def _segments(parsed):
    return [unquote(s) for s in parsed.path.split("/") if s]


# ---- jobs ---------------------------------------------------------------------------------

JOB_HINT = ("Must be an Upwork job: its id (~022110260925663995874 or 2110260925663995874) or any "
            "www.upwork.com/jobs/… link.")


def resolve_job(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError(JOB_HINT)
    url = _parse_url(raw)
    if url is not None:
        found = _JOB_CIPHER_RE.search(url.path) or _JOB_CIPHER_RE.search(url.query)
        if found:
            return found.group(0)
        raise ValueError("That upwork.com link has no job id. " + JOB_HINT)
    if _JOB_UID_RE.match(raw):
        return "~02" + raw
    if _JOB_CIPHER_RE.fullmatch(raw):
        return raw
    if raw.startswith("~") and _JOB_CIPHER_RE.match(raw):
        return _JOB_CIPHER_RE.match(raw).group(0)
    raise ValueError(JOB_HINT)


# ---- freelancers ------------------------------------------------------------------------------

FREELANCER_HINT = ("Must be an Upwork freelancer: the profile id (~01d699cdd471617458), the profile's vanity "
                   "name (sohaibilyas) or a www.upwork.com/freelancers/… link.")


def resolve_freelancer(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError(FREELANCER_HINT)
    url = _parse_url(raw)
    if url is not None:
        segs = _segments(url)
        if len(segs) >= 2 and segs[0] in ("freelancers", "fl", "o", "profiles"):
            cand = segs[1]
            if segs[0] == "o" and len(segs) >= 3:      # /o/profiles/users/~01…
                cand = segs[-1]
            if _PROFILE_CIPHER_RE.match(cand) or _VANITY_RE.match(cand):
                return cand
        raise ValueError("That upwork.com link is not a freelancer profile. " + FREELANCER_HINT)
    if _PROFILE_CIPHER_RE.match(raw):
        return raw.lower() if raw[:3] == "~01" else raw
    if raw.isdigit():
        raise ValueError("Numeric person ids cannot be opened directly; pass the ~01… profile id, the vanity "
                         "name or the profile link.")
    if _VANITY_RE.match(raw) and "." not in raw:
        return raw
    raise ValueError(FREELANCER_HINT)


# ---- agencies ----------------------------------------------------------------------------------

AGENCY_HINT = ("Must be an Upwork agency: its id (425249375254638592), its ~01… cipher, or a "
               "www.upwork.com/agencies/… link.")


def resolve_agency(value):
    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise ValueError(AGENCY_HINT)
    url = _parse_url(raw)
    if url is not None:
        segs = _segments(url)
        if len(segs) >= 2 and segs[0] in ("agencies", "ag"):
            cand = segs[1]
            if _ORG_ID_RE.match(cand) or _PROFILE_CIPHER_RE.match(cand) or _VANITY_RE.match(cand):
                return cand
        raise ValueError("That upwork.com link is not an agency profile. " + AGENCY_HINT)
    if _ORG_ID_RE.match(raw) or _PROFILE_CIPHER_RE.match(raw):
        return raw
    if _VANITY_RE.match(raw) and "." not in raw:
        return raw
    raise ValueError(AGENCY_HINT)


# ---- services (project catalog) -----------------------------------------------------------------

SERVICE_HINT = ("Must be an Upwork project catalog service: its id (1585271712814411776), its slug "
                "(development-it-a-data-scraping-task-…-1585271712814411776) or a "
                "www.upwork.com/services/product/… link.")


def resolve_service(value):
    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise ValueError(SERVICE_HINT)
    url = _parse_url(raw)
    if url is not None:
        segs = _segments(url)
        if len(segs) >= 3 and segs[0] == "services" and segs[1] == "product":
            raw = segs[2]
        else:
            raise ValueError("That upwork.com link is not a catalog service. " + SERVICE_HINT)
    if _ORG_ID_RE.match(raw):
        return "project-" + raw
    if re.match(r"^[A-Za-z0-9][A-Za-z0-9-]*-\d{12,22}$", raw):
        return raw.lower()
    raise ValueError(SERVICE_HINT)


def service_id(slug):
    """'…-1585271712814411776' -> '1585271712814411776'."""
    found = re.search(r"(\d{12,22})$", slug or "")
    return found.group(1) if found else None


# ---- skills (hire / freelance-jobs pages) ------------------------------------------------------------

SKILL_HINT = ("Must be a skill: its name (Python, Web Scraping, data-entry) or a www.upwork.com/hire/… or "
              "/freelance-jobs/… link.")


def resolve_skill(value):
    """-> the page slug ('python', 'web-scraping', or the full hire slug
    'python-developers' when a hire link was pasted)."""
    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise ValueError(SKILL_HINT)
    url = _parse_url(raw)
    if url is not None:
        segs = _segments(url)
        if len(segs) >= 2 and segs[0] in ("hire", "freelance-jobs"):
            return segs[1].lower()
        raise ValueError("That upwork.com link is not a skill page. " + SKILL_HINT)
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower().replace("&", " and ").replace("+", " plus ").replace("#", " sharp ")).strip("-")
    if not slug or not _SLUG_RE.match(slug) and len(slug) > 1:
        raise ValueError(SKILL_HINT)
    return slug
