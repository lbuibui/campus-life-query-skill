# Campus Life Query Skill · 大学生活质量指北

全国大学生活质量数据库 Skill，覆盖 3449 所高校的 25 个生活维度。
项目名：`campus-life-query-skill`

> 本项目基于 [University Info Skill](https://github.com/liliMozi/university-info-skill) 重构。

数据来源：[CollegesChat/university-information](https://github.com/CollegesChat/university-information)

> 数据仅供参考、娱乐和信息辅助，不代表任何学校或官方机构立场。

---

## 功能

### 1. 大学生活质量查询

支持查询 3449 所高校的真实生活条件，包括但不限于：

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

---

## 目录结构

```text
campus-life-query-skill/
├── SKILL.md                    # Skill 入口定义
├── README.md                   # 项目说明
├── LICENSE                     # CC BY-NC-SA 4.0 协议全文
├── NOTICE.md                   # 数据来源与署名说明
└── references/
    ├── index.md                # 学校索引
    └── universities/           # 每所学校一个 Markdown 数据文件
```

---

## 📦 安装方式

在 Claude Code、Codex、OpenClaw 等支持 Skill 的 Agent 里，直接说：

> 帮我安装这个 skill：https://github.com/lbuibui/campus-life-query-skill

Agent 会自己克隆 skill 到对应目录，不用操心路径。

当用户询问大学生活、宿舍、空调、校园网、断电断网、食堂、门禁等内容时，根据 `SKILL.md` 中的说明调用对应数据。

---

## 数据来源

大学生活质量数据整理自：

- 原项目：CollegesChat / university-information
- GitHub：https://github.com/CollegesChat/university-information
- 数据分支：https://github.com/CollegesChat/university-information/tree/generated
- 许可证：CC BY-NC-SA 4.0

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
