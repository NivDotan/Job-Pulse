
import requests
from bs4 import BeautifulSoup
import re
import json

def test_comeet_company(company_name, identifier):
    base_url = f"https://www.comeet.com/jobs/{company_name}/{identifier.strip()}"
    print(f"\nTesting: {company_name} → {base_url}")

    try:
        response = requests.get(base_url)
        if response.status_code != 200:
            print(f"  ❌ Failed to fetch page (status code {response.status_code})")
            return

        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", string=re.compile("COMPANY_POSITIONS_DATA"))
        if not script:
            print("  ❌ COMPANY_POSITIONS_DATA not found")
            return

        match = re.search(r"COMPANY_POSITIONS_DATA\s*=\s*(\[.*?\]);", script.string, re.DOTALL)
        if not match:
            print("  ❌ COMPANY_POSITIONS_DATA pattern not matched")
            return

        json_str = match.group(1).replace("undefined", "null")
        jobs = json.loads(json_str)
        print(f"  ✅ Success: Found {len(jobs)} jobs")
        print("Jobs found:\n" + "-" * 40)
        jobslst = []
        for job in jobs:
            name = job.get("name", "N/A")
            url = job.get("url_comeet_hosted_page", "N/A")
            loc = job.get("location", {})
            city = loc.get("city", "Unknown") if loc else "Unknown"
            categories = job.get("custom_fields", {}).get("categories", [])

            #print(f"\nJob: {name}")
            #print(f"City: {city}")
            #print(f"URL: {url}")
            jobslst.append({
                        #'department': department,
                        'title': name,
                        'location': city,
                        'link': url
                    })
            #for category in categories:
            #    print(f"  - {category['name']}: {category['value']}")
        print(jobslst)
        return jobslst

    except Exception as e:
        print(f"  ❌ Error: {e}")