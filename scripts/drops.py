"""Last Shift Coffee Drops: new coffees and restocks from UK roasters.

  python scripts/drops.py check [--state FILE] [--dry-run]   (hourly: record drops, alert Discord)
  python scripts/drops.py roundup [--state FILE] [--dry-run] (Friday: write the week's post,
                                                             run again after the push to announce it)

Roasters come from _data/roasters.yml, read through Shopify's public /products.json.
State (seen products, their stock, the last 30 days of drops) lives in a JSON file that is
NOT kept on master. A roaster's first check only records what is listed, it never alerts.

Credentials come from environment variables (GitHub secrets):
  DISCORD_INSTANT_WEBHOOK (paid #instant-drops), DISCORD_WEEKLY_WEBHOOK (free #weekly-drops)

Be polite: one store at a time, a pause between every request, and a 429 skips the store
until the next run. Never print webhook URLs.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'https://www.lastshiftcoffee.co.uk'
UA = 'LastShiftCoffeeDropsBot/0.1 (+https://www.lastshiftcoffee.co.uk/drops/)'
PAUSE = 30          # seconds between requests. Shopify rate-limits per IP across ALL its stores
MAX_PAGES = 4       # 1,000 products is plenty for any roaster
KEEP_DAYS = 30
DRY = '--dry-run' in sys.argv
ENV = os.environ.get

# Checked against the product type and title only: tags often carry tasting notes ("chocolate").
NOT_COFFEE = re.compile(
    r'gift|voucher|\bcards?\b|subscri|merch|equipment|brewer|brewing|grinder|kettle|\bscales?\b|'
    r'\bmugs?\b|keepcup|glass|tote|shirt|hoodie|\bhat\b|\bcap\b|apron|paper|dripper|v60|aeropress|'
    r'chemex|cafeti|french press|moka|machine|tamper|\bjug\b|pitcher|cleaning|descal|\bbook\b|'
    r'\btea\b|hot choc|syrup|capsule|\bpods?\b|bundle|sample|taster|training|course',
    re.I)
COFFEE = re.compile(r'coffee|bean|espresso|filter|blend|single origin|decaf|roast', re.I)
WEIGHT = re.compile(r'\b\d+(\.\d+)?\s?(g|kg)\b', re.I)


# --- helpers -------------------------------------------------------------------------------

def roasters():
    """Tiny reader for _data/roasters.yml (a list of name/url pairs), so no PyYAML needed."""
    out = []
    for line in open(os.path.join(ROOT, '_data', 'roasters.yml'), encoding='utf-8'):
        m = re.match(r'\s*-?\s*(name|url):\s*(.+?)\s*$', line)
        if m and m.group(1) == 'name':
            out.append({'name': m.group(2)})
        elif m:
            out[-1]['url'] = m.group(2).rstrip('/')
    return out


def fetch(base):
    """All products for one store, or None if the store refused or failed (state untouched)."""
    products = []
    for page in range(1, MAX_PAGES + 1):
        req = urllib.request.Request(f'{base}/products.json?limit=250&page={page}',
                                     headers={'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                batch = json.load(r)['products']
        except (urllib.error.URLError, ValueError, KeyError) as e:
            print(f'  skipped: {getattr(e, "code", "") or e}')
            return None
        finally:
            time.sleep(PAUSE)
        products += batch
        if len(batch) < 250:
            break
    return products


def is_coffee(p):
    name = f"{p.get('product_type') or ''} {p['title']}"
    if NOT_COFFEE.search(name):
        return False
    tags = ' '.join(p.get('tags') or [])
    variants = ' '.join(v.get('title') or '' for v in p.get('variants', []))
    return bool(COFFEE.search(f'{name} {tags}') or WEIGHT.search(variants))


def in_stock(p):
    return sorted(v['id'] for v in p.get('variants', []) if v.get('available'))


def price(p):
    prices = [float(v['price']) for v in p.get('variants', []) if v.get('available') and v.get('price')]
    return f'£{min(prices):.2f}' if prices else ''


def load(path):
    try:
        return json.load(open(path, encoding='utf-8'))
    except FileNotFoundError:
        return {'stores': {}, 'drops': []}


def discord(env_name, text):
    hook = ENV(env_name)
    if DRY or not hook:
        print(f'  [{"dry run" if DRY else env_name + " not set"}] {text.splitlines()[0]}')
        return
    req = urllib.request.Request(hook, method='POST', headers={'User-Agent': 'DiscordBot (https://www.lastshiftcoffee.co.uk, 1.0)', 'Content-Type': 'application/json'},
                                 data=json.dumps({'content': text[:2000]}).encode())
    urllib.request.urlopen(req, timeout=30).close()
    time.sleep(1)   # Discord allows ~5 webhook posts per 2 seconds


# --- check: hourly ---------------------------------------------------------------------------

def check(state_path):
    state = load(state_path)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    found = []
    for r in roasters():
        print(r['name'])
        products = fetch(r['url'])
        if products is None:
            continue
        seen = state['stores'].get(r['url'])
        first = seen is None
        seen = seen or {}
        for p in filter(is_coffee, products):
            pid, stock = str(p['id']), in_stock(p)
            old = seen.get(pid)
            kind = None
            if not first and stock and old is None:
                kind = 'new'
            elif not first and stock and old is not None and not old['stock']:
                kind = 'restock'
            seen[pid] = {'title': p['title'], 'stock': stock}
            if kind:
                found.append({'kind': kind, 'roaster': r['name'], 'title': p['title'], 'price': price(p),
                              'url': f"{r['url']}/products/{p['handle']}", 'at': now})
        state['stores'][r['url']] = seen
        print(f'  {len(seen)} coffees{" (first check, recorded only)" if first else ""}')

    cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    state['drops'] = [d for d in state['drops'] if d['at'] >= cut] + found
    print(f'{len(found)} drops this run')
    if not DRY:   # saved before alerting: a Discord failure loses an alert, never repeats them all
        json.dump(state, open(state_path, 'w', encoding='utf-8'), indent=1)
    for d in found:
        label = 'New' if d['kind'] == 'new' else 'Back in stock'
        discord('DISCORD_INSTANT_WEBHOOK', f"**{label} from {d['roaster']}:** {d['title']} {d['price']}\n{d['url']}")


# --- roundup: Friday ---------------------------------------------------------------------------

def roundup(state_path):
    today = dt.date.today()
    cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    drops = [d for d in load(state_path)['drops'] if d['at'] >= cut and d['kind'] == 'new']
    if not drops:
        print('no new coffees this week, no post')
        return
    by_roaster = {}
    for d in drops:
        by_roaster.setdefault(d['roaster'], []).append(d)
    nice = f'{today.day} {today:%B %Y}'
    body = [f'<p>{len(drops)} new coffees from {len(by_roaster)} UK roasters this week. '
            'Every link goes straight to the roaster.</p>']
    for name, items in sorted(by_roaster.items()):
        body.append(f'\n<h3>{html.escape(name)}</h3>\n<ul>')
        body += [f'<li><a href="{html.escape(d["url"])}">{html.escape(d["title"])}</a> {d["price"]}</li>' for d in items]
        body.append('</ul>')
    body.append('\n<p>Want them the moment they land? <a href="/drops/">Join Last Shift Coffee Drops</a>.</p>')
    slug = f'coffee-drops-{today:%Y-%m-%d}'   # URLs are /:year/:month/:title.html, so the date keeps them unique
    post = '\n'.join([
        '---',
        f'title: "Coffee Drops: New UK Coffees, Week Ending {nice}"',
        'author: Stuart Nightingale',
        'method: Coffee Drops',
        'tags:\n- Drops',
        f'description: "{len(drops)} new coffees from {len(by_roaster)} UK speciality roasters this week."',
        '---', '', *body, ''])
    path = os.path.join(ROOT, '_posts', f'{today:%Y-%m-%d}-{slug}.html')
    url = f'{SITE}/{today:%Y/%m}/{slug}.html'
    if DRY:
        print(post)
    elif not os.path.exists(path):   # first call writes the post, the workflow commits it
        open(path, 'w', encoding='utf-8').write(post)
        print(f'wrote {path}')
        return
    else:                            # second call, after the push: announce once it is live
        for _ in range(30):
            try:
                urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=30).close()
                break
            except urllib.error.URLError:
                time.sleep(30)
        else:
            sys.exit(f'{url} still not live after 15 minutes, Discord not told')
    discord('DISCORD_WEEKLY_WEBHOOK', f'**This week\'s coffee drops:** {len(drops)} new coffees from '
                                      f'{len(by_roaster)} UK roasters\n{url}')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    state_path = args[args.index('--state') + 1] if '--state' in args else os.path.join(ROOT, 'drops-state.json')
    {'check': check, 'roundup': roundup}.get(args[0] if args else '', lambda _: sys.exit(__doc__))(state_path)
