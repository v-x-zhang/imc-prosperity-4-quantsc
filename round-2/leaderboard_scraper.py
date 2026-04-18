"""
IMC Prosperity 4 Leaderboard Scraper
Uses Playwright to scrape JS-rendered leaderboard from https://prosperity.imc.com/leaderboard
"""

import re
import csv
from playwright.sync_api import sync_playwright

BASE_URL = "https://prosperity.imc.com/leaderboard"


def scrape_page(page_num: int = 1) -> list[dict]:
    """Scrape a single leaderboard page and return list of team dicts."""
    url = BASE_URL if page_num == 1 else f"{BASE_URL}?page={page_num}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(3000)

        text = page.inner_text("body")
        browser.close()

    return parse_leaderboard_text(text)


def parse_leaderboard_text(text: str) -> list[dict]:
    """Parse the raw page text into team dicts."""
    teams = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    i = 0
    while i < len(lines):
        rank_match = re.match(r"^(\d{1,5})$", lines[i])
        if rank_match:
            rank = int(rank_match.group(1))
            j = i + 1
            # Skip flag emoji lines
            while j < len(lines) and re.match(r"^[\U0001F1E0-\U0001F1FF\U0001F3F4\s🏴]+$", lines[j]):
                j += 1
            if j >= len(lines):
                i += 1
                continue
            team = lines[j]
            j += 1
            if j >= len(lines):
                i += 1
                continue
            country = lines[j]
            j += 1
            if j < len(lines) and re.match(r"^-?[\d,]+$", lines[j]):
                score = int(lines[j].replace(",", ""))
                teams.append({
                    "rank": rank,
                    "team": team,
                    "country": country,
                    "score": score,
                })
                i = j + 1
                continue
        i += 1

    return teams


def scrape_leaderboard(pages: int = 1) -> list[dict]:
    """Scrape multiple pages of the leaderboard."""
    all_teams = []
    for page in range(1, pages + 1):
        teams = scrape_page(page)
        all_teams.extend(teams)
        print(f"Page {page}: scraped {len(teams)} teams")

    # Deduplicate by rank
    seen = set()
    unique = []
    for t in all_teams:
        if t["rank"] not in seen:
            seen.add(t["rank"])
            unique.append(t)
    return sorted(unique, key=lambda x: x["rank"])


def save_csv(teams: list[dict], filename: str = "leaderboard.csv"):
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "team", "country", "score"])
        writer.writeheader()
        writer.writerows(teams)


if __name__ == "__main__":
    all_teams = []
    for pg in range(217, 223):
        teams = scrape_page(pg)
        all_teams.extend(teams)
        print(f"Page {pg}: scraped {len(teams)} teams")

    for t in all_teams:
        print(f"{t['rank']:>5}  {t['team']:<35} {t['country']:<20} {t['score']:>10,}")
    save_csv(all_teams, "data/leaderboard_pages_217_222.csv")
        
