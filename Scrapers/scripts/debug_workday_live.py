import sys

from job_scrapers import scrape_workday_jobs_api


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


companies = [
    ("crowdstrike", "https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers"),
    ("nvidia", "https://nvidia.wd5.myworkdayjobs.com/nvidiaexternalcareersite"),
    ("intel", "https://intel.wd1.myworkdayjobs.com/external"),
    ("abbott", "https://abbott.wd5.myworkdayjobs.com/abbottcareers"),
    ("hpe", "https://hpe.wd5.myworkdayjobs.com/ACJobSite"),
]


for company, instance in companies:
    jobs = scrape_workday_jobs_api(company, workday_instance=instance, max_jobs=60)
    print(f"\n=== {company.upper()} - {len(jobs)} jobs ===")
    for j in jobs[:3]:
        print(f"  [{j['location']}] {j['title']}")
        print(f"  {j['link']}")
