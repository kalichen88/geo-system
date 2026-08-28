# -*- coding: utf-8 -*-
"""
GEO 引用归因监测引擎
流程：读取提问库 -> 批量向豆包/Kimi/DeepSeek 提问（复用 geo-analyzer 采集通道）
      -> 解析每份回答：品牌提及/引用的 URL/是否命中已发布内容
      -> 生成占位成果 JSON + HTML 报告

用法：
  python monitor/monitor.py --brand brands/maixiang.yaml \
      --questions monitor/questions_maixiang.yaml \
      --published monitor/published_maixiang.yaml

依赖环境变量：
  REDFOX_API_KEY   红狐hub API Key（AI 平台采集通道）
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_SCRIPTS = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "geo-analyzer", "scripts")
sys.path.insert(0, SKILL_SCRIPTS)
sys.path.insert(0, BASE)

from factory.generate import load_brand_config  # 复用 YAML 解析

PLATFORMS = ["doubao", "kimi", "deepseek"]


# ---------- 第一步：批量采集 AI 回答（直接调用 geo-analyzer 的采集脚本） ----------

def collect_answers(questions, out_path):
    """调用红狐hub 采集脚本，向三大平台批量提问"""
    import subprocess
    script = os.path.join(SKILL_SCRIPTS, "geo_search.py")
    queries = [item["q"] for item in questions]
    env = os.environ.copy()
    if not env.get("REDFOX_API_KEY"):
        raise SystemExit("[错误] 未配置 REDFOX_API_KEY 环境变量（红狐hub 采集通道）")
    print(f"[采集] {len(queries)} 个问题 x {len(PLATFORMS)} 平台 = {len(queries)*len(PLATFORMS)} 次提问...")
    cmd = [
        sys.executable, script,
        "--queries", json.dumps(queries, ensure_ascii=False),
        "--platforms", ",".join(PLATFORMS),
        "--output", out_path,
    ]
    subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


# ---------- 第二步：归因分析 ----------

def normalize_url(url):
    """URL 归一化：去协议、去 www、去 query/fragment、小写域名"""
    try:
        p = urllib.parse.urlparse(url.strip())
        host = p.netloc.lower().replace("www.", "")
        path = p.path.rstrip("/")
        return host + path
    except Exception:
        return url.strip().lower()


def extract_urls(text):
    """从回答文本中提取所有 URL"""
    return re.findall(r"https?://[^\s\)\]\"'<>,，。；]+", text)


def analyze(search_results, questions_map, published):
    """核心归因：对每份回答判断品牌提及 + URL 引用 + 已发布内容命中"""
    pub_by_norm = {normalize_url(p["url"]): p for p in published}
    pub_domains = {urllib.parse.urlparse(p["url"]).netloc.replace("www.", "") for p in published}

    records = []
    for r in search_results.get("results", []):
        if r.get("status") != "completed":
            continue
        content = r.get("content", "")
        qitem = questions_map.get(r["question"], {})
        brand = r.get("_brand_name", "品牌")

        # 品牌提及检测（支持别名）
        mentioned = any(kw in content for kw in r.get("_brand_keywords", [brand]))

        # URL 引用
        urls = extract_urls(content)
        # sources 字段里的引用也算
        for s in r.get("sources", []):
            if s.get("url"):
                urls.append(s["url"])

        hits = []
        domain_hits = []
        for u in urls:
            nu = normalize_url(u)
            if nu in pub_by_norm:
                hits.append({"published_id": pub_by_norm[nu]["id"], "url": u, "match_type": "exact"})
            else:
                host = urllib.parse.urlparse(u).netloc.replace("www.", "")
                if host in pub_domains:
                    hits.append({"published_id": pub_by_norm[[normalize_url(p["url"]) for p in published if urllib.parse.urlparse(p["url"]).netloc.replace("www.", "") == host][0]]["id"], "url": u, "match_type": "domain"})

        records.append({
            "question": r["question"],
            "question_type": qitem.get("type", "unknown"),
            "platform": r["platform"],
            "brand_mentioned": mentioned,
            "urls_cited": len(urls),
            "published_hits": hits,
            "hit_count": len(hits),
            "all_domains": sorted({urllib.parse.urlparse(u).netloc.replace("www.", "") for u in urls}),
        })
    return records


def summarize(records, published):
    """汇总指标"""
    total = len(records) or 1
    mentioned = sum(1 for r in records if r["brand_mentioned"])
    hit_records = [r for r in records if r["hit_count"] > 0]

    per_published = {p["id"]: {"platform": p["platform"], "title": p["title"], "cited_count": 0, "questions": []} for p in published}
    for r in records:
        for h in r["published_hits"]:
            pid = h["published_id"]
            if pid in per_published:
                per_published[pid]["cited_count"] += 1
                per_published[pid]["questions"].append(f"{r['platform']}/{r['question'][:15]}")

    by_platform = {}
    for plat in PLATFORMS:
        rs = [r for r in records if r["platform"] == plat]
        by_platform[plat] = {
            "total": len(rs),
            "mentioned": sum(1 for r in rs if r["brand_mentioned"]),
            "hit": sum(1 for r in rs if r["hit_count"] > 0),
        }

    return {
        "total_answers": len(records),
        "brand_mention_rate": round(mentioned / total * 100, 1),
        "answers_citing_published": len(hit_records),
        "citation_rate": round(len(hit_records) / total * 100, 1),
        "per_published": per_published,
        "by_platform": by_platform,
    }


# ---------- 第三步：生成 HTML 报告 ----------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>GEO 占位成果报告 — {brand}</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; max-width: 860px; margin: 0 auto; padding: 24px; color: #1a1a1a; }}
h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; border-left: 4px solid #0f6e56; padding-left: 10px; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }}
.card {{ background: #f5f7f6; border-radius: 10px; padding: 14px; }}
.card .num {{ font-size: 26px; font-weight: 600; color: #0f6e56; }}
.card .lbl {{ font-size: 12px; color: #666; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 10px 0; }}
th, td {{ border-bottom: 1px solid #e5e5e5; padding: 8px 10px; text-align: left; }}
th {{ background: #f5f7f6; }}
.hit {{ color: #0f6e56; font-weight: 600; }}
.miss {{ color: #999; }}
.meta {{ color: #888; font-size: 12px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #e1f5ee; color: #0f6e56; }}
</style>
</head>
<body>
<h1>GEO 占位成果报告 — {brand}</h1>
<p class="meta">生成时间：{generated_at} ｜ 监测平台：豆包 / Kimi / DeepSeek ｜ 提问数：{qcount}</p>

<h2>核心指标</h2>
<div class="cards">
<div class="card"><div class="num">{mention_rate}%</div><div class="lbl">品牌提及率</div></div>
<div class="card"><div class="num">{cite_rate}%</div><div class="lbl">已发布内容引用率</div></div>
<div class="card"><div class="num">{cite_answers}</div><div class="lbl">命中我们内容的回答数</div></div>
<div class="card"><div class="num">{total}</div><div class="lbl">采集回答总数</div></div>
</div>

<h2>已发布内容被引用明细</h2>
<table>
<tr><th>内容</th><th>平台</th><th>被引用次数</th><th>出现在哪些回答</th></tr>
{published_rows}
</table>

<h2>逐条回答归因</h2>
<table>
<tr><th>平台</th><th>类型</th><th>问题</th><th>品牌提及</th><th>引用URL数</th><th>命中已发布内容</th></tr>
{detail_rows}
</table>

<h2>AI 回答引用的域名分布（TOP10）</h2>
<table>
<tr><th>域名</th><th>出现次数</th></tr>
{domain_rows}
</table>

<p class="meta">说明：exact = 回答直接引用了我们发布的 URL；domain = 引用了同一域名下的内容。品牌提及但不命中我们内容 = 竞品内容/第三方信源占位，需加大发布量。</p>
</body>
</html>"""


def render_html(summary, records, brand_name, qcount):
    pub_rows = ""
    for pid, info in summary["per_published"].items():
        cited = info["cited_count"]
        cls = "hit" if cited else "miss"
        qs = "、".join(info["questions"][:4]) or "—"
        pub_rows += f"<tr><td>{info['title'][:30]}</td><td>{info['platform']}</td><td class='{cls}'>{cited}</td><td>{qs}</td></tr>"

    detail_rows = ""
    for r in records:
        hit = "、".join(h["published_id"] for h in r["published_hits"]) or "—"
        badge = "<span class='badge'>提及</span>" if r["brand_mentioned"] else "<span class='miss'>未提及</span>"
        detail_rows += f"<tr><td>{r['platform']}</td><td>{r['question_type']}</td><td>{r['question'][:22]}</td><td>{badge}</td><td>{r['urls_cited']}</td><td class='{ 'hit' if r['hit_count'] else 'miss'}'>{hit}</td></tr>"

    domain_count = {}
    for r in records:
        for d in r["all_domains"]:
            domain_count[d] = domain_count.get(d, 0) + 1
    top_domains = sorted(domain_count.items(), key=lambda x: -x[1])[:10]
    domain_rows = "".join(f"<tr><td>{d}</td><td>{c}</td></tr>" for d, c in top_domains)

    from datetime import datetime
    return HTML_TEMPLATE.format(
        brand=brand_name,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        qcount=qcount,
        mention_rate=summary["brand_mention_rate"],
        cite_rate=summary["citation_rate"],
        cite_answers=summary["answers_citing_published"],
        total=summary["total_answers"],
        published_rows=pub_rows,
        detail_rows=detail_rows,
        domain_rows=domain_rows,
    )


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--questions", required=True)
    ap.add_argument("--published", required=True)
    ap.add_argument("--skip-collect", action="store_true", help="跳过采集，直接分析已有的 search_results.json")
    ap.add_argument("--results-file", help="已有的采集结果文件路径（配合 --skip-collect）")
    args = ap.parse_args()

    brand_cfg = load_brand_config(args.brand)["brand"]
    questions_data = load_brand_config(args.questions)["questions"]
    published = load_brand_config(args.published)["published"]
    questions_map = {item["q"]: item for item in questions_data}

    brand_slug = re.sub(r"\s+", "", brand_cfg["name"])
    out_dir = os.path.join(BASE, "output", brand_slug, "monitor")
    os.makedirs(out_dir, exist_ok=True)

    if args.skip_collect and args.results_file:
        with open(args.results_file, encoding="utf-8") as f:
            search_results = json.load(f)
    else:
        results_path = os.path.join(out_dir, "search_results.json")
        search_results = collect_answers(questions_data, results_path)

    # 注入品牌关键词供归因用
    keywords = [brand_cfg["name"]] + brand_cfg.get("aliases", [])
    for r in search_results.get("results", []):
        r["_brand_keywords"] = keywords

    records = analyze(search_results, questions_map, published)
    summary = summarize(records, published)

    result = {"brand": brand_cfg["name"], "summary": summary, "records": records}
    json_path = os.path.join(out_dir, "attribution_result.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    html = render_html(summary, records, brand_cfg["name"], len(questions_data))
    html_path = os.path.join(out_dir, "attribution_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(json.dumps(summary["summary"] if "summary" in summary else summary, ensure_ascii=False, indent=2, default=str))
    print(f"\n归因结果: {json_path}\n成果报告: {html_path}")


if __name__ == "__main__":
    main()
