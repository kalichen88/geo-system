# -*- coding: utf-8 -*-
"""
GEO 客户看板生成器
读取归因结果 + 已发布内容登记表 + 历史快照，生成面向客户的静态看板 HTML。

用法：
  python dashboard/build.py --brand brands/maixiang.yaml

输入：
  output/<品牌>/monitor/attribution_result.json   监测引擎产出
  monitor/published_<品牌slug>.yaml               发布台账
  dashboard/history/<品牌slug>_history.json       历史月度快照（自动追加）

输出：
  dashboard/site/<品牌slug>/index.html            客户看板（可直接部署）
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from factory.generate import load_brand_config  # noqa: E402

PLATFORM_CN = {"doubao": "豆包", "kimi": "Kimi", "deepseek": "DeepSeek"}
TYPE_CN = {
    "recommend": "推荐类", "compare": "对比类", "review": "评价类",
    "scene": "场景类", "longtail": "长尾类", "unknown": "其他",
}


def load_published(path):
    """读取发布台账（容错：文件不存在返回空表）"""
    if not os.path.exists(path):
        return []
    return load_brand_config(path).get("published", [])


def load_history(history_path, brand_slug, current_summary):
    """读取/更新历史快照，返回按月列表"""
    history = []
    if os.path.exists(history_path):
        try:
            with open(history_path, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    month = datetime.now().strftime("%Y-%m")
    if not any(h.get("month") == month for h in history):
        history.append({
            "month": month,
            "mention_rate": current_summary["brand_mention_rate"],
            "citation_rate": current_summary["citation_rate"],
            "total_answers": current_summary["total_answers"],
        })
        history.sort(key=lambda x: x["month"])
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    return history


def trend_svg(history):
    """双折线趋势图（纯 SVG，无依赖）"""
    w, h, pad = 640, 200, 36
    if len(history) < 2:
        return '<p style="color:#999;font-size:13px;">下月监测后生成趋势曲线（需 ≥2 期数据）。</p>'
    months = [x["month"] for x in history]
    mention = [x["mention_rate"] for x in history]
    cite = [x["citation_rate"] for x in history]
    ymax = max(max(mention, cite) * 1.25, 10)

    def pts(vals):
        out = []
        for i, v in enumerate(vals):
            x = pad + i * (w - 2 * pad) / (len(vals) - 1)
            y = h - pad - v / ymax * (h - 2 * pad)
            out.append(f"{x:.1f},{y:.1f}")
        return " ".join(out)

    grid = ""
    for gv in range(0, int(ymax) + 1, max(1, int(ymax) // 4)):
        gy = h - pad - gv / ymax * (h - 2 * pad)
        grid += f'<line x1="{pad}" y1="{gy:.0f}" x2="{w - pad}" y2="{gy:.0f}" stroke="#eee"/><text x="{pad - 6}" y="{gy + 4:.0f}" font-size="10" fill="#999" text-anchor="end">{gv}%</text>'
    labels = "".join(
        f'<text x="{pad + i * (w - 2 * pad) / (len(months) - 1):.0f}" y="{h - 10}" font-size="10" fill="#666" text-anchor="middle">{m}</text>'
        for i, m in enumerate(months)
    )
    return f'''<svg viewBox="0 0 {w} {h}" style="width:100%;max-width:640px;">
{grid}
<polyline points="{pts(mention)}" fill="none" stroke="#0f6e56" stroke-width="2.5"/>
<polyline points="{pts(cite)}" fill="none" stroke="#d97706" stroke-width="2.5" stroke-dasharray="5,3"/>
{labels}
<rect x="{pad}" y="4" width="12" height="3" fill="#0f6e56"/><text x="{pad + 18}" y="9" font-size="11" fill="#444">品牌提及率</text>
<rect x="{pad + 110}" y="4" width="12" height="3" fill="#d97706"/><text x="{pad + 128}" y="9" font-size="11" fill="#444">内容引用率</text>
</svg>'''


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(brand_cfg, summary, records, published, history):
    brand = brand_cfg["name"]
    now = datetime.now()
    total_pub = len(published)
    cited_pub = sum(1 for p in published if summary.get("per_published", {}).get(p["id"], {}).get("cited_count", 0) > 0)

    # —— 平台卡片 ——
    plat_cards = ""
    for plat, cn in PLATFORM_CN.items():
        d = summary["by_platform"].get(plat, {"total": 0, "mentioned": 0, "hit": 0})
        rate = round(d["mentioned"] / d["total"] * 100) if d["total"] else 0
        color = "#0f6e56" if rate >= 60 else "#d97706" if rate >= 30 else "#b91c1c"
        plat_cards += f'''<div class="pcard">
<div class="pname">{cn}</div>
<div class="pnum" style="color:{color}">{rate}%</div>
<div class="plbl">{d["mentioned"]}/{d["total"]} 次回答提及品牌</div>
<div class="bar"><span style="width:{rate}%;background:{color}"></span></div>
</div>'''

    # —— 发布台账 ——
    pub_rows = ""
    for p in published:
        info = summary.get("per_published", {}).get(p["id"], {})
        cited = info.get("cited_count", 0)
        badge = f'<span class="ok">已被引用 ×{cited}</span>' if cited else '<span class="wait">待收录</span>'
        pub_rows += f'''<tr>
<td><b>{esc(p["id"])}</b></td><td>{PLATFORM_CN.get(p["platform"], esc(p["platform"]))}</td>
<td><a href="{esc(p["url"])}" target="_blank" rel="noopener">{esc(p["title"])}</a></td>
<td>{p.get("brand_mentions", "-")}</td><td>{badge}</td></tr>'''

    # —— 逐条回答 ——
    rec_rows = ""
    for r in records:
        m = '<span class="ok">提及</span>' if r["brand_mentioned"] else '<span class="no">未提及</span>'
        rec_rows += f'''<tr><td>{PLATFORM_CN.get(r["platform"], r["platform"])}</td>
<td>{TYPE_CN.get(r["question_type"], r["question_type"])}</td>
<td>{esc(r["question"])}</td><td>{m}</td><td>{r["urls_cited"]}</td>
<td>{esc("、".join(h["published_id"] for h in r["published_hits"])) if r["published_hits"] else "—"}</td></tr>'''

    # —— 本月行动建议 ——
    tips = []
    weakest = min(summary["by_platform"].items(), key=lambda kv: kv[1]["mentioned"] / max(kv[1]["total"], 1))
    if weakest[1]["mentioned"] == 0:
        tips.append(f"{PLATFORM_CN[weakest[0]]}平台本月 0 次提及：下周加大该平台发布量（+2 篇），并优先覆盖长尾提问。")
    if cited_pub == 0 and total_pub > 0:
        tips.append("已发布内容尚未被 AI 引用：新发布内容一般在 1-4 周内进入检索索引，保持节奏，下月复测。")
    if summary["brand_mention_rate"] < 50:
        tips.append("品牌提及率偏低：建议补充百科词条 + 官网 FAQ 结构化内容，提升 AI 的可信信源密度。")
    if not tips:
        tips.append("各项指标健康，保持当前发布节奏并每两周扩充 2-3 个长尾提问方向。")

    return f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GEO 服务月报 — {esc(brand)}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; max-width: 900px; margin: 0 auto; padding: 28px 20px; color: #1a1a1a; background: #fafbfa; }}
.header {{ background: linear-gradient(135deg, #0f6e56, #0a4a3a); color: #fff; border-radius: 14px; padding: 26px 28px; margin-bottom: 20px; }}
.header h1 {{ margin: 0 0 6px; font-size: 22px; }}
.header .sub {{ opacity: .85; font-size: 13px; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 18px 0; }}
.card {{ background: #fff; border-radius: 12px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
.card .num {{ font-size: 28px; font-weight: 700; color: #0f6e56; }}
.card .lbl {{ font-size: 12px; color: #777; margin-top: 4px; }}
h2 {{ font-size: 17px; margin: 30px 0 10px; border-left: 4px solid #0f6e56; padding-left: 10px; }}
.panel {{ background: #fff; border-radius: 12px; padding: 18px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }}
.plats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
.pcard {{ background: #f6f9f8; border-radius: 10px; padding: 14px; }}
.pname {{ font-size: 13px; color: #555; }}
.pnum {{ font-size: 26px; font-weight: 700; }}
.plbl {{ font-size: 11px; color: #888; margin: 2px 0 8px; }}
.bar {{ height: 6px; background: #e5e5e5; border-radius: 3px; overflow: hidden; }}
.bar span {{ display: block; height: 100%; border-radius: 3px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #eee; padding: 9px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f6f9f8; font-weight: 600; }}
a {{ color: #0f6e56; }}
.ok {{ display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 12px; background: #e1f5ee; color: #0f6e56; font-weight: 600; white-space: nowrap; }}
.no, .wait {{ display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 12px; background: #f3f4f6; color: #999; white-space: nowrap; }}
.tips li {{ margin: 8px 0; line-height: 1.6; }}
.footer {{ margin-top: 30px; color: #999; font-size: 12px; text-align: center; }}
@media (max-width: 640px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} .plats {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>

<div class="header">
<h1>GEO 生成式引擎优化 · 月度服务看板</h1>
<div class="sub">客户：{esc(brand)}（{esc(brand_cfg.get("category", ""))} · {esc(brand_cfg.get("region", ""))}） ｜ 报告期：{now.strftime("%Y 年 %m 月")} ｜ 生成时间：{now.strftime("%Y-%m-%d %H:%M")}</div>
</div>

<h2>核心指标</h2>
<div class="cards">
<div class="card"><div class="num">{summary["brand_mention_rate"]}%</div><div class="lbl">品牌提及率（三大 AI 平台）</div></div>
<div class="card"><div class="num">{summary["citation_rate"]}%</div><div class="lbl">已发布内容引用率</div></div>
<div class="card"><div class="num">{total_pub}</div><div class="lbl">累计发布内容（条）</div></div>
<div class="card"><div class="num">{cited_pub}/{total_pub}</div><div class="lbl">已被引用内容数</div></div>
</div>

<h2>各 AI 平台表现</h2>
<div class="panel"><div class="plats">{plat_cards}</div></div>

<h2>指标趋势（按月）</h2>
<div class="panel">{trend_svg(history)}</div>

<h2>发布台账与收录状态</h2>
<div class="panel">
<table>
<tr><th>编号</th><th>平台</th><th>标题（点击查看）</th><th>品牌露出次数</th><th>状态</th></tr>
{pub_rows}
</table>
</div>

<h2>逐条回答归因明细</h2>
<div class="panel">
<table>
<tr><th>平台</th><th>问题类型</th><th>测试提问</th><th>品牌提及</th><th>引用URL数</th><th>命中内容</th></tr>
{rec_rows}
</table>
</div>

<h2>下月行动建议</h2>
<div class="panel"><ul class="tips">{''.join(f'<li>{esc(t)}</li>' for t in tips)}</ul></div>

<div class="footer">本报告由 GEO 智能监测系统自动生成 · 监测范围：豆包 / Kimi / DeepSeek 联网回答 · {now.strftime("%Y-%m-%d")}</div>
</body>
</html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True, help="品牌配置文件路径")
    args = ap.parse_args()

    cfg = load_brand_config(args.brand)
    brand_cfg = cfg["brand"]
    slug = re.sub(r"\s+", "", brand_cfg["name"])

    result_path = os.path.join(BASE, "output", slug, "monitor", "attribution_result.json")
    with open(result_path, encoding="utf-8") as f:
        result = json.load(f)
    summary, records = result["summary"], result["records"]

    published = load_published(os.path.join(BASE, "monitor", f"published_{slug}.yaml"))
    history = load_history(
        os.path.join(BASE, "dashboard", "history", f"{slug}_history.json"), slug, summary
    )

    html = render(brand_cfg, summary, records, published, history)

    site_dir = os.path.join(BASE, "dashboard", "site", slug)
    os.makedirs(site_dir, exist_ok=True)
    out = os.path.join(site_dir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"看板已生成: {out}")
    print(f"历史快照期数: {len(history)}")


if __name__ == "__main__":
    main()
