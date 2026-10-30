"""按关键词检索观点卡片（只用标准库，claude.ai 的代码执行环境可直接跑）。

用法：
  python3 scripts/search.py -n 8 实习 学生 毕业 学历     # 检索
  python3 scripts/search.py --show 2024-07-10 2023-06-12  # 看整张卡片

卡片按月存在 references/cards/YYYY-MM.md，每张以 <!-- card 日期 --> 开头。
中文没分词，按子串计数。标题、一句话、模型、适用场景、标签命中权重高；
命中的不同关键词越多越靠前。
"""
import argparse
import re
from pathlib import Path

CARDS = Path(__file__).resolve().parent.parent / "references" / "cards"
ARTICLES = CARDS.parent / "articles"
KEY_SECTIONS = ("一句话", "可复用的模型", "可调用的场景")


def load_cards():
    cards = {}
    for p in sorted(CARDS.glob("*.md")):
        for date, text in re.findall(r"<!-- card (\S+) -->\n(.*?)(?=<!-- card |\Z)", p.read_text(encoding="utf-8"), re.S):
            if date in cards:
                raise ValueError(f"重复卡片 ID：{date}")
            cards[date] = text.strip()
    return cards


def load_articles():
    articles = {}
    for p in sorted(ARTICLES.glob("*.md")):
        for key, text in re.findall(r"<!-- article (\S+) -->\n(.*?)(?=<!-- article |\Z)", p.read_text(encoding="utf-8"), re.S):
            if key in articles:
                raise ValueError(f"重复原文 ID：{key}")
            articles[key] = text.strip()
    return articles


def sections(text):
    parts, name = {}, "head"
    for line in text.splitlines():
        m = re.match(r"\*\*(?:作者回答的)?(.+?)\*\*", line)
        if m:
            name = m.group(1)
        parts[name] = parts.get(name, "") + line + "\n"
    return parts


def card_title(text):
    m = re.search(r"^# (.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def score(terms, title, text):
    sec = sections(text)
    tags = re.search(r"tags: \[(.*)\]", text)
    tags = tags.group(1) if tags else ""
    hits, s = set(), 0.0
    for t in terms:
        n_title, n_tag = title.count(t), tags.count(t)
        n_key = sum(sec.get(k, "").count(t) for k in KEY_SECTIONS)
        n_all = text.count(t)
        if n_all or n_title:
            hits.add(t)
        s += 6 * n_title + 4 * n_tag + 3 * n_key + min(n_all, 5)
    return (s * (1 + 0.5 * (len(hits) - 1)) if hits else 0.0), hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("terms", nargs="*")
    ap.add_argument("-n", type=int, default=8)
    ap.add_argument("--show", nargs="+", metavar="日期", help="按日期输出整张卡片")
    args = ap.parse_args()
    cards = load_cards()
    articles = load_articles()
    documents = {**cards, **articles}

    if args.show:
        for date in args.show:
            print(documents.get(date, f"没有 {date}（见 references/index.md 或 articles-index.md）"))
            print("\n" + "=" * 40 + "\n")
        return
    if not args.terms:
        ap.error("给几个关键词，或用 --show 日期")

    results = []
    covered = {(key, card_title(text)) for key, text in cards.items()}
    for date, text in documents.items():
        title = card_title(text)
        if date.startswith("article:"):
            published = re.search(r'^date: "([^"]+)"$', text, re.M)
            if published and (published.group(1), title) in covered:
                continue  # 搜索结果优先显示同篇卡片，原文仍可用 ID 打开。
        s, hits = score(args.terms, title, text)
        if s > 0:
            one = re.search(r"\*\*(?:作者回答的)?一句话\*\*：(.+)", text)
            kind = "原文，未提炼" if date.startswith("article:") else "卡片"
            if kind.startswith("原文"):
                s *= 0.65
            results.append((s, date, title, hits, one.group(1) if one else "", kind))
    results.sort(key=lambda r: r[0], reverse=True)

    print(f"卡片 {len(cards)} 张 / 可检索原文 {len(articles)} 篇，命中 {len(results)} 条，显示前 {args.n} 条\n")
    for s, date, title, hits, one, kind in results[: args.n]:
        print(f"[{s:.0f}] {date} 《{title}》【{kind}】 命中：{'、'.join(sorted(hits))}")
        if one:
            print(f"  一句话：{one[:150]}")
        print()
    if results:
        top = " ".join(r[1] for r in results[: min(args.n, 5)])
        print(f"看全文：python3 scripts/search.py --show {top}")


if __name__ == "__main__":
    main()
