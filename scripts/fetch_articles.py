"""下载并清洗公众号文章：data/list.jsonl → data/raw/<id>.html → articles/<日期>_<标题>.md

用法：
  .venv/bin/python scripts/fetch_articles.py               # 处理 list.jsonl 里全部文章
  .venv/bin/python scripts/fetch_articles.py --limit 10    # 只处理最新 10 篇
  .venv/bin/python scripts/fetch_articles.py --url <链接>  # 单篇测试，不需要 list.jsonl

原始 HTML 下载过就不再请求（断点续传）；Markdown 每次都从原始 HTML 重新生成。
任何一篇失败都会写进 data/errors.jsonl 并在结尾列出，退出码非 0。
遇到微信的人机验证页会立刻停下，不继续请求。
"""
import argparse
import hashlib
import json
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify

ROOT = Path(__file__).resolve().parent.parent
LIST_FILE = ROOT / "data" / "list.jsonl"
RAW_DIR = ROOT / "data" / "raw"
ERR_FILE = ROOT / "data" / "errors.jsonl"
OUT_DIR = ROOT / "articles"
CST = timezone(timedelta(hours=8))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# 页面上出现这些字样说明拿不到正文；值为写进错误记录的原因
DEAD_MARKERS = {
    "该内容已被发布者删除": "已被作者删除",
    "此内容因违规无法查看": "因违规无法查看",
    "此内容被多人投诉": "被投诉无法查看",
    "该公众号已迁移": "公众号已迁移",
}
CAPTCHA_MARKERS = ("环境异常", "完成验证后即可继续访问")
# 点号分隔线后以这些开头的，是推广/联系方式，不是正文（在 2023~2024 年无结尾标记的文章上逐类核对过）
PROMO_AFTER_DOTS = re.compile(
    r"(Tips|提示|PS|番外|“?加密|⭐|NFT|知识星球|财商|视频号|B站|微博|公众号小号|我是蔡垒磊|长期可进|"
    r"【|AI大航海|比特币定投|好，正文结束|按照.{0,10}直播)")


class CaptchaHit(Exception):
    pass


def article_id(item):
    if item.get("aid"):
        return str(item["aid"])
    return hashlib.sha1(item["link"].encode()).hexdigest()[:12]


def download(session, url):
    for attempt, wait in enumerate((5, 15, 45), 1):
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except requests.RequestException as e:
            if attempt == 3:
                raise
            print(f"  第 {attempt} 次失败（{e.__class__.__name__}），{wait} 秒后重试")
            time.sleep(wait)


def check_page(html):
    """返回 None 表示有正文；否则返回拿不到正文的原因。"""
    if any(m in html for m in CAPTCHA_MARKERS) and 'id="js_content"' not in html:
        raise CaptchaHit()
    for marker, reason in DEAD_MARKERS.items():
        if marker in html and 'id="js_content"' not in html:
            return reason
    if 'id="js_content"' not in html:
        return "页面里没有正文区域（可能是纯图片/视频消息，或页面结构变了）"
    return None


def parse(html, item):
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return tag["content"].strip() if tag and tag.get("content") else ""

    title = meta("og:title") or (soup.select_one("#activity-name") or soup.new_tag("x")).get_text(strip=True)
    account = (soup.select_one("#js_name") or soup.new_tag("x")).get_text(strip=True)
    author = meta("author")

    m = re.search(r'var\s+ct\s*=\s*"(\d{9,})"', html)
    ts = int(m.group(1)) if m else item.get("create_time")
    if not ts:
        raise ValueError("找不到发布时间")
    date = datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d")

    logo = soup.select_one("#copyright_logo")
    original = bool(logo and "原创" in logo.get_text())

    content = soup.select_one("#js_content")
    for tag in content.find_all(["script", "style"]):
        tag.decompose()
    for img in content.find_all("img"):
        if img.get("data-src"):
            img["src"] = img["data-src"]
    # 这个号的排版里每个段落是一个 <section>，按段落处理才能保住分段
    for sec in content.find_all("section"):
        sec.name = "p"
    body = markdownify(str(content), heading_style="ATX", strip=["span"])
    body = re.sub(r"[ \t ]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # 「（完）」或「（主体|正文）部分到此结束」之后是社群/星球/私董会等推广，不进知识库。
    # 都找不到就保留全文并在文件头标出来
    # 取第一个单独成行的「（完）」：2024-12~2025-03 的文章在推广区块末尾又放了一个（核对过 29 篇）
    m = re.search(r"^[ \t*]*（完）", body, re.M)
    end = m.start() if m else body.rfind("（完）")
    if end == -1:
        m = re.search(r"(主体|正文)部分到(此|这里)结束|正文结束", body)
        # 退回到这句话开头，免得留下「今天文章的」半句
        end = max(body.rfind(c, 0, m.start()) for c in "。！？\n") + 1 if m else -1
    if end == -1:
        # 早期文章没有结尾标记：推广前有一行点号分隔线。但读者来信和回信之间、作者的「题外话」前
        # 也用同样的分隔线，所以只在分隔线后紧跟推广开头时才截
        for d in re.finditer(r"^\s*[.。·…]{10,}\s*$", body, re.M):
            after = re.sub(r"!\[[^\]]*\]\([^)]*\)|\*", "", body[d.end():]).lstrip()
            if PROMO_AFTER_DOTS.match(after):
                end = d.start()
                break
    # 「ps，我要发招募了」这类没有分隔线的推广开头（核对过全库只有 2023-05-04 一篇）；比其他截断点靠前时才用
    m = re.search(r"^[^\w]{0,6}ps[，,：: ].{0,20}(招募|报名)", body, re.M | re.I)
    if m and (end == -1 or m.start() < end):
        end = m.start()
    has_end = end != -1
    if has_end:
        body = body[:end].rstrip()
    body = re.sub(r"^(!\[[^\]]*\]\([^)]*\)\s*)?文\s*[:：]\s*\S{1,10}\s*\n", r"\1", body).strip()
    if len(body) < 50:
        raise ValueError(f"正文过短（{len(body)} 字），疑似解析失败")

    return {"title": title or item.get("title", ""), "account": account, "author": author,
            "date": date, "original": original, "end_marker": has_end, "body": body}


def write_markdown(art, item, aid):
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", art["title"]).strip("_")[:60] or aid
    path = OUT_DIR / f"{art['date']}_{safe}.md"
    front = {
        "title": art["title"], "account": art["account"], "author": art["author"],
        "date": art["date"], "original": art["original"], "end_marker": art["end_marker"],
        "url": item["link"], "id": aid,
    }
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()] + ["---", ""]
    path.write_text("\n".join(lines) + f"# {art['title']}\n\n{art['body']}\n", encoding="utf-8")
    return path


def load_items(args):
    if args.url:
        return [{"link": args.url}]
    if not LIST_FILE.exists():
        sys.exit(f"缺少文章列表 {LIST_FILE}，先拉列表或用 --url 测单篇")
    items = [json.loads(l) for l in LIST_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    items.sort(key=lambda x: x.get("create_time", 0), reverse=True)
    return items[: args.limit] if args.limit else items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--url")
    ap.add_argument("--offline", action="store_true", help="只用已下载的原始页重新生成，不发请求")
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    items = load_items(args)
    if args.offline:
        items = [it for it in items if (RAW_DIR / f"{article_id(it)}.html").exists()]
    ok, cached, errors, no_end = 0, 0, [], []
    for i, item in enumerate(items, 1):
        aid = article_id(item)
        raw = RAW_DIR / f"{aid}.html"
        label = item.get("title") or item["link"]
        print(f"[{i}/{len(items)}] {label}")
        try:
            if raw.exists():
                html = raw.read_text(encoding="utf-8")
                cached += 1
            else:
                html = download(session, item["link"])
                reason = check_page(html)
                if reason:
                    raise ValueError(reason)
                raw.write_text(html, encoding="utf-8")
                time.sleep(random.uniform(3, 6))
            art = parse(html, item)
            path = write_markdown(art, item, aid)
            print(f"  → {path.relative_to(ROOT)}")
            if not art["end_marker"]:
                no_end.append(path.relative_to(ROOT))
            ok += 1
        except CaptchaHit:
            print("\n微信返回了人机验证页，已停止。过一段时间再跑，已下载的不会重复请求。")
            errors.append({"id": aid, "title": label, "url": item["link"], "reason": "触发人机验证，未处理"})
            break
        except Exception as e:
            print(f"  ✗ 失败：{e}")
            errors.append({"id": aid, "title": label, "url": item["link"], "reason": str(e)})

    if errors:
        with ERR_FILE.open("a", encoding="utf-8") as f:
            for e in errors:
                f.write(json.dumps({**e, "at": datetime.now(CST).isoformat(timespec="seconds")},
                                   ensure_ascii=False) + "\n")
    print(f"\n完成：成功 {ok} 篇（其中 {cached} 篇用已下载的原始页），失败 {len(errors)} 篇")
    for e in errors:
        print(f"  ✗ {e['title']}：{e['reason']}")
    if no_end:
        print(f"\n{len(no_end)} 篇没找到「（完）」，保留了全文（可能带推广内容），需要人工看一下：")
        for p in no_end:
            print(f"  ? {p}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
