# 💼 Upwork Scraper

Upwork Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Upwork data for free.

## ✨ What Can I Get?

- 💼 **Search 106K+ open jobs** — 18 filters: budget, hourly rate, experience, client hires, location & time zone
- 📄 **Full job + client details** — proposals, interviews, client spend, hires, rating & location
- 👩‍💻 **1.8M+ freelancers & 35K+ agencies** — rates, Job Success, earnings, portfolios & work history with reviews
- 🛒 **1.5M+ catalog services** — packages, prices, delivery times, sellers & review breakdowns

## 🎥 Example: A Full Upwork Job

```json
{
  "id": "2110042793670717934",
  "title": "Lead AI Engineer (Data & Automation)",
  "link": "https://www.upwork.com/jobs/~022110042793670717934",
  "description": "Skyward is a SEO and AI-search agency that runs its client work on software it builds itself. As Lead AI Engineer you are our primary engineer...",
  "job_type": "hourly",
  "experience_level": "intermediate",
  "hourly_rate": { "min": 20, "max": 60, "currency": "USD" },
  "duration": { "label": "More than 6 months", "weeks": 52 },
  "workload": "More than 30 hrs/week",
  "skills": [
    { "id": "1031626716094119936", "name": "Artificial Intelligence", "relevance": "mandatory" },
    { "id": "996364628025274386", "name": "Python", "relevance": "mandatory" }
  ],
  "published_at": "2026-10-13T16:19:51Z",
  "activity": { "proposals": 273, "interviewing": 0, "invites_sent": 0, "hired": 0 },
  "client": {
    "is_payment_verified": true,
    "location": { "city": "Cold Spring Harbor", "country": "United States", "timezone": "America/New_York" },
    "member_since": "2020-08-06",
    "stats": {
      "total_spent": { "amount": 183239.52, "currency": "USD" },
      "total_hires": 74,
      "active_hires": 35,
      "hours_billed": 4138.7,
      "rating": 4.99
    }
  }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Upwork Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/upwork-scraper
cd upwork-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/jobs/search?query=ai%20agent"
```

```json
{
  "count": 1411,
  "per_page": 10,
  "current_page": 1,
  "total_pages": 100,
  "jobs": [
    {
      "id": "2110312991530475421",
      "title": "AI Developer Needed for AI-Powered Fintech Portal",
      "link": "https://www.upwork.com/jobs/~022110312991530475421",
      "job_type": "hourly",
      "experience_level": "expert",
      "hourly_rate": { "min": 25, "max": 50, "currency": "USD" },
      "duration": { "label": "3 to 6 months", "weeks": 18 },
      "workload": "full_time",
      "skills": [
        { "id": "1691099314245873665", "name": "AI Agent Development" },
        { "id": "996364628025274386", "name": "Python" }
      ],
      "published_at": "2026-10-14T10:13:49Z"
    }
  ]
}
```

All 16 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

16 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Search Jobs | `/jobs/search` | Open jobs with 18 filters, facet counts, 10-50 per page |
| Job Details | `/jobs/details` | Full posting, proposals, interviews and the client's spend, hires and rating |
| Jobs by Skill | `/jobs/by-skill` | The 30 newest jobs for any skill with its total open jobs |
| Freelancer Details | `/freelancers/details` | Rate, Job Success, earnings, skills, portfolio and recent reviews |
| Search Freelancers | `/freelancers/search` | 1.8M+ freelancers with 26 filters, up to 50 per page |
| Freelancer Work History | `/freelancers/work-history` | Every contract with hours, rates, charges and both-side feedback |
| Top Freelancers | `/freelancers/top` | Upwork's top talent for a skill, plus its hiring cost guide |
| Agency Details / Members | `/agencies/details`, `/agencies/members` | Rates, earnings, services, clients, offices and every team member |
| Agency Work History / Portfolio | `/agencies/work-history`, `/agencies/portfolio` | Contracts with feedback, and portfolio projects with images |
| Search Services | `/services/search` | 1.5M+ catalog services by price, delivery time and seller badge |
| Service Details | `/services/details` | Packages, prices, delivery times, add-ons and review breakdown |
| Services by Seller | `/services/by-seller` | Every catalog service one freelancer sells |
| Autocomplete | `/suggest` | Search-box suggestions and related searches |
| Job Categories | `/categories` | Every category, subcategory and service with its filter ID |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-upwork-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-upwork-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-upwork-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/jobs/search",
    params={"query": "ai agent", "job_type": "hourly", "experience_level": "expert", "client_location": "United States"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Upwork Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Upwork%20Scraper%20API.)

[![Ask Us by Email about Upwork Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Upwork%20Scraper%20API&body=I%20need%20help%20using%20the%20Upwork%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**Glassdoor Scraper**](https://github.com/omkarcloud/glassdoor-scraper) — Glassdoor jobs, company ratings, salaries & reviews
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/upwork-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/upwork-scraper)
