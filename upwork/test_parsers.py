"""Offline tests: the Nuxt decoders, refs resolvers, marshmallow schemas,
value helpers, parsers and the endpoint functions with the transport
monkeypatched to serve fixtures (upwork/fixtures/*.json.gz, raw payloads and
decoded page states captured 2026-10-14) — no network.

    python -m pytest upwork/test_parsers.py -q
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schema_fields import load_query  # noqa: E402
from upwork import (agencies, fetch, freelancers, jobs, meta, nuxt, parsers as P, refdata, refs,  # noqa: E402
                    schemas, services, values as V)

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fx(name):
    with gzip.open(os.path.join(FX, name + ".json.gz"), "rt", encoding="utf-8") as f:
        return json.load(f)


def fx_html(name):
    with gzip.open(os.path.join(FX, name + ".html.gz"), "rb") as f:
        return f.read().decode("utf-8")


# ---- nuxt decoders -------------------------------------------------------------------------------

def test_decode_nuxt3_job_page():
    state = nuxt.decode_nuxt3(fx_html("job_page_fixed"))
    job = state["vuex"]["jobDetails"]["job"]
    assert job["ciphertext"] == "~022110260925663995874" and job["title"] == "Web scraping"
    assert state["vuex"]["jobDetails"]["buyer"]["location"]["country"] == "United States"


def test_decode_nuxt2_profile_page():
    state = nuxt.decode_nuxt2(fx_html("profile_page_cipher"))
    profile = state["state"]["profileViewer"]["profile"]
    assert profile["identity"]["ciphertext"] == "~01d699cdd471617458"
    assert profile["profile"]["name"] == "Ronald T."
    assert isinstance(profile["stats"]["totalHours"], float)
    # hoisted assignments ran: the work-history sort object was filled in
    assert state["state"]["profileViewer"]["workHistory"]["selectedSortByType"]["name"] == "Newest"


def test_decode_nuxt2_subset():
    html = ('<script>window.__NUXT__=(function(a,b,c){K.x=a;return {layout:"default",data:[{}],'
            'state:{n:b,s:c,arr:[a,,b],neg:-1.5e2,u:void 0,t:!0,f:!1,sparse:Array(2),k:K,key:{"q-1":c}}}}'
            '("x\\u002Fy",42,null));</script>').replace("K.x=a;", "")
    html = html.replace("k:K,", "")
    state = nuxt.decode_nuxt2(html)
    assert state["state"] == {"n": 42, "s": None, "arr": ["x/y", None, 42], "neg": -150, "u": None, "t": True,
                              "f": False, "sparse": [None, None], "key": {"q-1": None}}


def test_decode_errors():
    with pytest.raises(nuxt.NuxtStateError):
        nuxt.decode_nuxt3("<html>Just a moment</html>")
    with pytest.raises(nuxt.NuxtStateError):
        nuxt.decode_nuxt2("<html></html>")


# ---- refs ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("~022110260925663995874", "~022110260925663995874"), ("2110260925663995874", "~022110260925663995874"),
    ("https://www.upwork.com/jobs/Web-scraping_~022110260925663995874/?x=1", "~022110260925663995874"),
    ("https://www.upwork.com/freelance-jobs/apply/Web-scraping_~022110260925663995874/", "~022110260925663995874"),
    ("upwork.com/jobs/~022110260925663995874", "~022110260925663995874"),
])
def test_resolve_job(value, expected):
    assert refs.resolve_job(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "https://example.com/jobs/~022110260925663995874", "https://www.upwork.com/hire/x/"])
def test_resolve_job_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_job(value)


@pytest.mark.parametrize("value,expected", [
    ("~01d699cdd471617458", "~01d699cdd471617458"), ("sohaibilyas", "sohaibilyas"),
    ("https://www.upwork.com/freelancers/~01d699cdd471617458?referrer_url_path=x", "~01d699cdd471617458"),
    ("https://www.upwork.com/freelancers/sohaibilyas", "sohaibilyas"),
])
def test_resolve_freelancer(value, expected):
    assert refs.resolve_freelancer(value) == expected


def test_resolve_freelancer_rejects_numeric():
    with pytest.raises(ValueError):
        refs.resolve_freelancer("424309742238941184")


@pytest.mark.parametrize("value,expected", [
    ("425249375254638592", "425249375254638592"), ("~01559cda955b6ac18a", "~01559cda955b6ac18a"),
    ("https://www.upwork.com/agencies/425249375254638592/", "425249375254638592"),
    ("https://www.upwork.com/ag/talentegia/", "talentegia"),
])
def test_resolve_agency(value, expected):
    assert refs.resolve_agency(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("1585271712814411776", "project-1585271712814411776"),
    ("development-it-a-data-scraping-task-within-24-48hrs-1585271712814411776",
     "development-it-a-data-scraping-task-within-24-48hrs-1585271712814411776"),
    ("https://www.upwork.com/services/product/development-it-x-1585271712814411776", "development-it-x-1585271712814411776"),
])
def test_resolve_service(value, expected):
    assert refs.resolve_service(value) == expected
    assert refs.service_id(expected) == "1585271712814411776"


@pytest.mark.parametrize("value,expected", [
    ("Python", "python"), ("Web Scraping", "web-scraping"), ("C#", "c-sharp"), ("node.js", "node-js"),
    ("https://www.upwork.com/hire/python-developers/", "python-developers"),
    ("https://www.upwork.com/freelance-jobs/python/", "python"),
])
def test_resolve_skill(value, expected):
    assert refs.resolve_skill(value) == expected


# ---- refdata -----------------------------------------------------------------------------------------

def test_refdata_lookups():
    assert refdata.location("usa") == ("United States", "country")
    assert refdata.location("Europe") == ("Europe", "region")
    assert refdata.location("southern asia") == ("Southern Asia", "subregion")
    assert refdata.location("Narnia") is None
    assert refdata.us_state("california") == "CA" and refdata.us_state("TX") == "TX"
    assert refdata.timezone("America/New_York")[0] == "America/New_York"
    assert refdata.timezone("UTC-05:00")[1] == "UTC-05:00"
    assert refdata.timezone("+05:30")[0] == "Asia/Calcutta"
    assert refdata.category("Web, Mobile & Software Dev")["id"] == "531770282580668418"
    assert refdata.subcategory("Web Development")["id"] == "531770282584862733"
    assert len(refdata.LOCATIONS) == 263 and len(refdata.CATEGORIES) == 12


# ---- schemas ------------------------------------------------------------------------------------------

def test_job_search_schema():
    data, err = load_query(schemas.JobSearchSchema, {
        "query": "python", "job_type": "hourly,fixed", "experience_level": "Expert", "hourly_rate_min": "20",
        "client_location": "us,Europe", "client_timezone": "America/New_York", "duration": "month",
        "category": "Web, Mobile & Software Dev, IT & Networking", "subcategory": "Web Development", "per_page": "20",
        "contract_to_hire": "yes"})
    assert err is None
    assert data["job_type"] == ["hourly", "fixed"] and data["experience_level"] == ["expert"]
    assert data["client_location"] == ["United States", "Europe"] and data["client_timezone"] == ["America/New_York"]
    assert data["category"] == ["531770282580668418", "531770282580668419"] and data["subcategory"] == ["531770282584862733"]
    assert data["per_page"] == 20 and data["contract_to_hire"] is True and data["hourly_rate_min"] == 20


@pytest.mark.parametrize("query", [
    {"query": "x", "job_type": "weekly"}, {"query": "x", "per_page": "15"}, {"query": "x", "client_location": "Narnia"},
    {"query": "x", "hourly_rate_min": "50", "hourly_rate_max": "20"}, {"query": "x", "bogus": "1"},
    {"query": "x", "category": "Astrology"}, {"query": "x", "skill_ids": "abc"},
])
def test_job_search_schema_rejects(query):
    assert load_query(schemas.JobSearchSchema, query)[1] is not None


def test_freelancer_search_schema():
    data, err = load_query(schemas.FreelancerSearchSchema, {
        "query": "python", "english_level": "fluent", "location": "india,americas", "us_state": "ca,Texas",
        "timezone": "UTC+05:30", "languages": "en,FR", "talent_type": "agency", "job_success_min": "90", "per_page": "50"})
    assert err is None
    assert data["english_level"] == 3 and data["location"] == [("India", "country"), ("Americas", "region")]
    assert data["us_state"] == ["CA", "TX"] and data["timezone"] == ["UTC+05:30"] and data["languages"] == ["en", "fr"]
    assert data["talent_type"] == "agency"
    assert load_query(schemas.FreelancerSearchSchema, {"page": "201", "per_page": "50"})[1] is not None


def test_other_schemas():
    data, err = load_query(schemas.WorkHistorySchema, {"freelancer": "https://www.upwork.com/freelancers/sohaibilyas", "status": "in_progress"})
    assert err is None and data["freelancer"] == "sohaibilyas" and data["status"] == "in_progress"
    data, err = load_query(schemas.ServiceSearchSchema, {"query": "logo", "category": "logoDesign", "price_max": "100"})
    assert err is None and data["category"] == "projectCategory:logoDesign" and data["price_max"] == 100
    assert load_query(schemas.ServiceSearchSchema, {})[1] is None    # no filter = the whole catalog
    data, err = load_query(schemas.SuggestSchema, {"query": "pyth", "type": "services"})
    assert err is None and data["kind"] == "services"
    data, err = load_query(schemas.AgencyWorkHistorySchema, {"agency": "~01559cda955b6ac18a", "status": "active"})
    assert err is None and data["agency"] == "~01559cda955b6ac18a"


# ---- values -------------------------------------------------------------------------------------------

def test_values():
    assert V.amount("48,000") == 48000 and V.amount(12.345) == 12.35 and V.amount(None) is None
    assert V.percent(1.0) == 100 and V.percent(0.9869) == 99 and V.rating(0) is None and V.rating(4.635285549) == 4.64
    assert V.text('Web <span class="highlight">scraping</span>') == "Web scraping"
    assert V.text("H^React^H Web App") == "React Web App"
    assert V.iso_datetime("2026-10-14T06:46:26.528Z") == "2026-10-14T06:46:26Z"
    assert V.iso_datetime("2023-03-02T13:03:20+0000") == "2023-03-02T13:03:20Z"
    assert V.iso_date("2012-03-02T00:00:00+0000") == "2012-03-02" and V.iso_date(None) is None
    assert V.lower_snake("IntermediateLevel") == "intermediate_level" and V.lower_snake("PART_TIME") == "part_time"
    assert V.money({"node": {"amount": 64478.76, "currencyCode": "USD"}}) == {"amount": 64478.76, "currency": "USD"}
    assert V.money_range("15.0", "30.0") == {"min": 15, "max": 30, "currency": "USD"} and V.money_range(None, None) is None
    assert V.job_id("~022110260925663995874") == "2110260925663995874"
    assert V.strip_html("<p>Hi <b>there</b></p><p>x</p>") == "Hi there\nx"


# ---- parsers: jobs ---------------------------------------------------------------------------------------

def test_job_card():
    result = fx("job_search")["search"]["universalSearchNuxt"]["visitorJobSearchV1"]
    cards = [P.job_card(r) for r in result["results"]]
    assert len(cards) == 20
    card = cards[0]
    assert card["id"].isdigit() and card["ciphertext"].startswith("~02") and card["link"].endswith(card["ciphertext"])
    assert card["job_type"] in ("hourly", "fixed") and card["experience_level"] in ("entry", "intermediate", "expert")
    assert card["published_at"].endswith("Z") and card["skills"] and all(s["name"] for s in card["skills"])
    hourly = next(c for c in cards if c["job_type"] == "hourly")
    assert hourly["budget"] is None and (hourly["hourly_rate"] is None or hourly["hourly_rate"]["currency"] == "USD")
    fixed = next(c for c in cards if c["job_type"] == "fixed")
    assert fixed["hourly_rate"] is None and fixed["budget"]["currency"] == "USD"
    facets = P.job_facets(result["facets"])
    assert set(facets) >= {"job_type", "experience_level", "duration", "client_hires"}
    assert set(facets["experience_level"]) <= {"entry", "intermediate", "expert"}


def test_job_details_fixed_and_hourly():
    fixed = P.job_details(fx("job_page_fixed"))
    assert fixed["id"] == "2110260925663995874" and fixed["job_type"] == "fixed"
    assert fixed["budget"] == {"amount": 50, "currency": "USD"} and fixed["hourly_rate"] is None
    assert fixed["client"]["stats"]["total_spent"]["amount"] == 16185.77 and fixed["client"]["stats"]["rating"] == 4.89
    assert fixed["client"]["location"]["city"] == "Chicago" and fixed["client"]["member_since"] == "2012-07-16"
    assert fixed["activity"]["proposals"] > 20 and fixed["activity"]["last_viewed_by_client_at"].endswith("Z")
    assert fixed["skills"][0]["name"] == "Data Scraping" and fixed["occupation"]["name"] == "Data Extraction"
    assert fixed["category"]["slug"] == "data-extraction-etl" and len(fixed["similar_jobs"]) == 4
    hourly = P.job_details(fx("job_page_hourly"))
    assert hourly["job_type"] == "hourly" and hourly["budget"] is None
    assert hourly["hourly_rate"] == {"min": 90, "max": 120, "currency": "USD"} and hourly["experience_level"] == "expert"
    assert hourly["skills"][0]["group"] == "Back-End Programming Languages"
    assert P.job_details(fx("job_page_closed")) is None


def test_skill_jobs_page():
    out = P.skill_jobs_page(fx("skill_jobs_page"))
    assert out["skill"] == "Web Scraping" and out["total_jobs"] > 100 and len(out["jobs"]) == 30
    job = out["jobs"][0]
    assert job["ciphertext"].startswith("~02") and job["link"] and job["skills"]
    assert out["related_job_pages"][0]["link"].startswith("https://www.upwork.com/freelance-jobs/")


# ---- parsers: freelancers ----------------------------------------------------------------------------------

def test_freelancer_card():
    result = fx("freelancer_search")["search"]["universalSearchNuxt"]["visitorFreelancerSearchV2"]
    cards = [P.freelancer_card(p) for p in result["profiles"]]
    assert len(cards) == 10
    card = cards[0]
    assert card["id"].isdigit() and card["ciphertext"].startswith("~01") and card["link"].endswith(card["ciphertext"])
    assert card["hourly_rate"]["currency"] == "USD" and card["skills"] and card["location"]["country"]
    assert 0 <= (card["stats"]["job_success_score"] or 0) <= 100
    assert set(card["badges"]) == {"top_rated_status", "is_top_rated", "is_top_rated_plus", "is_rising_talent",
                                   "is_expert_vetted", "is_id_verified"}
    meta_ = P.freelancer_search_meta(result)
    assert meta_["suggested_skills"] and meta_["suggested_skills"][0]["name"]


def test_freelancer_profile():
    out = P.freelancer_profile(fx("profile_page_vanity"))
    assert out["vanity_slug"] == "sohaibilyas" and out["link"] == "https://www.upwork.com/freelancers/sohaibilyas"
    assert out["id"] == "424309742238941184" and out["ciphertext"] == "~01048777e7ce6a3ace"
    assert out["hourly_rate"] == {"amount": 65, "currency": "USD"} and out["experience_level"] == "expert"
    assert out["stats"]["job_success_score"] == 100 and out["stats"]["total_jobs"] == 109 and out["stats"]["member_since"] == "2013-05-16"
    assert out["badges"]["is_top_rated_plus"] and out["badges"]["is_id_verified"] and out["badges"]["is_phone_verified"]
    assert out["availability"]["capacity"] == "More than 30 hrs/week"
    assert out["agencies"][0]["name"] == "Qoest" and out["categories"][0]["group"] == "Web, Mobile & Software Dev"
    assert len(out["portfolio"]) == 4 and out["portfolio"][0]["attachments"][0]["link"] == "https://reseek.net"
    completed = out["work_history"]["completed"]
    assert completed["pagination"]["total_count"] > 50 and len(completed["contracts"]) == 10
    contract = completed["contracts"][0]
    assert contract["title"] and contract["status"] == "closed" and contract["feedback_from_client"]["score"] == 5
    assert len(out["work_history"]["in_progress"]["contracts"]) == 10
    cipher = P.freelancer_profile(fx("profile_page_cipher"))
    # a profile opened by cipher still reports its vanity name when it has one
    assert cipher["vanity_slug"] == "tagslyf" and cipher["link"] == "https://www.upwork.com/freelancers/tagslyf"
    assert cipher["ciphertext"] == "~01d699cdd471617458"
    assert P.freelancer_profile(fx("profile_page_missing")) is None


def test_work_history_page():
    node = fx("work_history_completed")["history"]["node"]
    out = P.work_history_page(node, 1, 10)
    assert out["pagination"]["total_count"] == node["totalItems"] and len(out["contracts"]) == 10
    contract = out["contracts"][0]
    assert contract["job_type"] in ("hourly", "fixed") and contract["started_at"].endswith("Z")
    assert contract["skills"] and contract["skills"][0]["name"]
    assert all(c["total_charged"] is None or c["total_charged"]["currency"] == "USD" for c in out["contracts"])
    assert any(c["feedback_from_client"] for c in out["contracts"])
    active = P.work_history_page(fx("work_history_in_progress")["history"]["node"], 1, 10)
    assert all(c["status"] == "active" and c["ended_at"] is None for c in active["contracts"])


def test_hire_page():
    out = P.hire_page(fx("hire_page"))
    assert out["skill"] == "Python" and out["slug"] == "python-developers" and len(out["freelancers"]) == 9
    fl = out["freelancers"][0]
    assert fl["ciphertext"].startswith("~01") and fl["hourly_rate"]["amount"] > 0 and fl["stats"]["rating"] > 4
    assert out["cost_guide"]["rows"][0]["cost_range"].startswith("$") and out["faq"] and out["hiring_guide"]
    assert out["reviews"]["count"] > 10000


# ---- parsers: agencies -------------------------------------------------------------------------------------

def test_agency():
    out = P.agency_profile(fx("agency_page"))
    assert out["id"] == "425249375254638592" and out["name"].startswith("Talentegia")
    assert out["hourly_rate"] == {"min": 20, "max": 40, "currency": "USD"} and out["stats"]["job_success_score"] == 99
    assert out["badges"]["is_top_rated_plus"] and out["year_founded"] == 2012 and out["owner"]["name"] == "Shilpi J."
    assert out["languages"][0]["code"] == "en" and len(out["services"]) == 5 and out["client_focus"] == ["medium_business", "very_small_business", "small_business"]
    locs = [P.agency_location(l) for l in fx("agency_locations")["agencyLocations"]["locations"]]
    assert locs[0]["city"] == "Chandigarh" and locs[0]["country"] == "India"
    members = [P.agency_member(m) for m in fx("agency_members")["agencyStaffs"]["staffs"]]
    assert len(members) == 40 and members[0]["link"].startswith("https://www.upwork.com/freelancers/~01")
    assert members[0]["badges"]["is_top_rated_plus"] and members[0]["job_success_score"] == 100
    contracts = [P.agency_contract(c) for c in fx("agency_work_history")["organization"]["agency"]["upWorkHistory"]["workHistoryList"]]
    assert contracts[0]["job_type"] == "hourly" and contracts[0]["total_charged"]["amount"] == 1994.31
    assert any(c["feedback_from_client"] and c["feedback_from_client"]["comment"] for c in contracts)
    projects = [P.agency_project(e["node"]) for e in fx("agency_portfolio")["organization"]["agency"]["projects"]["edges"]]
    assert projects[0]["project_link"] == "https://tradeecho.com/" and projects[0]["thumbnail"].startswith("https://www.upwork.com/att/")


# ---- parsers: services -------------------------------------------------------------------------------------------

def test_service_tiles():
    result = fx("service_search")["search"]["universalSearchNuxt"]["visitorCatalogSearchV4"]
    tiles = [P.service_tile(p["projectTile"]) for p in result["projects"]]
    assert len(tiles) == 24 and result["paging"]["nextCursorMark"]
    tile = tiles[0]
    assert tile["id"].isdigit() and tile["link"].startswith("https://www.upwork.com/services/product/")
    assert tile["starting_price"]["currency"] == "USD" and tile["seller"]["name"] and tile["seller"]["rating"] > 0
    seller = [P.service_tile(t) for t in fx("seller_services")["browseCatalogProjectTilesForActiveFreelancers"]["projectTiles"]]
    assert seller and all(t["seller"]["id"] == "424318107916681216" for t in seller)
    facets = P.catalog_facets(fx("service_facets")["search"]["universalSearchNuxt"]["visitorCatalogSearchV4Facets"])
    assert facets["total"] > 1000 and "projectCategory:dataAnalysisReports" in facets["categories"]


def test_service_details():
    out = P.service_details(fx("service_page"))
    assert out["id"] == "1585271712814411776" and out["status"] == "active"
    assert out["packages"][0]["price"] == {"amount": 50, "currency": "USD"} and out["packages"][0]["delivery_days"] == 2
    assert out["packages"][0]["specs"][0] == {"name": "Number of Pages Mined/Scraped", "value": "10"}
    assert out["project_type"]["name"] == "Data Mining & Web Scraping" and out["specs"] == [{"name": "Data Tool", "values": ["Scrapy"]}]
    assert out["seller"]["link"] == "https://www.upwork.com/freelancers/gimar" and out["seller"]["feedback_count"] == 588
    assert out["reviews"]["statistics"]["average_rating"] == 4.89 and out["reviews"]["statistics"]["distribution"]["5"] == 538
    assert out["reviews"]["for_this_service"]["count"] == 7 and out["reviews"]["for_this_service"]["items"][0]["client_name"] == "Brad W"
    assert out["created_at"] == "2022-10-26T14:06:43Z"
    assert P.service_details({"state": {"projects": {"projectSelected": None}}}) is None


# ---- parsers: metadata ------------------------------------------------------------------------------------------------

def test_categories():
    rows = [P.category(c) for c in fx("categories")["ontologyCategories"]]
    assert len(rows) == 12 and rows[0]["name"] == "Accounting & Consulting"
    assert rows[0]["subcategories"][0]["services"][0]["name"] == "Accounting"


# ---- endpoint functions with the transport mocked ---------------------------------------------------------------

class _Transport:
    """fetch.graphql / fetch.page replacement that serves fixtures by alias / path."""

    def __init__(self):
        self.calls = []

    def graphql(self, app, query, variables=None, alias=None, label=None):
        self.calls.append((app, alias, variables))
        table = {
            "visitorJobSearch": "job_search", "visitorFreelancerSearchV2": "freelancer_search",
            "gql-query-agencylocations": "agency_locations", "gql-query-agencystaffs": "agency_members",
            "gql-query-catalog-visitor-search": "service_search", "catalogApp-visitor-search": "service_facets",
            "gql-query-search": "similar_services", "gql-query-browsecatalogprojecttilesforactivefreelancers": "seller_services",
            "gql-query-ontologycategories": "categories", "autoSuggestions": "suggestions",
            "relatedSuggestions": "related_queries", "gql-query-projectsuggestions": "service_suggestions",
            "gql-query-catalogRelatedQueriesV1": "related_queries",
        }
        if alias == "fetchFeedback":
            return fx("work_history_in_progress" if "InProgress" in query else "work_history_completed")
        if alias == "gql-query-organization":
            return fx("agency_portfolio" if "projects(" in query else "agency_work_history")
        return fx(table[alias])

    def page(self, path, params=None, label=None):
        self.calls.append(("page", path, params))
        if path.startswith("/jobs/~021389"):
            return "<html>closed</html>"
        raise AssertionError(f"unexpected page {path}")


@pytest.fixture
def transport(monkeypatch):
    t = _Transport()
    monkeypatch.setattr(fetch, "graphql", t.graphql)
    monkeypatch.setattr(fetch, "page", t.page)
    monkeypatch.setattr(fetch, "memoized", lambda key, fn, ttl=None: fn())
    return t


def test_jobs_search_endpoint(transport):
    out = jobs.search(query="python scraping", per_page=20, job_type=["hourly", "fixed"], experience_level=["expert"],
                      hourly_rate_min=20, client_location=["United States"], workload=["part_time"], page=2)
    req = transport.calls[0][2]["requestVariables"]
    assert req["paging"] == {"offset": 20, "count": 20} and req["contractorTier"] == ["ExpertLevel"]
    assert req["workload"] == ["as_needed", "part_time"] and req["hourlyRate"] == "20-" and req["location"] == ["United States"]
    assert len(out["jobs"]) == 20 and out["pagination"]["total_pages"] == 17 and out["facets"]["job_type"]


def test_jobs_details_closed(monkeypatch, transport):
    monkeypatch.setattr(nuxt, "decode_nuxt3", lambda html: fx("job_page_closed"))
    with pytest.raises(fetch.UpworkNotFound):
        jobs.details("~021389363061737230336")


def test_freelancers_search_endpoint(transport):
    out = freelancers.search(query="python", name=None, page=1, per_page=10, hourly_rate_min=20, hourly_rate_max=60,
                             job_success_min=90, english_level=3, top_rated=True, talent_type="agency",
                             location=[("India", "country"), ("Americas", "region")], us_state=["CA"], hours_min=100,
                             recent_hours_only=True)
    req = transport.calls[0][2]["request"]
    assert req["rate"] == {"rangeStart": 20, "rangeEnd": 60} and req["nss"] == {"rangeStart": 0.9, "rangeEnd": 1}
    assert req["languages"] == ["en"] and req["minLanguageRankEn"] == 3 and req["providerType"] == "Agency"
    assert req["countries"] == ["India"] and req["regions"] == ["Americas"] and req["states"] == ["CA"]
    assert req["totalHoursRecent"] == {"rangeStart": 100} and req["orFilters"] == [{"disjunctionFields": ["country", "region", "state"]}]
    assert len(out["freelancers"]) == 10 and out["pagination"]["total_pages"] == 1000


def test_work_history_endpoint(monkeypatch, transport):
    monkeypatch.setattr(freelancers, "person_id", lambda f: "424309742238941184")
    out = freelancers.work_history("sohaibilyas", status="in_progress", page=1, per_page=10)
    assert out["status"] == "in_progress" and out["freelancer_id"] == "424309742238941184" and len(out["contracts"]) == 10
    assert transport.calls[0][2]["personId"] == "424309742238941184"


def test_agency_endpoints(transport):
    out = agencies.members("425249375254638592")
    assert len(out["members"]) == 40 and out["pagination"]["total_pages"] == 1
    out = agencies.work_history("425249375254638592", status="active", page=2, per_page=10)
    assert transport.calls[-1][2]["type"] == ["ACTIVE"] and transport.calls[-1][2]["offset"] == 10
    assert out["pagination"]["total_pages"] == 39
    out = agencies.portfolio("425249375254638592")
    assert len(out["projects"]) == 10 and out["pagination"]["total_count"] == 10


def test_services_endpoints(transport):
    out = services.search(query="web scraping", price_min=20, price_max=100, delivery_days=7, top_rated=True,
                          english_level=3, with_facets=True)
    req = transport.calls[0][2]["request"]
    assert req["price"] == {"rangeStart": 20, "rangeEnd": 100} and req["maxDaysToFulfill"] == 7 and req["topRated"] is True
    assert req["paging"] == {"rows": 24} and len(out["services"]) == 24 and out["facets"]["total"] > 1000
    assert out["pagination"]["total_pages"] == 50
    page2 = services.search(query="web scraping", price_min=20, price_max=100, delivery_days=7, top_rated=True,
                            english_level=3, page=2)
    assert transport.calls[-1][2]["request"]["paging"]["cursorMark"].startswith("version_2_")
    assert page2["pagination"]["page"] == 2


def test_meta_endpoints(transport):
    out = meta.categories()
    assert out["count"] == 12
    out = meta.suggest("python dev", kind="jobs")
    assert out["suggestions"][0]["text"] == "python developer" and out["related_queries"]
    out = meta.suggest("web scra", kind="services")
    assert out["suggestions"][0]["frequency"] == 5484
