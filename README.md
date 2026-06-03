# job-board-mcp

An MCP (Model Context Protocol) server that scrapes **new grad job listings** from [Jobright.ai](https://jobright.ai) and exposes them to MCP-compatible clients (Claude Desktop, Claude Code, etc.) as a callable tool.

The server lets an AI assistant answer questions like "show me data engineer new grad jobs posted in the last 12 hours that sponsor H1B" without leaving the chat.

---

## Table of contents

1. [What this project does](#what-this-project-does)
2. [How it works at a glance](#how-it-works-at-a-glance)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Running the scraper directly](#running-the-scraper-directly)
6. [Running as an MCP server](#running-as-an-mcp-server)
7. [Wiring it into an MCP client](#wiring-it-into-an-mcp-client)
8. [The `search_newgrad_jobs` tool](#the-search_newgrad_jobs-tool)
9. [Output schema](#output-schema)
10. [How the scraper works, step by step](#how-the-scraper-works-step-by-step)
11. [Debugging](#debugging)
12. [Extending the scraper](#extending-the-scraper)
13. [Known limitations](#known-limitations)
14. [Project layout](#project-layout)

---

## What this project does

Jobright.ai hosts curated new-grad job boards behind virtualized, JavaScript-rendered tables. There is no public API, and the rows only exist in the DOM while they are scrolled into view. This project:

- Launches a headless Chromium browser via Playwright
- Loads the Jobright "minisites-jobs/newgrad" iframe URL for each requested category
- Scrolls through the virtualized table and harvests the rendered text
- Parses that text into structured job records (title, posted time, H1B sponsorship, new-grad flag, source URL)
- Filters records by **how recently they were posted** and by **H1B sponsorship status**
- Returns the result either as plain Python output (when run directly) or as a tool response over MCP (when run as a server)

Four categories are currently wired up:

| Key                    | Jobright page              |
| ---------------------- | -------------------------- |
| `data_engineer`        | newgrad / data_engineer    |
| `data_analyst`         | newgrad / data_analysis    |
| `business_analyst`     | newgrad / business_analyst |
| `machine_learning_ai`  | newgrad / ml_ai            |

---

## How it works at a glance

```
MCP client (e.g. Claude Desktop)
        |
        |  calls tool: search_newgrad_jobs(...)
        v
server.py  (FastMCP wrapper)
        |
        |  splits comma-separated args, calls search_jobs(...)
        v
job_scraper.py
        |
        |  Playwright -> Chromium -> Jobright iframe
        |  scroll, capture inner_text, parse, filter, dedup
        v
returns list[dict] of job records
```

---

## Prerequisites

- **Python 3.12 or newer** (declared in `pyproject.toml`)
- **Poetry** for dependency management (https://python-poetry.org/docs/#installation)
- **A working Chromium install** managed by Playwright (installed in the next step — you do not need to install Chrome yourself)
- An OS that Playwright supports (this repo is developed on Windows 11; macOS and Linux work the same way)

---

## Installation

From the project root:

```bash
# 1. Install Python dependencies into a Poetry-managed virtual env
poetry install

# 2. Download the Chromium binary that Playwright will drive
poetry run playwright install chromium
```

The second step is **required** — without it, every scrape call will fail because Playwright cannot find a browser to launch. You only need to run it once per machine (re-run after upgrading the `playwright` package).

The repo also ships with a `.venv/` directory; you can use that directly instead of Poetry's managed env if you prefer (`./.venv/Scripts/python ...` on Windows, `./.venv/bin/python ...` on macOS/Linux), but commands below assume Poetry.

---

## Running the scraper directly

`job_scraper.py` has a `__main__` block that runs the full scrape with a **visible browser window** (headful) so you can watch what Playwright is doing:

```bash
poetry run python job_scraper.py
```

This will:

1. Open all four categories one by one
2. Scroll each page to load virtualized rows
3. Write the raw extracted text for each category to `debug_<category>.txt` in the project root (overwrites previous runs)
4. Print the filtered, deduplicated jobs to stdout

This is the **primary way to iterate on scraper logic**: tweak parsing, re-run, inspect the `debug_*.txt` files to see exactly what `inner_text()` produced.

---

## Running as an MCP server

```bash
poetry run python server.py
```

The server uses the **stdio transport** (FastMCP's default). It does not listen on a port — MCP clients spawn the process and communicate over stdin/stdout. Running `server.py` from a normal terminal is mostly useful as a sanity check; you'll see `Starting job-board-mcp server...` on stderr and then nothing (the server is waiting for an MCP client on stdin).

When invoked through an MCP client, the server always runs the scraper with `headless=True` — no browser window pops up.

---

## Wiring it into an MCP client

MCP clients launch local servers by spawning a command. Point your client at this project's `server.py` via Poetry. The exact config file depends on the client; the **shape** is the same.

### Claude Desktop example

Edit `claude_desktop_config.json` (on Windows it lives in `%APPDATA%\Claude\`) and add an entry under `mcpServers`:

```json
{
  "mcpServers": {
    "job-board-mcp": {
      "command": "poetry",
      "args": [
        "--directory",
        "C:\\Users\\<you>\\OneDrive\\Desktop\\git_personal\\job-board-mcp",
        "run",
        "python",
        "server.py"
      ]
    }
  }
}
```

Restart the client. The tool `search_newgrad_jobs` will then be available to the assistant.

> If `poetry` is not on your client's `PATH` (Claude Desktop launches with a minimal env on Windows), use the absolute path to the Python interpreter inside `.venv` as `command` instead, and put `server.py`'s absolute path in `args`.

---

## The `search_newgrad_jobs` tool

```text
search_newgrad_jobs(
    categories: str = "data_engineer,data_analyst,business_analyst,machine_learning_ai",
    posted_within_hours: int = 24,
    h1b_sponsorship: str = "Yes,Not Sure",
) -> list[dict]
```

All three arguments are simple scalars so MCP clients can fill them in trivially. Both `categories` and `h1b_sponsorship` are **comma-separated strings**, not arrays — `server.py` splits them before calling into the scraper.

| Argument              | Meaning                                                                 |
| --------------------- | ----------------------------------------------------------------------- |
| `categories`          | Any subset of the four keys in [the table above](#what-this-project-does). Unknown keys are silently skipped (and logged to stdout). |
| `posted_within_hours` | Keep jobs whose parsed "X hours ago" is `<=` this number. `today` is treated as 24. Jobs with an unparseable date are dropped. |
| `h1b_sponsorship`     | Keep jobs whose H1B field matches one of these values (case-insensitive). Common values on the site are `Yes`, `No`, `Not Sure`. |

### Example calls

| Goal                                                       | Call                                                                                   |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| All defaults: 4 categories, last 24h, Yes or Not Sure H1B  | `search_newgrad_jobs()`                                                                |
| Only data engineer jobs in the last 6 hours                | `search_newgrad_jobs(categories="data_engineer", posted_within_hours=6)`               |
| ML/AI jobs that **explicitly** say Yes to H1B in last 48h  | `search_newgrad_jobs(categories="machine_learning_ai", posted_within_hours=48, h1b_sponsorship="Yes")` |

---

## Output schema

The tool returns a `list[dict]`. Each dict represents one job:

```python
{
    "title": "Data Engineer, New Grad 2026",
    "category": "data_engineer",
    "posted": "3 hours ago",
    "posted_hours_ago": 3,            # int, or None if unparseable
    "h1b_sponsorship": "Yes",         # "Yes" | "No" | "Not Sure" | "Unknown"
    "is_new_grad": "Yes",             # "Yes" | "No" | "Not Sure" | "Unknown"
    "raw_details": "...",             # the full job-block text (useful for debugging)
    "source_url": "https://jobright.ai/minisites-jobs/newgrad/us/data_engineer?embed=true",
}
```

Results are **deduplicated** on `(title, category, posted, source_url)` lowercased — the scraper captures `inner_text()` several times during scrolling, so the same job appears in multiple snapshots and would otherwise show up repeatedly.

---

## How the scraper works, step by step

This section walks through `job_scraper.py` in execution order so you can follow what each function does.

### 1. `search_jobs(categories, posted_within_hours, h1b_values, headless)` — entry point

- Normalises `h1b_values` into a lowercased set for fast membership tests.
- Launches a single Chromium instance via `sync_playwright()`.
- Loops over the requested categories; unknown ones are skipped with a log line.
- For each category:
  - Opens a fresh page (`browser.new_page()`).
  - Calls `fetch_page_text` to extract the rendered text.
  - Writes that text verbatim to `debug_<category>.txt`.
  - Calls `parse_jobs_from_text` to turn text into structured rows.
  - Applies the time and H1B filters.
- After all categories are scraped, calls `deduplicate_jobs` and returns the result.

### 2. `fetch_page_text(page, url)` — get text out of a virtualized table

The Jobright iframe (`?embed=true`) renders rows only while they are scrolled into view, so a single `inner_text()` read would miss most jobs. The function:

1. Navigates to the URL with `wait_until="domcontentloaded"`, then sleeps **8s** to let the embedded app boot.
2. Captures `body.inner_text()` once.
3. Scrolls down in **6 steps** of 2500 pixels, sleeping 1.5s between each step, capturing `inner_text()` after every scroll.
4. Scrolls back to the top and captures one more time.
5. Joins all captured snapshots with newlines.
6. **Retry guard**: if the joined text contains neither `"hours ago"` nor `"minutes ago"`, the app probably wasn't ready — sleep another 8s and run the scroll loop again.

The result is a single long string containing every row that became visible at some point during the scroll.

### 3. `parse_jobs_from_text(raw_text, category, source_url)` — split into blocks

Jobright separates rows in the rendered text by emitting the row index on its own line: `1`, `2`, `3`, ... The parser:

- Splits `raw_text` into non-empty lines.
- Iterates: whenever a line is a bare integer, it treats the **previous accumulated lines** as one job block and starts a fresh block.
- After the loop, flushes the final block.
- Calls `parse_job_block` on each block.

This numeric-row-marker heuristic is the only reliable separator the site emits, which is why parsing is line-based rather than DOM-based.

### 4. `parse_job_block(block, category, source_url)` — extract fields from one block

For each block:

1. Scans every line for the regex `(\d+\s+hours?\s+ago|\d+\s+minutes?\s+ago|today)`. The **first** match wins — this is the posting-time line.
2. If no date is found, the block is discarded (returns `None`).
3. Title resolution:
   - First try: text **before** the date match on the same line.
   - Fallback: the line **immediately before** the date line.
   - If neither yields a non-empty title, drop the block.
4. H1B and new-grad fields:
   - Concatenate the block back into one string.
   - In the **last 700 characters**, find all `Yes | No | Not Sure` tokens.
   - Assume the second-to-last is the H1B field and the last is the new-grad field. (That's the order Jobright renders them in the row.)
   - If fewer than two tokens are found, fall back to `"Unknown"`.
5. Returns the job dict described in [Output schema](#output-schema).

### 5. `parse_posted_hours(posted_text)` — turn "3 hours ago" into an int

- `"X hours ago"` → `X`
- `"X minutes ago"` → `0` (it's less than an hour, so within any "last N hours" filter)
- `"today"` → `24`
- Anything else → `None` (the row will fail the time filter)

### 6. Filtering — back in `search_jobs`

For each parsed job:

- **Time filter**: `posted_hours_ago is not None and posted_hours_ago <= posted_within_hours`.
- **H1B filter**: the job's `h1b_sponsorship` (lowercased) is in the user-supplied set.

Jobs that pass both are appended to `all_jobs`.

### 7. `deduplicate_jobs(jobs)` — drop duplicates from overlapping scroll snapshots

Builds a key from `(title, category, posted, source_url)` (all lowercased and stripped) and keeps only the first occurrence.

---

## Debugging

When something goes wrong, work from the outside in:

1. **No jobs returned at all** — re-run `poetry run python job_scraper.py` (headful) and watch the browser. Is the page even loading? Does the iframe show jobs? Is there a captcha?
2. **Wrong number of jobs / wrong titles** — open `debug_<category>.txt`. This is exactly what the parser saw. If the row-index markers are missing, or the layout has changed, the numeric-marker split in `parse_jobs_from_text` needs to be reworked.
3. **All `h1b_sponsorship` come back as `"Unknown"`** — the trailing-700-char heuristic in `parse_job_block` did not find `Yes/No/Not Sure` tokens. Check the debug file to see what Jobright is rendering for those fields now.
4. **Playwright errors on launch** — you probably skipped `playwright install chromium`. Run it.
5. **MCP client doesn't see the tool** — confirm `poetry run python server.py` runs (it should print `Starting job-board-mcp server...` to stderr and then block). Then double-check the client's config path/args.

When iterating on parsing, you do not need to rescrape every time — copy a `debug_*.txt` into a quick test harness and call `parse_jobs_from_text(open(path).read(), category, url)` directly.

---

## Extending the scraper

### Adding a new category

1. Add an entry to `CATEGORY_URLS` in `job_scraper.py`:

   ```python
   CATEGORY_URLS = {
       ...,
       "software_engineer": "https://jobright.ai/minisites-jobs/newgrad/us/software_engineer?embed=true",
   }
   ```

2. Update the default value and docstring of `search_newgrad_jobs` in `server.py` so MCP clients discover the new key.

3. Run `poetry run python job_scraper.py` to confirm the new page parses cleanly. Check the new `debug_software_engineer.txt`.

### Changing the posted-time logic

`parse_posted_hours` is the only place that interprets the date phrase. If Jobright introduces new phrases like `"yesterday"` or `"X days ago"`, add a branch there. Remember the time filter compares **hours**, so days should be converted (e.g. `"3 days ago"` → `72`).

### Changing the scroll/wait timings

`fetch_page_text` is conservative on purpose: 8s initial wait, 6 scrolls × 1.5s, and a retry pass. If you find the page reliably loads faster (or, more often, slower), tune the `wait_for_timeout` and scroll-count values there. Going too low will reintroduce flaky empty pages.

---

## Known limitations

- **Brittle to Jobright layout changes.** The scraper relies on rendered text and the numeric-row-marker separator. Any major UI change to Jobright will likely break parsing first (not navigation). The debug files are your early-warning system.
- **No persistence.** Each call rescrapes from scratch. There is no cache, no database, no rate-limit handling.
- **No tests.** The repo currently has no automated tests or linting.
- **Sync Playwright API.** The scraper is synchronous, which means MCP calls block until the scrape finishes (typically tens of seconds for all four categories). Clients should expect long tool-response times.
- **One MCP tool.** The server exposes only `search_newgrad_jobs`; there is no separate "list categories" or "refresh" tool.

---

## Project layout

```
job-board-mcp/
├── server.py              # FastMCP server; exposes the single tool
├── job_scraper.py         # Playwright + text-parsing pipeline
├── pyproject.toml         # Poetry config, Python >=3.12, deps: mcp, playwright, python-dotenv
├── poetry.lock
├── CLAUDE.md              # Guidance for Claude Code working in this repo
├── README.md              # You are here
├── debug_<category>.txt   # Per-category raw page text from the most recent scrape (gitignored in practice)
└── .venv/                 # Local virtual env (optional; Poetry also manages one)
```
