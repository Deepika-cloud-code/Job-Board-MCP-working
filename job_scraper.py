from playwright.sync_api import sync_playwright
import re
from typing import List, Dict


CATEGORY_URLS = {
    "data_engineer": "https://jobright.ai/minisites-jobs/newgrad/us/data_engineer?embed=true",
    "data_analyst": "https://jobright.ai/minisites-jobs/newgrad/us/data_analysis?embed=true",
    "business_analyst": "https://jobright.ai/minisites-jobs/newgrad/us/business_analyst?embed=true",
    "machine_learning_ai": "https://jobright.ai/minisites-jobs/newgrad/us/ml_ai?embed=true",
}


def fetch_page_text(page, url: str) -> str:
    """
    Opens a category iframe URL, waits for the jobs table to render,
    scrolls to load more visible rows, and returns the page text.
    """

    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # Wait for the embedded app/table to render
    page.wait_for_timeout(8000)

    collected_text_parts = []

    # First read before scrolling
    collected_text_parts.append(page.locator("body").inner_text())

    # Scroll down to trigger lazy-loaded/virtualized rows
    for _ in range(6):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1500)
        collected_text_parts.append(page.locator("body").inner_text())

    # Scroll back to top and read once more
    page.mouse.wheel(0, -15000)
    page.wait_for_timeout(1500)
    collected_text_parts.append(page.locator("body").inner_text())

    combined_text = "\n".join(collected_text_parts)

    # Retry once if no job timing text is found
    if "hours ago" not in combined_text.lower() and "minutes ago" not in combined_text.lower():
        page.wait_for_timeout(8000)

        for _ in range(6):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1500)
            collected_text_parts.append(page.locator("body").inner_text())

        combined_text = "\n".join(collected_text_parts)

    return combined_text


def parse_posted_hours(posted_text: str) -> int | None:
    posted_text = posted_text.lower().strip()

    match = re.search(r"(\d+)\s+hours?\s+ago", posted_text)
    if match:
        return int(match.group(1))

    match = re.search(r"(\d+)\s+minutes?\s+ago", posted_text)
    if match:
        return 0

    if "today" in posted_text:
        return 24

    return None


def parse_jobs_from_text(raw_text: str, category: str, source_url: str) -> List[Dict]:
    """
    Splits page text into job blocks.

    The website usually separates jobs with numeric row markers:
    1, 2, 3, etc.
    """

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    jobs = []
    current_block = []

    for line in lines:
        if line.isdigit():
            if current_block:
                job = parse_job_block(current_block, category, source_url)
                if job:
                    jobs.append(job)

            current_block = []
        else:
            current_block.append(line)

    if current_block:
        job = parse_job_block(current_block, category, source_url)
        if job:
            jobs.append(job)

    return jobs


def parse_job_block(block: List[str], category: str, source_url: str) -> Dict | None:
    """
    Parses one job block into a structured dictionary.

    This version is flexible:
    - It does not assume the date is only on the first line.
    - It searches the whole job block for "X hours ago" / "X minutes ago".
    """

    if not block:
        return None

    date_match = None
    date_line_index = None

    for idx, line in enumerate(block):
        match = re.search(
            r"(\d+\s+hours?\s+ago|\d+\s+minutes?\s+ago|today)",
            line,
            re.IGNORECASE,
        )

        if match:
            date_match = match
            date_line_index = idx
            break

    if not date_match or date_line_index is None:
        return None

    posted = date_match.group(1)
    posted_hours_ago = parse_posted_hours(posted)

    date_line = block[date_line_index]

    # Case 1: title and date are on the same line
    title = date_line[:date_match.start()].strip()

    # Case 2: title is on the previous line
    if not title and date_line_index > 0:
        title = block[date_line_index - 1].strip()

    if not title:
        return None

    block_text = " ".join(block)

    # H1B Sponsored and Is New Grad usually appear near the end.
    # Example: "Not Sure        Not Sure"
    status_tokens = re.findall(
        r"\b(Not Sure|Yes|No)\b",
        block_text[-700:],
        flags=re.IGNORECASE,
    )

    normalized_status_tokens = [
        token.title() if token.lower() != "not sure" else "Not Sure"
        for token in status_tokens
    ]

    h1b_sponsorship = (
        normalized_status_tokens[-2]
        if len(normalized_status_tokens) >= 2
        else "Unknown"
    )

    is_new_grad = (
        normalized_status_tokens[-1]
        if len(normalized_status_tokens) >= 1
        else "Unknown"
    )

    return {
        "title": title,
        "category": category,
        "posted": posted,
        "posted_hours_ago": posted_hours_ago,
        "h1b_sponsorship": h1b_sponsorship,
        "is_new_grad": is_new_grad,
        "raw_details": block_text,
        "source_url": source_url,
    }


def search_jobs(
    categories: List[str],
    posted_within_hours: int = 24,
    h1b_values: List[str] | None = None,
    headless: bool = False,
) -> List[Dict]:
    if h1b_values is None:
        h1b_values = ["Yes", "Not Sure"]

    allowed_h1b = {value.lower().strip() for value in h1b_values}

    all_jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        for category in categories:
            if category not in CATEGORY_URLS:
                print(f"Skipping unknown category: {category}")
                continue

            url = CATEGORY_URLS[category]

            print(f"\nOpening category: {category}")
            print(f"URL: {url}")

            page = browser.new_page()
            raw_text = fetch_page_text(page, url)

            # Save raw text for debugging
            debug_file = f"debug_{category}.txt"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(raw_text)

            jobs = parse_jobs_from_text(raw_text, category, url)

            print(f"Parsed {len(jobs)} jobs before filtering for {category}")

            for job in jobs:
                within_time = (
                    job["posted_hours_ago"] is not None
                    and job["posted_hours_ago"] <= posted_within_hours
                )

                h1b_match = job["h1b_sponsorship"].lower().strip() in allowed_h1b

                if within_time and h1b_match:
                    all_jobs.append(job)

            print(f"Total collected so far: {len(all_jobs)}")

            page.close()

        browser.close()

    return deduplicate_jobs(all_jobs)


def deduplicate_jobs(jobs: List[Dict]) -> List[Dict]:
    seen = set()
    unique_jobs = []

    for job in jobs:
        key = (
            job.get("title", "").lower().strip(),
            job.get("category", "").lower().strip(),
            job.get("posted", "").lower().strip(),
            job.get("source_url", "").lower().strip(),
        )

        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    return unique_jobs


if __name__ == "__main__":
    results = search_jobs(
        categories=[
            "data_engineer",
            "data_analyst",
            "business_analyst",
            "machine_learning_ai",
        ],
        posted_within_hours=24,
        h1b_values=["Yes", "Not Sure"],
        headless=False,
    )

    print(f"\nFound {len(results)} jobs\n")

    for idx, job in enumerate(results, start=1):
        print(f"{idx}. {job['title']}")
        print(f"   Category: {job['category']}")
        print(f"   Posted: {job['posted']}")
        print(f"   H1B: {job['h1b_sponsorship']}")
        print(f"   New Grad: {job['is_new_grad']}")
        print(f"   Source: {job['source_url']}")
        print()