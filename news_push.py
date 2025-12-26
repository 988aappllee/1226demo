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
CUSTOM_NICKNAME = "📩Trump Truth快讯"  # 发件人昵称

# ---------------------- 基础配置（已绑定目标Feed地址） ----------------------
RSS_URL = "https://www.trumpstruth.org/feed"  # 目标RSS地址
LAST_LINK_FILE = "last_link.txt"  # 防重复推送的历史链接文件
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# 优化：增强资讯时间提取逻辑（适配更多格式）
def get_show_time(news):
    # 尝试从content中提取时间（原逻辑+扩展格式）
    content = news.get("content", [{}])[0].get("value", "") if news.get("content") else ""
    time_patterns = [
        r'(\d{2}:\d{2})<\/time>',  # 原格式：HH:MM</time>
        r'(\d{2}:\d{2}:\d{2})',    # 扩展：HH:MM:SS
        r'(\d{1,2}:\d{2}\s*[AP]M)',# 扩展：12小时制（如 9:30 AM）
    ]
    for pattern in time_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    # 从updated/published字段提取（兼容ISO格式和普通格式）
    time_str = news.get("updated", news.get("published", ""))
    if not time_str:
        return "未知时间"
    
    # 处理ISO格式（2025-12-26T15:30:00+00:00）
    if 'T' in time_str:
        time_part = time_str.split('T')[1].split('+')[0].split('-')[0]
        if ':' in time_part:
            return time_part[:5]  # 保留HH:MM
    # 处理普通格式（如 "December 26, 2025 15:30"）
    elif re.search(r'\d{2}:\d{2}', time_str):
        return re.search(r'\d{2}:\d{2}', time_str).group(0)
    
    # 最终 fallback 到月日格式
    try:
        date_obj = datetime.datetime.strptime(time_str.split('T')[0], "%Y-%m-%d")
        return date_obj.strftime("%m-%d")  # 格式：12-26
    except:
        return "未知时间"

# 新增：提取有效标题（过滤URL+清理冗余前缀，修改占位符为【转发贴，无文字】）
def get_valid_title(news):
    # 1. 获取原始标题并清洗
    raw_title = news.get("title", "").strip()
    # 排除无标题标识和无效内容
    no_title_flags = ["[No Title]", "no title", "untitled", "- Post from "]
    is_empty_title = not raw_title or any(flag in raw_title for flag in no_title_flags)
    
    if not is_empty_title:
        # 过滤原始标题中的URL
        clean_title = re.sub(r'https?://\S+', '', raw_title).strip()
        return clean_title if clean_title else raw_title
    
    # 2. 从content正文提取内容（适配转发内容，先清理HTML标签和URL）
    content = news.get("content", [{}])[0].get("value", "") if news.get("content") else ""
    # 第一步：移除所有HTML标签
    content_no_html = re.sub(r'<.*?>', '', content, flags=re.DOTALL)
    # 第二步：移除所有URL链接
    content_no_url = re.sub(r'https?://\S+', '', content_no_html).strip()
    # 第三步：清理冗余前缀（RT:/RT @/转推: 等）
    content_clean = re.sub(r'^(\s*RT[:\s]*|转推[:\s]*|分享[:\s]*)', '', content_no_url, flags=re.IGNORECASE)
    
    # 提取有效文本（非空且长度足够）
    if content_clean and len(content_clean) > 5:
        return f"【转发】{content_clean[:80]}"  # 截断过长内容
    
    # 3. 从summary/description提取（同样清理URL和前缀）
    summary = news.get("summary", "").strip() or news.get("description", "").strip()
    summary_no_html = re.sub(r'<.*?>', '', summary, flags=re.DOTALL)
    summary_no_url = re.sub(r'https?://\S+', '', summary_no_html).strip()
    summary_clean = re.sub(r'^(\s*RT[:\s]*|转推[:\s]*|分享[:\s]*)', '', summary_no_url, flags=re.IGNORECASE)
    if summary_clean and len(summary_clean) > 5:
        return f"【转发】{summary_clean[:80]}"
    
    # 4. 最终自定义占位符：改为【转发贴，无文字】
    return "【转发贴，无文字】"

# 抓取Trump Truth资讯（不用改）
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
        print(f"❌ Trump Truth资讯抓取失败：{str(e)}")
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
        print("🚨 新的Trump Truth资讯检测到，准备推送！")
        return True, all_news
    else:
        print(f"ℹ️  无新的Trump Truth资讯，本次跳过推送")
        return False, None

# 优化：调整邮件样式（颜色+字体+间距）+ 调用新标题提取函数
def make_email_content(all_news):
    if not all_news:
        return "<p style='font-size:16px; color:#333;'>暂无可用的Trump Truth资讯</p>"
    news_list = all_news[:300]  # 最多推300条

    # 优化颜色配置（更贴合主题，视觉更醒目）
    title_color = "#C8102E"    # 主标题红色（贴合Trump相关视觉）
    time_color = "#FF8C00"     # 时间橙色（突出时效性）
    serial_color = "#003366"   # 序号深蓝色（清晰区分）
    news_title_color = "#1A1A1A"# 资讯标题深灰（易读）
    link_color = "#0066CC"     # 链接蓝色（醒目且不刺眼）

    # 邮件标题部分（增大字体+加粗+间距）
    email_title_html = f"""
    <p style='margin: 0 0 20px 0; padding: 10px; background-color:#F5F5F5; border-left:4px solid {title_color};'>
        <strong><span style='color:{title_color}; font-size:20px;'>♥️ Trump Truth 每日速递</span></strong>
    </p>
    """

    # 资讯列表部分（优化字体大小+行高+间距）
    news_items = []
    for i, news in enumerate(news_list, 1):
        news_link = news["link"]
        news_title = get_valid_title(news)  # 调用新的标题提取函数
        show_time = get_show_time(news)
        news_items.append(f"""
        <div style='margin: 0 0 15px 0; padding: 10px; background-color:#FAFAFA; border-radius:4px;'>
            <p style='margin: 0 0 8px 0; padding: 0; line-height:1.6;'>
                <span style='color:{serial_color}; font-size:15px; font-weight:bold;'>{i}.</span> 
                <span style='color:{time_color}; font-weight: bold; font-size:15px; margin:0 8px;'>【{show_time}】</span>
                <span style='color:{news_title_color}; font-size:16px;'>{news_title}</span>
            </p>
            <p style='margin: 0; padding: 0; line-height:1.4;'>
                👉 <a href='{news_link}' target='_blank' style='color:{link_color}; text-decoration: none; font-size:14px; border-bottom:1px solid {link_color};'>
                    查看原文 →
                </a>
            </p>
        </div>
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
        print(f"✅ Gmail连接成功，即将向{len(receivers)}个收件人发送Trump Truth资讯邮件")

        # 获取当前北京时间（东八区）
        current_bj_time = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        bj_date = current_bj_time.strftime("%Y-%m-%d")  # 格式：2025-12-26

        # 逐个发送邮件（收件人仅可见自己）
        for receiver in receivers:
            msg = MIMEText(html_content, "html", "utf-8")
            msg["From"] = f"{CUSTOM_NICKNAME} <{GMAIL_EMAIL}>"
            msg["To"] = receiver
            msg["Subject"] = f"⏰ Trump Truth 每日资讯 | {bj_date}"  # 优化邮件主题格式
            smtp.sendmail(GMAIL_EMAIL, [receiver], msg.as_string())
            print(f"✅ Trump Truth资讯已发送给：{receiver}")

        smtp.quit()
        print("✅ 所有Trump Truth资讯邮件发送完成！")
    except smtplib.SMTPAuthenticationError:
        print("""❌ Gmail登录失败！请检查：
        1. Secrets里的邮箱/密码是否正确；
        2. Gmail是否开启「两步验证」；
        3. 应用专用密码是否有效（重新生成试试）。""")
    except Exception as e:
        print(f"❌ Trump Truth资讯邮件发送失败：{str(e)}")
        raise

# ---------------------- 程序入口（不用改） ----------------------
if __name__ == "__main__":
    # 双时区日志（UTC + 东八区）
    utc_now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cst_now = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"==================================================")
    print(f"📅 执行时间 | UTC：{utc_now} | 东八区：{cst_now}")
    print(f"📡 订阅源 | Trump Truth（{RSS_URL}）")
    print(f"==================================================")

    try:
        # 检查并推送
        need_push, news_data = check_push()
        if need_push and news_data:
            email_html = make_email_content(news_data)
            send_email(email_html)
        print(f"🎉 本次Trump Truth资讯推送流程结束")
    except Exception as e:
        print(f"💥 Trump Truth资讯推送程序异常：{str(e)}")
        raise

