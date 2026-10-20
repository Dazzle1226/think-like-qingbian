"""核对 cards/：七个小节齐全、锚句逐字出自原文。有问题退出码非 0。

用法：.venv/bin/python scripts/check_cards.py

原文按同名文件在 articles/ 里找；本地没有原文时（比如公开仓库）只查格式，跳过锚句比对，
用 fetch_album.py + fetch_articles.py 下载原文后即可完整核对。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "cards"
ARTICLES = ROOT / "articles"
SECTIONS = ["一句话", "论证链", "可复用的模型", "可调用的场景", "原文锚句", "使用边界"]


def main():
    problems, skipped = [], 0
    cards = sorted(CARDS.glob("*.md"))
    for c in cards:
        t = c.read_text(encoding="utf-8")
        src = ARTICLES / c.name
        art = src.read_text(encoding="utf-8") if src.exists() else None
        skipped += art is None
        missing = [s for s in SECTIONS if not re.search(rf"\*\*(作者回答的)?{s}\*\*", t)]
        if missing:
            problems.append(f"{c.name}：缺小节 {'、'.join(missing)}")
        quotes = re.findall(r"\*\*原文锚句\*\*：「(.+?)」\s*$", t, re.M)
        if not quotes:
            problems.append(f"{c.name}：没有锚句")
        for q in quotes if art is not None else []:
            if q not in art:
                problems.append(f"{c.name}：锚句不在原文里 →「{q}」")

    n_articles = len(list(ARTICLES.glob("*.md")))
    print(f"卡片 {len(cards)} 张 / 原文 {n_articles} 篇，问题 {len(problems)} 个")
    if skipped:
        print(f"  （{skipped} 张卡片本地没有对应原文，只查了格式，没有比对锚句）")
    for p in problems:
        print("  ✗", p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
