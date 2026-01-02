import feedparser
import smtplib
from email.mime.text import MIMEText
import requests
import re
import os
import datetime
from datetime import timezone, timedelta

# ---------------------- Gmail配置（从GitHub Secret读取，不用改） ----------------------
GMAIL_EMAIL = os.getenv("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECEIVER_EMAILS = os.getenv("RECEIVER_EMAILS")
SMTP_SERVER = "smtp.gmail.com"
CUSTOM_NICKNAME = "📩懂王快讯"

# ---------------------- 基础配置（不用改） ----------------------
RSS_URL = "https://www.trumpstruth.org/feed"
LAST_LINK_FILE = "last_link.txt"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# ✅ 精准提取pubDate并转北京时间
def get_show_time(news):
    beijing_tz = timezone(timedelta(hours=8))
    pub_date_str = news.get("pubdate", news.get("published", ""))
    
    if pub_date_str:
        try:
            dt_formats = [
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M %z",
                "%d %b %Y %H:%M:%S %z",
                "%Y-%m-%d %H:%M:%S %z"
            ]
            for fmt in dt_formats:
                try:
                    dt_utc = datetime.datetime.strptime(pub_date_str, fmt)
                    dt_beijing = dt_utc.astimezone(beijing_tz)
                    return dt_beijing.strftime("%Y-%m-%d %H:%M")
                except:
                    continue
        except:
            pass

    updated_str = news.get("updated", "")
    if updated_str:
        try:
            dt_utc = datetime.datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
            dt_beijing = dt_utc.astimezone(beijing_tz)
            return dt_beijing.strftime("%Y-%m-%d %H:%M")
        except:
            pass

    current_bj = datetime.datetime.now(beijing_tz)
    return current_bj.strftime("%Y-%m-%d %H:%M")

# ✅ 核心规则（无任何多余代码）
def parse_news_type_and_content(news):
    raw_title = news.get("title", "").strip()
    no_title_flags = ["[No Title]", "no title", "untitled", "- Post from "]
    is_forward = not raw_title or any(flag in raw_title for flag in no_title_flags)
    forward_tag = "（图片或转发）" if is_forward else ""

    if is_forward:
        content = news.get("content", [{}])[0].get("value", "") if news.get("content") else ""
        clean_text = re.sub(r'<.*?>', '', content, flags=re.DOTALL)
        clean_text = re.sub(r'https?://\S+', '', clean_text).strip()
        clean_text = re.sub(r'^(\s*RT[:\s]*|\s*@\w+:)', '', clean_text, flags=re.IGNORECASE)
        trump_text = clean_text.strip() if clean_text and len(clean_text) > 2 else "无文字描述"
        content_text = f"【懂王】：{trump_text}"
    else:
        clean_title = re.sub(r'https?://\S+', '', raw_title).strip()
        content_text = f"【懂王】：{clean_title}"

    return forward_tag, content_text

# 抓取资讯（不用改，修正了拼写错误REQUEST_HEADERS）
def fetch_news():
    try:
        response = requests.get(RSS_URL, headers=REQUEST_HEADERS, timeout=15)
        response.raise_for_status()
        news_list = feedparser.parse(response.content).entries
        if not news_list:
            print("📭 未抓取到任何Trump Truth资讯")
            return None, None
        latest_link = news_list[0]["link"].strip()
        print(f"📭 成功抓取到{len(news_list)}条Trump Truth资讯")
        return news_list, latest_link
    except Exception as e:
        print(f"❌ 资讯抓取失败：{str(e)}")
        return None, None

# 检查是否推送（防重复，不用改）
def check_push():
    is_first_run = not os.path.exists(LAST_LINK_FILE)
    last_saved_link = ""
    if not is_first_run:
        try:
            with open(LAST_LINK_FILE, 'r', encoding='utf-8') as f:
                last_saved_link = f.read().strip()
        except Exception as e:
            print(f"⚠️  历史链接读取失败，按首次运行处理：{str(e)}")
            is_first_run = True

    all_news, current_latest_link = fetch_news()
    if not all_news or not current_latest_link:
        return False, None

    if is_first_run or current_latest_link != last_saved_link:
        with open(LAST_LINK_FILE, 'w', encoding='utf-8') as f:
            f.write(current_latest_link)
        print("🚨 新资讯检测到，准备推送！")
        return True, all_news
    else:
        print(f"ℹ️  无新资讯，本次跳过推送")
        return False, None

# ✅ 核心修改：只改【时间】和（懂王转发贴）间距为1px，其他全部不变
def make_email_content(all_news):
    if not all_news:
        return "<p style='font-size:16px; color:#FFFFFF;'>暂无可用的Trump Truth资讯</p>"
    news_list = all_news[:300]

    # 颜色配置（匹配截图）
    title_color = "#C8102E"
    time_color = "#1E90FF"
    serial_color = "#FFFFFF"
    forward_color = "#C8102E"
    content_color = "#FFFFFF"
    link_color = "#1E90FF"
    arrow_color = "#FFCC00"
    
    # 你的原参数 全部不变
    content_indent = "20px"
    card_margin = "0 0 4px 0"
    card_padding = "6px"
    line_margin = "0 0 4px 0"

    email_title_html = f"""
    <p style='margin: 0 0 8px 0; padding: 6px; background-color:#2D2D2D; border-left:4px solid {title_color};'>
        <strong><span style='color:{title_color}; font-size:18px;'>♥️ 「7*24真实社交速递」</span></strong>
    </p>
    """

    news_items = []
    for i, news in enumerate(news_list, 1):
        news_link = news["link"]
        show_time = get_show_time(news)
        forward_tag, content_text = parse_news_type_and_content(news)
        
        news_items.append(f"""
        <div style='margin:{card_margin}; padding:{card_padding}; background-color:#2D2D2D; border-radius:4px;'>
            <div style='display: flex; align-items: center; margin:{line_margin};'>
                <span style='color:{serial_color}; font-size:15px; font-weight:bold; margin-right: 8px;'>{i}.</span>
                <div style='flex: 1;'>
                    <span style='color:{time_color}; font-weight:bold; font-size:15px;'>【{show_time}】</span>
                    <!-- 仅改这行：间距从 0 6px 改为 0 1px，实现贴近效果 -->
                    <span style='color:{forward_color}; font-weight:bold; margin:0 0px; font-size:15px;'>{forward_tag}</span>
                </div>
            </div>
            <p style='margin:{line_margin}; padding:0 0 0 {content_indent}; line-height:1.4; font-size:16px; color:{content_color}; margin-top:0;'>
                {content_text}
            </p>
            <p style='margin:0; padding:0 0 0 {content_indent}; line-height:1.4; font-size:14px;'>
                <span style='color:{arrow_color}; font-size:16px;'>👉</span>
                <a href='{news_link}' target='_blank' style='color:{link_color}; text-decoration:none;'>查看原文</a>
            </p>
        </div>
        """)
    return email_title_html + "".join(news_items)

# 发送邮件（不用改）
def send_email(html_content):
    if not all([GMAIL_EMAIL, GMAIL_APP_PASSWORD, RECEIVER_EMAILS]):
        print("❌ 请先配置GMAIL_EMAIL、GMAIL_APP_PASSWORD、RECEIVER_EMAILS这3个Secret！")
        return
    receivers = [email.strip() for email in RECEIVER_EMAILS.split(",") if email.strip()]
    if not receivers:
        print("❌ 收件人邮箱格式错误（多邮箱用英文逗号分隔）")
        return

    try:
        smtp = smtplib.SMTP_SSL(SMTP_SERVER, 465, timeout=20)
        smtp.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        print(f"✅ Gmail连接成功，即将向{len(receivers)}个收件人发送资讯邮件")

        current_bj_time = datetime.datetime.now(timezone(timedelta(hours=8)))
        bj_date = current_bj_time.strftime("%Y-%m-%d")
        for receiver in receivers:
            msg = MIMEText(html_content, "html", "utf-8")
            msg["From"] = f"{CUSTOM_NICKNAME} <{GMAIL_EMAIL}>"
            msg["To"] = receiver
            msg["Subject"] = f"⏰ | {bj_date}"
            smtp.sendmail(GMAIL_EMAIL, [receiver], msg.as_string())
            print(f"✅ 已发送给：{receiver}")

        smtp.quit()
        print("✅ 所有邮件发送完成！")
    except smtplib.SMTPAuthenticationError:
        print("""❌ Gmail登录失败！请检查：
        1. Secrets里的邮箱/密码是否正确；
        2. Gmail是否开启「两步验证」；
        3. 应用专用密码是否有效（重新生成试试）。""")
    except Exception as e:
        print(f"❌ 邮件发送失败：{str(e)}")
        raise

# 程序入口（不用改）
if __name__ == "__main__":
    utc_now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cst_now = datetime.datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    print(f"==================================================")
    print(f"📅 执行时间 | UTC：{utc_now} | 北京时间：{cst_now}")
    print(f"📡 订阅源 | Trump Truth（{RSS_URL}）")
    print(f"==================================================")

    try:
        need_push, news_data = check_push()
        if need_push and news_data:
            email_html = make_email_content(news_data)
            send_email(email_html)
        print(f"🎉 本次推送流程结束")
    except Exception as e:
        print(f"💥 程序异常：{str(e)}")
        raise
