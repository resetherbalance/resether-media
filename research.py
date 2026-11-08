"""Learning loop data: competitor posts (Business Discovery) and our own post insights.
Official Instagram Graph API only. Writes research/latest.json. Env: META_TOKEN."""
import json, os, datetime, urllib.request, urllib.parse

API = 'https://graph.facebook.com/v23.0'
TOKEN = os.environ['META_TOKEN'].strip()
IG = json.load(open('schedule.json'))['ig_user_id']
ACCOUNTS = ['menopause_doctor', 'drmaryclaire', 'drjengunter', 'dr_naomipotter', 'drpunamkrishan',
            'whatthemenopause', 'libbystevenson.wellbeing', 'nedratawwab', 'thenapministry', 'jamesclear',
            'drjuliesmith', 'drstacysims', 'lifewithkate']

def get(path, **params):
    params['access_token'] = TOKEN
    u = f'{API}/{path}?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(u, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {'error': e.read().decode()[:300]}

out = {'pulled_utc': datetime.datetime.utcnow().isoformat(), 'competitors': {}, 'ours': {}}
fields = 'caption,like_count,comments_count,media_type,media_product_type,timestamp,permalink'
for a in ACCOUNTS:
    r = get(IG, fields=f'business_discovery.username({a}){{followers_count,media_count,media.limit(30){{{fields}}}}}')
    bd = r.get('business_discovery')
    out['competitors'][a] = bd if bd else r
    print(a, 'ok' if bd else r.get('error', '')[:120])

posted = json.load(open('posted.json'))
for iid, p in posted.items():
    m = {}
    for metric in ['reach', 'views', 'saved', 'shares', 'likes', 'comments', 'total_interactions', 'follows', 'profile_visits', 'ig_reels_avg_watch_time']:
        r = get(f"{p['media_id']}/insights", metric=metric)
        if 'data' in r and r['data']:
            m[metric] = r['data'][0].get('values', [{}])[0].get('value', r['data'][0].get('total_value', {}).get('value'))
    out['ours'][iid] = {'published_utc': p['published_utc'], 'metrics': m}
    print(iid, m)
acct = get(IG, fields='followers_count,media_count')
out['ours']['_account'] = acct
print('account', acct)
os.makedirs('research', exist_ok=True)
json.dump(out, open('research/latest.json', 'w'), ensure_ascii=False, indent=1)
