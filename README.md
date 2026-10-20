# 请辩知识库（非官方读书笔记）

把公众号「请辩」（作者：蔡垒磊）合集「认知」里的 402 篇文章（2023-01 ~ 2026-10）整理成**观点卡片**和一份**思考方法总结**，
让 AI 助手（Codex、Cursor、Claude、ChatGPT、Gemini 等都可以）按作者的思考框架分析你的问题，同时标明每个观点出自哪篇文章、哪些是推演。

## ⚠️ 声明

- **这是个人整理的非官方笔记，与作者及其公众号没有任何关联，也未经作者审阅或认可。**
- 观点归原作者蔡垒磊所有。卡片里的「一句话」「论证链」「可复用的模型」是整理者的**转述和理解**，可能有偏差，一切以原文为准；
  「使用边界」是整理者的注释，**不是作者观点**。
- **本仓库不包含任何文章原文。** 每张卡片只摘一句很短的原文作为锚句，并附原文链接，请到公众号阅读全文、支持作者。
- 作者的付费社群、课程、产品推广等内容没有收入卡片，卡片也不构成任何投资建议。
- 如果作者或权利人认为本仓库有任何不妥，请提 issue，我们会立即修改或删除。

## 里面有什么

| 路径 | 内容 |
|---|---|
| `cards/` | 402 张观点卡片，一篇文章一张，文件名 `日期_标题.md`，frontmatter 里有原文链接 |
| `方法层.md` | 从全部卡片归纳的作者思考方式：14 条思考习惯、常追问的问题、论证风格、使用边界，每条标出处日期 |
| `AGENTS.md` | 给编程类 agent 的说明：怎么用方法层和卡片回答问题（`CLAUDE.md` 引用它） |
| `prompts/system-prompt.md` | 给聊天类工具的通用系统提示词 |
| `skill_src/` | Agent Skill 格式的模板：`SKILL.md` + 只用标准库的检索脚本 |
| `scripts/` | 抓取、清洗、核对、检索、打包工具（见下文），检索和打包只用 Python 标准库 |
| `data/list.jsonl` | 文章列表（标题、发布时间、原文链接） |

每张卡片的结构：一句话 / 论证链 / 可复用的模型 /（典型例子）/ 可调用的场景 / 原文锚句 / 使用边界（整理者注）。
读者来信类文章会把读者的问题和作者的回答分开写。

## 用法

问法都一样：「用请辩的思路看看：……」「蔡叔会怎么选」「请辩有没有写过……」。

### 下载就能用（不用装任何东西）

到 [Releases](https://github.com/Dazzle1226/think-like-qingbian/releases/latest) 下载：

| 你用的 | 下载 | 怎么装 |
|---|---|---|
| **Claude**（claude.ai 网页 / App） | [`qingbian.skill`](https://github.com/Dazzle1226/think-like-qingbian/releases/latest/download/qingbian.skill) | 设置 → Capabilities：打开「Code execution and file creation」→ Skills → Upload skill，选这个文件 |
| **ChatGPT、Gemini、豆包、Kimi 等** | [`qingbian-chat.zip`](https://github.com/Dazzle1226/think-like-qingbian/releases/latest/download/qingbian-chat.zip) | 解压后，把 `00-method.md` 和 4 个 `cards-*.md` 上传到知识库 / 文件里（ChatGPT 建 GPT 或 Project，Gemini 建 Gem）；把 `system-prompt.md` 的全部内容粘贴到「指令 / 系统提示词」 |

不支持自定义指令的工具，可以在对话开头上传这 5 个文件，再把 `system-prompt.md` 的内容作为第一条消息发出去。

### 编程类 agent（Codex、Cursor、Claude Code、Gemini CLI、Cline 等）

克隆本仓库，在仓库目录里打开你的 agent 直接问。仓库根目录的 `AGENTS.md` 写了完整的回答流程
（先读方法层 → 用 `scripts/search.py` 检索卡片 → 按固定格式回答并区分【原文】/【推演】），读 `AGENTS.md` 的 agent 会自动照做；
不会自动读的，第一句话告诉它「先读 AGENTS.md」即可。

Claude Code 也可以装成全局 skill：把 `qingbian.skill` 解压到 `~/.claude/skills/`，得到 `~/.claude/skills/qingbian/`。

### 自己生成下载包

改了卡片或方法层后，用这两条命令重新生成上面两个文件（只用 Python 标准库）：

```bash
python3 scripts/build_claude_skill.py   # → dist/qingbian.skill（卡片按月合并，满足 claude.ai 的 200 文件、纯 ASCII 路径限制）
python3 scripts/build_bundle.py         # → dist/bundle/ 和 dist/qingbian-chat.zip
```

### 直接检索卡片

```bash
python3 scripts/search.py -n 8 实习 学历 毕业 试错
```

## 自己在本地下载原文（可选）

原文不在仓库里。如果想在本地对照原文、核对锚句，或者用同一套工具整理你喜欢的其他公众号：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_album.py          # 从公开的合集接口拉文章列表 → data/list.jsonl
.venv/bin/python scripts/fetch_articles.py       # 下载并清洗 → articles/（可断点续传，自带限速）
.venv/bin/python scripts/check_cards.py          # 有原文时会逐字核对每张卡片的锚句
```

请遵守平台规则、控制请求频率。**下载的原文仅供个人阅读，请勿再次分发。**
`fetch_articles.py` 会把每篇文章正文截到结尾标记（「（完）」「正文部分到此结束」等）之前，去掉之后的招募和推广，规则说明见 `AGENTS.md`。

## 许可证

- **代码与提示词**（`scripts/`、`skill_src/`、`prompts/`、`AGENTS.md`）：[MIT](LICENSE)
- **整理内容**（`cards/`、`方法层.md`）：[CC BY-NC 4.0](LICENSE-CONTENT.md)——可以自由转载和改编，需署名、不得用于商业目的。
  这只针对整理者的转述与注释；文章原文及其中观点的权利仍归原作者所有。
