import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def parse_38_calendar():
    """
    38커뮤니케이션 실제 공모주 청약일정 실시간 크롤링
    URL: https://www.38.co.kr/html/fund/index.htm?o=k
    """
    url = "https://www.38.co.kr/html/fund/index.htm?o=k"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }

    stocks = []
    current_year = datetime.now().year

    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        # 메인 테이블 찾기
        tables = soup.find_all("table")
        target_table = None

        for t in tables:
            header_text = t.get_text()
            if "종목명" in header_text and "공모주청약일" in header_text:
                target_table = t
                break

        if not target_table:
            print("테이블을 찾을 수 없습니다.")
            return []

        rows = target_table.find_all("tr")
        for idx, row in enumerate(rows):
            cols = row.find_all(["td", "th"])
            col_texts = [clean_text(c.get_text()) for c in cols]

            # 헤더 행 건너뛰기
            if len(col_texts) < 6 or "종목명" in col_texts[0]:
                continue

            name = col_texts[0]
            # 스팩주 여부 판별
            is_spac = ("스팩" in name) or ("SPAC" in name.upper())

            # 공모청약일 파싱 (예: "2024.10.23 ~ 10.24" 또는 "10.23 ~ 10.24")
            date_col = col_texts[1]
            sub_start = ""
            sub_end = ""
            date_matches = re.findall(r'(\d{4}\.)?(\d{1,2})\.(\d{1,2})', date_col)

            if len(date_matches) >= 2:
                # 시작일
                s_y = date_matches[0][0].replace(".", "") if date_matches[0][0] else str(current_year)
                s_m = date_matches[0][1].zfill(2)
                s_d = date_matches[0][2].zfill(2)
                sub_start = f"{s_y}-{s_m}-{s_d}"

                # 마감일
                e_y = date_matches[1][0].replace(".", "") if date_matches[1][0] else s_y
                e_m = date_matches[1][1].zfill(2)
                e_d = date_matches[1][2].zfill(2)
                sub_end = f"{e_y}-{e_m}-{e_d}"

            # 확정공모가 (예: "18,000")
            price_str = re.sub(r'[^\d]', '', col_texts[2])
            price = int(price_str) if price_str else (2000 if is_spac else 0)

            # 주관사
            underwriter = col_texts[5] if len(col_texts) > 5 else "주관사 미정"

            # 기관경쟁률
            inst_ratio = 0.0
            if len(col_texts) > 6 and col_texts[6]:
                ratio_match = re.search(r'([\d\.,]+)\s*:\s*1', col_texts[6])
                if ratio_match:
                    inst_ratio = float(ratio_match.group(1).replace(",", ""))

            # 기본 지표 추정 및 스코어 계산
            lockup_ratio = 12.5 if inst_ratio > 800 else 3.2
            float_billion = 90 if is_spac else (450 if price < 25000 else 1100)
            existing_ratio = 0.0 if is_spac else (22.0 if inst_ratio > 800 else 45.0)

            score, grade, review = calculate_score(inst_ratio, lockup_ratio, float_billion, existing_ratio, is_spac)

            # 상장일 추정 (청약 마감일 기준 약 9일~10일 뒤)
            listing_date = ""
            if sub_end:
                try:
                    end_dt = datetime.strptime(sub_end, "%Y-%m-%d")
                    # 통상 청약 마감 8~10일 뒤 상장
                    from datetime import timedelta
                    listing_dt = end_dt + timedelta(days=9)
                    # 주말일 경우 월요일로 보정
                    if listing_dt.weekday() == 5:
                        listing_dt += timedelta(days=2)
                    elif listing_dt.weekday() == 6:
                        listing_dt += timedelta(days=1)
                    listing_date = listing_dt.strftime("%Y-%m-%d")
                except:
                    pass

            if sub_start and sub_end:
                stocks.append({
                    "id": f"real-{idx}",
                    "name": name,
                    "isSpac": is_spac,
                    "price": price,
                    "bandStatus": "확정" if price > 0 else "미정",
                    "institutionalRatio": inst_ratio,
                    "lockupRatio": lockup_ratio,
                    "floatAmountBillion": float_billion,
                    "existingShareholderRatio": existing_ratio,
                    "underwriter": underwriter,
                    "subStartDate": sub_start,
                    "subEndDate": sub_end,
                    "listingDate": listing_date,
                    "score": score,
                    "grade": grade,
                    "summaryReview": review
                })

    except Exception as e:
        print(f"크롤링 오류 발생: {e}")

    return stocks

def calculate_score(inst_ratio, lockup_ratio, float_amt_billion, existing_ratio, is_spac):
    if is_spac:
        return 85, "STRONG_BUY", "스팩(공모가 2,000원 고정)으로 원금 리스크가 극히 적음."

    score = 0
    reasons = []

    if inst_ratio >= 1000:
        score += 35
        reasons.append("기관경쟁률 1,000:1 이상 흥행")
    elif inst_ratio >= 500:
        score += 25
    elif inst_ratio > 0:
        score += 15
        reasons.append("기관경쟁률 다소 저조")
    else:
        score += 10
        reasons.append("기관경쟁률 미발표 상태")

    if lockup_ratio >= 10:
        score += 30
    else:
        score += 10

    if float_amt_billion <= 500:
        score += 25
        reasons.append("유통금액 가벼움")
    else:
        score += 10
        reasons.append("유통금액 다소 무거움")

    if existing_ratio <= 30:
        score += 10
    else:
        score += 0

    if score >= 80:
        grade = "STRONG_BUY"
    elif score >= 60:
        grade = "NEUTRAL"
    else:
        grade = "AVOID"

    return score, grade, ". ".join(reasons)

if __name__ == "__main__":
    real_stocks = parse_38_calendar()
    output = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalCount": len(real_stocks),
        "stocks": real_stocks
    }
    with open("ipo_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"총 {len(real_stocks)}개 실제 종목 수집 완료!")
