#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import csv, io, json, re, time, unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, quote
import requests
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"stage-ko.json"
KR_TXT=ROOT/"kr-stage-names.txt"
SHEET_ID="12bhVk1tfC9N-U2eU9xie-XoW2gw85acQAukR-W2k3KY"
SHEET_TABS=["旧レ","真レ","零レ","塔","降臨","強襲","超獣","開眼","コラボ","他"]
BASE="https://battlecats.anypupil.com/"
S=requests.Session()
S.headers.update({"User-Agent":"Nogachasheet-stage-ko-updater/2.0"})

def norm(s):
    s=unicodedata.normalize("NFKC",str(s or "")).strip()
    s=re.sub(r"\s+","",s)
    return s.replace("・","").replace("･","").replace("！","!").replace("？","?").lower()

def get(url,tries=4):
    last=None
    for i in range(tries):
        try:
            r=S.get(url,timeout=35); r.raise_for_status(); return r
        except Exception as e:
            last=e; time.sleep(1.2*(i+1))
    raise last

def parse_local():
    maps={}
    for line in KR_TXT.read_text(encoding="utf-8-sig").splitlines():
        m=re.match(r"^\s*(\d{3}(?:-\d{3}){0,2})\s+(.+?)\s*$",line)
        if not m: continue
        code,name=m.group(1),m.group(2).strip()
        p=code.split("-")
        if len(p)==2:
            maps[code]={"name":name,"stages":[]}
        elif len(p)==3:
            mc="-".join(p[:2]); maps.setdefault(mc,{"name":"","stages":[]})
            i=int(p[2])
            while len(maps[mc]["stages"])<=i: maps[mc]["stages"].append("")
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
                sc=x-9 if tab=="零レ" else left(x,"ステージ")
                if 0<=sc<len(row) and row[sc].strip(): out.add(row[sc].strip())
    return out

def collect_maps():
    # stages.php에 보이는 모든 내부 stage 관련 페이지를 BFS로 순회하여 stage_map 링크를 회수.
    queue=[urljoin(BASE,"stages.php?lang=ko")]
    visited=set(); map_urls=[]; map_seen=set()
    while queue and len(visited)<500:
        u=queue.pop(0)
        if u in visited: continue
        visited.add(u)
        try: soup=BeautifulSoup(get(u).text,"html.parser")
        except Exception: continue
        for a in soup.select("a[href]"):
            href=a.get("href",""); nu=urljoin(BASE,href)
            if not nu.startswith(BASE): continue
            if "stage_map.php" in nu:
                if nu not in map_seen: map_seen.add(nu); map_urls.append(nu)
            elif ("stages.php" in nu or "stage_" in nu) and "stage.php" not in nu:
                if nu not in visited and nu not in queue: queue.append(nu)

    result={}
    for n,u in enumerate(map_urls,1):
        try:
            soup=BeautifulSoup(get(u).text,"html.parser")
            h=soup.select_one("h1"); map_ko=h.get_text(" ",strip=True) if h else ""
            links=[]; sids=set()
            for a in soup.select('a[href*="stage.php"]'):
                sid=parse_qs(urlparse(urljoin(BASE,a.get("href",""))).query).get("sid",[None])[0]
                if sid and sid not in sids:
                    sids.add(sid); links.append(sid)
            if links: result[u]={"map_ko":map_ko,"sids":links}
        except Exception as e: print("map skip",u,e)
        if n%50==0: print("maps",n,"/",len(map_urls))
    return result

def pair(sid):
    # 한국어 상세 페이지는 H1=한국어, 바로 아래 보조명=일본어인 경우가 많지만
    # 일본어 페이지 H1을 별도로 읽어 일본어 key를 확정한다.
    ks=BeautifulSoup(get(f"{BASE}stage.php?lang=ko&sid={sid}").text,"html.parser")
    js=BeautifulSoup(get(f"{BASE}stage.php?lang=ja&sid={sid}").text,"html.parser")
    kh=ks.select_one("h1"); jh=js.select_one("h1")
    return (jh.get_text(" ",strip=True) if jh else "",
            kh.get_text(" ",strip=True) if kh else "")

def local_map_match(name,maps):
    n=norm(name)
    exact=[(c,d) for c,d in maps.items() if n and norm(d["name"])==n]
    if len(exact)==1:return exact[0],1.0
    cand=[]
    for c,d in maps.items():
        dn=norm(d["name"])
        if not n or not dn:continue
        s=SequenceMatcher(None,n,dn).ratio()
        if s>=.90:cand.append((s,c,d))
    cand.sort(reverse=True)
    if cand and (len(cand)==1 or cand[0][0]-cand[1][0]>=.04):
        s,c,d=cand[0]; return (c,d),s
    return None,0.0

def main():
    maps=parse_local()
    wanted=sheet_wanted()
    previous={}; previous_ctx={}
    if OUT.exists():
        try:
            d=json.loads(OUT.read_text(encoding="utf-8"))
            previous=d.get("stages",{}) or {}
            previous_ctx=d.get("context_stages",{}) or {}
        except Exception: pass

    result={}; evidence={}
    remote=collect_maps()
    cache={}
    for mn,(mu,md) in enumerate(remote.items(),1):
        lm,score=local_map_match(md["map_ko"],maps)
        lst=lm[1]["stages"] if lm else []
        for idx,sid in enumerate(md["sids"]):
            if sid not in cache:
                try: cache[sid]=pair(sid)
                except Exception as e:
                    print("stage skip",sid,e); continue
            ja,ko=cache[sid]
            if not ja: continue

            # 1. 동일 sid의 한국어 DB가 실제 번역되어 있으면 최우선
            if ko and norm(ko)!=norm(ja):
                result[ja]=ko
                evidence[ja]={"ko":ko,"method":"anypupil_same_sid","sid":sid}
            # 2. DB가 일본어 그대로면 업로드된 한국판 StageName을 map+순번으로 사용
            elif lm and idx<len(lst) and lst[idx]:
                result[ja]=lst[idx]
                evidence[ja]={"ko":lst[idx],"method":"kr_stage_file_map_index",
                              "sid":sid,"map_code":lm[0],"map_score":round(score,4),
                              "stage_index":idx}
        if mn%30==0: print("paired",mn,"/",len(remote))

    # 3. 예전 검증 DB는 누락된 key만 보완
    for ja,ko in previous.items():
        if ja and ko and ja not in result:
            result[ja]=ko
            evidence[ja]={"ko":ko,"method":"previous_verified"}

    missing=sorted(x for x in wanted if x not in result)
    payload={
        "source":"battlecats.anypupil.com + kr-stage-names.txt + previous verified stage-ko.json",
        "generated_by":"scripts/update_stage_ko.py v2",
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
    print("coverage",len(wanted)-len(missing),"/",len(wanted))
    if missing:
        print("UNTRANSLATED:")
        for x in missing: print(" -",x)

if __name__=="__main__":
    main()
