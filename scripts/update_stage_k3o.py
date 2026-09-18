#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import csv, io, json, re, time, unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, quote
import requests
from bs4 import BeautifulSoup, Tag

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"stage-ko.json"
KR_TXT=ROOT/"kr-stage-names.txt"
SHEET_ID="12bhVk1tfC9N-U2eU9xie-XoW2gw85acQAukR-W2k3KY"
SHEET_TABS=["旧レ","真レ","零レ","塔","降臨","強襲","超獣","開眼","コラボ","他"]
BASE="https://battlecats.anypupil.com/"
S=requests.Session()
S.headers.update({"User-Agent":"Nogachasheet-stage-ko-updater/3.0"})

JP_RE=re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
KO_RE=re.compile(r"[\uac00-\ud7a3]")

def norm(s):
    s=unicodedata.normalize("NFKC",str(s or "")).strip()
    s=re.sub(r"\s+","",s)
    return (s.replace("・","").replace("･","")
             .replace("！","!").replace("？","?")
             .replace("Ⅱ","ii").replace("Ⅲ","iii").lower())

def get(url,tries=5):
    last=None
    for i in range(tries):
        try:
            r=S.get(url,timeout=40)
            r.raise_for_status()
            return r
        except Exception as e:
            last=e
            time.sleep(1.4*(i+1))
    raise last

def parse_local():
    """사용자가 준 한국판 StageName 파일의 ID 계층을 보존한다."""
    maps={}
    for line in KR_TXT.read_text(encoding="utf-8-sig").splitlines():
        m=re.match(r"^\s*(\d{3}(?:-\d{3}){0,2})\s+(.+?)\s*$",line)
        if not m: continue
        code,name=m.group(1),m.group(2).strip()
        p=code.split("-")
        if len(p)==2:
            maps[code]={"name":name,"stages":[]}
        elif len(p)==3:
            mc="-".join(p[:2])
            maps.setdefault(mc,{"name":"","stages":[]})
            i=int(p[2])
            while len(maps[mc]["stages"])<=i:
                maps[mc]["stages"].append("")
            maps[mc]["stages"][i]=name
    return maps

def sheet_wanted():
    out=set()
    for tab in SHEET_TABS:
        u=f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={quote(tab)}"
        rows=list(csv.reader(io.StringIO(get(u).text)))
        if not rows: continue
        h=[x.strip() for x in rows[0]]
        pcs=[i for i,x in enumerate(h) if x=="プレイヤー"]
        def left(start,label):
            for c in range(start-1,-1,-1):
                if h[c]==label:return c
            return -1
        for row in rows[1:]:
            row += [""]*max(0,len(h)-len(row))
            for x in pcs:
                if x>=len(row) or not row[x].strip(): continue
                # 零レ의 실제 구조: 플레이어 기준 스테이지 x-9
                sc=x-9 if tab=="零レ" else left(x,"ステージ")
                if 0<=sc<len(row) and row[sc].strip():
                    out.add(row[sc].strip())
    return out

def discover_map_urls():
    """스테이지 인덱스/분류 페이지를 순회해 stage_map.php를 전부 찾는다."""
    queue=[urljoin(BASE,"stages.php?lang=ko")]
    seen=set(); maps=[]; map_seen=set()
    while queue and len(seen)<900:
        u=queue.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            soup=BeautifulSoup(get(u).text,"html.parser")
        except Exception as e:
            print("index skip",u,e); continue
        for a in soup.select("a[href]"):
            nu=urljoin(BASE,a.get("href",""))
            if not nu.startswith(BASE): continue
            if "stage_map.php" in nu:
                # 항상 한국어 렌더링 요청
                if "lang=" not in nu:
                    nu += ("&" if "?" in nu else "?")+"lang=ko"
                else:
                    nu=re.sub(r"([?&])lang=[^&]+",r"\1lang=ko",nu)
                if nu not in map_seen:
                    map_seen.add(nu); maps.append(nu)
            elif ("stages.php" in nu or "stage_category.php" in nu or "stage_" in nu) and "stage.php" not in nu:
                if nu not in seen and nu not in queue:
                    queue.append(nu)
    return maps

def text_lines(node):
    return [re.sub(r"\s+"," ",x).strip() for x in node.stripped_strings if str(x).strip()]

def stage_card_for_link(a):
    """한 stage.php 링크만 포함하는 가장 가까운 카드/블록을 찾는다."""
    cur=a
    best=None
    for _ in range(8):
        cur=cur.parent
        if not isinstance(cur,Tag): break
        links=cur.select('a[href*="stage.php"]')
        if len(links)==1:
            best=cur
            if cur.find(["h3","h4","h5","h6"]):
                return cur
        elif len(links)>1 and best is not None:
            break
    return best or a.parent

def bilingual_from_card(card):
    """
    카드 내부 텍스트를 순서대로 읽어 한국어명 바로 뒤의 일본어명을 찾는다.
    외부 DB 실제 구조:
      #### 절경 원생림 지역 17
      絶境原生林 エリア17
    """
    lines=text_lines(card)
    for i,ko in enumerate(lines):
        if not KO_RE.search(ko):
            continue
        if any(x in ko for x in ("스테이지 보기","통솔력","난이도","드롭","성 체력","스테이지 길이","적 라인","배경")):
            continue
        for ja in lines[i+1:i+4]:
            if JP_RE.search(ja) and not KO_RE.search(ja):
                if not any(x in ja for x in ("目前","這個","條件","解鎖","過關","重置","星級","個 stage")):
                    return ja,ko
    return "",""

def bilingual_pairs_from_page(soup):
    """
    stage 카드 DOM 모양에 의존하지 않고 페이지 전체의 텍스트 순서를 이용한다.
    한국어 제목 다음 1~3개 텍스트 안에 일본어 원문이 있으면 쌍으로 수집한다.
    """
    lines=text_lines(soup.select_one("main") or soup.body or soup)
    pairs=[]
    ignore_ko=("스테이지 보기","통솔력","난이도","드롭","성 체력","스테이지 길이","적 라인","배경",
               "냥코대전쟁","가이드 허브","캐릭터","검색","업데이트","홈","맵 개요","규칙 요약",
               "이 맵의 스테이지","공략 영상")
    for i,ko in enumerate(lines):
        if not KO_RE.search(ko) or any(x in ko for x in ignore_ko):
            continue
        for ja in lines[i+1:i+4]:
            if JP_RE.search(ja) and not KO_RE.search(ja):
                if any(x in ja for x in ("目前","這個","條件","解鎖","過關","重置","星級","個 stage")):
                    continue
                pairs.append((ja,ko))
                break
    return pairs

def direct_stage_pair(sid):
    """상세 페이지에서도 한국어/일본어가 같이 노출되는 경우를 보조적으로 읽는다."""
    soup=BeautifulSoup(get(f"{BASE}stage.php?lang=ko&sid={sid}").text,"html.parser")
    # 먼저 제목 주변의 짧은 텍스트를 본다.
    area=soup.select_one("main") or soup.body or soup
    lines=text_lines(area)[:80]
    ko=""; ja=""
    ignore_ko=("냥코대전쟁","가이드 허브","스테이지","캐릭터","적","검색","업데이트","홈")
    for s in lines:
        if not ko and KO_RE.search(s) and not any(x in s for x in ignore_ko) and len(s)<=80:
            ko=s
        if not ja and JP_RE.search(s) and not KO_RE.search(s) and len(s)<=80:
            if not any(x in s for x in ("目前","這個","條件","解鎖","過關","重置","星級")):
                ja=s
        if ko and ja: break
    return ja,ko

def collect_bilingual():
    result={}; evidence={}; sid_cache={}
    urls=discover_map_urls()
    print("map pages:",len(urls))
    for n,u in enumerate(urls,1):
        try:
            soup=BeautifulSoup(get(u).text,"html.parser")

            # 가장 신뢰도 높은 경로: 페이지에 실제로 연속 표시되는 한/일 제목 쌍
            for ja,ko in bilingual_pairs_from_page(soup):
                if ja and ko and norm(ja)!=norm(ko):
                    result[ja]=ko
                    evidence[ja]={"ko":ko,"method":"anypupil_page_adjacent"}

            # 보조 경로: 개별 stage 링크 카드/상세 페이지
            for a in soup.select('a[href*="stage.php"]'):
                href=urljoin(BASE,a.get("href",""))
                sid=parse_qs(urlparse(href).query).get("sid",[None])[0]
                card=stage_card_for_link(a)
                ja,ko=bilingual_from_card(card)
                if (not ja or not ko) and sid:
                    if sid not in sid_cache:
                        try:sid_cache[sid]=direct_stage_pair(sid)
                        except Exception:sid_cache[sid]=("","")
                    dja,dko=sid_cache[sid]
                    ja=ja or dja; ko=ko or dko
                if ja and ko and norm(ja)!=norm(ko):
                    result[ja]=ko
                    evidence[ja]={"ko":ko,"method":"anypupil_ko_bilingual","sid":sid or ""}
        except Exception as e:
            print("map skip",u,e)
        if n%50==0: print("maps",n,"/",len(urls),"pairs",len(result))
    return result,evidence

def main():
    if not KR_TXT.exists():
        raise SystemExit("kr-stage-names.txt가 저장소 루트에 없습니다.")

    # 파일 자체도 파싱해 형식을 검증한다.
    local=parse_local()
    print("local Korean maps:",len(local))
    wanted=sheet_wanted()
    print("ranking-sheet unique stages:",len(wanted))

    previous={}; previous_ctx={}
    if OUT.exists():
        try:
            old=json.loads(OUT.read_text(encoding="utf-8"))
            previous=old.get("stages",{}) or {}
            previous_ctx=old.get("context_stages",{}) or {}
        except Exception: pass

    result,evidence=collect_bilingual()

    # 기존에 검증되어 있던 번역은 외부 DB에서 못 찾은 key만 보완한다.
    for ja,ko in previous.items():
        if ja and ko and ja not in result:
            result[ja]=ko
            evidence[ja]={"ko":ko,"method":"previous_verified"}

    # 정규화 차이(전각/공백/로마숫자)도 실제 시트 key에 연결한다.
    norm_index={}
    for ja,ko in result.items():
        norm_index.setdefault(norm(ja),[]).append((ja,ko))
    for w in wanted:
        if w in result: continue
        cand=norm_index.get(norm(w),[])
        kos={ko for _,ko in cand if ko}
        if len(kos)==1:
            ko=next(iter(kos))
            result[w]=ko
            evidence[w]={"ko":ko,"method":"normalized_exact"}

    missing=sorted(x for x in wanted if not result.get(x))
    payload={
        "source":"battlecats.anypupil.com Korean bilingual stage pages + kr-stage-names.txt + previous verified stage-ko.json",
        "generated_by":"scripts/update_stage_ko.py v4",
        "sheet_id":SHEET_ID,
        "sheet_stage_count":len(wanted),
        "sheet_translated_count":len(wanted)-len(missing),
        "untranslated_count":len(missing),
        "count":len(result),
        "stages":dict(sorted(result.items())),
        "evidence":evidence,
        "untranslated":missing,
        "context_stages":previous_ctx
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print("coverage:",len(wanted)-len(missing),"/",len(wanted))
    print("untranslated:",len(missing))
    for x in missing: print(" -",x)

if __name__=="__main__":
    main()
