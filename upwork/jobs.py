"""/upwork/jobs/* — job search (the site's own GraphQL, 10-50 a page), job
details (the job page's Nuxt state) and the per-skill job pages."""
from upwork import cache_config as ttl
from upwork import fetch, nuxt, queries, refdata
from upwork import parsers as P

PAGE_SIZES = (10, 20, 50)
MAX_PAGES = 100            # Upwork's own pager stops at 100 pages

JOB_TYPE_TOKENS = {"hourly": "hourly", "fixed": "fixed"}
EXPERIENCE_TOKENS = {"entry": "EntryLevel", "intermediate": "IntermediateLevel", "expert": "ExpertLevel"}
WORKLOAD_TOKENS = {"part_time": ["as_needed", "part_time"], "full_time": ["full_time"]}
DURATION_TOKENS = {"week": "week", "month": "month", "semester": "semester", "ongoing": "ongoing"}
FIXED_BUDGET_BUCKETS = ("0-99", "100-499", "500-999", "1000-4999", "5000-")
CLIENT_HIRES_BUCKETS = ("0", "1-9", "10-")
SORTS = {"recency": "recency", "relevance": "relevance+desc"}


def _range(low, high):
    if low is None and high is None:
        return None
    return f"{'' if low is None else int(low)}-{'' if high is None else int(high)}"


def _request(query, sort, page, per_page, job_type, experience_level, hourly_rate_min, hourly_rate_max,
             fixed_budget, duration, workload, client_hires, client_location, client_timezone, contract_to_hire,
             skill_ids, category, subcategory):
    req = {
        "userQuery": query or None,
        "sort": SORTS.get(sort, "recency"),
        "highlight": False,
        "paging": {"offset": (page - 1) * per_page, "count": per_page},
    }
    if job_type:
        req["jobType"] = [JOB_TYPE_TOKENS[t] for t in job_type]
    if experience_level:
        req["contractorTier"] = [EXPERIENCE_TOKENS[t] for t in experience_level]
    if workload:
        req["workload"] = [tok for w in workload for tok in WORKLOAD_TOKENS[w]]
    if duration:
        req["durationV3"] = [DURATION_TOKENS[d] for d in duration]
    hourly = _range(hourly_rate_min, hourly_rate_max)
    if hourly:
        req["hourlyRate"] = hourly
    if fixed_budget:
        req["budget"] = list(fixed_budget)
    if client_hires:
        req["clientHires"] = list(client_hires)
    if client_location:
        req["location"] = list(client_location)
    if client_timezone:
        req["timezone"] = list(client_timezone)
    if contract_to_hire:
        req["contractToHire"] = True
    if skill_ids:
        req["ontologySkillUid"] = list(skill_ids)
    if category:
        req["category2Uid"] = list(category)
    if subcategory:
        req["subcategory2Uid"] = list(subcategory)
    return req


def search(query=None, sort="recency", page=1, per_page=10, job_type=None, experience_level=None,
           hourly_rate_min=None, hourly_rate_max=None, fixed_budget=None, duration=None, workload=None,
           client_hires=None, client_location=None, client_timezone=None, contract_to_hire=None, skill_ids=None,
           category=None, subcategory=None):
    """One page of a public job search with Upwork's own filters (the
    proposals-count and payment-verified filters exist only for logged-in
    users and are not offered)."""
    req = _request(query, sort, page, per_page, job_type, experience_level, hourly_rate_min, hourly_rate_max,
                   fixed_budget, duration, workload, client_hires, client_location, client_timezone, contract_to_hire,
                   skill_ids, category, subcategory)
    data = fetch.graphql("search", queries.JOB_SEARCH, {"requestVariables": req}, alias="visitorJobSearch",
                         label="job search")
    result = P.as_dict(P.g(data, "search", "universalSearchNuxt", "visitorJobSearchV1"))
    jobs = [P.job_card(r) for r in P.as_list(result.get("results")) if P.g(r, "jobTile", "job")]
    total = P.g(result, "paging", "total")
    total_pages = min(MAX_PAGES, -(-int(total) // per_page)) if total is not None else (page if jobs else 0)
    return {
        "search": {"query": query, "sort": sort, "filters": {k: v for k, v in req.items()
                                                             if k not in ("userQuery", "sort", "highlight", "paging")}},
        "facets": P.job_facets(result.get("facets")),
        "jobs": jobs,
        "pagination": {"page": page, "items_per_page": per_page, "total_count": P.g(result, "paging", "total"),
                       "total_pages": total_pages},
    }


def details(job):
    """One job by ciphertext: the full posting, client stats and activity."""
    html = fetch.page(f"/jobs/{job}", label=f"job {job}")
    try:
        state = nuxt.decode_nuxt3(html)
    except nuxt.NuxtStateError as e:
        raise fetch.UpworkUpstreamError(f"job page {job}: {e}")
    out = P.job_details(state)
    if out is None:
        if P.g(state, "vuex", "jobDetails") is not None:
            # the job page rendered with an empty store: a private posting
            # (visible to invited freelancers only, HTTP 403 upstream)
            raise fetch.UpworkNotFound(f"Upwork job {job} is private (visible to invited freelancers only)")
        # closed / removed jobs redirect to the category's job listing
        raise fetch.UpworkNotFound(f"Upwork has no open job {job} (closed, removed or never existed)")
    return out


def by_skill(skill):
    """The 30 newest jobs of a /freelance-jobs/<skill>/ page with the skill's
    totals and related pages."""
    slug = skill
    html = fetch.page(f"/freelance-jobs/{slug}/", label=f"jobs for skill {slug}")
    try:
        state = nuxt.decode_nuxt3(html)
    except nuxt.NuxtStateError as e:
        raise fetch.UpworkUpstreamError(f"skill page {slug}: {e}")
    out = P.skill_jobs_page(state)
    if out is None:
        raise fetch.UpworkNotFound(f"Upwork has no job page for skill '{slug}'")
    out["link"] = f"{fetch.SITE}/freelance-jobs/{slug}/"
    return out
