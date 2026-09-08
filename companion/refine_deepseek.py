#!/usr/bin/env python3
"""DeepSeek 整理层：把「零碎口语转写」理顺成可发送的工作信息。

aipassport 核心差异化模块。接在本地 ASR 定稿之后、注入输入框之前：
    原始口语文本 -> DeepSeek V4-Flash -> 通顺/结构化工作稿

设计要点：
- 走 DeepSeek OpenAI 兼容接口（https://api.deepseek.com/chat/completions），
  model=deepseek-v4-flash（你已配好的 key，便宜）。
- 用「预设 preset」控制对象/结构/语气/长度，preset 定义在 PRESETS 里，
  配置里 refine_preset 选一个即可。
- 网络/密钥失败时不崩主链路：raise 让调用方决定（relay 里回退为注入原文，
  保证「最差也能用」）。
- 纯函数式 refine(raw_text, cfg) ，便于单测与无硬件验证。

调用示例：
    from refine_deepseek import refine
    polished = refine("呃那个啥明天的会能不能改到下午因为上午我有事", cfg)
"""
import os

import requests

# ---- 整理预设 ----
# 每个 preset: (system 角色说明, 附加约束)。relay 配置 refine_preset 选其一。
PRESETS = {
    # 对同事/工作群发的工作消息：简洁、直接、去口语
    "work_wechat": (
        "你是一个把零碎口语整理成专业工作消息的助手。"
        "用户会用语音口述一段零碎、口语化、可能语序混乱的工作内容，"
        "请整理成一段可以直接发到工作群/同事的消息：",
        "要求：1) 去掉\"呃、那个、就是、然后、啥\"等口头禅和重复；"
        "2) 补全主语和必要的上下文，让没听语音的人也能看懂；"
        "3) 用简洁的工作书面语，不堆砌客套；"
        "4) 保留所有事实（时间、人物、事项、数字）；"
        "5) 默认一段，重点用项目符号分条，不超过 5 条；"
        "6) 不添加你推测的、用户没说的内容。"
        "7) 输入常是语音转写：无标点、人称乱(他/她/你混用)、长句绕。"
        "你必须重断句、理顺主语指代与先后逻辑、该拆句就拆句，"
        "输出通顺完整的中文段落——只删几个字不算整理，不得照抄原句顺序。",
    ),
    # 对老板/客户的汇报：更正式、结论先行
    "report_boss": (
        "你是一个帮用户把口头想法整理成对老板/客户的汇报的助手。",
        "要求：1) 结论先行（先说结果/诉求，再补背景）；"
        "2) 用正式但不过度客套的书面语；"
        "3) 事实清晰、可量化；4) 如需决策，明确给出建议选项；"
        "5) 不写用户没说的事。",
    ),
    # 会议纪要/待办：结构化提取
    "meeting_notes": (
        "你是一个会议纪要助手，把用户口述整理成结构化纪要。",
        "要求：输出分三部分——\n"
        "【结论/决议】\n【待办事项】（每条含 负责人? + 截止? + 事项）\n"
        "【背景/讨论】。没有的信息写「待确认」。",
    ),
    # 仅做轻度润色，尽量保留原话风格
    "light_polish": (
        "你只做极轻度润色：修正明显语病、去掉重复口头禅，"
        "但尽可能保留用户原本的说话顺序和风格，不要重写结构。",
        "要求：仅输出润色后的正文，不要解释，不要分点。",
    ),
    # 对 AI/vibe coding 助手的任务指令：把口语想法变成可直接执行的指令
    # (2026-09-08 需求: 场景三「对 agent」—— 用户口述要做的事 → 整理成
    # 发给 vibe coding / vibe working 等 AI agent 的任务说明)
    "agent_prompt": (
        "你是一个把用户口语想法整理成「给 AI 助手的清晰任务指令」的助手。"
        "用户会用语音零碎口述一个想交给 AI 做的事（写代码、改文档、"
        "整理数据、执行流程等），请整理成 AI 能直接理解和执行的指令：",
        "要求：1) 去掉口头禅与重复，理顺语序；"
        "2) 明确任务目标（要 AI 做什么、产出什么）；"
        "3) 保留关键约束（对象/范围/偏好/格式要求/截止等），补全省略的主语；"
        "4) 分条列出核心要求，可直接逐条执行，不超过 6 条；"
        "5) 用对 AI 说话的口吻（祈使句为主），不要写成对同事的客套消息；"
        "6) 不添加用户没说的内容；不确定的细节标注「待确认」；"
        "7) 语音转写常无标点、人称乱，必须重断句、理顺逻辑再输出。",
    ),
    # v0.2.3 语音输入场景: 录音即文字 —— 单段口语 → 通顺书面文字。
    # 不做工作消息/任务指令格式转换，只把话"说顺说清"，保留全部信息点
    # (随手记/长段口述/写作草稿)。relay 在此场景单段定稿后自动整理。
    "voice_input": (
        "你是语音输入的文字整理助手。用户把想写下来的话用语音说了出来，"
        "请整理成通顺、清晰、有条理的书面文字：",
        "要求：1) 修正语病、去口头禅与重复（呃/那个/就是/然后/啥）；"
        "2) 理顺语序与逻辑，该断句断句、该分段分段；"
        "3) 保留全部信息点：数字、时间、人名、细节一字不漏；"
        "4) 忠实原意，不要改写用户想表达的内容，不要添加推测内容，"
        "不要转换成工作汇报或任务指令格式——它就是一段被整理顺了的文字；"
        "5) 直接输出整理后的文字，不要解释、不要加引号或前缀。",
    ),
}


def _build_messages(raw_text, preset, extra_instruction=None):
    persona, constraints = PRESETS.get(preset, PRESETS["work_wechat"])
    sys_text = persona + "\n" + constraints
    if extra_instruction:
        sys_text += "\n" + extra_instruction
    # 多段输入(2026-09-08): relay 把 1-3 段转写用分段标记拼接后传入,
    # 由模型综合梳理(去重/理顺跨段逻辑/合并成完整成稿)。
    is_multi = "\n◆第" in raw_text and "段◆" in raw_text
    # 实测(2026-09-07): DeepSeek V4-Flash 对 system 角色指令遵从差——长
    # system + 弱 user 时模型直接复读 user 原文(整理任务完全失效); 把完整
    # 指令并入 user 消息后模型正常改写(口语→结构化工作稿)。故不再用 system。
    if is_multi:
        user_content = (
            sys_text +
            "\n\n以下是用户分多次语音录入的转写片段（每段可能不完整、"
            "内容有重叠或跳跃）。请把它们【综合】成一段连贯完整的内容："
            "1) 合并相同主题、删除跨段重复；"
            "2) 按逻辑顺序重排（时间/因果/主次）；"
            "3) 跨段补全指代，让整段通顺；"
            "4) 输出最终成稿本身，不要复述各段原文、不要解释、不要加前缀；"
            "整理稿控制在 200 字以内。\n\n" +
            raw_text)
    else:
        # 单段输入: 通用工作整理尾巴; voice_input 场景(语音输入=录音即文字)
        # 语义不同 —— 要的是通顺书面文字而非工作消息, 不设 80 字上限。
        if preset == "voice_input":
            _tail = ("\n\n以下是语音转写的口语原文。请按上面的要求把它整理成"
                     "通顺清晰的书面文字；直接输出整理结果本身，不要复述原文、"
                     "不要解释、不要加引号或前缀；保留全部信息点，不设字数上限。\n\n")
        else:
            _tail = ("\n\n以下是语音转写的口语原文。请实际整理它：删除口头禅/重复、"
                     "理顺语序、补全上下文，输出可直接发送的工作消息。"
                     "直接输出整理稿本身，不要复述原文、不要解释、不要加引号或前缀；"
                     "除非信息必须更详细，否则整理稿控制在 80 字以内。\n\n")
        user_content = sys_text + _tail + raw_text
    return [{"role": "user", "content": user_content}]


# 助理话术特征: 输入短/无内容时 DeepSeek 回复"好的，请发送您需要整理的
# 语音转写内容"这类话术(非整理稿), 命中即拦截(见 refine)。
# 2026-09-07 实机补: "好的，以下是整理后的工作消息：xxx" 也是话术变体
# (模型把"没听清/无实质内容"当"请求整理"回复), 一并拦截。
_ASSISTANT_PATTERNS = (
    "请提供", "请发送", "需要整理的语音", "语音转写内容", "语音转写原文",
    "收到您的指令", "收到您的消息", "按您的要求", "为您整理", "好的，请",
    "您好，请", "请把您需要", "请将您需要",
    "好的，以下是", "以下是整理后的", "整理后的工作消息", "为您整理如下",
    "整理如下", "请参考以下", "可以这样",
)


def _is_assistant_patter(text: str) -> bool:
    if not text or len(text) > 120:
        return False
    return any(p in text for p in _ASSISTANT_PATTERNS)


def refine(raw_text, cfg=None, extra_instruction=None):
    """把原始口语文本整理成工作稿。失败抛异常（调用方回退原文）。

    cfg: load_config() 返回的字典。refine_provider 选择后端:
        "deepseek"(默认): deepseek_api_key/base_url/model/temperature
        "glm": glm_api_key(ZHIPU_API_KEY 兜底)/glm_model(默认 glm-4.7-flash)
        两后端共用 refine_preset/refine_timeout/refine_max_tokens。
    """
    if cfg is None:
        from asr_local_whisper import load_config
        cfg = load_config()

    raw_text = (raw_text or "").strip()
    if not raw_text:
        return raw_text
    # 过短输入(≤5字, 无实质内容)直接返回, 不调 API —— 否则模型会把
    # 它当成"用户在测试助手"而回复"好的，请发送您需要整理的语音转写内容"
    # 这类助理话术(实测 2026-09-07 真机短转写触发, 话术被当整理稿注入)。
    if len(raw_text) <= 5:
        return raw_text

    preset = cfg.get("refine_preset", "work_wechat")
    provider = (cfg.get("refine_provider") or "deepseek").strip().lower()
    if provider == "glm":
        base_url = (cfg.get("glm_base_url")
                    or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        api_key = (cfg.get("glm_api_key")
                   or os.environ.get("GLM_API_KEY")
                   or os.environ.get("ZHIPU_API_KEY", ""))
        model = cfg.get("glm_model") or "glm-4.7-flash"
        temperature = float(cfg.get("glm_temperature", 0.3))
        if not api_key:
            raise RuntimeError(
                "缺少智谱 GLM API Key：请在 config.local.json 设 glm_api_key，"
                "或导出环境变量 GLM_API_KEY / ZHIPU_API_KEY")
    else:   # deepseek(默认)
        base_url = (cfg.get("deepseek_base_url")
                    or "https://api.deepseek.com").rstrip("/")
        api_key = (cfg.get("deepseek_api_key")
                   or os.environ.get("DEEPSEEK_API_KEY", ""))
        model = cfg.get("deepseek_model") or "deepseek-v4-flash"
        temperature = float(cfg.get("deepseek_temperature", 0.3))
        if not api_key:
            raise RuntimeError(
                "缺少 DeepSeek API Key：请在 config.local.json 设 "
                "deepseek_api_key，或导出环境变量 DEEPSEEK_API_KEY")

    # 实测(2026-09-07): 单请求超时收紧到可配(refine_timeout, 默认 6s),
    # 慢请求重试一次, 别让用户在输入框干等。
    timeout_s = float(cfg.get("refine_timeout", 6.0))

    messages = _build_messages(raw_text, preset, extra_instruction)

    def _call():
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": int(cfg.get("refine_max_tokens", 1024)),
            # 🔴 关键(2026-09-07 实锤): deepseek-v4-flash / glm-4.7 是推理
            # 模型, reasoning 会抢 max_tokens → content 恒空/复读/慢。
            # 整理是轻量任务, 显式关 thinking: reasoning=0、正文正常快速输出。
            "thinking": {"type": "disabled"},
        }
        return requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout_s,
        )

    last_err = None
    for attempt in range(2):   # 最多重试 1 次(慢请求/瞬时错误/复读/整理不足)
        try:
            resp = _call()
        except requests.RequestException as e:
            last_err = e
            continue            # 超时/网络抖动 → 重试
        if resp.status_code != 200:
            last_err = RuntimeError(
                f"HTTP {resp.status_code}: {resp.text[:200]}")
            continue
        data = resp.json()
        polished = (data["choices"][0]["message"]["content"] or "").strip()
        if attempt == 0 and len(raw_text) > 6:
            import difflib
            # 复读/几乎没改检测: 完全一致 或 与原文相似度 >0.85(只删几个字/
            # 加标点) 都视为「没有效整理」(实测超长混乱口语 DeepSeek 会偷懒
            # 输出近原文)。重试一次并附强指令逼它真正重写。
            sim = difflib.SequenceMatcher(None, raw_text, polished).ratio()
            if polished == raw_text.strip() or sim > 0.85:
                messages = _build_messages(
                    raw_text, preset,
                    extra_instruction=(
                        "（提示：上一次整理没有真正改写，被系统判为不合格。）"
                        "现在请务必对原文做实质性重写：重新断句、理顺主语和"
                        "时间线、删除一切口语冗余，输出通顺清晰的成稿，"
                        "不得与原文高度相似。"))
                continue
        # 助理话术拦截: 输入短/无实质内容时 DeepSeek 可能回复"好的，请提供/
        # 请发送您需要整理的语音转写内容"这类话术(不是整理稿)。识别即判无效:
        # 重试一次; 重试仍话术 → 返回空串(调用方回退原文, 不注入话术)。
        if _is_assistant_patter(polished):
            if attempt == 0:
                messages = _build_messages(
                    raw_text, preset,
                    extra_instruction=(
                        "（提示：上一次你回复了'请提供内容'之类的助理话术，"
                        "这是无效输出。）用户已给出语音转写内容，请直接整理它，"
                        "输出整理稿本身，不要任何客套或追问。"))
                continue
            return ""
        return polished or raw_text
    raise RuntimeError(f"整理服务重试仍失败: {last_err}")


# ---- CLI 自测 ----
if __name__ == "__main__":
    import sys
    sample = sys.argv[1] if len(sys.argv) > 1 else \
        "呃那个啥明天的周会能不能改到下午三点因为上午我要去见客户然后那个需求文档你帮我看下哈"
    out = refine(sample)
    print("原始:", sample)
    print("整理:", out)
