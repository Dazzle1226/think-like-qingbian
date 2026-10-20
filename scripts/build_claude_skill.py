"""把方法层 + 全部卡片打包成可上传到 claude.ai 的 skill：dist/qingbian.skill（zip 格式）。

用法：.venv/bin/python scripts/build_claude_skill.py

步骤：先跑卡片核对（有问题就停）→ 组装 dist/qingbian/ → 校验 SKILL.md → 打成 zip。
原文不打包：体积大，卡片已含观点、论证链和逐字锚句。
"""
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "skill_src"
DIST = ROOT / "dist"
NAME = "qingbian"


def check_cards():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_cards.py")], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        sys.exit("卡片核对没通过，先修好再打包")


def validate(skill_md):
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        sys.exit("SKILL.md 缺少 frontmatter")
    fm = dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", m.group(1), re.M))
    if set(fm) - {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}:
        sys.exit(f"frontmatter 有不允许的字段：{set(fm)}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm.get("name", "")) or len(fm["name"]) > 64:
        sys.exit("name 必须是小写字母/数字/连字符，最长 64")
    desc = fm.get("description", "").strip()
    if not desc or len(desc) > 1024 or "<" in desc or ">" in desc:
        sys.exit(f"description 为空、超过 1024 字或含尖括号（当前 {len(desc)} 字）")


def write_references(ref):
    """claude.ai 拒收含中文/全角符号路径的 zip，包内一律用 ASCII 文件名：
    方法层 → method.md，卡片 → cards/日期.md（日期唯一），标题收进 index.md。"""
    cards_dir = ref / "cards"
    cards_dir.mkdir(parents=True)
    shutil.copy(ROOT / "方法层.md", ref / "method.md")
    rows = []
    for p in sorted((ROOT / "cards").glob("*.md")):
        date, title = p.stem[:10], p.stem[11:]
        dst = cards_dir / f"{date}.md"
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or dst.exists():
            sys.exit(f"卡片文件名日期不合规或重复：{p.name}")
        shutil.copy(p, dst)
        rows.append(f"- {date} 《{title}》")
    (ref / "index.md").write_text(
        f"# 卡片目录（{len(rows)} 张）\n\n文件在 `references/cards/日期.md`。\n\n" + "\n".join(rows) + "\n",
        encoding="utf-8")


def main():
    check_cards()
    out = DIST / NAME
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SRC, out, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
    write_references(out / "references")
    validate(out / "SKILL.md")

    pkg = DIST / f"{NAME}.skill"
    files = [f for f in sorted(out.rglob("*")) if f.is_file()]
    bad = [str(f.relative_to(DIST)) for f in files if not re.fullmatch(r"[A-Za-z0-9._/-]+", str(f.relative_to(DIST)))]
    if bad:
        sys.exit(f"包内路径必须是 ASCII（claude.ai 会拒收）：{bad[:5]}")
    with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(DIST))
    n_cards = len(list((out / "references" / "cards").glob("*.md")))
    print(f"\n已生成 {pkg.relative_to(ROOT)}：{n_cards} 张卡片，{pkg.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
