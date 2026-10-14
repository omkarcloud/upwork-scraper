"""Live endpoint smoke tests: one call per /upwork/* route against a running
service, with example values proven to return data (2026-10-14). The
listing tooling (derive_facts.py) reads each route's FIRST call from this
file's AST as its working example, so the values stay literals.

Skipped unless UPWORK_BASE points at a running service:

    SCRAPERS_PORT=6061 ONLY_SCRAPER=upwork python run.py
    UPWORK_BASE=http://127.0.0.1:6061 python -m pytest upwork/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("UPWORK_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set UPWORK_BASE to run live endpoint tests")


def call(path, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=300)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def status(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=300).status_code


def test_jobs_search():
    body = call("/upwork/jobs/search", query="python scraping", per_page=20)
    assert body["count"] > 50 and len(body["jobs"]) == 20 and body["next"] and body["facets"]["job_type"]
    job = body["jobs"][0]
    assert job["ciphertext"].startswith("~02") and job["title"] and job["link"] and job["published_at"]
    body = call("/upwork/jobs/search", query="react", job_type="hourly", experience_level="intermediate,expert",
                hourly_rate_min=20, client_location="United States,Europe", client_hires="10-", sort="relevance")
    assert body["jobs"] and all(j["job_type"] == "hourly" for j in body["jobs"])
    body = call("/upwork/jobs/search", query="logo", job_type="fixed", fixed_budget="500-999,1000-4999",
                category="Design & Creative")
    assert all(j["job_type"] == "fixed" for j in body["jobs"])


def test_jobs_details():
    from curl_cffi import requests
    # some fresh postings are private (invited freelancers only -> 404): take the first public one
    for job in call("/upwork/jobs/search", query="data entry")["jobs"][:5]:
        resp = requests.get(BASE + "/upwork/jobs/details", params={"job": f"https://www.upwork.com/jobs/{job['ciphertext']}"},
                            timeout=300)
        if resp.status_code == 200:
            break
    else:
        raise AssertionError("no public job among the first five search results")
    body = resp.json()
    assert body["ciphertext"] == job["ciphertext"] and body["description"] and body["client"]["location"]["country"]
    assert "proposals" in body["activity"] and body["skills"]
    assert status("/upwork/jobs/details", job="~021389363061737230336") == 404


def test_jobs_by_skill():
    body = call("/upwork/jobs/by-skill", skill="Web Scraping")
    assert body["skill"] == "Web Scraping" and len(body["jobs"]) == 30 and body["total_jobs"] > 50


def test_freelancers_search():
    body = call("/upwork/freelancers/search", query="python developer", per_page=20)
    assert body["count"] > 1000 and len(body["freelancers"]) == 20 and body["total_pages"] == 500
    fl = body["freelancers"][0]
    assert fl["ciphertext"].startswith("~01") and fl["title"] and fl["hourly_rate"]["currency"] == "USD"
    body = call("/upwork/freelancers/search", query="python", top_rated="true", hourly_rate_min=20, hourly_rate_max=60,
                location="United States", english_level="fluent", job_success_min=90)
    assert body["freelancers"] and all(f["badges"]["is_top_rated"] for f in body["freelancers"])
    assert all(f["location"]["country"] == "United States" for f in body["freelancers"])
    body = call("/upwork/freelancers/search", query="react", talent_type="agency", per_page=5)
    assert all(f["agency"] for f in body["freelancers"])


def test_freelancers_details():
    body = call("/upwork/freelancers/details", freelancer="https://www.upwork.com/freelancers/sohaibilyas")
    assert body["vanity_slug"] == "sohaibilyas" and body["skills"] and body["stats"]["total_jobs"] > 50
    assert body["work_history"]["completed"]["contracts"]
    body = call("/upwork/freelancers/details", freelancer="~01d699cdd471617458")
    assert body["name"] == "Ronald T."
    assert status("/upwork/freelancers/details", freelancer="~01000000000000dead") == 404


def test_freelancers_work_history():
    body = call("/upwork/freelancers/work-history", freelancer="sohaibilyas", per_page=5, page=2)
    assert body["count"] > 50 and len(body["contracts"]) == 5 and body["previous"]
    assert body["contracts"][0]["feedback_from_client"] or body["contracts"][0]["title"]
    body = call("/upwork/freelancers/work-history", freelancer="sohaibilyas", status="in_progress")
    assert all(c["status"] == "active" for c in body["contracts"])


def test_freelancers_top():
    body = call("/upwork/freelancers/top", skill="python")
    assert body["slug"] == "python-developers" and len(body["freelancers"]) >= 5 and body["cost_guide"]["rows"]
    body = call("/upwork/freelancers/top", skill="https://www.upwork.com/hire/data-extraction-freelancers/")
    assert body["freelancers"]


def test_agencies():
    body = call("/upwork/agencies/details", agency="~01559cda955b6ac18a")
    assert body["id"] == "425249375254638592" and body["locations"] and body["skills"] and body["stats"]["total_jobs"]
    body = call("/upwork/agencies/members", agency="425249375254638592")
    assert body["count"] >= 10 and body["members"][0]["link"]
    body = call("/upwork/agencies/work-history", agency="425249375254638592", per_page=5)
    assert body["count"] > 100 and len(body["contracts"]) == 5 and body["contracts"][0]["job_type"]
    body = call("/upwork/agencies/work-history", agency="https://www.upwork.com/agencies/425249375254638592/",
                status="active", per_page=5)
    assert all(c["status"] == "active" for c in body["contracts"])
    body = call("/upwork/agencies/portfolio", agency="425249375254638592", per_page=4)
    assert len(body["projects"]) == 4 and body["projects"][0]["title"]
    assert status("/upwork/agencies/details", agency="4252493752546385920000") == 404


def test_services():
    body = call("/upwork/services/search", query="web scraping", with_facets="true")
    assert body["count"] > 1000 and len(body["services"]) == 24 and body["facets"]["total"]
    page2 = call("/upwork/services/search", query="web scraping", page=2)
    assert page2["services"][0]["id"] not in {s["id"] for s in body["services"]}
    body = call("/upwork/services/search", query="logo", category="logoDesign", price_max=100, delivery_days=7,
                top_rated="true")
    assert body["services"] and all(s["starting_price"]["amount"] <= 100 for s in body["services"])
    body = call("/upwork/services/details", service="1585271712814411776")
    assert body["packages"][0]["price"]["amount"] == 50 and body["seller"]["name"] and body["reviews"]["statistics"]
    assert body["similar_services"]
    body = call("/upwork/services/by-seller", freelancer="gimar")
    assert body["count"] >= 1 and body["services"][0]["link"]
    assert status("/upwork/services/details", service="https://www.upwork.com/services/product/foo-0000000000000000001") == 404


def test_categories_and_suggest():
    body = call("/upwork/categories")
    assert body["count"] == 12 and body["categories"][0]["subcategories"][0]["services"]
    body = call("/upwork/suggest", query="python dev")
    assert body["suggestions"][0]["text"] and body["related_queries"]
    body = call("/upwork/suggest", query="web scra", type="services")
    assert body["suggestions"][0]["frequency"]


def test_validation():
    assert status("/upwork/jobs/search", query="x", job_type="weekly") == 400
    assert status("/upwork/jobs/search", query="x", client_location="Narnia") == 400
    assert status("/upwork/freelancers/details", freelancer="12345") == 400
    assert status("/upwork/services/search", delivery_days=3) == 400
