import os
import re
import json
import time
import random
from datetime import datetime, timezone, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import ssl
from bs4 import BeautifulSoup
import urllib3

# 한국 표준시(KST, UTC+9) 정의
KST = timezone(timedelta(hours=9))

# 경고 로그 비활성화
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

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def parse_detail_page_robust(session, detail_url, default_name):
    """상세 페이지 정밀 파서 (희망공모가와 확정공모가 모두 수집)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.38.co.kr/html/fund/?o=k"
    }

    detail_info = {
        "name": default_name,
        "priceBand": "미정",
        "confirmedPrice": "미정",
        "subscriptionRatio": "0:1",
        "underwriter": "미확인",
        "subDate": "미정",
        "refundDate": "미정",
        "listingDate": "미정",
        "institutionalRatio": "0:1",
        "lockupRatio": "0.0%"
    }

    try:
        res = session.get(detail_url, headers=headers, timeout=15, verify=False)
        res.encoding = 'euc-kr'
        if res.status_code != 200:
            return detail_info

        soup = BeautifulSoup(res.text, 'html.parser')

        # 테이블 행 순회하며 희망공모가와 확정공모가 모두 독립적으로 수집
        for tr in soup.find_all('tr'):
            tds = tr.find_all(['td', 'th'])
            texts = [clean_text(td.text) for td in tds]

            for i, t in enumerate(texts):
                if i + 1 < len(texts):
                    next_t = texts[i + 1]

                    if any(bad in next_t for bad in ["동원파츠", "확정공모가2", "구분", "주주명"]):
                        continue
                    
                    # 1. 희망공모가 (밴드 형식)
                    if "희망공모가" in t and detail_info["priceBand"] == "미정":
                        m = re.search(r'([\d,]+\s*~\s*[\d,]+\s*원)', next_t)
                        if m:
                            detail_info["priceBand"] = re.sub(r'\s+', '', m.group(1))
                    
                    # 2. 확정공모가
                    elif "확정공모가" in t and detail_info["confirmedPrice"] == "미정":
                        m = re.search(r'^([\d,]+원)$', next_t.replace(" ", ""))
                        if m:
                            detail_info["confirmedPrice"] = m.group(1)
                    
                    # 3. 청약경쟁률 (일반)
                    elif "청약경쟁률" in t and "기관" not in t and detail_info["subscriptionRatio"] == "0:1":
                        m = re.search(r'([\d,\.]+\s*:\s*1)', next_t)
                        if m:
                            detail_info["subscriptionRatio"] = m.group(1).replace(" ", "")
                            
                    # 4. 기관경쟁률
                    elif "기관" in t and "경쟁률" in t and detail_info["institutionalRatio"] == "0:1":
                        m = re.search(r'([\d,\.]+\s*:\s*1)', next_t)
                        if m:
                            detail_info["institutionalRatio"] = m.group(1).replace(" ", "")
                            
                    # 5. 의무보유확약
                    elif "의무보유" in t and detail_info["lockupRatio"] == "0.0%":
                        m = re.search(r'([\d,\.]+\s*%)', next_t)
                        if m:
                            detail_info["lockupRatio"] = m.group(1).replace(" ", "")
                            
                    # 6. 주간사
                    elif "주간사" in t and detail_info["underwriter"] == "미확인":
                        if len(next_t) > 1 and "주간사" not in next_t and not next_t.startswith("주식수"):
                            clean_uw = re.sub(r'주식수.*', '', next_t).strip()
                            if clean_uw and len(clean_uw) < 30:
                                detail_info["underwriter"] = clean_uw
                            
                    # 7. 공모청약일
                    elif "공모청약일" in t and detail_info["subDate"] == "미정":
                        m = re.search(r'(\d{4}[\./-]\d{1,2}[\./-]\d{1,2}\s*~\s*\d{4}[\./-]\d{1,2}[\./-]\d{1,2})', next_t)
                        if m:
                            detail_info["subDate"] = m.group(1).replace(" ", "")
                        else:
                            m_short = re.search(r'(\d{4}[\./-]\d{1,2}[\./-]\d{1,2})', next_t)
                            if m_short:
                                detail_info["subDate"] = next_t
                            
                    # 8. 환불일
                    elif "환불일" in t and detail_info["refundDate"] == "미정":
                        m = re.search(r'(\d{4}[\./-]\d{1,2}[\./-]\d{1,2})', next_t)
                        if m:
                            detail_info["refundDate"] = m.group(1)
                            
                    # 9. 상장일
                    elif ("신규상장일" in t or "상장일" in t) and detail_info["listingDate"] == "미정":
                        m = re.search(r'(\d{4}[\./-]\d{1,2}[\./-]\d{1,2})', next_t)
                        if m:
                            detail_info["listingDate"] = m.group(1)

    except Exception as e:
        print(f"  ⚠️ 상세 페이지 파싱 중 에러 ({detail_url}): {e}")

    return detail_info

def print_vscode_preview(stocks):
    """VS Code 터미널 프리뷰 출력 (희망공모가와 확정공모가 동시 표시)"""
    print("\n" + "=" * 130)
    print(f" 🚀 38커뮤니케이션 공모주 수집 결과 프리뷰 (총 {len(stocks)}개 종목)")
    print("=" * 130)

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="공모주 상세 데이터 요약", show_lines=True)

        table.add_column("No", justify="center", style="cyan", no_wrap=True)
        table.add_column("종목명", style="bold white", no_wrap=True)
        table.add_column("희망공모가(밴드)", style="yellow")
        table.add_column("확정공모가", style="bright_yellow")
        table.add_column("청약일", style="green")
        table.add_column("상장일", style="magenta")
        table.add_column("기관경쟁률", justify="right", style="blue")
        table.add_column("확약", justify="right", style="red")
        table.add_column("주간사", style="dim")

        for item in stocks:
            table.add_row(
                item["no"],
                item["name"],
                item["priceBand"],
                item["confirmedPrice"],
                item["subDate"],
                item["listingDate"],
                item["institutionalRatio"],
                item["lockupRatio"],
                item["underwriter"]
            )

        console.print(table)

    except ImportError:
        print(f"{'No':<6} | {'종목명':<12} | {'희망공모가(밴드)':<16} | {'확정공모가':<12} | {'청약일':<11} | {'상장일':<6} | {'기관경쟁률':<10} | {'확약':<6} | {'주간사'}")
        print("-" * 130)
        for item in stocks:
            print(f"{item['no']:<6} | {item['name']:<12} | {item['priceBand']:<16} | {item['confirmedPrice']:<12} | {item['subDate']:<11} | {item['listingDate']:<6} | {item['institutionalRatio']:<10} | {item['lockupRatio']:<6} | {item['underwriter']}")

    print("=" * 130 + "\n")

def get_full_ipo_data():
    url = "https://www.38.co.kr/html/fund/?o=k"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.38.co.kr/"
    }

    session = requests.Session()
    session.mount("https://", CompatibleSSLAdapter())

    print(f"📡 38커뮤니케이션 목록 페이지 요청 중...")
    try:
        response = session.get(url, headers=headers, timeout=15, verify=False)
        response.encoding = 'euc-kr'
        
        if response.status_code != 200:
            print(f"❌ 목록 페이지 접속 실패 (Status: {response.status_code})")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        
        seen_no = set()
        seen_names = set()
        ipo_list = []

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if 'o=v' in href and 'no=' in href:
                match_no = re.search(r'no=(\d+)', href)
                if match_no:
                    no_val = match_no.group(1)
                    
                    if int(no_val) >= 3000:
                        continue

                    if no_val in seen_no:
                        continue
                    seen_no.add(no_val)

                    link_text = clean_text(a.text)
                    corp_name = re.sub(r'^\d{1,2}[/.]\d{1,2}\s*', '', link_text)
                    corp_name = re.sub(r'$.*?$|$.*?$', '', corp_name).strip()
                    
                    if corp_name and len(corp_name) < 15 and not corp_name.isdigit():
                        if corp_name in seen_names:
                            continue
                        seen_names.add(corp_name)

                        if href.startswith('/'):
                            full_detail_url = f"https://www.38.co.kr{href}"
                        elif href.startswith('http'):
                            full_detail_url = href
                        else:
                            full_detail_url = f"https://www.38.co.kr/html/fund/{href}"

                        ipo_list.append({
                            "no": no_val,
                            "name": corp_name,
                            "url": full_detail_url
                        })

        print(f"✅ 유효 종목 {len(ipo_list)}개 발견. 상세 페이지 파싱 시작...\n")

        results = []
        for idx, item in enumerate(ipo_list, 1):
            print(f"[{idx}/{len(ipo_list)}] {item['name']} (no={item['no']}) 파싱 중...")
            detail_data = parse_detail_page_robust(session, item["url"], item["name"])
            detail_data["no"] = item["no"]
            detail_data["url"] = item["url"]
            results.append(detail_data)
            
            # 💡 대상 서버 차단 방지를 위한 미세 랜덤 지연 (0.3초 ~ 0.7초)
            time.sleep(random.uniform(0.3, 0.7))

        return results

    except Exception as e:
        print(f"⚠️ 메인 크롤링 에러: {e}")
        return []

if __name__ == "__main__":
    print("=== 38커뮤니케이션 공모주 수집 시작 ===")
    ipo_data = get_full_ipo_data()
    
    if ipo_data:
        print_vscode_preview(ipo_data)
        
        # 💡 GitHub Actions 환경(UTC)에서도 무조건 한국 표준시(KST)로 저장되도록 설정
        now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        
        output = {
            "updatedAt": now_kst,
            "totalCount": len(ipo_data),
            "stocks": ipo_data
        }
        
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ipo_data.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
            
        print(f"🎉 총 {len(ipo_data)}개 종목 데이터 수집 완료 및 {output_path} 저장 성공! (기록 일시: {now_kst} KST)")
    else:
        print("❌ 수집된 데이터가 없습니다.")
