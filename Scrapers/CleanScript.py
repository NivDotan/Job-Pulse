import json
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import subprocess
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from datetime import datetime, timezone
import os
import sys
from telegramInsertBot import main as telegram_main
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from os.path import join, dirname
from job_scrapers import (
    scrape_greenhouse_jobs_api,
    scrape_comeet_jobs,
    fetch_lever_jobs_api,
    extraction_of_text_lever_eu,
    extraction_of_text_smartrecruiters,
    scrape_bamboohr_jobs_api,
    scrape_ashby_jobs_api,
    scrape_workday_jobs_api,
    scrape_icims_jobs_api,
    scrape_jobvite_jobs_api,
)
from schedule_manager import is_within_schedule

# Optional imports - guard for cloud/cron environments
try:
    from lama_chat import chat
except ImportError:
    chat = None
    print("Note: lama_chat not available (not needed in cron mode)")

# Load environment variables
dotenv_path = join(dirname(__file__), '.env')
load_dotenv(dotenv_path)

# Project paths - configurable via environment variables
# BASE_DIR defaults to the parent of the Scrapers directory (project root)
SCRAPERS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(SCRAPERS_DIR))
LOG_DIRECTORY = os.environ.get("LOG_DIRECTORY", os.path.join(SCRAPERS_DIR, "logs"))
COMPANY_DATA_JSON = os.environ.get("COMPANY_DATA_JSON", os.path.join(PROJECT_ROOT, "airflow_processes", "data", "combined_company_data3.json"))
ETL_TMP_DIR = os.environ.get("ETL_TMP_DIR", os.path.join(SCRAPERS_DIR, "tmp"))
ETL_TMP_UNCLEAN = os.path.join(ETL_TMP_DIR, "tmp_unclean.txt")
ETL_TMP_CLEAN = os.path.join(ETL_TMP_DIR, "tmp.txt")
DEDUP_JSON_PATH_UNCLEAN = os.environ.get(
    "DEDUP_JSON_PATH",
    os.path.join(PROJECT_ROOT, "deduplicated_links_for_bot_unclean.json")
)
DEDUP_JSON_PATH_CLEAN = os.path.join(
    os.path.dirname(DEDUP_JSON_PATH_UNCLEAN),
    "deduplicated_links_for_bot.json"
)
BASH_SCRIPT_PATH = os.environ.get("BASH_SCRIPT_PATH", "")
GIT_BASH_PATH = os.environ.get("GIT_BASH_PATH", "")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", 5050))
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", f"http://localhost:{DASHBOARD_PORT}")

# Run mode: "local" = infinite loop + dashboard,
# "cron"/"render"/others = single run (Render environments)
RUN_MODE = os.environ.get("RUN_MODE", "local")
IS_RENDER_ENV = RUN_MODE in ("cron", "render") or os.environ.get("RENDER", "").lower() == "true"

# Database operations for company data and log metadata
from db_operations import (
    get_all_companies,
    get_latest_log_run,
    parse_log_file_for_metadata,
    save_log_metadata,
    sync_companies_from_json,
    get_companies_with_failures,
    get_failure_summary
)

# Alerting system
try:
    from alerting import (
        send_high_error_rate_alert,
        send_company_failures_alert,
        send_scraper_crash_alert,
        alert_critical_error
    )
    ALERTING_ENABLED = True
except ImportError:
    ALERTING_ENABLED = False
    print("Warning: Alerting module not available")

# Log cleanup
try:
    from log_cleanup import schedule_cleanup, LogCleanupPolicy
    LOG_CLEANUP_ENABLED = True
except ImportError:
    LOG_CLEANUP_ENABLED = False
    print("Warning: Log cleanup module not available")


class json_file_class:
    def __init__(self, json_file_path):
        try:
            self.json_file_path = json_file_path
            self.data = self.read_json_file()
        except Exception as e:
            logging.error(f"An error occurred while reading the JSON file: {e}")

    def read_json_file(self):
        with open(self.json_file_path, 'r') as f:
            data = json.load(f)
        return data


class JobScraper:
    def __init__(self, data):
        self.data_from_json = data

    def scrapers(self, url, link_type, company_name=None):
        driver = None  # Initialize driver to None

        # API-based scrapers don't need Selenium - handle them first
        api_based_types = ["green", "lever", "bamboohr", "ashby", "workday", "icims", "jobvite", "comeet"]

        # Only initialize Selenium driver for scrapers that need it
        if link_type not in api_based_types:
            try:
                driver = None
            except Exception as e:
                logging.error(f"Failed to initialize Chrome driver: {e}")
                return [], []

        try:
            print(f"compayn: {company_name}")
            if link_type == "green":
                job_listings = scrape_greenhouse_jobs_api(company_name)
                return job_listings, []

            elif link_type == "smart":
                if driver is None:
                    logging.error(f"Cannot scrape SmartRecruiters for {company_name}: driver not initialized")
                    return [], []
                try:
                    driver.get(url)
                    driver.implicitly_wait(5)
                    xpaths = ['/html/body/div[1]/div/main/section/div']
                    for xpath in xpaths:
                        job_listing_list = extraction_of_text_smartrecruiters(driver, xpath)
                        if job_listing_list:
                            return job_listing_list, []
                finally:
                    if driver:
                        driver.quit()
                return [], []

            elif link_type == "lever":
                job_listing_list = fetch_lever_jobs_api(company_name)
                if job_listing_list:
                    return job_listing_list, []

                logging.warning(f"Lever API returned no jobs for {company_name}")
                return [], []

            elif link_type == "bamboohr":
                job_listings = scrape_bamboohr_jobs_api(company_name)
                return job_listings, []

            elif link_type == "comeet":
                print("test url before:", url)
                job_listing_list = scrape_comeet_jobs(url)
                print("extract: ", job_listing_list)
                return job_listing_list, []

            elif link_type == "ashby":
                job_listings = scrape_ashby_jobs_api(company_name)
                return job_listings, []

            elif link_type == "workday":
                job_listings = scrape_workday_jobs_api(company_name, workday_instance=url)
                return job_listings, []

            elif link_type == "icims":
                job_listings = scrape_icims_jobs_api(company_name)
                return job_listings, []

            elif link_type == "jobvite":
                job_listings = scrape_jobvite_jobs_api(company_name)
                return job_listings, []

            else:
                logging.warning(f"Unknown link_type: {link_type}")
                return [], []

        except Exception as e:
            logging.error(f"An error occurred while loading the page: {e}")
            return [], []  # Always return tuple, never None

    def remove_duplicates(self, file_path, output_path):
        seen = set()
        with open(file_path, "r", encoding="utf-8") as infile, open(output_path, "w", encoding="utf-8") as outfile:
            for line in infile:
                if line not in seen:
                    outfile.write(line)
                    seen.add(line)

    def SendEmail(self, description=None):
        your_email = os.environ.get("Email_adddress", "")
        your_password = os.environ.get("Email_password", "")
        recipient_email = your_email

        msg = MIMEMultipart()
        msg['From'] = your_email
        msg['To'] = recipient_email
        msg['Subject'] = "New Jobs Listing"

        body = "New job listings found:\n"
        tmpbody = ""
        for i in description:
            for j in i[1]:
                try:
                    body += f"Company: {i[0]}, Job Name: {j[0]}, City: {j[1]}, Link: {i[2]}\n"
                    tmpbody += f"Company: {i[0]}, Job Name: {j[0]}, City: {j[1]}, Link: {i[2]}\n"
                except Exception:
                    body += f"Company: {i[0]}, Job Name: {i[1]}, Link: {i[2]}\n"
                    tmpbody += f"Company: {i[0]}, Job Name: {i[1]}, Link: {i[2]}\n"

        msg.attach(MIMEText(body, 'plain'))
        os.makedirs(ETL_TMP_DIR, exist_ok=True)
        with open(ETL_TMP_UNCLEAN, "w", encoding="utf-8") as file:
            file.write(tmpbody)

        self.remove_duplicates(ETL_TMP_UNCLEAN, ETL_TMP_CLEAN)

        try:
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(your_email, your_password)
                server.sendmail(your_email, recipient_email, msg.as_string())
                print("Email sent successfully!")
        except Exception as e:
            logging.error(f"Failed to send email: {e}")

        try:
            self.run_bash_script()
        except Exception as e:
            logging.error(f"Failed to parse the data: {e}")

    def run_bash_script(self):
        if not BASH_SCRIPT_PATH or not GIT_BASH_PATH:
            print("Skipping bash script execution: BASH_SCRIPT_PATH or GIT_BASH_PATH not configured")
            return

        try:
            result = subprocess.run(
                [GIT_BASH_PATH, BASH_SCRIPT_PATH],
                check=True,
                text=True,
                capture_output=True,
                encoding="utf-8"
            )
            print("Script Output:", result.stdout)
        except subprocess.CalledProcessError as e:
            print("Error executing script:", e)
            print("Output:", e.output)

    def call_by_url(self, url):
        job_titles = self.scrapers(url)
        if job_titles:
            contains_student = any("student" in title.lower() for title in job_titles)
            if contains_student:
                self.SendEmail()

    def parse_job_listings_after_Lama(self, listings_text, company_name):
        pattern = r"\d+\.\s(.*?)\s-\s(.*?)\((.*?)\)"
        parsed_jobs = []
        matches = re.findall(pattern, listings_text)

        for match in matches:
            job_title, experience_level, years_of_experience = match
            parsed_jobs.append({
                "job_title": job_title.strip(),
                "experience_level": experience_level.strip(),
                "years_of_experience": years_of_experience.strip()
            })
        logging.info(f"Parsed using LAMA, {company_name} listing: {parsed_jobs}.")
        return parsed_jobs

    def remove_duplicates_json(self, file_path, output_path):
        with open(file_path, "r", encoding="utf-8") as infile:
            data = json.load(infile)

        for company in data:
            if isinstance(company, list) and len(company) > 1 and isinstance(company[1], list):
                unique_jobs = []
                seen_links = set()

                for job_entry in company[1]:
                    job_link = None

                    if isinstance(job_entry, list) and job_entry:
                        job_link = job_entry[-1]  # Last item is the job link
                    elif isinstance(job_entry, dict) and "link" in job_entry:
                        job_link = job_entry["link"]

                    if isinstance(job_link, str) and job_link not in seen_links:
                        seen_links.add(job_link)
                        unique_jobs.append(job_entry)

                company[1] = unique_jobs

        with open(output_path, "w", encoding="utf-8") as outfile:
            json.dump(data, outfile, indent=4)

    def process_job_data(self, job_data, words_to_search, diff_parsing_companies):
        """
        Process a single job_data entry.
        Now includes failure tracking for companies.
        """
        results = {"Job_Found_Companies": [], "Job_Found_By_Companies_And_Type": []}
        resultsWithLinks = {"Job_Found_Companies": [], "Job_Found_By_Companies_And_Type": []}

        # Import failure tracking functions
        try:
            from db_operations import record_company_success, record_company_failure
            failure_tracking_enabled = True
        except ImportError:
            failure_tracking_enabled = False

        try:
            company_name = job_data.get("Company")
            link_type = job_data.get("LinkType")

            # Validate company name - skip invalid entries
            if not company_name or not isinstance(company_name, str):
                logging.warning(f"Invalid company name: {company_name}")
                return results

            # Skip entries that look like URLs or paths (corrupted data)
            if company_name.startswith('/') or company_name.startswith('http') or '?' in company_name:
                logging.warning(f"Skipping invalid company entry (looks like URL): {company_name}")
                return results

            # Validate link_type - skip unsupported types
            valid_link_types = ['green', 'smart', 'lever', 'comeet', 'bamboohr', 'ashby', 'workday', 'icims', 'jobvite']
            if not link_type or link_type not in valid_link_types:
                logging.warning(f"Skipping company '{company_name}' with unsupported link_type: {link_type}")
                return results

            # Generate URL based on link type
            if link_type == 'green':
                url = f"https://boards.greenhouse.io/{company_name.lower()}"
            elif link_type == 'smart':
                url = f"https://www.smartrecruiters.com/{company_name.lower()}"
            elif link_type == 'lever':
                url = f"https://jobs.lever.co/{company_name.lower()}"
            elif link_type == 'comeet':
                UniqueIdentifier = job_data.get("Unique Identifier")
                url = f"https://www.comeet.com/jobs/{company_name.lower()}/{UniqueIdentifier}"
                import comeet_scraper
                job_titles = comeet_scraper.test_comeet_company(company_name.lower(), UniqueIdentifier)
                print("job_titles_comeet ", job_titles)
            elif link_type == 'bamboohr':
                url = f"https://{company_name.lower()}.bamboohr.com/careers/list"
            elif link_type == 'ashby':
                url = f"https://jobs.ashbyhq.com/{company_name.lower()}"
            elif link_type == 'workday':
                workday_instance = job_data.get("Workday Instance")
                url = workday_instance if workday_instance else f"https://{company_name.lower()}.wd5.myworkdayjobs.com"
            elif link_type == 'icims':
                url = f"https://careers-{company_name.lower()}.icims.com/jobs/search"
            elif link_type == 'jobvite':
                url = f"https://jobs.jobvite.com/careers/{company_name.lower()}/jobs"
            else:
                logging.error(f"Invalid LinkType: {link_type}")
                return results

            if link_type == "comeet":
                job_titles, links = job_titles, []
            elif link_type == "lever":
                job_titles, links = self.scrapers(url, link_type, company_name.lower())
            else:
                job_titles, links = self.scrapers(url, link_type, company_name)

            logging.info(f"Processing {company_name},{link_type}, job titles: {job_titles}, links: {links}")
            print(f"Processing {company_name},{link_type}, job titles: {job_titles}, links: {links}")
            if job_titles:
                matching_titles_with_place = []
                matching_titles_with_place_and_link = []
                logging.info(f"Starting job title processing for company: {company_name}")

                if company_name.lower() in diff_parsing_companies:
                    logging.info(f"Company '{company_name}' is in diff_parsing_companies.")
                    if chat is None:
                        logging.warning(f"Skipping Lama parsing for '{company_name}' - lama_chat not available (cron mode)")
                        response = ""
                    elif len(job_titles) > 150:
                        response = ""
                        logging.info(f"Splitting job_titles into chunks for Lama - Total titles: {len(job_titles)}")
                        for i in range(math.ceil(len(job_titles) / 150)):
                            chunk = job_titles[i * 150: (i + 1) * 150]
                            logging.info(f"Processing chunk {i+1}: {chunk}")
                            response += chat.chatWithLama(','.join(str(x) for x in chunk))
                    else:
                        logging.info(f"Sending all job_titles to Lama for parsing.")
                        response = chat.chatWithLama(','.join(str(x) for x in job_titles))

                    for i in self.parse_job_listings_after_Lama(response, company_name):
                        for word in words_to_search:
                            if (word in i["job_title"].lower() or word in i["experience_level"].lower()):
                                logging.info(f"Match found in Lama parsed results for '{word}' in company '{company_name}': {i}")
                                matching_titles_with_place.append([i["job_title"], "Tel Aviv"])
                else:
                    logging.info(f"Company '{company_name}' is NOT in diff_parsing_companies.")

                    api_based_types = ["green", "comeet", "lever", "bamboohr", "ashby", "workday", "icims", "jobvite"]

                    if link_type in api_based_types:
                        logging.info(f"Link type '{link_type}' uses API format (list of dicts)")
                        filtered_jobs = []
                        for job in job_titles:
                            if isinstance(job, dict):
                                job_title = job.get("title", "")
                                if job_title and any(word.lower() in job_title.lower() for word in words_to_search):
                                    filtered_jobs.append(job)
                            else:
                                if any(word.lower() in str(job).lower() for word in words_to_search):
                                    filtered_jobs.append({"title": str(job), "location": "Unknown", "link": ""})

                        logging.info(f"Filtered jobs found for company '{company_name}': {filtered_jobs}")
                        if filtered_jobs:
                            matching_titles_with_place_and_link.append(filtered_jobs)
                    else:
                        logging.info(f"Link type '{link_type}' uses Selenium format (list of strings)")
                        for i, title in enumerate(job_titles):
                            logging.info(f"Processing title {i}: {title}")

                            if isinstance(title, dict):
                                title_str = title.get("title", str(title))
                            else:
                                title_str = str(title)

                            for word in words_to_search:
                                if word in title_str.lower() and word != title_str.lower():
                                    logging.info(f"Partial match for word '{word}' in title '{title_str}' for company '{company_name}'")
                                    place = ""
                                    try:
                                        if i + 1 < len(job_titles) and job_titles[i + 1] != '':
                                            place = job_titles[i + 1]
                                        elif i + 2 < len(job_titles):
                                            place = job_titles[i + 2]
                                    except IndexError:
                                        place = "Unknown"
                                    logging.info(f"Place inferred: {place}")

                                elif word == title_str.lower() and i > 0 and job_titles[i - 1] != title_str:
                                    logging.info(f"Exact match for word '{word}' in title '{title_str}' for company '{company_name}'")
                                    try:
                                        if matching_titles_with_place and matching_titles_with_place[-1][0] != title_str:
                                            title_str = job_titles[i - 2] if i >= 2 else title_str
                                            place = job_titles[i - 1] if i >= 1 else "Unknown"
                                        matching_titles_with_place.append([title_str, place, ""])
                                    except Exception as e:
                                        logging.exception(f"Exception in exact match backtrack for company '{company_name}': {e}")
                                        title_str = job_titles[i - 2] if i >= 2 else title_str
                                        place = None
                                        matching_titles_with_place.append([title_str, place, ""])

                print("matching_titles_with_place_and_link3: ", matching_titles_with_place_and_link)
                if matching_titles_with_place_and_link:
                    resultsWithLinks["Job_Found_Companies"].append(company_name)
                    resultsWithLinks["Job_Found_By_Companies_And_Type"].append([company_name, matching_titles_with_place_and_link])

                # Record successful scrape
                if failure_tracking_enabled:
                    try:
                        jobs_count = len(job_titles) if job_titles else 0
                        record_company_success(company_name, link_type, jobs_count)
                    except Exception as track_err:
                        logging.debug(f"Could not track success for {company_name}: {track_err}")

        except Exception as e:
            logging.error(f"Error processing job_data {job_data}: {e}")

            # Record failure for tracking
            if failure_tracking_enabled:
                try:
                    company_name = job_data.get("Company", "Unknown")
                    link_type = job_data.get("LinkType", "Unknown")
                    failure_info = record_company_failure(company_name, link_type, str(e))

                    if failure_info.get("threshold_exceeded"):
                        logging.warning(f"Company {company_name} has exceeded failure threshold ({failure_info.get('consecutive_failures')} failures)")

                    if failure_info.get("auto_deactivated"):
                        logging.warning(f"Company {company_name} has been auto-deactivated after {failure_info.get('consecutive_failures')} consecutive failures")
                except Exception as track_err:
                    logging.debug(f"Could not track failure for {company_name}: {track_err}")

        return resultsWithLinks

    def main(self, words_to_search=None):
        diff_parsing_companies = []
        Job_Found_By_Companies_And_Type = []

        total_jobs = len(self.data_from_json)
        progress_counter = 0
        counter_lock = Lock()

        def process_and_track(job_data):
            nonlocal progress_counter
            with counter_lock:
                progress_counter += 1
                print(f"Processing {job_data}, [{progress_counter}/{total_jobs}].")
                logging.info(f"Processing {job_data}, [{progress_counter}/{total_jobs}].")
            return self.process_job_data(job_data, words_to_search, diff_parsing_companies)

        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_job = {
                executor.submit(process_and_track, job_data): job_data
                for job_data in self.data_from_json
            }

            for future in as_completed(future_to_job):
                result = future.result()
                Job_Found_By_Companies_And_Type.extend(result["Job_Found_By_Companies_And_Type"])

            print("Job_Found_By_Companies_And_Type: ", Job_Found_By_Companies_And_Type)
            with open(DEDUP_JSON_PATH_UNCLEAN, 'w', encoding='utf-8') as file:
                json.dump(Job_Found_By_Companies_And_Type, file, indent=4)
            print(f"Wrote dedup JSON to {DEDUP_JSON_PATH_UNCLEAN} ({len(Job_Found_By_Companies_And_Type)} companies)")

            self.remove_duplicates_json(DEDUP_JSON_PATH_UNCLEAN, DEDUP_JSON_PATH_CLEAN)
            telegram_main()


def run_scraper_once():
    """
    Run the scraper once: load companies, scrape, process, email, save metadata.
    Used by both local (loop) mode and cron (single-run) mode.
    """
    import traceback

    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"DEDUP_JSON_PATH_UNCLEAN: {DEDUP_JSON_PATH_UNCLEAN}")
    print(f"DEDUP_JSON_PATH_CLEAN: {DEDUP_JSON_PATH_CLEAN}")

    now = datetime.now()
    dt_string = now.strftime("%d_%m_%Y_%H")
    log_directory = LOG_DIRECTORY
    log_filename = f'{log_directory}/scraper_{dt_string}.log'

    if IS_RENDER_ENV:
        os.makedirs(log_directory, exist_ok=True)
        open(log_filename, 'a').close()
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s:%(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(log_filename)
            ],
            force=True
        )
    else:
        os.makedirs(log_directory, exist_ok=True)
        print(f"Log directory exists: {os.path.exists(log_directory)}")
        open(log_filename, 'a').close()
        print(f"Log file created: {log_filename}")
        logging.basicConfig(filename=log_filename, level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s', force=True)

    logging.info("Starting the scraping process")

    if IS_RENDER_ENV:
        try:
            company_data = get_all_companies()
            print(f"Loaded {len(company_data)} companies from database")
            logging.info(f"Loaded {len(company_data)} companies from database")
            if not company_data:
                logging.error("Database returned 0 companies. Cannot proceed on Render without DB data.")
                print("ERROR: No companies in database. Add companies via db_operations sync first.")
                return
        except Exception as e:
            logging.error(f"Failed to load companies from database: {e}")
            print(f"ERROR: Cannot load companies from DB: {e}")
            return
    else:
        try:
            sync_companies_from_json(COMPANY_DATA_JSON)
            company_data = get_all_companies()
            print(f"Loaded {len(company_data)} companies from database")
            logging.info(f"Loaded {len(company_data)} companies from database")

            if not company_data or len(company_data) == 0:
                print("Database returned 0 companies, falling back to JSON file")
                logging.warning("Database returned 0 companies, falling back to JSON file")
                json_data = json_file_class(COMPANY_DATA_JSON)
                company_data = json_data.data
                print(f"Loaded {len(company_data)} companies from JSON fallback")
                logging.info(f"Loaded {len(company_data)} companies from JSON fallback")
        except Exception as e:
            print(f"Failed to load from database, falling back to JSON: {e}")
            logging.warning(f"Failed to load from database, falling back to JSON: {e}")
            json_data = json_file_class(COMPANY_DATA_JSON)
            company_data = json_data.data

    scraper = JobScraper(company_data)
    words_to_search = [
        "student", "junior", "entry", "graduate", "intern", "software", "developer",
        "engineer", "analyst", "data", "devops", "programmer", "economics", "game",
        "cloud", "architect", "scientist", "designer", "artist", "writer", "success",
        "administrator", "technician", "consultant", "specialist", "associate",
        "coordinator", "assistant", "trainee", "researcher", "fullstack", "backend",
        "frontend", "mobile", "ios", "android", "web", "product", "security",
        "machine learning", "AI", "deep learning", "cyber", "blockchain", "automation",
        "QA", "tester", "support", "helpdesk", "database", "marketing", "SEO"
    ]

    try:
        scraper.main(words_to_search)
    except Exception as scraper_error:
        error_trace = traceback.format_exc()
        logging.critical(f"Scraper crashed: {scraper_error}")
        logging.critical(f"Stack trace: {error_trace}")

        if ALERTING_ENABLED:
            try:
                send_scraper_crash_alert(
                    error_message=str(scraper_error),
                    stack_trace=error_trace,
                    context={
                        "log_file": log_filename,
                        "companies_loaded": len(company_data),
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                )
            except Exception as alert_err:
                logging.error(f"Failed to send crash alert: {alert_err}")

    try:
        logging.info("Scraping process completed, saving log metadata to database")
        metrics = parse_log_file_for_metadata(log_filename)
        if save_log_metadata(metrics):
            print(f"Log metadata saved to database for: {os.path.basename(log_filename)}")
            logging.info(f"Log metadata saved to database successfully")
        else:
            print(f"Failed to save log metadata to database")
            logging.warning(f"Failed to save log metadata to database")

        if ALERTING_ENABLED:
            try:
                error_count = metrics.get("error_count", 0)
                total_companies = metrics.get("total_companies", 0)

                if total_companies > 0 and error_count / total_companies > 0.2:
                    error_messages = metrics.get("error_summary", [])
                    send_high_error_rate_alert(
                        total_companies=total_companies,
                        failed_companies=error_count,
                        error_messages=error_messages,
                        log_file=log_filename
                    )
                    logging.info("High error rate alert sent")

                failed_companies = get_companies_with_failures()
                if failed_companies:
                    send_company_failures_alert(failed_companies)
                    logging.info(f"Company failures alert sent for {len(failed_companies)} companies")

            except Exception as alert_err:
                logging.error(f"Error sending alerts: {alert_err}")

    except Exception as e:
        print(f"Error saving log metadata: {e}")
        logging.error(f"Error saving log metadata to database: {e}")

    if LOG_CLEANUP_ENABLED and RUN_MODE == "local":
        try:
            cleanup_policy = LogCleanupPolicy(
                retention_days=30,
                compress_after_days=7,
                min_logs_to_keep=10,
                enable_compression=True
            )
            cleanup_result = schedule_cleanup(log_directory, cleanup_policy)
            if cleanup_result:
                logging.info(f"Log cleanup completed: deleted {len(cleanup_result.get('deleted', []))} files, "
                             f"compressed {len(cleanup_result.get('compressed', []))} files")
        except Exception as cleanup_err:
            logging.error(f"Error during log cleanup: {cleanup_err}")

    # Run company discovery for whichever ATS is most overdue (one per cron tick).
    # State is tracked in the discovery_state table — no extra Render services needed.
    try:
        from company_discovery import run_discovery_if_due
        run_discovery_if_due(interval_hours=24)
    except Exception as discovery_err:
        logging.warning(f"Discovery check failed (non-fatal): {discovery_err}")

    logging.info("Scraper run finished.")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scrape complete.")


if __name__ == '__main__':
    import time

    if RUN_MODE == "cron":
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running in CRON mode (single run)")

        is_allowed, schedule_msg = is_within_schedule()
        if not is_allowed:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {schedule_msg} Exiting without running.")
            sys.exit(0)

        MIN_INTERVAL_MINUTES = int(os.environ.get("SCRAPER_MIN_INTERVAL_MINUTES", "110"))
        minutes_since_last_run = None
        try:
            latest_run = get_latest_log_run()
            if latest_run and latest_run.get("start_time"):
                last_run_iso = latest_run["start_time"].replace("Z", "+00:00")
                last_dt = datetime.fromisoformat(last_run_iso)
                if last_dt.tzinfo:
                    last_dt = last_dt.astimezone(timezone.utc).replace(tzinfo=None)
                minutes_since_last_run = (datetime.utcnow() - last_dt).total_seconds() / 60.0
        except Exception as e:
            print(f"Could not get last run from DB: {e}. Proceeding with scrape.")

        if minutes_since_last_run is not None and minutes_since_last_run < MIN_INTERVAL_MINUTES:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Last run was {minutes_since_last_run:.1f} min ago; need {MIN_INTERVAL_MINUTES} min. Skipping. Exiting.")
            sys.exit(0)

        run_scraper_once()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Cron job finished. Exiting.")
        sys.exit(0)

    else:
        import threading
        import webbrowser
        from pyngrok import ngrok

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from DashboardApp.app import app as dashboard_app
        PORT = DASHBOARD_PORT
        NGROK_DOMAIN = os.environ.get("NGROK_DOMAIN", "")

        SLEEP_INTERVAL = int(os.environ.get("SCRAPER_SLEEP_INTERVAL", 7200))

        def run_dashboard():
            dashboard_app.run(debug=False, host='0.0.0.0', port=PORT, use_reloader=False)

        dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
        dashboard_thread.start()
        print(f"Dashboard started at {DASHBOARD_URL}")

        if NGROK_DOMAIN:
            public_url = ngrok.connect(addr=PORT, proto="http", domain=NGROK_DOMAIN)
            print("Ngrok public URL:", public_url)

        time.sleep(1)
        webbrowser.open(DASHBOARD_URL)

        print(f"\n=== Schedule Configuration ===")
        print(f"Run mode: {RUN_MODE}")
        print(f"Start time: {os.environ.get('SCRAPER_START_HOUR', '08:00')}")
        print(f"End time: {os.environ.get('SCRAPER_END_HOUR', '22:30')}")
        print(f"Skip days: {os.environ.get('SCRAPER_SKIP_DAYS', '5')} (5=Saturday)")
        print(f"Sleep interval: {SLEEP_INTERVAL} seconds ({SLEEP_INTERVAL/3600:.1f} hours)")
        print(f"================================\n")

        while True:
            is_allowed, schedule_msg = is_within_schedule()

            if not is_allowed:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {schedule_msg}")
                print("Waiting 15 minutes before checking again...")
                time.sleep(15 * 60)
                continue

            run_scraper_once()

            logging.info(f"Sleeping for {SLEEP_INTERVAL/3600:.1f} hours...")
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Sleeping for {SLEEP_INTERVAL/3600:.1f} hours...")
            time.sleep(SLEEP_INTERVAL)
