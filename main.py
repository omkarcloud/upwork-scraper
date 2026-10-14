"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does (before pagination links);
results are written to output/*.json.
"""
import json
import os

from upwork import freelancers, jobs, services

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # the newest open jobs, with Upwork's own filters
    save("jobs_ai_agent.json", jobs.search(query="ai agent", job_type=["hourly"], experience_level=["expert"]))

    # a full freelancer profile: rate, Job Success, earnings, portfolio, work history
    save("freelancer_sohaibilyas.json", freelancers.details("sohaibilyas"))

    # a Project Catalog service: packages, prices, delivery times and reviews
    save("service_logo_design.json", services.details("project-1395542645421912064"))
