#!/usr/bin/env python3
"""脱敏 references/ 中的个人信息（来源列表标识 + 答案正文）。

背景：上游 CollegesChat/university-information 的生成数据把问卷填写者留下的
邮箱等标识原样写进了两处——

  1. 每所学校文件头 `<details>` 来源列表的「标识」字段
     （活跃库 1,501 个文件、2,672 个邮箱；归档库 1,026 个文件、1,965 个）；
  2. 答案正文与「自由补充部分」，学生为了互相联系常直接留下
     邮箱 / 手机号 / QQ / 微信 / Telegram，甚至有 base64 多层编码的邮箱。

项目以 CC BY-NC-SA 4.0 公开发布，上述都属于不该随数据集二次分发的个人信息，
两类都要处理。

处理方式：
  - 来源列表：只动「标识」字段，`<li>` 的问卷编号与时间戳保持原样；每个不同的
    标识映射为稳定的「实名反馈者 N」，同一标识在全库得到同一编号；新编号从
    **现有最大编号 + 1** 继续，绝不与既有编号冲突（增量同步安全）。
  - 答案正文：按高置信模式替换邮箱 / 手机号 / QQ / 微信 / Telegram / 社交账号，
    以及「base64 解码后含上述信息」的混淆内容，统一替换为可读的占位符。
  - 幂等：占位符不再匹配任何模式，重复运行不会二次替换，也不会重复插入提示行。
  - 不改动问卷编号、时间戳、问题标题与其它正文。

用法：
    python3 tools/redact.py --check    # 只统计仍有多少待脱敏内容（有则退出码 1）
    python3 tools/redact.py --dry-run  # 打印将要替换的内容，不写入
    python3 tools/redact.py            # 执行脱敏
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = [
    ROOT / "references" / "universities",
    ROOT / "references" / "archived" / "universities",
]

# <li>A12345: 标识 (2025 年 06 月)</li>
LI_RE = re.compile(r"<li>(A\d+):\s*(.*?)\s*\(([^)]*)\)</li>")
ANON = "匿名"
REDACTED = "实名反馈者"
NOTE = "> 数据来源中的个人信息已匿名化处理（原始标识已替换为“实名反馈者 N”）。"

# 匹配任何像邮箱 / 手机号 / 社交账号的标识，用于 --check 兜底扫描
SENSITIVE_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|\b1[3-9]\d{9}\b"
    r"|\b\d{5,12}\b"
)

# 正文脱敏规则：(占位符, 正则)。顺序有意义：
#   - 邮箱先于手机号，避免邮箱局部数字被当手机号；
#   - 微信先于 QQ，避免「加我v：…」被 QQ 规则（加我+数字）抢走而错标；
#   - 各规则都要求足够明确的上下文，避免把「微信支付」「b站GitHub」这类
#     平台名当成个人账号（宁漏勿错杀正文）。
BODY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("[邮箱已脱敏]", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("[Telegram已脱敏]", re.compile(r"(?:https?://)?t\.me/[A-Za-z0-9_+/]+")),
    ("[手机号已脱敏]", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("[微信已脱敏]", re.compile(
        r"(?:微信号|微信|wechat|WeChat|VX|vx|加我\s*[vV])\s*[:：]?\s*"
        r"(?![Aa]lipay|支付|支付寶|公[众眾]|群|[Ss]chool|ecard|小程序|钱包)"
        r"(?:[A-Za-z][A-Za-z0-9_-]{4,19}|(?<!\d)\d{5,12}(?!\d))"
        r"|[vV]\s*[:：]\s*(?:[A-Za-z][A-Za-z0-9_-]{4,19}|(?<!\d)\d{5,12}(?!\d))"
    )),
    ("[QQ已脱敏]", re.compile(
        r"(?:QQ|qq|Qq|qQ|企鹅号?|扣扣|扣|加\s*[Qq]|加我[^\d\n]{0,10}?|[Qq])"
        r"\s*(?:号|群|交流群|咨询群|咨询|联系)?\s*[:：，,]?\s*[（(]?\s*\d{5,12}"
    )),
    ("[社交账号已脱敏]", re.compile(
        r"微博\s*(?:ID|id|号|账号)\s*(?:是)?\s*[:：]?\s*[\"“][^\"”\n]{2,24}[\"”]?"
    )),
    ("[社交账号已脱敏]", re.compile(r"(?:抖音|快手)\s*(?:号)?\s*[:：]?\s*\d{6,15}")),
    ("[社交账号已脱敏]", re.compile(
        r"(?:B站|b站|哔哩哔哩)\s*(?:(?:号|账号|ID|id)\s*[:：]?|[:：])\s*[A-Za-z][A-Za-z0-9_]{2,19}"
    )),
]
# base64 候选片段（足够长才可能是被编码的整段内容）
BASE64_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
PLACEHOLDER_B64 = "[已脱敏的编码内容]"


def split_head(text: str) -> tuple[str, str]:
    """拆出第一个 "## " 之前的头部与之后的主体。"""
    idx = text.find("\n## ")
    if idx == -1:
        return text, ""
    return text[:idx], text[idx:]


def collect_identifiers() -> dict[str, str]:
    """为新出现的非匿名标识分配编号。

    编号从现有「实名反馈者 N」的最大 N + 1 开始：绝不复用既有编号，因此增量
    同步（新增文件 / 上游覆盖回原始邮箱）不会让新标识与旧标识撞号。
    """
    seen: list[str] = []
    used: set[int] = set()
    num_re = re.compile(rf"{REDACTED}\s*(\d+)")
    for d in TARGET_DIRS:
        for path in sorted(d.glob("*.md")):
            head, _ = split_head(path.read_text(encoding="utf-8"))
            for _aid, ident, _date in LI_RE.findall(head):
                ident = ident.strip()
                if ANON in ident:
                    continue
                m = num_re.fullmatch(ident)
                if m:
                    used.add(int(m.group(1)))
                    continue
                if ident not in seen:
                    seen.append(ident)
    nxt = (max(used) + 1) if used else 1
    return {ident: f"{REDACTED} {nxt + i}" for i, ident in enumerate(seen)}


def redact_source_idents(head: str, mapping: dict[str, str]) -> tuple[str, int]:
    """只替换来源列表的「标识」字段，保留编号与时间戳。"""
    count = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal count
        aid, ident, date = m.group(1), m.group(2).strip(), m.group(3)
        if ANON in ident or ident.startswith(REDACTED):
            return m.group(0)
        repl = mapping.get(ident)
        if repl is None:
            return m.group(0)
        count += 1
        return f"<li>{aid}: {repl} ({date})</li>"

    return LI_RE.sub(sub, head), count


def _decode_chain(blob: str, depth: int = 3) -> list[str]:
    """对候选 base64 片段连续解码，返回各层解码结果（用于识别混淆内容）。"""
    layers: list[str] = []
    cur = blob.strip()
    for _ in range(depth):
        try:
            raw = base64.b64decode(cur, validate=True)
        except (binascii.Error, ValueError):
            break
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            break
        layers.append(decoded)
        cur = decoded.strip()
    return layers


def _contains_pii(text: str) -> bool:
    return any(rx.search(text) for _ph, rx in BODY_RULES) or bool(SENSITIVE_RE.search(text))


def _apply_text_rules(segment: str, hits: list[tuple[str, str]]) -> str:
    for placeholder, rx in BODY_RULES:
        def sub(m: re.Match[str], ph: str = placeholder) -> str:
            hits.append((ph, m.group(0)))
            return ph
        segment = rx.sub(sub, segment)
    return segment


def redact_body(body: str) -> tuple[str, list[tuple[str, str]]]:
    """替换答案正文里的个人信息，返回 (新正文, [(占位符, 命中原文)])。

    base64 候选片段先被单独切出来处理：能解码出个人信息的整段替换，其它候选
    原样保留且**不参与**文本规则匹配。否则文本规则会先把合法 base64 串里的
    字母数字改掉（例如 `VX…` 被当成微信号），导致真正的编码信息再也解不出来。
    """
    hits: list[tuple[str, str]] = []
    out: list[str] = []
    pos = 0
    for m in BASE64_RE.finditer(body):
        out.append(_apply_text_rules(body[pos:m.start()], hits))
        blob = m.group(0)
        if any(_contains_pii(layer) for layer in _decode_chain(blob)):
            hits.append((PLACEHOLDER_B64, blob))
            out.append(PLACEHOLDER_B64)
        else:
            out.append(blob)
        pos = m.end()
    out.append(_apply_text_rules(body[pos:], hits))
    return "".join(out), hits


def _iter_files():
    for d in TARGET_DIRS:
        yield from sorted(d.glob("*.md"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只统计，不写文件")
    ap.add_argument("--dry-run", action="store_true", help="打印替换内容，不写文件")
    args = ap.parse_args()

    mapping = collect_identifiers()
    print(f"扫描到 {len(mapping)} 个待处理的新标识（编号从现有最大值继续）")

    if args.check:
        files_with_idents = 0
        head_sensitive = 0
        body_hits = 0
        for path in _iter_files():
            head, body = split_head(path.read_text(encoding="utf-8"))
            for raw in re.findall(r"<li>(.*?)</li>", head):
                if ANON in raw or REDACTED in raw:
                    continue
                if SENSITIVE_RE.search(raw):
                    head_sensitive += 1
            idents = [i.strip() for _a, i, _d in LI_RE.findall(head)]
            if any(ANON not in i and not i.startswith(REDACTED) for i in idents):
                files_with_idents += 1
            body_hits += len(redact_body(body)[1])
        print(f"仍含非匿名来源标识的文件：{files_with_idents}")
        print(f"来源列表敏感模式兜底命中：{head_sensitive}")
        print(f"正文待脱敏命中：{body_hits}")
        return 1 if (files_with_idents or head_sensitive or body_hits) else 0

    if args.dry_run:
        shown = 0
        for path in _iter_files():
            head, body = split_head(path.read_text(encoding="utf-8"))
            new_head, n_id = redact_source_idents(head, mapping)
            new_body, hits = redact_body(body)
            if n_id == 0 and not hits:
                continue
            rel = path.relative_to(ROOT)
            print(f"\n{rel}: 来源标识 {n_id} 处，正文 {len(hits)} 处")
            for ph, text in hits[:5]:
                print(f"    {ph} <- {text[:80]!r}")
            shown += 1
            if shown >= 120:
                print("\n…（命中文件过多，仅显示前 120 个）")
                break
        print(f"\n共 {shown} 个文件需要处理（未写入）")
        return 0

    stats = {"files": 0, "idents": 0, "body": 0, "b64": 0}
    for path in _iter_files():
        text = path.read_text(encoding="utf-8")
        head, body = split_head(text)
        new_head, n_id = redact_source_idents(head, mapping)
        new_body, hits = redact_body(body)
        if n_id == 0 and not hits:
            continue
        if n_id and NOTE not in new_head:
            # 插到第一个空行之后（免责声明块之后），保持排版
            marker = "\n\n"
            at = new_head.find(marker)
            if at != -1:
                new_head = (new_head[: at + len(marker)] + NOTE + "\n\n"
                            + new_head[at + len(marker):])
            else:
                new_head = new_head.rstrip() + "\n\n" + NOTE + "\n\n"

        mode = stat.S_IMODE(path.stat().st_mode)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(new_head + new_body, encoding="utf-8")
        os.chmod(tmp, mode)  # 保持原文件权限，避免 0600 -> 0644
        tmp.replace(path)

        stats["files"] += 1
        stats["idents"] += n_id
        stats["body"] += len(hits)
        stats["b64"] += sum(1 for ph, _t in hits if ph == PLACEHOLDER_B64)

    print(
        f"已处理 {stats['files']} 个文件：来源标识 {stats['idents']} 处、"
        f"正文 {stats['body']} 处（其中编码内容 {stats['b64']} 处）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
