import feedparser
import smtplib
import socket
from email.mime.text import MIMEText
import requests
import re
import os
import datetime
from datetime import timezone, timedelta

# ---------------------- 全局配置（按需修改） ----------------------
# Gmail配置（从GitHub Secret读取）
GMAIL_EMAIL = os.getenv("GMAIL_EMAIL")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECEIVER_EMAILS = os.getenv("RECEIVER_EMAILS")
# RSS配置
RSS_URL = "https://www.trumpstruth.org/feed"
LAST_LINK_FILE = "last_link.txt"
# 网络请求配置
REQUEST_TIMEOUT = 15  # 请求超时时间（秒）
SOCKET_TIMEOUT = 20  # 全局socket超时
# 邮件样式配置
CUSTOM_NICKNAME = "📩懂王快讯"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

# ---------------------- 请求头配置（解决415错误核心） ----------------------
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",  # 明确支持RSS/XML媒体类型
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive"
}

# ---------------------- 工具函数：时间转换（原逻辑保留） ----------------------
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
                except ValueError:
                    continue
        except Exception:
            pass

    updated_str = news.get("updated", "")
    if updated_str:
        try:
            dt_utc = datetime.datetime.fromisoformat(updated_str.replace('Z', '+00:00'))
            dt_beijing = dt_utc.astimezone(beijing_tz)
            return dt_beijing.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    current_bj = datetime.datetime.now(beijing_tz)
    return current_bj.strftime("%Y-%m-%d %H:%M")

# ---------------------- 工具函数：新闻内容解析（原逻辑保留） ----------------------
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

# ---------------------- 核心函数：RSS抓取（修复415+超时控制） ----------------------
def fetch_news():
    # 设置全局socket超时，兜底网络请求
    socket.setdefaulttimeout(SOCKET_TIMEOUT)
    try:
        # 用requests请求实现超时，解决feedparser不支持timeout的问题
        response = requests.get(
            RSS_URL,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True  # 自动处理重定向
        )
        # 校验HTTP状态码
        response.raise_for_status()
        # 解析RSS内容
        feed = feedparser.parse(response.content)
        # 校验RSS解析是否出错
        if feed.get("bozo") != 0:
            raise Exception(f"RSS解析错误: {str(feed.get('bozo_exception'))}")
        # 提取新闻列表
        news_list = feed.entries
        if not news_list:
            print("📭 未抓取到任何Trump Truth资讯")
            return None, None
        # 获取最新新闻链接
        latest_link = news_list[0]["link"].strip()
        print(f"📭 成功抓取到{len(news_list)}条Trump Truth资讯")
        return news_list, latest_link
    except requests.exceptions.Timeout:
        print("❌ 资讯抓取失败：请求超时（超过{REQUEST_TIMEOUT}秒）")
        return None, None
    except requests.exceptions.HTTPError as e:
        print(f"❌ 资讯抓取失败：HTTP错误 {e.response.status_code} - {e.response.reason}")
        return None, None
    except requests.exceptions.ConnectionError:
        print("❌ 资讯抓取失败：网络连接错误（目标服务器不可达/域名解析失败）")
        return None, None
    except Exception as e:
        print(f"❌ 资讯抓取失败：{str(e)}")
        return None, None

# ---------------------- 核心函数：检查是否需要推送（防重复） ----------------------
def check_push():
    is_first_run = not os.path.exists(LAST_LINK_FILE)
    last_saved_link = ""
    # 读取历史链接
    if not is_first_run:
        try:
            with open(LAST_LINK_FILE, 'r', encoding='utf-8') as f:
                last_saved_link = f.read().strip()
        except Exception as e:
            print(f"⚠️  历史链接读取失败，按首次运行处理：{str(e)}")
            is_first_run = True
    # 抓取新闻
    all_news, current_latest_link = fetch_news()
    if not all_news or not current_latest_link:
        return False, None
    # 判断是否为新资讯
    if is_first_run or current_latest_link != last_saved_link:
        try:
            with open(LAST_LINK_FILE, 'w', encoding='utf-8') as f:
                f.write(current_latest_link)
            print("🚨 新资讯检测到，准备推送！")
            return True, all_news
        except Exception as e:
            print(f"❌ 历史链接写入失败：{str(e)}")
            return False, None
    else:
        print(f"ℹ️  无新资讯，本次跳过推送")
        return False, None

# ---------------------- 核心函数：生成邮件HTML内容（原样式保留） ----------------------
def make_email_content(all_news):
    if not all_news:
        return "<p style='font-size:16px; color:#FFFFFF;'>暂无可用的Trump Truth资讯</p>"
    # 限制最多推送300条，避免邮件过大
    news_list = all_news[:300]

    # 颜色与样式配置
    title_color = "#C8102E"
    time_color = "#1E90FF"
    serial_color = "#FFFFFF"
    forward_color = "#C8102E"
    content_color = "#FFFFFF"
    link_color = "#1E90FF"
    arrow_color = "#FFCC00"
    content_indent = "20px"
    card_margin = "0 0 4px 0"
    card_padding = "6px"
    line_margin = "0 0 4px 0"

    # 邮件标题HTML
    email_title_html = f"""
    <p style='margin: 0 0 8px 0; padding: 6px; background-color:#2D2D2D; border-left:4px solid {title_color};'>
        <strong><span style='color:{title_color}; font-size:18px;'>♥️ 「7*24真实社交速递」</span></strong>
    </p>
    """

    # 生成新闻列表HTML
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
                    <span style='color:{forward_color}; font-weight:bold; margin:0 1px; font-size:15px;'>{forward_tag}</span>
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

# ---------------------- 核心函数：发送邮件（精细化异常处理） ----------------------
def send_email(html_content):
    # 校验Gmail配置
    if not all([GMAIL_EMAIL, GMAIL_APP_PASSWORD, RECEIVER_EMAILS]):
        print("❌ 请先配置GMAIL_EMAIL、GMAIL_APP_PASSWORD、RECEIVER_EMAILS环境变量！")
        return
    # 解析收件人
    receivers = [email.strip() for email in RECEIVER_EMAILS.split(",") if email.strip()]
    if not receivers:
        print("❌ 收件人邮箱格式错误（多邮箱用英文逗号分隔）")
        return
    # 发送邮件
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=20) as smtp:
            smtp.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
            print(f"✅ Gmail连接成功，即将向{len(receivers)}个收件人发送资讯邮件")
            # 生成邮件主题
            current_bj_time = datetime.datetime.now(timezone(timedelta(hours=8)))
            bj_date = current_bj_time.strftime("%Y-%m-%d")
            # 逐个发送邮件
            for receiver in receivers:
                msg = MIMEText(html_content, "html", "utf-8")
                msg["From"] = f"{CUSTOM_NICKNAME} <{GMAIL_EMAIL}>"
                msg["To"] = receiver
                msg["Subject"] = f"⏰ | {bj_date}"
                smtp.sendmail(GMAIL_EMAIL, [receiver], msg.as_string())
                print(f"✅ 已发送给：{receiver}")
        print("✅ 所有邮件发送完成！")
    except smtplib.SMTPAuthenticationError:
        print("""❌ Gmail登录失败！请检查：
        1. 环境变量中的邮箱/应用专用密码是否正确；
        2. Gmail是否开启「两步验证」；
        3. 应用专用密码是否为「邮件」类型。""")
    except smtplib.SMTPConnectError:
        print("❌ Gmail服务器连接失败（检查网络/服务器地址端口）")
    except Exception as e:
        print(f"❌ 邮件发送失败：{str(e)}")

# ---------------------- 程序入口 ----------------------
if __name__ == "__main__":
    # 打印执行时间
    utc_now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cst_now = datetime.datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{'='*60}")
    print(f"📅 执行时间 | UTC：{utc_now} | 北京时间：{cst_now}")
    print(f"📡 订阅源 | Trump Truth（{RSS_URL}）")
    print(f"{'='*60}")
    # 执行推送流程
    try:
        need_push, news_data = check_push()
        if need_push and news_data:
            email_html = make_email_content(news_data)
            send_email(email_html)
        print(f"🎉 本次推送流程结束")
    except Exception as e:
        print(f"💥 程序异常终止：{str(e)}")

