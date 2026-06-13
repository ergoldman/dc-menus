#!/usr/bin/env python3
"""
Sends push notifications: for each subscriber, checks whether any of their
favorite dishes appears in today's menus.json, and if so sends one push.

Runs in the GitHub Action right after scrape.py. Needs three secrets in env:
  SUPABASE_URL          - your project URL
  SUPABASE_SECRET_KEY   - the sb_secret_... key (server-side only)
  VAPID_PRIVATE_KEY     - the private VAPID key
  VAPID_PUBLIC_KEY      - the public VAPID key
  VAPID_SUBJECT         - a mailto: contact, e.g. mailto:you@example.com
"""

import os
import json
import sys
from urllib import request as urlrequest

from pywebpush import webpush, WebPushException

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
VAPID_PRIVATE = os.environ["VAPID_PRIVATE_KEY"]
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")


def sb_get(table, params=""):
    """Read all rows from a Supabase table via the REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?select=*{params}"
    req = urlrequest.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    with urlrequest.urlopen(req) as r:
        return json.loads(r.read().decode())


def sb_delete(table, column, value):
    """Delete rows where column == value (used to clean up dead subscriptions)."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{column}=eq.{value}"
    req = urlrequest.Request(url, method="DELETE", headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    try:
        urlrequest.urlopen(req)
    except Exception:
        pass


def main():
    # Load today's menu and build a set of dish names available today
    with open("menus.json", encoding="utf-8") as f:
        menus = json.load(f)
    todays_dishes = set()
    for dc in menus:
        for dish in dc.get("dishes", []):
            todays_dishes.add(dish["name"])

    subscriptions = sb_get("subscriptions")
    favorites = sb_get("favorites")

    # Group favorites by subscription
    favs_by_sub = {}
    for fav in favorites:
        favs_by_sub.setdefault(fav["subscription_id"], []).append(fav["dish_name"])

    sent = 0
    for sub in subscriptions:
        wanted = favs_by_sub.get(sub["id"], [])
        # Which of this person's favorites are on the menu today?
        matches = [name for name in wanted if name in todays_dishes]
        if not matches:
            continue

        if len(matches) == 1:
            body = f"{matches[0]} is on the menu today!"
        else:
            body = f"{len(matches)} of your favorites are on the menu today: " + ", ".join(matches[:3])
            if len(matches) > 3:
                body += "…"

        payload = json.dumps({"title": "DC Menus", "body": body})
        sub_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        try:
            webpush(
                subscription_info=sub_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE,
                vapid_claims={"sub": VAPID_SUBJECT},
            )
            sent += 1
        except WebPushException as e:
            # 404/410 means the subscription is dead — remove it
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                sb_delete("subscriptions", "id", sub["id"])
            else:
                print(f"push failed for one sub: {e}", file=sys.stderr)

    print(f"Sent {sent} notification(s) to {len(subscriptions)} subscriber(s).")


if __name__ == "__main__":
    main()
