"""Raw Upwork payloads -> clean API objects. Pure functions, no network;
every parser tolerates missing / null / wrong-typed fields and never raises
on a partial payload.

Inputs are the Nuxt page states (upwork/nuxt.py) and the GraphQL `data`
objects (upwork/queries.py). Where the same entity arrives in two shapes
(SSR work-history items vs GraphQL {node} wrappers; SSR catalog tiles vs
GraphQL project tiles) one parser handles both.

Intentionally dropped everywhere: tracking / experiment blobs (annotations,
relevanceEncoded, tracker guids, feature flags, visitor ids), i18n label keys
("jsn_Intermediate_206"), presentation duplicates (shortName next to name,
the five portrait sizes — one photo link is kept), signed S3 URLs that
expire within minutes (originalPortrait, agency banner), internal record
numbers (rid / recno), and the job's AI-generation history (annotations.
customFields.*AIv2 — the client's draft prompts, not the posting).
"""
import json
import re

from upwork import values as V

SITE = V.SITE


def g(obj, *path, default=None):
    """Safe nested get: g(d, "a", "b", 0) -> d["a"]["b"][0] or default."""
    for step in path:
        if isinstance(step, int):
            if not isinstance(obj, list) or not -len(obj) <= step < len(obj):
                return default
            obj = obj[step]
        else:
            if not isinstance(obj, dict):
                return default
            obj = obj.get(step)
        if obj is None:
            return default
    return obj


def as_list(value):
    return value if isinstance(value, list) else []


def as_dict(value):
    return value if isinstance(value, dict) else {}


def n(obj, *path, default=None):
    """g() that also looks through GraphQL {node: …} wrappers at every step."""
    cur = _unwrap(obj)
    for step in path:
        cur = g(cur, step)
        cur = _unwrap(cur)
        if cur is None:
            return default
    return cur


def _unwrap(value):
    if isinstance(value, dict) and set(value.keys()) == {"node"}:
        return value["node"]
    return value


def _unwrap_list(value):
    return [_unwrap(v) for v in as_list(value) if _unwrap(v) is not None]


# ---- enums ----------------------------------------------------------------------------------

_TIERS = {1: "entry", 2: "intermediate", 3: "expert", "1": "entry", "2": "intermediate", "3": "expert",
          "EntryLevel": "entry", "IntermediateLevel": "intermediate", "ExpertLevel": "expert",
          "ENTRY_LEVEL": "entry", "INTERMEDIATE": "intermediate", "EXPERT": "expert"}
_JOB_TYPES = {1: "fixed", 2: "hourly", "1": "fixed", "2": "hourly", "FIXED": "fixed", "HOURLY": "hourly",
              "Fixed": "fixed", "Hourly": "hourly", "fixed": "fixed", "hourly": "hourly",
              "WEEKLY_RETAINER": "weekly_retainer"}
_TOP_RATED = {"top_rated_plus": "top_rated_plus", "top_rated": "top_rated", "hipo": "rising_talent",
              "rising_talent": "rising_talent", "not_eligible": None, "": None, None: None}


def experience_level(value):
    return _TIERS.get(value)


def job_type(value):
    return _JOB_TYPES.get(value)


def _top_rated_status(status, plus=None):
    """The best badge of (topRatedStatus, topRatedPlusStatus) -> one label."""
    if plus in ("top_rated_plus",) or status == "top_rated_plus":
        return "top_rated_plus"
    return _TOP_RATED.get(status) if status in _TOP_RATED else V.lower_snake(status)


def _badges(status, plus=None, vetted=None):
    best = _top_rated_status(status, plus)
    return {
        "top_rated_status": best,
        "is_top_rated": best in ("top_rated", "top_rated_plus"),
        "is_top_rated_plus": best == "top_rated_plus",
        "is_rising_talent": best == "rising_talent",
        "is_expert_vetted": bool(vetted) if vetted is not None else None,
    }


# ---- skills ------------------------------------------------------------------------------------

def skill(item):
    """Any of the site's skill shapes -> {id, name} (None when nameless)."""
    item = _unwrap(item)
    if isinstance(item, str):
        return {"id": None, "name": V.text(item)}
    if not isinstance(item, dict):
        return None
    inner = _unwrap(item.get("skill")) or _unwrap(item.get("ontologySkill")) or {}
    name = (item.get("prettyName") or item.get("prefLabel") or item.get("preferredLabel") or item.get("name")
            or item.get("label") or inner.get("prettyName") or inner.get("prefLabel") or inner.get("preferredLabel")
            or inner.get("name"))
    sid = item.get("uid") or item.get("id") or item.get("skillId") or inner.get("uid") or inner.get("id")
    if not name:
        return None
    return {"id": str(sid) if sid is not None else None, "name": V.text(name)}


def skills(items):
    out = []
    for item in as_list(items):
        parsed = skill(item)
        if parsed and parsed["name"] and parsed["name"] not in {s["name"] for s in out}:
            out.append(parsed)
    return out


# ---- jobs: search ------------------------------------------------------------------------------

def _duration(node):
    node = _unwrap(node)
    if not isinstance(node, dict):
        return None
    label = V.text(node.get("label"))
    weeks = V.to_int(node.get("weeks"))
    if label is None and weeks is None:
        return None
    return {"label": label, "weeks": weeks}


def job_card(result):
    """One visitorJobSearchV1 result -> job summary."""
    job = as_dict(g(result, "jobTile", "job"))
    ciphertext = job.get("ciphertext") or (f"~02{result.get('id')}" if result.get("id") else None)
    kind = job_type(job.get("jobType"))
    hourly = V.money_range(job.get("hourlyBudgetMin"), job.get("hourlyBudgetMax"))
    if hourly and not (hourly["min"] or hourly["max"]):
        hourly = None
    fixed = V.money(job.get("fixedPriceAmount"))
    duration = _duration(job.get("hourlyEngagementDuration")) or _duration(job.get("fixedPriceEngagementDuration"))
    return {
        "id": str(job.get("id") or result.get("id") or V.job_id(ciphertext) or "") or None,
        "ciphertext": ciphertext,
        "title": V.text(result.get("title")),
        "link": V.job_link(ciphertext),
        "description": V.multiline(result.get("description")),
        "job_type": kind,
        "experience_level": experience_level(job.get("contractorTier")),
        "budget": fixed if kind != "hourly" else None,
        "hourly_rate": hourly,
        "weekly_retainer_budget": V.amount(job.get("weeklyRetainerBudget")),
        "duration": duration,
        "workload": V.lower_snake(job.get("hourlyEngagementType")),
        "skills": skills(result.get("ontologySkills")),
        "highlighted_skills": [s["name"] for s in (skills([x for x in as_list(result.get("ontologySkills"))
                                                            if g(x, "highlighted")]))],
        "created_at": V.iso_datetime(job.get("createTime")),
        "published_at": V.iso_datetime(job.get("publishTime")),
    }


def job_facets(facets):
    """{jobType: [{key, value}], …} -> {job_type: {fixed: 617, …}, …}."""
    out = {}
    names = {"jobType": "job_type", "workload": "workload", "clientHires": "client_hires", "durationV3": "duration",
             "amount": "fixed_budget", "contractorTier": "experience_level", "contractToHire": "contract_to_hire"}
    for raw, name in names.items():
        rows = as_list(g(facets, raw))
        if not rows:
            continue
        counts = {}
        for row in rows:
            key = g(row, "key")
            if key is None:
                continue
            if raw == "contractorTier":
                key = experience_level(key) or V.lower_snake(key)
            elif raw == "amount" and key == "*":
                key = "not_fixed_price"
            counts[str(key)] = V.to_int(g(row, "value"))
        out[name] = counts
    return out


# ---- jobs: details -------------------------------------------------------------------------------

def _qualifications(q):
    q = as_dict(q)
    out = {
        "min_job_success_score": V.positive(q.get("minJobSuccessScore")),
        "min_hours_billed": V.positive(q.get("minOdeskHours")),
        "min_hours_per_week": V.positive(q.get("minHoursWeek")),
        "min_english_level": V.positive(q.get("prefEnglishSkill")),
        "rising_talent_only": bool(q.get("risingTalent")) or None,
        "portfolio_required": bool(q.get("shouldHavePortfolio")) or None,
        "countries": as_list(q.get("countries")) or None,
        "regions": as_list(q.get("regions")) or None,
        "timezones": as_list(q.get("timezones")) or None,
        "languages": as_list(q.get("languages")) or None,
        "on_site_type": V.lower_snake(q.get("onSiteType")),
        "location": V.text(q.get("location")) or V.text(q.get("localDescription")),
    }
    return out if any(v for v in out.values()) else None


def _client(buyer):
    buyer = as_dict(buyer)
    stats = as_dict(buyer.get("stats"))
    location = as_dict(buyer.get("location"))
    company = as_dict(buyer.get("company"))
    profile = as_dict(company.get("profile"))
    tz = V.text(location.get("countryTimezone"))
    return {
        "is_payment_verified": bool(buyer.get("isPaymentMethodVerified")),
        "is_enterprise": bool(buyer.get("isEnterprise")),
        "is_top_client": bool(buyer.get("isTopClient")),
        "location": {
            "city": V.text(location.get("city")),
            "country": V.text(location.get("country")),
            "timezone": tz.split(" ")[0] if tz else None,
            "utc_offset_hours": (V.num(location.get("offsetFromUtcMillis")) or 0) / 3600000
            if location.get("offsetFromUtcMillis") is not None else None,
        },
        "member_since": V.iso_date(company.get("contractDate")),
        "company": {"name": V.text(company.get("name")), "industry": V.text(profile.get("industry")),
                    "size": V.text(profile.get("size"))},
        "stats": {
            "total_spent": V.money(stats.get("totalCharges")),
            "total_hires": V.to_int(stats.get("totalAssignments")),
            "active_hires": V.to_int(stats.get("activeAssignmentsCount")),
            "hours_billed": V.hours(stats.get("hoursCount")),
            "feedback_count": V.to_int(stats.get("feedbackCount")),
            "rating": V.rating(stats.get("score")),
            "jobs_with_hires": V.to_int(stats.get("totalJobsWithHires")),
            "jobs_posted": V.to_int(g(buyer, "jobs", "postedCount")),
            "open_jobs": V.to_int(g(buyer, "jobs", "openCount")),
            "avg_hourly_rate_paid": V.amount(buyer.get("avgHourlyJobsRate")),
        },
    }


def _sands_skills(sands):
    """The job's skill block: mandatory skills grouped under ontology groups
    plus the flat additionalSkills list -> one deduped list."""
    out = []
    for group in as_list(g(sands, "ontologySkills")):
        for child in as_list(g(group, "children")):
            parsed = skill(child)
            if parsed:
                parsed["group"] = V.text(g(group, "name"))
                parsed["relevance"] = V.lower_snake(child.get("relevance"))
                out.append(parsed)
    for item in as_list(g(sands, "additionalSkills")):
        parsed = skill(item)
        if parsed and parsed["name"] not in {s["name"] for s in out}:
            parsed["group"] = None
            parsed["relevance"] = V.lower_snake(item.get("relevance"))
            out.append(parsed)
    return out


def similar_job(item):
    item = as_dict(item)
    ciphertext = item.get("ciphertext")
    hourly = V.money_range(g(item, "hourlyBudget", "min"), g(item, "hourlyBudget", "max"))
    if hourly and not (hourly["min"] or hourly["max"]):
        hourly = None
    fixed = V.money(item.get("amount"))
    kind = job_type(item.get("type"))
    return {
        "id": V.job_id(ciphertext),
        "title": V.text(item.get("title")),
        "link": V.job_link(ciphertext),
        "description": V.multiline(item.get("description")),
        "job_type": kind,
        "experience_level": experience_level(item.get("contractorTier")),
        "budget": fixed if kind != "hourly" and fixed and fixed["amount"] else None,
        "hourly_rate": hourly,
        "duration": V.text(item.get("durationLabel")),
        "workload": V.text(item.get("engagement")),
        "skills": skills(item.get("attrs") or item.get("ontologySkills") or item.get("skills")),
        "published_at": V.iso_datetime(item.get("publishedOn") or item.get("createdOn")),
    }


def job_details(state):
    """The jobDetails store of a job page -> the full job, or None when the
    page is not a job (closed jobs redirect to a category page)."""
    jd = g(state, "vuex", "jobDetails")
    job = as_dict(g(jd, "job"))
    if not job.get("uid") and not job.get("ciphertext"):
        return None
    ciphertext = job.get("ciphertext") or f"~02{job['uid']}"
    kind = job_type(job.get("type"))
    budget = V.money(job.get("budget"))
    if kind == "hourly" or not budget or not budget["amount"]:
        budget = None if kind == "hourly" or not budget or not budget["amount"] else budget
    ext = as_dict(job.get("extendedBudgetInfo"))
    hourly = V.money_range(ext.get("hourlyBudgetMin"), ext.get("hourlyBudgetMax"))
    if hourly and not (hourly["min"] or hourly["max"]):
        hourly = None
    activity = as_dict(job.get("clientActivity"))
    segmentation = [V.text(s.get("label")) for s in as_list(job.get("segmentationData")) if g(s, "label")]
    sands = as_dict(g(jd, "sands"))
    occupation = as_dict(sands.get("occupation"))
    return {
        "id": str(job.get("uid") or V.job_id(ciphertext)),
        "ciphertext": ciphertext,
        "title": V.text(job.get("title")),
        "link": V.job_link(ciphertext),
        "description": V.multiline(job.get("description")),
        "job_type": kind,
        "experience_level": experience_level(job.get("contractorTier")),
        "budget": budget,
        "hourly_rate": hourly,
        "weekly_retainer_budget": V.amount(job.get("weeklyRetainerBudget")),
        "is_budget_hidden": bool(job.get("hideBudget")),
        "duration": _duration(job.get("engagementDuration")) or ({"label": V.text(job.get("durationLabel")), "weeks": None}
                                                                 if job.get("durationLabel") else None),
        "workload": V.text(job.get("workload")),
        "project_type": segmentation[0] if segmentation else None,
        "category": {"name": V.text(g(job, "category", "name")), "slug": g(job, "category", "urlSlug")},
        "category_group": {"name": V.text(g(job, "categoryGroup", "name")), "slug": g(job, "categoryGroup", "urlSlug")},
        "occupation": {"id": occupation.get("uid") or occupation.get("id"), "name": V.text(occupation.get("prefLabel"))}
        if occupation else None,
        "skills": _sands_skills(sands),
        "tools": [V.text(t) for t in as_list(job.get("tools")) if t] or None,
        "deliverables": V.multiline(job.get("deliverables")),
        "positions_to_hire": V.to_int(job.get("numberOfPositionsToHire") or activity.get("numberOfPositionsToHire")),
        "is_contract_to_hire": bool(job.get("isContractToHire")),
        "is_hiring_now": bool(job.get("hiringNow")),
        "was_renewed": bool(job.get("wasRenewed")),
        "created_at": V.iso_datetime(job.get("createdOn") or job.get("postedOn")),
        "published_at": V.iso_datetime(job.get("publishTime")),
        "start_date": V.iso_date(job.get("startDate")),
        "delivery_date": V.iso_date(job.get("deliveryDate")),
        "deadline": V.iso_date(job.get("deadline")),
        "qualifications": _qualifications(job.get("qualifications")),
        "activity": {
            "proposals": V.to_int(activity.get("totalApplicants")),
            "interviewing": V.to_int(activity.get("totalInvitedToInterview")),
            "invites_sent": V.to_int(activity.get("invitationsSent")),
            "unanswered_invites": V.to_int(activity.get("unansweredInvites")),
            "hired": V.to_int(activity.get("totalHired")),
            "last_viewed_by_client_at": V.iso_datetime(activity.get("lastBuyerActivity")),
        },
        "client": _client(g(jd, "buyer")),
        "similar_jobs": [similar_job(s) for s in as_list(g(jd, "similarJobs")) if g(s, "ciphertext")],
    }


def skill_page_job(item):
    """A job tile of a /freelance-jobs/<skill>/ page."""
    item = as_dict(item)
    ciphertext = item.get("ciphertext")
    kind = job_type(item.get("type"))
    fixed = V.money(item.get("amount"))
    hourly = V.money_range(g(item, "amount", "amount"), g(item, "maxAmount", "amount")) if kind == "hourly" else None
    if hourly and not (hourly["min"] or hourly["max"]):
        hourly = None
    return {
        "id": V.job_id(ciphertext),
        "ciphertext": ciphertext,
        "title": V.text(item.get("title")),
        "link": V.job_link(ciphertext),
        "description": V.multiline(item.get("description")),
        "job_type": kind,
        "experience_level": experience_level(item.get("contractorTier")),
        "budget": fixed if kind == "fixed" and fixed and fixed["amount"] else None,
        "hourly_rate": hourly,
        "duration": V.text(item.get("durationLabel")),
        "workload": V.text(item.get("engagement")),
        "skills": skills(item.get("ontologySkills")),
        "created_at": V.iso_datetime(item.get("createdOn")),
        "renewed_at": V.iso_datetime(item.get("renewedOn")),
        "posted": V.text(item.get("ago")),
    }


def _related_link(item):
    return {"title": V.text(g(item, "title")), "link": V.link(g(item, "url") or g(item, "urlPath"))}


def skill_jobs_page(state):
    data = _asyncdata(state)
    if data is None or not isinstance(data.get("jobs"), list):
        return None
    return {
        "skill": V.text(data.get("prettySkillName") or data.get("modifier")),
        "title": V.text(data.get("h1Title")),
        "total_jobs": V.to_int(data.get("totalJobs")),
        "reviews": {"average_rating": V.rating(g(data, "reviews", "avgRating")),
                    "count": V.to_int(g(data, "reviews", "totalCount"))},
        "jobs": [skill_page_job(j) for j in data["jobs"] if g(j, "ciphertext")],
        "related_job_pages": [_related_link(r) for r in as_list(data.get("relatedJobs"))],
        "related_skill_pages": [_related_link(r) for r in as_list(data.get("relatedSkills"))],
    }


def _asyncdata(state):
    for key, value in as_dict(g(state, "data")).items():
        if key.startswith("options:asyncdata") and isinstance(value, dict):
            return value
    return None


# ---- freelancers: search ---------------------------------------------------------------------------

def _location(loc):
    loc = as_dict(loc)
    out = {
        "city": V.text(loc.get("city")),
        "state": V.text(loc.get("state")),
        "country": V.text(loc.get("country")),
        "country_code": loc.get("countryCodeIso2"),
        "region": V.text(loc.get("region")),
        "subregion": V.text(loc.get("subregion")),
        "timezone": V.text(loc.get("timezone") or loc.get("countryTimezone")),
    }
    return out if any(out.values()) else None


def _portfolio_item(item):
    item = as_dict(item)
    attachments = []
    for att in as_list(item.get("attachments")):
        att = as_dict(att)
        attachments.append({
            "type": att.get("type"),
            "title": V.text(att.get("title")),
            "link": att.get("link") or V.link(att.get("originalAttachment")) or V.link(att.get("imageLarge")),
            "image": V.link(att.get("imageLarge") or att.get("imageMiddle") or att.get("imageSmall")),
        })
    return {
        "id": str(item.get("uid") or item.get("id") or "") or None,
        "title": V.text(item.get("title")),
        "description": V.multiline(item.get("description")),
        "project_link": item.get("projectUrl") or item.get("src"),
        "video_link": item.get("videoUrl"),
        "thumbnail": V.link(item.get("thumbnail") or item.get("thumbnailUrl")),
        "completed_on": V.iso_date(item.get("completionDate")),
        "category": V.text(g(item, "category", "level2") or g(item, "subCategory")) or None,
        "skills": [V.text(s) for s in as_list(item.get("skills")) if isinstance(s, str)] or None,
        "attachments": attachments or None,
    }


def _agency_ref(a):
    a = as_dict(a)
    org = a.get("orgId") or a.get("uid") or a.get("id")
    if not org and not a.get("name"):
        return None
    return {"id": str(org) if org else None, "ciphertext": a.get("ciphertext"), "name": V.text(a.get("name")),
            "link": V.agency_link(org), "logo": a.get("logo"),
            "total_earnings": V.money({"amount": a.get("totalEarnings")}) if a.get("totalEarnings") else None}


def freelancer_card(item):
    """One visitorFreelancerSearchV2 profile -> freelancer summary."""
    item = as_dict(item)
    profile = as_dict(item.get("profile"))
    personal = as_dict(profile.get("personalData"))
    agg = as_dict(profile.get("profileAggregates"))
    prefs = as_dict(profile.get("preferences"))
    identity = as_dict(profile.get("identity"))
    ciphertext = identity.get("ciphertext")
    rate = V.amount(g(personal, "chargeRate", "rawValue"))
    agencies = [_agency_ref(a) for a in as_list(g(profile, "agencies", "agencies"))]
    first, last = V.text(personal.get("firstName")), V.text(personal.get("lastName"))
    return {
        "id": str(item.get("personId") or identity.get("id") or "") or None,
        "ciphertext": ciphertext,
        "name": " ".join(x for x in (first, last) if x) or None,
        "title": V.text(personal.get("title")),
        "link": V.freelancer_link(ciphertext) or (personal.get("profileUrl") or "").replace("https://upwork.com", SITE) or None,
        "description": V.multiline(personal.get("description")),
        "photo": g(personal, "portrait", "portrait100"),
        "location": _location(personal.get("location")),
        "hourly_rate": {"amount": rate, "currency": g(personal, "chargeRate", "currency") or "USD"}
        if rate is not None else None,
        "skills": skills(profile.get("skills")),
        "stats": {
            "job_success_score": None if prefs.get("hideJss") else V.percent(agg.get("nSS100BwScore")),
            "total_earnings": None if prefs.get("hideEarnings") else V.amount(item.get("individualTotalEarnings")
                                                                           if item.get("individualTotalEarnings") is not None
                                                                           else agg.get("totalEarnings")),
            "agency_earnings": None if prefs.get("hideEarnings") else V.amount(item.get("agencyTotalEarnings")),
            "total_hours": V.hours(agg.get("totalHours")),
            "hourly_jobs": V.to_int(agg.get("totalHourlyJobs")),
            "fixed_jobs": V.to_int(agg.get("totalFixedJobs")),
            "completed_jobs": V.to_int(item.get("totalCompletedJobs")),
        },
        "badges": {**_badges(agg.get("topRatedStatus"), agg.get("topRatedPlusStatus"), item.get("vetted")),
                   "is_id_verified": bool(g(profile, "verifications", "idVerified")
                                          or g(profile, "verifications", "idBadgeStatus") == "PASSED")},
        "offers_consultations": bool(item.get("offerConsultations")),
        "has_availability_badge": bool(g(profile, "personAvailability", "purchasedInvitationBadge", "active")),
        "agency": next((a for a in agencies if a), None),
        "portfolio": [{
            "id": str(p.get("id") or ""), "title": V.text(p.get("title")), "description": V.multiline(p.get("description")),
            "project_link": p.get("projectUrl"), "thumbnail": V.link(p.get("thumbnail")),
            "category": V.text(p.get("subCategory") or p.get("category")),
        } for p in as_list(g(profile, "projectList", "projects")) if isinstance(p, dict)],
        "portfolio_count": V.to_int(g(profile, "projectList", "totalProjects")),
    }


def freelancer_search_meta(result):
    return {
        "suggested_skills": [{"id": s.get("id"), "name": V.text(s.get("prefLabel"))}
                             for s in as_list(result.get("adaptiveSkills")) if isinstance(s, dict)],
        "hourly_rate_facets": {str(r.get("key")): V.to_int(r.get("value"))
                               for r in as_list(g(result, "facets", "hourlyRate")) if isinstance(r, dict)} or None,
    }


# ---- freelancers: profile ------------------------------------------------------------------------------

def _score_details(details):
    return {V.lower_snake(d.get("label")): V.rating(d.get("score")) for d in _unwrap_list(details)
            if isinstance(d, dict) and d.get("label")} or None


def _feedback(node):
    node = _unwrap(node)
    if not isinstance(node, dict):
        return None
    score = V.rating(node.get("score"))
    comment = V.multiline(node.get("comment"))
    if score is None and comment is None:
        return None
    return {"score": score, "comment": comment, "response": V.multiline(node.get("response")),
            "details": _score_details(node.get("scoreDetails")),
            "created_at": V.iso_datetime(node.get("creationTs")) if isinstance(node.get("creationTs"), str) else None}


def assignment(item):
    """A work-history contract (SSR page item or GraphQL node)."""
    item = _unwrap(item)
    if not isinstance(item, dict):
        return None
    ciphertext = item.get("ciphertext")
    portfolio = n(item, "linkedPortfolio")
    client_name = V.text(n(item, "clientInformation", "name"))
    return {
        "id": str(item.get("id") or "") or None,
        "title": V.text(item.get("title")),
        "job_id": item.get("openingUid"),
        "job_link": V.job_link(ciphertext) if ciphertext and item.get("isOpeningVisible") else None,
        "description": V.multiline(item.get("description")) if item.get("description") != item.get("title") else None,
        "job_type": job_type(item.get("type")),
        "status": V.lower_snake(item.get("status")),
        "is_private": bool(item.get("isPrivate")),
        "started_at": V.iso_datetime(item.get("startedOn")),
        "ended_at": V.iso_datetime(item.get("endedOn")),
        "total_hours": V.hours(item.get("totalHours")),
        "hours_per_week": V.to_int(item.get("hoursPerWeek")) or None,
        "hourly_rate": V.money(n(item, "hourlyRate")),
        "total_charged": V.money(n(item, "totalCharges")),
        "fixed_price": V.money(n(item, "initialAmount")),
        "weekly_stipend": V.money(n(item, "weeklyStipendChargeAmount")),
        "client": {"name": client_name, "team_id": item.get("clientTeamUid")} if client_name or item.get("clientTeamUid") else None,
        "agency_name": V.text(item.get("agencyName")),
        "feedback_from_client": _feedback(item.get("feedback")),
        "feedback_to_client": _feedback(item.get("feedbackGiven")),
        "mid_contract_feedback_average": _feedback(item.get("midContractFeedbacksAverage")),
        "skills": skills(item.get("skills")),
        "linked_portfolio": {"id": str(portfolio.get("uid") or ""), "title": V.text(portfolio.get("title")),
                             "project_link": portfolio.get("projectUrl")} if isinstance(portfolio, dict) else None,
    }


def work_history_page(node, page, per_page):
    node = _unwrap(node) or {}
    items = [assignment(a) for a in as_list(node.get("assignments") or node.get("pageItems"))]
    items = [a for a in items if a]
    total = V.to_int(node.get("totalItems"))
    return {
        "contracts": items,
        "pagination": {"page": page, "items_per_page": per_page, "total_count": total,
                       "total_pages": -(-total // per_page) if total is not None else (page if items else 0)},
    }


def _availability(a):
    a = as_dict(a)
    capacity = as_dict(a.get("capacity"))
    if not a:
        return None
    return {"capacity": V.text(capacity.get("name")), "capacity_code": V.lower_snake(capacity.get("nid")),
            "min_hours": V.to_int(a.get("minHours")), "max_hours": V.to_int(a.get("maxHours")),
            "available_days": a.get("availableDays")}


def _language(item):
    item = as_dict(item)
    lang = as_dict(item.get("language"))
    level = as_dict(item.get("proficiencyLevel"))
    name = V.text(lang.get("englishName") or item.get("name") or lang.get("name"))
    if not name:
        return None
    return {"name": name, "code": lang.get("iso639Code"), "proficiency": V.text(level.get("proficiencyTitle") or level.get("name")),
            "proficiency_rank": V.to_int(level.get("rank"))}


def _generic_items(items, keys):
    """Keep only the listed keys (camelCase -> snake_case) of unknown-shape
    lists (education / employment / certificates render null for visitors)."""
    out = []
    for item in _unwrap_list(items):
        if not isinstance(item, dict):
            continue
        row = {snake: (V.text(item.get(src)) if isinstance(item.get(src), str) else item.get(src)) for src, snake in keys}
        if any(v not in (None, "", []) for v in row.values()):
            out.append(row)
    return out or None


def freelancer_profile(state, html=None):
    """The profileViewer store of a freelancer page -> the full profile,
    or None when the profile is private / missing."""
    pv = g(state, "state", "profileViewer")
    wrapper = as_dict(g(pv, "profile"))
    profile = as_dict(wrapper.get("profile"))
    if not profile.get("name") and not profile.get("title"):
        return None
    identity = as_dict(wrapper.get("identity"))
    stats = as_dict(wrapper.get("stats"))
    ciphertext = identity.get("ciphertext") or g(pv, "person", "ciphertext")
    vanity = g(wrapper, "talentVanityUrl", "vanityUrl") or wrapper.get("vanityUrl") or identity.get("userId")
    rate = V.amount(g(stats, "hourlyRate", "amount"))
    hide_earnings = bool(wrapper.get("hideEarnings") or g(pv, "options", "isHideEarnings"))
    wh = as_dict(g(pv, "workHistory"))
    completed = as_dict(wh.get("assignmentsCompleted"))
    in_progress = as_dict(wh.get("assignmentsInProgress"))
    categories = []
    for group in as_list(wrapper.get("jobCategoriesV2") or wrapper.get("jobCategories")):
        for cat in as_list(g(group, "selectedCategories")):
            categories.append({"id": cat.get("uid") or cat.get("id"), "name": V.text(cat.get("name")),
                               "group": V.text(g(group, "groupName"))})
    specialized = []
    for sp in as_list(wrapper.get("specializedProfilesInfo")):
        sp = as_dict(sp)
        specialized.append({"id": sp.get("profileId"),
                            "occupations": [V.text(o.get("prefLabel")) for o in as_list(sp.get("occupations")) if g(o, "prefLabel")]})
    agencies = [_agency_ref(a) for a in as_list(wrapper.get("agencies"))]
    location = as_dict(profile.get("location"))
    return {
        "id": str(identity.get("uid") or identity.get("id") or g(pv, "person", "uid") or "") or None,
        "ciphertext": ciphertext,
        "vanity_slug": vanity if vanity and not str(vanity).startswith("~") else None,
        "name": V.text(profile.get("name")),
        "title": V.text(profile.get("title")),
        "link": V.freelancer_link(vanity if vanity and not str(vanity).startswith("~") else ciphertext),
        "description": V.multiline(profile.get("description")),
        "photo": g(profile, "portrait", "bigPortrait") or g(profile, "portrait", "portrait"),
        "location": {
            "city": V.text(location.get("city")), "state": V.text(location.get("state")),
            "country": V.text(location.get("country")), "country_code": location.get("countryCodeIso2"),
            "timezone": V.text(location.get("countryTimezone")),
            "utc_offset_hours": (V.num(location.get("timezoneOffset")) or 0) / 3600
            if location.get("timezoneOffset") is not None else None,
        },
        "hourly_rate": {"amount": rate, "currency": g(stats, "hourlyRate", "currencyCode") or "USD"} if rate is not None else None,
        "experience_level": experience_level(profile.get("contractorTier")),
        "availability": _availability(wrapper.get("availability")),
        "is_open_to_contract_to_hire": bool(profile.get("contractToHire")),
        "skills": skills(profile.get("skills")),
        "categories": categories,
        "specialized_profiles": specialized or None,
        "stats": {
            "job_success_score": None if profile.get("hideJss") else V.percent(stats.get("nSS100BwScore")),
            "rating": V.rating(stats.get("rating")),
            "recent_rating": V.rating(stats.get("ratingRecent")),
            "feedback_count": V.to_int(stats.get("totalFeedback")),
            "total_jobs": V.to_int(stats.get("totalJobsWorked")),
            "hourly_jobs": V.to_int(stats.get("totalHourlyJobs")),
            "fixed_jobs": V.to_int(stats.get("totalFixedJobs")),
            "total_hours": V.hours(stats.get("totalHoursActual") or stats.get("totalHours")),
            "recent_hours": V.hours(stats.get("totalHoursRecent")),
            "hire_again_percentage": V.rating(stats.get("hireAgainPercentage")),
            "total_earnings": None if hide_earnings else V.positive(stats.get("totalEarningsNumValue") or stats.get("totalEarnings")),
            "member_since": V.iso_date(stats.get("memberSince")),
            "last_worked_at": V.iso_date(stats.get("lastWorkedOn")),
            "responsiveness": V.lower_snake(stats.get("responsiveState")) or None,
            "english_level": V.positive(stats.get("englishLevel")),
        },
        "badges": {**_badges(stats.get("topRatedStatus"), stats.get("topRatedPlusStatus"), None),
                   "is_id_verified": bool(g(profile, "idv", "isVerified") or profile.get("idBadgeStatus") == "PASSED"),
                   "is_phone_verified": bool(profile.get("phoneVerified"))},
        "profile_completeness": V.to_int(g(profile, "pci", "display")),
        "is_earnings_hidden": hide_earnings,
        "agencies": [a for a in agencies if a] or None,
        "portfolio": [_portfolio_item(p) for p in as_list(wrapper.get("portfolios"))],
        "portfolio_count": V.to_int(stats.get("totalPortfolioItems")),
        "languages": [l for l in (_language(x) for x in as_list(wrapper.get("languages"))) if l] or None,
        "education": _generic_items(wrapper.get("education"), (("institutionName", "institution"), ("areaOfStudy", "area_of_study"),
                                                              ("degree", "degree"), ("dateStarted", "started"), ("dateEnded", "ended"),
                                                              ("comment", "comment"))),
        "employment_history": _generic_items(wrapper.get("employmentHistory"), (("companyName", "company"), ("jobTitle", "title"),
                                                                              ("city", "city"), ("country", "country"),
                                                                              ("startDate", "started"), ("endDate", "ended"),
                                                                              ("description", "description"))),
        "certificates": _generic_items(wrapper.get("certificates"), (("name", "name"), ("provider", "provider"),
                                                                    ("description", "description"), ("verificationUrl", "link"))),
        "work_history": {
            "completed": work_history_page(completed, V.to_int(completed.get("currentPage")) or 1,
                                           V.to_int(completed.get("itemsPerPage")) or 10),
            "in_progress": work_history_page(in_progress, V.to_int(in_progress.get("currentPage")) or 1,
                                             V.to_int(in_progress.get("itemsPerPage")) or 10),
        },
        "testimonials": as_list(g(pv, "testimonials")) or None,
        "related_skills": [V.text(s.get("pretty") or s.get("name")) for s in as_list(g(pv, "relatedSkills")) if isinstance(s, dict)] or None,
    }


def hire_page_profile(item):
    """A curated profile tile of a /hire/<skill>/ page."""
    item = as_dict(item)
    ciphertext = item.get("ciphertext")
    hide = bool(item.get("hideEarnings"))
    return {
        "id": item.get("personUid"),
        "ciphertext": ciphertext,
        "name": V.text(item.get("shortName")),
        "title": V.text(item.get("title")),
        "link": V.freelancer_link(ciphertext),
        "description": V.multiline(item.get("description")),
        "photo": item.get("portrait150") or item.get("portrait"),
        "location": _location(item.get("location")),
        "hourly_rate": {"amount": V.amount(item.get("hourlyRate")), "currency": "USD"} if item.get("hourlyRate") else None,
        "skills": skills(item.get("skills")),
        "stats": {
            "job_success_score": V.percent(item.get("nSS100BwScore")) or V.to_int(item.get("nss100")),
            "rating": V.rating(item.get("avgFeedbackScore")),
            "feedback_count": V.to_int(item.get("totalFeedback")),
            "total_jobs": V.to_int(item.get("totalJobsCount")),
            "total_hours": V.hours(item.get("totalHours")),
            "total_earnings": None if hide else V.positive(item.get("totalEarnings") or item.get("totalEarned")),
        },
        "is_id_verified": bool(item.get("isVerified")),
    }


def hire_page(state):
    data = _asyncdata(state)
    if data is None or not isinstance(data.get("profiles"), list):
        return None
    meta = as_dict(data.get("metaData"))
    cost = as_dict(data.get("costTable"))
    return {
        "skill": V.text(meta.get("name")),
        "slug": meta.get("slug"),
        "skill_id": meta.get("attributeId"),
        "title": V.text(data.get("prettyNameCaseFix") or meta.get("modifier")),
        "reviews": {"average_rating": V.rating(g(data, "reviews", "avgRating")), "count": V.to_int(g(data, "reviews", "totalCount"))},
        "freelancers": [hire_page_profile(p) for p in data["profiles"] if g(p, "ciphertext")],
        "cost_guide": {
            "title": V.text(cost.get("title")),
            "summary": V.strip_html(cost.get("intro")),
            "rows": [{"project_type": V.text(r.get("projectType")), "cost_range": V.text(r.get("costRange")),
                      "cost_unit": V.text(r.get("costUnit")), "experience_level": V.text(r.get("experienceLevel")),
                      "deliverables": [V.text(d) for d in as_list(r.get("deliverables"))]}
                     for r in as_list(cost.get("rows")) if isinstance(r, dict)],
        } if cost else None,
        "hiring_guide": V.strip_html(g(data, "content", "content")),
        "faq": [{"question": V.strip_html(f.get("question")), "answer": V.strip_html(f.get("answer"))}
                for f in as_list(g(data, "hireFaq", "items")) if isinstance(f, dict)] or None,
        "related_skill_pages": [_related_link(r) for r in as_list(data.get("interlinkingSkillsLinks"))],
        "breadcrumbs": [V.text(b.get("name")) for b in as_list(data.get("breadcrumbs")) if g(b, "name")],
    }


# ---- agencies ---------------------------------------------------------------------------------------------

def agency_profile(state):
    a = as_dict(g(state, "vuex", "agencyProfile", "agency"))
    if not a.get("id") and not a.get("name"):
        return None
    owner = as_dict(g(a, "ownerStaff", "personalData"))
    settings = as_dict(g(state, "vuex", "agencyProfile", "agencyProfileSettings"))
    return {
        "id": str(a.get("id")),
        "ciphertext": a.get("ciphertext"),
        "name": V.text(a.get("name")),
        "link": V.agency_link(a.get("id")),
        "tagline": V.text(a.get("summary")),
        "description": V.multiline(a.get("description")),
        "logo": a.get("photo"),
        "website": a.get("website"),
        "hourly_rate": V.money_range(a.get("minRate"), a.get("maxRate")),
        "minimum_project_size": V.text(a.get("minimumProjectSize")),
        "company_size": V.text(a.get("numberOfEmployees")),
        "year_founded": V.to_int(a.get("agencyYearFounded")),
        "client_focus": [V.lower_snake(c) for c in as_list(a.get("clientFocus"))] or None,
        "stats": {
            "job_success_score": V.percent(a.get("jobSuccessScore")),
            "total_jobs": V.to_int(a.get("totalJobs")),
            "total_hours": V.hours(a.get("totalHours")),
            "total_earnings": V.positive(a.get("totalEarnings")),
            "member_since": V.iso_date(a.get("memberSinceDateTime")),
            "last_worked_at": V.iso_date(a.get("lastDateWorkedDateTime")),
        },
        "badges": _badges(a.get("topRatedStatus"), a.get("topRatedPlusStatus"), a.get("vetted")),
        "skills": skills(a.get("skills")),
        "services": [{"category": V.text(s.get("occupationName")), "category_id": s.get("occupationId"),
                      "title": V.text(s.get("customTitle")), "description": V.multiline(s.get("description"))}
                     for s in as_list(a.get("services")) if isinstance(s, dict)],
        "featured_clients": [{"name": V.text(c.get("name")), "description": V.multiline(c.get("description"))}
                             for c in as_list(a.get("featuredClients")) if isinstance(c, dict)],
        "languages": [l for l in (_language(x) for x in as_list(a.get("languages"))) if l] or None,
        "awards": [{"name": V.text(w.get("name")), "description": V.multiline(w.get("description"))}
                   for w in as_list(a.get("awards")) if isinstance(w, dict)] or None,
        "owner": {"id": owner.get("id"), "name": V.text(owner.get("name")), "ciphertext": owner.get("ciphertext"),
                  "link": V.freelancer_link(owner.get("ciphertext")), "photo": owner.get("portrait")} if owner else None,
        "teams": [{"id": t.get("id"), "name": V.text(t.get("name"))} for t in as_list(a.get("teams")) if isinstance(t, dict)] or None,
        "category_ids": as_list(a.get("projectCategoryIds")) or None,
        "shows_members": not settings.get("hideMembers") if settings else None,
    }


def agency_location(item):
    item = as_dict(item)
    return {"city": V.text(item.get("city")), "state": V.text(item.get("state")), "country": V.text(item.get("country")),
            "address": V.text(item.get("address")), "zip_code": V.text(item.get("zipCode"))}


def agency_member(item):
    item = as_dict(item)
    person = as_dict(item.get("personalData"))
    return {
        "id": person.get("id"),
        "ciphertext": person.get("ciphertext"),
        "name": V.text(person.get("name")),
        "link": V.freelancer_link(person.get("ciphertext")),
        "photo": person.get("portrait"),
        "role": "owner" if item.get("agencyOwner") else V.lower_snake(item.get("memberType")),
        "is_owner": bool(item.get("agencyOwner")),
        "is_active": bool(item.get("active")),
        "is_profile_public": person.get("profileAccess") == "PublicAccess" and bool(item.get("canBeViewed")),
        "job_success_score": None if person.get("hideJss") else V.percent(person.get("jobSuccessScore")),
        "badges": _badges(person.get("topRatedStatus"), person.get("topRatedPlusStatus"), item.get("vetted")),
    }


def _agency_feedback(node):
    node = as_dict(node)
    if not node:
        return None
    score = V.rating(node.get("score"))
    comment = V.multiline(node.get("comment")) if node.get("commentPublic", True) else None
    if score is None and comment is None:
        return None
    return {"score": score, "comment": comment,
            "details": {V.lower_snake(d.get("label")): V.rating(d.get("score")) for d in as_list(node.get("details"))
                        if isinstance(d, dict) and d.get("label")} or None}


def agency_contract(item):
    item = as_dict(item)
    ciphertext = item.get("ciphertext")
    hide = bool(item.get("hideEacEarnings"))
    return {
        "title": V.text(item.get("title")),
        "job_id": V.job_id(ciphertext),
        "job_link": V.job_link(ciphertext),
        "job_type": job_type(item.get("jobType")),
        "status": V.lower_snake(item.get("status")),
        "started_at": V.iso_datetime(item.get("startedOnDateTime")),
        "ended_at": V.iso_datetime(item.get("endedOnDateTime")),
        "total_hours": V.hours(item.get("totalHours")),
        "hourly_rate": {"amount": V.amount(item.get("hourlyRate")), "currency": "USD"} if item.get("hourlyRate") else None,
        "total_charged": None if hide else V.money({"amount": item.get("totalCharges")}),
        "total_cost": None if hide else V.money({"amount": item.get("totalCost")}),
        "contractor_earnings": None if hide else V.money({"amount": item.get("contractorEarnings")}),
        "client_team_id": item.get("clientTeamUid"),
        "feedback_from_client": _agency_feedback(item.get("feedback")),
        "feedback_to_client": _agency_feedback(item.get("feedbackGiven")),
    }


def agency_project(node):
    node = as_dict(node)
    return {
        "id": node.get("id"),
        "title": V.text(node.get("title")),
        "description": V.multiline(node.get("description")),
        "project_link": node.get("projectUrl"),
        "thumbnail": V.link(node.get("thumbnail")),
        "completed_at": V.iso_date(node.get("completionDateTime")),
        "category_id": node.get("categoryId"),
        "skill_ids": as_list(node.get("skillIds")) or None,
        "attachments": [{"type": a.get("type"), "title": V.text(a.get("title")), "name": a.get("name"),
                         "image": V.link(a.get("imageLarge") or a.get("imageMiddle")), "file": V.link(a.get("originalFile"))}
                        for a in as_list(node.get("attachments")) if isinstance(a, dict)] or None,
    }


# ---- services (project catalog) ------------------------------------------------------------------------------

def _seller(person):
    person = as_dict(person)
    if not person:
        return None
    ciphertext = person.get("ciphertext")
    return {
        "id": person.get("uid") or person.get("id"),
        "ciphertext": ciphertext,
        "name": V.text(person.get("name") or person.get("shortName") or g(person, "detail", "name")),
        "link": V.freelancer_link(person.get("vanityUrl") or ciphertext),
        "photo": person.get("portrait100") or person.get("smallPortrait"),
        "rating": V.rating(person.get("adjScore") if person.get("adjScore") is not None else person.get("rating")),
        "feedback_count": V.to_int(person.get("totalFeedback")),
        "badges": {"is_top_rated": bool(person.get("topRated")) or bool(person.get("topRatedPlus")),
                   "is_top_rated_plus": bool(person.get("topRatedPlus")),
                   "is_rising_talent": bool(person.get("risingTalent"))},
    }


def _cover_image(tile):
    url = tile.get("coverImageUrl") or tile.get("thumbnailUrl") or g(tile, "coverMedia", "url")
    if url:
        return url
    meta = g(tile, "coverMedia", "metadataJson") or g(tile, "media", 0, "metadataJson")
    try:
        return g(json.loads(meta), "secure_url") if isinstance(meta, str) else None
    except ValueError:
        return None


def service_tile(tile):
    """A catalog project tile (GraphQL {id, data, person} or the SSR flat shape)."""
    tile = as_dict(tile)
    data = as_dict(tile.get("data")) or tile
    slug = data.get("slug")
    price_start = V.amount(data.get("priceStart"))
    return {
        "id": str(tile.get("id") or tile.get("uid") or "") or None,
        "title": V.text(data.get("title") or data.get("name")),
        "slug": slug,
        "link": V.service_link(slug),
        "cover_image": _cover_image(tile),
        "starting_price": {"amount": price_start, "currency": "USD"} if price_start is not None else None,
        "delivery_days": V.to_int(data.get("minDaysToFulfill") or data.get("deliveryTime")),
        "status": V.lower_snake(data.get("status")),
        "flow_type": V.lower_snake(data.get("flowType")) if isinstance(data.get("flowType"), str) else None,
        "seller": _seller(tile.get("person")),
    }


def _package(pkg):
    pkg = as_dict(pkg)
    specs = []
    for spec in as_list(pkg.get("specs")):
        spec = as_dict(spec)
        selected = [c.get("choiceLabel") for c in as_list(spec.get("choices")) if g(c, "selected")]
        value = spec.get("value") if spec.get("value") not in (None, "") else (", ".join(selected) if selected else None)
        if spec.get("label"):
            specs.append({"name": V.text(spec.get("label")), "value": V.text(value) if value is not None else None})
    return {
        "id": pkg.get("uid"),
        "tier": V.text(pkg.get("title")),
        "title": V.text(pkg.get("customTitle")),
        "description": V.multiline(pkg.get("customDescription")),
        "price": {"amount": V.amount(pkg.get("price")), "currency": "USD"},
        "delivery_days": V.to_int(pkg.get("daysToFulfill")),
        "extra_fast": {"price": V.amount(pkg.get("extraFastPrice")), "delivery_days": V.to_int(pkg.get("extraFastDaysToFulfill"))}
        if pkg.get("extraFastPrice") else None,
        "specs": specs,
    }


def _addons(addons):
    addons = as_dict(addons)
    out = []
    for key in ("scopeAddons", "optionAddons", "customAddons"):
        for item in as_list(addons.get(key)):
            item = as_dict(item)
            out.append({"kind": V.lower_snake(key.replace("Addons", "")), "title": V.text(item.get("title") or item.get("label") or item.get("name")),
                        "description": V.multiline(item.get("description")), "price": V.amount(item.get("price")),
                        "delivery_days": V.to_int(item.get("daysToFulfill"))})
    return out or None


def service_review(item):
    item = as_dict(item)
    first, last = V.text(item.get("clientFirstName")), V.text(item.get("clientLastName"))
    return {
        "id": str(item.get("id") or "") or None,
        "score": V.rating(item.get("score")),
        "text": V.multiline(item.get("text")),
        "client_name": " ".join(x for x in (first, last) if x) or None,
        "contract_title": V.text(item.get("assignmentTitle")),
        "ended_at": V.iso_datetime(item.get("assignmentEndedOn")),
        "is_for_this_service": bool(item.get("projectId")),
        "details": {V.lower_snake(d.get("name")): V.rating(d.get("score")) for d in as_list(item.get("details"))
                    if isinstance(d, dict) and d.get("name")} or None,
    }


def feedback_statistics(stats):
    stats = as_dict(stats)
    if not stats:
        return None
    return {
        "average_rating": V.rating(stats.get("averageScore")),
        "count": V.to_int(stats.get("totalCountOfRates")),
        "distribution": {str(d.get("rate")): V.to_int(d.get("count")) for d in as_list(stats.get("distributions")) if isinstance(d, dict)} or None,
        "details": {V.lower_snake(d.get("name")): V.rating(d.get("averageScore")) for d in as_list(stats.get("detailsDistributions"))
                    if isinstance(d, dict) and d.get("name")} or None,
    }


def service_details(state):
    """The project catalog store of a /services/product/<slug> page."""
    selected = as_dict(g(state, "state", "projects", "projectSelected"))
    wrapper = as_dict(selected.get("project"))
    project = as_dict(wrapper.get("project"))
    if not project.get("uid"):
        return None
    desc = as_dict(wrapper.get("description"))
    freelancer = as_dict(selected.get("freelancer"))
    reviews_store = as_dict(g(state, "state", "reviews"))
    seller_uid = freelancer.get("uid") or project.get("providerPersonUid")
    stats = feedback_statistics(g(reviews_store, "feedbackStatistics", str(seller_uid))) if seller_uid else None
    feedbacks = as_dict(g(reviews_store, "feedbacks", str(seller_uid))) if seller_uid else {}
    by_project = as_dict(feedbacks.get("byThisProject"))
    by_all = as_dict(feedbacks.get("byAllProjects"))
    taxonomy = as_dict(wrapper.get("taxonomy"))
    specs = []
    for spec in as_list(project.get("specs")):
        spec = as_dict(spec)
        selected_choices = [V.text(c.get("choiceLabel")) for c in as_list(spec.get("choices")) if g(c, "selected")]
        if spec.get("label") and (selected_choices or spec.get("value")):
            specs.append({"name": V.text(spec.get("label")), "values": selected_choices or [V.text(spec.get("value"))]})
    media = []
    for item in as_list(wrapper.get("media")):
        try:
            meta = json.loads(g(item, "metadataJson") or "{}")
        except ValueError:
            meta = {}
        url = meta.get("secure_url") or g(meta, "links", "c_scale,w_1000/jpg")
        if url:
            media.append(url)
    return {
        "id": str(project.get("uid")),
        "title": V.text(project.get("title")),
        "slug": project.get("slug"),
        "link": V.service_link(project.get("slug")),
        "description": V.multiline(desc.get("description")),
        "cover_image": desc.get("coverImageUrl") or (media[0] if media else None),
        "media": media or None,
        "status": V.lower_snake(project.get("status")),
        "project_type": {"id": project.get("typeId"), "name": V.text(g(taxonomy, "projectTypeConcept", "label")
                                                                       or g(taxonomy, "projectType", "label"))},
        "category": V.text(g(taxonomy, "projectCategoriesL4", 0, "label")) or None,
        "specs": specs,
        "tags": [V.text(t) for t in as_list(wrapper.get("tags")) if t] or None,
        "packages": [_package(p) for p in as_list(wrapper.get("packages"))],
        "add_ons": _addons(wrapper.get("addons")),
        "requirements": [{"question": V.text(r.get("title")), "type": V.lower_snake(r.get("type")), "is_required": bool(r.get("isRequired"))}
                         for r in as_list(project.get("requirementsFormJson")) if isinstance(r, dict)] or None,
        "max_queue_size": V.to_int(project.get("maxQueueSize")),
        "active_orders": V.to_int(project.get("currentOrdersCount")),
        "created_at": V.iso_datetime(str(project.get("createdTs") or "").replace(" ", "T").replace("+00", "+00:00")),
        "updated_at": V.iso_datetime(str(project.get("updatedTs") or "").replace(" ", "T").replace("+00", "+00:00")),
        "seller": {
            **(_seller(freelancer) or {}),
            "title": V.text(freelancer.get("title")),
            "description": V.multiline(freelancer.get("description")),
            "top_rated_status": _top_rated_status(freelancer.get("topRatedStatus"), freelancer.get("topRatedStatusEx")),
            "job_success_score": V.percent(freelancer.get("jss")),
            "is_id_verified": bool(freelancer.get("isIdentityVerified")),
        } if freelancer else None,
        "reviews": {
            "statistics": stats,
            "for_this_service": {"count": V.to_int(by_project.get("totalItemsLength")),
                                 "items": [service_review(f) for f in as_list(by_project.get("feedbacks"))]},
            "for_all_services": {"count": V.to_int(by_all.get("totalItemsLength")),
                                 "items": [service_review(f) for f in as_list(by_all.get("feedbacks"))]},
        },
    }


def catalog_facets(facets):
    facets = as_dict(facets)
    cats = as_dict(facets.get("projectCategoryL4Facets"))
    talent = as_dict(facets.get("talentDetailsFacets"))
    delivery = as_dict(facets.get("deliveryTimeFacets"))
    return {
        "total": V.to_int(cats.get("allCount")),
        "categories": {f.get("id"): V.to_int(f.get("count")) for f in as_list(cats.get("facets")) if g(f, "id")} or None,
        "delivery_time": {"any": V.to_int(delivery.get("anyTime")), "within_1_day": V.to_int(delivery.get("lessThan1Day")),
                          "within_7_days": V.to_int(delivery.get("lessThan7Days")), "within_21_days": V.to_int(delivery.get("lessThan21Days"))}
        if delivery else None,
        "seller": {"top_rated": V.to_int(talent.get("topRated")), "top_rated_plus": V.to_int(talent.get("topRatedPlus")),
                   "rising_talent": V.to_int(talent.get("risingTalent")),
                   "english_native": V.to_int(talent.get("englishProficiencyLevelRank4")),
                   "english_fluent": V.to_int(talent.get("englishProficiencyLevelRank3"))} if talent else None,
    }


# ---- metadata ---------------------------------------------------------------------------------------------------

def category(item):
    item = as_dict(item)
    return {
        "id": item.get("id"),
        "name": V.text(item.get("preferredLabel")),
        "ontology_id": item.get("ontologyId"),
        "subcategories": [{
            "id": s.get("id"), "name": V.text(s.get("preferredLabel")), "ontology_id": s.get("ontologyId"),
            "services": [{"id": x.get("id"), "name": V.text(x.get("preferredLabel")), "ontology_id": x.get("ontologyId")}
                         for x in as_list(s.get("services")) if isinstance(x, dict)],
        } for s in as_list(item.get("subcategories")) if isinstance(s, dict)],
        "services": [{"id": x.get("id"), "name": V.text(x.get("preferredLabel")), "ontology_id": x.get("ontologyId")}
                     for x in as_list(item.get("services")) if isinstance(x, dict)],
    }
