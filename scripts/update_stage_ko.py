#!/usr/bin/env python3

import csv
import io
import json
import re
import time
import html as htmlmod
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# =========================================================
# 설정
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

# 구레 / 신레 / 레제로는 시트 자체에 Korean 열이 존재하므로
# 외부 DB보다 시트 번역을 우선 사용
SHEET_KOREAN_TABS = {
    "旧レ",
    "真レ",
    "零レ",
}

BASE = "https://battlecats.anypupil.com/"
OUT = Path(__file__).resolve().parents[1] / "stage-ko.json"

UA = (
    "Mozilla/5.0 "
    "(compatible; BattleCatsStageNameSync/3.0; GitHubActions)"
)


# =========================================================
# HTTP
# =========================================================

def get(url, timeout=25):
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "ko-KR,ko;q=0.9,ja;q=0.7,en;q=0.5",
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
    text = htmlmod.unescape(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_jp(text):
    if not text:
        return ""

    return (
        re.sub(r"\s+", " ", text)
        .strip()
        .replace("Lv．", "Lv.")
        .replace("Ｌｖ．", "Lv.")
        .replace("　", " ")
    )


def valid_korean(text):
    if not text:
        return False

    bad = (
        "未命名",
        "미명명",
        "Unnamed",
        "unknown",
        "不明",
    )

    low = text.lower()

    if any(x.lower() in low for x in bad):
        return False

    return bool(re.search(r"[가-힣]", text))


# =========================================================
# Google Sheet 읽기
# =========================================================

def sheet_csv_url(sheet):
    return (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/gviz/tq?"
        + urlencode(
            {
                "tqx": "out:csv",
                "sheet": sheet,
            }
        )
    )


def read_sheet(sheet):
    url = sheet_csv_url(sheet)

    print(f"[Sheet] {sheet}")

    raw = get(url)

    return list(
        csv.reader(
            io.StringIO(raw)
        )
    )


# =========================================================
# 플레이어 블록 및 스테이지 추출
# =========================================================

def find_player_columns(header):
    return [
        i
        for i, value in enumerate(header)
        if value.strip() == "プレイヤー"
    ]


def extract_sheet_stages(sheet, rows):
    """
    プレイヤー 열을 기준으로 같은 데이터 블록의
    ステージ 열을 찾아 실제 등록된 스테이지만 추출한다.
    """

    if not rows:
        return set(), {}

    header = rows[0]

    player_cols = find_player_columns(header)

    stages = set()
    korean = {}

    for pcol in player_cols:

        # 기본 데이터 구조:
        #
        # ステージ ... 日付* プレイヤー
        #
        # プレイヤー에서 왼쪽으로 가장 가까운
        # ステージ 헤더를 찾는다.

        scol = None

        for c in range(pcol - 1, -1, -1):
            if header[c].strip() == "ステージ":
                scol = c
                break

        # 零レ 첫 블록처럼 헤더 오타/특수구조가 있을 수 있으므로
        # プレイヤー 기준 9칸 왼쪽도 fallback
        if scol is None:
            fallback = pcol - 9

            if fallback >= 0:
                scol = fallback

        if scol is None:
            continue

        for row in rows[1:]:

            if pcol >= len(row):
                continue

            player = row[pcol].strip()

            # 실제 게시자 기록이 없는 행은 굳이 처리하지 않음
            if not player:
                continue

            if scol >= len(row):
                continue

            jp = normalize_jp(
                row[scol]
            )

            if jp:
                stages.add(jp)

    # -----------------------------------------------------
    # 구레 / 신레 / 레제로 Korean 열
    # -----------------------------------------------------

    if sheet in SHEET_KOREAN_TABS:

        korean_col = None

        for i, value in enumerate(header):
            if value.strip() == "Korean":
                korean_col = i
                break

        if korean_col is not None:

            # 번역표는 보통 마지막 데이터 블록 오른쪽에 존재.
            # Korean 열과 같은 행에 있는 일본어 스테이지명을
            # 플레이어 블록에서 찾는다.

            stage_columns = [
                i
                for i, value in enumerate(header)
                if value.strip() == "ステージ"
            ]

            # 零レ 첫 블록의 헤더가 マップ으로 잘못 적힌 경우
            if sheet == "零レ" and 2 not in stage_columns:
                stage_columns.insert(0, 2)

            # 번역표와 가장 자연스럽게 대응되는 첫 번째
            # 스테이지 열을 기준으로 행별 매칭
            if stage_columns:
                reference_stage_col = stage_columns[0]

                for row in rows[1:]:

                    if (
                        reference_stage_col >= len(row)
                        or korean_col >= len(row)
                    ):
                        continue

                    jp = normalize_jp(
                        row[reference_stage_col]
                    )

                    ko = row[korean_col].strip()

                    if (
                        jp
                        and valid_korean(ko)
                    ):
                        korean[jp] = ko

    return stages, korean


# =========================================================
# 현재 시트 전체 스테이지 목록
# =========================================================

def collect_sheet_data():

    all_stages = set()
    sheet_korean = {}

    for sheet in SHEETS:

        try:
            rows = read_sheet(sheet)

            stages, korean = extract_sheet_stages(
                sheet,
                rows,
            )

            all_stages.update(stages)
            sheet_korean.update(korean)

            print(
                f"  stages={len(stages)} "
                f"korean={len(korean)}"
            )

        except Exception as e:
            print(
                f"[Sheet error] {sheet}: {e}"
            )

    return all_stages, sheet_korean


# =========================================================
# 기존 JSON
# =========================================================

def load_existing():

    if not OUT.exists():
        return {}

    try:
        data = json.loads(
            OUT.read_text(
                encoding="utf-8"
            )
        )

        return data.get(
            "stages",
            {}
        )

    except Exception as e:
        print(
            "[JSON load error]",
            e,
        )

        return {}


# =========================================================
# 한국 DB 검색
# =========================================================

def search_db(jp_name):
    """
    DB 검색 결과에서 stage.php?sid=... 후보를 찾는다.
    """

    query = quote(jp_name)

    candidates = [
        f"{BASE}search.php?q={query}&lang=ko",
        f"{BASE}search.php?keyword={query}&lang=ko",
    ]

    sids = []

    for url in candidates:

        try:
            doc = get(url)

        except Exception:
            continue

        found = re.findall(
            r'stage\.php\?[^"\']*sid=([A-Za-z0-9_-]+)',
            doc,
            flags=re.I,
        )

        for sid in found:
            if sid not in sids:
                sids.append(sid)

        if sids:
            break

    return sids


# =========================================================
# 상세 페이지에서 JP / KO 이름 추출
# =========================================================

def parse_stage_page(sid):

    url = (
        f"{BASE}stage.php?"
        f"lang=ko&sid={quote(sid)}"
    )

    doc = get(url)

    # 페이지 전체 텍스트 후보
    texts = [
        clean(x)
        for x in re.findall(
            r">([^<>]{1,200})<",
            doc,
            flags=re.S,
        )
    ]

    texts = [
        x
        for x in texts
        if x
    ]

    ko = ""
    jp = ""

    # h1을 한국어 이름 우선 후보로 사용
    h1 = re.search(
        r"<h1[^>]*>(.*?)</h1>",
        doc,
        flags=re.S | re.I,
    )

    if h1:
        h1_text = clean(
            h1.group(1)
        )

        if valid_korean(h1_text):
            ko = h1_text

    # 일본어 문자열 탐색
    for text in texts:

        if (
            re.search(
                r"[ぁ-んァ-ン一-龯]",
                text,
            )
            and not re.search(
                r"[가-힣]",
                text,
            )
        ):
            jp = normalize_jp(
                text
            )

            break

    # h1이 아니더라도 한국어명 탐색
    if not ko:

        for text in texts:

            if valid_korean(text):
                ko = text
                break

    if not jp or not ko:
        return None

    return jp, ko


# =========================================================
# 일본어 이름 하나 조회
# =========================================================

def lookup_korean(jp_name):

    sids = search_db(jp_name)

    if not sids:
        return None

    normalized_target = normalize_jp(
        jp_name
    )

    # 검색 결과가 여러 개일 수 있으므로
    # 일본어 원문이 정확히 일치하는 것만 인정
    for sid in sids[:10]:

        try:
            pair = parse_stage_page(
                sid
            )

        except Exception as e:
            print(
                f"    sid={sid} error={e}"
            )

            continue

        if not pair:
            continue

        jp, ko = pair

        if (
            normalize_jp(jp)
            == normalized_target
            and valid_korean(ko)
        ):
            return ko

    return None


# =========================================================
# 메인
# =========================================================

def main():

    print(
        "=== Battle Cats Korean Stage Sync v3 ==="
    )

    # 현재 시트 스테이지
    all_stages, sheet_korean = (
        collect_sheet_data()
    )

    print()
    print(
        "Sheet stage count:",
        len(all_stages),
    )

    print(
        "Sheet Korean names:",
        len(sheet_korean),
    )

    # 기존 캐시
    stages = load_existing()

    print(
        "Existing cache:",
        len(stages),
    )

    # 시트 자체의 한국어명은 무조건 우선
    for jp, ko in sheet_korean.items():

        if jp in all_stages:
            stages[jp] = ko

    # 이미 번역된 것은 재검색하지 않는다.
    missing = sorted(
        stage
        for stage in all_stages
        if stage not in stages
    )

    print(
        "Need lookup:",
        len(missing),
    )

    found = 0
    not_found = []

    for index, jp in enumerate(
        missing,
        1,
    ):

        print(
            f"[{index}/{len(missing)}] "
            f"{jp}"
        )

        try:

            ko = lookup_korean(
                jp
            )

            if ko:

                stages[jp] = ko
                found += 1

                print(
                    "  ->",
                    ko,
                )

            else:

                not_found.append(
                    jp
                )

                print(
                    "  -> Korean version not found"
                )

        except Exception as e:

            not_found.append(
                jp
            )

            print(
                "  -> error:",
                e,
            )

        # 서버에 과도한 요청을 보내지 않도록
        # 아주 짧은 간격
        time.sleep(0.12)

    # 현재 시트에 존재하는 스테이지만 JSON에 유지
    # 예전에 삭제된 스테이지 데이터가 무한히 쌓이는 것을 방지
    filtered = {
        jp: ko
        for jp, ko in stages.items()
        if jp in all_stages
        and valid_korean(ko)
    }

    payload = {
        "source": BASE,
        "generated_by": (
            "scripts/update_stage_ko.py v3"
        ),
        "sheet_id": SHEET_ID,
        "sheet_stage_count": len(
            all_stages
        ),
        "count": len(
            filtered
        ),
        "untranslated_count": len(
            all_stages
        ) - len(filtered),
        "note": (
            "Google Sheet에 현재 존재하는 "
            "스테이지만 대상으로 한국판 명칭을 "
            "동기화합니다. 기존 번역은 캐시하며 "
            "한국판 명칭이 확인되지 않는 스테이지는 "
            "등록하지 않습니다."
        ),
        "stages": dict(
            sorted(
                filtered.items()
            )
        ),
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
        "=== Complete ==="
    )

    print(
        "New names:",
        found,
    )

    print(
        "Total Korean names:",
        len(filtered),
    )

    print(
        "Untranslated / unreleased:",
        len(all_stages)
        - len(filtered),
    )

    if not_found:

        print()
        print(
            "Not found:"
        )

        for stage in not_found:
            print(
                " -",
                stage,
            )


if __name__ == "__main__":
    main()
