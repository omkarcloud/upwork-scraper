"""/upwork/freelancers/* — talent search (the site's GraphQL, 10-50 a page),
full profiles (the profile page's Nuxt state), paginated work history (the
profile app's GraphQL) and the curated /hire/<skill>/ pages."""
from upwork import cache_config as ttl
from upwork import fetch, nuxt, queries, refdata
from upwork import parsers as P

PAGE_SIZES = range(1, 51)
MAX_RESULTS = 10000        # Upwork serves no talent result past the 10,000th
WORK_HISTORY_MAX = 50
TALENT_TYPES = {"freelancer": "Individual", "agency": "Agency"}
# /hire/<skill>-<suffix>/ — Upwork picks the noun per skill; the candidates are
# tried in parallel when the caller passes a bare skill name.
HIRE_SUFFIXES = ("developers", "specialists", "freelancers", "experts", "designers", "writers", "consultants",
                 "marketers", "engineers", "professionals", "artists", "translators", "editors", "managers")


def _request(query, name, page, per_page, hourly_rate_min, hourly_rate_max, job_success_min, earned_min, hours_min,
             recent_hours_only, talent_type, english_level, top_rated, top_rated_plus, rising_talent, expert_vetted,
             available_now, contract_to_hire, offers_consultations, languages, skill_ids, location, city, us_state,
             timezone, us_only):
    req = {
        "individualEarningsSearch": True,
        "paging": {"start": (page - 1) * per_page, "rows": per_page},
        "facets": ["hourly_rate"],
        "addGoodSummaries10Rids": True,
        "userQuery": name or query or None,
    }
    if name:
        req["nameSearch"] = True
    if hourly_rate_min is not None or hourly_rate_max is not None:
        req["rate"] = {"rangeStart": hourly_rate_min, "rangeEnd": hourly_rate_max}
    if job_success_min is not None:
        req["nss"] = {"rangeStart": job_success_min / 100.0, "rangeEnd": 1}
    if earned_min is not None:
        req["combinedTotalEarnings"] = {"rangeStart": earned_min} if earned_min else {"rangeStart": 0, "rangeEnd": 0}
    if hours_min is not None:
        req["totalHoursRecent" if recent_hours_only else "hours"] = {"rangeStart": hours_min}
    if talent_type:
        req["providerType"] = TALENT_TYPES[talent_type]
        req["agencySearch"] = talent_type == "agency"
    langs = list(languages or [])
    if english_level:
        req["minLanguageRankEn"] = english_level
        if "en" not in langs:
            langs.append("en")
    if langs:
        req["languages"] = langs
    for flag, key in ((top_rated, "topRated"), (top_rated_plus, "topRatedPlus"), (rising_talent, "risingTalent"),
                      (available_now, "availableNow"), (contract_to_hire, "contractToHire"), (us_only, "usOnly")):
        if flag:
            req[key] = True
    if expert_vetted:
        req["vettedStatuses"] = ["vetted"]
    if offers_consultations:
        req["offerConsultations"] = True
    if skill_ids:
        req["attributeUids"] = list(skill_ids)
    regions, subregions, countries = [], [], []
    for name_, kind in location or []:
        {"region": regions, "subregion": subregions, "country": countries}[kind].append(name_)
    if regions:
        req["regions"] = regions
    if subregions:
        req["subregions"] = subregions
    if countries:
        req["countries"] = countries
    if us_state:
        req["states"] = list(us_state)
    if timezone:
        req["timezones"] = list(timezone)
    if city:
        req["locationSearch"] = [{"city": c, "country": None} for c in city]
    disjunction = [f for f, v in (("country", countries), ("region", regions), ("subregion", subregions),
                                  ("state", us_state), ("timezone", timezone)) if v]
    if len(disjunction) > 1:
        req["orFilters"] = [{"disjunctionFields": disjunction}]
    return req


def search(query=None, name=None, page=1, per_page=10, hourly_rate_min=None, hourly_rate_max=None, job_success_min=None,
           earned_min=None, hours_min=None, recent_hours_only=None, talent_type=None, english_level=None,
           top_rated=None, top_rated_plus=None, rising_talent=None, expert_vetted=None, available_now=None,
           contract_to_hire=None, offers_consultations=None, languages=None, skill_ids=None, location=None, city=None,
           us_state=None, timezone=None, us_only=None):
    """One page of the public talent search with Upwork's own facets."""
    req = _request(query, name, page, per_page, hourly_rate_min, hourly_rate_max, job_success_min, earned_min,
                   hours_min, recent_hours_only, talent_type, english_level, top_rated, top_rated_plus, rising_talent,
                   expert_vetted, available_now, contract_to_hire, offers_consultations, languages, skill_ids, location,
                   city, us_state, timezone, us_only)
    data = fetch.graphql("search", queries.FREELANCER_SEARCH, {"request": req}, alias="visitorFreelancerSearchV2",
                         label="talent search")
    result = P.as_dict(P.g(data, "search", "universalSearchNuxt", "visitorFreelancerSearchV2"))
    rows = [P.freelancer_card(p) for p in P.as_list(result.get("profiles")) if P.g(p, "profile")]
    paging = P.as_dict(result.get("pagingInfo"))
    origin_total = paging.get("originTotal")
    served = min(int(origin_total), MAX_RESULTS) if origin_total is not None else (paging.get("total") or 0)
    return {
        "search": {"query": query, "name": name,
                   "filters": {k: v for k, v in req.items() if k not in ("individualEarningsSearch", "paging", "facets",
                                                                         "addGoodSummaries10Rids", "userQuery")}},
        **P.freelancer_search_meta(result),
        "freelancers": rows,
        "pagination": {"page": page, "items_per_page": per_page, "total_count": origin_total,
                       "total_pages": -(-served // per_page) if served else (page if rows else 0)},
    }


# ---- profiles ---------------------------------------------------------------------------------

def _profile_state(freelancer):
    html = fetch.page(f"/freelancers/{freelancer}", label=f"freelancer {freelancer}")
    try:
        return nuxt.decode_nuxt2(html)
    except nuxt.NuxtStateError as e:
        raise fetch.UpworkUpstreamError(f"profile page {freelancer}: {e}")


def _profile(freelancer):
    state = _profile_state(freelancer)
    out = P.freelancer_profile(state)
    if out is None:
        if P.g(state, "state", "isPrivateProfile"):
            raise fetch.UpworkNotFound(f"Upwork profile {freelancer} is private or does not exist")
        raise fetch.UpworkNotFound(f"Upwork has no freelancer {freelancer}")
    fetch.memoized(("person-id", freelancer), lambda: out["id"])
    return out


def details(freelancer):
    """The full public profile, with the first page of completed and
    in-progress work history embedded."""
    return _profile(freelancer)


def person_id(freelancer):
    """The numeric person id behind a profile cipher / vanity name."""
    return fetch.memoized(("person-id", freelancer), lambda: _profile(freelancer)["id"])


def work_history(freelancer, status="completed", page=1, per_page=10, with_feedback_only=None):
    """One page of a freelancer's contracts (completed or in progress) with
    the feedback exchanged on each."""
    pid = person_id(freelancer)
    variables = {"personId": pid, "pageNumber": page, "itemsPerPage": per_page, "sortBy": "Newest",
                 "filterClientAssignments": False, "excludeWithoutFeedback": bool(with_feedback_only),
                 "excludeNoFeedbackComment": False}
    data = fetch.graphql("profile", queries.WORK_HISTORY[status], variables, alias="fetchFeedback",
                         label=f"work history {freelancer}")
    out = P.work_history_page(P.g(data, "history"), page, per_page)
    return {"freelancer_id": pid, "status": status, **out}


# ---- /hire/<skill>/ ---------------------------------------------------------------------------------

def _hire_page(slug):
    html = fetch.page(f"/hire/{slug}/", label=f"hire page {slug}")
    try:
        state = nuxt.decode_nuxt3(html)
    except nuxt.NuxtStateError as e:
        raise fetch.UpworkUpstreamError(f"hire page {slug}: {e}")
    if P.g(state, "error", "statusCode") == 404:
        raise fetch.UpworkNotFound(f"Upwork has no hire page /hire/{slug}/")
    out = P.hire_page(state)
    if out is None:
        raise fetch.UpworkNotFound(f"Upwork has no hire page /hire/{slug}/")
    out["link"] = f"{fetch.SITE}/hire/{slug}/"
    return out


def _resolve_hire_slug(skill):
    """'python' -> 'python-developers': the suffix Upwork gave the skill's
    hire page, found by trying the candidates in parallel (memoised)."""
    def find():
        if skill.rsplit("-", 1)[-1] in HIRE_SUFFIXES:
            return skill
        candidates = [f"{skill}-{suffix}" for suffix in HIRE_SUFFIXES]
        results = fetch.run_parallel([lambda c=c: _hire_page(c) for c in candidates], workers=6)
        for candidate, (status, value) in zip(candidates, results):
            if status == "ok":
                fetch.memoized(("hire-page", candidate), lambda: value, ttl=600)
                return candidate
        for status, value in results:
            if status == "error" and not isinstance(value, fetch.UpworkNotFound):
                raise value
        raise fetch.UpworkNotFound(f"Upwork has no hire page for skill '{skill}'")
    return fetch.memoized(("hire-slug", skill), find, ttl=7 * 86400)


def top(skill):
    """The curated top freelancers, cost guide and FAQ of a /hire/<skill>/ page."""
    slug = _resolve_hire_slug(skill)
    return fetch.memoized(("hire-page", slug), lambda: _hire_page(slug), ttl=600)
