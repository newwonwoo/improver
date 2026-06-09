#!/usr/bin/env python3
"""fn 22건 tractability триage — '기계적 버그' vs 'SME 판정 필요' 분류 (LLM 0회).

E-03(클린 버그)은 회수 완료. 나머지를 측정으로 분류해 '무작정 룰 완화'(게이밍)를 막고
실국장 adjudication 이 필요한 지점을 특정한다.
"""
import json, sys
sys.path.insert(0, '.')
from engine.parser import parse_law
from engine.rules import run_all
from engine import fpc
import scripts.mechanical_reco as mr

gold = [json.loads(l) for l in open('outputs/gold_reco_review.jsonl')]
mech = {r['fid']: r for r in json.load(open('outputs/reco_mechanical_measure.json'))['records']}
fmap = json.load(open('outputs/fid_article_map.json'))
PREC = {'E-01':0.32,'E-03':0.50,'E-05':0.05,'F-01':0.38,'F-02':0.07,'F-03':0.24,
        'G-01':0.27,'L-03':0.01,'S-04':0.17}
fn = [r for r in gold if r['verdict']=='반려' and mech.get(r['fid'],{}).get('status')=='fn_not_fired']
def strip(t): return t.split('---',2)[2] if t.lstrip().startswith('---') else t
def load(n): return parse_law(strip(open(f'data/laws/raw/{n}/법률.md',encoding='utf-8').read()),name=n)

out=[]
for r in fn:
    rid='-'.join(r['fid'].split('@')[0].split('-')[:2])
    name=r['fid'].split('@',1)[1]; ano=fmap.get(r['fid'])
    try: law=load(name); art={x.number:x for x in law.articles}.get(ano)
    except Exception: art=None
    trig_hit = bool(art) and any(t.search(art.full_text) for t in mr._DEFECT_TRIGGERS.get(rid,[]))
    other=[]
    if art:
        other=sorted(set(f.pattern_id for f in fpc.correct(law,run_all(law))
                         if f.article_number.replace(' ','')==ano.replace(' ','')))
    prec=PREC.get(rid)
    # 분류: E-03=fixed. trigger miss=신규트리거 필요. 다른 패턴 발화=taxonomy. 정밀도<0.2=정밀도우선.
    if rid=='E-03':
        cls='fixed(이번세션 회수)'
    elif not trig_hit:
        cls='신규트리거 필요(defect signal 부재)'
    elif other:
        cls=f'taxonomy 중복({"/".join(other)} 발화)'
    elif prec and prec < 0.2:
        cls='정밀도 우선(과발화 룰 — recall보다 FP정리)'
    else:
        cls='SME 판정 필요(임계/주체 경계)'
    out.append({'fid':r['fid'],'rule':rid,'article':ano,'precision':prec,
                'trigger_hit':trig_hit,'other_fired':other,'class':cls,'fix_hint':r['fix']})

from collections import Counter
dist=Counter(x['class'].split('(')[0] for x in out)
json.dump({'fn_total':len(fn),'class_distribution':dict(dist),'records':out},
          open('outputs/fn_triage.json','w'), ensure_ascii=False, indent=2)
print('fn triage:', dict(dist))
for x in out:
    print(f"  {x['rule']:5} {x['fid'].split('@')[0]:12} prec={x['precision']}  {x['class']}")
