#!/usr/bin/env python3
import json, re, time
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE='https://battlecats.anypupil.com/'
INDEX=urljoin(BASE,'stages.php?lang=ko')
OUT=Path(__file__).resolve().parents[1]/'stage-ko.json'
UA='Mozilla/5.0 (compatible; BattleCatsStageNameSync/1.0)'

def get(url):
    req=Request(url,headers={'User-Agent':UA,'Accept-Language':'ko-KR,ko;q=0.9'})
    with urlopen(req,timeout=30) as r:
        return r.read().decode('utf-8','replace')

def clean_html(x):
    x=re.sub(r'<[^>]+>',' ',x)
    x=x.replace('&amp;','&').replace('&quot;','"').replace('&#039;',"'")
    return re.sub(r'\s+',' ',x).strip()

def stage_ids(html):
    # 스테이지 목록/검색 페이지에 노출되는 상세 링크에서 sid를 수집한다.
    return sorted(set(re.findall(r'stage\.php\?(?:[^"\']*&amp;|[^"\']*&)?sid=([A-Za-z0-9_-]+)',html)))

def parse_stage(html):
    # 현재 Guide Hub 상세 페이지는 H1에 한국어명, 바로 뒤의 별도 표기에 일본어 원문을 제공한다.
    m=re.search(r'<h1[^>]*>(.*?)</h1>',html,re.S|re.I)
    if not m:return None
    ko=clean_html(m.group(1))
    tail=html[m.end():m.end()+2500]
    # 일본어 원문은 제목 직후 텍스트/요소에 나타난다. 일본어 문자가 포함된 첫 짧은 텍스트를 고른다.
    texts=[clean_html(x) for x in re.findall(r'>([^<>]{1,160})<',tail,re.S)]
    jp=''
    for t in texts:
        if t and re.search(r'[ぁ-んァ-ン一-龯]',t) and t not in ('스테이지로 돌아가기','맵으로 돌아가기'):
            jp=t;break
    if not jp:return None
    # 한국판 미개최/미명명 항목은 넣지 않는다.
    bad=('未命名','미명명','Unnamed','unknown','不明')
    if not ko or any(b.lower() in ko.lower() for b in bad):return None
    if ko==jp:return None
    return jp,ko

def main():
    html=get(INDEX)
    ids=stage_ids(html)
    # 목록 페이지가 모든 상세 링크를 직접 싣지 않는 경우 검색 엔진용 사이트맵도 보조로 사용한다.
    for extra in ('sitemap.xml','sitemap_index.xml'):
        try:
            h=get(urljoin(BASE,extra))
            ids += re.findall(r'stage\.php\?(?:amp;)?lang=ko&amp;sid=([A-Za-z0-9_-]+)',h)
            ids += re.findall(r'stage\.php\?lang=ko&sid=([A-Za-z0-9_-]+)',h)
        except Exception:
            pass
    ids=sorted(set(ids))
    old={}
    if OUT.exists():
        try: old=json.loads(OUT.read_text(encoding='utf-8')).get('stages',{})
        except Exception: pass
    stages=dict(old)
    ok=0
    for i,sid in enumerate(ids,1):
        try:
            pair=parse_stage(get(urljoin(BASE,f'stage.php?lang=ko&sid={sid}')))
            if pair:
                jp,ko=pair;stages[jp]=ko;ok+=1
        except Exception as e:
            print('skip',sid,e)
        if i%30==0: time.sleep(.4)
    payload={'source':BASE,'note':'한국판 명칭이 확인된 스테이지만 포함. 미개최/미명명 항목은 제외.','stages':dict(sorted(stages.items()))}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'ids={len(ids)} parsed={ok} total={len(stages)}')
if __name__=='__main__':main()
