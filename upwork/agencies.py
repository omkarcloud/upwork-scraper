"""/upwork/agencies/* — agency profile (page state + locations), members,
Upwork work history and portfolio, all from the AgencyNuxt app's data."""
from upwork import fetch, nuxt, queries
from upwork import parsers as P

MEMBERS_PER_PAGE = 50
HISTORY_PAGE_SIZES = range(1, 51)


def _agency_page(agency):
    html = fetch.page(f"/agencies/{agency}/", label=f"agency {agency}")
    try:
        state = nuxt.decode_nuxt3(html)
    except nuxt.NuxtStateError as e:
        raise fetch.UpworkUpstreamError(f"agency page {agency}: {e}")
    if P.g(state, "error", "statusCode") == 404:
        raise fetch.UpworkNotFound(f"Upwork has no agency {agency}")
    return state


def org_id(agency):
    """The numeric organisation id of an agency given as id, cipher or vanity
    name (the page redirects to the canonical /agencies/<id>/)."""
    if agency.isdigit():
        return agency

    def resolve():
        state = _agency_page(agency)
        oid = P.g(state, "vuex", "agencyProfile", "agencyId") or P.g(state, "vuex", "agencyProfile", "agency", "id")
        if not oid:
            raise fetch.UpworkNotFound(f"Upwork has no agency {agency}")
        return str(oid)
    return fetch.memoized(("agency-id", agency), resolve)


def details(agency):
    state = _agency_page(agency)
    out = P.agency_profile(state)
    if out is None:
        raise fetch.UpworkNotFound(f"Upwork has no agency {agency}")
    data = fetch.graphql("agency", queries.AGENCY_LOCATIONS, {"orgId": out["id"]}, alias="gql-query-agencylocations",
                         label="agency locations")
    out["locations"] = [P.agency_location(l) for l in P.as_list(P.g(data, "agencyLocations", "locations"))]
    return out


def members(agency, page=1):
    oid = org_id(agency)
    data = fetch.graphql("agency", queries.AGENCY_MEMBERS, {
        "agencyId": oid, "agencyTeamId": oid, "limit": MEMBERS_PER_PAGE,
        "offset": str((page - 1) * MEMBERS_PER_PAGE) if page > 1 else ""}, alias="gql-query-agencystaffs",
        label="agency members")
    staffs = P.as_dict(P.g(data, "agencyStaffs"))
    total = P.g(staffs, "totalCount")
    rows = [P.agency_member(m) for m in P.as_list(staffs.get("staffs"))]
    if not rows and page == 1 and total is None:
        raise fetch.UpworkNotFound(f"Upwork has no agency {agency}")
    return {"agency_id": oid, "members": rows,
            "pagination": {"page": page, "items_per_page": MEMBERS_PER_PAGE, "total_count": total,
                           "total_pages": -(-int(total) // MEMBERS_PER_PAGE) if total else (1 if rows else 0)}}


def work_history(agency, status="closed", page=1, per_page=10):
    oid = org_id(agency)
    data = fetch.graphql("agency", queries.AGENCY_WORK_HISTORY, {
        "agencyId": oid, "publicOnly": True, "type": ["ACTIVE" if status == "active" else "CLOSED"],
        "offset": (page - 1) * per_page, "limit": per_page}, alias="gql-query-organization", label="agency work history")
    hist = P.as_dict(P.g(data, "organization", "agency", "upWorkHistory"))
    total = P.g(hist, "totalCount")
    return {"agency_id": oid, "status": status,
            "contracts": [P.agency_contract(c) for c in P.as_list(hist.get("workHistoryList"))],
            "pagination": {"page": page, "items_per_page": per_page, "total_count": total,
                           "total_pages": -(-int(total) // per_page) if total else 0}}


def portfolio(agency, page=1, per_page=10):
    oid = org_id(agency)
    data = fetch.graphql("agency", queries.AGENCY_PORTFOLIO, {
        "agencyId": oid, "publicOnly": True, "offset": (page - 1) * per_page, "limit": per_page, "categoryId": ""},
        alias="gql-query-organization", label="agency portfolio")
    projects = P.as_dict(P.g(data, "organization", "agency", "projects"))
    total = P.g(projects, "totalCount")
    return {"agency_id": oid,
            "projects": [P.agency_project(P.g(e, "node")) for e in P.as_list(projects.get("edges")) if P.g(e, "node")],
            "pagination": {"page": page, "items_per_page": per_page, "total_count": total,
                           "total_pages": -(-int(total) // per_page) if total else 0}}
