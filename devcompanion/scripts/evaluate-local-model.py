"""Measure the existing suggestion client on local Ollama only.

Usage: .venv/bin/python scripts/evaluate-local-model.py --model qwen3-coder:30b
Uses small synthetic evidence, alternating cases and passing/breaking-only inputs.
Outputs raw replies and timings; automatic checks are narrow, not a quality score.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from devcompanion.llm.client import suggest

ap = argparse.ArgumentParser()
ap.add_argument('--model', default='qwen3-coder:30b')
ap.add_argument('--repeats', type=int, default=10)
ap.add_argument('--output', type=Path, default=Path('/tmp/devcompanion-model-evaluation.json'))
a = ap.parse_args()
if a.repeats < 1:
    ap.error('--repeats must be positive')
api = 'http://127.0.0.1:11434'

cases = [
    dict(name='required_argument', change='add(a, b) -> add(a, b, carry)',
         broken=dict(where='tests/test_calc.py:7',verdict='breaks',why="missing required 'carry'",code='add(1, 2)'),
         fit=dict(where='report.py:7',verdict='ok',why='arguments fit the new signature',code='add(t, x, 0)'),
         expected='carry', forbidden='report.py'),
    dict(name='keyword_rename', change='Ledger.post(self, amount, memo) -> Ledger.post(self, amount, note)',
         broken=dict(where='report.py:18',verdict='breaks',why="unknown keyword 'memo'",code='ledger.post(a, memo="auto")'),
         fit=dict(where='tests/test_ledger.py:8',verdict='ok',why='arguments fit the new signature',code='ledger.post(5, note="x")'),
         expected='note', forbidden='test_ledger'),
]
result = {'model':a.model,'timestamp':time.time(),'context_limit':4096,'output_limit':60,
          'temperature':0,'repeats':a.repeats,'remote_calls':False,'rows':[]}


def save():
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2))


def get(path):
    with urllib.request.urlopen(api+path,timeout=10) as r:
        return json.load(r)


installed = get('/api/tags')['models']
model = next((m for m in installed if m['name']==a.model),None)
if not model:
    raise SystemExit(f'Model {a.model} is not installed; no automatic download or substitution')
result['installed_model'] = model
result['ollama_version'] = get('/api/version')
# Warm-load separately; do not count load time as a warm suggestion latency.
start=time.monotonic()
req=urllib.request.Request(api+'/api/generate',data=json.dumps({
    'model':a.model,'prompt':'','stream':False,'keep_alive':'15m',
    'options':{'num_ctx':4096}}).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=240) as r:
    result['load_reply']=json.load(r)
result['load_wall_s']=round(time.monotonic()-start,3)
result['resident_after_load']=get('/api/ps')
save()
print(f"Loaded {a.model} in {result['load_wall_s']}s",flush=True)
for repeat in range(a.repeats):
    for condition in ('all_sites','breaking_only'):
        for c in cases:
            sites=[c['fit'],c['broken']] if condition=='all_sites' else [c['broken']]
            payload={'change':c['change'],'claim':f'{len(sites)} call site(s): 1 break, 0 unsure, {len(sites)-1} fit','sites':sites}
            reply=suggest(json.dumps(payload),model=a.model,base_url=api,num_ctx=4096)
            text=reply.text or ''
            row={'repeat':repeat,'condition':condition,'case':c['name'],'payload':payload,**asdict(reply),
                 'nonempty':bool(text.strip()),'mentions_expected_token':c['expected'] in text,
                 'mentions_passing_file':c['forbidden'] in text,'word_count':len(text.split())}
            result['rows'].append(row)
            save()
            print(f"{condition} {c['name']} {reply.status} {reply.wall_s:.2f}s: {text}",flush=True)
            if reply.status=='timeout':
                result['stopped']='30s suggestion deadline exceeded; avoid queuing more work'
                save()
                raise SystemExit(2)
result['resident_after_run']=get('/api/ps')
result['summary']={}
for condition in ('all_sites','breaking_only'):
    rows=[r for r in result['rows'] if r['condition']==condition]
    times=sorted(r['wall_s'] for r in rows)
    result['summary'][condition]={'calls':len(rows),'median_s':round(statistics.median(times),3),
        'max_s':round(max(times),3),'p95_nearest_rank_s':round(times[max(0,__import__('math').ceil(.95*len(times))-1)],3),
        'nonempty':sum(r['nonempty'] for r in rows),'expected_token':sum(r['mentions_expected_token'] for r in rows),
        'passing_file_mentions':sum(r['mentions_passing_file'] for r in rows),
        'over_25_words':sum(r['word_count']>25 for r in rows)}
save()
print(json.dumps(result['summary'],indent=2))
print(f'Raw results: {a.output}')
