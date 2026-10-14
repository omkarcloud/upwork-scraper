"""/upwork/services/* — the project catalog: cursor-paged search (the site's
GraphQL, 24 a page), service details (the product page's Nuxt state) and a
seller's catalog."""
import threading
import time
from collections import OrderedDict

from upwork import fetch, freelancers, nuxt, queries, refs
from upwork import parsers as P

PER_PAGE = 24
MAX_PAGES = 50
DELIVERY_DAYS = (1, 7, 21)

# cursor chain memo: page N needs page N-1's nextCursorMark
_cursors = OrderedDict()
_cursors_lock = threading.Lock()
CURSOR_TTL = 1800
CURSOR_MAX = 512


def _request(query, category, project_type, price_min, price_max, delivery_days, location, rating_min,
             top_rated, top_rated_plus, rising_talent, english_level):
    """The VcsV4Request the catalog app builds from its URL params."""
    req = {"userQuery": query or None, "projectCategoryId": category, "projectTypeId": project_type,
           "serviceId": None, "projectSpecsSelect": None, "price": None, "regions": [], "subregions": [],
           "countries": []}
    if price_min is not None or price_max is not None:
        req["price"] = {"rangeStart": price_min, "rangeEnd": price_max}
    if delivery_days:
        req["maxDaysToFulfill"] = delivery_days
    if rating_min is not None:
        req["minAdjScore"] = rating_min
    if english_level:
        req["minEnglishProficiencyLevelRank"] = english_level
    for flag, key in ((top_rated, "topRated"), (top_rated_plus, "topRatedPlus"), (rising_talent, "risingTalent")):
        if flag:
            req[key] = True
    for name, kind in location or []:
        {"region": req["regions"], "subregion": req["subregions"], "country": req["countries"]}[kind].append(name)
    return {k: v for k, v in req.items() if v is not None}


def _page(req, page):
    key = (repr(sorted((k, repr(v)) for k, v in req.items())), page)
    now = time.monotonic()
    with _cursors_lock:
        hit = _cursors.get(key)
        if hit and now - hit[0] < CURSOR_TTL:
            _cursors.move_to_end(key)
            return hit[1]
    cursor = None
    if page > 1:
        prev = _page(req, page - 1)
        cursor = prev["next_cursor"]
        if not cursor:
            return {"result": {}, "next_cursor": None}
    paging = {"rows": PER_PAGE}
    if cursor:
        paging["cursorMark"] = cursor
    data = fetch.graphql("catalog", queries.CATALOG_SEARCH, {"request": {**req, "paging": paging}},
                         alias="gql-query-catalog-visitor-search", label="service search")
    result = P.as_dict(P.g(data, "search", "universalSearchNuxt", "visitorCatalogSearchV4"))
    value = {"result": result, "next_cursor": P.g(result, "paging", "nextCursorMark")}
    with _cursors_lock:
        _cursors[key] = (now, value)
        _cursors.move_to_end(key)
        while len(_cursors) > CURSOR_MAX:
            _cursors.popitem(last=False)
    return value


def search(query=None, page=1, category=None, project_type=None, price_min=None, price_max=None, delivery_days=None,
           location=None, rating_min=None, top_rated=None, top_rated_plus=None, rising_talent=None, english_level=None,
           with_facets=None):
    """One page (24) of the project catalog search."""
    req = _request(query, category, project_type, price_min, price_max, delivery_days, location, rating_min,
                   top_rated, top_rated_plus, rising_talent, english_level)
    chunk = _page(req, page)
    result = chunk["result"]
    rows = [P.service_tile(P.g(p, "projectTile")) for p in P.as_list(result.get("projects")) if P.g(p, "projectTile")]
    total = P.g(result, "paging", "total")
    if total is None and page > 1:
        total = P.g(_page(req, 1)["result"], "paging", "total")
    out = {"search": {"query": query, "category": category, "project_type": project_type}, "services": rows}
    if with_facets:
        data = fetch.graphql("catalog", queries.CATALOG_FACETS, {"VisitorV4FacetsRequest": {
            **{k: v for k, v in req.items() if k not in ("maxDaysToFulfill", "minAdjScore", "minEnglishProficiencyLevelRank",
                                                         "topRated", "topRatedPlus", "risingTalent")},
            "calculateProjectCategoryL4Facets": True,
            "calculateProjectSpecFacets": [], "calculateTalentDetailsFacets": True, "calculateDeliveryTimeFacets": True}},
            alias="catalogApp-visitor-search", label="service facets")
        out["facets"] = P.catalog_facets(P.g(data, "search", "universalSearchNuxt", "visitorCatalogSearchV4Facets"))
    out["pagination"] = {"page": page, "items_per_page": PER_PAGE, "total_count": total,
                         "total_pages": min(MAX_PAGES, -(-int(total) // PER_PAGE)) if total else (page if rows else 0)}
    return out


def details(service):
    html = fetch.page(f"/services/product/{service}", label=f"service {service}")
    try:
        state = nuxt.decode_nuxt2(html)
    except nuxt.NuxtStateError as e:
        raise fetch.UpworkUpstreamError(f"service page {service}: {e}")
    if P.g(state, "error", "statusCode") == 404:
        raise fetch.UpworkNotFound(f"Upwork has no catalog service {refs.service_id(service) or service}")
    out = P.service_details(state)
    if out is None:
        raise fetch.UpworkNotFound(f"Upwork has no catalog service {refs.service_id(service) or service}")
    seller_id = P.g(out, "seller", "id")
    if seller_id:
        data = fetch.graphql("catalog_details", queries.CATALOG_SIMILAR, {"visitorMoreLikeThisV2Request": {
            "projectUid": out["id"], "count": 8, "flowType": ["STANDARD"]}}, alias="gql-query-search", label="similar services")
        out["similar_services"] = [P.service_tile(P.g(p, "projectTile"))
                                   for p in P.as_list(P.g(data, "search", "catalogProjectDetailsNuxt", "visitorMoreLikeThisV2", "projects"))
                                   if P.g(p, "projectTile")]
    return out


def by_seller(freelancer, limit=20):
    """Every active catalog service of one freelancer."""
    pid = freelancers.person_id(freelancer)
    data = fetch.graphql("catalog_details", queries.CATALOG_SELLER_PROJECTS, {"request": {
        "providerPersonId": pid, "limit": limit, "orderByDimension": "CREATED_TS", "orderByDirection": "DESC"}},
        alias="gql-query-browsecatalogprojecttilesforactivefreelancers", label="seller services")
    rows = [P.service_tile(t) for t in P.as_list(P.g(data, "browseCatalogProjectTilesForActiveFreelancers", "projectTiles"))]
    return {"freelancer_id": pid, "count": len(rows), "services": rows}
