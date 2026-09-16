#!/usr/bin/env python3

import csv
import io
import json
import re
import html
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed

SHEET_ID = "12bhVk1tfC9N-U2eU9xie-XoW2gw85acQAukR-W2k3KY"

SHEETS = [
    "旧レ",
    "真レ",
    "零レ",
    "塔",
    "降臨",
    "強襲",
    "超獣",
    "開眼",
    "コラボ",
    "他",
]

BASE = "https://battlecats.anypupil.com/"
START = BASE + "stages.php?lang=ko"

OUT = Path(__file__).resolve().parents[1] / "stage-ko.json"

UA = (
    "Mozilla/5.0 "
    "(compatible; BattleCatsStageNameSync/4.0; GitHubActions)"
)

# 동시에 너무 많이 요청하지 않도록 16개
WORKERS = 16


# =========================================================
# HTTP
# =========================================================

def get(url, timeout=30):
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "ko-KR,ko;q=0.9,ja;q=0.8",
        },
    )

    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# =========================================================
# 문자열 처리
# =========================================================

def clean(text):
    if not text:
        return ""

    text = re.sub(
        r"<script\b.*?</script>|<style\b.*?</style>",
        " ",
        text,
        flags=re.S | re.I,
    )

    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize(text):
    if not text:
        return ""

    return (
        re.sub(r"\s+", " ", text)
        .strip()
        .replace("　", " ")
        .replace("Lv．", "Lv.")
        .replace("Ｌｖ．", "Lv.")
    )


def has_japanese(text):
    return bool(
        re.search(r"[ぁ-んァ-ン一-龯々]", text)
    )


def has_korean(text):
    return bool(
        re.search(r"[가-힣]", text)
    )


def valid_ko(text):
    if not text:
        return False

    bad = [
        "미명명",
        "未命名",
        "unknown",
        "unnamed",
        "不明",
    ]

    lower = text.lower()

    if any(x.lower() in lower for x in bad):
        return False

    return has_korean(text)


# =========================================================
# Google Sheet
# =========================================================

def sheet_url(name):
    return (
        "https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/gviz/tq?"
        + urlencode(
            {
                "tqx": "out:csv",
                "sheet": name,
            }
        )
    )


def read_sheet(name):
    raw = get(sheet_url(name))

    return list(
        csv.reader(
            io.StringIO(raw)
        )
    )


def find_player_columns(header):
    return [
        i
        for i, value in enumerate(header)
        if value.strip() == "プレイヤー"
    ]


def collect_sheet_stages():

    result = set()

    for sheet in SHEETS:

        print(f"[SHEET] {sheet}")

        try:
            rows = read_sheet(sheet)

        except Exception as e:
            print("  ERROR:", e)
            continue

        if not rows:
            continue

        header = rows[0]

        player_cols = find_player_columns(header)

        for pcol in player_cols:

            scol = None

            # 같은 블록에서 가장 가까운 ステージ 찾기
            for c in range(pcol - 1, -1, -1):

                if (
                    c < len(header)
                    and header[c].strip() == "ステージ"
                ):
                    scol = c
                    break

            # 특수 구조 fallback
            if scol is None:
                fallback = pcol - 9

                if fallback >= 0:
                    scol = fallback

            if scol is None:
                continue

            for row in rows[1:]:

                if (
                    pcol >= len(row)
                    or scol >= len(row)
                ):
                    continue

                player = row[pcol].strip()
                stage = normalize(row[scol])

                if player and stage:
                    result.add(stage)

    print()
    print("Sheet unique stages:", len(result))

    return result


# =========================================================
# 기존 JSON
# =========================================================

def load_existing():

    if not OUT.exists():
        return {}

    try:
        data = json.loads(
            OUT.read_text(encoding="utf-8")
        )

        return {
            normalize(k): v
            for k, v in data.get(
                "stages",
                {}
            ).items()
            if valid_ko(v)
        }

    except Exception as e:
        print("Existing JSON error:", e)
        return {}


# =========================================================
# stages.php에서 모든 맵 URL 확보
# =========================================================

def get_map_urls():

    print()
    print("[1/4] Reading stage index...")

    doc = get(START)

    urls = set()

    for href in re.findall(
        r'href=["\']([^"\']+)["\']',
        doc,
        flags=re.I,
    ):

        href = html.unescape(href)

        url = urljoin(BASE, href)

        parsed = urlparse(url)

        if not parsed.path.endswith("stage_map.php"):
            continue

        qs = parse_qs(parsed.query)

        if not qs.get("id"):
            continue

        map_id = qs["id"][0]

        urls.add(
            BASE
            + "stage_map.php?"
            + urlencode(
                {
                    "id": map_id,
                    "lang": "ko",
                }
            )
        )

    urls = sorted(urls)

    print("Map pages:", len(urls))

    return urls


# =========================================================
# 맵 페이지 검색
# =========================================================

def scan_map(url, missing):

    try:
        doc = get(url)

    except Exception:
        return []

    text = normalize(clean(doc))

    # 이 맵에 우리가 원하는 일본어명이 하나라도 없으면
    # stage.php 링크를 분석할 필요 없음
    matched = [
        stage
        for stage in missing
        if stage in text
    ]

    if not matched:
        return []

    stage_urls = set()

    for href in re.findall(
        r'href=["\']([^"\']*stage\.php[^"\']*)["\']',
        doc,
        flags=re.I,
    ):

        href = html.unescape(href)

        url2 = urljoin(BASE, href)

        parsed = urlparse(url2)
        qs = parse_qs(parsed.query)

        if not qs.get("sid"):
            continue

        sid = qs["sid"][0]

        stage_urls.add(
            BASE
            + "stage.php?"
            + urlencode(
                {
                    "lang": "ko",
                    "sid": sid,
                }
            )
        )

    return list(stage_urls)


# =========================================================
# stage.php 파싱
# =========================================================

def parse_stage_page(url):

    try:
        doc = get(url)

    except Exception:
        return None

    # h1 = 현재 언어(한국어)의 스테이지명인 경우가 많음
    h1 = re.search(
        r"<h1[^>]*>(.*?)</h1>",
        doc,
        flags=re.S | re.I,
    )

    ko = ""

    if h1:
        candidate = normalize(
            clean(h1.group(1))
        )

        if valid_ko(candidate):
            ko = candidate

    # 페이지에서 일본어 원문 찾기
    texts = []

    for value in re.findall(
        r">([^<>]{1,180})<",
        doc,
        flags=re.S,
    ):

        value = normalize(
            html.unescape(value)
        )

        if value:
            texts.append(value)

    jp_candidates = [
        x
        for x in texts
        if has_japanese(x)
        and not has_korean(x)
    ]

    if not jp_candidates:
        return None

    # h1 바로 다음에 나오는 일본어 원문이 가장 유력
    if h1:

        tail = doc[h1.end():h1.end() + 1500]

        tail_texts = [
            normalize(html.unescape(x))
            for x in re.findall(
                r">([^<>]{1,180})<",
                tail,
                flags=re.S,
            )
        ]

        for x in tail_texts:

            if (
                x
                and has_japanese(x)
                and not has_korean(x)
            ):
                jp = x

                if ko:
                    return normalize(jp), ko

    # fallback
    if ko:
        return normalize(jp_candidates[0]), ko

    return None


# =========================================================
# main
# =========================================================

def main():

    print(
        "=== Battle Cats Korean Stage Sync v4 ==="
    )

    # -----------------------------------------------------
    # 시트
    # -----------------------------------------------------

    sheet_stages = collect_sheet_stages()

    existing = load_existing()

    print(
        "Existing translations:",
        len(existing),
    )

    # 기존 번역 중 현재 시트에 있는 것만 유지
    translations = {
        jp: ko
        for jp, ko in existing.items()
        if jp in sheet_stages
    }

    missing = {
        x
        for x in sheet_stages
        if x not in translations
    }

    print(
        "Need lookup:",
        len(missing),
    )

    if not missing:

        print("Nothing to update.")
        return

    # -----------------------------------------------------
    # 모든 맵 URL
    # -----------------------------------------------------

    map_urls = get_map_urls()

    print()
    print(
        "[2/4] Scanning map pages in parallel..."
    )

    stage_urls = set()

    done = 0

    with ThreadPoolExecutor(
        max_workers=WORKERS
    ) as pool:

        futures = {
            pool.submit(
                scan_map,
                url,
                missing,
            ): url
            for url in map_urls
        }

        for future in as_completed(futures):

            done += 1

            try:
                found = future.result()

                stage_urls.update(found)

            except Exception:
                pass

            if done % 100 == 0:
                print(
                    f"  maps {done}/{len(map_urls)}"
                )

    print(
        "Candidate stage pages:",
        len(stage_urls),
    )

    # -----------------------------------------------------
    # 상세 페이지
    # -----------------------------------------------------

    print()
    print(
        "[3/4] Reading candidate stages..."
    )

    discovered = {}

    done = 0

    with ThreadPoolExecutor(
        max_workers=WORKERS
    ) as pool:

        futures = {
            pool.submit(
                parse_stage_page,
                url,
            ): url
            for url in stage_urls
        }

        for future in as_completed(futures):

            done += 1

            try:
                pair = future.result()

            except Exception:
                pair = None

            if pair:

                jp, ko = pair

                if (
                    jp in missing
                    and valid_ko(ko)
                ):
                    # 같은 일본어 이름이 여러 맵에 있을 경우
                    # 한국어명이 동일하면 그대로 사용
                    if jp not in discovered:
                        discovered[jp] = ko

                    elif discovered[jp] != ko:
                        print(
                            "AMBIGUOUS:",
                            jp,
                            "=>",
                            discovered[jp],
                            "/",
                            ko,
                        )

            if done % 100 == 0:
                print(
                    f"  stages {done}/{len(stage_urls)}"
                )

    translations.update(discovered)

    # -----------------------------------------------------
    # 결과
    # -----------------------------------------------------

    unresolved = sorted(
        x
        for x in sheet_stages
        if x not in translations
    )

    payload = {
        "source": BASE,
        "generated_by":
            "scripts/update_stage_ko.py v4",
        "sheet_id": SHEET_ID,
        "sheet_stage_count":
            len(sheet_stages),
        "count":
            len(translations),
        "untranslated_count":
            len(unresolved),
        "note":
            "battlecats.anypupil.com의 실제 "
            "스테이지 인덱스와 맵 구조를 순회하여 "
            "한국어판 명칭이 확인된 스테이지만 저장합니다.",
        "stages": dict(
            sorted(
                translations.items()
            )
        ),
        "untranslated": unresolved,
    }

    OUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "[4/4] Complete"
    )

    print(
        "Found this run:",
        len(discovered),
    )

    print(
        "Total translated:",
        len(translations),
    )

    print(
        "Still untranslated:",
        len(unresolved),
    )

    if unresolved:

        print()
        print("UNRESOLVED:")

        for x in unresolved:
            print(" -", x)


if __name__ == "__main__":
    main()
