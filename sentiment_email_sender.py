#!/usr/bin/env python3
"""
Send a daily email report for the market sentiment tracker.
"""

from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


EMAIL_CONFIG = {
    "smtp_server": os.getenv("SMTP_SERVER", "smtp.163.com"),
    "smtp_port": int(os.getenv("SMTP_PORT", "465")),
    "use_ssl": os.getenv("SMTP_USE_SSL", "true").lower() == "true",
    "sender_email": os.getenv("SENDER_EMAIL", ""),
    "sender_password": os.getenv("SENDER_PASSWORD", ""),
    "receiver_emails": [e.strip() for e in os.getenv("RECEIVER_EMAILS", "").split(",") if e.strip()],
    "subject_prefix": "[A股情绪指标]",
}


def _load_local_email_config():
    local_path = os.path.join(os.path.dirname(__file__), "data", "email_config.local.json")
    if not os.path.exists(local_path):
        return

    with open(local_path, "r", encoding="utf-8") as handle:
        local_config = json.load(handle)

    EMAIL_CONFIG.update({key: value for key, value in local_config.items() if value not in ("", None, [])})
    if isinstance(EMAIL_CONFIG.get("receiver_emails"), str):
        EMAIL_CONFIG["receiver_emails"] = [
            item.strip() for item in EMAIL_CONFIG["receiver_emails"].split(",") if item.strip()
        ]


if not EMAIL_CONFIG["sender_password"]:
    try:
        _load_local_email_config()
    except Exception:
        pass


def load_sentiment_data(date_str=None):
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")
    history_path = os.path.join(os.path.dirname(__file__), "data", "sentiment_history.json")
    if not os.path.exists(history_path):
        return None

    with open(history_path, "r", encoding="utf-8") as handle:
        history = json.load(handle)

    for record in history:
        if record.get("date") == target_date:
            return record
    return None


def load_latest_sentiment_data():
    history_path = os.path.join(os.path.dirname(__file__), "data", "sentiment_history.json")
    if not os.path.exists(history_path):
        return None

    with open(history_path, "r", encoding="utf-8") as handle:
        history = json.load(handle)

    if not history:
        return None
    history = sorted(history, key=lambda item: item.get("date", ""))
    return history[-1]


def get_interpretation(score):
    if score >= 80:
        return "市场处于过热阶段，风险偏好非常高，适合控制追高冲动。"
    if score >= 60:
        return "市场偏乐观，风险偏好在扩张，但仍要防止短期过热。"
    if score >= 40:
        return "市场整体中性，适合把它当作环境过滤，而不是方向结论。"
    if score >= 20:
        return "市场偏谨慎，风险偏好较弱，更适合防守和等待确认。"
    return "市场处于极度谨慎阶段，情绪明显收缩，但不应单独作为抄底信号。"


def get_data_source_badge(source):
    source = (source or "").lower()
    if source in {"eastmoney", "akshare", "sse", "sse_plus_szse", "realtime_cross_section", "index_panel", "eastmoney_indices", "sina_spot"}:
        return "真实/代理"
    if source in {"mock", "simulated"}:
        return "模拟"
    if source in {"manual_input"}:
        return "手动录入"
    if source in {"estimate", "estimated"}:
        return "估算"
    if not source:
        return "缺失"
    return source


def _fmt_number(value, digits=2, suffix=""):
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except Exception:
        return str(value)


def _component_rows(data):
    components = data.get("components", {})
    raw_data = data.get("raw_data", {})
    rows = [
        ("市场广度", components.get("market_breadth"), raw_data.get("breadth_source")),
        ("横截面情绪", components.get("cross_section"), raw_data.get("cross_section_source")),
        ("成交活跃度", components.get("volume_change"), raw_data.get("volume_source", "derived")),
        ("波动率", components.get("volatility"), raw_data.get("volatility_source", "derived")),
        ("北向资金", components.get("north_flow"), raw_data.get("north_source")),
        ("两融变化", components.get("margin_trading"), raw_data.get("margin_source")),
        ("趋势", components.get("trend", components.get("index_change")), raw_data.get("trend_source", "derived")),
    ]
    return rows


def generate_email_content(data):
    if not data:
        return None, None

    date = data["date"]
    score = float(data["sentiment_score"])
    level = data["sentiment_level"]
    coverage = data.get("coverage")
    raw = data.get("raw_data", {})

    if score >= 80:
        color = "#c53030"
    elif score >= 60:
        color = "#dd6b20"
    elif score >= 40:
        color = "#2f855a"
    elif score >= 20:
        color = "#b7791f"
    else:
        color = "#2b6cb0"

    component_html = "".join(
        f"""
        <tr>
            <td style="padding:10px 0;border-bottom:1px solid #eee;">{name}</td>
            <td style="padding:10px 0;border-bottom:1px solid #eee;text-align:right;">{_fmt_number(score_value)}</td>
            <td style="padding:10px 0;border-bottom:1px solid #eee;text-align:right;color:#666;">{get_data_source_badge(source)}</td>
        </tr>
        """
        for name, score_value, source in _component_rows(data)
    )

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; background:#f7f7f7; padding:24px; }}
            .card {{ max-width:720px; margin:0 auto; background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 8px 24px rgba(0,0,0,0.08); }}
            .header {{ padding:28px 32px; background:#1f2937; color:#fff; }}
            .score {{ padding:28px 32px; border-bottom:1px solid #eee; }}
            .score-number {{ font-size:48px; font-weight:700; color:{color}; }}
            .section {{ padding:24px 32px; }}
            .muted {{ color:#666; font-size:13px; }}
            table {{ width:100%; border-collapse:collapse; }}
            .pill {{ display:inline-block; margin-left:8px; padding:2px 8px; border-radius:999px; background:#edf2f7; color:#4a5568; font-size:12px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">
                <div style="font-size:24px;font-weight:700;">A股情绪指标日报</div>
                <div class="muted" style="color:#d1d5db;margin-top:6px;">{date}</div>
            </div>
            <div class="score">
                <div class="score-number">{score:.2f}</div>
                <div style="font-size:20px;font-weight:700;color:{color};margin-top:8px;">{level}</div>
                <div class="muted" style="margin-top:10px;">
                    覆盖度: {_fmt_number(coverage, 2)} | 可用组件: {data.get("available_components", "N/A")}
                </div>
                <div style="margin-top:14px;line-height:1.7;color:#333;">{get_interpretation(score)}</div>
            </div>
            <div class="section">
                <div style="font-size:18px;font-weight:700;margin-bottom:14px;">分项得分</div>
                <table>
                    <thead>
                        <tr>
                            <th align="left">组件</th>
                            <th align="right">得分</th>
                            <th align="right">数据状态</th>
                        </tr>
                    </thead>
                    <tbody>
                        {component_html}
                    </tbody>
                </table>
            </div>
            <div class="section" style="background:#fafafa;">
                <div style="font-size:18px;font-weight:700;margin-bottom:14px;">市场数据</div>
                <div style="line-height:1.9;color:#333;">
                    上证收盘: {_fmt_number(raw.get("index_close"))}<br>
                    指数涨跌: {_fmt_number(raw.get("index_change"), 2, "%")}<br>
                    日收益率: {_fmt_number(raw.get("daily_return", 0) * 100, 2, "%")}<br>
                    成交额: {_fmt_number((raw.get("volume") or 0) / 1e8, 2, " 亿")}
                </div>
            </div>
            <div class="section">
                <div class="muted">
                    说明：该指标适合作为市场环境参考，不建议单独作为交易触发条件。<br>
                    发送时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    text_lines = [
        f"A股情绪指标日报 - {date}",
        "",
        f"总分: {score:.2f}",
        f"等级: {level}",
        f"覆盖度: {_fmt_number(coverage, 2)}",
        f"可用组件: {data.get('available_components', 'N/A')}",
        "",
        "分项得分:",
    ]
    for name, score_value, source in _component_rows(data):
        text_lines.append(f"- {name}: {_fmt_number(score_value)} | {get_data_source_badge(source)}")
    text_lines.extend(
        [
            "",
            "市场数据:",
            f"- 上证收盘: {_fmt_number(raw.get('index_close'))}",
            f"- 指数涨跌: {_fmt_number(raw.get('index_change'), 2, '%')}",
            f"- 日收益率: {_fmt_number((raw.get('daily_return', 0) or 0) * 100, 2, '%')}",
            f"- 成交额: {_fmt_number((raw.get('volume') or 0) / 1e8, 2, ' 亿')}",
            "",
            "解读:",
            get_interpretation(score),
        ]
    )
    text_content = "\n".join(text_lines)
    return html_content, text_content


def _validate_email_config(config):
    missing = []
    if not config.get("sender_email"):
        missing.append("sender_email")
    if not config.get("sender_password"):
        missing.append("sender_password")
    if not config.get("receiver_emails"):
        missing.append("receiver_emails")
    return missing


def send_email(html_content, text_content, date_str, attachment_path=None):
    config = EMAIL_CONFIG
    missing = _validate_email_config(config)
    if missing:
        print(f"[FAIL] 邮件配置缺失: {', '.join(missing)}")
        return False

    try:
        current = load_sentiment_data(date_str)
        level_text = current["sentiment_level"] if current else "未分类"

        message = MIMEMultipart("alternative")
        message["Subject"] = f"{config['subject_prefix']} {date_str} {level_text}"
        message["From"] = config["sender_email"]
        message["To"] = ", ".join(config["receiver_emails"])
        message.attach(MIMEText(text_content, "plain", "utf-8"))
        message.attach(MIMEText(html_content, "html", "utf-8"))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as handle:
                attachment = MIMEApplication(handle.read())
            attachment.add_header("Content-Disposition", "attachment", filename=os.path.basename(attachment_path))
            message.attach(attachment)

        if config["use_ssl"]:
            server = smtplib.SMTP_SSL(config["smtp_server"], config["smtp_port"])
        else:
            server = smtplib.SMTP(config["smtp_server"], config["smtp_port"])
            server.starttls()

        try:
            server.login(config["sender_email"], config["sender_password"])
            server.sendmail(config["sender_email"], config["receiver_emails"], message.as_string())
        finally:
            server.quit()

        print("[OK] 邮件发送成功")
        print(f"   收件人: {', '.join(config['receiver_emails'])}")
        return True
    except Exception as exc:
        print(f"[FAIL] 邮件发送失败: {exc}")
        return False


def main():
    print("=" * 60)
    print("A股情绪指标邮件发送")
    print("=" * 60)

    today = datetime.now().strftime("%Y-%m-%d")
    data = load_sentiment_data(today)
    if not data:
        data = load_latest_sentiment_data()
        if not data:
            print(f"[FAIL] 未找到 {today} 的情绪数据，也没有历史记录可回退。")
            return False
        print(f"[INFO] {today} 没有记录，回退到最近交易日 {data['date']}。")

    html_content, text_content = generate_email_content(data)

    attachment_path = None
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    target_date = data["date"]
    date_tag = target_date.replace("-", "")
    if os.path.isdir(data_dir):
        for filename in os.listdir(data_dir):
            if filename.startswith(f"sentiment_{date_tag}") and filename.endswith(".png"):
                attachment_path = os.path.join(data_dir, filename)
                break

    return send_email(html_content, text_content, target_date, attachment_path)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
