"""Refresh assets/loot_prices.json from MeowDB Etc NPC sell-back prices.

Source: https://meowdb.com/msclassic/api/items?type=Etc
Price field: stats.price (same as npcSellBack.price on item detail pages).
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "loot_prices.json"
BASE = "https://meowdb.com/msclassic/api/items"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

SPOT_CHECK = (
    "Evil Eye Tail",
    "Curse Eye Tail",
    "Lorang Claw",
    "Tablecloth",
    "Charm of the Undead",  # Jr. Wraith / Wraith etc
    "Jr. Necki Skin",
    "Pig's Ribbon",
)


def get_json(url: str, retries: int = 4):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(0.8 * (i + 1))
    raise last


def parse_price(stats) -> int | None:
    if stats is None:
        return None
    if isinstance(stats, str):
        try:
            stats = json.loads(stats)
        except Exception:
            return None
    if not isinstance(stats, dict):
        return None
    price = stats.get("price")
    if type(price) is int and price >= 0:
        return price
    if isinstance(price, str) and price.isdigit():
        return int(price)
    return None


def fetch_all_etc(page_size: int = 100) -> list[dict]:
    items = []
    page = 1
    while True:
        q = urllib.parse.urlencode({"type": "Etc", "limit": page_size, "page": page})
        data = get_json(f"{BASE}?{q}")
        batch = data.get("items") or []
        # Keep only rows that are actually Etc (API has miscounted totals before).
        batch = [it for it in batch if (it.get("type") or "").lower() == "etc"]
        items.extend(batch)
        print(
            f"page {page}: +{len(batch)} (running {len(items)}; "
            f"hasMore={data.get('hasMore')} total={data.get('total')})",
            flush=True,
        )
        if not batch or not data.get("hasMore"):
            break
        page += 1
        if page > 50:
            break
        time.sleep(0.15)
    return items


def main():
    rows = fetch_all_etc()
    priced = {}
    skipped = 0
    for row in rows:
        name = row.get("name") or row.get("displayName")
        price = parse_price(row.get("stats"))
        if not isinstance(name, str) or not name.strip():
            skipped += 1
            continue
        if price is None or price <= 0:
            skipped += 1
            continue
        priced[name.strip()] = price

    items = {k: priced[k] for k in sorted(priced, key=str.lower)}
    out = {
        "about": (
            "NPC sell-back prices (mesos) for Etc / common drops counted into notice-mode etc value. "
            "Synced from meowdb.com/msclassic (stats.price / npcSellBack). Potions and food use half "
            "their shop buy price from potion_table.json instead. Unpriced names are listed in the "
            "tracker, not guessed."
        ),
        "source": "https://meowdb.com/msclassic/item-db",
        "items": items,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(items)} priced etc items to {OUT} (skipped {skipped})")
    for want in SPOT_CHECK:
        print(f"  {want}: {items.get(want, 'MISSING')}")


if __name__ == "__main__":
    main()
