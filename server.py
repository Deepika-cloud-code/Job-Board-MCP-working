from mcp.server.fastmcp import FastMCP
import sys

from job_scraper import search_jobs

mcp = FastMCP("job-board-mcp")


@mcp.tool()
def search_newgrad_jobs(
    categories: str = "data_engineer,data_analyst,business_analyst,machine_learning_ai",
    posted_within_hours: int = 24,
    h1b_sponsorship: str = "Yes,Not Sure",
) -> list[dict]:
    """
    Search new grad jobs from Jobright/newgrad job board.

    Supported categories:
    - data_engineer
    - data_analyst
    - business_analyst
    - machine_learning_ai

    Filters:
    - posted within the given number of hours
    - H1B sponsorship values such as Yes or Not Sure
    """

    category_list = [
        category.strip()
        for category in categories.split(",")
        if category.strip()
    ]

    h1b_values = [
        value.strip()
        for value in h1b_sponsorship.split(",")
        if value.strip()
    ]

    jobs = search_jobs(
        categories=category_list,
        posted_within_hours=posted_within_hours,
        h1b_values=h1b_values,
        headless=True,
    )

    return jobs


if __name__ == "__main__":
    print("Starting job-board-mcp server...", file=sys.stderr)
    mcp.run()