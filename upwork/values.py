"""Value helpers shared by every Upwork parser: numbers, text, dates, money
and links. Pure functions; every helper tolerates None and junk."""
import html as html_lib
import re
from datetime import datetime, timezone

SITE = "https://www.upwork.com"


# ---- numbers --------------------------------------------------------------------------

def num(value):
    """int / float / numeric string ('1,234.5', '$48,000') -> float; junk -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    text = re.sub(r"[,$\s]", "", str(value))
    try:
        out = float(text)
    except ValueError:
        return None
    return out if out == out else None


def to_int(value):
    out = num(value)
    return int(round(out)) if out is not None else None


def amount(value):
    """A money amount: whole numbers as int, others rounded to cents."""
    out = num(value)
    if out is None:
        return None
    return int(out) if float(out).is_integer() else round(out, 2)


def positive(value):
    """Counts / amounts where 0 means "not given" -> None."""
    out = amount(value)
    return out if out else None


def rating(value):
    """A 0-5 score rounded to 2 places; 0 / missing -> None."""
    out = num(value)
    return round(out, 2) if out else None


def percent(value):
    """A 0-1 ratio -> whole percent (JSS 1.0 -> 100); None stays None."""
    out = num(value)
    return int(round(out * 100)) if out is not None else None


def hours(value):
    out = num(value)
    return round(out, 1) if out is not None else None


# ---- text --------------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_HIGHLIGHT_RE = re.compile(r"\^H|H\^|<span class=\"highlight\">|</span>")


def text(value):
    """Whitespace-collapsed, HTML-unescaped string without search highlight
    markup; '' -> None."""
    if value is None:
        return None
    out = _TAG_RE.sub("", _HIGHLIGHT_RE.sub("", str(value)))
    out = " ".join(html_lib.unescape(out).replace("\xa0", " ").split())
    return out or None


def multiline(value):
    """Like text() but keeps paragraph breaks (descriptions, reviews)."""
    if value is None:
        return None
    raw = _HIGHLIGHT_RE.sub("", str(value))
    lines = [" ".join(line.split()) for line in html_lib.unescape(raw).replace("\xa0", " ").splitlines()]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out or None


def lower_snake(value):
    """'IntermediateLevel' / 'top_rated' / 'PART_TIME' -> 'intermediate_level' / 'top_rated' / 'part_time'."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    return re.sub(r"[\s\-]+", "_", s).lower()


def strip_html(value):
    """HTML fragment -> plain text with paragraph breaks."""
    if value is None:
        return None
    s = re.sub(r"(?i)<br\s*/?>", "\n", str(value))
    s = re.sub(r"(?i)</(p|div|li|h\d|tr)>", "\n", s)
    return multiline(_TAG_RE.sub("", s))


# ---- dates -------------------------------------------------------------------------------

def iso_datetime(value):
    """ISO-8601 string with any offset -> UTC 'YYYY-MM-DDTHH:MM:SSZ'; junk -> None."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(value):
    """ISO date/datetime string -> 'YYYY-MM-DD'; junk -> None."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    out = iso_datetime(s)
    return out[:10] if out else None


# ---- money ---------------------------------------------------------------------------------

def money(node, currency="USD"):
    """{amount, currencyCode} (optionally wrapped in {node}) -> {amount, currency} or None."""
    if isinstance(node, dict) and "node" in node and isinstance(node.get("node"), (dict, type(None))):
        node = node.get("node")
    if not isinstance(node, dict):
        return None
    value = amount(node.get("amount"))
    if value is None:
        return None
    return {"amount": value, "currency": node.get("currencyCode") or node.get("isoCurrencyCode") or currency}


def money_range(low, high, currency="USD"):
    low, high = amount(low), amount(high)
    if low is None and high is None:
        return None
    return {"min": low, "max": high, "currency": currency}


# ---- links ---------------------------------------------------------------------------------

def link(path):
    if not path:
        return None
    path = str(path)
    if path.startswith("http"):
        return path
    return SITE + (path if path.startswith("/") else "/" + path)


def job_link(ciphertext):
    return f"{SITE}/jobs/{ciphertext}" if ciphertext else None


def freelancer_link(ciphertext_or_vanity):
    return f"{SITE}/freelancers/{ciphertext_or_vanity}" if ciphertext_or_vanity else None


def agency_link(org_id):
    return f"{SITE}/agencies/{org_id}/" if org_id else None


def service_link(slug):
    return f"{SITE}/services/product/{slug}" if slug else None


def job_id(ciphertext):
    """'~022110260925663995874' -> '2110260925663995874'."""
    if not ciphertext:
        return None
    s = str(ciphertext)
    return s[3:] if s.startswith("~02") else s
