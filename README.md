# University Info Skill · 大学生活质量指北 + UNTI 人格测试

一个用于 HanaAgent / OpenHanako 的大学生活信息查询 Skill。

它把开源项目 [CollegesChat/university-information](https://github.com/CollegesChat/university-information) 的全国高校生活质量数据整理为可被 Agent 调用的本地知识库，并附带一个自包含的 **UNTI 大学生活人格测试** HTML 页面。

> 数据与测试均仅供参考、娱乐和信息辅助，不代表任何学校或官方机构立场。

---

## 功能

### 1. 大学生活质量查询

支持查询 3461 所高校的真实生活条件，包括但不限于：

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

### 2. UNTI 大学生活人格测试

`assets/UNTI-测试.html` 是一个完全自包含的单文件 HTML，双击即可打开。

包含：

- 高中版 / 大学版双入口
- 12 道趣味选择题
- 16 种大学生人格结果
- 人格角色图与文案
- 4 维度雷达图分析
- 维度落点小卡片
- 副人格倾向
- 上一题回退按钮
- 图片与字体内嵌，无外部依赖

### 3. 人格结果与大学查询联动

当用户提供 UNTI 测试结果后，Agent 可以根据人格类型调整查询重点。

例如：

- `DAD / 义父`：优先关注宿舍条件、洗衣机、外卖便利度
- `ZZZ / 失联者`：优先关注断电断网、门禁、查寝封寝、热水时间
- `YUMY / 老吃家`：优先关注食堂价格、外卖、超市、快递

---

## 目录结构

```text
university-info-skill/
├── SKILL.md                    # HanaAgent Skill 入口说明
├── README.md                   # 项目说明
├── LICENSE                     # 原项目 CC BY-NC-SA 4.0 完整协议文本
├── NOTICE.md                   # 数据来源与署名说明
├── assets/
│   └── UNTI-测试.html          # UNTI 人格测试页面
└── references/
    ├── index.md                # 学校索引
    └── universities/           # 每所学校一个 Markdown 数据文件
```

---

## 使用方式

### 在 HanaAgent / OpenHanako 中使用

将整个文件夹作为一个 Skill 安装或放入 HanaAgent 的 skills 目录。

Skill 的入口文件是：

```text
SKILL.md
```

当用户询问大学生活、宿舍、空调、校园网、断电断网、食堂、门禁、大学人格测试等内容时，Agent 会根据 `SKILL.md` 中的说明调用对应数据或交付测试页面。

### 单独使用 UNTI 测试

直接打开：

```text
assets/UNTI-测试.html
```

这是一个完全自包含的网页，不需要服务器、不需要网络。

---

## 数据来源

大学生活质量数据整理自：

- 原项目：CollegesChat / university-information
- GitHub：https://github.com/CollegesChat/university-information
- 数据分支：https://github.com/CollegesChat/university-information/tree/generated
- 许可证：CC BY-NC-SA 4.0

本仓库对其进行了适配整理，使其可以作为 HanaAgent / OpenHanako Skill 使用。

---

## 许可证

本项目沿用原始数据集的 **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International** 协议，即 **CC BY-NC-SA 4.0**。根目录的 `LICENSE` 使用原项目 generated 分支中的完整协议文本。

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
- UNTI 人格测试是娱乐向测试，不具备心理学、教育学或职业规划诊断效力。

---

## 致谢

感谢 [CollegesChat/university-information](https://github.com/CollegesChat/university-information) 项目的维护者和所有提供大学生活信息的同学们。

也感谢每一个愿意把真实校园体验留下来的人。那些细碎的回答拼在一起，就是一所学校活着的样子。
