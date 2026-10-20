"""从公众号「合集」的公开接口拉文章列表，合并进 data/list.jsonl（不需要登录，不受后台限流影响）

用法：
  .venv/bin/python scripts/fetch_album.py                       # 默认拉「认知」合集
  .venv/bin/python scripts/fetch_album.py --album <album_id>

拉完会核对条数是否等于合集声明的文章数，不一致会报出来、退出码非 0。
"""
import argparse
import json
import random
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
            r.raise_for_status()
            data = r.json()
            if data.get("base_resp", {}).get("ret") != 0:
                raise RuntimeError(f"接口返回异常：{data.get('base_resp')}")
            return data["getalbum_resp"]
        except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
            if attempt == 3:
                raise
            print(f"  第 {attempt} 次失败（{e}），{wait} 秒后重试")
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--album", default=DEFAULT_ALBUM)
    args = ap.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = UA
    LIST_FILE.parent.mkdir(exist_ok=True)

    existing = {}
    if LIST_FILE.exists():
        for line in LIST_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                existing[item["aid"]] = item

    found, begin, declared, album_title = {}, None, None, ""
    while True:
        resp = get_page(session, args.album, begin)
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
                          "create_time": int(a["create_time"]), "album": album_title}
        print(f"  已拉 {len(found)}/{declared} 篇")
        if resp.get("continue_flag") != "1" or not arts or new == 0:
            break
        last = arts[-1]
        begin = (last["msgid"], last["itemidx"])
        time.sleep(random.uniform(2, 4))

    merged = {**existing, **found}
    with LIST_FILE.open("w", encoding="utf-8") as f:
        for item in sorted(merged.values(), key=lambda x: x["create_time"], reverse=True):
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\n合集「{album_title}」：拉到 {len(found)} 篇，合集声明 {declared} 篇；list.jsonl 现共 {len(merged)} 篇")
    if len(found) != declared:
        print(f"✗ 条数对不上，差 {declared - len(found)} 篇，需要排查")
        sys.exit(1)


if __name__ == "__main__":
    main()
