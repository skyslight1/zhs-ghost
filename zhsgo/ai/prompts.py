"""答题提示词模板。

措辞基本沿用原项目 —— 这套 prompt 是被实际跑通过的，重写时不应"优化"掉它
能生效的部分。改动只有两处：
  * 题目类型常量集中到 TYPE_*，不再靠 1/2/14 的裸数字散落各处；
  * 模板函数不再依赖 `self.extra`（隐式全局状态），改成显式传入上下文。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

TYPE_SINGLE = 1
TYPE_MULTIPLE = 2
TYPE_JUDGE = 14

TYPE_NAMES = {
    TYPE_SINGLE: "单选题",
    TYPE_MULTIPLE: "多选题",
    TYPE_JUDGE: "判断题",
}


@dataclass
class AnswerContext:
    course_name: str = "未知课程"
    theme: str = ""
    knowledge_point: str = ""

    def describe(self) -> str:
        parts = [f"课程《{self.course_name}》"]
        if self.theme:
            parts.append(f"主题：{self.theme}")
        if self.knowledge_point:
            parts.append(f"知识点：{self.knowledge_point}")
        return " / ".join(parts)


def materials_block(materials: Optional[Sequence[dict]]) -> str:
    if not materials:
        return ""
    blocks = []
    for m in materials:
        content = m.get("content") or ""
        if not content:
            continue
        blocks.append(f"```{m.get('name', '')}\n{content}\n```")
    if not blocks:
        return ""
    return "参考资料：\n" + "\n".join(blocks)


def base_template(ctx: AnswerContext, question: str, choices: List[dict],
                  materials: Optional[Sequence[dict]], answer_type: str) -> str:
    reason = "最合适的答案" if answer_type == TYPE_NAMES[TYPE_SINGLE] else "所有正确的答案"
    head = (f"假设你是一名学生，正在学习《{ctx.course_name}》。"
            f"需要严格按照考试要求完成一道题目，否则无法及格。\n")
    theme = f"现在，你学习到了{ctx.theme}。\n" if ctx.theme else ""
    point = f"本次考察知识点为{ctx.knowledge_point}。\n" if ctx.knowledge_point else ""

    requirement = f"""本题为{answer_type}，请从选项中选择{reason}，回答放到markdown代码块中，例如：

        ```answer
        [{{"id": 652308395, "content": "<p>仅涉及心、肺、肝、肾及脑相关疾病</p>"}}]
        ```
        答案必须为满足格式的json字符串(列表，单选也要是列表)，否则视为无效答案，不能得分。在这个markdown代码块（answer）外，你需要解释为什么你认为这个答案是正确的，并且标注出你选择这个答案的依据，这些依据必须有一定的权威性。（我提供给你的参考资料绝对权威可信）
        """
    body = f"现在，请听题：\n\n{question}\n\n"
    options = f"选项如下：```choices\n{json.dumps(choices, ensure_ascii=False, indent=4)}\n```\n"
    return materials_block(materials) + head + theme + point + requirement + body + options


def build_prompt(ctx: AnswerContext, question_type: int, question: str,
                 choices: List[dict], materials: Optional[Sequence[dict]] = None) -> str:
    name = TYPE_NAMES.get(question_type)
    if name is None:
        raise ValueError(f"不支持的题型: {question_type}")
    return base_template(ctx, question, choices, materials, name)


ANSWER_BLOCK = r"```answer\s*\n(.*?)\n```"
