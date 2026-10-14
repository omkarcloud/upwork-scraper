"""/upwork/categories and /upwork/suggest — the taxonomy and the search
boxes' autocomplete, from the site's GraphQL."""
from upwork import fetch, queries
from upwork import parsers as P
from upwork import values as V


def categories():
    data = fetch.graphql("search", queries.CATEGORIES, {}, alias="gql-query-ontologycategories", label="categories")
    rows = [P.category(c) for c in P.as_list(P.g(data, "ontologyCategories"))]
    return {"count": len(rows), "categories": rows}


def suggest(query, kind="jobs", limit=10):
    """Autocomplete for the job / talent search box (kind jobs|talent) or the
    project catalog box (kind services), plus the related searches shown
    under the results."""
    if kind == "services":
        calls = [
            lambda: fetch.graphql("catalog", queries.CATALOG_SUGGESTIONS, {"input": {"queryText": query}},
                                  alias="gql-query-projectsuggestions", label="service suggestions"),
            lambda: fetch.graphql("catalog", queries.CATALOG_RELATED, {"query": query},
                                  alias="gql-query-catalogRelatedQueriesV1", label="service related queries"),
        ]
        sugg, related = fetch.run_parallel(calls)
        suggestions = [{"text": V.text(s.get("suggestion")), "frequency": V.to_int(s.get("frequency"))}
                       for s in P.as_list(P.g(sugg[1], "projectSuggestions", "suggestions"))
                       if sugg[0] == "ok" and isinstance(s, dict)][:limit]
        related_rows = P.as_list(P.g(related[1], "search", "catalogApp", "relatedQueriesV1", "relatedQueries")) if related[0] == "ok" else []
    else:
        calls = [
            lambda: fetch.graphql("search", queries.SUGGESTIONS,
                                  {"isUser": False, "request": {"personId": None, "query": query, "records": limit}},
                                  alias="autoSuggestions", label="suggestions"),
            lambda: fetch.graphql("search", queries.RELATED_QUERIES, {"request": {"query": query}},
                                  alias="relatedSuggestions", label="related queries"),
        ]
        sugg, related = fetch.run_parallel(calls)
        suggestions = [{"text": V.text(s.get("label")), "frequency": None}
                       for s in P.as_list(P.g(sugg[1], "allSuggestions", "suggestions"))
                       if sugg[0] == "ok" and isinstance(s, dict)][:limit]
        related_rows = P.as_list(P.g(related[1], "ufsRelatedQueries", "relatedQueries")) if related[0] == "ok" else []
    if sugg[0] != "ok" and related[0] != "ok":
        raise sugg[1]
    return {"query": query, "type": kind, "suggestions": suggestions,
            "related_queries": [V.text(r) for r in related_rows if isinstance(r, str)]}
