#!/usr/bin/env python3
import csv, io, json, re, time, html as htmlmod
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup

SHEET_ID = '12bhVk1tfC9N-U2eU9xie-XoW2gw85acQAukR-W2k3KY'
SHEETS = ['旧レ','真レ','零レ','塔','降臨','強襲','超獣','開眼','コラボ','他']
BASE = 'https://battlecats.anypupil.com/'
START = BASE + 'stages.php?lang=ko'
OUT = Path(__file__).resolve().parents[1] / 'stage-ko.json'
UA = 'Mozilla/5.0 (compatible; BattleCatsStageNameSync/5.0; +GitHubActions)'
TIMEOUT = 30
SLEEP = 0.04

session = requests.Session()
session.headers.update({
    'User-Agent': UA,
    'Accept-Language': 'ko-KR,ko;q=0.9,ja;q=0.8'
})


def norm(s):
    return re.sub(
        r'\s+', ' ',
        str(s or '').replace('\u3000', ' ')
    ).strip()


def has_ko(s):
    return bool(re.search(r'[가-힣]', s or ''))


def has_jp(s):
    return bool(re.search(r'[ぁ-んァ-ン一-龯々]', s or ''))


def has_cjk_no_ko(s):
    return (
        bool(re.search(r'[\u3400-\u9fff]', s or ''))
        and not has_ko(s)
    )


def valid_ko(s):
    s = norm(s)

    if not s or not has_ko(s):
        return False

    if any(x in s.lower() for x in [
        '미명명',
        'unknown',
        'unnamed',
        '不明'
    ]):
        return False

    return True


def get(url):
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or 'utf-8'
    return r.text


def sheet_url(name):
    return (
        f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?'
        + urlencode({
            'tqx': 'out:csv',
            'sheet': name
        })
    )


def find_left(header, start, label):
    for c in range(start - 1, -1, -1):
        if norm(header[c] if c < len(header) else '') == label:
            return c

    return None


def collect_sheet_records():
    records = []

    for tab in SHEETS:
        print('[SHEET]', tab)

        rows = list(
            csv.reader(
                io.StringIO(
                    get(sheet_url(tab))
                )
            )
        )

        if not rows:
            continue

        h = [norm(x) for x in rows[0]]

        pcols = [
            i for i, x in enumerate(h)
            if x == 'プレイヤー'
        ]

        for pc in pcols:
            sc = find_left(h, pc, 'ステージ')
            mc = find_left(
                h,
                sc if sc is not None else pc,
                'マップ'
            )

            if sc is None:
                continue

            for row in rows[1:]:
                if pc >= len(row) or not norm(row[pc]):
                    continue

                stage = norm(
                    row[sc] if sc < len(row) else ''
                )

                mapjp = norm(
                    row[mc]
                    if mc is not None and mc < len(row)
                    else ''
                )

                if stage:
                    records.append({
                        'tab': tab,
                        'map': mapjp,
                        'stage': stage
                    })

    # 같은 문맥의 중복 제거
    seen = set()
    out = []

    for r in records:
        k = (
            r['tab'],
            r['map'],
            r['stage']
        )

        if k not in seen:
            seen.add(k)
            out.append(r)

    print(
        'Sheet contextual stages:',
        len(out)
    )

    print(
        'Sheet unique stage names:',
        len({r['stage'] for r in out})
    )

    return out


def load_existing():
    if not OUT.exists():
        return {}, {}

    try:
        j = json.loads(
            OUT.read_text(encoding='utf-8')
        )

        simple = {
            norm(k): norm(v)
            for k, v in j.get('stages', {}).items()
            if valid_ko(v)
        }

        ctx = {
            norm(k): norm(v)
            for k, v in j.get(
                'context_stages', {}
            ).items()
            if valid_ko(v)
        }

        return simple, ctx

    except Exception as e:
        print('Existing JSON error:', e)
        return {}, {}


def soup(url):
    time.sleep(SLEEP)

    return BeautifulSoup(
        get(url),
        'html.parser'
    )


def hrefs(s):
    for a in s.find_all('a', href=True):
        yield urljoin(
            BASE,
            htmlmod.unescape(a['href'])
        )


def discover_map_urls():
    print('\n[1/5] Discovering map pages...')

    q = deque([START])
    visited = set()
    maps = set()

    while q and len(visited) < 600:
        url = q.popleft()

        if url in visited:
            continue

        visited.add(url)

        try:
            s = soup(url)

        except Exception as e:
            print(
                ' index error:',
                url,
                e
            )
            continue

        for u in hrefs(s):
            p = urlparse(u)

            if p.netloc != 'battlecats.anypupil.com':
                continue

            if (
                p.path.endswith('/stage_map.php')
                or p.path.endswith('stage_map.php')
            ):
                qs = parse_qs(p.query)

                if qs.get('id'):
                    maps.add(
                        BASE
                        + 'stage_map.php?'
                        + urlencode({
                            'id': qs['id'][0],
                            'lang': 'ko'
                        })
                    )

                continue

            # 스테이지 상세 페이지는 따라가지 않고
            # 스테이지 목록/카테고리 페이지만 탐색
            name = p.path.rsplit('/', 1)[-1]

            if (
                name == 'stages.php'
                or (
                    name.startswith('stage_')
                    and name not in {
                        'stage.php',
                        'stage_map.php'
                    }
                )
            ):
                qs = parse_qs(p.query)
                qs['lang'] = ['ko']

                flat = {
                    k: v[0]
                    for k, v in qs.items()
                    if v
                }

                nu = (
                    f'{p.scheme or "https"}://'
                    f'{p.netloc}{p.path}?'
                    f'{urlencode(flat)}'
                )

                if nu not in visited:
                    q.append(nu)

    print(
        'Map pages:',
        len(maps),
        'index pages:',
        len(visited)
    )

    return sorted(maps)


def first_heading(s):
    h = s.find('h1')

    return (
        norm(h.get_text(' ', strip=True))
        if h else ''
    )


def japanese_subtitle_near_heading(
    s,
    heading
):
    h = s.find('h1')

    if not h:
        return ''

    # 현지화된 H1 뒤에 있는
    # 일본어 원문을 탐색
    for el in h.find_all_next(limit=12):
        if el is h:
            continue

        t = norm(
            el.get_text(
                ' ',
                strip=True
            )
        )

        if (
            not t
            or t == heading
            or len(t) > 160
        ):
            continue

        if has_jp(t) and not has_ko(t):
            return t

    return ''


def stage_cards_from_map(s):
    out = []
    seen = set()

    for a in s.find_all('a', href=True):
        u = urljoin(BASE, a['href'])
        p = urlparse(u)

        if not p.path.endswith('stage.php'):
            continue

        sid = (
            parse_qs(p.query).get('sid')
            or ['']
        )[0]

        if not sid or sid in seen:
            continue

        seen.add(sid)

        # 링크에서 위로 올라가며
        # 해당 STAGE 카드 영역 탐색
        node = a
        card = None

        for _ in range(7):
            node = node.parent

            if not node:
                break

            text = norm(
                node.get_text(
                    '\n',
                    strip=True
                )
            )

            if (
                re.search(
                    r'STAGE\s*\d+',
                    text,
                    re.I
                )
                and len(text) < 1800
            ):
                card = node
                break

        ko = ''
        jp = ''

        if card:
            hs = card.find_all([
                'h2',
                'h3',
                'h4',
                'h5',
                'strong'
            ])

            for h in hs:
                t = norm(
                    h.get_text(
                        ' ',
                        strip=True
                    )
                )

                if valid_ko(t) and not ko:
                    ko = t

            texts = [
                norm(x)
                for x in card.stripped_strings
            ]

            for t in texts:
                if (
                    not t
                    or re.match(
                        r'^STAGE\s*\d+$',
                        t,
                        re.I
                    )
                ):
                    continue

                if (
                    has_jp(t)
                    and not has_ko(t)
                    and len(t) < 140
                ):
                    jp = t
                    break

        out.append((
            sid,
            jp,
            ko
        ))

    return out


def parse_stage_page(sid):
    url = (
        BASE
        + 'stage.php?'
        + urlencode({
            'lang': 'ko',
            'sid': sid
        })
    )

    s = soup(url)

    ko = first_heading(s)

    jp = japanese_subtitle_near_heading(
        s,
        ko
    )

    return jp, ko


def crawl_db(needed_stage_names):
    maps = discover_map_urls()

    print('\n[2/5] Reading map pages...')

    db = []

    for i, url in enumerate(maps, 1):
        try:
            s = soup(url)

            mapko = first_heading(s)

            mapjp = japanese_subtitle_near_heading(
                s,
                mapko
            )

            cards = stage_cards_from_map(s)

            for sid, jp, ko in cards:

                # 맵 카드에서 충분한 정보를
                # 얻지 못한 경우에만
                # 상세 페이지 확인
                if (
                    not jp
                    or jp in needed_stage_names
                ):
                    try:
                        pjp, pko = parse_stage_page(
                            sid
                        )

                        jp = jp or pjp
                        ko = ko or pko

                    except Exception:
                        pass

                if jp:
                    db.append({
                        'map_jp': norm(mapjp),
                        'map_ko': norm(mapko),
                        'stage_jp': norm(jp),
                        'stage_ko': norm(ko),
                        'sid': sid
                    })

        except Exception as e:
            print(
                ' map error:',
                url,
                e
            )

        if i % 100 == 0:
            print(
                f'  maps {i}/{len(maps)} '
                f'records={len(db)}'
            )

    print(
        'DB stage records:',
        len(db)
    )

    return db


def build_maps(
    records,
    db,
    old_simple,
    old_ctx
):
    by_stage = defaultdict(list)
    by_map_stage = defaultdict(list)

    for d in db:
        if valid_ko(d['stage_ko']):
            by_stage[
                d['stage_jp']
            ].append(d)

            by_map_stage[
                (
                    d['map_jp'],
                    d['stage_jp']
                )
            ].append(d)

    simple = dict(old_simple)
    ctx = dict(old_ctx)

    unresolved = []
    ambiguous = []

    for r in records:
        tab = r['tab']
        mapjp = r['map']
        stage = r['stage']

        ck = (
            f'{tab}|'
            f'{mapjp}|'
            f'{stage}'
        )

        mk = (
            f'{mapjp}|'
            f'{stage}'
        )

        ko = (
            ctx.get(ck)
            or ctx.get(mk)
            or simple.get(stage, '')
        )

        # 1순위:
        # 맵 + 스테이지 문맥 일치
        cands = by_map_stage.get(
            (mapjp, stage),
            []
        )

        vals = {
            d['stage_ko']
            for d in cands
            if valid_ko(d['stage_ko'])
        }

        if len(vals) == 1:
            ko = next(iter(vals))

        elif not ko:
            # 2순위:
            # 같은 일본어 스테이지명이
            # DB 전체에서 단 하나의
            # 한국어명으로만 대응되는 경우
            vals = {
                d['stage_ko']
                for d in by_stage.get(
                    stage,
                    []
                )
                if valid_ko(
                    d['stage_ko']
                )
            }

            if len(vals) == 1:
                ko = next(iter(vals))

            elif len(vals) > 1:
                ambiguous.append({
                    'tab': tab,
                    'map': mapjp,
                    'stage': stage,
                    'candidates': sorted(vals)
                })

        if ko:
            ctx[ck] = ko

        else:
            unresolved.append({
                'tab': tab,
                'map': mapjp,
                'stage': stage
            })

    # 일본어 스테이지명 하나가
    # 한국어명 하나로만 확정되는 경우에만
    # 단순 매핑에 저장
    for stage, items in by_stage.items():
        vals = {
            d['stage_ko']
            for d in items
            if valid_ko(d['stage_ko'])
        }

        if len(vals) == 1:
            simple[stage] = next(
                iter(vals)
            )

    return (
        simple,
        ctx,
        unresolved,
        ambiguous
    )


def main():
    print(
        '=== Battle Cats Korean '
        'Stage Sync v5 ==='
    )

    records = collect_sheet_records()

    old_simple, old_ctx = load_existing()

    needed = {
        r['stage']
        for r in records
        if r['stage'] not in old_simple
    }

    print(
        'Existing simple translations:',
        len(old_simple),
        'need lookup names:',
        len(needed)
    )

    db = crawl_db(needed)

    print(
        '\n[3/5] Matching sheet context...'
    )

    (
        simple,
        ctx,
        unresolved,
        ambiguous
    ) = build_maps(
        records,
        db,
        old_simple,
        old_ctx
    )

    print(
        '\n[4/5] Writing JSON...'
    )

    payload = {
        'source': BASE,
        'generated_by':
            'scripts/update_stage_ko.py v5',
        'sheet_id': SHEET_ID,
        'sheet_context_count':
            len(records),
        'count':
            len(simple),
        'context_count':
            len(ctx),
        'untranslated_count':
            len(unresolved),
        'ambiguous_count':
            len(ambiguous),
        'note':
            '검증된 한국어명만 저장합니다. '
            '조회는 category|map|stage 문맥을 '
            '우선하고, 고유한 stage 이름만 '
            '단순 키로 보조합니다.',
        'stages':
            dict(sorted(simple.items())),
        'context_stages':
            dict(sorted(ctx.items())),
        'untranslated':
            unresolved,
        'ambiguous':
            ambiguous,
    }

    OUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ) + '\n',
        encoding='utf-8'
    )

    print('\n[5/5] Complete')

    print(
        'Simple:',
        len(simple),
        'Context:',
        len(ctx),
        'Untranslated:',
        len(unresolved),
        'Ambiguous:',
        len(ambiguous)
    )

    if unresolved:
        print(
            '\nUNRESOLVED '
            '(first 100):'
        )

        for x in unresolved[:100]:
            print(
                ' -',
                x['tab'],
                '|',
                x['map'],
                '|',
                x['stage']
            )


if __name__ == '__main__':
    main()
