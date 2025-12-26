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
CUSTOM_NICKNAME = "📩路透快讯"

# ---------------------- 基础配置（路透社Feed，不用改） ----------------------
RSS_URL = "https://reutersnew.buzzing.cc/feed.xml"  # 路透社资讯源
LAST_LINK_FILE = "last_link.txt"  # 防重复推送的历史链接文件
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# 提取资讯时间（分时优先，否则月日，不用改）
def get_show_time(news):
    content = news.get("content", [{}])[0].get("value", "") if news.get("content") else ""
    try:
        pattern = r'(\d{2}:\d{2})<\/time>'
        hour_min = re.search(pattern, content).group(1)
        return hour_min
    except:
        updated_str = news.get("updated", news.get("published", ""))
        date_part = updated_str.split('T')[0]
        month_day = '-'.join(date_part.split('-')[1:])
        return month_day

# 抓取路透社资讯（不用改）
def fetch_news():
    try:
        response = requests.get(RSS_URL, headers=REQUEST_HEADERS, timeout=15)
        response.raise_for_status()
        news_list = feedparser.parse(response.content).entries
        if not news_list:
            print("📭 未抓取到任何路透资讯")
            return None, None
        latest_link = news_list[0]["link"].strip()
        print(f"📭 成功抓取到{len(news_list)}条路透资讯")
        return news_list, latest_link
    except Exception as e:
        print(f"❌ 资讯抓取失败：{str(e)}")
        return None, None

# 检查是否需要推送（防重复，不用改）
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

# 生成邮件HTML内容（样式固定，不用改）
def make_email_content(all_news):
    if not all_news:
        return "暂无可用的路透资讯"
    news_list = all_news[:300]  # 最多推300条

    # 颜色配置（保持美观，不用改）
    title_color = "#2E4057"
    time_color = "#FFB400"
    serial_color = "#1E88E5"
    news_title_color = "#333333"
    link_color = "#143060"

    # 邮件标题部分
    email_title_html = f"""
    <p><strong><span style='color:{title_color};'>♥️「路透速递」</span></strong></p>
    """

    # 资讯列表部分
    news_items = []
    for i, news in enumerate(news_list, 1):
        news_link = news["link"]
        news_title = news["title"]
        show_time = get_show_time(news)
        news_items.append(f"""
        <p style='margin: 8px 0; padding: 0;'>
            <span style='color:{serial_color}; font-size: 16px;'>{i}</span>. 
            【<span style='color:{time_color}; font-weight: bold; font-size: 16px;'>{show_time}</span>】
            <span style='color:{news_title_color}; font-size: 16px;'>{news_title}</span>
        </p>
        <p style='margin: 0 0 12px 0; padding: 0;'>
            👉 <a href='{news_link}' target='_blank' style='color:{link_color}; text-decoration: underline; font-size: 14px;'>原文链接</a>
        </p>
        """)

    return email_title_html + "".join(news_items)

# 发送邮件（核心功能，不用改）
def send_email(html_content):
    # 校验环境变量是否齐全
    if not all([GMAIL_EMAIL, GMAIL_APP_PASSWORD, RECEIVER_EMAILS]):
        print("❌ 请先配置GMAIL_EMAIL、GMAIL_APP_PASSWORD、RECEIVER_EMAILS这3个Secret！")
        return

    # 处理收件人列表（多邮箱用英文逗号分隔）
    receivers = [email.strip() for email in RECEIVER_EMAILS.split(",") if email.strip()]
    if not receivers:
        print("❌ 收件人邮箱格式错误（多邮箱用英文逗号分隔）")
        return

    try:
        # 连接Gmail SMTP服务器
        smtp = smtplib.SMTP_SSL(SMTP_SERVER, 465, timeout=20)
        smtp.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        print(f"✅ Gmail连接成功，即将向{len(receivers)}个收件人发送邮件")

        # 获取当前北京时间（东八区）
        current_bj_time = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        bj_date = current_bj_time.strftime("%Y-%m-%d")  # 格式：2025-12-17

        # 逐个发送邮件（收件人仅可见自己）
        for receiver in receivers:
            msg = MIMEText(html_content, "html", "utf-8")
            msg["From"] = f"{CUSTOM_NICKNAME} <{GMAIL_EMAIL}>"
            msg["To"] = receiver
            msg["Subject"] = f"⏰｜{bj_date}"  # 邮件标题（时间标识+日期）
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

# ---------------------- 程序入口（不用改） ----------------------
if __name__ == "__main__":
    # 双时区日志（UTC + 东八区）
    utc_now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cst_now = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"==================================================")
    print(f"📅 执行时间 | UTC：{utc_now} | 东八区：{cst_now}")
    print(f"==================================================")

    try:
        # 检查并推送
        need_push, news_data = check_push()
        if need_push and news_data:
            email_html = make_email_content(news_data)
            send_email(email_html)
        print(f"🎉 本次流程结束")
    except Exception as e:
        print(f"💥 程序异常：{str(e)}")
        raise
