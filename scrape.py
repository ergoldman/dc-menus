#!/usr/bin/env python3
"""
UC Davis Dining Commons menu scraper.

Renders each DC page with Playwright (the menu is injected client-side, so a
plain HTTP request returns an empty shell), then parses the Bootstrap accordion
into structured dishes with meal period, zone, dietary tags, allergens, and
nutrition.

Setup (one time):
    pip install playwright beautifulsoup4
    playwright install chromium

Run:
    python scrape.py            # scrape all DCs -> menus.json
    python scrape.py --headed   # show the browser while it works
"""

import sys
import re
import os
import json
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DINING_COMMONS = [
    ("Segundo", "https://housing.ucdavis.edu/dining/dining-commons/segundo/"),
    ("Tercero", "https://housing.ucdavis.edu/dining/dining-commons/tercero/"),
    ("Cuarto",  "https://housing.ucdavis.edu/dining/dining-commons/cuarto/"),
]

HEADED = "--headed" in sys.argv

SKIP_NAMES = {"Menu Filters"}
NUTRITION_LABELS = ("Contains", "Serving Size", "Calories", "Fat", "Carb",
                    "Sugar", "Protein", "Sodium", "Fiber", "Cholesterol")

# Patterns that mark a row as NOT a real dish (section/time markers, arrow noise)
_ZONE_MARKER = re.compile(r"@\s*(Red|Yellow|Blue|Green|Pink|Purple)\s*Zone", re.I)
_TIME_MARKER = re.compile(r"^\d{1,2}:\d{2}\s")
_ARROW_TAIL = re.compile(r"\s*--+>+\s*$")


def _is_junk(name):
    n = name.strip()
    if _ZONE_MARKER.search(n):
        return True
    if _TIME_MARKER.match(n):
        return True
    if set(n) <= set("->> "):  # bare arrow rows
        return True
    return False


def parse_dc(html, dc_name):
    """Parse one DC's rendered HTML into a list of dish dicts."""
    soup = BeautifulSoup(html, "html.parser")
    dishes = []
    current_meal = None
    current_zone = None

    for el in soup.find_all(["h2", "h3", "div"]):
        cls = el.get("class") or []

        if el.name == "h2" and "stickyMealHeader" in cls:
            current_meal = el.get_text(strip=True)
            current_zone = None
        elif el.name == "h3":
            txt = el.get_text(strip=True)
            if "Zone" in txt:
                current_zone = txt
        elif el.name == "div" and "panel" in cls and "panel-default" in cls:
            link = el.select_one('a[data-toggle="collapse"]')
            md = el.select_one(".mealDetails")
            if not link or not md:
                continue

            name = link.get_text(strip=True)
            if not name or name in SKIP_NAMES or _is_junk(name):
                continue
            name = _ARROW_TAIL.sub("", name).strip()
            if not name:
                continue

            # Dietary tags from icon alt text (Vegan / Vegetarian / Halal)
            dietary = [img.get("alt") for img in md.select("img[alt]") if img.get("alt")]

            # Allergens from the "Contains: ..." line
            allergens = []
            full_text = md.get_text(" ", strip=True)
            m = re.search(r"Contains\s*:\s*([^.]*)", full_text)
            if m:
                allergens = [a.strip() for a in m.group(1).split(",") if a.strip()]

            # Description = first underline paragraph that isn't a nutrition label
            description = ""
            for p in md.select("p.underline"):
                t = p.get_text(" ", strip=True)
                if not t.startswith(NUTRITION_LABELS):
                    description = t
                    break

            # Calories
            calories = None
            cm = re.search(r"Calories\s*:\s*([\d.]+)", full_text)
            if cm:
                calories = float(cm.group(1))

            dishes.append({
                "dc": dc_name,
                "meal": current_meal,
                "zone": current_zone,
                "name": name,
                "description": description,
                "dietary": dietary,
                "allergens": allergens,
                "calories": calories,
            })

    # De-duplicate: the page repeats some panels. Keep first of each (name, meal, zone).
    seen = set()
    unique = []
    for d in dishes:
        key = (d["name"], d["meal"], d["zone"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


def scrape():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADED)
        for dc_name, url in DINING_COMMONS:
            page = browser.new_page()
            try:
                print(f"[{dc_name}] loading {url}")
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)
                html = page.content()
                dishes = parse_dc(html, dc_name)
                print(f"[{dc_name}] parsed {len(dishes)} dishes")
                results.append({
                    "dc": dc_name,
                    "url": url,
                    "scrapedAt": datetime.now().isoformat(),
                    "dishes": dishes,
                })
            except Exception as e:
                print(f"[{dc_name}] ERROR: {e}")
                results.append({"dc": dc_name, "url": url, "error": str(e), "dishes": []})
            finally:
                page.close()
        browser.close()

    # Current snapshot (what the app reads)
    with open("menus.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Dated archive copy — this is the historical record that builds over time.
    # Once written, a given day's file never changes, so history accumulates.
    os.makedirs("archive", exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join("archive", f"{stamp}.json")
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total = sum(len(r["dishes"]) for r in results)
    print(f"\nwrote menus.json — {total} dishes across {len(results)} dining commons")
    print(f"archived {archive_path}")
    if total == 0:
        print("0 dishes: the site may be empty right now (migration). Try again later,")
        print("or run with --headed to watch what loads.")


if __name__ == "__main__":
    scrape()
