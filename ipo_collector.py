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
    """VS Code 터미널 프리뷰 출력"""
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
        for item in stocks:
            print(item)

    print("=" * 130 + "\n")

def is_date_match(target_str, dt_obj):
    """문자열 날짜와 datetime 객체가 동일한 날짜인지 검사"""
    if not target_str or target_str == "미정":
        return False
    formats = [
        dt_obj.strftime("%Y.%m.%d"),
        dt_obj.strftime("%Y-%m-%d"),
        dt_obj.strftime("%Y/%m/%d"),
        f"{dt_obj.year}.{dt_obj.month}.{dt_obj.day}"
    ]
    return any(f in target_str for f in formats)

def is_sub_closing_today(sub_date_str, dt_obj):
    """오늘이 공모청약 마지막 날인지 판별"""
    if not sub_date_str or sub_date_str == "미정":
        return False
    if "~" in sub_date_str:
        end_part = sub_date_str.split("~")[-1].strip()
        return is_date_match(end_part, dt_obj)
    return is_date_match(sub_date_str, dt_obj)

def send_telegram_msg(token, chat_id, text):
    """텔레그램 메시지 전송 공통 함수"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("🚀 텔레그램 알림 전송 완료!")
        else:
            print(f"⚠️ 텔레그램 전송 실패 ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"⚠️ 텔레그램 발송 오류: {e}")

def process_telegram_notifications(stocks, now_kst):
    """시간대별 맞춤 알림 발송 (수동 실행 시 자동 건너뜀)"""
    # 💡 깃허브 액션에서 수동 실행(workflow_dispatch)된 경우 알림을 보내지 않음
    event_name = os.environ.get("EVENT_NAME", "")
    if event_name == "workflow_dispatch":
        print("ℹ️ 수동 실행(workflow_dispatch) 감지됨: 텔레그램 알림을 발송하지 않고 건너뜁니다.")
        return

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("ℹ️ 텔레그램 환경변수(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)가 없어 알림을 건너뜁니다.")
        return

    cur_hour = now_kst.hour
    cur_minute = now_kst.minute
    test_mode = os.environ.get("FORCE_TELEGRAM_TEST", "false").lower() == "true"
    
    print(f"⏰ 알림 조건 확인 (현재 KST 시간: {now_kst.strftime('%H:%M')})")
    if test_mode:
        print("🧪 [테스트 모드 활성화됨] 시간 조건을 무시하고 테스트 알림을 발송합니다.")

    # 1. 오늘 상장 종목 알림 (KST 8시~9시 사이 실행 시 발송)
    if test_mode or (cur_hour == 8 or (cur_hour == 9 and cur_minute <= 30)):
        listing_today = [s for s in stocks if is_date_match(s.get("listingDate", ""), now_kst)]
        
        if not listing_today and test_mode and stocks:
            listing_today = [stocks[0]]

        if listing_today:
            msg = [
                "🔔 *[오늘 신규 상장 종목 알림]*",
                f"📅 일시: {now_kst.strftime('%Y-%m-%d')} 장 시작 전",
                ""
            ]
            for s in listing_today:
                msg.append(f"📌 *{s['name']}* (오늘 상장)")
                msg.append(f"• 확정공모가: `{s.get('confirmedPrice', '미정')}`")
                msg.append(f"• 기관경쟁률: `{s.get('institutionalRatio', '0:1')}`")
                msg.append(f"• 의무보유확약: `{s.get('lockupRatio', '0.0%')}`")
                msg.append(f"• 주관사: {s.get('underwriter', '미확인')}")
                if s.get("url"):
                    msg.append(f"• [38커뮤니케이션 바로가기]({s['url']})")
                msg.append("")
            send_telegram_msg(token, chat_id, "\n".join(msg))
        else:
            print("ℹ️ 오늘 상장하는 종목이 없습니다.")

    # 2. 오늘 청약 마감 종목 알림 (KST 15시~16시 사이 실행 시 발송)
    if test_mode or (cur_hour == 15 or (cur_hour == 16 and cur_minute <= 30)):
        closing_today = [s for s in stocks if is_sub_closing_today(s.get("subDate", ""), now_kst)]
        
        if not closing_today and test_mode and stocks:
            closing_today = [stocks[0]]

        if closing_today:
            msg = [
                "📢 *[오늘 청약 마감(마지막 날) 종목 알림]*",
                f"⏰ 청약 마감 전 ({now_kst.strftime('%Y-%m-%d %H:%M')})",
                "⚠️ 증권사별로 마감 시간(16:00 전후)이 상이하니 서둘러 확인하세요!",
                ""
            ]
            for s in closing_today:
                msg.append(f"📌 *{s['name']}* (청약 최종일)")
                msg.append(f"• 확정공모가: `{s.get('confirmedPrice', '미정')}`")
                msg.append(f"• 청약경쟁률: `{s.get('subscriptionRatio', '0:1')}`")
                msg.append(f"• 주관사: {s.get('underwriter', '미확인')}")
                msg.append(f"• 환불일: {s.get('refundDate', '미정')}")
                if s.get("url"):
                    msg.append(f"• [38커뮤니케이션 바로가기]({s['url']})")
                msg.append("")
            send_telegram_msg(token, chat_id, "\n".join(msg))
        else:
            print("ℹ️ 오늘 청약 마감(최종일)인 종목이 없습니다.")

    if not test_mode and not (8 <= cur_hour <= 9 or 15 <= cur_hour <= 16):
        print(f"ℹ️ 현재 시간({now_kst.strftime('%H:%M')})은 정기 알림 시간대가 아닙니다.")

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
                    if int(no_val) >= 3000 or no_val in seen_no:
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

                        ipo_list.append({"no": no_val, "name": corp_name, "url": full_detail_url})

        results = []
        for idx, item in enumerate(ipo_list, 1):
            print(f"[{idx}/{len(ipo_list)}] {item['name']} 파싱 중...")
            detail_data = parse_detail_page_robust(session, item["url"], item["name"])
            detail_data["no"] = item["no"]
            detail_data["url"] = item["url"]
            results.append(detail_data)
            time.sleep(random.uniform(0.3, 0.7))

        return results
    except Exception as e:
        print(f"⚠️ 메인 크롤링 에러: {e}")
        return []

if __name__ == "__main__":
    print("=== 38커뮤니케이션 공모주 수집 시작 ===")
    
    os.environ["FORCE_TELEGRAM_TEST"] = "false"

    ipo_data = get_full_ipo_data()
    
    if ipo_data:
        print_vscode_preview(ipo_data)
        
        now_dt = datetime.now(KST)
        now_kst_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        output = {
            "updatedAt": now_kst_str,
            "totalCount": len(ipo_data),
            "stocks": ipo_data
        }
        
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ipo_data.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
            
        print(f"🎉 JSON 저장 완료! (기록 일시: {now_kst_str} KST)")

        # 💡 시간대별 조건 알림 발송 (수동 실행 시 자동 차단됨)
        process_telegram_notifications(ipo_data, now_dt)
    else:
        print("❌ 수집된 데이터가 없습니다.")
