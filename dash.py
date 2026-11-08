"""Builds the data files behind the ResetHer Command Centre dashboard.

Reads schedule.json, posted.json, research/latest.json and dashboard/manual/*.json,
pulls fresh Instagram insights with the official Graph API (env META_TOKEN), and
writes dashboard/*.json (rows the dashboard reads). Runs daily in GitHub Actions.
"""
import json, os, re, datetime as dt, statistics, urllib.request, urllib.parse
from zoneinfo import ZoneInfo

API = 'https://graph.facebook.com/v23.0'
TOKEN = os.environ.get('META_TOKEN', '').strip()
UK = ZoneInfo('Europe/London')
NOW = dt.datetime.now(dt.timezone.utc)
os.makedirs('dashboard', exist_ok=True)

S = json.load(open('schedule.json'))
IG = S['ig_user_id']
POSTED = json.load(open('posted.json'))


def get(path, **params):
    if not TOKEN:
        return {'error': 'no token'}
    params['access_token'] = TOKEN
    u = f'{API}/{path}?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(u, timeout=60) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        body = getattr(e, 'read', lambda: b'')()
        return {'error': (body.decode() if body else str(e))[:300]}


def write(name, rows):
    json.dump(rows, open(f'dashboard/{name}.json', 'w'), ensure_ascii=False, indent=1)
    print(name, len(rows), 'rows')


def first_sentence(text):
    text = (text or '').split('\n')[0].strip()
    m = re.match(r'(.+?[.?])(\s|$)', text)
    s = m.group(1) if m else text
    return s if len(s) <= 110 else s[:107].rstrip() + '...'


FORMAT = {'REELS': 'Reel', 'CAROUSEL': 'Carousel', 'IMAGE': 'Static', 'STORY': 'Story'}
METRICS = ['reach', 'views', 'likes', 'comments', 'saved', 'shares', 'follows', 'profile_visits', 'ig_reels_avg_watch_time']

# ---------- posts: every scheduled item with its status and insights ----------
prev = {}
if os.path.exists('dashboard/posts.json'):
    prev = {r['id']: r for r in json.load(open('dashboard/posts.json'))}

posts = []
for it in S['items']:
    when = dt.datetime.fromisoformat(it['when_utc'].replace('Z', '+00:00'))
    local = when.astimezone(UK)
    row = {
        'id': it['id'], 'date': local.strftime('%Y-%m-%d'), 'slot': local.strftime('%H:%M'),
        'weekday': local.strftime('%a'), 'format': FORMAT.get(it['type'], it['type'].title()),
        'title': first_sentence(it.get('caption', '')), 'batch': it.get('batch', 1),
        'approved': bool(it.get('approved')),
    }
    p = POSTED.get(it['id'])
    if p:
        pub = dt.datetime.fromisoformat(p['published_utc'])
        row['status'] = 'Posted'
        row['posted_at'] = pub.astimezone(UK).strftime('%Y-%m-%d %H:%M')
        row['minutes_late'] = max(0, round((pub - when).total_seconds() / 60))
        m = {}
        for metric in METRICS:
            r = get(f"{p['media_id']}/insights", metric=metric)
            if r.get('data'):
                d0 = r['data'][0]
                v = d0.get('values', [{}])[0].get('value', d0.get('total_value', {}).get('value'))
                if v is not None:
                    m[metric] = v
        if not m and it['id'] in prev:  # keep the last numbers if the API had a hiccup
            m = {k: prev[it['id']].get(k) for k in ['reach', 'views', 'likes', 'comments', 'saves', 'shares', 'follows', 'profile_visits', 'avg_watch_s'] if prev[it['id']].get(k) is not None}
            m = {('saved' if k == 'saves' else k): v for k, v in m.items()}
        link = get(p['media_id'], fields='permalink')
        row['permalink'] = link.get('permalink', '')
        row['removed'] = 'error' in link
        if row['removed']:
            row['status'] = 'Removed'
        row['reach'] = m.get('reach', 0)
        row['views'] = m.get('views', 0)
        row['likes'] = m.get('likes', 0)
        row['comments'] = m.get('comments', 0)
        row['saves'] = m.get('saved', 0)
        row['shares'] = m.get('shares', 0)
        row['follows'] = m.get('follows', 0)
        row['profile_visits'] = m.get('profile_visits', 0)
        row['interactions'] = row['likes'] + row['comments'] + row['saves'] + row['shares']
        row['engagement_rate'] = round(row['interactions'] / row['reach'], 4) if row['reach'] else None
        # comment quality: counts only, no comment text or usernames are stored
        cm = get(f"{p['media_id']}/comments", fields='text,username,replies{username}', limit=100)
        if 'data' in cm:
            theirs = [c for c in cm['data'] if (c.get('username') or '').lower() != 'resetherbalance']
            row['comments_from_others'] = len(theirs)
            row['quality_comments'] = sum(1 for c in theirs if len(re.findall(r"[A-Za-z']+", c.get('text') or '')) >= 5)
            row['reset_comments'] = sum(1 for c in theirs if re.search(r'\breset\b', c.get('text') or '', re.I))
            row['replied_comments'] = sum(1 for c in theirs if any((r.get('username') or '').lower() == 'resetherbalance' for r in (c.get('replies') or {}).get('data', [])))
        elif it['id'] in prev:
            for k in ['comments_from_others', 'quality_comments', 'reset_comments', 'replied_comments']:
                if k in prev[it['id']]:
                    row[k] = prev[it['id']][k]
        if 'ig_reels_avg_watch_time' in m:
            row['avg_watch_s'] = round(m['ig_reels_avg_watch_time'] / 1000, 1)
    else:
        if not it.get('approved'):
            row['status'] = 'Waiting for approval'
        elif when < NOW - dt.timedelta(hours=6):
            row['status'] = 'Missed'
        elif when <= NOW:
            row['status'] = 'Due now'
        else:
            row['status'] = 'Scheduled'
    d = (local.date() - NOW.astimezone(UK).date()).days
    row['day'] = 'Today' if d == 0 else 'Tomorrow' if d == 1 else 'Yesterday' if d == -1 else ('Past' if d < 0 else 'Later')
    posts.append(row)
write('posts', posts)

# ---------- account: follower history, one row a day ----------
acct = get(IG, fields='followers_count,media_count')
hist = json.load(open('dashboard/account.json')) if os.path.exists('dashboard/account.json') else []
if not hist:  # seed with the snapshots the learning loop already took
    hist = [{'date': '2026-11-04', 'followers': 3, 'posts': 4, 'source': 'research pull 4 Nov'}]
    try:
        lat = json.load(open('research/latest.json'))
        a = lat['ours'].get('_account', {})
        day = lat['pulled_utc'][:10]
        if a.get('followers_count') is not None:
            hist.append({'date': day, 'followers': a['followers_count'], 'posts': a.get('media_count', 0), 'source': 'research pull'})
    except Exception:  # noqa: BLE001
        pass
today = NOW.astimezone(UK).strftime('%Y-%m-%d')
if 'followers_count' in acct:
    hist = [h for h in hist if h['date'] != today]
    hist.append({'date': today, 'followers': acct['followers_count'], 'posts': acct.get('media_count', 0), 'source': 'daily pull'})
hist.sort(key=lambda h: h['date'])
write('account', hist)

# ---------- competitors: what is working for others ----------
comp = []
try:
    lat = json.load(open('research/latest.json'))
    for name, bd in lat.get('competitors', {}).items():
        media = (bd.get('media') or {}).get('data') or []
        if not media:
            continue
        eng = [(m.get('like_count') or 0) + (m.get('comments_count') or 0) for m in media]
        med = statistics.median(eng) or 1
        best = max(media, key=lambda m: (m.get('like_count') or 0) + (m.get('comments_count') or 0))
        best_e = (best.get('like_count') or 0) + (best.get('comments_count') or 0)
        fmt = {'VIDEO': 'Reel', 'CAROUSEL_ALBUM': 'Carousel', 'IMAGE': 'Static'}.get(best.get('media_type'), best.get('media_type', ''))
        if best.get('media_product_type') == 'REELS':
            fmt = 'Reel'
        comp.append({
            'account': '@' + name, 'followers': bd.get('followers_count', 0), 'posts_read': len(media),
            'median_engagement': round(med), 'best_multiple': round(best_e / med, 1),
            'best_format': fmt, 'best_hook': first_sentence(best.get('caption', '')),
            'best_link': best.get('permalink', ''), 'pulled': lat.get('pulled_utc', '')[:10],
        })
except Exception as e:  # noqa: BLE001
    print('competitors skipped', e)
comp.sort(key=lambda r: -r['best_multiple'])
write('competitors', comp)

# ---------- automated jobs: last run of each GitHub job ----------
jobs = json.load(open('dashboard/manual/jobs.json'))
runs = {}
gh = os.environ.get('GITHUB_TOKEN')
repo = os.environ.get('GITHUB_REPOSITORY', 'resetherbalance/resether-media')
if gh:
    req = urllib.request.Request(f'https://api.github.com/repos/{repo}/actions/runs?per_page=100',
                                 headers={'Authorization': f'Bearer {gh}', 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            for run in json.load(r).get('workflow_runs', []):
                if run['name'] not in runs and run.get('conclusion'):
                    runs[run['name']] = run
    except Exception as e:  # noqa: BLE001
        print('runs skipped', e)
for j in jobs:
    run = runs.get(j.get('workflow', ''))
    if run:
        t = dt.datetime.fromisoformat(run['updated_at'].replace('Z', '+00:00')).astimezone(UK)
        j['last_run'] = t.strftime('%Y-%m-%d %H:%M')
        j['last_result'] = 'OK' if run['conclusion'] == 'success' else run['conclusion'].title()
    j.setdefault('last_run', '')
    j.setdefault('last_result', '')
write('jobs', jobs)

# ---------- hand-kept lists: copied through as they are ----------
for name in ['tasks', 'learnings', 'improvements', 'tools', 'tests']:
    write(name, json.load(open(f'dashboard/manual/{name}.json')))

# ---------- summary: one row of headline numbers ----------
live = [p for p in posts if p['status'] == 'Posted']
def avg(rows, k):
    return round(sum(r.get(k, 0) for r in rows) / len(rows), 1) if rows else 0
reels = [p for p in live if p['format'] == 'Reel']
cars = [p for p in live if p['format'] != 'Reel']
upcoming = [p for p in posts if p['status'] == 'Scheduled']
nxt = upcoming[0] if upcoming else {}
f_now = hist[-1]['followers'] if hist else 0
week_ago = (NOW.astimezone(UK).date() - dt.timedelta(days=7)).isoformat()
older = [h for h in hist if h['date'] <= week_ago]
base = older[-1]['followers'] if older else (hist[0]['followers'] if hist else 0)
summary = [{
    'built': NOW.astimezone(UK).strftime('%Y-%m-%d %H:%M'),
    'followers': f_now, 'followers_change': f_now - base,
    'followers_change_since': older[-1]['date'] if older else (hist[0]['date'] if hist else ''),
    'posts_live': len(live), 'scheduled': len(upcoming),
    'total_reach': sum(p.get('reach', 0) for p in live),
    'total_interactions': sum(p.get('interactions', 0) for p in live),
    'avg_reach_reel': avg(reels, 'reach'), 'avg_reach_feed': avg(cars, 'reach'),
    'avg_watch_s': avg([r for r in reels if 'avg_watch_s' in r], 'avg_watch_s'),
    'avg_minutes_late': avg(live, 'minutes_late'),
    'comments_from_others': sum(p.get('comments_from_others', 0) for p in live),
    'quality_comments': sum(p.get('quality_comments', 0) for p in live),
    'reset_comments': sum(p.get('reset_comments', 0) for p in live),
    'replied_comments': sum(p.get('replied_comments', 0) for p in live),
    'total_saves': sum(p.get('saves', 0) for p in live),
    'total_shares': sum(p.get('shares', 0) for p in live),
    'total_follows_from_posts': sum(p.get('follows', 0) for p in live),
    'next_title': nxt.get('title', ''), 'next_when': (nxt.get('weekday', '') + ' ' + nxt.get('date', '')[8:] + ' ' + nxt.get('slot', '')).strip(),
    'next_format': nxt.get('format', ''),
    'to_reach_50': max(0, 50 - f_now), 'to_reach_10k': max(0, 10000 - f_now),
}]
write('summary', summary)

json.dump({'built_utc': NOW.isoformat(timespec='seconds')}, open('dashboard/built.json', 'w'))
