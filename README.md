# WHOOP AI Analyst · WHOOP 智能身体状态分析助手

> WHOOP 告诉你：“今天 Recovery = 46%”。
> 这个项目告诉你：**为什么是 46%、最近发生了什么、你和自己平时相比哪里变了、这种情况过去什么时候出现过，以及今天应该怎么调整。**

WHOOP AI Analyst 是一个面向中文用户、可自托管的开源项目，核心只有一件事：**基于你自己的长期历史，对 WHOOP 数据做个性化深度分析**。训练计划、饮食、长期记忆、AI 对话都是为这个核心服务的。

```
WHOOP 原始数据 → 数据清洗 → 历史时间序列 → 7/28/90 天趋势 → 个人 Baseline
  → 异常检测 → 多指标联合分析 → 长期个人规律 → AI 中文解释 → 训练 / 睡眠 / 恢复建议
```

---

## 核心特性

| 能力 | 说明 |
|---|---|
| **个人基线优先** | 所有指标都和“你自己的 28 日 / 90 日基线”比较，而不是人群常模。基线使用当天之前的窗口（不含当天）。 |
| **完整统计** | rolling mean / median / std、百分比偏差、z-score、趋势斜率（含 p 值）、连续异常天数、个人百分位、变异系数 —— 全部由 Python 计算，LLM 不做任何基础统计。 |
| **多指标联合分析** | 判断 HRV、静息心率、睡眠、近期 Strain、呼吸频率、皮温是否**同向变化**：多指标同步变差 → 恢复不足；只有 HRV 单项偏低 → 保守，不做强判断；HRV↓ RHR↑ 且呼吸/皮温↑ 而负荷不高 → 提示非训练因素（不做医学诊断）。 |
| **可配置异常检测** | 阈值写在 YAML 里，可在设置页按用户覆盖；“自适应”模式参考个人波动（z-score）；并能根据你自己的历史分布**给出个性化阈值建议**。 |
| **长期个人规律学习** | 自动挖掘“睡眠 < 6.5h → 次日 HRV 下降 X%”“连续两天 Strain > 16 → 第三天 Recovery 平均 Y%”“饮酒后第二天 HRV ↓”等规律，附样本量、p 值和置信度，并且只表述为相关趋势。 |
| **历史相似日** | “这种情况以前出现过吗？”—— 找出偏离模式最相似的历史日子，以及之后几天恢复得怎么样。 |
| **身体状态分** | 0-100 综合分：个人偏差（HRV / RHR / 睡眠 / 昨日负荷 / 呼吸频率）与 WHOOP Recovery 混合。 |
| **AI Agent** | 20 个数据工具（`get_today_whoop`、`get_hrv_history`、`get_metric_trend`、`detect_anomalies`、`get_learned_patterns`、`find_similar_days`、`save_memory`…），回答前必须先调用真实数据。 |
| **训练 / 饮食（第二层）** | 先判断身体状态，再读取当天计划并调整（例如总量 -20~30%、RPE -1、避免力竭，或改为恢复训练）。饮食只做宏量层面的简单建议。 |
| **长期记忆** | 记住“昨晚喝酒”“考试周”“开始减脂”“Deload”等，用于解释第二天的数据，也参与规律学习。对话里提到会自动记录。 |
| **日报 / 周报** | 规则引擎生成结构化中文报告；配置大模型后可一键生成 AI 解读。 |
| **国内友好** | 大模型支持 DeepSeek / 通义千问 / Kimi / 智谱等 OpenAI 兼容接口，也支持 Claude；**不配置大模型也能完整运行**（规则引擎问答）。 |

## 截图里能看到什么

- **今日状态**：身体状态分 + 联合判断 → Recovery / HRV / RHR / 睡眠 / 昨日 Strain 与个人基线的偏差 → AI 今日分析（3 条最重要结论）→ 训练调整（原计划 vs 调整后）→ 饮食 → 相关规律 / 相似日子 / 近期记录
- **趋势**：7D / 28D / 90D / 180D，每日数值 + 7 日均线 + 28 日个人基线 ±1σ 带 + 异常点，以及完整统计面板
- **AI 对话**：可展开查看每次回答调用了哪些数据工具
- **周报**、**个人规律**、**记录与计划**、**设置**（WHOOP 连接、阈值调整与个性化建议）

---

## 快速开始（5 分钟，无需 WHOOP 账号）

依赖：Python 3.11+、Node 20+（推荐 [uv](https://github.com/astral-sh/uv)）。

```bash
git clone <your-gitlab-repo-url> whoop-ai-analyst && cd whoop-ai-analyst
cp .env.example .env

# 后端
cd backend
uv venv && uv pip install -e ".[dev]"      # 或：python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/whoop-analyst demo                # 生成 200 天 Demo 数据并完成全部分析
.venv/bin/uvicorn app.main:app --reload --port 8000

# 前端（另开一个终端）
cd frontend
npm install
npm run dev                                 # 打开 http://localhost:5173
```

Demo 数据会模拟真实的生理规律（睡眠不足、连续高负荷、饮酒、生病、出差、考试周、长期 HRV 改善），系统能从中“学到”个人规律。最近 4 天被设计成“考试周 + 连续高负荷”，方便直接看到多指标联合分析的效果。

### 命令行

```bash
whoop-analyst demo [--days 200]      # 生成 Demo 数据
whoop-analyst sync [--full]          # 同步 WHOOP
whoop-analyst recompute              # 从原始数据重算全部分析
whoop-analyst report [--date D]      # 终端打印日报
whoop-analyst ask "为什么我的 HRV 最近一直下降？"
```

### Docker 部署

```bash
cp .env.example .env     # 填写 WHOOP / LLM 配置
docker compose up -d     # 打开 http://localhost:8000（前后端同一端口）
```

需要 PostgreSQL：`docker compose --profile postgres up -d`，并在 `.env` 中设置 `DATABASE_URL=postgresql+psycopg://whoop:whoop@db:5432/whoop_analyst`。

---

## 连接 WHOOP

1. 在 [WHOOP Developer Dashboard](https://developer-dashboard.whoop.com) 创建应用
2. Redirect URL 填 `http://localhost:8000/api/whoop/auth/callback`（与 `.env` 中 `WHOOP_REDIRECT_URI` 一致）
3. 勾选 scopes：`read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement`（项目会额外请求 `offline` 以获取 refresh token）
4. 把 Client ID / Secret 写入 `.env`，重启后端
5. 打开「设置」→「连接 WHOOP」。首次授权会回填 `WHOOP_INITIAL_BACKFILL_DAYS` 天的历史数据（会先清空 Demo 数据）

之后可以手动「立即同步」，或设置 `ENABLE_SCHEDULER=true` 每天自动同步并生成日报，每周一生成周报。增量同步会回看 3 天，覆盖 WHOOP 延迟打分或修改过的数据。

使用的 WHOOP API v2 端点：`/v2/cycle`、`/v2/recovery`、`/v2/activity/sleep`、`/v2/activity/workout`、`/v2/user/profile/basic`、`/v2/user/measurement/body`。原始 JSON 全部保存在 `raw` 字段中，分析层随时可以从原始数据完整重算。

## 配置大模型（可选）

| 提供方 | `.env` |
|---|---|
| 不使用（默认） | `LLM_PROVIDER=none` —— 规则引擎生成中文解读与问答 |
| DeepSeek | `LLM_PROVIDER=openai_compatible` `LLM_BASE_URL=https://api.deepseek.com` `LLM_MODEL=deepseek-chat` `LLM_API_KEY=…` |
| 通义千问 | `LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1` `LLM_MODEL=qwen-plus` |
| Kimi | `LLM_BASE_URL=https://api.moonshot.cn/v1` `LLM_MODEL=moonshot-v1-32k` |
| Claude | `LLM_PROVIDER=anthropic` `ANTHROPIC_API_KEY=…`（默认 `claude-opus-5-5`，`ANTHROPIC_EFFORT=medium`） |

大模型只负责**理解、联合判断、解释、说人话**。所有数字都来自工具调用，系统提示词要求：先取数再回答、与个人基线比较、单指标异常保持保守、只说相关不说因果、不做医学诊断。大模型调用失败时会自动降级为规则引擎回答。

---

## 架构

```
frontend/  (React + Vite + ECharts)
    │  /api
backend/app/
├── whoop/        OAuth2、API v2 客户端、原始数据入库（日期归属规则见 ingest.py）、增量同步
├── analytics/    ← 项目核心：Python 分析层
│   ├── timeseries.py   原始表 → 按天对齐的时间序列
│   ├── stats.py        滚动统计、z-score、斜率、百分位、连续天数、Welch t 检验
│   ├── analysis.py     单指标深度分析（7/28/90 天、基线、趋势、波动性）
│   ├── anomaly.py      可配置异常检测 + 个性化阈值建议（anomaly_rules.yaml）
│   ├── joint.py        多指标联合分析（状态判定 + 证据 + 置信度）
│   ├── readiness.py    身体状态分
│   ├── patterns.py     个人规律挖掘
│   ├── similar.py      历史相似日
│   ├── drivers.py      恢复驱动因素（四分位对比 + Spearman）
│   └── pipeline.py     全量重算流水线（daily_metrics / baselines / anomalies / patterns）
├── reports/      日报、周报（规则引擎中文叙述）
├── coaching/     训练调整、饮食建议（第二层）
├── memory/       长期记忆（标签识别、时间窗检索）
├── agent/        Tools、LLM 提供方（OpenAI 兼容 / Anthropic）、规则引擎兜底、提示词
├── api/          FastAPI 路由
└── demo/         与 WHOOP v2 结构一致的模拟数据生成器
```

数据库表：`users` `whoop_connections` `whoop_cycles` `whoop_recovery` `whoop_sleep` `whoop_workouts` `body_measurements` `daily_metrics` `metric_baselines` `metric_anomalies` `learned_patterns` `daily_reports` `weekly_reports` `memories` `training_plans` `nutrition_plans` `conversations` `conversation_messages`。

分析方法的细节（基线定义、阈值、联合判断规则、规律挖掘的统计检验、身体状态分公式）见 [docs/methodology.md](docs/methodology.md)。

## 开发

```bash
cd backend && .venv/bin/pytest -q          # 后端测试
cd frontend && npm run build               # 前端类型检查 + 构建
```

主要 API：`GET /api/dashboard`、`GET /api/trends?metric=hrv&days=90`、`GET /api/patterns`、`GET /api/anomalies`、`GET /api/similar`、`GET /api/drivers`、`POST /api/chat`、`GET /api/reports/weekly/{week_start}`、`GET|PUT /api/settings`。启动后访问 `/docs` 查看完整 OpenAPI 文档。

## Roadmap

- [ ] WHOOP Webhooks 实时更新
- [ ] 多用户与登录（当前为自托管单用户模式）
- [ ] 长期记忆的向量检索（pgvector）
- [ ] 规律学习：多变量回归、滞后效应、个人阈值自动校准
- [ ] 月度报告、导出 PDF
- [ ] 移动端 PWA

## 免责声明

本项目是个人数据分析工具，**不是医疗器械，不提供医学诊断或治疗建议**。所有分析都是基于个人历史数据的统计相关性。如有身体不适，请咨询专业医生。

本项目与 WHOOP, Inc. 无任何关联，WHOOP 是其各自所有者的商标。

## License

[MIT](LICENSE)
