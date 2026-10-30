import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

def clean_txt(t):
    return re.sub(r'\s+', ' ', t).strip() if t else ""

def get_naver_ipo_data():
    """네이버페이 증권 공모주 청약/상장 일정 크롤링"""
    url = "https://finance.naver.com/sise/ipo.naver"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    stocks = []
    cur_year = datetime.now().year

    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = "cp949"
        soup = BeautifulSoup(res.text, "html.parser")

        # 네이버 증권 IPO 테이블 파싱
        table = soup.find("table", class_="type_1")
        if not table:
            table = soup.find("table")

        rows = table.find_all("tr") if table else []

        for idx, row in enumerate(rows):
            cols = row.find_all(["td", "th"])
            col_texts = [clean_txt(c.get_text()) for c in cols]

            if len(col_texts) < 6 or "종목명" in col_texts[0]:
                continue

            name = col_texts[0]
            is_spac = ("스팩" in name) or ("SPAC" in name.upper())

            # 날짜 파싱 (예: "2024.10.24~10.25" 또는 "10.24~10.25")
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
            price_str = re.sub(r'[^\d]', '', col_texts[2])
            price = int(price_str) if price_str else (2000 if is_spac else 0)

            # 주관사
            underwriter = col_texts[5] if len(col_texts) > 5 else "주관사 미정"

            # 상장일 (네이버 증권에 상장일 컬럼이 있는 경우 파싱)
            listing_date = ""
            if len(col_texts) > 6 and re.search(r'\d{1,2}\.\d{1,2}', col_texts[6]):
                l_match = re.search(r'(\d{4}\.)?(\d{1,2})\.(\d{1,2})', col_texts[6])
                if l_match:
                    ly = l_match.group(1).replace(".", "") if l_match.group(1) else str(cur_year)
                    listing_date = f"{ly}-{l_match.group(2).zfill(2)}-{l_match.group(3).zfill(2)}"

            if sub_start and sub_end:
                stocks.append({
                    "id": f"real-{idx}",
                    "name": name,
                    "isSpac": is_spac,
                    "price": price,
                    "bandStatus": "확정" if price > 0 else "미정",
                    "institutionalRatio": 0.0,
                    "lockupRatio": 0.0,
                    "floatAmountBillion": 100 if is_spac else 400,
                    "existingShareholderRatio": 0.0,
                    "underwriter": underwriter,
                    "subStartDate": sub_start,
                    "subEndDate": sub_end,
                    "listingDate": listing_date if listing_date else sub_end,
                    "score": 85 if is_spac else 75,
                    "grade": "STRONG_BUY" if is_spac else "NEUTRAL",
                    "summaryReview": "네이버 증권 실시간 공모 일정 반영"
                })

    except Exception as e:
        print(f"네이버 크롤링 에러: {e}")

    return stocks

if __name__ == "__main__":
    real_data = get_naver_ipo_data()
    output = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalCount": len(real_data),
        "stocks": real_data
    }
    with open("ipo_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"네이버 증권 데이터 {len(real_data)}개 수집 및 저장 완료!")
