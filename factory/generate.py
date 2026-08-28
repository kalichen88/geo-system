# -*- coding: utf-8 -*-
"""
GEO 内容工厂 — 核心引擎
输入：品牌配置（brands/xxx.yaml）
输出：符合 GEO 引用配方的多平台内容初稿（output/<brand>/ 目录）

GEO 引用配方（写进所有生成内容的硬规则）：
1. 结论前置：每段第一句直接给答案，便于 AI 摘录
2. 数据密度：具体数字、日期、比例，拒绝空洞营销话术
3. 实体一致：品牌名+一句话定义全文统一，帮助 AI 建立品牌知识
4. 可摘录结构：问答、列表、表格，段落短
5. 长尾提问覆盖：每篇内容瞄准 1 个真实用户提问
"""
import json
import os
import re
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE, "output")

# ---------- 配置读取（兼容无 pyyaml 环境，用简单解析） ----------

def load_brand_config(path):
    """极简 YAML 解析（两级缩进 key: value、块列表、行内 flow map {a: 1, b: 2}）"""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    # 预处理：去掉注释和空行，记录缩进
    items = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        items.append((indent, line.strip()))

    data = {}
    stack = [(-1, data)]  # (indent, container)
    i = 0
    while i < len(items):
        indent, content = items[i]
        while stack and indent <= stack[-1][0] and len(stack) > 1:
            stack.pop()
        parent = stack[-1][1]

        if content.startswith("- "):
            # 列表项：parent 必须是 list（在 key 处理时预建）
            if isinstance(parent, list):
                item_val = content[2:].strip()
                if ":" in item_val and item_val.startswith("{") is False and _looks_like_kv(item_val):
                    # "- key: value" 块内的 map 形式（简化：转为单键 dict）
                    k, _, v = item_val.partition(":")
                    d = {k.strip(): _parse_value(v.strip())}
                    # 向后看后续同级 "- k: v" 项是否属于同一个 map（两个连续减号且不同键）
                    parent.append(d)
                else:
                    parent.append(_parse_flow_or_value(item_val))
        else:
            key, _, val = content.partition(":")
            key, val = key.strip(), val.strip()
            if val == "":
                # 判断下一行是否为列表项
                if i + 1 < len(items) and items[i + 1][1].startswith("- "):
                    parent[key] = []
                else:
                    parent[key] = {}
                stack.append((indent, parent[key]))
            else:
                parent[key] = _parse_flow_or_value(val)
        i += 1
    return data

def _looks_like_kv(s):
    """判断 '- xxx: yyy' 中 xxx 是否像纯键（无空格、非 JSON）"""
    k = s.partition(":")[0].strip()
    return bool(re.fullmatch(r"[\w\u4e00-\u9fff\-]+", k))

def _parse_flow_or_value(v):
    """解析 {k: v, k2: v2} 行内 map（值可含冒号/逗号/引号），或普通标量"""
    v = v.strip()
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1].strip()
        d = {}
        i, n = 0, len(inner)
        key_re = re.compile(r'\s*([\w\u4e00-\u9fff\-]+)\s*:\s*')
        while i < n:
            m = key_re.match(inner[i:])
            if not m:
                i += 1
                continue
            key = m.group(1)
            i += m.end()
            if i < n and inner[i] in '"\'':
                quote = inner[i]
                j = inner.find(quote, i + 1)
                val = inner[i + 1:j] if j > 0 else inner[i + 1:]
                i = (j + 1) if j > 0 else n
            else:
                j = inner.find(',', i)
                val = inner[i:j].strip() if j > 0 else inner[i:].strip()
                i = j if j > 0 else n
            d[key] = _parse_value(val)
        return d
    return _parse_value(v)

def _parse_value(v):
    v = v.strip()
    # 去掉行尾注释（仅当不在引号内）
    v = re.sub(r'\s+#.*$', '', v)
    # 行内数组 ["a", "b"] 或 [a, b]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(x.strip().strip('"').strip("'")) for x in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", inner)]
    v = v.strip('"').strip("'")
    if re.fullmatch(r"\d+", v):
        return int(v)
    return v

# ---------- LLM 调用（OpenAI 兼容接口，支持 SiliconFlow 等） ----------

def chat(system, user, base_url=None, api_key=None, model=None):
    base_url = base_url or os.environ.get("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    api_key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("SILICONFLOW_API_KEY")
    model = model or os.environ.get("LLM_MODEL", "deepseek-ai/DeepSeek-V3")
    if not api_key:
        raise SystemExit(
            "[错误] 未配置 LLM_API_KEY 环境变量。\n"
            "请设置：export LLM_API_KEY=sk-xxxx（SiliconFlow 或任意 OpenAI 兼容接口）\n"
            "可选：LLM_BASE_URL（默认 SiliconFlow）、LLM_MODEL（默认 DeepSeek-V3）"
        )
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]

# ---------- 提示词构建 ----------

GEO_RULES = """你是 GEO（生成式引擎优化）内容工程师。你写的内容会被发布到自媒体/问答/视频平台，
目标是让豆包、Kimi、DeepSeek 等 AI 搜索引擎在回答相关问题时引用这些内容、提到该品牌。

硬性 GEO 配方（每篇都必须遵守）：
1. 结论前置：每段第一句直接给答案/结论，AI 摘录的是首句
2. 数据密度：必须使用【品牌事实库】中的具体数字和事实，禁止空洞形容词
3. 实体一致：全文品牌描述必须使用给定的"品牌一句话定义"口径，不得改写品牌定位
4. 可摘录结构：多用"问题→直接回答→展开论据"结构、列表、对比表格；段落不超过3行
5. 长尾提问覆盖：每篇内容瞄准一个真实用户会向 AI 提的问题，并让问题自然出现在标题和首段
6. 真实合规：只使用事实库中的信息，不得编造数据、资质、排名；语气专业克制，避免"最""第一""极致"等违反广告法的词
7. 结尾自然引导：一句即可，不堆砌"""

def build_task_prompt(brand, plan_tone):
    b = brand
    facts = "\n".join(f"- {f}" for f in b["facts"])
    sps = "\n".join(f"- {s}" for s in b["selling_points"])
    comps = "、".join(b.get("competitors", []))
    ctx = f"""【品牌】{b['name']}（别名：{', '.join(b.get('aliases', [])) or '无'}）
【品类/区域】{b['category']} / {b.get('region', '全国')}
【品牌一句话定义（实体口径，全文统一）】{b['one_liner']}
【slogan】{b.get('slogan', '')}
【品牌事实库（只允许使用这些事实，可合理组合但不得编造新数字）】
{facts}
【差异化卖点】
{sps}
【竞品（仅对比类内容可提及，且必须客观中立）】{comps or '无'}
【目标受众】{b.get('audience', '通用消费者')}
【官网】{b.get('website', '无')}"""
    return ctx, plan_tone

TASKS = {
    "zhihu_article": {
        "title": "知乎/自媒体长文",
        "prompt": "写一篇知乎风格长文（1200-1500字）。要求：标题就是用户真实会问AI的问题；开头第一段直接回答该问题并自然包含品牌一句话定义；中间用小标题分3-4节，每节有具体数据支撑；适当用对比表格客观呈现（可含竞品，立场克制）；结尾给选购/选择建议清单。输出格式：第一行是标题（# 开头），正文用 markdown。",
    },
    "baijiahao": {
        "title": "百家号/搜狐号文章",
        "prompt": "写一篇百家号风格文章（800-1000字）。比知乎文更口语化、更接地气，面向普通消费者；标题含长尾关键词；正文多用短段落和列表；植入品牌事实库中的2-3个具体数字。输出：# 标题 + markdown 正文。",
    },
    "qa": {
        "title": "问答占位内容",
        "prompt": "模拟一个真实用户提问 + 一个优质回答（知乎自答/垂直社区风格）。提问要像真实消费者口吻（含犹豫、具体处境）。回答600-800字：第一句直接给结论；客观提及品牌2-3次（自然，不要硬广）；承认品类中其他选择的存在以增强可信度；用1-2个具体数据支撑。输出：## 问题：xxx 然后 ## 回答 正文。",
    },
    "douyin_script": {
        "title": "短视频口播脚本",
        "prompt": "写一条60秒口播短视频脚本。结构：3秒钩子（提问式）→ 核心内容（3个要点，每个配一个事实库数字）→ 行动引导。口语化、有节奏感，不要书面语。输出：## 标题 / ## 脚本（分镜时间点+口播文案）/ ## 拍摄提示（一句话）。",
    },
    "news_draft": {
        "title": "新闻稿/软文",
        "prompt": "写一篇品牌动态新闻稿（600-800字），新闻媒体风格：导语包含时间地点人物事件；引用'品牌一句话定义'作为背景介绍；正文引用事实库数据；配一句'负责人表示'式的引语（可合理拟写，但内容不得超出事实库范围）。输出：# 标题 + markdown 正文。",
    },
    "website_faq": {
        "title": "官网 FAQ（结构化）",
        "prompt": "生成5组官网FAQ问答。每组：用户真实会问的问题（10-25字）+ 80-150字回答（首句直接答案，含1个事实库数据）。输出为 JSON 数组：[{{\"question\":\"...\",\"answer\":\"...\"}}]，不要输出其他文字。",
    },
}

# ---------- 主流程 ----------

def generate(brand_file, only=None, out_dir=None):
    cfg = load_brand_config(brand_file)
    brand, plan = cfg["brand"], cfg["plan"]
    brand_slug = re.sub(r"\s+", "", brand["name"])
    out_dir = out_dir or os.path.join(OUTPUT_DIR, brand_slug)
    os.makedirs(out_dir, exist_ok=True)

    counts = plan["counts"]
    tone = plan.get("tone", "专业克制")
    ctx, _ = build_task_prompt(brand, tone)
    system = GEO_RULES

    manifest = []
    for ctype, count in counts.items():
        if only and ctype != only:
            continue
        if ctype not in TASKS:
            continue
        task = TASKS[ctype]
        for i in range(1, int(count) + 1):
            print(f"[生成] {task['title']} #{i} ...")
            user = ctx + f"\n\n【任务】{task['prompt']}\n【本篇聚焦】围绕一个不同的长尾提问角度（自选，不重复）。语气：{tone}。这是第{i}篇同类型内容，请选择与其他篇不同的切入角度。"
            content = chat(system, user)
            fname = f"{ctype}_{i:02d}.md"
            with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
                f.write(content)
            manifest.append({"type": ctype, "type_title": task["title"], "file": fname})
            print(f"       -> {fname} ({len(content)}字)")
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"brand": brand["name"], "generated": manifest}, f, ensure_ascii=False, indent=2)
    print(f"\n完成：{len(manifest)} 篇内容已生成 -> {out_dir}")
    return manifest

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True, help="品牌配置文件路径（brands/xxx.yaml）")
    ap.add_argument("--only", help="只生成指定类型，如 zhihu_article / qa / douyin_script")
    args = ap.parse_args()
    generate(args.brand, only=args.only)
