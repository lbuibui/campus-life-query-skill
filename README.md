# Campus Life Query Skill · 大学生活质量指北

全国大学生活质量数据库 Skill，覆盖 6153 所高校（含 3448 所活跃 + 2705 所历史归档）的 25 个生活维度。
项目名：`campus-life-query-skill`

> 本项目基于 [University Info Skill](https://github.com/liliMozi/university-info-skill) 重构。

数据来源：[CollegesChat/university-information](https://github.com/CollegesChat/university-information)

> 最后更新：2026-09-19（数据）；2026-10-05（SQLite 索引架构重构）
>
> 数据仅供参考、娱乐和信息辅助，不代表任何学校或官方机构立场。

---

## 功能

### 1. 大学生活质量查询

支持查询 6153 所高校（3448 活跃 + 2705 归档）的真实生活条件，包括但不限于：

- 宿舍是否上床下桌、有没有空调、独立卫浴 / 澡堂距离
- 早自习、晚自习、晨跑 / 跑步打卡
- 寒暑假 / 小学期、外卖、交通、地铁
- 洗衣机、校园网、断电断网、食堂价格、热水、门禁、查寝等

数据来自多届学生匿名回答，同一学校可能存在不同校区、不同年份、不同体验之间的差异。

### 2. 结构化查询与反向筛选

`tools/query.py` 是唯一查询入口，后端为 `data/index.sqlite`（回答的极性判定在建库期
算好），毫秒级返回。支持单校查询、跨校对比、按省份浏览、数据来源查询，以及
「哪些学校不断电」这类按生活条件反向筛选；结果标出「分化 / 分校区差异」，并打印
判定口径，避免把字面 grep 命中当成结论。

```bash
python3 tools/query.py 北邮 --q 断电
python3 tools/query.py --compare 北邮 华科 --q 空调
python3 tools/query.py --reverse 独立卫浴 --polarity yes --min-yes 3
python3 tools/query.py --province 广东
```

### 3. 简称 / 别名检索

内置 2800+ 条可唯一检索的别名 / 简称 / 曾用名（「北邮」「华科」「人大」「央财」），
覆盖 2300+ 所学校。真正指向多所学校的简称（地大、华师、华农、中国地质大学、
中国石油大学）不猜，命中时列出候选并以退出码 2 结束，要求用户确认。

---

## 架构

```text
campus-life-query-skill/
├── SKILL.md                    # Skill 入口定义
├── README.md                   # 项目说明
├── LICENSE                     # CC BY-NC-SA 4.0 协议全文
├── NOTICE.md                   # 数据来源、署名与改动说明
├── tools/
│   ├── query.py                # 唯一查询入口（SQLite 后端 CLI）
│   ├── polarity.py             # 25 个问题各自的极性判定规格（纯标准库）
│   ├── build_db.py             # 从 data/ 构建查询索引（确定性构建）
│   ├── alias_seed.py           # 简称 / 别名种子表与派生规则
│   ├── verify.py               # 数据库完整性校验
│   └── check_all.sh            # 一键跑完全部检查（与 CI 同步）
├── tests/                      # 单元测试（unittest，兼容 pytest）
└── data/
    ├── index.sqlite            # 查询索引（学校 / 25 问 / 回答 / 来源 / 别名）
    ├── universities/           # 上游原始镜像：活跃库每校一个 Markdown
    ├── nav.txt                 # 上游导航（校名 → 省份 → 文件）
    └── archived/
        ├── universities/       # 上游原始镜像：归档库（2023 年前）
        └── nav.txt
```

数据真源是 `data/` 下的上游 markdown 原样镜像；`data/index.sqlite` 由
`tools/build_db.py` 从镜像构建，回答的极性分类（yes / no / mixed / unknown）
在构建期一次性算好落库，查询期零分类开销。构建是确定性的：所有表按固定顺序
插入、不写入任何墙钟时间，重复构建产生字节一致的数据库；
`build_db.py --check` 重建到临时文件并比对内容摘要（与 sqlite 版本无关的逻辑
指纹），防止索引与镜像漂移。

---

## 📦 安装方式

在 Claude Code、Codex、OpenClaw 等支持 Skill 的 Agent 里，直接说：

```text
帮我安装启用这个 skill：https://github.com/lbuibui/campus-life-query-skill
```

Agent 会自己克隆 skill 到对应目录，不用操心路径。

环境要求：Python 3（脚本只依赖标准库，在 3.10-3.13 上验证通过）。查询索引已随仓库
提交，克隆即可查询；只有同步上游数据后才需要重建索引。

---

## 数据来源

大学生活质量数据整理自：

- 原项目：CollegesChat / university-information
- GitHub：https://github.com/CollegesChat/university-information
- 数据分支：https://github.com/CollegesChat/university-information/tree/generated
- 数据更新于：**2026-09-19**（generated 分支 `0abf14dfc897`）
- 活跃数据（3448 所）：2023-2026 年提交，442,536 条回答（含 14,486 条「自由补充」）
- 归档数据（2705 所）：2021-2022 年提交，409,215 条回答（含 12,415 条「自由补充」），仅供参考
- 许可证：CC BY-NC-SA 4.0

数据按上游 generated 分支原样镜像到 `data/`（含上游自身的错放条目与数据瑕疵）；
唯一的建库期归并是 1 个以校名变更说明命名的错放文件（`A33177`，25 条回答 +
1 条自由补充），其回答在查询索引中归入「广东轻工职业技术大学」，数据文件本身
保持上游原样。

**隐私说明**：`data/` 是上游数据的原样镜像，未做脱敏改写——上游生成数据在来源
列表与答案正文中保留了问卷填写者自愿留下的联系方式，此处与上游保持一致，以便
溯源与逐字节对比。如需分发脱敏版本，请在下游自行处理。

---

## 数据校验与测试

本地一键跑完所有检查（与 CI 同步）：

```bash
./tools/check_all.sh
```

单独运行：

```bash
python3 -m unittest discover -s tests   # 单元测试（解析 / 判定器 / 查询 / 构建）
python3 tools/query.py --selftest        # 极性判定回归样例（离线）
python3 tools/build_db.py                # 从 data/ 重建 data/index.sqlite
python3 tools/build_db.py --check        # 重建并比对内容摘要（校验索引未漂移）
python3 tools/verify.py                  # 数据库完整性校验，期望 0 失败
python3 tools/verify.py --quiet          # 只输出警告、失败项与汇总
```

CI（`.github/workflows/ci.yml`）在 Python 3.10-3.13 上跑单元测试，并用 pytest
再收集一次；另有 `data-integrity` 作业确认 `build_db.py --check` 摘要一致、
`verify.py` 0 失败。

`verify.py` 检查：外键与取值域自洽、schools 行与 nav / 文件系统逐一对应、内容
摘要未漂移、别名不劫持真实校名全称、每所学校 25 个问题区块都有回答。上游固有
特征以**警告**列出、不计入失败——当前为 **0 失败 / 3 项警告**：以说明文字或简称
作校名的条目 76 个、文件名超 150 字符 3 个、空回答正文 2 处。这些都是上游原始数据
的性质，本项目如实保留、不做批量改写。

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
