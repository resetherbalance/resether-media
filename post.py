"""Publishes approved, due items from schedule.json to Instagram via the official Graph API.

Env: META_TOKEN (GitHub secret). Optional: DRY_RUN=1 (build containers, never publish), ONLY=<item id>.
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse

API = 'https://graph.facebook.com/v23.0'
TOKEN = os.environ['META_TOKEN'].strip()
DRY = os.environ.get('DRY_RUN') == '1'
ONLY = os.environ.get('ONLY', '').strip()

S = json.load(open('schedule.json'))
POSTED = json.load(open('posted.json'))
IG = S['ig_user_id']
BASE = S['media_base']


def call(method, path, params=None, data=None, headers=None, url=None):
    params = dict(params or {})
    params['access_token'] = TOKEN
    u = url or f'{API}/{path}'
    body = None
    if method == 'GET':
        u += '?' + urllib.parse.urlencode(params)
    elif data is None:
        body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(u, data=body if data is None else data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        raise SystemExit(f'API error on {path}: {e.read().decode()[:600]}')


def wait_ready(cid, tries=60):
    for _ in range(tries):
        st = call('GET', cid, {'fields': 'status_code,status'})
        if st.get('status_code') == 'FINISHED':
            return
        if st.get('status_code') in ('ERROR', 'EXPIRED'):
            raise SystemExit(f'Container {cid} failed: {st}')
        time.sleep(10)
    raise SystemExit(f'Container {cid} not ready in time')


def build(item):
    t = item['type']
    if t == 'CAROUSEL':
        kids = []
        for f in item['files']:
            k = call('POST', f'{IG}/media', {'image_url': BASE + f, 'is_carousel_item': 'true'})['id']
            kids.append(k)
        for k in kids:
            wait_ready(k)
        cid = call('POST', f'{IG}/media', {'media_type': 'CAROUSEL', 'children': ','.join(kids), 'caption': item['caption']})['id']
    elif t == 'IMAGE':
        cid = call('POST', f'{IG}/media', {'image_url': BASE + item['file'], 'caption': item['caption']})['id']
    elif t == 'STORY':
        cid = call('POST', f'{IG}/media', {'image_url': BASE + item['file'], 'media_type': 'STORIES'})['id']
    elif t == 'REELS':
        p = {'media_type': 'REELS', 'upload_type': 'resumable', 'caption': item['caption'], 'share_to_feed': 'true'}
        if item.get('cover'):
            p['cover_url'] = BASE + item['cover']
        if item.get('trial'):
            p['trial_params'] = json.dumps({'graduation_strategy': 'SS_PERFORMANCE'})
        r = call('POST', f'{IG}/media', p)
        cid = r['id']
        path = os.path.join('media', item['file'])
        blob = open(path, 'rb').read()
        req = urllib.request.Request(r['uri'], data=blob, method='POST', headers={
            'Authorization': f'OAuth {TOKEN}', 'offset': '0', 'file_size': str(len(blob))})
        with urllib.request.urlopen(req, timeout=600) as up:
            print('upload:', up.read()[:200])
    else:
        raise SystemExit(f'Unknown type {t}')
    wait_ready(cid)
    return cid


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    done_any = False
    for item in S['items']:
        iid = item['id']
        if ONLY and iid != ONLY:
            continue
        if iid in POSTED:
            continue
        if not item.get('approved') and not (DRY and ONLY):
            print(f'skip {iid}: not approved')
            continue
        when = datetime.datetime.fromisoformat(item['when_utc'].replace('Z', '+00:00'))
        if not ONLY and when > now:
            continue
        if not ONLY and (now - when).total_seconds() > 6 * 3600:
            print(f'skip {iid}: more than 6 hours late, needs a human decision')
            continue
        print(f'building {iid} ({item["type"]})')
        cid = build(item)
        if DRY:
            print(f'DRY RUN ok: {iid} container {cid} is ready, not published')
            continue
        pub = call('POST', f'{IG}/media_publish', {'creation_id': cid})
        POSTED[iid] = {'media_id': pub.get('id'), 'published_utc': now.isoformat()}
        json.dump(POSTED, open('posted.json', 'w'), indent=1)
        print(f'PUBLISHED {iid}: {pub}')
        done_any = True
        break  # one post per run, so posts never pile up together
    if not done_any and not ONLY and not DRY and not os.environ.get('NO_WAIT'):
        # GitHub's timer fires only every 40 to 60 minutes. If a post is due within
        # the next 55 minutes, wait for it here so it goes out on time.
        now = datetime.datetime.now(datetime.timezone.utc)
        upcoming = []
        for item in S['items']:
            if item['id'] in POSTED or not item.get('approved'):
                continue
            when = datetime.datetime.fromisoformat(item['when_utc'].replace('Z', '+00:00'))
            wait = (when - now).total_seconds()
            if 0 < wait <= 55 * 60:
                upcoming.append((wait, item['id']))
        if upcoming:
            wait, iid = min(upcoming)
            print(f'waiting {int(wait)}s for {iid}')
            time.sleep(wait + 5)
            os.environ['NO_WAIT'] = '1'
            return main()
        print('nothing published this run')


if __name__ == '__main__':
    main()
