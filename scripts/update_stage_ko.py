#!/usr/bin/env python3
import json,re,time,html as htmlmod
from pathlib import Path
from urllib.parse import urljoin,urlparse,parse_qs
from urllib.request import Request,urlopen

BASE='https://battlecats.anypupil.com/'
START=urljoin(BASE,'stages.php?lang=ko')
OUT=Path(__file__).resolve().parents[1]/'stage-ko.json'
UA='Mozilla/5.0 (compatible; BattleCatsStageNameSync/2.0; +GitHubActions)'

def get(url):
    req=Request(
        url,
        headers={
            'User-Agent':UA,
            'Accept-Language':'ko-KR,ko;q=0.9,en;q=0.5'
        }
    )
    with urlopen(req,timeout=35) as r:
        return r.read().decode('utf-8','replace')

def clean(x):
    x=re.sub(
        r'<script\b.*?</script>|<style\b.*?</style>',
        ' ',
        x,
        flags=re.S|re.I
    )
    x=re.sub(r'<[^>]+>',' ',x)
    x=htmlmod.unescape(x)
    return re.sub(r'\s+',' ',x).strip()

def hrefs(doc,base):
    out=[]
    for h in re.findall(r'href=["\']([^"\']+)',doc,re.I):
        h=htmlmod.unescape(h)
        u=urljoin(base,h)

        if urlparse(u).netloc=='battlecats.anypupil.com':
            out.append(u)

    return out

def normalize_jp(s):
    return (
        re.sub(r'\s+',' ',s)
        .strip()
        .replace('Lv．','Lv.')
        .replace('Ｌｖ．','Lv.')
    )

def parse_stage(doc):
    m=re.search(r'<h1[^>]*>(.*?)</h1>',doc,re.S|re.I)

    if not m:
        return None

    ko=clean(m.group(1))
    tail=doc[m.end():m.end()+5000]

    candidates=[
        clean(x)
        for x in re.findall(r'>([^<>]{1,180})<',tail,re.S)
    ]

    jp=''

    for t in candidates:
        if (
            t
            and re.search(r'[ぁ-んァ-ン一-龯]',t)
            and not re.search(r'[가-힣]',t)
        ):
            jp=t
            break

    if not jp:
        return None

    bad=(
        '未命名',
        '미명명',
        'Unnamed',
        'unknown',
        '不明'
    )

    if (
        not ko
        or any(b.lower() in ko.lower() for b in bad)
        or ko==jp
    ):
        return None

    return normalize_jp(jp),ko

def crawl_ids():
    # 입구 → 분류 → 맵을 순회한다.
    # stages.php에 stage.php 링크가 직접 존재한다고 가정하지 않는다.

    q=[START]
    seen=set()
    sids=set()
    map_pages=set()

    while q and len(seen)<900:
        u=q.pop(0)

        if u in seen:
            continue

        seen.add(u)

        try:
            doc=get(u)
        except Exception as e:
            print('page skip',u,e)
            continue

        for v in hrefs(doc,u):
            p=urlparse(v)
            qs=parse_qs(p.query)

            if (
                p.path.endswith('/stage.php')
                or p.path.endswith('stage.php')
            ):
                if qs.get('sid'):
                    sids.add(qs['sid'][0])

            elif (
                p.path.endswith('/stage_map.php')
                or p.path.endswith('stage_map.php')
            ):
                # 한국어 페이지로 강제하여
                # 한국판 미개최 항목이 DB에 들어오는 것을 방지한다.

                if qs.get('id'):
                    mv=urljoin(
                        BASE,
                        'stage_map.php?id='
                        +qs['id'][0]
                        +'&lang=ko'
                    )

                    if (
                        mv not in seen
                        and mv not in map_pages
                    ):
                        map_pages.add(mv)
                        q.append(mv)

            elif (
                ('stage' in p.path or 'categor' in p.path)
                and p.netloc=='battlecats.anypupil.com'
            ):
                # 분류 페이지도 제한적으로 따라간다.

                if 'lang=ko' not in v:
                    v += (
                        '&' if '?' in v else '?'
                    )+'lang=ko'

                if v not in seen:
                    q.append(v)

        if len(seen)%40==0:
            time.sleep(.25)

    return sorted(sids)

def main():
    old={}

    if OUT.exists():
        try:
            old=json.loads(
                OUT.read_text(encoding='utf-8')
            ).get('stages',{})
        except Exception:
            pass

    ids=crawl_ids()

    print(
        'discovered stage ids:',
        len(ids)
    )

    stages=dict(old)
    parsed=0

    for i,sid in enumerate(ids,1):
        try:
            pair=parse_stage(
                get(
                    urljoin(
                        BASE,
                        f'stage.php?lang=ko&sid={sid}'
                    )
                )
            )

            if pair:
                jp,ko=pair
                stages[jp]=ko
                parsed+=1

        except Exception as e:
            print(
                'stage skip',
                sid,
                e
            )

        if i%50==0:
            time.sleep(.25)

    payload={
        'source':BASE,
        'generated_by':'scripts/update_stage_ko.py v2',
        'note':'한국어 DB에서 한국어명과 일본어 원문이 함께 확인된 스테이지만 포함. 한국판 미개최/미명명 항목은 제외.',
        'count':len(stages),
        'stages':dict(
            sorted(stages.items())
        )
    }

    OUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        )+'\n',
        encoding='utf-8'
    )

    print(
        f'parsed={parsed} total={len(stages)}'
    )

if __name__=='__main__':
    main()
