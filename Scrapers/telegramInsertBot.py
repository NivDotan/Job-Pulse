import asyncio
import re
import os
from typing import Any, Optional
from dotenv import load_dotenv
import json
import subprocess
from datetime import datetime, date
from zoneinfo import ZoneInfo
import supabase
from os.path import join, dirname
import pandas as pd
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
import html
import local_llm_function

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

load_dotenv()

# Project paths - configurable via environment variables
SCRAPERS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(SCRAPERS_DIR))
ETL_TMP_DIR = os.environ.get("ETL_TMP_DIR", os.path.join(SCRAPERS_DIR, "tmp"))
ETL_TMP_CLEAN = os.path.join(ETL_TMP_DIR, "tmp.txt")
DEDUP_JSON_PATH = os.environ.get("DEDUP_JSON_PATH", os.path.join(PROJECT_ROOT, "deduplicated_links_for_bot_unclean.json"))
BASH_SCRIPT_PATH = os.environ.get("BASH_SCRIPT_PATH", "")
GIT_BASH_PATH = os.environ.get("GIT_BASH_PATH", "")

# Initialize the event loop for async (Windows compatibility)
if asyncio.get_event_loop_policy().__class__.__name__ == 'WindowsProactorEventLoopPolicy':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def is_location_in_israel(location: str) -> bool:
    # List of major cities in Israel
    israel_cities = [
        'Jerusalem', 'Modi‘in','Modiin', 'Jaffa', 'Tel Aviv', 'Tel-Aviv', 'Rishon LeTsiyyon', 'Reẖovot','Rehovot',"rechovot","Migdal HaEmek","Migdal-HaEmek"
        'Ramat Gan', 'Petah Tiqva', 'Netanya', 'Kfar Saba', 'Holon', 'Herzliya', 'Haifa','petah tikva','Center','Yokneam','Or Yehuda','Or-Yehuda','Glil Yam',
        'Hadera', 'Bnei Brak', 'Beersheba','Beer sheba', 'Bat Yam', 'Ashdod','TLV',"tlv", 'Giv‘atayim','Givatayim', 'hod hasharon',"Ra'anana","Raanana","Hod Ha'Sharon"
    ]

    # Convert everything to lowercase
    location = location.lower()
    cities_lower = [city.lower() for city in israel_cities]

    problem_locations = ["chicago" , "philippines" , "nashville","philadelphia" ,"Vilnius", "Atlanta", "Wrocław","Marseille"]

    if location in problem_locations:
        #print(f"City: {location}")
        return False
    # Check if 'il', 'israel' is in the location string
    if any(keyword in location for keyword in ['il', 'israel']):
        #print(f"City: {location}")
        return True
    
    for city in cities_lower:
        if city in location:
            #print(f"City: {city}, Location: {location}")
            return True
    return False


def is_location_in_israel_or_usa(location: str) -> bool:
    if is_location_in_israel(location):
        return True

    location = location.lower()
    usa_keywords = [
        "united states", "usa", "u.s.a", "u.s.", "us,",
        "california", "new york", "texas", "washington", "oregon",
        "massachusetts", "illinois", "georgia", "florida", "colorado",
        "arizona", "virginia", "north carolina", "pennsylvania",
        "sunnyvale", "santa clara", "san jose", "san francisco",
        "new york", "seattle", "austin", "boston", "chicago", "atlanta",
    ]

    return any(keyword in location for keyword in usa_keywords)
#Samsung

def run_bash_script():
    # Define the path to your Bash script (configurable via env vars)
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


async def process_jobs2(data):
    os.makedirs(ETL_TMP_DIR, exist_ok=True)
    file_path = ETL_TMP_CLEAN
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Error deleting file: {e}")

    problem_companies = {
        "abra_rnd", "QualityScore", "ZIM", "gk8", "gk8bygalaxy",
        "wiliot", "etoro", "fire-arc", "tango", "automatit","overwolf"
    }

    for company_data in data:
        if len(company_data) != 2:
            print(f"Skipping invalid company data: {company_data}")
            continue  # Skip invalid structure

        company_name, jobs = company_data
        if not isinstance(jobs, list):
            print(f"Skipping non-list jobs for company: {company_name}")
            continue

        if isinstance(company_name, str) and company_name.startswith("/embed/job_board?for="):
            company_name = company_name.split("=")[-1].capitalize()

        for job_entry in jobs:
            
            # Case 1: job_entry is a dict
            if isinstance(job_entry, dict):
                title = job_entry.get("title")
                location = job_entry.get("location")
                link = job_entry.get("link") or job_entry.get("url")

                job_with_company = [title, company_name, location, link]

                try:
                    if isinstance(location, str) and is_location_in_israel_or_usa(location):
                        tmpbody = f"Company: {company_name}, Job Name: {title}, City: {location}, Link: {link}\n"
                        with open(file_path, "a", encoding="utf-8") as file:
                            file.write(tmpbody)
                except Exception as e:
                    print(f"Error occurred: {e}")

            # Case 2: job_entry is a list
            elif isinstance(job_entry, list):
                # Case 2a: job_entry is a list of dicts (multiple jobs)
                if job_entry and all(isinstance(j, dict) for j in job_entry):
                    for job_dict in job_entry:
                        title = job_dict.get("title")
                        location = job_dict.get("location")
                        link = job_dict.get("link") or job_dict.get("url")

                        job_with_company = [title, company_name, location, link]

                        if company_name == "overwolf":
                            location="Tel-Aviv"



                        try:
                            if isinstance(location, str) and is_location_in_israel_or_usa(location):
                                tmpbody = f"Company: {company_name}, Job Name: {title}, City: {location}, Link: {link}\n"
                                with open(file_path, "a", encoding="utf-8") as file:
                                    file.write(tmpbody)

                                    
                        except Exception as e:
                            print(f"Error occurred: {e}")

                

                # Case 2b: job_entry is a simple job list [title, location, link]
                elif len(job_entry) >= 3:
                    # Fix location for problem companies
                    if company_name in problem_companies:
                        job_entry[1] = "Israel"

                    title, location, link = job_entry[0], job_entry[1], job_entry[2]
                    job_with_company = [title, company_name, location, link]

                    try:
                        if isinstance(location, str) and is_location_in_israel_or_usa(location):
                            tmpbody = f"Company: {company_name}, Job Name: {title}, City: {location}, Link: {link}\n"
                            with open(file_path, "a", encoding="utf-8") as file:
                                file.write(tmpbody)
                    except Exception as e:
                        print(f"Error occurred: {e}")
                    

                else:
                    print(f"Skipping invalid job entry list: {job_entry}, {company_name}")
                    continue

            else:
                print(f"Skipping invalid job entry: {job_entry}")
                continue
    try:
        run_bash_script()
        
    except Exception as e:
        print(f"Failed to parse the data: {e}")


# ============== Supabase Email History Functions ==============
# Table: emailed_jobs_history
# Columns: id, title, company, city, link, sent_at, is_filtered, email_date

def get_supabase_connection() -> Any:
    """Get Supabase connection for email history."""
    dotenv_path = join(dirname(__file__), '.env')
    load_dotenv(dotenv_path)
    supabase_url = os.environ.get("supabaseUrl")
    supabase_key = os.environ.get("supabaseKey")
    return supabase.create_client(supabase_url, supabase_key)

def get_sent_links_today() -> set[str]:
    """Get all links that were already sent today from Supabase."""
    today = date.today().isoformat()
    try:
        conn = get_supabase_connection()
        response = conn.table("emailed_jobs_history").select("link").eq("email_date", today).execute()
        sent_links = [row["link"] for row in response.data] if response.data else []
        return set(sent_links)
    except Exception as e:
        print(f"Error fetching sent links from Supabase: {e}")
        return set()

def save_emailed_jobs_to_supabase(jobs_list: list[dict]) -> Optional[Any]:
    """Save emailed jobs to Supabase. Each job should be a dict with title, company, city, link, is_filtered."""
    if not jobs_list:
        return
    
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        conn = get_supabase_connection()
        
        # Prepare records for insertion
        records = []
        for job in jobs_list:
            records.append({
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "city": job.get("city", ""),
                "link": job.get("link", ""),
                "sent_at": now,
                "is_filtered": job.get("is_filtered", True),
                "email_date": today
            })
        
        # Insert all records
        response = conn.table("emailed_jobs_history").insert(records).execute()
        print(f"Successfully saved {len(records)} jobs to Supabase emailed_jobs_history")
        return response
    except Exception as e:
        print(f"Error saving emailed jobs to Supabase: {e}")
        return None

# ── US jobs (non-Israel) ────────────────────────────────────────────────────

def is_us_digest_time() -> bool:
    """True when Israel clock is 20:00–23:59 — the daily US-jobs digest window."""
    return datetime.now(ISRAEL_TZ).hour >= 20


def save_us_jobs_to_supabase(jobs: list[dict]) -> None:
    """Upsert non-Israeli jobs into us_jobs_history (one row per link per day)."""
    if not jobs:
        return
    today = date.today().isoformat()
    records = [
        {"title": j["title"], "company": j["company"], "city": j["city"],
         "link": j["link"], "email_date": today}
        for j in jobs
    ]
    try:
        conn = get_supabase_connection()
        conn.table("us_jobs_history").upsert(records, on_conflict="link,email_date").execute()
        print(f"Saved {len(records)} US jobs to us_jobs_history")
    except Exception as e:
        print(f"Error saving US jobs to Supabase: {e}")


def send_us_jobs_digest() -> None:
    """Fetch today's unemailes US jobs and send a nightly digest email."""
    today = date.today().isoformat()
    try:
        conn = get_supabase_connection()
        resp = (
            conn.table("us_jobs_history")
            .select("*")
            .eq("email_date", today)
            .is_("emailed_at", "null")
            .execute()
        )
        jobs = resp.data or []
    except Exception as e:
        print(f"Error fetching US jobs for digest: {e}")
        return

    if not jobs:
        print("US digest: no new jobs to send today")
        return

    your_email = os.environ.get("Email_adddress", "")
    your_password = os.environ.get("Email_password", "")
    recipient_emails_str = os.environ.get("RECIPIENT_EMAILS", your_email)
    recipient_emails = [e.strip() for e in recipient_emails_str.split(",") if e.strip()]

    rows = "".join(
        f"<tr><td>{j['company']}</td><td>{j['title']}</td><td>{j['city']}</td>"
        f"<td><a href='{j['link']}'>View</a></td></tr>"
        for j in jobs
    )
    body = f"""
    <html><head><style>
      table{{border-collapse:collapse;width:100%;font-family:Arial,sans-serif}}
      th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
      th{{background:#f2f2f2}}
    </style></head><body>
    <h2>US Job Listings — {today}</h2>
    <p>{len(jobs)} new positions found today outside Israel.</p>
    <table>
      <tr><th>Company</th><th>Job Title</th><th>City</th><th>Link</th></tr>
      {rows}
    </table>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = your_email
    msg["To"] = ", ".join(recipient_emails)
    msg["Subject"] = f"US Jobs Digest — {today} ({len(jobs)} listings)"
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(your_email, your_password)
            server.sendmail(your_email, recipient_emails, msg.as_string())
        print(f"US digest sent: {len(jobs)} jobs")

        now = datetime.now().isoformat()
        conn = get_supabase_connection()
        for j in jobs:
            conn.table("us_jobs_history").update({"emailed_at": now}).eq("id", j["id"]).execute()
    except Exception as e:
        print(f"Failed to send US digest: {e}")


def filter_new_jobs(job_listings: list, sent_links: set[str]) -> list:
    """Filter out jobs that have already been sent (based on link)."""
    new_jobs = []
    for job in job_listings:
        title, company, city, link = job
        if link not in sent_links:
            new_jobs.append(job)
    return new_jobs

def SendEmail(job_listings, data_to_email, df_existing_Tal_filter_today, data_to_email_not_for_students):
    your_email = os.environ.get("Email_adddress", "")
    your_password = os.environ.get("Email_password", "")
    recipient_emails_str = os.environ.get("RECIPIENT_EMAILS", your_email)
    recipient_emails = [e.strip() for e in recipient_emails_str.split(",") if e.strip()]

    # Get sent links from Supabase (for today only)
    sent_links = get_sent_links_today()
    
    # Filter out jobs that have already been sent today
    original_count = len(job_listings)
    job_listings = filter_new_jobs(job_listings, sent_links)
    filtered_count = original_count - len(job_listings)
    
    if filtered_count > 0:
        print(f"Filtered out {filtered_count} jobs that were already sent today")

    print("email: ", job_listings, "data_to_email_not_for_students:", data_to_email_not_for_students)

    msg = MIMEMultipart("alternative")
    msg['From'] = your_email
    msg['To'] = ", ".join(recipient_emails)
    msg['Subject'] = "משרות חדשות"

    # Create HTML table header
    html = """
    <html>
    <head>
        <style>
            table {
                border-collapse: collapse;
                width: 100%;
                font-family: Arial, sans-serif;
            }
            th, td {
                border: 1px solid #dddddd;
                text-align: left;
                padding: 8px;
            }
            th {
                background-color: #f2f2f2;
            }
            a {
                color: #1a73e8;
                text-decoration: none;
            }
        </style>
    </head>
    <body>
        <p>Here are the new job listings:</p>
        <table>
            <tr>
                <th>Company</th>
                <th>Job Title</th>
                <th>City</th>
                <th>Link</th>
            </tr>
    """
    words_to_search = ["intern", "student","junior","entry","graduate","new grad","undergraduate"]
    have_listing = False
    new_links_to_save = []
    new_filtered_jobs = []      # Jobs matching student/intern criteria
    new_unfiltered_jobs = []    # Jobs that don't match filters
    
    # Calculate the index where unfiltered jobs start
    unfiltered_start_index = len(job_listings) - len(df_existing_Tal_filter_today) - len(data_to_email_not_for_students)
    
    # Add each job row
    for i, job in enumerate(job_listings):
        title, company, city, link = job
        #company = job['company']
        #title = job['job_name']
        #city = job['city_y']
        #link = job['link']
        #if any(word in title.lower() for word in words_to_search):
        
        # Track whether this is a filtered or unfiltered job
        is_unfiltered = i >= unfiltered_start_index
        
        if i == unfiltered_start_index:
            html += """
                <tr class="section-title">
                    <td colspan="4">Unfiltered job listings – may not be suitable</td>
                </tr>
            """

        have_listing = True
        new_links_to_save.append(link)
        
        # Create job object for saving
        job_obj = {
            "title": title,
            "company": company,
            "city": city,
            "link": link,
            "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_filtered": not is_unfiltered
        }
        
        if is_unfiltered:
            new_unfiltered_jobs.append(job_obj)
        else:
            new_filtered_jobs.append(job_obj)
        
        html += f"""
            <tr>
                <td>{company}</td>
                <td>{title}</td>
                <td>{city}</td>
                <td><a href="{link}">View</a></td>
            </tr>
        """

    # Close the HTML
    html += """
        </table>
    </body>
    </html>
    """

    # Attach the HTML content
    msg.attach(MIMEText(html, 'html'))

    # Send the email
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            if have_listing:
                server.starttls()
                server.login(your_email, your_password)
                server.sendmail(your_email, recipient_emails, msg.as_string())
                print("Email sent successfully!")
                
                # Save the newly sent jobs to Supabase after successful send
                all_jobs_to_save = new_filtered_jobs + new_unfiltered_jobs
                save_emailed_jobs_to_supabase(all_jobs_to_save)
                print(f"Saved {len(all_jobs_to_save)} jobs to Supabase")
                print(f"  - Filtered jobs: {len(new_filtered_jobs)}")
                print(f"  - Unfiltered jobs: {len(new_unfiltered_jobs)}")
            else:
                print("Not found jobs this time")
    except Exception as e:
        print(f"Failed to send email: {e}")


#SendEmail([['QA Engineer (Entry Level)', 'DealHub', 'Holon', 'https://www.comeet.com/jobs/dealhub/86.005/qa-engineer-entry-level/D2.A5F']])
def validate_string(text):
    markdown_v2_special_chars = r"_*[]()~`>#+-=|{}.!"
    if not isinstance(text, str):  # Ensure the input is a string
        return ""
    return re.sub(f"([{re.escape(markdown_v2_special_chars)}])", r"\\\1", text)

def clean_location(location):
    # If "TIME" is in the location, extract the part after "TIME"
    if "TIME" in location:
        return location.split("TIME")[-1].strip()
    return location.strip()

def parse_job_string2(job_string):
    # Split the string into company sections using "Company:" as a delimiter
    companies_raw = job_string.split("Company:")
    
    # Initialize a list to store structured data
    data = []
    
    # Iterate through each company section (skip the first empty part before the first 'Company:')
    for company_section in companies_raw[1:]:
        # Extract company name (first part of the section, until the first ',')
        company_name = company_section.split(',')[0].strip()
        
        # Extract the job name (text after 'Job Name:' and before the next ',')
        job_name_match = re.search(r"Job Name: (.*?)(?:,|$)", company_section)
        job_name = job_name_match.group(1).strip() if job_name_match else None
        
        # Extract the city (text after 'City:' and before the next ',')
        city_match = re.search(r"City: (.*?)(?:,|$)", company_section)
        city = clean_location(city_match.group(1).strip()) if city_match else None
        
        # Extract the link (appears after 'Link:')
        link_match = re.search(r"Link: (https://\S+)", company_section)
        job_link = link_match.group(1) if link_match else None
        
        # Append the structured data for this company
        data.append({
            'company': company_name,
            'job_name': job_name,
            'city': city,
            'link': job_link
        })

    print(f"Parsed job data: {data}")
    return data


def get_new_data_df(job_string):
    parsed_data = parse_job_string2(job_string)
    df_new = pd.DataFrame(parsed_data)
    print("New data DataFrame:\n", df_new)
    return df_new

def get_existing_data_df(table="scrapers_data"):
    dotenv_path = join(dirname(__file__), '.env')
    load_dotenv(dotenv_path)
    supabase_url = os.environ.get("supabaseUrl")
    supabase_key = os.environ.get("supabaseKey")

    conn = supabase.create_client(supabase_url, supabase_key)
    
    response = conn.table(table).select("*").execute()
    existing_data = response.data if response.data else []
    
    df_existing = pd.DataFrame(existing_data)
    print("Existing data DataFrame:\n", df_existing)
    return df_existing




def filter_today(df: pd.DataFrame) -> pd.DataFrame:
    df['post_date'] = pd.to_datetime(df['post_date']).dt.date
    today = date.today()
    return df[df['post_date'] == today]


def get_data_from_comeet(url):
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"  ❌ Failed to fetch page (status code {response.status_code})")
            return
        
        soup = BeautifulSoup(response.text, "html.parser")
        page_text = response.text
        job_data = None

        # -----------------------------
        # 1. Try to find JSON-LD (Your new script's logic, with the parsing fix)
        # -----------------------------
        json_script = soup.find("script", {"type": "application/ld+json"})
        if json_script and json_script.string:
            try:
                print("ℹ️ Trying JSON-LD method...")
                cleaned = json_script.string.replace('\n', '').replace('\r', '').strip()
                
                # Find the *last* closing brace
                last_brace = cleaned.rfind("}")
                if last_brace != -1:
                    # **FIX**: Slice to *include* the last brace (your script sliced to exclude it)
                    cleaned = cleaned[: last_brace + 1]
                
                job_data = json.loads(cleaned)
                print("✅ Found data via JSON-LD.")
            except Exception as e:
                print(f"⚠️ JSON-LD parse error: {e}. Trying fallback.")

        # -----------------------------
        # 2. FALLBACK: extract from POSITION_DATA (Comeet)
        # -----------------------------
        if job_data is None: # Only run if JSON-LD failed
            print("ℹ️ Falling back to POSITION_DATA...")
            match = re.search(r"POSITION_DATA\s*=\s*(\{.*?\});", page_text, re.DOTALL)
            if match:
                try:
                    js_obj = match.group(1)
                    js_obj = js_obj.rstrip(";")
                    job_data = json.loads(js_obj)
                    print("✅ Found data via POSITION_DATA.")
                except Exception as e:
                    print(f"⚠️ POSITION_DATA parse error: {e}")

        # -----------------------------
        # 3. FALLBACK: extract from <h1> (page header)
        # -----------------------------
        if job_data is None: # Only run if both above failed
            print("ℹ️ Falling back to <h1> title...")
            h1 = soup.find("h1")
            if h1:
                # We create a fake job_data object just to hold the title
                job_data = {"title": h1.get_text(strip=True)}
            else:
                job_data = {} # Failsafe

        # ------------------------------------------------------------------
        # Extract and clean description (combined logic)
        # ------------------------------------------------------------------
        
        # Try getting 'description' (from JSON-LD) first
        raw_desc = job_data.get("description", "")

        # If 'description' is empty, try the POSITION_DATA structure
        if not raw_desc and "custom_fields" in job_data:
            print("ℹ️ No top-level 'description'. Trying 'custom_fields'...")
            try:
                details = job_data.get("custom_fields", {}).get("details", [])
                desc_parts = []
                for field in details:
                    # Capture both "Description" and "Requirements"
                    if field.get("name") and field.get("value"):
                        desc_parts.append(f"<h3>{html.escape(field.get('name'))}</h3>\n{field.get('value')}")
                
                if desc_parts:
                    raw_desc = "\n\n".join(desc_parts)
                
            except Exception as e:
                print(f"⚠️ Error parsing custom_fields: {e}")
        
        # -----------------------------------
        # Clean description (using your new script's method)
        # -----------------------------------
        if raw_desc:
            decoded_html = html.unescape(raw_desc)
            # Use get_text() with no separator, as in your new script
            clean_text = BeautifulSoup(decoded_html, "html.parser").get_text()
        else:
            clean_text = "No description found."

        # --- Output from your new script ---
        print("\n===== CLEANED DESCRIPTION =====\n")
        print(clean_text)

        # --- Logic from your new script ---
        # I cannot run 'local_llm_function' as it is not defined
        # You would need to define or import it for these lines to work.
        
        print("\n--- Calling LLM function ---")
        reqs_desc = local_llm_function.classify_job_for_juniors(clean_text)
        print("reqs_desc:", reqs_desc)
        reqs_desc = json.loads(reqs_desc)
        return reqs_desc
        
        # Returning the clean_text instead
        #return clean_text

    except Exception as e:
        print(f"  ❌ An unexpected error occurred: {e}")
        return None
    

def get_data_from_workday(url):
    """Fetch and classify a Workday job posting via HTML/JSON-LD scraping."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            print(f"  Workday page returned {response.status_code} for {url}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Try JSON-LD (JobPosting schema — most structured)
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = next((d for d in data if d.get("@type") == "JobPosting"), None) or {}
                description = data.get("description", "")
                if description:
                    clean_text = BeautifulSoup(html.unescape(description), "html.parser").get_text(separator="\n")
                    if clean_text.strip():
                        print("  Workday: extracted via JSON-LD")
                        reqs_desc = local_llm_function.classify_job_for_juniors(clean_text[:4000])
                        return json.loads(reqs_desc)
            except Exception as e:
                print(f"  Workday JSON-LD parse error: {e}")

        # 2. Try Workday data-automation-id selectors
        for automation_id in ("jobPostingDescription", "wd-text-viewer-placeholder"):
            div = soup.find(attrs={"data-automation-id": automation_id})
            if div:
                clean_text = div.get_text(separator="\n").strip()
                if clean_text:
                    print(f"  Workday: extracted via data-automation-id={automation_id}")
                    reqs_desc = local_llm_function.classify_job_for_juniors(clean_text[:4000])
                    return json.loads(reqs_desc)

        # 3. Fall back to full page body text
        body = soup.find("body")
        if body:
            clean_text = body.get_text(separator="\n").strip()
            if len(clean_text) > 200:
                print("  Workday: falling back to full body text")
                reqs_desc = local_llm_function.classify_job_for_juniors(clean_text[:4000])
                return json.loads(reqs_desc)

        return None

    except Exception as e:
        print(f"  Error fetching Workday job {url}: {e}")
        return None


def get_data_from_greenhouse(url):
    response = requests.get(url)
    txt = response.text

    # Regex to extract the window.__remixContext = {...};
    #pattern = r'window\.__remixContext\s*=\s*({.*?});\n' #routes/$url_token_.jobs_.$job_post_id, "jobPost":
    #pattern = r'window\.__remixContext\s*=\s*{.*?"state"\s*:\s*({.*?})\s*,.*?};\n'
    #pattern = r'window\.__remixContext\s*=\s*{.*?"state"\s*:\s*{.*?"loaderData"\s*:\s*({.*?})\s*}.*?};\n'
    #pattern = (
    #r'window\.__remixContext\s*=\s*{.*?"state"\s*:\s*{.*?"loaderData"\s*:\s*{.*?'
    #r'"routes/\$url_token_\.jobs_\.\$job_post_id"\s*:\s*({.*?})\s*}.*?}.*?};\n'
    #    )
    pattern = (
    r'window\.__remixContext\s*=\s*{.*?"state"\s*:\s*{.*?"loaderData"\s*:\s*{.*?'
    r'"routes/\$url_token_\.jobs_\.\$job_post_id"\s*:\s*{.*?"jobPost"\s*:\s*{.*?"content"\s*:\s*("(?:\\.|[^"\\])*")'
    r'.*?}.*?}.*?}.*?};\n'
)
    match = re.search(pattern, txt, re.DOTALL)
    if match:
        js_obj_str = match.group(1)
        #state_start = js_obj_str.find('"state":')
        print("js_obj_str:", js_obj_str)
 

        decoded_unicode = js_obj_str.encode('utf-8').decode('unicode_escape')

        # 2. Decode HTML entities (like &nbsp;, &amp;, etc.):
        clean_html = html.unescape(decoded_unicode)
        soup = BeautifulSoup(clean_html, "html.parser")
        plain_text = soup.get_text(separator="").strip()
        
        print(plain_text)
        reqs_desc = local_llm_function.classify_job_for_juniors(plain_text)
        print("reqs_desc:", reqs_desc)
        reqs_desc = json.loads(reqs_desc)

        return reqs_desc

    else:
        print("Could not find window.__remixContext variable in page.")

#get_data_from_greenhouse("https://job-boards.greenhouse.io/pagayais/jobs/6659796003")

def process_and_sync_data(df_new, df_existing):
    """
    Sync scraped data with the scrapers_data table.
    - INSERT new jobs that don't exist in DB
    - DELETE jobs from DB that no longer appear in scrapes
    """
    conn = connect()
    
    df_existing['created_at'] = pd.to_datetime(df_existing['created_at'], errors='coerce')
    df_existing['created_at'] = df_existing['created_at'].dt.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

    # If the timezone is missing, you can fill it with "+00:00" (UTC)
    df_existing['created_at'] = df_existing['created_at'].fillna('').str.replace(r'\+0000', '+00:00', regex=True)
    print("Processing data sync...")
    
    # Normalize merge key columns (strip whitespace, lowercase for comparison)
    merge_keys = ['company', 'job_name', 'link']
    for col in merge_keys:
        if col in df_existing.columns:
            df_existing[col] = df_existing[col].astype(str).str.strip()
        if col in df_new.columns:
            df_new[col] = df_new[col].astype(str).str.strip()
    
    print(f"DEBUG: df_existing shape={df_existing.shape}, columns={list(df_existing.columns)}")
    print(f"DEBUG: df_new shape={df_new.shape}, columns={list(df_new.columns)}")
    if not df_new.empty:
        print(f"DEBUG: df_new sample links: {df_new['link'].head(3).tolist()}")
    if not df_existing.empty:
        print(f"DEBUG: df_existing sample links: {df_existing['link'].head(3).tolist()}")
    
    # Perform an outer join on 'company', 'job_name', and 'link' to find differences
    merged_df = df_existing.merge(df_new, on=['company', 'job_name', 'link'], how='outer', indicator=True)
    print(f"DEBUG: merge results: both={len(merged_df[merged_df['_merge']=='both'])}, "
          f"left_only={len(merged_df[merged_df['_merge']=='left_only'])}, "
          f"right_only={len(merged_df[merged_df['_merge']=='right_only'])}")
    
    # Find records only in the new data (to be inserted)
    records_to_insert = merged_df[merged_df['_merge'] == 'right_only'].drop(columns=['_merge'])
    print("Records to insert:\n", records_to_insert)
    
    records_to_save = merged_df[merged_df['_merge'] == 'both'].drop(columns=['_merge'])
    print("Records to save:\n", records_to_save)
    
    final_records = pd.concat([records_to_save, records_to_insert], ignore_index=True)
    print("Final records:\n", final_records)

    # Find records in existing DB that are no longer in new scrape data (to be deleted)
    records_to_delete = df_existing[~df_existing[['company', 'job_name', 'link']].apply(tuple, axis=1).isin(df_new[['company', 'job_name', 'link']].apply(tuple, axis=1))]

    print("Records to insert:\n", records_to_insert)
    print("Records to delete:\n", records_to_delete)
    
    # =====================================================
    # ACTUALLY PERFORM DATABASE OPERATIONS
    # =====================================================
    
    # 1. INSERT new records into scrapers_data
    if not records_to_insert.empty:
        insert_columns = ['company', 'job_name', 'link', 'city_y']
        # Only select columns that exist in records_to_insert
        available_cols = [col for col in insert_columns if col in records_to_insert.columns]
        insert_df = records_to_insert[available_cols].copy()
        
        # Rename city_y to city for database insert
        if 'city_y' in insert_df.columns:
            insert_df = insert_df.rename(columns={'city_y': 'city'})
        
        # Convert to list of dicts for Supabase insert
        records_list = insert_df.to_dict(orient='records')
        
        # Clean None values
        for record in records_list:
            for key, value in list(record.items()):
                if pd.isna(value):
                    record[key] = None
        
        try:
            print(f"\n>>> INSERTING {len(records_list)} new records into scrapers_data...")
            response = conn.table("scrapers_data").insert(records_list).execute()
            print(f">>> Successfully inserted {len(records_list)} records!")
        except Exception as e:
            print(f">>> ERROR inserting records: {e}")
    else:
        print("\n>>> No new records to insert into scrapers_data")
    
    # 2. DELETE old records from scrapers_data (jobs no longer on career pages)
    if not records_to_delete.empty:
        print(f"\n>>> DELETING {len(records_to_delete)} old records from scrapers_data...")
        deleted_count = 0
        
        for idx, row in records_to_delete.iterrows():
            try:
                # Delete by ID if available (most reliable)
                if 'id' in row and pd.notna(row['id']):
                    response = conn.table("scrapers_data").delete().eq('id', int(row['id'])).execute()
                    deleted_count += 1
                    print(f"    Deleted: {row['company']} - {row['job_name']}")
                else:
                    # Fallback: delete by company + job_name + link combination
                    response = conn.table("scrapers_data").delete()\
                        .eq('company', row['company'])\
                        .eq('job_name', row['job_name'])\
                        .eq('link', row['link'])\
                        .execute()
                    deleted_count += 1
                    print(f"    Deleted: {row['company']} - {row['job_name']}")
            except Exception as e:
                print(f"    ERROR deleting {row['company']} - {row['job_name']}: {e}")
        
        print(f">>> Successfully deleted {deleted_count} records!")
    else:
        print("\n>>> No records to delete from scrapers_data")
    
    final_records = final_records.where(pd.notnull(final_records), None)
    return records_to_insert

def connect():
    dotenv_path = join(dirname(__file__), '.env')
    load_dotenv(dotenv_path)
    supabase_url = os.environ.get("supabaseUrl")
    supabase_key = os.environ.get("supabaseKey")
    return supabase.create_client(supabase_url, supabase_key)


def test(data_array):
    conn = connect()
    data_to_email = []
    data_to_email_not_for_students = []
    data_to_email_fallback = []  # Jobs that couldn't be processed by LLM but should still be sent
    us_jobs_list = []            # Non-Israeli jobs — stored in DB, sent in nightly digest
    words_to_search = ["intern", "student","junior","entry","graduate","new grad","undergraduate"]
    tmpIndex = 1

    for i in data_array:
        print(f"[{tmpIndex}/{len(data_array)}] Processing company: {i['company']}")
        tmpIndex+=1
        print(f"Company: {i['company']}, Job Name: {i['job_name']}, Link: {i['link']}")

        # Non-Israeli jobs skip Groq and the immediate email — stored for nightly digest
        if not is_location_in_israel(i.get("city_y", "")):
            us_jobs_list.append({
                "title": i["job_name"],
                "company": i["company"],
                "city": i.get("city_y", ""),
                "link": i["link"],
            })
            continue
        
        job_processed = False  # Track if job was successfully classified
        reqs_desc = None
        
        # Try to get job description and classify with LLM
        try:
            if 'comeet' in i['link']:
                reqs_desc = get_data_from_comeet(f'{i["link"]}')
            elif 'green' in i['link']:
                reqs_desc = get_data_from_greenhouse(f'{i["link"]}')
            elif 'myworkdayjobs.com' in i['link']:
                reqs_desc = get_data_from_workday(i['link'])
        except Exception as e:
            print(f"Error fetching job details for {i['company']}: {e}")
            reqs_desc = None

        # If we got valid LLM results, process them
        if reqs_desc and isinstance(reqs_desc, dict):
            try:
                # Save to database if we have description
                if reqs_desc.get('desc') or reqs_desc.get('reqs'):
                    data = {
                        "desc": reqs_desc.get('desc', ''), 
                        "reqs": reqs_desc.get('reqs', ''), 
                        "Company": i['company'], 
                        "JobDesc": i['job_name'], 
                        "Link": i['link']
                    }
                    conn.table("desc_reqs_scrapers").insert(data).execute()
                
                # Check LLM classification
                suitable = reqs_desc.get("suitable_for_junior")
                print(f"LLM classification: suitable_for_junior = {suitable}")
                
                if suitable == "True" or suitable == "Unclear":
                    tmparr = [i['job_name'], i['company'], i["city_y"], i["link"]]
                    data_to_email.append(tmparr)
                    job_processed = True
                elif suitable == "False":
                    tmparr = [i['job_name'], i['company'], i["city_y"], i["link"]]
                    data_to_email_not_for_students.append(tmparr)
                    job_processed = True
                    
            except Exception as e:
                print(f"Error processing LLM results for {i['company']}: {e}")
        
        # FALLBACK: If LLM didn't process the job, add to fallback list
        # This ensures new jobs are NEVER lost, even if LLM is unavailable
        if not job_processed:
            tmparr = [i['job_name'], i['company'], i["city_y"], i["link"]]
            
            # If job title contains student/junior keywords, add to main list
            if any(word in i['job_name'].lower() for word in words_to_search):
                print(f"Fallback: Adding '{i['job_name']}' to email list (keyword match)")
                data_to_email.append(tmparr)
            else:
                # Otherwise add to fallback list (will be sent as "unclassified")
                print(f"Fallback: Adding '{i['job_name']}' to fallback list (LLM unavailable)")
                data_to_email_fallback.append(tmparr)
    
    # Add fallback jobs to the not_for_students list so they still get sent
    # These are jobs we couldn't classify but user should still see
    if data_to_email_fallback:
        print(f"Adding {len(data_to_email_fallback)} unclassified jobs to email")
        data_to_email_not_for_students.extend(data_to_email_fallback)

    # Persist US (non-Israeli) jobs to DB for the nightly digest
    save_us_jobs_to_supabase(us_jobs_list)
    print(f"US jobs collected this run: {len(us_jobs_list)}")

    print("email: ", data_to_email, "data_to_email_not_for_students:", data_to_email_not_for_students)

    df_existing_Tal = get_existing_data_df("Tal_scrapers")
    #print(df_existing_Tal)
    df_existing_Tal_filter_today = filter_today(df_existing_Tal)
    df_existing_Tal_filter_today = df_existing_Tal_filter_today.rename(columns={"location": "city"})
    job_listings = df_existing_Tal_filter_today[["title", "company", "city", "link"]].values.tolist()
    print("df_existing_Tal_filter_today: ", job_listings)
    
    data_to_email = data_to_email + job_listings + data_to_email_not_for_students
    SendEmail(data_to_email, data_to_email, job_listings, data_to_email_not_for_students)



def main():
    asyncio.get_event_loop().close()
    print(asyncio.get_event_loop().is_closed())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()
    df_existing = get_existing_data_df() 
    with open(DEDUP_JSON_PATH, 'r') as file:
        data = json.load(file)
    loop.run_until_complete(process_jobs2(data))

    # Check if tmp.txt exists (it won't if no Israel jobs were found)
    tmp_file_path = ETL_TMP_CLEAN
    if not os.path.exists(tmp_file_path):
        print("No Israel jobs found in this run - tmp.txt was not created. Skipping ETL processing.")
        return
      
    with open(tmp_file_path, 'r',encoding='utf-8') as file:
        content = file.read()
    
    # Check if file is empty
    if not content.strip():
        print("tmp.txt is empty - no jobs to process. Skipping ETL processing.")
        return
        
    df_new = get_new_data_df(content)
    records_to_insert = process_and_sync_data(df_new, df_existing) 
    selected_columns = ["company", "job_name", "link", "city_y"]
    filtered_df = records_to_insert[selected_columns]
    data_dict = filtered_df.to_dict(orient="records")
    data_array = filtered_df.values.tolist()
    conn = connect()
    print("Records to insert:\n", data_dict)
    try:
        test(data_dict)
    except Exception as e:
        print(f"Error in test(): {e}")
        RUN_MODE = os.environ.get("RUN_MODE", "local")
        if RUN_MODE == "local":
            print("Please open LM Studio! \nPress enter when you are ready.")
            input()
            test(data_dict)
        else:
            print("Running in cron mode - skipping retry prompt. Jobs will be emailed without LLM classification.")




    #df_existing_Tal = get_existing_data_df("Tal_scrapers")
    ##print(df_existing_Tal)
    #df_existing_Tal_filter_today = filter_today(df_existing_Tal)
    #df_existing_Tal_filter_today = df_existing_Tal_filter_today.rename(columns={"location": "city"})
    #job_listings = df_existing_Tal_filter_today[["title", "company", "city", "link"]].values.tolist()
    #print(job_listings)
    
        
    #titles = []
    #data_to_email = []
    #words_to_search = ["intern", "student","junior","entry","graduate","new grad","undergraduate"]
    #for i in data_array:
    #    print(f"Company: {i[0]}, Job Name: {i[1]}, City: {i[3]}, Link: {i[2]}")
    #    if 'comeet' in i[2]:
    #        reqs_desc = get_data_from_comeet(f'Link: {i[2]}')
#
    #    elif 'green' in i[2]:
    #        reqs_desc = get_data_from_greenhouse(f'Link: {i[2]}')
    #        
    #    titles.append(i[1])
#
    #    if 'comeet' in i[2] or 'green' in i[2]:
    #        #print(reqs_desc["desc"])
    #        #print(local_llm_function.classify_job_for_juniors(reqs_desc["desc"], reqs_desc["reqs"]))
    #        data = {
    #                    "desc": reqs_desc['desc'], 
    #                    "reqs": reqs_desc['reqs'], 
    #                    "Company": i['company'], 
    #                    "JobDesc": i['job_name'], 
    #                    "Link": i['link']
    #                }
    #        conn.table("desc_reqs_scrapers").insert(data).execute()
    #    
    #    try:
    #        if reqs_desc["suitable_for_junior"] == "True" or reqs_desc["suitable_for_junior"] == "Unclear":
    #            tmparr = [i[1], i[0], i[3], i[2]]
    #            data_to_email.append(tmparr)
    #        elif any(word in i[1].lower() for word in words_to_search):
    #            tmparr = [i[1], i[0], i[3], i[2]]
    #            data_to_email.append(tmparr)
    #    except:
    #        continue
    #print(data_to_email)
    #print(tmparr)
    #    
    #    #loop.run_until_complete(get_bot_details(i, None))
    #SendEmail(data_to_email)
    #TypeOfListing = chat.chatWithLamaForGettingJobs(titles)
    #print(f"TypeOfListing: {TypeOfListing}")
    #loop.close()


    # Get new data from the parsed text file
    
#def is_location_in_israel(location_name):
#    gc = geonamescache.GeonamesCache()
#    cities = gc.get_cities()
#
#    # Iterate through all cities and check if the location matches and belongs to Israel
#    for city_data in cities.values():
#        if city_data['name'].lower() == location_name.lower() and city_data['countrycode'] == 'IL':
#            return True  # The location is in Israel
#
#    return False  # Location not found or not in Israel
#
##print(is_location_in_israel("Naimi Park, Or Yehuda, Israel"))

