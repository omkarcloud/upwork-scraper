"""The 16 Upwork endpoints. Every path is served with and without the
`/upwork` prefix, so code generated against the hosted API on RapidAPI
(paths like /jobs/search) runs unchanged against this server.

Params are validated by the marshmallow schemas in upwork/schemas.py: ONE
param per input — `job` an id or any upwork.com job link, `freelancer` a
profile id / vanity name / link, `agency` an id / cipher / link, `service` a
catalog id / slug / link, `skill` a name or a /hire/ or /freelance-jobs/ link.
"""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from upwork import agencies, freelancers, jobs, meta, services
from upwork import schemas


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so a UTF-8 "Zürich" would arrive as "ZÃ¼rich")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    host = request.headers.get("Host") or "localhost"
    scheme = request.urlparts.scheme or "http"
    return f"{scheme}://{host}{path}?{urlencode(query, doseq=True)}"


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def paginate(result, path, raw):
    """Lift the scraper's `pagination` block into the flat shape the hosted
    API returns: count / per_page / current_page / total_pages / next / previous."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _as_int(pagination.get("page")) or _as_int(raw.get("page")) or 1
    total_pages = max(_as_int(pagination.get("total_pages")), 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, raw, page + 1 if page < total_pages else None),
        "previous": _page_link(path, raw, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(path, schema_cls, impl, paginated=False):
    """Validate the query, run the scraper, map failures to HTTP:
    bad params -> 400, missing entity -> 404, blocked / upstream -> 502,
    anything else -> 500."""
    raw = query_dict()
    data, error = load_query(schema_cls, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"upwork rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"upwork blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"upwork {path} failed: {e}"}, 502)
    except Exception as e:
        return json_response({"error": f"upwork {path} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


ENDPOINTS = [
    ("/jobs/search", schemas.JobSearchSchema, jobs.search, True),
    ("/jobs/details", schemas.JobDetailsSchema, jobs.details, False),
    ("/jobs/by-skill", schemas.SkillJobsSchema, jobs.by_skill, False),
    ("/freelancers/details", schemas.FreelancerDetailsSchema, freelancers.details, False),
    ("/freelancers/search", schemas.FreelancerSearchSchema, freelancers.search, True),
    ("/freelancers/work-history", schemas.WorkHistorySchema, freelancers.work_history, True),
    ("/freelancers/top", schemas.TopFreelancersSchema, freelancers.top, False),
    ("/agencies/details", schemas.AgencyDetailsSchema, agencies.details, False),
    ("/agencies/members", schemas.AgencyMembersSchema, agencies.members, True),
    ("/agencies/work-history", schemas.AgencyWorkHistorySchema, agencies.work_history, True),
    ("/agencies/portfolio", schemas.AgencyPortfolioSchema, agencies.portfolio, True),
    ("/services/search", schemas.ServiceSearchSchema, services.search, True),
    ("/services/details", schemas.ServiceDetailsSchema, services.details, False),
    ("/services/by-seller", schemas.SellerServicesSchema, services.by_seller, False),
    ("/suggest", schemas.SuggestSchema, meta.suggest, False),
    ("/categories", schemas.CategoriesSchema, meta.categories, False),
]


def mount(path, schema_cls, impl, paginated):
    """Serve one endpoint at /path and /upwork/path."""
    def handler():
        return call(path, schema_cls, impl, paginated)
    handler.__name__ = "upwork_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/upwork" + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
