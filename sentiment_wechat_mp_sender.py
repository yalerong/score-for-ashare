#!/usr/bin/env python3
"""
Create and optionally publish a WeChat Official Account daily sentiment report.
"""

from __future__ import annotations

import html
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from config import DATA_DIR
from sentiment_email_sender import (
    _component_rows,
    _fmt_number,
    get_interpretation,
    load_latest_sentiment_data,
    load_sentiment_data,
)


TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
DRAFT_ADD_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"
MATERIAL_ADD_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material"
FREEPUBLISH_URL = "https://api.weixin.qq.com/cgi-bin/freepublish/submit"
MASS_SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/mass/sendall"


def _env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


WECHAT_MP_CONFIG = {
    "appid": os.getenv("WECHAT_MP_APPID", "").strip(),
    "secret": os.getenv("WECHAT_MP_SECRET", "").strip(),
    "author": os.getenv("WECHAT_MP_AUTHOR", "持志堂").strip(),
    "thumb_media_id": os.getenv("WECHAT_MP_THUMB_MEDIA_ID", "").strip(),
    "cover_image": os.getenv("WECHAT_MP_COVER_IMAGE", "").strip(),
    "content_source_url": os.getenv("WECHAT_MP_CONTENT_SOURCE_URL", "").strip(),
    "auto_publish": _env_bool("WECHAT_MP_AUTO_PUBLISH", False),
    "auto_mass_send": _env_bool("WECHAT_MP_AUTO_MASS_SEND", False),
    "timeout": float(os.getenv("WECHAT_MP_TIMEOUT", "15")),
}


def _token_cache_path():
    return Path(DATA_DIR) / "wechat_mp_token_cache.json"


def _media_cache_path():
    return Path(DATA_DIR) / "wechat_mp_media_cache.json"


def _read_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _validate_config(config):
    missing = []
    if not config.get("appid"):
        missing.append("WECHAT_MP_APPID")
    if not config.get("secret"):
        missing.append("WECHAT_MP_SECRET")
    return missing


def get_access_token(config=None):
    config = config or WECHAT_MP_CONFIG
    missing = _validate_config(config)
    if missing:
        raise RuntimeError("微信公众号配置缺失: " + ", ".join(missing))

    cache_path = _token_cache_path()
    cached = _read_json(cache_path)
    now = time.time()
    if (
        cached
        and cached.get("appid") == config["appid"]
        and cached.get("access_token")
        and float(cached.get("expires_at", 0)) > now + 60
    ):
        return cached["access_token"]

    response = requests.get(
        TOKEN_URL,
        params={
            "grant_type": "client_credential",
            "appid": config["appid"],
            "secret": config["secret"],
        },
        timeout=config.get("timeout", 15),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errcode"):
        raise RuntimeError(f"获取 access_token 失败: {payload}")

    token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 7200))
    _write_json(
        cache_path,
        {
            "appid": config["appid"],
            "access_token": token,
            "expires_at": now + max(300, expires_in - 300),
        },
    )
    return token


def _generate_default_cover(path):
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
    ax.set_facecolor("#f7f7f5")
    fig.patch.set_facecolor("#f7f7f5")
    ax.axis("off")
    ax.text(0.08, 0.68, "A股情绪指标日报", fontsize=34, fontweight="bold", color="#1f2937")
    ax.text(0.08, 0.47, "市场环境参考，不作为单独交易触发条件", fontsize=16, color="#4b5563")
    ax.text(0.08, 0.25, datetime.now().strftime("%Y-%m-%d"), fontsize=18, color="#6b7280")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    return path


def upload_cover_image(access_token, config=None):
    config = config or WECHAT_MP_CONFIG
    cover_image = config.get("cover_image")
    if cover_image:
        image_path = Path(cover_image)
    else:
        image_path = Path(DATA_DIR) / "wechat_mp_cover.png"
        if not image_path.exists():
            _generate_default_cover(image_path)

    if not image_path.exists():
        raise RuntimeError(f"封面图片不存在: {image_path}")

    with image_path.open("rb") as handle:
        response = requests.post(
            MATERIAL_ADD_URL,
            params={"access_token": access_token, "type": "image"},
            files={"media": (image_path.name, handle, "image/png")},
            timeout=config.get("timeout", 15),
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errcode"):
        raise RuntimeError(f"上传公众号封面失败: {payload}")

    media_id = payload.get("media_id")
    if not media_id:
        raise RuntimeError(f"上传公众号封面未返回 media_id: {payload}")

    _write_json(_media_cache_path(), {"thumb_media_id": media_id, "image": str(image_path)})
    return media_id


def get_thumb_media_id(access_token, config=None):
    config = config or WECHAT_MP_CONFIG
    if config.get("thumb_media_id"):
        return config["thumb_media_id"]

    cached = _read_json(_media_cache_path())
    if cached and cached.get("thumb_media_id"):
        return cached["thumb_media_id"]

    return upload_cover_image(access_token, config)


def _wechat_post(url, access_token, payload, timeout=15):
    response = requests.post(
        url,
        params={"access_token": access_token},
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("errcode"):
        raise RuntimeError(str(result))
    return result


def _score_color(score):
    if score >= 80:
        return "#c53030"
    if score >= 60:
        return "#dd6b20"
    if score >= 40:
        return "#2f855a"
    if score >= 20:
        return "#b7791f"
    return "#2b6cb0"


def generate_article(data, config=None):
    config = config or WECHAT_MP_CONFIG
    date = data["date"]
    score = float(data["sentiment_score"])
    level = data["sentiment_level"]
    raw = data.get("raw_data", {})
    amount = raw.get("amount", raw.get("volume"))
    color = _score_color(score)

    component_items = []
    for name, value, _source in _component_rows(data):
        component_items.append(
            f"<li>{html.escape(str(name))}：<strong>{html.escape(_fmt_number(value))}</strong></li>"
        )

    title = f"A股情绪指标日报 {date}"
    digest = f"总分 {score:.2f}，等级 {level}，覆盖度 {_fmt_number(data.get('coverage'), 2)}。"
    content = f"""
<section style="font-size:16px;line-height:1.8;color:#222;">
  <h2>A股情绪指标日报</h2>
  <p style="color:#666;">{html.escape(date)}</p>
  <p style="font-size:20px;">总分：<strong style="color:{color};">{score:.2f}</strong></p>
  <p>等级：<strong>{html.escape(str(level))}</strong></p>
  <p>覆盖度：{html.escape(_fmt_number(data.get("coverage"), 2))} | 可用组件：{html.escape(str(data.get("available_components", "N/A")))}</p>
  <h3>分项</h3>
  <ul>
    {"".join(component_items)}
  </ul>
  <h3>市场数据</h3>
  <p>
    上证收盘：{html.escape(_fmt_number(raw.get("index_close")))}<br/>
    指数涨跌：{html.escape(_fmt_number(raw.get("index_change"), 2, "%"))}<br/>
    日收益率：{html.escape(_fmt_number((raw.get("daily_return", 0) or 0) * 100, 2, "%"))}<br/>
    成交额：{html.escape(_fmt_number((amount or 0) / 1e8, 2, " 亿"))}
  </p>
  <h3>解读</h3>
  <p>{html.escape(get_interpretation(score))}</p>
  <p style="color:#666;font-size:14px;">该指标适合作为市场环境参考，不建议单独作为交易触发条件。</p>
</section>
"""
    return {
        "title": title,
        "author": config.get("author", "持志堂"),
        "digest": digest,
        "content": content,
        "content_source_url": config.get("content_source_url", ""),
    }


def create_draft(access_token, article, thumb_media_id, config=None):
    config = config or WECHAT_MP_CONFIG
    payload = {
        "articles": [
            {
                "title": article["title"],
                "author": article["author"],
                "digest": article["digest"],
                "content": article["content"],
                "content_source_url": article.get("content_source_url", ""),
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }
        ]
    }
    result = _wechat_post(DRAFT_ADD_URL, access_token, payload, timeout=config.get("timeout", 15))
    media_id = result.get("media_id")
    if not media_id:
        raise RuntimeError(f"创建公众号草稿未返回 media_id: {result}")
    return media_id


def publish_draft(access_token, media_id, config=None):
    config = config or WECHAT_MP_CONFIG
    result = _wechat_post(
        FREEPUBLISH_URL,
        access_token,
        {"media_id": media_id},
        timeout=config.get("timeout", 15),
    )
    return result.get("publish_id")


def mass_send_all(access_token, media_id, config=None):
    config = config or WECHAT_MP_CONFIG
    payload = {
        "filter": {"is_to_all": True},
        "mpnews": {"media_id": media_id},
        "msgtype": "mpnews",
        "send_ignore_reprint": 0,
    }
    result = _wechat_post(MASS_SEND_URL, access_token, payload, timeout=config.get("timeout", 15))
    return result.get("msg_id")


def send_wechat_mp_report(data, config=None):
    config = config or WECHAT_MP_CONFIG
    missing = _validate_config(config)
    if missing:
        print("[SKIP] 微信公众号未配置: " + ", ".join(missing))
        return False

    access_token = get_access_token(config)
    thumb_media_id = get_thumb_media_id(access_token, config)
    article = generate_article(data, config)
    media_id = create_draft(access_token, article, thumb_media_id, config)
    print(f"[OK] 微信公众号草稿已创建: {media_id}")

    if config.get("auto_publish"):
        publish_id = publish_draft(access_token, media_id, config)
        print(f"[OK] 微信公众号发布已提交: {publish_id}")

    if config.get("auto_mass_send"):
        msg_id = mass_send_all(access_token, media_id, config)
        print(f"[OK] 微信公众号群发已提交: {msg_id}")

    return True


def main(date_str=None):
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")
    data = load_sentiment_data(target_date)
    if not data:
        data = load_latest_sentiment_data()
        if not data:
            print(f"[FAIL] 未找到 {target_date} 的情绪数据，也没有历史记录可回退。")
            return False
        print(f"[INFO] {target_date} 没有记录，回退到最近交易日 {data['date']}。")

    return send_wechat_mp_report(data)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
