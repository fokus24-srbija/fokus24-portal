import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

FILE = Path(__file__).resolve().parent.parent / 'news.json'
FEEDS = {
    'RTS': 'https://www.rts.rs/vesti/rss.html',
    'N1': 'https://n1info.rs/feed/',
    'Danas': 'https://www.danas.rs/feed/',
    'Blic': 'https://www.blic.rs/rss/danasnje-vesti',
    'Nova.rs': 'https://nova.rs/feed/',
    'Telegraf': 'https://www.telegraf.rs/rss',
    'Kurir': 'https://www.kurir.rs/rss',
    'Novosti': 'https://www.novosti.rs/rss/57%7C25%7C49%7C56%7C33%7C19%7C34%7C20%7C18%7C32%7C58%7C45%7C16%7C31%7C50%7C5%7C1%7C3%7C26%7C52%7C2%7C6%7C55%7C35%7C4%7C9%7C8%7C7%7C51%7C12%7C47%7C46%7C30%7C53%7C14%7C13%7C11%7C15%7C10%7C48%7C36%7C54%7C61-Sve%20vesti',
    'Politika': 'https://www.politika.rs/rss',
}


def category(title):
    s = title.casefold()
    if any(w in s for w in ('uhap', 'hapšen', 'hapsen', 'pritvor', 'tužila', 'tuzila', 'policij', 'istrag', 'optuž', 'optuz', 'ubist', 'nesreć', 'nesrec', 'požar', 'pozar', 'sud')):
        return 'Hronika'
    if any(w in s for w in ('fudbal', 'košark', 'kosark', 'tenis', 'đoković', 'djokovic', 'jokić', 'jokic', 'zvezd', 'partizan', 'utakmic', 'liga šampion', 'olimpij', 'sport')):
        return 'Sport'
    if any(w in s for w in ('pevač', 'pevac', 'pevačic', 'muzik', 'film', 'serij', 'koncert', 'estrad', 'glum', 'festival', 'rijaliti')):
        return 'Zabava'
    if any(w in s for w in ('privred', 'ekonom', 'inflacij', 'plat', 'penzij', 'budžet', 'budzet', 'investic', 'bank', 'cen', 'berz', 'porez', 'evr', 'dinara')):
        return 'Ekonomija'
    if any(w in s for w in ('vlada', 'predsednik', 'skupštin', 'skupstin', 'izbor', 'ministar', 'strank', 'opozicij', 'protest', 'studentsk', 'poslanik', 'politi')):
        return 'Politika'
    return 'Društvo'


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()


def get_text(node, names):
    for name in names:
        v = node.findtext(name)
        if v:
            return v
    return ''


def safe_xml(data):
    """Repair invalid XML control characters and unescaped ampersands."""
    # XML feeds are expected to be UTF-8; preserve XML declaration for standard parser.
    text = data.decode('utf-8-sig', errors='replace')
    # HTML pages are not RSS feeds; do not invent articles from them.
    if re.search(r'<!doctype\s+html|<html(?:\s|>)', text[:1500], flags=re.I):
        return ''
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]', '', text)
    text = re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|[a-zA-Z][a-zA-Z0-9._:-]*;)', '&amp;', text)
    return text


def parse_entries(data):
    text = safe_xml(data)
    if not text:
        return [], 'adresa vraća HTML stranicu umesto RSS-a'
    try:
        root = ET.fromstring(text)
        entries = root.findall('.//item') or root.findall('{http://www.w3.org/2005/Atom}entry')
        if entries:
            return entries, 'XML'
    except ET.ParseError as exc:
        print(f'  XML nije potpuno ispravan ({exc}); pokušavam oporavak pojedinačnih stavki')
    # A broken item must not invalidate the entire feed. Parse RSS items separately.
    entries = []
    for raw in re.findall(r'<item(?:\s[^>]*)?>.*?</item\s*>', text, flags=re.I | re.S):
        try:
            entries.append(ET.fromstring(raw))
        except ET.ParseError:
            # Some providers include undeclared namespace prefixes inside an item.
            # Drop only invalid item rather than inventing data.
            continue
    if entries:
        return entries, 'oporavljeno'
    return [], 'nema čitljivih stavki'


def main():
    now = dt.datetime.now(dt.timezone.utc)
    try:
        old = json.loads(FILE.read_text(encoding='utf-8')).get('articles', [])
    except (OSError, ValueError):
        old = []
    items = {x['id']: x for x in old if isinstance(x, dict) and x.get('id')}
    success, added = 0, 0
    for source, url in FEEDS.items():
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 TRAG24News/1.0',
                'Accept': 'application/rss+xml,application/atom+xml,application/xml,text/xml,*/*',
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read(2_000_000)
            entries, mode = parse_entries(data)
            if not entries:
                print(f'{source}: nema čitljivih RSS/Atom stavki ({mode}); proveriti zvaničnu RSS adresu')
                continue
            success += 1
            count = 0
            for entry in entries:
                title = clean(get_text(entry, ('title', '{http://www.w3.org/2005/Atom}title')))
                link = get_text(entry, ('link',))
                if not link:
                    atomlink = entry.find('{http://www.w3.org/2005/Atom}link')
                    link = atomlink.get('href', '') if atomlink is not None else ''
                link = link.strip()
                rawdate = get_text(entry, ('pubDate', '{http://www.w3.org/2005/Atom}published', '{http://www.w3.org/2005/Atom}updated'))
                if not title or not link.startswith('https://') or not urlparse(link).hostname or not rawdate:
                    continue
                try:
                    date = email.utils.parsedate_to_datetime(rawdate)
                except (TypeError, ValueError):
                    try:
                        date = dt.datetime.fromisoformat(rawdate.replace('Z', '+00:00'))
                    except ValueError:
                        continue
                if date.tzinfo is None:
                    date = date.replace(tzinfo=dt.timezone.utc)
                date = date.astimezone(dt.timezone.utc)
                if not now - dt.timedelta(days=3) <= date <= now + dt.timedelta(hours=2):
                    continue
                uid = hashlib.sha256(link.encode()).hexdigest()[:20]
                if uid in items:
                    continue
                items[uid] = {
                    'id': uid, 'title': title[:220],
                    'summary': f'Prema objavi medija {source}: {title[:240]}. Navodi nisu nezavisno potvrđeni od strane TRAG 24.',
                    'category': category(title), 'source': source, 'source_url': link,
                    'published_at': date.isoformat(timespec='minutes'),
                    'verification_status': 'preneto_iz_izvora',
                }
                added += 1
                count += 1
            print(f'{source}: učitano ({mode}), dodato {count}')
        except (OSError, ValueError, ET.ParseError) as exc:
            print(f'{source}: greška: {exc}')
    if not success:
        print('Nijedan izvor nije uspešno učitan; postojeće vesti ostaju netaknute.')
        return
    for x in items.values():
        if isinstance(x.get('summary'), str):
            x['summary'] = x['summary'].replace('FOKUS 24', 'TRAG 24')
        if x.get('category') == 'Hapšenja i istrage':
            x['category'] = 'Hronika'
        elif x.get('category') == 'Opozicija':
            x['category'] = 'Politika'
        elif x.get('category') == 'Alta banka':
            x['category'] = 'Ekonomija'
    articles = sorted(items.values(), key=lambda x: x.get('published_at', ''), reverse=True)[:300]
    FILE.write_text(json.dumps({'updated_at': now.isoformat(), 'articles': articles}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Ukupno dodato {added}; sačuvano {len(articles)} vesti.')


if __name__ == '__main__':
    main()
