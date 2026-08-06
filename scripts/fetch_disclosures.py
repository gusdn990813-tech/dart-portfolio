#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DART 포트폴리오 공시 수집기.

portfolio.json 의 종목코드를 읽어 OpenDART 공시검색 API를 호출하고,
결과를 docs/data/*.json 으로 저장합니다. 대시보드(docs/index.html)는
이 JSON만 읽으므로 브라우저 CORS 문제가 없습니다.

환경변수:
  DART_API_KEY  (필수)  https://opendart.fss.or.kr 에서 무료 발급

사용:
  python scripts/fetch_disclosures.py
  python scripts/fetch_disclosures.py --days 30 --force-corp-refresh
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


# ===================================================================
# 공시 중요도 분류 규칙  (키워드를 고치고 싶으면 이 블록만 수정하세요)
#   3 = 매우 중요 / 2 = 중요 / 1 = 참고 / 0 = 일반
# ===================================================================
# (카테고리, 중요도, [키워드들])
RULES = [
    # --- 위험 신호 ---------------------------------------------------------
    ("위험신호", 3, [
        "상장폐지", "관리종목", "투자주의환기", "거래정지", "매매거래정지",
        "부도", "당좌거래정지", "회생절차", "파산", "감사의견", "의견거절",
        "한정의견", "횡령", "배임", "자본잠식", "감사보고서제출(연결감사의견",
        "불성실공시법인", "조회공시요구",
    ]),

    # --- 자본 / 주식수 변동 ------------------------------------------------
    ("증자·CB", 3, [
        "유상증자결정", "유상증자", "전환사채권발행결정", "신주인수권부사채권발행결정",
        "교환사채권발행결정", "전환청구권행사", "신주인수권행사", "감자결정",
        "무상증자결정", "주식분할결정", "주식병합결정", "주식매수선택권부여",
        "출자전환", "채무재조정",
    ]),
    ("자기주식", 2, [
        "자기주식취득", "자기주식처분", "자기주식소각", "자기주식취득신탁계약",
    ]),

    # --- 실적 --------------------------------------------------------------
    ("실적", 3, [
        "매출액또는손익구조", "영업(잠정)실적", "연결재무제표기준영업(잠정)실적",
        "매출액또는손익구조30%", "결산실적공시",
    ]),
    ("정기보고서", 2, [
        "사업보고서", "반기보고서", "분기보고서",
        "감사보고서", "연결감사보고서", "내부회계관리제도",
    ]),

    # --- 지배구조 / M&A ----------------------------------------------------
    ("지배구조", 3, [
        "최대주주변경", "경영권", "회사합병결정", "회사분할결정", "분할합병",
        "주식교환", "포괄적교환", "영업양수", "영업양도", "타법인주식및출자증권취득",
        "타법인주식및출자증권처분", "공개매수",
    ]),
    ("지분변동", 2, [
        "주식등의대량보유상황보고서", "임원ㆍ주요주주특정증권등소유상황보고서",
        "임원·주요주주특정증권등소유상황보고서", "의결권대리행사권유",
    ]),

    # --- 사업 / 계약 -------------------------------------------------------
    ("계약·투자", 2, [
        "단일판매", "공급계약체결", "신규시설투자", "유형자산취득", "유형자산처분",
        "기술이전", "라이선스", "특허", "임상시험", "품목허가", "신약",
    ]),

    # --- 주주환원 ----------------------------------------------------------
    ("배당·주주환원", 2, [
        "현금ㆍ현물배당결정", "현금·현물배당결정", "배당결정", "주식배당결정",
        "주주환원",
    ]),

    # --- 기타 --------------------------------------------------------------
    ("주주총회", 1, [
        "주주총회소집", "주주총회결과", "정기주주총회", "임시주주총회",
    ]),
    ("소송·제재", 2, [
        "소송등의제기", "소송등의판결", "제재", "과징금", "벌금",
    ]),
    ("정정공시", 1, [
        "[기재정정]", "[첨부정정]", "[정정]",
    ]),
]

DEFAULT_CATEGORY = "기타"
DEFAULT_LEVEL = 0


def _norm(text: str) -> str:
    """비교용 정규화: 공백/특수기호 제거."""
    return (
        text.replace(" ", "")
        .replace("·", "")
        .replace("ㆍ", "")
        .replace("ㆍ", "")
        .replace("·", "")
    )


def classify(report_nm: str):
    """공시 제목을 받아 (카테고리, 중요도) 반환."""
    title = _norm(report_nm or "")
    is_correction = ("[기재정정]" in report_nm) or ("[첨부정정]" in report_nm)

    for category, level, keywords in RULES:
        for kw in keywords:
            if _norm(kw) in title:
                # 정정공시는 원 공시보다 한 단계 낮게
                if is_correction and category != "정정공시" and level > 1:
                    level -= 1
                return category, level
    return DEFAULT_CATEGORY, DEFAULT_LEVEL

# ===================================================================
# 여기서부터 수집 로직
# ===================================================================

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"
PORTFOLIO_FILE = ROOT / "portfolio.json"
CORP_MAP_FILE = DATA_DIR / "corp_map.json"
DISCLOSURES_FILE = DATA_DIR / "disclosures.json"
META_FILE = DATA_DIR / "meta.json"

API_BASE = "https://opendart.fss.or.kr/api"
KST = timezone(timedelta(hours=9))
CORP_MAP_MAX_AGE_DAYS = 7
REQUEST_PAUSE = 0.12  # 초 — API 예의상 간격

STATUS_MSG = {
    "000": "정상",
    "010": "등록되지 않은 인증키입니다",
    "011": "사용할 수 없는 인증키입니다 (일시적 사용중지)",
    "012": "접근할 수 없는 IP입니다",
    "013": "조회된 데이터가 없습니다",
    "014": "파일이 존재하지 않습니다",
    "020": "요청 제한을 초과했습니다 (일 20,000건)",
    "021": "조회 가능한 회사 개수가 초과했습니다",
    "100": "부적절한 필드 값입니다",
    "101": "부적절한 접근입니다",
    "800": "시스템 점검 중입니다",
    "900": "정의되지 않은 오류입니다",
    "901": "사용자 계정의 개인정보보유기간이 만료되었습니다",
}


def log(msg: str) -> None:
    print(f"[{datetime.now(KST):%H:%M:%S}] {msg}", flush=True)


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- 설정 읽기
def load_portfolio() -> dict:
    if not PORTFOLIO_FILE.exists():
        die(f"{PORTFOLIO_FILE} 이 없습니다.")
    cfg = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))

    entries = []
    for section, kind in (("portfolio", "보유"), ("watchlist", "관심")):
        for item in cfg.get(section) or []:
            if isinstance(item, str):
                item = {"ticker": item}
            ticker = str(item.get("ticker", "")).strip().zfill(6)
            if not ticker.isdigit() or len(ticker) != 6:
                log(f"  ! 종목코드 형식이 이상해서 건너뜀: {item!r}")
                continue
            entries.append({
                "ticker": ticker,
                "label": (item.get("label") or "").strip(),
                "group": (item.get("group") or "").strip(),
                "kind": kind,
            })

    # 중복 제거 (앞선 것 우선)
    seen, unique = set(), []
    for e in entries:
        if e["ticker"] in seen:
            continue
        seen.add(e["ticker"])
        unique.append(e)

    if not unique:
        die("portfolio.json 에 유효한 종목이 하나도 없습니다.")

    cfg["_entries"] = unique
    return cfg


# ------------------------------------------------------- 고유번호 매핑 관리
def corp_map_is_fresh() -> bool:
    if not CORP_MAP_FILE.exists():
        return False
    try:
        data = json.loads(CORP_MAP_FILE.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(data["fetched_at"])
    except Exception:
        return False
    age = datetime.now(timezone.utc) - fetched.astimezone(timezone.utc)
    return age < timedelta(days=CORP_MAP_MAX_AGE_DAYS)


def refresh_corp_map(api_key: str) -> dict:
    """DART 전체 고유번호 파일(zip)을 받아 상장사만 매핑으로 저장."""
    log("고유번호 매핑 갱신 중 (corpCode.xml)...")
    r = requests.get(
        f"{API_BASE}/corpCode.xml",
        params={"crtfc_key": api_key},
        timeout=60,
    )
    r.raise_for_status()

    if r.content[:2] != b"PK":  # zip이 아니면 에러 XML
        try:
            root = ET.fromstring(r.content.decode("utf-8", "replace"))
            status = (root.findtext("status") or "").strip()
            die(f"corpCode 요청 실패 [{status}] {STATUS_MSG.get(status, root.findtext('message'))}")
        except ET.ParseError:
            die("corpCode 응답을 해석할 수 없습니다.")

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
        xml_bytes = zf.read(name)

    root = ET.fromstring(xml_bytes.decode("utf-8", "replace"))
    mapping = {}
    for node in root.iter("list"):
        stock_code = (node.findtext("stock_code") or "").strip()
        if not stock_code:  # 비상장사 제외
            continue
        mapping[stock_code] = {
            "corp_code": (node.findtext("corp_code") or "").strip(),
            "corp_name": (node.findtext("corp_name") or "").strip(),
        }

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(mapping),
        "map": mapping,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CORP_MAP_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    log(f"  상장사 {len(mapping):,}개 매핑 저장")
    return payload


def get_corp_map(api_key: str, force: bool) -> dict:
    if not force and corp_map_is_fresh():
        data = json.loads(CORP_MAP_FILE.read_text(encoding="utf-8"))
        log(f"고유번호 매핑 캐시 사용 ({data['count']:,}개)")
        return data
    return refresh_corp_map(api_key)


# ----------------------------------------------------------- 공시 조회
def fetch_list(api_key: str, corp_code: str, bgn: str, end: str) -> list[dict]:
    """한 종목의 기간 내 공시 전체 (페이지네이션 포함)."""
    out, page = [], 1
    while True:
        r = requests.get(
            f"{API_BASE}/list.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": bgn,
                "end_de": end,
                "page_no": page,
                "page_count": 100,
                "sort": "date",
                "sort_mth": "desc",
            },
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        status = body.get("status")

        if status == "013":       # 데이터 없음
            break
        if status == "020":
            die("일일 API 호출 한도(20,000건)를 초과했습니다.")
        if status != "000":
            log(f"  ! [{status}] {STATUS_MSG.get(status, body.get('message'))}")
            break

        out.extend(body.get("list") or [])
        if page >= int(body.get("total_page") or 1):
            break
        page += 1
        time.sleep(REQUEST_PAUSE)
    return out


def normalize(raw: dict, entry: dict) -> dict:
    report_nm = (raw.get("report_nm") or "").strip()
    category, level = classify(report_nm)
    rcept_no = (raw.get("rcept_no") or "").strip()
    rcept_dt = (raw.get("rcept_dt") or "").strip()
    return {
        "rcept_no": rcept_no,
        "date": f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}" if len(rcept_dt) == 8 else rcept_dt,
        "ticker": entry["ticker"],
        "name": entry["label"] or (raw.get("corp_name") or "").strip(),
        "group": entry["group"],
        "kind": entry["kind"],
        "market": {"Y": "코스피", "K": "코스닥", "N": "코넥스", "E": "기타"}.get(
            (raw.get("corp_cls") or "").strip(), ""
        ),
        "title": report_nm,
        "filer": (raw.get("flr_nm") or "").strip(),
        "remark": (raw.get("rm") or "").strip(),
        "category": category,
        "level": level,
        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
    }


# ------------------------------------------------------------------ 병합
def merge(existing: list[dict], fresh: list[dict], keep_days: int):
    by_id = {d["rcept_no"]: d for d in existing}
    known = set(by_id)

    new_ids = []
    for d in fresh:
        if d["rcept_no"] not in known:
            new_ids.append(d["rcept_no"])
        by_id[d["rcept_no"]] = d  # 최신 분류 규칙으로 덮어쓰기

    cutoff = (datetime.now(KST) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    merged = [d for d in by_id.values() if d["date"] >= cutoff]
    merged.sort(key=lambda d: (d["date"], d["rcept_no"]), reverse=True)
    return merged, new_ids


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="조회 기간(일). 기본은 portfolio.json 값")
    ap.add_argument("--force-corp-refresh", action="store_true", help="고유번호 매핑 강제 갱신")
    args = ap.parse_args()

    api_key = (os.environ.get("DART_API_KEY") or "").strip()
    if not api_key:
        die("환경변수 DART_API_KEY 가 설정되지 않았습니다. "
            "https://opendart.fss.or.kr 에서 발급 후 설정하세요.")

    cfg = load_portfolio()
    entries = cfg["_entries"]
    lookback = args.days or int(cfg.get("lookback_days") or 90)
    keep_days = int(cfg.get("keep_days") or 365)

    now = datetime.now(KST)
    bgn = (now - timedelta(days=lookback)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    log(f"대상 {len(entries)}종목 / 기간 {bgn}~{end}")

    corp_map = get_corp_map(api_key, args.force_corp_refresh)["map"]

    fresh, unresolved = [], []
    for i, entry in enumerate(entries, 1):
        info = corp_map.get(entry["ticker"])
        if not info:
            unresolved.append(entry["ticker"])
            log(f"  ({i}/{len(entries)}) {entry['ticker']} — DART 상장사 목록에 없음, 건너뜀")
            continue
        if not entry["label"]:
            entry["label"] = info["corp_name"]

        try:
            rows = fetch_list(api_key, info["corp_code"], bgn, end)
        except requests.RequestException as e:
            log(f"  ({i}/{len(entries)}) {entry['label']} — 요청 실패: {e}")
            continue

        fresh.extend(normalize(r, entry) for r in rows)
        log(f"  ({i}/{len(entries)}) {entry['label']} — {len(rows)}건")
        time.sleep(REQUEST_PAUSE)

    existing = []
    if DISCLOSURES_FILE.exists():
        try:
            existing = json.loads(DISCLOSURES_FILE.read_text(encoding="utf-8")).get("items", [])
        except Exception:
            existing = []

    merged, new_ids = merge(existing, fresh, keep_days)
    new_set = set(new_ids)
    for d in merged:
        d["is_new"] = d["rcept_no"] in new_set

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DISCLOSURES_FILE.write_text(
        json.dumps({"items": merged}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    meta = {
        "updated_at": now.isoformat(),
        "updated_at_display": now.strftime("%Y-%m-%d %H:%M KST"),
        "range": {"from": bgn, "to": end, "lookback_days": lookback, "keep_days": keep_days},
        "total": len(merged),
        "new_count": len(new_ids),
        "unresolved_tickers": unresolved,
        "holdings": [
            {"ticker": e["ticker"], "label": e["label"], "group": e["group"], "kind": e["kind"]}
            for e in entries
        ],
    }
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    log(f"완료 — 전체 {len(merged):,}건, 신규 {len(new_ids)}건")
    if unresolved:
        log(f"매핑 실패 종목코드: {', '.join(unresolved)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
