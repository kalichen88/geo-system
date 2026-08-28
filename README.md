# GEO 内容工厂（Content Factory）

让品牌内容被豆包 / Kimi / DeepSeek 等 AI 搜索引擎引用的批量内容生产工具。

## 它解决什么问题

AI 搜索引擎回答"XX行业哪个品牌好"这类问题时，会实时检索网页信源并引用。
本工具按 **GEO 引用配方**（结论前置、数据密度、实体一致、可摘录结构、长尾提问覆盖）
批量生成适配各平台的内容初稿，发布后成为 AI 的信源，从而提高品牌在 AI 答案中的出现率。

## 使用方法

```bash
# 1. 复制品牌模板并填写
cp brands/template.yaml brands/我的品牌.yaml

# 2. 配置 LLM API（SiliconFlow 或任意 OpenAI 兼容接口）
export LLM_API_KEY=sk-xxxx
# 可选：
# export LLM_BASE_URL=https://api.siliconflow.cn/v1
# export LLM_MODEL=deepseek-ai/DeepSeek-V3

# 3. 生成全套内容初稿
python factory/generate.py --brand brands/我的品牌.yaml

# 只生成某一类
python factory/generate.py --brand brands/我的品牌.yaml --only qa
```

## 输出内容类型

| 类型 | 用途 | 发布目标 |
|------|------|---------|
| zhihu_article | 知乎/自媒体长文 | 知乎、头条号 |
| baijiahao | 百家号风格文章 | 百家号、搜狐号 |
| qa | 问答占位 | 知乎自答、垂直社区 |
| douyin_script | 60秒口播脚本 | 抖音、视频号、B站 |
| news_draft | 新闻稿 | 垂直媒体投稿 |
| website_faq | 官网 FAQ（JSON） | 官网 + Schema.org 标记 |

## 目录结构

```
geo-system/
├── factory/generate.py   # 生成引擎
├── brands/               # 品牌配置（template.yaml 为模板）
├── output/<品牌名>/       # 生成结果 + manifest.json
└── README.md
```

## 重要提醒

- 生成的是**初稿**，发布前必须人工审校（事实核对 + 平台合规）
- 只使用品牌配置中的真实事实，**严禁编造数据、资质、排名**——虚假内容会被 AI 降权且违反广告法
- 各平台发布请遵守平台规则，矩阵号需养号，勿批量注册
