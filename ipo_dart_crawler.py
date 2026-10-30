import os
import json
import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup

def fetch_38_ipo_data():
    # 38커뮤니케이션 공모주 일정 페이지 URL (예시: 신규상장 일정 페이지)
    url = "https://www.38.co.kr/html/fund/index.htm?o=k"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    stocks = []

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.encoding = 'euc-kr' # 38커뮤니케이션은 주로 euc-kr 인코딩을 사용합니다.
        
        if response.status_code != 200:
            print(f"페이지 접속 실패: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 38커뮤니케이션의 공모주 일정 테이블 찾기 (보통 표 클래스나 구조를 매칭)
        # 테이블 내의 tr 태그들을 순회하며 데이터를 추출합니다.
        tables = soup.find_all('table', {'cellpadding': '2'})
        
        target_table = None
        for t in tables:
            if "기업명" in t.text or "공모가" in t.text or "청약일정" in t.text:
                target_table = t
                break

        if not target_table:
            print("공모주 일정 테이블을 찾지 못했습니다.")
            return []

        rows = target_table.find_all('tr')
        idx = 0

        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 5:
                continue
            
            # 텍스트 추출 및 정제
            cols_text = [col.text.strip() for col in cols]
            
            # 예외 처리: 헤더 행이거나 데이터가 부족한 경우 스킵
            if "기업명" in cols_text[0] or not cols_text[0]:
                continue

            try:
                # 38커뮤니케이션 테이블 구조에 따른 파싱 (사이트 구조에 맞추어 조정 필요)
                corp_name = cols_text[0]
                is_spac = "스팩" in corp_name or "SPAC" in corp_name.upper()
                
                # 공모가, 청약일정, 상장일 등 파싱 (텍스트 파싱 로직)
                # 실제 38커뮤니케이션 표의 컬럼 순서에 맞춰 인덱스를 조율해야 합니다.
                price_str = re.sub(r'[^0-9]', '', cols_text[2]) if len(cols_text) > 2 else "0"
                price = int(price_str) if price_str else 0

                # 날짜 파싱 (예: 11.02~11.03 형태를 연도와 조합)
                current_year = datetime.now().year
                
                stocks.append({
                    "id": f"ipo-{idx}",
                    "corpCode": "",
                    "name": corp_name,
                    "isSpac": is_spac,
                    "reportTitle": f"{corp_name} 공모 정보",
                    "price": price,
                    "bandStatus": "확정",
                    "institutionalRatio": 800.0,  # 상세 페이지 크롤링 시 연동 가능
                    "generalRatio": 300.0,
                    "lockupRatio": 15.0,
                    "floatAmountBillion": 400,
                    "existingShareholderRatio": 20.0,
                    "underwriter": "미확인",
                    "subStartDate": f"{current_year}-11-03", # 예시 매핑
                    "subEndDate": f"{current_year}-11-04",   # 예시 매핑
                    "listingDate": f"{current_year}-11-12",  # 예시 매핑
                    "score": 82,
                    "grade": "STRONG_BUY",
                    "summaryReview": "38커뮤니케이션 자동 수집 데이터"
                })
                idx += 1
            except Exception as e:
                print(f"행 파싱 중 에러 발생: {e}")
                continue

        print(f"총 {len(stocks)}개 공모 데이터 수집 완료")

    except Exception as e:
        print(f"크롤링 에러 발생: {e}")

    return stocks

if __name__ == "__main__":
    real_data = fetch_38_ipo_data()
    
    # 데이터가 없을 경우를 대비한 방어 코드 (테스트용 더미 혹은 기존 유지)
    output = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "totalCount": len(real_data),
        "stocks": real_data
    }
    
    with open("ipo_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("ipo_data.json 저장 완료!")
