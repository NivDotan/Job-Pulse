"""
ATS-specific job scraper implementations.

Each function is a standalone adapter for one ATS platform.
JobScraper.scrapers() in CleanScript.py routes to these functions.
"""
import json
import logging
import os
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup


def scrape_greenhouse_jobs_api(company: str, driver=None) -> list[dict]:
    """Fetch job listings from Greenhouse API for a given company."""
    try:
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
        response = requests.get(api_url)
        response.raise_for_status()

        jobs_data = response.json().get("jobs", [])
        jobs = []

        for job in jobs_data:
            title = job.get("title", "Unknown")
            location = job.get("location", {}).get("name", "Unknown")
            link = job.get("absolute_url", "")

            jobs.append({
                "title": title,
                "location": location,
                "link": link
            })

        logging.info(f"Scraped {len(jobs)} jobs for {company}")
        return jobs

    except Exception as e:
        logging.error(f"Error occurred while scraping {company}: {e}")

        response = requests.get(f"https://boards.greenhouse.io{company}")
        soup = BeautifulSoup(response.text, "html.parser")

        jobs = []

        for job_div in soup.select("div.opening"):
            title_tag = job_div.find("a")
            if title_tag:
                job_title = title_tag.text.strip()
                job_url = title_tag.get("href")
                location = job_div.find("span", class_="location").text.strip() if job_div.find("span", class_="location") else "No location"
                jobs.append({
                    "title": job_title,
                    "location": location,
                    "url": job_url
                })

        logging.info(f"Scraped {len(jobs)} jobs for {company}")
        return jobs


def scrape_comeet_jobs(url: str) -> Optional[list[dict]]:
    """Scrape job listings from a Comeet careers page."""
    base_url = url

    try:
        response = requests.get(base_url)
        if response.status_code != 200:
            print(f"  Failed to fetch page (status code {response.status_code})")
            return

        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.find("script", string=re.compile("COMPANY_POSITIONS_DATA"))
        if not script:
            print("  COMPANY_POSITIONS_DATA not found")
            return

        match = re.search(r"COMPANY_POSITIONS_DATA\s*=\s*(\[.*?\]);", script.string, re.DOTALL)
        if not match:
            print("  COMPANY_POSITIONS_DATA pattern not matched")
            return

        json_str = match.group(1).replace("undefined", "null")
        jobs = json.loads(json_str)
        print(f"  Success: Found {len(jobs)} jobs")
        jobslst = []
        for job in jobs:
            name = job.get("name", "N/A")
            job_url = job.get("url_comeet_hosted_page", "N/A")
            loc = job.get("location", {})
            city = loc.get("city", "Unknown") if loc else "Unknown"

            jobslst.append({
                'title': name,
                'location': city,
                'link': job_url
            })

        return jobslst

    except Exception as e:
        print(f"  Error: {e}")


def fetch_lever_jobs_api(company: str, region: Optional[str] = None) -> list[dict]:
    """
    Fetch job listings from Lever API for a given company.
    Automatically tries US API first, then EU if US fails.
    Also tries different case variations of the company name.
    """
    company_variations = [company, company.lower()]
    if company != company.lower():
        company_variations.append(company.lower())

    if region == "eu":
        api_bases = ["https://api.eu.lever.co"]
    elif region == "us":
        api_bases = ["https://api.lever.co"]
    else:
        api_bases = ["https://api.lever.co", "https://api.eu.lever.co"]

    for base_url in api_bases:
        for company_name in company_variations:
            try:
                api_url = f"{base_url}/v0/postings/{company_name}"
                response = requests.get(api_url, timeout=15)

                if response.status_code == 404:
                    continue

                response.raise_for_status()
                jobs_data = response.json()

                if not jobs_data:
                    continue

                jobs = []
                for job in jobs_data:
                    title = job.get("text", "Unknown")

                    categories = job.get("categories", {})
                    if isinstance(categories, dict):
                        location = categories.get("location", "Unknown")
                    else:
                        location = "Unknown"

                    link = job.get("hostedUrl", "")

                    jobs.append({
                        "title": title,
                        "location": location,
                        "link": link
                    })

                region_name = "EU" if "eu.lever" in base_url else "US"
                logging.info(f"Fetched {len(jobs)} jobs for {company} from Lever ({region_name}, slug: {company_name})")
                return jobs

            except requests.exceptions.RequestException as e:
                logging.debug(f"Lever API attempt failed for {company_name} at {base_url}: {e}")
                continue
            except Exception as e:
                logging.debug(f"Error processing Lever response for {company_name}: {e}")
                continue

    logging.warning(f"Could not fetch jobs for {company} from Lever (tried US and EU APIs)")
    return []


def extraction_of_text_lever_eu(driver, xpath):
    """Extract text from Lever EU Selenium job listings."""
    try:
        from selenium.webdriver.common.by import By
        for element in driver.find_elements(By.XPATH, xpath):
            target_div = element.text.split("\n")
        return target_div
    except Exception as e:
        logging.error(f"An error occurred during text extraction: {e}")


def extraction_of_text_smartrecruiters(driver, xpath):
    """Extract text from SmartRecruiters Selenium job listings."""
    try:
        from selenium.webdriver.common.by import By
        for element in driver.find_elements(By.XPATH, xpath):
            target_div = element.text.split("\n")
        return target_div
    except Exception as e:
        logging.error(f"An error occurred during text extraction: {e}")


def scrape_bamboohr_jobs_api(company: str) -> list[dict]:
    """Fetch job listings from BambooHR API for a given company."""
    try:
        company_variations = [company, company.lower()]

        for company_name in company_variations:
            try:
                url = f"https://{company_name}.bamboohr.com/careers/list"
                response = requests.get(url, timeout=15)

                if response.status_code == 404:
                    continue

                response.raise_for_status()
                data = response.json()
                listings = []

                for job in data.get("result", []):
                    job_title = job.get("jobOpeningName", "N/A")
                    job_id = job.get("id")

                    location_data = job.get("location", {})
                    if isinstance(location_data, dict):
                        city = location_data.get("city", "N/A") or "N/A"
                    elif isinstance(location_data, str):
                        city = location_data
                    else:
                        city = "N/A"

                    job_link = f"https://{company_name}.bamboohr.com/careers/{job_id}"

                    listings.append({
                        "title": job_title,
                        "location": city,
                        "link": job_link
                    })

                if listings:
                    logging.info(f"Scraped {len(listings)} jobs for {company} from BambooHR")
                    return listings

            except requests.exceptions.RequestException:
                continue

        logging.warning(f"Could not fetch jobs for {company} from BambooHR")
        return []

    except Exception as e:
        logging.error(f"Error occurred while scraping {company} from BambooHR: {e}")
        return []


def scrape_ashby_jobs_api(company: str) -> list[dict]:
    """Fetch job listings from Ashby API for a given company."""
    try:
        api_url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        data = response.json()
        jobs = []

        for job in data.get("jobs", []):
            title = job.get("title", "Unknown")
            location = job.get("location", "Unknown")

            if isinstance(location, dict):
                location = location.get("name", "Unknown")

            job_id = job.get("id", "")
            link = f"https://jobs.ashbyhq.com/{company}/{job_id}"

            jobs.append({
                "title": title,
                "location": location,
                "link": link
            })

        logging.info(f"Scraped {len(jobs)} jobs from Ashby for {company}")
        return jobs

    except Exception as e:
        logging.error(f"Error scraping Ashby for {company}: {e}")
        return []


def _workday_country_aliases(country: str) -> set[str]:
    country_lower = country.lower()
    if country_lower == "united states":
        return {"united states", "united states of america", "usa", "u.s.a.", "u.s."}
    return {country_lower}


def _extract_workday_country_facet(data: dict, country_filter: tuple[str, ...]) -> tuple[Optional[str], list[str], list[str]]:
    aliases = {country: _workday_country_aliases(country) for country in country_filter}
    location_values = []

    # Prefer country-level facets when the tenant exposes them.
    for facet in data.get("facets", []):
        for group in facet.get("values", []):
            facet_parameter = group.get("facetParameter")
            if facet_parameter == "locations":
                location_values.extend(group.get("values", []))
                continue
            if facet_parameter not in {"locationHierarchy1", "locationCountry"}:
                continue

            facet_ids = []
            matched_countries = []
            for value in group.get("values", []):
                descriptor = value.get("descriptor", "").lower()
                for country, country_aliases in aliases.items():
                    if descriptor in country_aliases and value.get("id"):
                        facet_ids.append(value["id"])
                        matched_countries.append(country)

            if facet_ids:
                return facet_parameter, facet_ids, matched_countries

    # Some Workday tenants only expose site-level location facets.
    facet_ids = []
    matched_countries = set()
    for value in location_values:
        descriptor = value.get("descriptor", "").lower()
        for country, country_aliases in aliases.items():
            site_aliases = country_aliases - {"us"}
            if any(alias in descriptor for alias in site_aliases) and value.get("id"):
                facet_ids.append(value["id"])
                matched_countries.add(country)

    if facet_ids:
        return "locations", facet_ids, list(country_filter)

    return None, [], []


def scrape_workday_jobs_api(
    company: str,
    workday_instance: Optional[str] = None,
    country_filter: Optional[tuple[str, ...]] = ("Israel", "United States"),
    max_jobs: Optional[int] = None,
) -> list[dict]:
    """Fetch job listings from Workday for a given company."""
    from urllib.parse import urlparse
    try:
        if workday_instance:
            parsed = urlparse(workday_instance)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            # path is e.g. "/External" or "/Jobs" or "/Careers"; strip leading slash
            site = parsed.path.strip("/") or "careers"
        else:
            base_url = f"https://{company.lower()}.wd5.myworkdayjobs.com"
            site = "careers"

        api_url = f"{base_url}/wday/cxs/{company.lower()}/{site}/jobs"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        jobs = []
        page_size = 20
        offset = 0
        if max_jobs is None:
            max_jobs = int(os.environ.get("WORKDAY_MAX_JOBS", "500"))
        max_pages = max(1, (max_jobs + page_size - 1) // page_size) if max_jobs > 0 else 100
        applied_facets = {}
        matched_countries = []

        if country_filter:
            facet_payload = {
                "appliedFacets": {},
                "limit": page_size,
                "offset": 0,
                "searchText": ""
            }
            response = requests.post(api_url, json=facet_payload, headers=headers, timeout=20)
            response.raise_for_status()
            facet_parameter, facet_ids, matched_countries = _extract_workday_country_facet(response.json(), country_filter)

            if facet_parameter and facet_ids:
                applied_facets = {facet_parameter: facet_ids}
            else:
                logging.warning(
                    "Workday country filter %s did not match any facets for %s; scraping unfiltered",
                    country_filter,
                    company,
                )

        for _ in range(max_pages):
            payload = {
                "appliedFacets": applied_facets,
                "limit": page_size,
                "offset": offset,
                "searchText": ""
            }

            response = requests.post(api_url, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            postings = data.get("jobPostings", [])

            for job in postings:
                title = job.get("title", "Unknown")

                location = job.get("locationsText", "Unknown")
                if not location or location == "Unknown":
                    location = job.get("location", "Unknown")
                if matched_countries and re.fullmatch(r"\d+\s+Locations?", str(location)):
                    location = f"{', '.join(matched_countries)} ({location})"

                external_path = job.get("externalPath", "")
                link = f"{base_url}/{site}{external_path}" if external_path else ""

                jobs.append({
                    "title": title,
                    "location": location,
                    "link": link
                })

            offset += page_size
            total = data.get("total")
            if (
                not postings
                or len(postings) < page_size
                or (max_jobs > 0 and len(jobs) >= max_jobs)
                or (isinstance(total, int) and total > 0 and offset >= total)
            ):
                break

        if max_jobs > 0:
            jobs = jobs[:max_jobs]

        logging.info(f"Scraped {len(jobs)} jobs from Workday for {company}")
        return jobs

    except Exception as e:
        logging.error(f"Error scraping Workday for {company}: {e}")
        return []


def scrape_icims_jobs_api(company: str, portal_id: Optional[str] = None) -> list[dict]:
    """Fetch job listings from iCIMS for a given company."""
    try:
        if portal_id:
            api_url = f"https://careers-{company.lower()}.icims.com/jobs/search?ss=1&searchCompany={portal_id}&in_iframe=1"
        else:
            api_url = f"https://careers-{company.lower()}.icims.com/jobs/search?ss=1&in_iframe=1"

        headers = {
            "Accept": "application/json, text/html",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        jobs = []

        for job_div in soup.select(".iCIMS_JobsTable .iCIMS_JobListItem, .iCIMS_JobsContainer .job-item"):
            title_elem = job_div.find("a", class_="iCIMS_Anchor") or job_div.find("a")
            if title_elem:
                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")

                if link and not link.startswith("http"):
                    link = f"https://careers-{company.lower()}.icims.com{link}"

                location_elem = job_div.find(class_="iCIMS_JobLocation") or job_div.find("span", class_="location")
                location = location_elem.get_text(strip=True) if location_elem else "Unknown"

                jobs.append({
                    "title": title,
                    "location": location,
                    "link": link
                })

        logging.info(f"Scraped {len(jobs)} jobs from iCIMS for {company}")
        return jobs

    except Exception as e:
        logging.error(f"Error scraping iCIMS for {company}: {e}")
        return []


def scrape_jobvite_jobs_api(company: str) -> list[dict]:
    """Fetch job listings from Jobvite for a given company."""
    try:
        api_url = f"https://jobs.jobvite.com/careers/{company}/jobs"

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        try:
            data = response.json()
            jobs = []

            for job in data.get("requisitions", data.get("jobs", [])):
                title = job.get("title", "Unknown")
                location = job.get("location", job.get("city", "Unknown"))
                job_id = job.get("id", job.get("eId", ""))
                link = f"https://jobs.jobvite.com/{company}/job/{job_id}"

                jobs.append({
                    "title": title,
                    "location": location,
                    "link": link
                })

            logging.info(f"Scraped {len(jobs)} jobs from Jobvite for {company}")
            return jobs

        except Exception:
            soup = BeautifulSoup(response.text, "html.parser")
            jobs = []

            for job_elem in soup.select(".jv-job-list li, .job-listing"):
                title_elem = job_elem.find("a")
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    link = title_elem.get("href", "")

                    if link and not link.startswith("http"):
                        link = f"https://jobs.jobvite.com{link}"

                    location_elem = job_elem.find(class_="jv-job-list-location")
                    location = location_elem.get_text(strip=True) if location_elem else "Unknown"

                    jobs.append({
                        "title": title,
                        "location": location,
                        "link": link
                    })

            logging.info(f"Scraped {len(jobs)} jobs from Jobvite for {company}")
            return jobs

    except Exception as e:
        logging.error(f"Error scraping Jobvite for {company}: {e}")
        return []
