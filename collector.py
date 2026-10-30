import os
import json
import re
from datetime import datetime, timedelta
import requests

# 코드에 직접 적지 않고, 환경변수에서 안전하게 가져옴
DART_API_KEY = os.environ.get("DART_API_KEY")


def fetch_dart_ipo_data(api_key):
    """
    DART Open API를 통해 증권신고서 및 신규상장 관련 공시 수집
    """
    if not api_key or api_key == "YOUR_DART_API_KEY_HERE":
        print("경고: DART_API_KEY가 설정되지 않았습니다. API 키를 입력해주세요.")
        return []

    # DART API 제한에 맞춰 검색 기간을 3개월(90일)로 설정
    today = datetime.now()
    start_date = (today - timedelta(days=90)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    url = "https://opendart.fss.or.kr/api/list.json"
    
    params = {
        "crtfc_key": api_key,
        "bgn_de": start_date,
        "end_de": end_date,
        "page_count": 100
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    stocks = []

    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            status = data.get("status")
            
            if status != "000":
                print(f"DART API 오류 [코드 {status}]: {data.get('message')}")
                return []

            raw_items = data.get("list", [])
            seen_companies = set()

            for idx, item in enumerate(raw_items):
                corp_name = item.get("corp_name", "").strip()
                report_nm = item.get("report_nm", "")
                rcept_dt = item.get("rcept_dt", "")  # 공시 접수일자 (YYYYMMDD)

                # IPO 관련 핵심 공시 키워드 필터링 (증권신고서, 투자설명서, 신규상장)
                if not any(keyword in report_nm for keyword in ["증권신고서", "투자설명서", "신규상장"]):
                    continue

                if not corp_name or corp_name in seen_companies:
                    continue
                seen_companies.add(corp_name)

                is_spac = ("스팩" in corp_name) or ("SPAC" in corp_name.upper())

                sub_date = normalize_date(rcept_dt)
                price = 2000 if is_spac else 0
                inst_ratio = 0.0
                lockup_ratio = 15.0 if is_spac else 5.0
                float_billion = 90 if is_spac else 500
                existing_ratio = 0.0 if is_spac else 30.0

                score, grade, review = calculate_score(inst_ratio, lockup_ratio, float_billion, existing_ratio, is_spac)

                stocks.append({
                    "id": f"dart-{idx}",
                    "corpCode": item.get("corp_code", ""),
                    "name": corp_name,
                    "isSpac": is_spac,
                    "reportTitle": report_nm,
                    "receiptDate": sub_date,
                    "price": price,
                    "bandStatus": "확정" if price > 0 else "공시참조",
                    "institutionalRatio": inst_ratio,
                    "lockupRatio": lockup_ratio,
                    "floatAmountBillion": float_billion,
                    "existingShareholderRatio": existing_ratio,
                    "underwriter": "공시문서 참조",
                    "flrNm": item.get("flr_nm", ""),
                    "score": score,
                    "grade": grade,
                    "summaryReview": f"DART 공시 제출기업 ({report_nm})"
                })

            print(f"DART API 호출 성공: 총 {len(stocks)}개 공모주 관련 기업 수집")
        else:
            print(f"DART API 응답 실패 코드: {res.status_code}")
    except Exception as e:
        print(f"네트워크 오류: {e}")

    return stocks


def normalize_date(d_str):
    if not d_str:
        return ""
    m = re.search(r'(\d{4})[\.\-/]?(\d{2})[\.\-/]?(\d{2})', str(d_str))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def calculate_score(inst_ratio, lockup_ratio, float_amt_billion, existing_ratio, is_spac):
    if is_spac:
        return 85, "STRONG_BUY", "스팩(공모가 2,000원 보장)으로 안정적 수급 성격."
    score = 0
    reasons = []
    if inst_ratio >= 1000:
        score += 35
        reasons.append("기관경쟁률 1,000:1 흥행")
    elif inst_ratio >= 500:
        score += 25
    elif inst_ratio > 0:
        score += 15
    else:
        score += 10

    if lockup_ratio >= 10:
        score += 30
    else:
        score += 10

    if float_amt_billion <= 500:
        score += 25
        reasons.append("유통금액 가벼움")
    else:
        score += 10

    if existing_ratio <= 30:
        score += 10

    if score >= 80:
        grade = "STRONG_BUY"
    elif score >= 60:
        grade = "NEUTRAL"
    else:
        grade = "AVOID"

    return score, grade, ". ".join(reasons)


if __name__ == "__main__":
    real_data = fetch_dart_ipo_data(DART_API_KEY)

    output = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalCount": len(real_data),
        "stocks": real_data
    }

    with open("ipo_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("ipo_data.json 저장 완료!")
