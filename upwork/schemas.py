"""Marshmallow request schemas for every /upwork/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Upwork resolvers (refs.py), the filter vocabularies and the
per-route schemas. Every schema's load() output is the kwargs dict its
endpoint function takes.

ONE param per input (tripadvisor QueryOrLinkField convention, never a
sibling `url`/`id` pair): `job` takes a job id or any upwork.com job link;
`freelancer` a profile cipher, vanity name or profile link; `agency` an
agency id, cipher or link; `service` a catalog id, slug or link; `skill` a
skill name or a /hire/ or /freelance-jobs/ link.
"""
from marshmallow import ValidationError, fields, validate

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, LanguageCodeField, PageField, PageSizeField,
                           PositiveInt, QueryField, RefField, StrippedString, NonNegativeNumber)
from upwork import agencies, freelancers, jobs, refdata, refs, services


class JobField(RefField):
    resolver = staticmethod(refs.resolve_job)


class FreelancerField(RefField):
    resolver = staticmethod(refs.resolve_freelancer)


class AgencyField(RefField):
    resolver = staticmethod(refs.resolve_agency)


class ServiceField(RefField):
    resolver = staticmethod(refs.resolve_service)


class SkillField(RefField):
    resolver = staticmethod(refs.resolve_skill)


def _max_length(n):
    """validate.Length(max=n) that tolerates the None StrippedString returns
    for an empty value (marshmallow runs validators on it; len(None) is a 500)."""
    def check(value):
        if value is not None and len(value) > n:
            raise ValidationError(f"Longer than maximum length {n}.")
    return check


class OptionalQuery(StrippedString):
    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", _max_length(200))
        super().__init__(**kwargs)


class LocationListField(fields.Field):
    """Comma-separated client / talent locations: countries, regions
    (Americas, Europe, …) or subregions (Southern Asia, …) by name, ISO code
    or slug -> [(name, type)]."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            found = refdata.location(raw)
            if not found:
                raise ValidationError(f"'{raw}' is not an Upwork location (a country, region or subregion name, e.g. "
                                      "United States, Europe, Southern Asia).")
            if found not in out:
                out.append(found)
        if len(out) > 20:
            raise ValidationError("At most 20 locations.")
        return out or None


class LocationNamesField(LocationListField):
    """Same input, returns the location names only (the jobs filter)."""

    def _deserialize(self, value, attr, data, **kwargs):
        found = super()._deserialize(value, attr, data, **kwargs)
        return [name for name, _ in found] if found else None


class TimezoneListField(fields.Field):
    """Comma-separated time zones (IANA name, UTC offset or label) -> zones
    (mode='zone') or offsets (mode='offset')."""

    def __init__(self, mode="zone", **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)
        self.mode = mode

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            found = refdata.timezone(raw)
            if not found:
                raise ValidationError(f"'{raw}' is not a time zone Upwork filters on (e.g. America/New_York or UTC-05:00).")
            token = found[0] if self.mode == "zone" else found[1]
            if token not in out:
                out.append(token)
        return out or None


class UsStateListField(fields.Field):
    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            code = refdata.us_state(raw)
            if not code:
                raise ValidationError(f"'{raw}' is not a US state (use CA or California).")
            if code not in out:
                out.append(code)
        return out or None


class CategoryListField(fields.Field):
    """Job categories (id or name) -> ids. Names may contain commas ("Web,
    Mobile & Software Dev"), so comma-separated input is matched greedily;
    `;` or `|` also separate values."""

    def __init__(self, sub=False, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)
        self.sub = sub

    def _lookup(self, raw):
        return refdata.subcategory(raw) if self.sub else refdata.category(raw)

    def _deserialize(self, value, attr, data, **kwargs):
        text = str(value or "")
        parts = [p.strip() for p in (text.replace("|", ";").split(";") if (";" in text or "|" in text) else [text])]
        out = []
        kind = "subcategory" if self.sub else "category"
        for part in parts:
            if not part:
                continue
            tokens = [t.strip() for t in part.split(",") if t.strip()]
            i = 0
            while i < len(tokens):
                found, step = None, 0
                for j in range(len(tokens), i, -1):
                    found = self._lookup(", ".join(tokens[i:j]))
                    if found:
                        step = j - i
                        break
                if not found:
                    raise ValidationError(f"'{tokens[i]}' is not an Upwork job {kind}; pass its id or name "
                                          "(see /upwork/categories).")
                if found["id"] not in out:
                    out.append(found["id"])
                i += step
        if len(out) > 12:
            raise ValidationError(f"At most 12 {kind} values.")
        return out or None


class IdListField(CommaListField):
    """Comma-separated numeric Upwork ids (skills: ontology_skill_uid)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_items", 20)
        super().__init__(upper=False, **kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        items = super()._deserialize(value, attr, data, **kwargs)
        for item in items or []:
            if not item.isdigit() or not 6 <= len(item) <= 30:
                raise ValidationError(f"'{item}' is not an Upwork id (digits, e.g. 996364628025274386).")
        return items


def _list_choice(allowed, **kwargs):
    kwargs.setdefault("max_items", len(allowed))
    return CommaListField(allowed=allowed, upper=False, **kwargs)


class HourlyRateField(NonNegativeNumber):
    """Hourly USD rate bound; 20.5 -> 20.5."""


# ---- jobs ----------------------------------------------------------------------------------------

class JobSearchSchema(BaseSchema):
    query = OptionalQuery()
    sort = ChoiceField(choices=list(jobs.SORTS), load_default="recency")
    page = PageField(max_page=jobs.MAX_PAGES)
    per_page = fields.Integer(load_default=10, strict=False, validate=validate.OneOf(jobs.PAGE_SIZES))
    job_type = _list_choice(list(jobs.JOB_TYPE_TOKENS))
    experience_level = _list_choice(list(jobs.EXPERIENCE_TOKENS))
    hourly_rate_min = HourlyRateField()
    hourly_rate_max = HourlyRateField()
    fixed_budget = _list_choice(list(jobs.FIXED_BUDGET_BUCKETS))
    duration = _list_choice(list(jobs.DURATION_TOKENS))
    workload = _list_choice(list(jobs.WORKLOAD_TOKENS))
    client_hires = _list_choice(list(jobs.CLIENT_HIRES_BUCKETS))
    client_location = LocationNamesField()
    client_timezone = TimezoneListField(mode="zone")
    contract_to_hire = Flag()
    skill_ids = IdListField()
    category = CategoryListField()
    subcategory = CategoryListField(sub=True)

    class Meta(BaseSchema.Meta):
        pass

    def _check(self, data):
        if data.get("hourly_rate_min") is not None and data.get("hourly_rate_max") is not None \
                and data["hourly_rate_max"] < data["hourly_rate_min"]:
            raise ValidationError("hourly_rate_max must be >= hourly_rate_min.", "hourly_rate_max")
        return data

    def load(self, *args, **kwargs):
        return self._check(super().load(*args, **kwargs))


class JobDetailsSchema(BaseSchema):
    job = JobField()


class SkillJobsSchema(BaseSchema):
    skill = SkillField()


# ---- freelancers -----------------------------------------------------------------------------------

class FreelancerSearchSchema(BaseSchema):
    query = OptionalQuery()
    name = OptionalQuery()
    page = PageField(max_page=1000)
    per_page = PageSizeField(default=10, max_size=50)
    hourly_rate_min = HourlyRateField()
    hourly_rate_max = HourlyRateField()
    job_success_min = fields.Integer(load_default=None, strict=False, validate=validate.Range(min=0, max=100))
    earned_min = NonNegativeNumber()
    hours_min = fields.Integer(load_default=None, strict=False, validate=validate.Range(min=0))
    recent_hours_only = Flag()
    talent_type = ChoiceField(choices=list(freelancers.TALENT_TYPES))
    english_level = ChoiceField(choices={"basic": 1, "conversational": 2, "fluent": 3, "native": 4})
    top_rated = Flag()
    top_rated_plus = Flag()
    rising_talent = Flag()
    expert_vetted = Flag()
    available_now = Flag()
    contract_to_hire = Flag()
    offers_consultations = Flag()
    languages = CommaListField(upper=False, max_items=10)
    skill_ids = IdListField()
    location = LocationListField()
    city = CommaListField(upper=False, max_items=10)
    us_state = UsStateListField()
    timezone = TimezoneListField(mode="offset")
    us_only = Flag()

    def load(self, *args, **kwargs):
        data = super().load(*args, **kwargs)
        if data.get("languages"):
            for code in data["languages"]:
                if not (len(code) in (2, 3) and code.isalpha()):
                    raise ValidationError(f"'{code}' is not an ISO 639 language code.", "languages")
            data["languages"] = [c.lower() for c in data["languages"]]
        if data.get("hourly_rate_min") is not None and data.get("hourly_rate_max") is not None \
                and data["hourly_rate_max"] < data["hourly_rate_min"]:
            raise ValidationError("hourly_rate_max must be >= hourly_rate_min.", "hourly_rate_max")
        if data["page"] * data["per_page"] > freelancers.MAX_RESULTS:
            raise ValidationError(f"Upwork serves at most {freelancers.MAX_RESULTS} talent results per search.", "page")
        return data


class FreelancerDetailsSchema(BaseSchema):
    freelancer = FreelancerField()


class WorkHistorySchema(BaseSchema):
    freelancer = FreelancerField()
    status = ChoiceField(choices=["completed", "in_progress"], load_default="completed")
    page = PageField(max_page=500)
    per_page = PageSizeField(default=10, max_size=freelancers.WORK_HISTORY_MAX)
    with_feedback_only = Flag()


class TopFreelancersSchema(BaseSchema):
    skill = SkillField()


# ---- agencies -----------------------------------------------------------------------------------------

class AgencyDetailsSchema(BaseSchema):
    agency = AgencyField()


class AgencyMembersSchema(BaseSchema):
    agency = AgencyField()
    page = PageField(max_page=100)


class AgencyWorkHistorySchema(BaseSchema):
    agency = AgencyField()
    status = ChoiceField(choices=["closed", "active"], load_default="closed")
    page = PageField(max_page=500)
    per_page = PageSizeField(default=10, max_size=50)


class AgencyPortfolioSchema(BaseSchema):
    agency = AgencyField()
    page = PageField(max_page=100)
    per_page = PageSizeField(default=10, max_size=50)


# ---- services -------------------------------------------------------------------------------------------

class ServiceSearchSchema(BaseSchema):
    query = OptionalQuery()
    page = PageField(max_page=services.MAX_PAGES)
    category = StrippedString(required=False, load_default=None)
    project_type = StrippedString(required=False, load_default=None)
    price_min = NonNegativeNumber()
    price_max = NonNegativeNumber()
    delivery_days = fields.Integer(load_default=None, strict=False, validate=validate.OneOf(services.DELIVERY_DAYS))
    location = LocationListField()
    rating_min = fields.Float(load_default=None, validate=validate.Range(min=0, max=5))
    top_rated = Flag()
    top_rated_plus = Flag()
    rising_talent = Flag()
    english_level = ChoiceField(choices={"basic": 1, "conversational": 2, "fluent": 3, "native": 4})
    with_facets = Flag()

    def load(self, *args, **kwargs):
        data = super().load(*args, **kwargs)
        for key, prefix in (("category", "projectCategory:"), ("project_type", "projectType:")):
            value = data.get(key)
            if value and not value.startswith(prefix):
                data[key] = prefix + value
        return data


class ServiceDetailsSchema(BaseSchema):
    service = ServiceField()


class SellerServicesSchema(BaseSchema):
    freelancer = FreelancerField()
    limit = fields.Integer(load_default=20, strict=False, validate=validate.Range(min=1, max=50))


# ---- metadata --------------------------------------------------------------------------------------------

class CategoriesSchema(BaseSchema):
    pass


class SuggestSchema(BaseSchema):
    query = QueryField(max_length=100)
    kind = ChoiceField(choices=["jobs", "talent", "services"], load_default="jobs", data_key="type")
    limit = fields.Integer(load_default=10, strict=False, validate=validate.Range(min=1, max=20))
