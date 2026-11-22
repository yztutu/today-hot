#!/usr/bin/env python3
"""今日热榜聚合：抓取微博/知乎/B站/百度/抖音五个公开热榜，
生成 README.md、index.html 和 data/latest.json。

每个来源独立容错：抓到就用真实数据，抓不到就在产出里如实标注该源暂缺，
绝不编造条目。用标准库 + requests 实现。
"""
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CST = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TOP_N = 20  # 每个榜单保留条数


def fmt_heat(n):
    """把热度数字格式化成中文可读形式；拿不到就返回空串。"""
    if n is None or n == "":
        return ""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1e8:
        return f"{n / 1e8:.1f} 亿"
    if n >= 1e4:
        return f"{n / 1e4:.1f} 万"
    return str(int(n))


def get(url, **kw):
    kw.setdefault("timeout", 20)
    headers = {"User-Agent": UA}
    headers.update(kw.pop("headers", {}))
    return requests.get(url, headers=headers, **kw)


# ---------------- 微博热搜 ----------------
def fetch_weibo():
    url = "https://weibo.com/ajax/side/hotSearch"
    r = get(url, headers={"Referer": "https://weibo.com/"})
    r.raise_for_status()
    data = r.json()
    d = data.get("data") or {}
    band = d.get("realtime") or d.get("band_list") or []
    items = []
    for it in band:
        title = it.get("note") or it.get("word")
        if not title:
            continue
        word = it.get("word") or title
        link = "https://s.weibo.com/weibo?q=" + urllib.parse.quote(f"#{word}#")
        items.append({"title": title, "heat": fmt_heat(it.get("num")), "url": link})
    if not items:
        raise RuntimeError("接口返回为空")
    return items[:TOP_N]


# ---------------- 知乎热榜 ----------------
def fetch_zhihu():
    # 主接口：热榜文章（部分出口 IP 会被挡，失败则走备用接口）
    try:
        return _fetch_zhihu_primary()
    except Exception:
        return _fetch_zhihu_top_search()


def _fetch_zhihu_primary():
    url = "https://api.zhihu.com/topstory/hot-lists/total"
    r = get(url, params={"limit": 50})
    r.raise_for_status()
    data = r.json()
    items = []
    for it in data.get("data") or []:
        t = it.get("target") or {}
        title = t.get("title")
        if not title:
            continue
        qid = t.get("id")
        link = f"https://www.zhihu.com/question/{qid}" if qid else "https://www.zhihu.com/hot"
        heat = ""
        m = re.search(r"([\d.]+\s*[万亿]?)", it.get("detail_text") or "")
        if m:
            heat = m.group(1) + " 热度"
        items.append({"title": title, "heat": heat, "url": link})
    if not items:
        raise RuntimeError("接口返回为空")
    return items[:TOP_N]


def _fetch_zhihu_top_search():
    # 备用接口：热搜词（与知乎存档脚本同款；德国机上此接口通，主接口不通）
    url = "https://www.zhihu.com/api/v4/search/top_search"
    r = get(url, headers={"Referer": "https://www.zhihu.com/hot"})
    r.raise_for_status()
    data = r.json()
    words = ((data.get("top_search") or {}).get("words") or [])
    items = []
    for w in words:
        title = (w.get("display_query") or w.get("query") or "").strip()
        if not title:
            continue
        items.append({"title": title, "heat": "",
                      "url": "https://www.zhihu.com/search?q=" + urllib.parse.quote(title)})
    if not items:
        raise RuntimeError("备用接口返回为空")
    return items[:TOP_N]


# ---------------- B站热门 ----------------
def fetch_bilibili():
    url = "https://api.bilibili.com/x/web-interface/popular"
    r = get(url, params={"ps": TOP_N, "pn": 1},
            headers={"Referer": "https://www.bilibili.com/"})
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"B站接口 code={data.get('code')}")
    items = []
    for it in (data.get("data") or {}).get("list") or []:
        title = it.get("title")
        bvid = it.get("bvid")
        if not title or not bvid:
            continue
        view = (it.get("stat") or {}).get("view")
        items.append({"title": title,
                      "heat": (fmt_heat(view) + " 播放") if view else "",
                      "url": f"https://www.bilibili.com/video/{bvid}"})
    if not items:
        raise RuntimeError("接口返回为空")
    return items[:TOP_N]


# ---------------- 百度热搜 ----------------
def fetch_baidu():
    url = "https://top.baidu.com/board?tab=realtime"
    r = get(url)
    r.raise_for_status()
    html = r.text
    words = re.findall(r'"word":"((?:[^"\\]|\\.)*)"', html)
    scores = re.findall(r'"hotScore":"?(\d+)"?', html)
    urls = re.findall(r'"rawUrl":"(https?:\\?/\\?/[^"]+)"', html)
    items = []
    seen = set()
    for i, w in enumerate(words):
        try:
            title = json.loads(f'"{w}"')
        except Exception:
            title = w
        if not title or title in seen:
            continue
        seen.add(title)
        heat = fmt_heat(scores[i]) if i < len(scores) else ""
        link = ""
        if i < len(urls):
            link = urls[i].replace("\\/", "/")
        if not link:
            link = "https://www.baidu.com/s?wd=" + urllib.parse.quote(title)
        items.append({"title": title, "heat": heat, "url": link})
        if len(items) >= TOP_N:
            break
    if not items:
        raise RuntimeError("页面解析为空")
    return items


# ---------------- 抖音热榜 ----------------
def fetch_douyin():
    # 先试公开聚合接口 vvhan
    try:
        r = get("https://api.vvhan.com/api/hotlist/douyinHot")
        r.raise_for_status()
        data = r.json()
        items = []
        for it in data.get("data") or []:
            title = it.get("title")
            if not title:
                continue
            link = it.get("url") or ("https://www.douyin.com/search/" +
                                     urllib.parse.quote(title))
            items.append({"title": title,
                          "heat": fmt_heat(it.get("hotValue") or it.get("hot")),
                          "url": link})
        if items:
            return items[:TOP_N]
    except Exception:
        pass  # 落到官方接口兜底
    # 官方热榜接口兜底
    url = "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/"
    r = get(url)
    r.raise_for_status()
    data = r.json()
    items = []
    for it in data.get("word_list") or []:
        title = it.get("word")
        if not title:
            continue
        link = "https://www.douyin.com/search/" + urllib.parse.quote(title)
        items.append({"title": title, "heat": fmt_heat(it.get("hot_value")), "url": link})
    if not items:
        raise RuntimeError("两个接口均无数据")
    return items[:TOP_N]


SOURCES = [
    ("weibo", "微博热搜", "🔥", fetch_weibo),
    ("zhihu", "知乎热榜", "💡", fetch_zhihu),
    ("bilibili", "B站热门", "📺", fetch_bilibili),
    ("baidu", "百度热搜", "🔍", fetch_baidu),
    ("douyin", "抖音热榜", "🎵", fetch_douyin),
]


def esc_md(s):
    return (s or "").replace("|", "｜").replace("\n", " ").strip()


def esc_html(s):
    return ((s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def build_readme(now_str, results):
    total = sum(len(r["items"]) for r in results.values() if r["ok"])
    ok_names = [r["name"] for r in results.values() if r["ok"]]
    lines = [
        "# 今日热榜 · 全网热搜聚合",
        "",
        "一页看全网热点：微博热搜、知乎热榜、B站热门、百度热搜、抖音热榜，自动聚合，每小时更新。",
        "",
        f"> 🕐 最近更新：{now_str}（北京时间） · 本期共收录 **{total}** 条 · "
        f"数据来源：{'、'.join(ok_names) if ok_names else '暂无'}",
        "",
        "🌐 网页版（手机上看更方便）：https://yztutu.github.io/today-hot/",
        "",
    ]
    for key, name, emoji, _f in SOURCES:
        r = results[key]
        lines.append(f"## {emoji} {name}")
        lines.append("")
        if not r["ok"]:
            lines.append(f"> ⚠️ 该来源暂时无法获取（{r['error']}），下次更新自动重试。")
            lines.append("")
            continue
        lines.append("| 名次 | 标题 | 热度 |")
        lines.append("| --- | --- | --- |")
        for i, it in enumerate(r["items"], 1):
            title = esc_md(it["title"])
            cell = f"[{title}]({it['url']})" if it["url"] else title
            lines.append(f"| {i} | {cell} | {esc_md(it['heat'])} |")
        lines.append("")
    lines += [
        "---",
        "",
        "数据来自各平台公开热榜接口，仅做汇总展示，版权归原平台所有。"
        "本仓库由脚本自动维护，欢迎 Star ⭐ 收藏，每小时回来看一眼。",
    ]
    return "\n".join(lines) + "\n"


def build_html(now_str, results):
    total = sum(len(r["items"]) for r in results.values() if r["ok"])
    sections = []
    nav = []
    for key, name, emoji, _f in SOURCES:
        r = results[key]
        nav.append(f'<a href="#{key}">{emoji} {esc_html(name)}</a>')
        if not r["ok"]:
            body = (f'<p class="miss">⚠️ 该来源暂时无法获取'
                    f'（{esc_html(r["error"])}），下次更新自动重试。</p>')
        else:
            rows = []
            for i, it in enumerate(r["items"], 1):
                cls = ' class="top"' if i <= 3 else ""
                title = esc_html(it["title"])
                cell = (f'<a href="{esc_html(it["url"])}" target="_blank" '
                        f'rel="noopener">{title}</a>') if it["url"] else title
                rows.append(f'<tr{cls}><td class="rank">{i}</td>'
                            f'<td class="t">{cell}</td>'
                            f'<td class="h">{esc_html(it["heat"])}</td></tr>')
            body = ('<table><thead><tr><th>名次</th><th>标题</th><th>热度</th></tr>'
                    f'</thead><tbody>{"".join(rows)}</tbody></table>')
        sections.append(f'<section id="{key}"><h2>{emoji} {esc_html(name)}</h2>{body}</section>')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>今日热榜 · 全网热搜聚合</title>
<meta name="description" content="微博热搜、知乎热榜、B站热门、百度热搜、抖音热榜，一页看全网热点，每小时更新。">
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f6f7f9;color:#1f2328}}
header{{background:linear-gradient(135deg,#ff4d4f,#ff7a45);color:#fff;padding:28px 16px 20px;text-align:center}}
header h1{{margin:0 0 6px;font-size:26px}}
header p{{margin:2px 0;opacity:.92;font-size:13px}}
nav{{position:sticky;top:0;background:#fff;display:flex;gap:8px;overflow-x:auto;padding:10px 12px;box-shadow:0 1px 6px rgba(0,0,0,.08);z-index:9}}
nav a{{white-space:nowrap;text-decoration:none;color:#333;background:#f0f1f3;border-radius:999px;padding:6px 12px;font-size:13px}}
main{{max-width:760px;margin:0 auto;padding:8px 12px 32px}}
section{{background:#fff;border-radius:12px;padding:14px 14px 8px;margin-top:14px;box-shadow:0 1px 4px rgba(0,0,0,.05)}}
h2{{font-size:18px;margin:2px 0 10px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{text-align:left;color:#8a8f98;font-weight:500;border-bottom:1px solid #eee;padding:6px 4px}}
td{{border-bottom:1px solid #f2f2f2;padding:8px 4px;vertical-align:top}}
tr:last-child td{{border-bottom:none}}
td.rank{{width:34px;color:#8a8f98}}
tr.top td.rank{{color:#ff4d4f;font-weight:700}}
td.h{{width:86px;text-align:right;color:#ff7a45;white-space:nowrap}}
td.t a{{color:#1f2328;text-decoration:none}}
td.t a:hover{{color:#ff4d4f}}
.miss{{color:#8a8f98;font-size:14px}}
footer{{text-align:center;color:#9aa0a6;font-size:12px;padding:18px 12px 28px;line-height:1.7}}
</style>
</head>
<body>
<header>
<h1>🔥 今日热榜</h1>
<p>微博 · 知乎 · B站 · 百度 · 抖音，一页看全网热点</p>
<p>🕐 最近更新：{esc_html(now_str)}（北京时间） · 本期共 {total} 条</p>
</header>
<nav>{''.join(nav)}</nav>
<main>{''.join(sections)}</main>
<footer>数据来自各平台公开热榜接口，仅做汇总展示，版权归原平台所有。<br>
由脚本自动维护，每小时更新 · <a href="https://github.com/yztutu/today-hot">GitHub 仓库</a></footer>
</body>
</html>
"""


def main():
    now = datetime.now(CST)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    results = {}
    for key, name, _emoji, fn in SOURCES:
        try:
            items = fn()
            results[key] = {"name": name, "ok": True, "items": items, "error": ""}
            print(f"[OK]   {name}: {len(items)} 条")
        except Exception as e:  # 独立容错：单源失败不影响其他源
            msg = f"{type(e).__name__}: {e}"[:200]
            results[key] = {"name": name, "ok": False, "items": [], "error": msg}
            print(f"[FAIL] {name}: {msg}")

    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    payload = {"updated_at": now_str, "timezone": "Asia/Shanghai",
               "sources": {k: {"name": v["name"], "ok": v["ok"],
                               "error": v["error"], "items": [
                                   {"rank": i + 1, **it}
                                   for i, it in enumerate(v["items"])]}
                           for k, v in results.items()}}
    with open(os.path.join(HERE, "data", "latest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(os.path.join(HERE, "README.md"), "w", encoding="utf-8") as f:
        f.write(build_readme(now_str, results))
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_html(now_str, results))
    ok_count = sum(1 for v in results.values() if v["ok"])
    total = sum(len(v["items"]) for v in results.values())
    print(f"完成：{ok_count}/5 个来源可用，共 {total} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
