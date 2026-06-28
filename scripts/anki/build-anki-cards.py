#!/usr/bin/env python3
"""
从试题文件中正则匹配题目，输出可直接导入 Anki 的闪卡文件（.txt）。

用法：
    python scripts/anki/build-anki-cards.py

工作流程：
    1. 读取工作目录下的 args.txt，获取源文件路径
    2. 解析源文件中的题目（单选题/多选题）
    3. 每道题生成一张 Anki 闪卡：
       正面：题号. (题型) 题干<br>A. 选项1<br>B. 选项2<br>...
       背面：正确答案:X
    4. 输出为制表符分隔的 .txt 文件（Anki 可导入）

支持的文件格式：
    - 题目以 "n. (单选题)" 或 "n. (多选题)" 开头
    - 选项以 A.-E. 编号
    - 答案行包含 "正确答案:"
    - 章节标记（如 "第一章"）会自动跳过
"""

import re
import os
import sys
from pathlib import Path


def read_source_paths(args_path="args.txt"):
    """读取 args.txt，返回源文件路径列表。

    依次查找：
      1. 工作目录下的 args.txt
      2. cards/args.txt
    """
    # 尝试多个位置
    candidates = [Path(args_path), Path("cards") / args_path]
    args_file = None
    for c in candidates:
        if c.exists():
            args_file = c
            break

    if args_file is None:
        print(f"[错误] 未找到 {args_path}，已在以下位置查找：")
        for c in candidates:
            print(f"  - {c.resolve()}")
        print("请确保 args.txt 存在。")
        sys.exit(1)

    paths = []
    with open(args_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                paths.append(line)
    return paths


def find_question_blocks(text):
    """将文本按题目分割为独立的题目块。

    使用正则匹配每一题的起始行: n. (题型)
    也跳过 "一. 单选题" 等章节标题和 "作业详情" 等元信息。
    """
    # 匹配题号+题型
    q_header_re = re.compile(r"^(\d+)\.\s*\((单选题|多选题)\)", re.MULTILINE)
    matches = list(q_header_re.finditer(text))

    if not matches:
        return []

    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if block:
            blocks.append(block)
    return blocks


def parse_options_text(text):
    """从题目文本中提取所有选项，返回有序列表 [(letter, content), ...]。

    处理多种格式：
      - 标准: "A. 选项内容"
      - 换行: "A." 下一行 "内容"
      - 选项间有空行
    """
    lines = text.split("\n")
    options = []
    pending_letter = None  # 等待内容的选项字母
    in_options = False  # 是否已进入选项区域

    for line in lines:
        stripped = line.strip()

        # 跳过空行
        if not stripped:
            if pending_letter:
                # 如果正在等待内容，空行不影响
                continue
            continue

        # 碰到答案行 -> 停止
        if "正确答案:" in stripped or "我的答案:" in stripped:
            break

        # 跳过章节标记
        if re.match(r"^第[一二三四五六七八九十]+章$", stripped):
            break

        # 检查是否是选项行
        opt_match = re.match(r"^([A-E])\s*[.、]\s*(.*)", stripped)
        if opt_match:
            letter = opt_match.group(1)
            content = opt_match.group(2).strip()
            in_options = True

            if content:
                # 标准格式: "A. 内容"
                options.append((letter, content))
                pending_letter = None
            else:
                # "A." 单独一行，内容在下一行
                pending_letter = letter
        elif in_options and pending_letter:
            # 上一行是 "A."，这一行是内容
            options.append((pending_letter, stripped))
            pending_letter = None
        elif in_options and not re.match(r"^[A-E]\s*[.、]", stripped):
            # 可能是选项的延续内容（长选项跨行）
            if options:
                last_letter, last_content = options[-1]
                options[-1] = (last_letter, last_content + " " + stripped)

    return options


def extract_stem(text):
    """从题目文本中提取题干。

    text 的第一行是 "n. (题型) [题干]"，
    如果题干不在第一行，则第二行是题干。
    """
    lines = text.strip().split("\n")
    if not lines:
        return ""

    first = lines[0].strip()
    m = re.match(r"^\d+\.\s*\((?:单选题|多选题)\)\s*(.*)", first)

    if m:
        stem = m.group(1).strip()
        if stem:
            return stem
        # 题干在下一行（处理 "n. (题型)" 单独一行的情况）
        for line in lines[1:]:
            s = line.strip()
            if s and not re.match(r"^[A-E]\s*[.、]", s) and "正确答案:" not in s and "我的答案:" not in s:
                if not re.match(r"^第[一二三四五六七八九十]+章$", s):
                    return s
            if re.match(r"^[A-E]\s*[.、]", s):
                break
    return ""


def parse_answer_line(text):
    """从文本中提取正确答案。

    "正确答案:" 可能在单独的答案行中（与 "我的答案" 同行）。
    返回正确答案的字母组合，如 "BCE", "C"。
    """
    m = re.search(r"正确答案:([A-E]+)", text)
    return m.group(1) if m else ""


def build_anki_front(qnum, qtype, stem, options):
    """构建 Anki 正面字段。

    格式：题号. (题型) 题干<br>A. 选项<br>B. 选项<br>...
    所有换行替换为 <br>。
    """
    parts = [f"{qnum}. ({qtype}) {stem}"]
    for letter, content in options:
        parts.append(f"{letter}. {content}")
    return "<br>".join(parts)


def build_anki_back(correct):
    """构建 Anki 背面字段。

    只输出答案字母，不加前缀，避免每次输入多打字。
    """
    return correct


def process_source(source_path):
    """处理单个源文件，返回题目列表。

    每个题目为 dict: {front, back, num, type, stem, correct}
    """
    path = Path(source_path)
    if not path.exists():
        print(f"[跳过] 文件不存在: {source_path}")
        return []

    print(f"[处理] {source_path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = find_question_blocks(text)
    print(f"  -> 发现 {len(blocks)} 道题目")

    questions = []
    for i, block in enumerate(blocks):
        # 提取题型和题号
        header = block.split("\n")[0].strip()
        h_match = re.match(r"^(\d+)\.\s*\((单选题|多选题)\)", header)
        if not h_match:
            continue

        qnum = h_match.group(1)
        qtype = h_match.group(2)
        stem = extract_stem(block)
        options = parse_options_text(block)
        correct = parse_answer_line(block)

        if not correct:
            print(f"  [警告] 题目 {qnum} ({qtype}) 未找到正确答案")

        front = build_anki_front(qnum, qtype, stem, options)
        back = build_anki_back(correct)

        questions.append({
            "num": qnum,
            "type": qtype,
            "stem": stem,
            "options": options,
            "correct": correct,
            "front": front,
            "back": back,
        })

    return questions


def write_anki_file(questions, output_path):
    """将所有题目写入制表符分隔的 Anki 导入文件。

    Anki 支持的文本导入格式：每行一个卡片，字段之间用制表符分隔。
    默认两个字段：正面 | 背面
    """
    # 如果问题编号有重复（多选题和单选题各自从1开始），加前缀区分
    seen_nums = {}
    for q in questions:
        key = (q["num"], q["type"])
        seen_nums[key] = seen_nums.get(key, 0) + 1

    # 检查是否有重复题号
    has_dup = any(c > 1 for c in seen_nums.values())

    with open(output_path, "w", encoding="utf-8") as f:
        # 写 BOM 以便 Anki 正确识别 UTF-8
        f.write("\ufeff")

        for q in questions:
            # 如果题号重复，在编号前加 "多"/"单" 前缀
            if has_dup:
                prefix = "多" if q["type"] == "多选题" else "单"
                display_num = f"{prefix}{q['num']}"
                front = q["front"].replace(f"{q['num']}.", f"{display_num}.", 1)
            else:
                front = q["front"]

            # 制表符分隔：正面\t背面
            f.write(f"{front}\t{q['back']}\n")

    print(f"[输出] {output_path}")
    print(f"  -> 共 {len(questions)} 张闪卡")


def main():
    # 读取 args.txt 获取源文件路径
    source_paths = read_source_paths()

    if not source_paths:
        print("[错误] args.txt 中没有指定任何文件路径。")
        sys.exit(1)

    # 处理所有源文件
    all_questions = []
    for src in source_paths:
        questions = process_source(src)
        all_questions.extend(questions)

    if not all_questions:
        print("[提示] 未解析到任何题目。")
        sys.exit(0)

    # 输出到 Anki 文件，默认放在源文件同目录
    output_dir = Path(source_paths[0]).parent if source_paths else Path.cwd()
    output_path = output_dir / "anki-cards.txt"

    write_anki_file(all_questions, output_path)

    # 打印统计
    types = {}
    for q in all_questions:
        types[q["type"]] = types.get(q["type"], 0) + 1
    for t, c in sorted(types.items()):
        print(f"  {t}: {c} 张")
    print("\n导入 Anki 方法：")
    print("  1. Anki → 文件 → 导入")
    print("  2. 选择生成的 anki-cards.txt")
    print("  3. 字段分隔符选「制表符」，第一字段选「正面」，第二字段选「背面」")
    print("  4. 如遇到HTML换行不显示，在导入时勾选「允许HTML」")


if __name__ == "__main__":
    main()
