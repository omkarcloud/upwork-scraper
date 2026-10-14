"""Cache TTL per /upwork/* endpoint (cache.py, keyed on the validated params —
marshmallow fills the defaults, so an omitted param and its default share a
row).

Job listings churn by the minute (Upwork posts ~10k jobs a day) and a job's
proposal counts move for days; profiles, agencies and catalog services change
slowly; the taxonomy and suggestion lists barely move."""
from datetime import timedelta

# --- jobs ---------------------------------------------------------------------------------
JOB_SEARCH_CACHE = timedelta(minutes=30)
JOB_CACHE = timedelta(hours=3)
SKILL_JOBS_CACHE = timedelta(hours=1)

# --- freelancers ------------------------------------------------------------------------------
FREELANCER_SEARCH_CACHE = timedelta(hours=12)
FREELANCER_CACHE = timedelta(days=1)
WORK_HISTORY_CACHE = timedelta(days=1)
TOP_FREELANCERS_CACHE = timedelta(days=3)

# --- agencies -----------------------------------------------------------------------------------
AGENCY_CACHE = timedelta(days=2)
AGENCY_MEMBERS_CACHE = timedelta(days=2)
AGENCY_WORK_HISTORY_CACHE = timedelta(days=1)
AGENCY_PORTFOLIO_CACHE = timedelta(days=3)

# --- services ------------------------------------------------------------------------------------
SERVICE_SEARCH_CACHE = timedelta(hours=12)
SERVICE_CACHE = timedelta(days=1)
SELLER_SERVICES_CACHE = timedelta(days=1)

# --- metadata ----------------------------------------------------------------------------------------
CATEGORIES_CACHE = timedelta(days=7)
SUGGEST_CACHE = timedelta(days=3)
