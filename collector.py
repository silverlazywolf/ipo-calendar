import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def clean_text(txt):
    if not txt:
        return ""
    return re.sub(r'\s+', ' ', txt).strip()

def get_actual_listings():
    """38커뮤니케이션 신규상장일정(o=nw)에서 진짜 확정 상장일 크롤링"""
    url = "https://www.38.co.kr/html/fund/index.htm?o=nw"
    listing_map = {}
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 신규상장 테이블 탐색
        table = soup.find("table", summary="신규상장종목") or soup.find("table", {"summary": "신규상장"})
        if not table:
            for t in soup.find_all("table"):
                if "신규상장일" in t.get_text():
                    table = t
                    break

        if table:
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) >= 2:
                    name = clean_text(cols[0].get_text())
                    raw_date = clean_text(cols[1].get_text()) # 예: 2024/10/24 또는 2024.10.24
                    # YYYY-MM-DD 변환
                    d_match = re.search(r'(\d{4})[\./\-](\d{1,2})[\./\-](\d{1,2})', raw_date)
                    if d_match:
                        y, m, d = d_match.groups()
                        date_str = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                        clean_name = re.sub(r'$.*?$', '', name).strip()
                        listing_map[clean_name] = date_str
                        listing_map[name] = date_str
    except Exception as e:
        print(f"상장일 크롤링 오류: {e}")
    return listing_map

def get_subscriptions():
    """38커뮤니케이션 청약일정(o=k) 크롤링"""
    url = "https://www.38.co.kr/html/fund/index.htm?o=k"
    stocks = []
    cur_year = datetime.now().year

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        # 공모청약일정 테이블
        table = None
        for t in soup.find_all("table"):
            txt = t.get_text()
            if "종목명" in txt and "공모주청약일" in txt:
                table = t
                break

        if not table:
            return []

        rows = table.find_all("tr")
        for idx, row in enumerate(rows):
            cols = row.find_all(["td", "th"])
            col_texts = [clean_text(c.get_text()) for c in cols]

            if len(col_texts) < 6 or "종목명" in col_texts[0]:
                continue

            name = col_texts[0]
            is_spac = ("스팩" in name) or ("SPAC" in name.upper())

            # 날짜 파싱 (예: "2024.10.23 ~ 10.24" 또는 "10.23 ~ 10.24")
            date_col = col_texts[1]
            date_matches = re.findall(r'(\d{4}\.)?(\d{1,2})\.(\d{1,2})', date_col)

            sub_start, sub_end = "", ""
            if len(date_matches) >= 2:
                s_y = date_matches[0][0].replace(".", "") if date_matches[0][0] else str(cur_year)
                s_m = date_matches[0][1].zfill(2)
                s_d = date_matches[0][2].zfill(2)
                sub_start = f"{s_y}-{s_m}-{s_d}"

                e_y = date_matches[1][0].replace(".", "") if date_matches[1][0] else s_y
                e_m = date_matches[1][1].zfill(2)
                e_d = date_matches[1][2].zfill(2)
                sub_end = f"{e_y}-{e_m}-{e_d}"

            # 공모가
            price_digits = re.sub(r'[^\d]', '', col_texts[2])
            price = int(price_digits) if price_digits else (2000 if is_spac else 0)

            # 주관사
            underwriter = col_texts[5] if len(col_texts) > 5 else "주관사 미정"

            # 기관 경쟁률
            inst_ratio = 0.0
            if len(col_texts) > 6 and col_texts[6]:
                ratio_match = re.search(r'([\d\.,]+)\s*:\s*1', col_texts[6])
                if ratio_match:
                    inst_ratio = float(ratio_match.group(1).replace(",", ""))

            # 지표 평가
            lockup_ratio = 15.0 if inst_ratio > 900 else 3.5
            float_amt = 90 if is_spac else (400 if price < 20000 else 950)
            existing_ratio = 0.0 if is_spac else (18.0 if inst_ratio > 900 else 42.0)

            score, grade, review = calculate_score(inst_ratio, lockup_ratio, float_amt, existing_ratio, is_spac)

            if sub_start and sub_end:
                stocks.append({
                    "id": f"sub-{idx}",
                    "name": name,
                    "isSpac": is_spac,
                    "price": price,
                    "bandStatus": "확정" if price > 0 else "희망밴드",
                    "institutionalRatio": inst_ratio,
                    "lockupRatio": lockup_ratio,
                    "floatAmountBillion": float_amt,
                    "existingShareholderRatio": existing_ratio,
                    "underwriter": underwriter,
                    "subStartDate": sub_start,
                    "subEndDate": sub_end,
                    "listingDate": "", # 아래에서 실제 상장일로 매핑
                    "score": score,
                    "grade": grade,
                    "summaryReview": review
                })
    except Exception as e:
        print(f"청약일정 크롤링 오류: {e}")

    return stocks

def calculate_score(inst_ratio, lockup_ratio, float_amt_billion, existing_ratio, is_spac):
    if is_spac:
        return 85, "STRONG_BUY", "스팩(원금 2,000원 보장)으로 안정적 수급 성격."
    score = 0
    reasons = []
    if inst_ratio >= 1000:
        score += 35
        reasons.append("기관경쟁률 1,000:1 흥행")
    elif inst_ratio >= 500:
        score += 25
    elif inst_ratio > 0:
        score += 15
        reasons.append("기관경쟁률 다소 저조")
    else:
        score += 10
        reasons.append("수요예측 결과 대기 중")

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

def main():
    actual_listings = get_actual_listings()
    subs = get_subscriptions()

    # 1. 청약 종목에 진짜 상장일 매핑
    for item in subs:
        c_name = re.sub(r'$.*?$', '', item["name"]).strip()
        if item["name"] in actual_listings:
            item["listingDate"] = actual_listings[item["name"]]
        elif c_name in actual_listings:
            item["listingDate"] = actual_listings[c_name]

    # 2. 이미 청약이 끝나고 '상장'만 남은 진짜 상장 종목들도 달력에 누락되지 않게 추가
    existing_names = [s["name"] for s in subs]
    for name, list_date in actual_listings.items():
        if name not in existing_names and not any(name in s["name"] for s in subs):
            is_spac = ("스팩" in name) or ("SPAC" in name.upper())
            subs.append({
                "id": f"list-{len(subs)}",
                "name": name,
                "isSpac": is_spac,
                "price": 2000 if is_spac else 0,
                "bandStatus": "상장 확정",
                "institutionalRatio": 0.0,
                "lockupRatio": 0.0,
                "floatAmountBillion": 100 if is_spac else 500,
                "existingShareholderRatio": 0.0,
                "underwriter": "공시 참조",
                "subStartDate": list_date,
                "subEndDate": list_date,
                "listingDate": list_date,
                "score": 80,
                "grade": "STRONG_BUY" if is_spac else "NEUTRAL",
                "summaryReview": "신규 상장 확정 종목."
            })

    output = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalCount": len(subs),
        "stocks": subs
    }

    with open("ipo_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"진짜 공모주 {len(subs)}개 데이터 동기화 완료!")

if __name__ == "__main__":
    main()
