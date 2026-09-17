#!/usr/bin/env python3

import csv
import io
import json
import re
import time
import html as htmlmod

from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup


# =========================================================
# 기본 설정
# =========================================================

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
START_URL = BASE + "stages.php?lang=ko"

OUT = Path(__file__).resolve().parents[1] / "stage-ko.json"

TIMEOUT = 30
SLEEP = 0.05

session = requests.Session()

session.headers.update({
    "User-Agent":
        "Mozilla/5.0 "
        "(compatible; BattleCatsStageNameSync/6.0; GitHubActions)",

    "Accept-Language":
        "ko-KR,ko;q=0.9,ja;q=0.8,en;q=0.5",
})


# =========================================================
# 문자열 처리
# =========================================================

def norm(text):
    return re.sub(
        r"\s+",
        " ",
        str(text or "").replace("\u3000", " ")
    ).strip()


def has_korean(text):
    return bool(
        re.search(r"[가-힣]", text or "")
    )


def has_japanese(text):
    return bool(
        re.search(
            r"[ぁ-んァ-ン一-龯々]",
            text or ""
        )
    )


def valid_korean(text):
    text = norm(text)

    if not text:
        return False

    if not has_korean(text):
        return False

    return True


# =========================================================
# HTTP
# =========================================================

def get(url):
    response = session.get(
        url,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    if not response.encoding:
        response.encoding = "utf-8"

    return response.text


def soup(url):
    time.sleep(SLEEP)

    return BeautifulSoup(
        get(url),
        "html.parser"
    )


# =========================================================
# Google Sheet
# =========================================================

def sheet_url(sheet_name):
    return (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/gviz/tq?"
        + urlencode({
            "tqx": "out:csv",
            "sheet": sheet_name
        })
    )


def find_left(header, start, target):
    for i in range(start - 1, -1, -1):

        if i >= len(header):
            continue

        if norm(header[i]) == target:
            return i

    return None


def collect_sheet_records():

    print("\n[1/6] Google Sheet 읽는 중...")

    records = []

    for tab in SHEETS:

        print(" -", tab)

        try:
            text = get(
                sheet_url(tab)
            )

        except Exception as e:
            print(
                "   ERROR:",
                e
            )
            continue

        rows = list(
            csv.reader(
                io.StringIO(text)
            )
        )

        if not rows:
            continue

        header = [
            norm(x)
            for x in rows[0]
        ]

        player_columns = [
            i
            for i, value in enumerate(header)
            if value == "プレイヤー"
        ]

        for player_col in player_columns:

            stage_col = find_left(
                header,
                player_col,
                "ステージ"
            )

            if stage_col is None:
                continue

            map_col = find_left(
                header,
                stage_col,
                "マップ"
            )

            for row in rows[1:]:

                if player_col >= len(row):
                    continue

                player = norm(
                    row[player_col]
                )

                if not player:
                    continue

                stage = norm(
                    row[stage_col]
                    if stage_col < len(row)
                    else ""
                )

                map_name = norm(
                    row[map_col]
                    if (
                        map_col is not None
                        and map_col < len(row)
                    )
                    else ""
                )

                if not stage:
                    continue

                records.append({
                    "tab": tab,
                    "map": map_name,
                    "stage": stage,
                })

    # 동일 기록 중복 제거
    unique = []
    seen = set()

    for record in records:

        key = (
            record["tab"],
            record["map"],
            record["stage"],
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(record)

    print(
        "Sheet contextual stages:",
        len(unique)
    )

    print(
        "Sheet unique stage names:",
        len({
            x["stage"]
            for x in unique
        })
    )

    return unique


# =========================================================
# 기존 JSON
# =========================================================

def load_existing():

    stages = {}
    context = {}

    if not OUT.exists():
        return stages, context

    try:

        data = json.loads(
            OUT.read_text(
                encoding="utf-8"
            )
        )

        for jp, ko in data.get(
            "stages",
            {}
        ).items():

            jp = norm(jp)
            ko = norm(ko)

            if jp and valid_korean(ko):
                stages[jp] = ko

        for key, ko in data.get(
            "context_stages",
            {}
        ).items():

            key = norm(key)
            ko = norm(ko)

            if key and valid_korean(ko):
                context[key] = ko

    except Exception as e:

        print(
            "기존 stage-ko.json 읽기 실패:",
            e
        )

    return stages, context


# =========================================================
# 외부 DB URL 수집
# =========================================================

def canonical_url(url):

    parsed = urlparse(url)

    query = parse_qs(
        parsed.query
    )

    query["lang"] = ["ko"]

    flat = {
        key: values[0]
        for key, values in query.items()
        if values
    }

    return (
        f"https://"
        f"{parsed.netloc}"
        f"{parsed.path}"
        f"?{urlencode(flat)}"
    )


def discover_map_urls():

    print(
        "\n[2/6] 외부 DB 맵 목록 수집 중..."
    )

    queue = [START_URL]

    visited = set()
    map_urls = set()

    while queue:

        current = queue.pop(0)

        if current in visited:
            continue

        visited.add(current)

        try:
            page = soup(current)

        except Exception as e:

            print(
                "목록 페이지 실패:",
                current,
                e
            )

            continue

        for a in page.find_all(
            "a",
            href=True
        ):

            url = urljoin(
                BASE,
                htmlmod.unescape(
                    a["href"]
                )
            )

            parsed = urlparse(url)

            if (
                parsed.netloc
                != "battlecats.anypupil.com"
            ):
                continue

            filename = (
                parsed.path
                .rsplit("/", 1)[-1]
            )

            if filename == "stage_map.php":

                query = parse_qs(
                    parsed.query
                )

                if "id" not in query:
                    continue

                map_id = query["id"][0]

                map_urls.add(
                    BASE
                    + "stage_map.php?"
                    + urlencode({
                        "id": map_id,
                        "lang": "ko"
                    })
                )

                continue

            # 스테이지 카테고리/목록 페이지 탐색
            if (
                filename == "stages.php"
                or (
                    filename.startswith(
                        "stage_"
                    )
                    and filename not in {
                        "stage.php",
                        "stage_map.php",
                    }
                )
            ):

                normalized = canonical_url(
                    url
                )

                if normalized not in visited:
                    queue.append(
                        normalized
                    )

    print(
        "발견한 맵 페이지:",
        len(map_urls)
    )

    return sorted(map_urls)


# =========================================================
# HTML 텍스트 추출
# =========================================================

def get_heading(page):

    for tag in [
        "h1",
        "h2",
        "h3",
    ]:

        element = page.find(tag)

        if element:

            text = norm(
                element.get_text(
                    " ",
                    strip=True
                )
            )

            if text:
                return text

    return ""


def extract_lines(element):

    if not element:
        return []

    result = []

    for text in element.stripped_strings:

        text = norm(text)

        if text:
            result.append(text)

    return result


def find_japanese_text(lines):

    for text in lines:

        if (
            has_japanese(text)
            and not has_korean(text)
            and len(text) <= 160
        ):
            return text

    return ""


def find_korean_text(lines):

    for text in lines:

        if (
            valid_korean(text)
            and len(text) <= 160
        ):
            return text

    return ""


# =========================================================
# 맵 이름 추출
# =========================================================

def extract_map_names(page):

    heading = get_heading(page)

    map_ko = ""
    map_jp = ""

    if valid_korean(heading):
        map_ko = heading

    elif (
        has_japanese(heading)
        and not has_korean(heading)
    ):
        map_jp = heading

    # 페이지 상단 영역에서
    # 다른 언어 제목 탐색
    candidates = []

    for element in page.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "div",
            "span",
            "p",
        ],
        limit=80
    ):

        text = norm(
            element.get_text(
                " ",
                strip=True
            )
        )

        if (
            text
            and len(text) <= 160
        ):
            candidates.append(text)

    if not map_ko:

        for text in candidates:

            if valid_korean(text):
                map_ko = text
                break

    if not map_jp:

        for text in candidates:

            if (
                has_japanese(text)
                and not has_korean(text)
            ):
                map_jp = text
                break

    return (
        norm(map_jp),
        norm(map_ko)
    )


# =========================================================
# stage.php 상세 페이지
# =========================================================

def parse_stage_detail(sid):

    url = (
        BASE
        + "stage.php?"
        + urlencode({
            "sid": sid,
            "lang": "ko"
        })
    )

    page = soup(url)

    candidates = []

    for element in page.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "strong",
            "div",
            "span",
            "p",
        ],
        limit=150
    ):

        text = norm(
            element.get_text(
                " ",
                strip=True
            )
        )

        if (
            text
            and len(text) <= 180
        ):
            candidates.append(text)

    stage_ko = ""
    stage_jp = ""

    # 한국어 우선
    for text in candidates:

        if valid_korean(text):

            stage_ko = text
            break

    # 일본어 원문
    for text in candidates:

        if (
            has_japanese(text)
            and not has_korean(text)
        ):

            stage_jp = text
            break

    return (
        norm(stage_jp),
        norm(stage_ko)
    )


# =========================================================
# 맵 페이지의 stage 링크 수집
# =========================================================

def collect_stage_links(page):

    result = []
    seen = set()

    for a in page.find_all(
        "a",
        href=True
    ):

        url = urljoin(
            BASE,
            a["href"]
        )

        parsed = urlparse(url)

        if (
            parsed.path
            .rsplit("/", 1)[-1]
            != "stage.php"
        ):
            continue

        query = parse_qs(
            parsed.query
        )

        sid = (
            query.get("sid")
            or [""]
        )[0]

        if not sid:
            continue

        if sid in seen:
            continue

        seen.add(sid)

        result.append(sid)

    return result


# =========================================================
# DB 전체 수집
# =========================================================

def crawl_database():

    map_urls = discover_map_urls()

    print(
        "\n[3/6] 외부 DB 스테이지 수집 중..."
    )

    database = []

    total = len(map_urls)

    for index, map_url in enumerate(
        map_urls,
        1
    ):

        try:

            page = soup(map_url)

            map_jp, map_ko = (
                extract_map_names(page)
            )

            stage_ids = (
                collect_stage_links(page)
            )

            for sid in stage_ids:

                try:

                    stage_jp, stage_ko = (
                        parse_stage_detail(
                            sid
                        )
                    )

                except Exception as e:

                    print(
                        " stage 실패:",
                        sid,
                        e
                    )

                    continue

                if not stage_jp:
                    continue

                if not valid_korean(stage_ko):
                    continue

                database.append({
                    "sid": sid,
                    "map_jp": map_jp,
                    "map_ko": map_ko,
                    "stage_jp": stage_jp,
                    "stage_ko": stage_ko,
                })

        except Exception as e:

            print(
                "map 실패:",
                map_url,
                e
            )

        if (
            index % 50 == 0
            or index == total
        ):

            print(
                f"  {index}/{total}"
                f" | 확보={len(database)}"
            )

    print(
        "확보한 한국어 스테이지:",
        len(database)
    )

    return database


# =========================================================
# 본능 해방의 길 예외
# =========================================================

def instinct_exception(
    map_jp,
    map_ko,
    stage_jp
):

    # 해당 일본어 스테이지가 아니면
    # 예외 적용 안 함
    if stage_jp != "本能解放への道":
        return ""

    combined = (
        f"{map_jp} {map_ko}"
    )

    # 무트
    if (
        "ムート" in combined
        or "무트" in combined
    ):

        return (
            "본능 해방의 길 "
            "(고양이 무트)"
        )

    # 발키리
    if (
        "ヴァルキリー" in combined
        or "발키리" in combined
    ):

        return (
            "본능 해방의 길 "
            "(고양이 발키리)"
        )

    return ""


# =========================================================
# 번역 테이블 생성
# =========================================================

def build_translation_table(
    records,
    database,
    old_stages,
    old_context
):

    print(
        "\n[4/6] 번역 매핑 생성 중..."
    )

    stages = dict(
        old_stages
    )

    context = dict(
        old_context
    )

    # -----------------------------------------------------
    # 핵심:
    # 중복 여부를 따지지 않는다.
    #
    # 같은 일본어명이 여러 번 나오면
    # 발견되는 한국어명을 그냥 넣는다.
    # -----------------------------------------------------

    for item in database:

        jp = norm(
            item["stage_jp"]
        )

        ko = norm(
            item["stage_ko"]
        )

        if not jp:
            continue

        if not valid_korean(ko):
            continue

        special = instinct_exception(
            item["map_jp"],
            item["map_ko"],
            jp
        )

        if special:

            # 본능 해방의 길은
            # 단순 stages에 넣지 않음
            #
            # 맵별 context에만 저장
            map_candidates = [
                item["map_jp"],
                item["map_ko"],
            ]

            for map_name in map_candidates:

                map_name = norm(
                    map_name
                )

                if not map_name:
                    continue

                context[
                    f"{map_name}|{jp}"
                ] = special

            continue

        # 중복 여부 상관없이 그냥 적용
        stages[jp] = ko

    # -----------------------------------------------------
    # 시트 기록에 본능 해방 예외 적용
    # -----------------------------------------------------

    for record in records:

        stage = norm(
            record["stage"]
        )

        map_name = norm(
            record["map"]
        )

        if (
            stage
            != "本能解放への道"
        ):
            continue

        # 먼저 DB에서 같은 맵을 찾음
        for item in database:

            if (
                item["stage_jp"]
                != stage
            ):
                continue

            db_maps = {
                norm(item["map_jp"]),
                norm(item["map_ko"]),
            }

            if (
                map_name
                and map_name in db_maps
            ):

                special = (
                    instinct_exception(
                        item["map_jp"],
                        item["map_ko"],
                        stage
                    )
                )

                if special:

                    context[
                        f"{map_name}|{stage}"
                    ] = special

                    context[
                        f"{record['tab']}|"
                        f"{map_name}|"
                        f"{stage}"
                    ] = special

    # -----------------------------------------------------
    # 미번역 확인
    # -----------------------------------------------------

    untranslated = []

    for record in records:

        stage = norm(
            record["stage"]
        )

        map_name = norm(
            record["map"]
        )

        tab = norm(
            record["tab"]
        )

        found = False

        # 본능 해방은 context 우선
        keys = [
            f"{tab}|{map_name}|{stage}",
            f"{map_name}|{stage}",
        ]

        for key in keys:

            if (
                key in context
                and valid_korean(
                    context[key]
                )
            ):
                found = True
                break

        if (
            not found
            and stage in stages
            and valid_korean(
                stages[stage]
            )
        ):

            found = True

        if not found:

            untranslated.append({
                "tab": tab,
                "map": map_name,
                "stage": stage,
            })

    return (
        stages,
        context,
        untranslated
    )


# =========================================================
# JSON 저장
# =========================================================

def save_json(
    records,
    stages,
    context,
    untranslated
):

    print(
        "\n[5/6] stage-ko.json 저장 중..."
    )

    payload = {

        "source":
            BASE,

        "generated_by":
            "scripts/update_stage_ko.py v6",

        "sheet_id":
            SHEET_ID,

        "sheet_context_count":
            len(records),

        "count":
            len(stages),

        "context_count":
            len(context),

        "untranslated_count":
            len(untranslated),

        "note":
            "v6: 중복 일본어 스테이지명도 "
            "외부 DB에서 발견한 한국어명을 "
            "그대로 적용합니다. "
            "本能解放への道만 무트/발키리를 "
            "맵 문맥으로 구분합니다.",

        "stages":
            dict(
                sorted(
                    stages.items()
                )
            ),

        "context_stages":
            dict(
                sorted(
                    context.items()
                )
            ),

        "untranslated":
            untranslated,
    }

    OUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        )
        + "\n",
        encoding="utf-8"
    )


# =========================================================
# 실행
# =========================================================

def main():

    print(
        "======================================"
    )

    print(
        " Battle Cats Korean Stage Sync v6"
    )

    print(
        "======================================"
    )

    records = (
        collect_sheet_records()
    )

    old_stages, old_context = (
        load_existing()
    )

    print(
        "\n기존 번역:",
        len(old_stages)
    )

    database = (
        crawl_database()
    )

    (
        stages,
        context,
        untranslated
    ) = build_translation_table(
        records,
        database,
        old_stages,
        old_context
    )

    save_json(
        records,
        stages,
        context,
        untranslated
    )

    print(
        "\n[6/6] 완료"
    )

    print(
        "--------------------------------------"
    )

    print(
        "Simple translations :",
        len(stages)
    )

    print(
        "Context translations:",
        len(context)
    )

    print(
        "Untranslated        :",
        len(untranslated)
    )

    print(
        "--------------------------------------"
    )

    if untranslated:

        print(
            "\n미번역 목록 "
            "(최대 150개 표시)"
        )

        for item in untranslated[:150]:

            print(
                " -",
                item["tab"],
                "|",
                item["map"],
                "|",
                item["stage"]
            )


if __name__ == "__main__":
    main()
