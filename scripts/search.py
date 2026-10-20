"""按关键词检索知识库：有卡片的文章优先看卡片，没卡片的直接看原文。

用法：
  .venv/bin/python scripts/search.py 拖延 坚持 自律 正反馈
  .venv/bin/python scripts/search.py -n 8 实习 杂活 成长

关键词由调用方（Claude）从问题里拆出来，带上同义词；中文没分词，按子串计数。
打分：卡片标题/一句话/模型/适用场景命中权重高，原文正文命中按次数开方计分，避免长文占便宜。
"""
import argparse
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
CARDS = ROOT / "cards"


def card_sections(text):
    """把卡片切成 {小节名: 内容}，小节名取 **xxx** 开头的行。"""
    parts, name = {}, "head"
    for line in text.splitlines():
        m = re.match(r"\*\*(.+?)\*\*", line)
        if m:
            name = m.group(1)
        parts[name] = parts.get(name, "") + line + "\n"
    return parts


def score(terms, article, card):
    hits, s = set(), 0.0
    title = re.search(r'^title: "(.*)"', article, re.M)
    title = title.group(1) if title else ""
    body = article.split("---", 2)[-1]
    sec = card_sections(card) if card else {}
    for t in terms:
        n_title = title.count(t)
        n_body = body.count(t)
        n_key = sum(sec.get(k, "").count(t) for k in ("一句话", "可复用的模型", "可调用的场景")) + \
            (re.search(r"tags: \[(.*)\]", card).group(1).count(t) if card and "tags:" in card else 0)
        n_card = card.count(t) if card else 0
        if n_title or n_body or n_card:
            hits.add(t)
        s += 6 * n_title + 3 * n_key + 1 * min(n_card, 5) + math.sqrt(n_body)
    # 命中的不同关键词越多越相关
    return s * (1 + 0.5 * (len(hits) - 1)) if hits else 0.0, hits, title


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("terms", nargs="+")
    ap.add_argument("-n", type=int, default=6)
    args = ap.parse_args()

    results = []
    # 有原文就原文+卡片一起搜；公开仓库没有原文时只搜卡片
    names = sorted({p.name for p in ARTICLES.glob("*.md")} | {p.name for p in CARDS.glob("*.md")})
    for name in names:
        a, c = ARTICLES / name, CARDS / name
        article = a.read_text(encoding="utf-8") if a.exists() else f'---\ntitle: "{name[11:-3]}"\n---\n'
        card = c.read_text(encoding="utf-8") if c.exists() else ""
        s, hits, title = score(args.terms, article, card)
        if s > 0:
            results.append((s, a, c if card else None, hits, title, card, article))

    results.sort(key=lambda r: r[0], reverse=True)
    n_cards = len(list(CARDS.glob("*.md")))
    print(f"共 {len(list(ARTICLES.glob('*.md')))} 篇原文、{n_cards} 张卡片；命中 {len(results)} 篇，显示前 {args.n} 篇\n")
    for s, a, c, hits, title, card, article in results[: args.n]:
        date = a.name[:10]
        print(f"[{s:.1f}] 《{title}》{date}  命中：{'、'.join(sorted(hits))}")
        if c:
            one = re.search(r"\*\*(?:作者回答的)?一句话\*\*：(.+)", card)
            print(f"  卡片：{c.relative_to(ROOT)}")
            if one:
                print(f"  一句话：{one.group(1)[:120]}")
        else:
            body = article.split("---", 2)[-1]
            t = next(iter(hits))
            i = body.find(t)
            snippet = re.sub(r"!\[[^\]]*\]\([^)]*\)|\s+", " ", body[max(0, i - 40): i + 80])
            print(f"  （还没有卡片）原文：{a.relative_to(ROOT)}")
            print(f"  片段：…{snippet.strip()}…")
        print()


if __name__ == "__main__":
    main()
