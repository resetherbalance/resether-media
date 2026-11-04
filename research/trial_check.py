"""Checks whether @resetherbalance can create Trial Reels via the API. Creates an unpublished
container only (it expires on its own after 24h). Never publishes. Writes research/trial_check.json."""
import json, os, time, urllib.request, urllib.parse
API='https://graph.facebook.com/v23.0'; TOKEN=os.environ['META_TOKEN'].strip()
IG=json.load(open('schedule.json'))['ig_user_id']
def call(method, path, params):
    params['access_token']=TOKEN
    req=urllib.request.Request(f'{API}/{path}', data=urllib.parse.urlencode(params).encode() if method=='POST' else None, method=method)
    if method=='GET': req=urllib.request.Request(f'{API}/{path}?'+urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)
    except urllib.error.HTTPError as e: return {'error': e.read().decode()[:600]}
res={}
r=call('POST', f'{IG}/media', {'media_type':'REELS','upload_type':'resumable','caption':'trial check, not published','share_to_feed':'false',
       'trial_params': json.dumps({'graduation_strategy':'MANUAL'})})
res['create']=r
if 'id' in r:
    blob=open('media/R4b.mp4','rb').read()
    req=urllib.request.Request(r['uri'], data=blob, method='POST', headers={'Authorization':f'OAuth {TOKEN}','offset':'0','file_size':str(len(blob))})
    try:
        with urllib.request.urlopen(req, timeout=600) as up: res['upload']=up.read().decode()[:200]
    except urllib.error.HTTPError as e: res['upload']=e.read().decode()[:400]
    for _ in range(30):
        s=call('GET', r['id'], {'fields':'status_code,status'})
        res['status']=s
        if s.get('status_code') in ('FINISHED','ERROR','EXPIRED'): break
        time.sleep(10)
json.dump(res, open('research/trial_check.json','w'), indent=1); print(json.dumps(res)[:1500])
