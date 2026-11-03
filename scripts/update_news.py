import datetime as dt
import email.utils
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

FILE = Path(__file__).resolve().parent.parent / "news.json"
FEEDS = {
    "RTS": "https://www.rts.rs/rss/vesti.html",
    "N1": "https://n1info.rs/feed/",
    "Danas": "https://www.danas.rs/feed/"
}

def category(title):
    s = title.casefold()
    if "alta bank" in s:
        return "Alta banka"
    if any(w in s for w in ("uhap", "hapšen", "hapsen", "pritvor", "tužila", "tuzila", "policij", "istrag", "optuž", "optuz")):
        return "Hapšenja i istrage"
    if any(w in s for w in ("opozicij", "studentsk", "protest")):
        return "Opozicija"
    if any(w in s for w in ("vlada", "predsednik", "skupštin", "skupstin", "izbor", "ministar", "strank")):
        return "Politika"
    if any(w in s for w in ("privred", "ekonom", "inflacij", "plate", "budžet", "budzet", "investic", "bank", "cene")):
        return "Ekonomija"
    return None

def main():
    now = dt.datetime.now(dt.timezone.utc)
    try:
        old = json.loads(FILE.read_text(encoding="utf-8")).get("articles", [])
    except (OSError, ValueError):
        old = []
    items = {x["id"]: x for x in old if isinstance(x, dict) and x.get("id")}
    success = 0
    added = 0
    for source, url in FEEDS.items():
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Fokus24RSS/1.0"})
            with urllib.request.urlopen(request, timeout=18) as response:
                root = ET.fromstring(response.read(2000000))
            success += 1
            for entry in root.findall(".//item"):
                title = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", entry.findtext("title") or "")).strip()
                link = (entry.findtext("link") or "").strip()
                date_text = entry.findtext("pubDate")
                if not title or not link.startswith("https://") or not urlparse(link).hostname or not date_text:
                    continue
                try:
                    date = email.utils.parsedate_to_datetime(date_text)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=dt.timezone.utc)
                    date = date.astimezone(dt.timezone.utc)
                except (TypeError, ValueError, IndexError):
                    continue
                if date > now + dt.timedelta(hours=2) or date < now - dt.timedelta(days=3):
                    continue
                group = category(title)
                if not group:
                    continue
                uid = hashlib.sha256(link.encode()).hexdigest()[:20]
                if uid in items:
                    continue
                items[uid] = {
                    "id": uid,
                    "title": title[:220],
                    "summary": f"Prema objavi medija {source}: {title[:240]}. Navodi nisu nezavisno potvrđeni od strane FOKUS 24.",
                    "category": group,
                    "source": source,
                    "source_url": link,
                    "published_at": date.isoformat(timespec="minutes"),
                    "verification_status": "preneto_iz_izvora"
                }
                added += 1
        except (OSError, ValueError, ET.ParseError) as error:
            print(f"{source}: {error}")
    if not success or not added:
        print("Nema novih vesti za objavljivanje.")
        return
    articles = sorted(items.values(), key=lambda x: x.get("published_at", ""), reverse=True)[:300]
    FILE.write_text(json.dumps({"updated_at": now.isoformat(), "articles": articles}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Dodato {added} vesti.")

if __name__ == "__main__":
    main()
