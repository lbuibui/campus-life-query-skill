# Campus Life Query Skill · 大学生活质量指北

全国大学生活质量数据库 Skill，覆盖 6153 所高校（含 3448 所活跃 + 2705 所历史归档）的 25 个生活维度。
项目名：`campus-life-query-skill`

> 本项目基于 [University Info Skill](https://github.com/liliMozi/university-info-skill) 重构。

数据来源：[CollegesChat/university-information](https://github.com/CollegesChat/university-information)

> 最后更新：2026-09-19
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

`references/aliases.md` 收录 3157 条可唯一检索的别名、简称与曾用名（如「北邮」「华科」「人大」「央财」），解决用户用口语简称提问时按全称索引搜不到的问题。

### 3. 结构化查询与反向筛选

`tools/query.py` 按问题区块解析回答并做极性分类，支持单校查询、跨校对比和「哪些学校不断电」这类反向筛选，同时标出「分化 / 分校区差异」，避免用字面 grep 把「有人提到断电」误当成「这所学校断电」。

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
│   ├── query.py                # 结构化查询 / 反向筛选
│   ├── build_aliases.py        # 生成别名索引
│   ├── redact.py               # 来源个人信息脱敏
│   └── verify.py               # 数据完整性回归校验
└── references/
    ├── index.md                # 活跃学校索引（3448 所）
    ├── aliases.md              # 别名 / 简称索引（3157 条）
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

当用户询问大学生活、宿舍、空调、校园网、断电断网、食堂、门禁等内容时，根据 `SKILL.md` 中的说明调用对应数据。

---

## 数据来源

大学生活质量数据整理自：

- 原项目：CollegesChat / university-information
- GitHub：https://github.com/CollegesChat/university-information
- 数据分支：https://github.com/CollegesChat/university-information/tree/generated
- 数据更新于：**2026-09-19**（generated 分支 `0abf14dfc897`）
- 活跃数据（3448 所）：2023-2026 年提交，428,050 条回答（含 1 条从错放文件归并回来的 2026 年回答）
- 归档数据（2705 所）：2021-2022 年提交，396,800 条回答，仅供参考
- 许可证：CC BY-NC-SA 4.0

数据规模说明：基础库覆盖中国大陆 31 个省级行政区；索引中另有 499 所标为「其他」，多为海外院校或上游未能归类的学校。

**隐私处理**：上游生成数据在每所学校文件的来源列表中保留了问卷填写者留下的邮箱等标识。本项目已将其统一替换为「实名反馈者 N」（同一标识对应同一编号），处理脚本为 `tools/redact.py`，可重复运行。

---

## 数据校验

同步上游数据后运行：

```bash
python3 tools/consolidate.py   # 归并上游错放条目（幂等）
python3 tools/redact.py        # 来源列表脱敏（幂等）
python3 tools/build_aliases.py # 重建别名索引
python3 tools/patch_index.py   # 施加索引本地修正（幂等）
python3 tools/verify.py        # 完整性校验，期望 0 失败
```

`verify.py` 检查索引与文件双向一致、25 个问题区块完整、回答编号无悬空引用、来源列表已脱敏、索引无异常校名。

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
