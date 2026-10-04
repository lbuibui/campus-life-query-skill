# Campus Life Query Skill · 大学生活质量指北

全国大学生活质量数据库 Skill，覆盖 6153 所高校（含 3448 所活跃 + 2705 所历史归档）的 25 个生活维度。
项目名：`campus-life-query-skill`

> 本项目基于 [University Info Skill](https://github.com/liliMozi/university-info-skill) 重构。

数据来源：[CollegesChat/university-information](https://github.com/CollegesChat/university-information)

> 最后更新：2026-09-19（数据）；2026-10-04（判定器重写、单元测试与 CI、工具与隐私加固）
>
> 数据仅供参考、娱乐和信息辅助，不代表任何学校或官方机构立场。

---

## 功能

### 1. 大学生活质量查询

支持查询 6153 所高校（3448 活跃 + 2705 归档）的真实生活条件，包括但不限于：

- 宿舍是否上床下桌
- 是否有空调
- 独立卫浴 / 澡堂距离
- 早自习、晚自习
- 晨跑 / 跑步打卡
- 寒暑假 / 小学期
- 外卖、交通、地铁
- 洗衣机、校园网、断电断网
- 食堂价格、热水、门禁、查寝等

数据来自多届学生匿名回答，因此同一学校可能存在不同校区、不同年份、不同体验之间的差异。

### 2. 简称 / 别名检索

`references/aliases.md` 收录 **2827 条**可唯一检索的别名、简称与曾用名，覆盖 **2348 所学校**（如「北邮」「华科」「人大」「央财」），解决用户用口语简称提问时按全称索引搜不到的问题。生成器保证任何别名的文字都不会等于另一所**真实学校**的全称，因此简称不会劫持全称查询；少数别名会指向一个上游以简称命名的占位条目（如「川农」→ 四川农业大学），这是有意为之。真正指向多所学校的简称（地大、华师、华农、中国地质大学、中国石油大学）不猜，单独列入文件末尾的「歧义简称」表，`query.py` 命中时会列出候选并退出。

### 3. 结构化查询与反向筛选

`tools/query.py` 按问题区块解析回答并做极性分类，支持单校查询、跨校对比和「哪些学校不断电」这类反向筛选，同时标出「分化 / 分校区差异」，避免用字面 grep 把「有人提到断电」误当成「这所学校断电」。关键词命中多个问题时（如「宿舍」→ 7 个问题），反向筛选结果按学校归并、以「命中维度」列标出该校命中了几个问题，报的是唯一学校数而不是命中行数。

```bash
python3 tools/query.py 北邮 --q 断电
python3 tools/query.py --compare 北邮 华科 --q 空调
python3 tools/query.py --reverse 独立卫浴 --polarity yes --min-yes 3
```

---

## 目录结构

```text
campus-life-query-skill/
├── SKILL.md                    # Skill 入口定义
├── README.md                   # 项目说明
├── LICENSE                     # CC BY-NC-SA 4.0 协议全文
├── NOTICE.md                   # 数据来源、署名与改动说明
├── tools/                      # 可选脚本：查询、校验、维护
│   ├── query.py                # 结构化查询 / 反向筛选（CLI 入口）
│   ├── polarity.py             # 按 25 个问题区分的极性判定器（纯标准库）
│   ├── build_aliases.py        # 生成别名索引（--check 校验是否与现存表一致）
│   ├── redact.py               # 来源列表 + 答案正文个人信息脱敏（幂等）
│   ├── consolidate.py          # 归并上游错放条目（幂等）
│   ├── patch_index.py          # 施加索引本地修正（幂等）
│   ├── verify.py               # 数据完整性回归校验（--quiet / --sample）
│   └── check_all.sh            # 一键跑完下列全部检查（与 CI 同步）
├── tests/                      # 单元测试（unittest，兼容 pytest）
│   ├── test_polarity.py        # 判定器逐题回归 + 边界样例
│   └── test_query.py           # 解析 / 索引 / 别名 / CLI 冒烟
└── references/
    ├── index.md                # 活跃学校索引（3448 所）
    ├── aliases.md              # 别名 / 简称索引（2827 条 + 歧义简称）
    ├── sync-log.md             # 上游同步台账
    ├── universities/           # 每所学校一个 Markdown 数据文件
    └── archived/
        ├── index.md            # 已归档学校索引（2705 所）
        └── universities/       # 2023 年前的归档数据
```

---

## 📦 安装方式

在 Claude Code、Codex、OpenClaw 等支持 Skill 的 Agent 里，直接说：

```text
帮我安装启用这个 skill：https://github.com/lbuibui/campus-life-query-skill
```

Agent 会自己克隆 skill 到对应目录，不用操心路径。

环境要求：Python 3（脚本只依赖标准库；在 3.12 上验证通过）。数据本体是纯 Markdown，不需要任何运行时。

当用户询问大学生活、宿舍、空调、校园网、断电断网、食堂、门禁等内容时，根据 `SKILL.md` 中的说明调用对应数据。

---

## 数据来源

大学生活质量数据整理自：

- 原项目：CollegesChat / university-information
- GitHub：https://github.com/CollegesChat/university-information
- 数据分支：https://github.com/CollegesChat/university-information/tree/generated
- 数据更新于：**2026-09-19**（generated 分支 `0abf14dfc897`）
- 活跃数据（3448 所）：2023-2026 年提交，428,050 条回答，另有 14,486 条「自由补充」
- 归档数据（2705 所）：2021-2022 年提交，396,800 条回答，另有 12,415 条「自由补充」，仅供参考
- 条目归并：上游有 1 个以校名变更说明命名的错放文件（仅 1 位问卷者 `A33177`，2026 年 02 月，25 条回答 + 1 条自由补充），已由 `tools/consolidate.py` 原地归并回「广东轻工职业技术大学」；全库条目总数不变（活跃 442,536 条 / 归档 409,215 条）
- 许可证：CC BY-NC-SA 4.0

数据规模说明：基础库覆盖中国大陆 31 个省级行政区；活跃索引另有 499 所、归档索引另有 219 所标为「其他」，多为海外院校或上游未能归类的学校。

**隐私处理**：上游生成数据在每所学校文件的来源列表中保留了问卷填写者留下的邮箱等标识，答案正文与「自由补充部分」里也常有学生留下的邮箱 / 手机号 / QQ / 微信 / Telegram（含少量 base64 多层编码的邮箱）。本项目两类都处理：

- 来源列表标识统一替换为「实名反馈者 N」（同一标识对应同一编号，新编号从现有最大值继续，增量同步不复用旧编号）；
- 答案正文里的联系方式替换为 `[邮箱已脱敏]` / `[手机号已脱敏]` / `[QQ已脱敏]` / `[微信已脱敏]` / `[Telegram已脱敏]` / `[社交账号已脱敏]`，能解码出个人信息的 base64 片段整段替换为 `[已脱敏的编码内容]`。

处理脚本为 `tools/redact.py`，幂等、可重复运行；`python3 tools/redact.py --check` 可随时确认是否还有漏网内容。

---

## 数据校验与测试

本地一键跑完所有检查（与 CI 同步）：

```bash
./tools/check_all.sh
```

单独运行：

```bash
python3 -m unittest discover -s tests   # 单元测试（判定器 + 解析）
python3 tools/query.py --selftest        # 极性判定回归样例（离线）
python3 tools/consolidate.py             # 归并上游错放条目（幂等，异常时退出码 1）
python3 tools/redact.py                  # 来源列表 + 正文个人信息脱敏（幂等）
python3 tools/build_aliases.py           # 重建别名索引
python3 tools/patch_index.py             # 施加索引本地修正（幂等）
python3 tools/verify.py                  # 完整性校验，期望 0 失败
python3 tools/verify.py --quiet          # 只输出警告、失败项与汇总
```

CI（`.github/workflows/ci.yml`）在 Python 3.10-3.13 上跑单元测试，并用 pytest
再收集一次；另有一个 `data-integrity` 作业确认脱敏/归并/索引修正幂等、`verify.py`
0 失败。只读校验模式：`consolidate.py --check`、`redact.py --check`（另有
`--dry-run` 打印待替换内容）、`build_aliases.py --check`（比对现存 `aliases.md`
是否与生成结果一致，不一致即退出码 1）、`patch_index.py --check`；`verify.py`
本身就是只读校验，可用 `--quiet` 精简输出、`--sample N` 抽样跑结构检查。

### 极性判定器（tools/polarity.py）

反向筛选与单校统计都依赖把每条回答判定为 `yes / no / mixed / unknown`。判定器
按 25 个问题各自维护语义规格（专属名词 + 通用说法 + 分化措辞），而不是套用一套
与问题无关的词表，因此：

- 「不断电」在断电问题里判否，且不会被当成「断电」的肯定；
- 「不是上床下桌」「是上下铺」判否，「上床下桌但不是一人一桌」判分化；
- 「不贵」在食堂问题里判肯定；
- 分校区 / 年份差异（「部分」「有的校区」）与转折措辞一律归入 `mixed`，
  无法断言时给 `unknown` 而不是硬猜。

判定口径会随每次查询结果一起打印（例如 `yes = 「有独立卫浴」`），计数只是回答
条数统计，不是官方事实。逐题回归样例见 `tests/test_polarity.py` 与
`python3 tools/query.py --selftest`。

`verify.py` 检查索引与文件双向一致、索引正文声明的院校/「其他」总数、别名不劫持真实校名、25 个问题区块且每区块至少 1 条回答、回答编号无悬空引用、来源列表已脱敏、H1 与索引一致。上游固有特征以**警告**列出、不计入失败——当前为 **0 失败 / 8 项警告**：空回答正文 2 处、以简称命名的占位条目 34 个、索引名为说明文字或超长 50 个、文件名超 150 字符 3 个。这些都是上游原始数据的性质，本项目如实保留、不做批量改写。

---

## 许可证

本项目遵循 **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International** 协议，即 **CC BY-NC-SA 4.0**。根目录的 `LICENSE` 为协议全文。

你可以：

- 复制、分享本项目
- 修改、二次创作
- 在非商业场景中使用

但你必须：

- 保留署名与来源说明
- 不得用于商业目的
- 基于本项目的改作也必须使用相同或兼容协议继续分享

详见：

- [`LICENSE`](./LICENSE)
- https://creativecommons.org/licenses/by-nc-sa/4.0/

---

## 免责声明

- 本项目不是官方招生信息，不代表任何学校或机构立场。
- 数据来自学生匿名回答，可能存在时间差、校区差异和主观体验差异。
- 查询结果仅供参考，不应作为唯一决策依据。
- 工具输出的「肯定 / 否定」为回答条数统计，不是官方事实。
