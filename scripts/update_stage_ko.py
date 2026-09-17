#!/usr/bin/env python3

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup

BASE = "https://battlecats.anypupil.com/"
START = BASE + "stages.php?lang=ko"
OUT = Path(__file__).resolve().parents[1] / "stage-ko.json"
TIMEOUT = 30
DELAY = 0.03

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; BattleCatsKoreanStageSync/7.0)",
    "Accept-Language": "ko-KR,ko;q=0.9,ja;q=0.8",
})

def norm(text):
    return re.sub(r"\s+", " ", str(text or "").replace("\u3000", " ")).strip()

def has_korean(text):
    return bool(re.search(r"[가-힣]", text or ""))

def has_japanese(text):
    return bool(re.search(r"[ぁ-んァ-ン一-龯々]", text or ""))

def get(url):
    time.sleep(DELAY)
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text

def discover_all_maps():
    print("[1/4] 모든 맵 탐색 시작")
    queue = [START]
    visited = set()
    maps = set()

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            html = get(url)
        except Exception as e:
            print("페이지 실패:", url, e)
            continue

        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            target = urljoin(BASE, a["href"])
            parsed = urlparse(target)

            if parsed.netloc != "battlecats.anypupil.com":
                continue

            filename = parsed.path.rsplit("/", 1)[-1]
            query = parse_qs(parsed.query)

            if filename == "stage_map.php":
                map_id = (query.get("id") or [None])[0]
                if map_id:
                    maps.add(
                        BASE + "stage_map.php?" +
                        urlencode({"id": map_id, "lang": "ko"})
                    )
                continue

            if filename == "stages.php" or filename.startswith("stage_"):
                if filename in ("stage.php", "stage_map.php"):
                    continue

                query["lang"] = ["ko"]
                flattened = {
                    k: v[0]
                    for k, v in query.items()
                    if v
                }

                normalized = "https://" + parsed.netloc + parsed.path
                if flattened:
                    normalized += "?" + urlencode(flattened)

                if normalized not in visited:
                    queue.append(normalized)

    print("발견한 맵:", len(maps))
    return sorted(maps)

def get_map_title(soup):
    h1 = soup.find("h1")
    if not h1:
        return ""
    return norm(h1.get_text(" ", strip=True))

def parse_map_with_exceptions(url):
    html = get(url)
    soup = BeautifulSoup(html, "html.parser")
    map_title = get_map_title(soup)
    results = []

    for heading in soup.find_all(["h4", "h3"]):
        ko = norm(heading.get_text(" ", strip=True))

        if not has_korean(ko):
            continue

        jp = ""
        node = heading.next_sibling
        checked = 0

        while node is not None and checked < 12:
            checked += 1

            if hasattr(node, "get_text"):
                text = norm(node.get_text(" ", strip=True))
            else:
                text = norm(str(node))

            if text and has_japanese(text) and not has_korean(text):
                jp = text
                break

            if getattr(node, "name", None) in ("h3", "h4"):
                break

            node = node.next_sibling

        if not jp or len(jp) > 150:
            continue

        if jp == "本能解放への道":
            if "ムート" in map_title or "무트" in map_title:
                ko = "본능 해방의 길 (고양이 무트)"
            elif "ヴァルキリー" in map_title or "발키리" in map_title:
                ko = "본능 해방의 길 (고양이 발키리)"

        results.append((jp, ko, map_title))

    return results

def load_existing():
    if not OUT.exists():
        return {}

    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        return dict(data.get("stages", {}))
    except Exception:
        return {}

def main():
    print("=====================================")
    print(" Battle Cats Stage Sync v7")
    print("=====================================")

    maps = discover_all_maps()

    print("\n[2/4] 전체 스테이지 번역 수집")

    stages = load_existing()
    instinct = []
    found_pairs = 0

    for i, url in enumerate(maps, 1):
        try:
            entries = parse_map_with_exceptions(url)
        except Exception as e:
            print("맵 실패:", url, e)
            continue

        for jp, ko, map_title in entries:
            found_pairs += 1

            if jp == "本能解放への道":
                instinct.append({
                    "map": map_title,
                    "jp": jp,
                    "ko": ko,
                })
                continue

            # 중복 여부를 검사하지 않고 발견한 한국어명을 그대로 적용.
            stages[jp] = ko

        if i % 50 == 0 or i == len(maps):
            print(
                f"{i}/{len(maps)}"
                f" | 발견={found_pairs}"
                f" | 고유명={len(stages)}"
            )

    print("\n[3/4] JSON 생성")

    context = {}

    for item in instinct:
        map_name = item["map"]
        if not map_name:
            continue

        context[f"{map_name}|本能解放への道"] = item["ko"]

    payload = {
        "source": BASE,
        "generated_by": "scripts/update_stage_ko.py v7",
        "map_count": len(maps),
        "found_stage_pairs": found_pairs,
        "count": len(stages),
        "context_count": len(context),
        "note": (
            "battlecats.anypupil.com의 모든 stage_map.php에서 "
            "한국어 스테이지명과 일본어 원문을 직접 수집합니다. "
            "중복명은 검사하지 않으며 마지막으로 발견된 한국어명을 사용합니다. "
            "本能解放への道만 별도로 구분합니다."
        ),
        "stages": dict(sorted(stages.items())),
        "context_stages": dict(sorted(context.items())),
    }

    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print("\n[4/4] 완료")
    print("맵:", len(maps))
    print("발견한 JP→KO 쌍:", found_pairs)
    print("고유 일본어 스테이지명:", len(stages))
    print("본능 해방 예외:", len(context))

if __name__ == "__main__":
    main()
