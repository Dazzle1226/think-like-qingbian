"""从公众号「合集」的公开接口拉文章列表，合并进 data/list.jsonl（不需要登录，不受后台限流影响）

用法：
  .venv/bin/python scripts/fetch_album.py                       # 默认拉「认知」合集
  .venv/bin/python scripts/fetch_album.py --album <album_id>

拉完会核对条数是否等于合集声明的文章数，不一致会报出来、退出码非 0。
"""
import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LIST_FILE = ROOT / "data" / "list.jsonl"
BIZ = "MzI0MDg5ODA2NQ=="          # 请辩
DEFAULT_ALBUM = "2745537846752641026"  # 合集「认知」
API = "https://mp.weixin.qq.com/mp/appmsgalbum"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def get_page(session, album, begin=None):
    params = {"action": "getalbum", "__biz": BIZ, "album_id": album, "count": 20, "f": "json"}
    if begin:
        params["begin_msgid"], params["begin_itemidx"] = begin
    for attempt, wait in enumerate((5, 15, 45), 1):
        try:
            r = session.get(API, params=params, timeout=20)
            if r.status_code == 429:
                raise RuntimeError("微信返回 HTTP 429 限流，停止请求")
            r.raise_for_status()
            data = r.json()
            if data.get("base_resp", {}).get("ret") != 0:
                raise RuntimeError(f"接口返回异常 ret={data.get('base_resp', {}).get('ret')}，停止请求")
            return data["getalbum_resp"]
        except requests.RequestException as e:
            if attempt == 3:
                raise
            print(f"  第 {attempt} 次失败（{e.__class__.__name__}），{wait} 秒后重试")
            time.sleep(wait)


def fetch_album(session, album):
    found, begin, declared, album_title = {}, None, None, ""
    while True:
        resp = get_page(session, album, begin)
        info = resp.get("base_info", {})
        declared = declared or int(info.get("article_count", 0))
        album_title = album_title or info.get("title", "")
        arts = resp.get("article_list") or []
        arts = arts if isinstance(arts, list) else [arts]  # 只剩一篇时接口返回的是对象
        new = 0
        for a in arts:
            aid = f"{a['msgid']}_{a['itemidx']}"
            if aid not in found:
                new += 1
            found[aid] = {"aid": aid, "title": a["title"], "link": a["url"].replace("http://", "https://"),
                          "create_time": int(a["create_time"]), "album": album_title,
                          "albums": [{"id": album, "title": album_title}]}
        print(f"  已拉 {len(found)}/{declared} 篇")
        if str(resp.get("continue_flag")) != "1" or not arts or new == 0:
            break
        last = arts[-1]
        begin = (last["msgid"], last["itemidx"])
        time.sleep(random.uniform(2, 4))

    if not declared or len(found) != declared:
        raise RuntimeError(f"合集「{album_title}」条数不符：{len(found)}/{declared}，未写入")
    print(f"合集「{album_title}」：{len(found)}/{declared}")
    return found, {"id": album, "title": album_title, "article_count": declared}


def discover_albums(raw_dir):
    found = {DEFAULT_ALBUM: "认知"}
    for path in sorted(raw_dir.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for album, title in re.findall(r"album_id:\s*'([0-9]+)',\s*title:\s*'([^']*)'", text):
            found[album] = title
    return found


def merge_items(existing, found):
    merged = dict(existing)
    for aid, item in found.items():
        old = merged.get(aid, {})
        memberships = {a["id"]: a for a in old.get("albums", [])}
        if "albums" not in old and old.get("album") == "认知":
            memberships.setdefault(DEFAULT_ALBUM, {"id": DEFAULT_ALBUM, "title": "认知"})
        memberships.update({a["id"]: a for a in item["albums"]})
        merged[aid] = {**old, **item, "album": old.get("album", item["album"]),
                       "albums": list(memberships.values())}
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--album", default=DEFAULT_ALBUM)
    ap.add_argument("--all", action="store_true", help="从已下载页面发现全部可见合集")
    args = ap.parse_args()
    session = requests.Session()
    session.headers["User-Agent"] = UA
    LIST_FILE.parent.mkdir(exist_ok=True)
    existing = {it["aid"]: it for it in (json.loads(l) for l in LIST_FILE.read_text(encoding="utf-8").splitlines() if l.strip())} if LIST_FILE.exists() else {}
    albums = discover_albums(ROOT / "data" / "raw") if args.all else {args.album: ""}
    # 本轮完整刷新这些合集的成员，保留历史文章但不保留已移出的旧归属。
    refreshed = set(albums)
    for item in existing.values():
        memberships = item.get("albums")
        if memberships is None:
            if item.get("album") != "认知":
                raise ValueError(f"旧列表未知合集归属：{item.get('album')}")
            memberships = [{"id": DEFAULT_ALBUM, "title": "认知"}]
        item["albums"] = [a for a in memberships if a["id"] not in refreshed]
    manifest = []
    for album in sorted(albums):
        print(f"拉取 {albums[album]} ({album})", flush=True)
        found, info = fetch_album(session, album)
        existing = merge_items(existing, found)
        manifest.append(info)
    tmp = LIST_FILE.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in sorted(existing.values(), key=lambda x: x["create_time"], reverse=True)), encoding="utf-8")
    tmp.replace(LIST_FILE)
    if args.all:
        (ROOT / "data" / "albums.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"去重后共 {len(existing)} 篇")


if __name__ == "__main__":
    main()
