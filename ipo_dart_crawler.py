import os
import re
import json
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import ssl
from bs4 import BeautifulSoup
import urllib3

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
    """상세 페이지 데이터 정밀 파서"""
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
        full_text = clean_text(soup.get_text())

        # 1. 테이블 행(tr) 순회 매칭
        for tr in soup.find_all('tr'):
            tds = tr.find_all(['td', 'th'])
            texts = [clean_text(td.text) for td in tds]

            for i, t in enumerate(texts):
                if i + 1 < len(texts):
                    next_t = texts[i + 1]
                    
                    if "희망공모가액" in t and detail_info["priceBand"] == "미정":
                        if next_t and ("~" in next_t or "원" in next_t):
                            detail_info["priceBand"] = next_t
                    elif "확정공모가" in t and detail_info["confirmedPrice"] == "미정":
                        if next_t and next_t != "확정공모가":
                            detail_info["confirmedPrice"] = next_t
                    elif "청약경쟁률" in t and "기관" not in t and detail_info["subscriptionRatio"] == "0:1":
                        if ":" in next_t:
                            detail_info["subscriptionRatio"] = next_t
                    elif "주간사" in t and detail_info["underwriter"] == "미확인":
                        if next_t and len(next_t) > 1:
                            detail_info["underwriter"] = next_t
                    elif "공모청약일" in t and detail_info["subDate"] == "미정":
                        if next_t:
                            detail_info["subDate"] = next_t
                    elif "환불일" in t and detail_info["refundDate"] == "미정":
                        if next_t:
                            detail_info["refundDate"] = next_t
                    elif ("신규상장일" in t or "상장일" in t) and detail_info["listingDate"] == "미정":
                        if next_t and "상장일" not in next_t:
                            detail_info["listingDate"] = next_t

        # 2. 전체 페이지 텍스트 기반 정밀 정규식 보완 (누락 방지)
        if detail_info["priceBand"] == "미정":
            m = re.search(r'희망공모가액[^\d]*([\d,]+\s*~\s*[\d,]+원?)', full_text)
            if m: detail_info["priceBand"] = m.group(1).strip()

        if detail_info["confirmedPrice"] == "미정":
            m = re.search(r'확정공모가[^\d]*([\d,]+원?)', full_text)
            if m: detail_info["confirmedPrice"] = m.group(1).strip()

        if detail_info["institutionalRatio"] == "0:1":
            m = re.search(r'기관(?:신청)?경쟁률[^\d]*([\d,\.]+\s*:\s*1)', full_text)
            if m: detail_info["institutionalRatio"] = m.group(1).strip()

        if detail_info["lockupRatio"] == "0.0%":
            m = re.search(r'의무보유확약[^\d]*([\d,\.]+\s*%)', full_text)
            if m: detail_info["lockupRatio"] = m.group(1).strip()

        if detail_info["subDate"] == "미정":
            m = re.search(r'공모청약일[^\d]*(\d{1,2}[-./]\d{1,2}(?:\s*~\s*\d{1,2}[-./]\d{1,2})?)', full_text)
            if m: detail_info["subDate"] = m.group(1).strip()

        if detail_info["refundDate"] == "미정":
            m = re.search(r'환불일[^\d]*(\d{1,2}[-./]\d{1,2})', full_text)
            if m: detail_info["refundDate"] = m.group(1).strip()

        if detail_info["listingDate"] == "미정":
            m = re.search(r'(?:신규)?상장일[^\d]*(\d{1,2}[-./]\d{1,2})', full_text)
            if m: detail_info["listingDate"] = m.group(1).strip()

    except Exception as e:
        print(f"  ⚠️ 상세 페이지 파싱 중 에러 ({detail_url}): {e}")

    return detail_info

def print_vscode_preview(stocks):
    """터미널 프리뷰 출력"""
    print("\n" + "=" * 120)
    print(f" 🚀 38커뮤니케이션 공모주 수집 결과 프리뷰 (총 {len(stocks)}개 종목)")
    print("=" * 120)

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="공모주 상세 데이터 요약", show_lines=True)

        table.add_column("No", justify="center", style="cyan", no_wrap=True)
        table.add_column("종목명", style="bold white", no_wrap=True)
        table.add_column("희망공모가 / 확정가", style="yellow")
        table.add_column("청약일", style="green")
        table.add_column("상장일", style="magenta")
        table.add_column("기관경쟁률", justify="right", style="blue")
        table.add_column("확약", justify="right", style="red")
        table.add_column("주간사", style="dim")

        for item in stocks:
            price_display = item["confirmedPrice"] if item["confirmedPrice"] != "미정" else item["priceBand"]
            table.add_row(
                item["no"],
                item["name"],
                price_display,
                item["subDate"],
                item["listingDate"],
                item["institutionalRatio"],
                item["lockupRatio"],
                item["underwriter"]
            )

        console.print(table)

    except ImportError:
        print(f"{'No':<6} | {'종목명':<12} | {'공모가(확정/밴드)':<18} | {'청약일':<11} | {'상장일':<6} | {'기관경쟁률':<10} | {'확약':<6} | {'주간사'}")
        print("-" * 120)
        for item in stocks:
            p_val = item["confirmedPrice"] if item["confirmedPrice"] != "미정" else item["priceBand"]
            print(f"{item['no']:<6} | {item['name']:<12} | {p_val:<18} | {item['subDate']:<11} | {item['listingDate']:<6} | {item['institutionalRatio']:<10} | {item['lockupRatio']:<6} | {item['underwriter']}")

    print("=" * 120 + "\n")

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
                    corp_name = re.sub(r'\[.*?\]|\(.*?\)', '', corp_name).strip()
                    
                    if corp_name and len(corp_name) < 15 and not corp_name.isdigit():
                        if corp_name in seen_names:
                            continue
                        seen_names.add(corp_name)

                        detail_url = f"https://www.38.co.kr/html/fund/?o=v&no={no_val}&l=&page=1"
                        ipo_list.append({
                            "no": no_val,
                            "name": corp_name,
                            "url": detail_url
                        })

        print(f"✅ 유효 종목 {len(ipo_list)}개 발견. 상세 페이지 파싱 시작...\n")

        results = []
        for idx, item in enumerate(ipo_list, 1):
            print(f"[{idx}/{len(ipo_list)}] {item['name']} (no={item['no']}) 파싱 중...")
            detail_data = parse_detail_page_robust(session, item["url"], item["name"])
            detail_data["no"] = item["no"]
            detail_data["url"] = item["url"]
            results.append(detail_data)

        return results

    except Exception as e:
        print(f"⚠️ 메인 크롤링 에러: {e}")
        return []

if __name__ == "__main__":
    print("=== 38커뮤니케이션 공모주 수집 시작 ===")
    ipo_data = get_full_ipo_data()
    
    if ipo_data:
        print_vscode_preview(ipo_data)
        
        output = {
            "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "totalCount": len(ipo_data),
            "stocks": ipo_data
        }
        
        # GitHub 저장소 루트 경로에 안전하게 저장되도록 설정
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ipo_data.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
            
        print(f"🎉 총 {len(ipo_data)}개 종목 데이터 수집 완료 및 {output_path} 저장 성공!")
    else:
        print("❌ 수집된 데이터가 없습니다.")
