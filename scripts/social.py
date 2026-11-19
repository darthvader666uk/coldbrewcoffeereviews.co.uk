"""Share new reviews on social media, and send a daily digest of replies.

  python scripts/social.py announce <post file>... [--dry-run]
  python scripts/social.py archive scripts/archive.txt [--dry-run]   (posts whatever is due and not shared yet)
  python scripts/social.py digest [--dry-run]

Credentials come from environment variables (GitHub secrets):
  META_PAGE_TOKEN, META_PAGE_ID, META_IG_ID, BSKY_HANDLE, BSKY_APP_PASSWORD, NTFY_TOPIC

The repo is public, so its Action logs are too. Never print tokens, comment text or messages:
logs only ever show counts and post links.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SITE = 'https://www.lastshiftcoffee.co.uk'
GRAPH = 'https://graph.facebook.com'
BSKY = 'https://bsky.social/xrpc'
HASHTAGS = '#coldbrew #coldbrewcoffee #coffeereview #icedcoffee #specialtycoffee #ukcoffee'
DRY = '--dry-run' in sys.argv
ENV = os.environ.get


# --- helpers -------------------------------------------------------------------------------

def http(method, url, data=None, headers=None, raw=None):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    h = {'User-Agent': 'last-shift-coffee/1.0'}
    if data is not None:
        h['Content-Type'] = 'application/json'
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read()
    except urllib.error.HTTPError as e:
        text = e.read()
        try:
            err = json.loads(text)
        except ValueError:
            err = {}
        msg = (err.get('error') or {}).get('message') if isinstance(err.get('error'), dict) else err.get('message')
        raise RuntimeError(f'{e.code} {msg or "error"}') from None
    return json.loads(text) if text else {}


def graph(method, path, **params):
    params['access_token'] = ENV('META_PAGE_TOKEN')
    q = urllib.parse.urlencode(params)
    if method == 'GET':
        return http('GET', f'{GRAPH}/{path}?{q}')
    return http('POST', f'{GRAPH}/{path}', raw=q.encode(),
                headers={'Content-Type': 'application/x-www-form-urlencoded'})


def front_matter(path):
    text = open(path, encoding='utf-8').read()
    fm = text.split('---', 2)[1]
    meta = {}
    for line in fm.splitlines():
        m = re.match(r'^(\w+):\s*(.*)$', line)
        if m:
            meta[m.group(1)] = m.group(2).strip().strip('"\'')
    name = os.path.basename(path)
    if 'permalink' in meta:
        meta['url'] = SITE + meta['permalink']
    else:
        y, mo, _, slug = name.split('-', 3)
        meta['url'] = f'{SITE}/{y}/{mo}/{os.path.splitext(slug)[0]}.html'
    meta['image_url'] = SITE + meta['image'] if meta.get('image', '').startswith('/') else meta.get('image', '')
    meta['title'] = re.sub(r'\s+Review$', '', meta.get('title', ''))
    return meta


def beans(rating):
    return '🫘' * int(rating or 0) + f' {rating}/5' if rating else ''


def since(hours=24):
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)


def parse_time(s):
    s = s.replace('Z', '+00:00')
    if re.search(r'[+-]\d{4}$', s):
        s = s[:-2] + ':' + s[-2:]
    return dt.datetime.fromisoformat(s)


def wait_until_live(url, minutes=15):
    for _ in range(minutes * 4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'last-shift-coffee/1.0'})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(15)
    return False


# --- announce ------------------------------------------------------------------------------

def bluesky_session():
    return http('POST', f'{BSKY}/com.atproto.server.createSession',
                {'identifier': ENV('BSKY_HANDLE'), 'password': ENV('BSKY_APP_PASSWORD')})


def post_bluesky(p):
    imgs = social_images(p)
    if len(imgs) > 1:   # photo post: up to 4 images (cover + the last 3, usually the brew), link in the text
        imgs = imgs if len(imgs) <= 4 else imgs[:1] + imgs[-3:]
        link = p['url'].removeprefix('https://www.')
        desc = re.sub(r'\s*Scores \d beans out of 5\.$', '', p.get('description', ''))   # the beans line says it
        head, tail = f"{p['lead']}: {p['title']}", f"{beans(p.get('rating'))}\n\n{link}"
        room = 300 - len(head) - len(tail) - 4
        if len(desc) > room:
            desc = desc[:room - 3].rsplit(' ', 1)[0] + '...'
        text = '\n\n'.join(x for x in (head, desc, tail) if x)
    else:
        text = f"{p['lead']}: {p['title']}\n\n{beans(p.get('rating'))}".strip()
        if len(text) > 280:
            text = text[:277] + '...'
    if DRY:
        return print(f'  bluesky (dry run, {f"{len(imgs)} images" if len(imgs) > 1 else "link card"}):', text.replace('\n', ' | '))
    s = bluesky_session()
    auth = {'Authorization': f"Bearer {s['accessJwt']}"}
    record = {'$type': 'app.bsky.feed.post', 'text': text, 'langs': ['en'],
              'createdAt': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')}
    if len(imgs) > 1:
        images = []
        for i, u in enumerate(imgs, 1):
            img = open(u.removeprefix(SITE + '/'), 'rb').read()   # the slides are in the checkout
            blob = http('POST', f'{BSKY}/com.atproto.repo.uploadBlob', raw=img, headers={**auth, 'Content-Type': 'image/jpeg'})
            images.append({'image': blob['blob'], 'alt': f"{p['title']}, photo {i} of {len(imgs)}"})
        end = len(text.encode())
        record['facets'] = [{'index': {'byteStart': end - len(link.encode()), 'byteEnd': end},
                             'features': [{'$type': 'app.bsky.richtext.facet#link', 'uri': p['url']}]}]
        record['embed'] = {'$type': 'app.bsky.embed.images', 'images': images}
    else:
        external = {'uri': p['url'], 'title': p['title'], 'description': p.get('description', '')}
        if p['image_url']:
            with urllib.request.urlopen(urllib.request.Request(p['image_url'], headers={'User-Agent': 'last-shift-coffee/1.0'})) as r:
                img, mime = r.read(), r.headers.get_content_type()   # drops covers are Shopify URLs ending in ?width=
            if len(img) < 1_000_000:
                blob = http('POST', f'{BSKY}/com.atproto.repo.uploadBlob', raw=img, headers={**auth, 'Content-Type': mime})
                external['thumb'] = blob['blob']
        record['embed'] = {'$type': 'app.bsky.embed.external', 'external': external}
    r = http('POST', f'{BSKY}/com.atproto.repo.createRecord',
             {'repo': s['did'], 'collection': 'app.bsky.feed.post', 'record': record}, headers=auth)
    url = 'https://bsky.app/profile/' + s['handle'] + '/post/' + r['uri'].rsplit('/', 1)[1]
    print('  bluesky: posted', url)
    return url


def post_facebook(p):
    imgs = social_images(p)
    message = f"{p['lead']}: {p['title']}\n\n{p.get('description', '')}\n\n{beans(p.get('rating'))}".strip()
    if len(imgs) > 1:   # multi-photo post, the link goes in the text (a link card can't sit with photos)
        message += f"\n\nFull review: {p['url']}"
    if DRY:
        return print(f'  facebook (dry run, {f"{len(imgs)} images" if len(imgs) > 1 else "link card"}):', message.replace('\n', ' | '))
    page = ENV('META_PAGE_ID')
    if len(imgs) > 1:
        ids = [graph('POST', f'{page}/photos', url=u, published='false')['id'] for u in imgs]
        r = graph('POST', f'{page}/feed', message=message,
                  **{f'attached_media[{i}]': json.dumps({'media_fbid': x}) for i, x in enumerate(ids)})
    else:
        r = graph('POST', f'{page}/feed', message=message, link=p['url'])
    url = graph('GET', r['id'], fields='permalink_url').get('permalink_url')
    print('  facebook: posted', url)
    return url


def social_images(p):
    """Social slides: every JPEG in the post's `social:` folder (4:5, 1080x1350), else the main image."""
    d = p.get('social', '').strip('/')
    files = sorted(f for f in os.listdir(d) if f.lower().endswith(('.jpg', '.jpeg'))) if d and os.path.isdir(d) else []
    return [f'{SITE}/{d}/{f}' for f in files][:20] or [p['image_url']]


def post_instagram(p):
    imgs = social_images(p)
    if not all(u.lower().endswith(('.jpg', '.jpeg')) for u in imgs):
        return print('  instagram: skipped, Instagram only accepts JPEG and the main image is', imgs[0].rsplit('.', 1)[-1])
    caption = (f"{p['lead']}: {p['title']}\n\n{p.get('description', '')}\n\n{beans(p.get('rating'))}\n\n"
               f"Full review at lastshiftcoffee.co.uk\n\n{HASHTAGS}")
    if DRY:
        return print(f'  instagram (dry run, {len(imgs)} image(s)):', caption.replace('\n', ' | ')[:200])
    ig = ENV('META_IG_ID')

    def container(**params):
        c = graph('POST', f'{ig}/media', **params)
        for _ in range(20):
            if graph('GET', c['id'], fields='status_code').get('status_code') == 'FINISHED':
                break
            time.sleep(5)
        return c['id']

    if len(imgs) == 1:
        cid = container(image_url=imgs[0], caption=caption, alt_text=p['title'])
    else:   # carousel: caption on the parent only, alt text on each slide
        kids = [container(image_url=u, is_carousel_item='true', alt_text=f"{p['title']}, photo {i} of {len(imgs)}")
                for i, u in enumerate(imgs, 1)]
        cid = container(media_type='CAROUSEL', children=','.join(kids), caption=caption)
    r = graph('POST', f'{ig}/media_publish', creation_id=cid)
    url = graph('GET', r['id'], fields='permalink').get('permalink')
    print('  instagram: posted', url)
    return url


def record_links(path, links):
    """Save the post links in the review's front matter (the layout lists them at the bottom).
    Links already there are kept, so an archive re-share never replaces the first post."""
    text = open(path, encoding='utf-8').read()
    _, fm, body = text.split('---', 2)
    add = ''.join(f'{k}_post: {v}\n' for k, v in links.items() if v and not re.search(rf'^{k}_post:', fm, re.M))
    if add and not DRY:
        open(path, 'w', encoding='utf-8').write(f'---{fm.rstrip()}\n{add}---{body}')


def announce(files, archive=False):
    failed = []
    for f in files:
        f = f.strip().strip('`\'"').rstrip('.,')
        p = front_matter(f)
        p['lead'] = f'From the archive ({os.path.basename(f)[:4]})' if archive else 'New review'
        drops = p.get('method') == 'Coffee Drops'
        if drops:   # weekly roundup: no Instagram, its only image is a roaster's product photo
            p['lead'], p['title'] = "This week's coffee drops", p['title'].removeprefix('Coffee Drops: ')
        print('Announcing', p['url'])
        if not DRY and not wait_until_live(p['url']):
            failed.append(f'{f}: page never went live')
            continue
        links = {}
        for name, fn in [('bluesky', post_bluesky), ('facebook', post_facebook), ('instagram', post_instagram)][:2 if drops else 3]:
            try:
                links[name] = fn(p)
            except Exception as e:
                print(f'  {name}: FAILED', e)
                failed.append(f'{name}: {e}')
        record_links(f, links)
    if failed:
        notify('Last Shift Coffee: sharing failed', '\n'.join(failed), SITE)
        sys.exit(1)


# --- digest --------------------------------------------------------------------------------

def digest_instagram(cut):
    lines, n = [], 0
    ig = ENV('META_IG_ID')
    media = graph('GET', f'{ig}/media', fields='id,permalink,comments_count', limit=25).get('data', [])
    for m in media:
        if not m.get('comments_count'):
            continue
        comments = graph('GET', f"{m['id']}/comments", fields='username,timestamp', limit=50).get('data', [])
        who = [c['username'] for c in comments if parse_time(c['timestamp']) >= cut]
        if who:
            n += len(who)
            lines.append(f"Instagram: {len(who)} comment(s) from {', '.join(sorted(set(who)))} {m['permalink']}")
    try:
        convos = graph('GET', f"{ENV('META_PAGE_ID')}/conversations", platform='instagram',
                       fields='updated_time,participants', limit=25).get('data', [])
        new = [c for c in convos if parse_time(c['updated_time']) >= cut]
        if new:
            n += len(new)
            lines.append(f'Instagram: {len(new)} message thread(s) updated https://www.instagram.com/direct/inbox/')
    except RuntimeError as e:
        if 'disabled access' not in str(e):
            raise
    return n, lines


def digest_facebook(cut):
    lines, n = [], 0
    posts = graph('GET', f"{ENV('META_PAGE_ID')}/feed", fields='permalink_url,comments.limit(50){from,created_time}',
                  limit=25).get('data', [])
    for p in posts:
        comments = (p.get('comments') or {}).get('data', [])
        who = [(c.get('from') or {}).get('name', 'someone') for c in comments if parse_time(c['created_time']) >= cut]
        if who:
            n += len(who)
            lines.append(f"Facebook: {len(who)} comment(s) from {', '.join(sorted(set(who)))} {p.get('permalink_url', '')}")
    return n, lines


def digest_bluesky(cut):
    s = bluesky_session()
    notes = http('GET', f'{BSKY}/app.bsky.notification.listNotifications?limit=100',
                 headers={'Authorization': f"Bearer {s['accessJwt']}"}).get('notifications', [])
    new = [x for x in notes if parse_time(x['indexedAt']) >= cut]
    counts = {}
    for x in new:
        counts[x['reason']] = counts.get(x['reason'], 0) + 1
    if not counts:
        return 0, []
    talk = sum(counts.get(k, 0) for k in ('reply', 'mention', 'quote'))
    summary = ', '.join(f'{v} {k}' for k, v in sorted(counts.items()))
    return talk, [f'Bluesky: {summary} https://bsky.app/notifications']


def notify(title, body, click):
    topic = ENV('NTFY_TOPIC')
    if DRY or not topic:
        return print('ntfy (not sent):', title, '|', body.replace('\n', ' | '))
    http('POST', f'https://ntfy.sh/{topic}', raw=body.encode(),
         headers={'Title': title.encode('ascii', 'ignore').decode(), 'Click': click, 'Tags': 'coffee'})


def digest():
    cut = since(24)
    lines, total, problems = [], 0, []
    for name, fn in [('Instagram', digest_instagram), ('Facebook', digest_facebook), ('Bluesky', digest_bluesky)]:
        try:
            n, l = fn(cut)
            total += n
            lines += l
            print(f'{name}: {len(l)} line(s)')
        except Exception as e:
            print(f'{name}: FAILED', e)
            problems.append(f'{name} check failed: {e}')
    if lines or problems:
        title = f'Last Shift Coffee: {total} new comment(s) or message(s)' if total else 'Last Shift Coffee: new activity'
        notify(title, '\n'.join(problems + lines), 'https://www.instagram.com/lastshiftcoffee/')
    else:
        print('Nothing new, no notification sent.')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if a != '--dry-run']
    if args[:1] == ['announce']:
        announce(args[1:])
    elif args[:1] == ['archive']:
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        # Due today or overdue (GitHub sometimes runs the 18:00 job after midnight), and not shared yet:
        # a shared post has its links saved in the front matter.
        due = [f for d, f in (line.split()[:2] for line in open(args[1]) if re.match(r'\d{4}-\d{2}-\d{2} ', line))
               if d <= today and not re.search(r'^\w+_post:', open(f, encoding='utf-8').read().split('---', 2)[1], re.M)]
        if due:
            announce(due, archive=True)
        else:
            print('Nothing due in the archive list on', today)
    elif args[:1] == ['digest']:
        digest()
    else:
        sys.exit(__doc__)
