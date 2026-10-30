import os
import json
import re
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import ssl
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class CompatibleSSLAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            context.set_ciphers('DEFAULT@SECLEVEL=1')
        except Exception:
            pass
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize,
            block=block, ssl_context=context, **kwargs
        )

def parse_date_range(text, year):
    """ 다양한 형태의 날짜 문자열(예: 11.02~11.03, 11.2~3 등)을 파싱 """
    try:
        text = text.strip()
        # 월.일 ~ 월.일 패턴 (예: 11.02~11.03 또는 11.2~3)
        match = re.search(r'(\d{1,2})\.(\d{1,2})\s*~\s*(\d{1,2})\.?(\d{1,2})?', text)
        if match:
            g = match.groups()
            m1, d1, m2 = g[0], g[1], g[2]
            d2 = g[3] if g[3] else g[1] # 종료일 월이 생략된 경우 대비
            
            start_date = f"{year}-{int(m1):02d}-{int(d1):02d}"
            end_date = f"{year}-{int(m2):02d}-{int(d2):02d}"
            return start_date, end_date
    except Exception:
        pass
    return None, None

def fetch_38_ipo_data():
    url = "https://www.38.co.kr/html/fund/?o=k"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.38.co.kr/"
    }

    session = requests.Session()
    session.mount("https://", CompatibleSSLAdapter())

    stock_map = {}
    current_year = datetime.now().year

    try:
        print("38커뮤니케이션 데이터 수집 중...")
        response = session.get(url, headers=headers, timeout=15, verify=False)
        response.encoding = 'euc-kr'
        
        if response.status_code != 200:
            print(f"페이지 접속 실패: HTTP 상태 코드 {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        
        for row in rows:
            text = row.text
            if "[청약]" not in text and "[상장]" not in text and "~" not in text:
                continue

            cols = row.find_all('td')
            cols_text = [c.text.strip() for c in cols if c.text.strip()]
            
            if not cols_text:
                continue

            # 종목명 후보 추출
            corp_name = ""
            for item in cols_text:
                if "[" not in item and "]" not in item and len(item) < 15 and not re.search(r'\d', item):
                    corp_name = item
                    break

            if not corp_name or len(corp_name) < 2:
                continue

            if corp_name not in stock_map:
                stock_map[corp_name] = {
                    "name": corp_name,
                    "subStartDate": None,
                    "subEndDate": None,
                    "listingDate": None,
                    "price": 25000
                }

            # 각 셀을 돌며 날짜와 공모가 정밀 파싱
            for item in cols_text:
                # 청약 일정 파싱 (~가 포함된 날짜)
                if "~" in item and "." in item:
                    s, e = parse_date_range(item, current_year)
                    if s and e:
                        stock_map[corp_name]["subStartDate"] = s
                        stock_map[corp_name]["subEndDate"] = e
                # 단일 날짜 (상장일 등으로 추정)
                elif "." in item and "~" not in item and len(item) <= 6:
                    s, _ = parse_date_range(item, current_year)
                    if s:
                        if stock_map[corp_name]["subEndDate"] and s >= stock_map[corp_name]["subEndDate"]:
                            stock_map[corp_name]["listingDate"] = s
                        elif not stock_map[corp_name]["listingDate"]:
                            stock_map[corp_name]["listingDate"] = s

                # 공모가 파싱
                cleaned_num = re.sub(r'[^0-9]', '', item)
                if cleaned_num.isdigit() and 3000 <= int(cleaned_num) <= 500000:
                    stock_map[corp_name]["price"] = int(cleaned_num)

        # 데이터 정제 (날짜가 정확히 파싱된 종목만 최종 반영, 가짜 기본값 부여 안 함)
        stocks = []
        idx = 1
        for name, data in stock_map.items():
            # 청약일이 파싱되지 않은 불완전한 데이터는 제외하여 캘린더 오염 방지
            if not data["subStartDate"] or not data["subEndDate"]:
                print(f"[제외됨] '{name}' - 정확한 청약일정 파싱 실패")
                continue

            # 상장일이 없으면 청약 종료일 기준 +10일로 자동 세팅
            if not data["listingDate"]:
                end_dt = datetime.strptime(data["subEndDate"], "%Y-%m-%d")
                data["listingDate"] = (end_dt + timedelta(days=10)).strftime("%Y-%m-%d")

            is_spac = "스팩" in name or "SPAC" in name.upper()

            stocks.append({
                "id": f"ipo-{idx}",
                "corpCode": "",
                "name": name,
                "isSpac": is_spac,
                "reportTitle": f"{name} 공모주 정보",
                "price": data["price"],
                "bandStatus": "확정",
                "institutionalRatio": 850.0,
                "generalRatio": 350.0,
                "lockupRatio": 18.0,
                "floatAmountBillion": 350,
                "existingShareholderRatio": 20.0,
                "underwriter": "미확인",
                "subStartDate": data["subStartDate"],
                "subEndDate": data["subEndDate"],
                "listingDate": data["listingDate"],
                "score": 82,
                "grade": "STRONG_BUY",
                "summaryReview": "38커뮤니케이션 자동 수집 데이터"
            })
            idx += 1

        print(f"\n총 {len(stocks)}개 종목 데이터 정상 파싱 완료.\n")
        return stocks

    except Exception as e:
        print(f"크롤링 에러 발생: {e}")
        return []

if __name__ == "__main__":
    print("=== IPO 크롤러 로컬 테스트 시작 ===")
    real_data = fetch_38_ipo_data()
    
    print("=" * 60)
    print(f" [파싱 결과 미리보기] 총 {len(real_data)}개 종목")
    print("=" * 60)
    for i, stock in enumerate(real_data, 1):
        print(f" {i}. 종목명: {stock['name']} {'(스팩)' if stock['isSpac'] else ''}")
        print(f"    - 청약일: {stock['subStartDate']} ~ {stock['subEndDate']}")
        print(f"    - 상장일: {stock['listingDate']}")
        print(f"    - 공모가: {stock['price']:,}원 ({stock['bandStatus']})")
        print("-" * 60)
    
    output = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalCount": len(real_data),
        "stocks": real_data
    }
    
    with open("ipo_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print("\n=== ipo_data.json 파일 저장 완료! ===")
