import feedparser
import smtplib
from email.mime.text import MIMEText
import requests
import re
import os
import datetime

# ---------------------- Gmail配置（从GitHub Secret读取，不用改） ----------------------
GMAIL_EMAIL = os.getenv("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECEIVER_EMAILS = os.getenv("RECEIVER_EMAILS")
SMTP_SERVER = "smtp.gmail.com"
CUSTOM_NICKNAME = "📩Trump Truth快讯"

# ---------------------- 基础配置（不用改） ----------------------
RSS_URL = "https://www.trumpstruth.org/feed"
LAST_LINK_FILE = "last_link.txt"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# 优化：增强资讯时间提取逻辑（适配所有格式，不用改）
def get_show_time(news):
    content = news.get("content", [{}])[0].get("value", "") if news.get("content") else ""
    time_patterns = [
        r'(\d{2}:\d{2})<\/time>',
        r'(\d{2}:\d{2}:\d{2})',
        r'(\d{1,2}:\d{2}\s*[AP]M)',
    ]
    for pattern in time_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    time_str = news.get("updated", news.get("published", ""))
    if not time_str:
        return "未知时间"
    if 'T' in time_str:
        time_part = time_str.split('T')[1].split('+')[0].split('-')[0]
        if ':' in time_part:
            return time_part[:5]
    elif re.search(r'\d{2}:\d{2}', time_str):
        return re.search(r'\d{2}:\d{2}', time_str).group(0)

    try:
        date_obj = datetime.datetime.strptime(time_str.split('T')[0], "%Y-%m-%d")
        return date_obj.strftime("%m-%d")
    except:
        return "未知时间"

# ✅ 核心精简规则（无任何多余代码，完美匹配你的要求）
# 1. 转发贴 → 时间后加【转发贴】 + 换行【懂王】：无文字/说话内容
# 2. 非转发贴 → 时间后无标注 + 换行【懂王】：原文标题
# 3. 彻底删除【转发源为】所有相关功能，无残留
def parse_news_type_and_content(news):
    raw_title = news.get("title", "").strip()
    no_title_flags = ["[No Title]", "no title", "untitled", "- Post from "]
    is_forward = not raw_title or any(flag in raw_title for flag in no_title_flags)
    forward_tag = "【转发贴】" if is_forward else ""

    # 提取懂王的文字内容（清洗所有冗余内容，只留纯文本）
    if is_forward:
        content = news.get("content", [{}])[0].get("value", "") if news.get("content") else ""
        clean_text = re.sub(r'<.*?>', '', content, flags=re.DOTALL)
        clean_text = re.sub(r'https?://\S+', '', clean_text).strip()
        clean_text = re.sub(r'^(\s*RT[:\s]*|\s*@\w+:)', '', clean_text, flags=re.IGNORECASE)
        trump_text = clean_text.strip() if clean_text and len(clean_text) > 2 else "无文字"
        content_text = f"\n【懂王】：{trump_text}"
    else:
        clean_title = re.sub(r'https?://\S+', '', raw_title).strip()
        content_text = f"\n【懂王】：{clean_title}"

    return forward_tag, content_text

# 抓取资讯（不用改）
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
        print("ℹ️  无新资讯，本次跳过推送")
        return False, None

# 邮件样式+完美适配换行排版（【转发贴】标红醒目，不用改）
def make_email_content(all_news):
    if not all_news:
        return "<p style='font-size:16px; color:#333;'>暂无可用的Trump Truth资讯</p>"
    news_list = all_news[:300]

    title_color = "#C8102E"
    time_color = "#FF8C00"
    serial_color = "#003366"
    news_title_color = "#1A1A1A"
    link_color = "#0066CC"
    forward_color = "#E63946" # 【转发贴】红色醒目

    email_title_html = f"""
    <p style='margin: 0 0 20px 0; padding: 10px; background-color:#F5F5F5; border-left:4px solid {title_color};'>
        <strong><span style='color:{title_color}; font-size:20px;'>♥️ Trump Truth 每日速递</span></strong>
    </p>
    """

    news_items = []
    for i, news in enumerate(news_list, 1):
        news_link = news["link"]
        show_time = get_show_time(news)
        forward_tag, content_text = parse_news_type_and_content(news)
        
        news_items.append(f"""
        <div style='margin: 0 0 15px 0; padding: 10px; background-color:#FAFAFA; border-radius:4px;'>
            <p style='margin: 0 0 8px 0; padding: 0; line-height:1.9; white-space: pre-line;'>
                <span style='color:{serial_color}; font-size:15px; font-weight:bold;'>{i}.</span> 
                <span style='color:{time_color}; font-weight: bold; font-size:15px;'>【{show_time}】</span>
                <span style='color:{forward_color}; font-weight: bold; font-size:15px;'>{forward_tag}</span>
                <span style='color:{news_title_color}; font-size:16px;'>{content_text}</span>
            </p>
            <p style='margin: 0; padding: 0; line-height:1.4;'>
                👉 <a href='{news_link}' target='_blank' style='color:{link_color}; text-decoration: none; font-size:14px; border-bottom:1px solid {link_color};'>
                    查看原文 →
                </a>
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

        current_bj_time = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        bj_date = current_bj_time.strftime("%Y-%m-%d")
        for receiver in receivers:
            msg = MIMEText(html_content, "html", "utf-8")
            msg["From"] = f"{CUSTOM_NICKNAME} <{GMAIL_EMAIL}>"
            msg["To"] = receiver
            msg["Subject"] = f"⏰ Trump Truth 每日资讯 | {bj_date}"
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
    cst_now = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"==================================================")
    print(f"📅 执行时间 | UTC：{utc_now} | 东八区：{cst_now}")
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

