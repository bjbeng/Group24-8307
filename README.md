# IndustryAgent — 工业 AI 文档智能审核系统

基于**多 Agent 协作架构**的工业作业文档自动审核平台，支持：
- **场景一**：作业指导书文本审核（11 维度）
- **场景二**：高后果区风险管控方案多模态审核（文本 + 图片）

适用于油气管道行业，自动化检测文档的结构完整性、内容合规性、语言规范性及图片一致性。

---

## 目录

- [系统架构](#系统架构)
- [两种运行模式](#两种运行模式)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [Pipeline 详解](#pipeline-详解)
- [Agent 设计](#agent-设计)
- [数据库设计](#数据库设计)
- [API 参考](#api-参考)
- [快速启动](#快速启动)
- [CLI 使用](#cli-使用)
- [配置说明](#配置说明)
- [安全特性](#安全特性)
- [输出格式](#输出格式)
- [部署指南](#部署指南)

---

## 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端层 (Frontend)                        │
│   React 18 + TypeScript + Vite + Axios + React Router + Tauri  │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTP/WebSocket
┌───────────────────────────────▼─────────────────────────────────┐
│                         后端层 (Backend)                        │
│                     FastAPI + Uvicorn                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Auth Route  │  │  Upload API  │  │  Audit/History/Monitor│  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              WebSocket / 实时进度推送                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│                       引擎层 (Engine)                           │
│                                                                  │
│  ┌─────────────────┐         ┌─────────────────────────────┐   │
│  │  AuditPipeline  │         │     LabelPipeline           │   │
│  │   (单 LLM 审核)  │         │   (2+1 Agent 打标 Ground Truth)│   │
│  └────────┬────────┘         └──────────┬──────────────────┘   │
│           │                            │                       │
│           ▼                            ▼                       │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              多维度 Agent 并行执行                       │    │
│  │  C1 C2 C3 C4 C5 │ E1 E2 │ L2 │ T1 T2 T3                 │    │
│  │  (Content)      (Exec)  (Std) (Tech)                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                  │
│           ┌──────────────────┼──────────────────┐               │
│           ▼                  ▼                  ▼               │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐         │
│  │  LLM Provider│   │  FTS5 检索   │   │  标准库检索  │         │
│  │ (vLLM/Ollama)│   │  (SQLite)    │   │  (ChromaDB)  │         │
│  └──────────────┘   └──────────────┘   └──────────────┘         │
└───────────────────────────────┬─────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────┐
│                      存储层 (Storage)                           │
│              SQLite (FTS5) + ChromaDB + 文件系统                │
└─────────────────────────────────────────────────────────────────┘
```

### 三层分离架构

| 层级 | 职责 | 技术 |
|------|------|------|
| **前端展示层** | 用户交互、文件上传、结果可视化、实时进度 | React + TypeScript + Vite + Tauri |
| **API 路由层** | HTTP 路由、鉴权、WebSocket、任务调度 | FastAPI + Uvicorn |
| **引擎计算层** | 文档解析、Agent 执行、LLM 调用、结果仲裁 | Python + LangGraph + ThreadPoolExecutor |

---

## 两种运行模式

### 模式对比

| 维度 | 审核（Audit） | 打标（Label） |
|------|---------------|---------------|
| **Pipeline** | `src/pipeline/audit.py`（按场景路由到 `src/pipeline/image_pipeline.py` 等） | `src/harness/pipeline/label_pipeline.py` |
| **Agent 架构** | 单 LLM Provider + 8 维度并行 | 2+1（Explorer A ‖ B + Critic） |
| **前端** | ✅ 有（FastAPI + React） | ❌ 无（纯 CLI） |
| **输出** | JSON + 人工可读报告 + 带批注 DOCX | Ground Truth JSON（用于模型训练） |
| **适用场景** | 生产审核、人工复核辅助 | 模型微调数据标注 |

> 重要：**场景二（s2）的“审核（audit）”不走 `harness/`**。`harness/` 仅用于 **打标（label）2+1**。
> s2 审核会在 `src/pipeline/audit.py` 内通过场景路由（`src/pipeline/scenario_router.py`）进入 `src/pipeline/image_pipeline.py` 等模块。

### 2+1 打标架构详解

```
Explorer A（高召回）‖ Explorer B（高精度）
        │                    │
        ▼                    ▼
   temperature=0.2      temperature=0.0
   采样多样性           确定性输出
        │                    │
        └──────────┬─────────┘
                   ▼
           CrossDimensionCritic
                   │
           ┌──────┴──────┐
           ▼             ▼
     规则仲裁         LLM 仲裁
   （快速，无成本）   （仅分歧维度）
           │             │
           └──────┬──────┘
                  ▼
            Ground Truth
            写入 labels 表
```

**Explorer A vs B 的区别：**
- **Explorer A**：temperature=0.2，采样多样，擅长发现边缘 case
- **Explorer B**：temperature=0.0，确定性输出，擅长精确判断
- **Critic**：仲裁 A/B 分歧，高难度 case 保存为 Skill

**场景模型配置：**

| 角色 | 场景一（s1，作业书） | 场景二（s2，风险管控） |
|------|---------------------|----------------------|
| Explorer A | DeepSeek-V3（中文理解） | Qwen-VL（文字+图片） |
| Explorer B | Qwen3.5-Plus | Gemini（视觉理解） |
| Critic | deepseek-reasoner（推理仲裁） | Qwen3.6-Plus |

---

## 技术栈

### 后端技术

| 类别 | 技术 | 用途 |
|------|------|------|
| **语言** | Python 3.10+ | 核心业务逻辑 |
| **Web 框架** | FastAPI + Uvicorn | REST API + WebSocket |
| **多步推理** | LangGraph | C5 逻辑审核（业务逻辑链） |
| **并发** | ThreadPoolExecutor | Agent 并行执行 |
| **数据库** | SQLite + FTS5 | 文档存储 + 全文检索 |
| **向量检索** | ChromaDB | 标准库语义检索 |
| **文档解析** | python-docx, pdfplumber, PyMuPDF, MinerU | DOCX/PDF 解析 |
| **NLP** | jieba（分词）, LangGraph | 中文处理 + 状态机 |
| **LLM 集成** | OpenAI-compatible API | 支持 vLLM/Ollama/自定义后端 |
| **配置** | Pydantic + YAML | 配置管理 |

### 前端技术

| 类别 | 技术 | 用途 |
|------|------|------|
| **框架** | React 18 | UI 组件库 |
| **语言** | TypeScript | 类型安全 |
| **构建** | Vite | 快速开发构建 |
| **HTTP** | Axios | API 调用 |
| **路由** | React Router v6 | SPA 路由 |
| **状态** | React Context | 全局状态（Auth/I18n） |
| **桌面** | Tauri v2 | Windows .exe 打包 |

### 部署技术

| 类别 | 技术 | 用途 |
|------|------|------|
| **Web 服务器** | Nginx | 反向代理 + 静态资源 |
| **进程管理** | systemd | 开机自启 + 进程守护 |
| **SSL** | Let's Encrypt | HTTPS 证书 |
| **容器** | Docker（可选） | 环境隔离 |

---

## 目录结构

```
industry-demo/
├── backend/
│   ├── app/                          # FastAPI Web 层
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI 应用入口
│   │   ├── config.py                 # Pydantic 配置模型
│   │   ├── security.py               # 路径穿越防护
│   │   ├── auth/                     # 认证模块
│   │   │   ├── core.py               # bcrypt 密码哈希
│   │   │   ├── deps.py               # CSRF 校验
│   │   │   └── routes.py              # 登录/注册路由
│   │   ├── routes/                   # API 路由
│   │   │   ├── audit.py              # 审核相关 API
│   │   │   ├── upload.py             # 文件上传
│   │   │   ├── ws.py                 # WebSocket 进度
│   │   │   ├── rules.py              # 规则管理
│   │   │   ├── history.py            # 审核历史
│   │   │   └── monitor.py            # 系统监控
│   │   ├── monitor/                  # Monitor Agent
│   │   │   └── agent.py
│   │   ├── tasks/                    # 异步任务队列
│   │   └── tracing/                  # 事件追踪 hooks
│   │
│   ├── src/                          # 核心引擎
│   │   ├── __init__.py
│   │   ├── config.py                 # 引擎配置（从 YAML 加载）
│   │   ├── cli.py                    # CLI 入口
│   │   │
│   │   ├── agents/                   # 维度 Agent 实现
│   │   │   ├── base.py               # BaseAgent 基类 + 数据模型
│   │   │   ├── audit_judgment.py     # LLM judgment 服务
│   │   │   ├── llm_audit_utils.py    # Agent 工具函数
│   │   │   ├── standards_seed.py     # 标准库初始化
│   │   │   ├── scene1/               # 场景一 Agent（文本）
│   │   │   │   ├── c1_structure.py   # C1 结构完整性（规则）
│   │   │   │   ├── c2_content.py     # C2 内容完整性（FTS+RAG）
│   │   │   │   ├── c3_language.py    # C3 语言规范（FTS+RAG）
│   │   │   │   ├── c4_reference.py   # C4 引用追溯（规则）
│   │   │   │   ├── c5_logic.py       # C5 业务逻辑（LangGraph）
│   │   │   │   ├── e1_staffing.py    # E1 人员配备（公式）
│   │   │   │   ├── e2_emergency.py   # E2 应急措施（FTS+RAG）
│   │   │   │   └── l2_standards.py   # L2 标准合规（RAG）
│   │   │   └── scene2/               # 场景二 Agent（多模态）
│   │   │       ├── vision_base.py    # 视觉 Agent 基类
│   │   │       ├── i1_signature.py   # I1 签章检测
│   │   │       ├── i2_required_images.py
│   │   │       ├── i3_aerial.py      # I3 航拍图检测
│   │   │       ├── i4_entry_route.py # I4 进场地形图
│   │   │       ├── i5_evacuation.py  # I5 逃生路线图
│   │   │       ├── i6_water_containment.py
│   │   │       ├── i7_municipal_crossing.py
│   │   │       ├── i8_image_text_consistency.py
│   │   │       ├── l1_context_consistency.py
│   │   │       ├── l2_standards.py
│   │   │       ├── l3_required_sections.py
│   │   │       ├── l4_time_sequence.py
│   │   │       ├── l5_data_logic.py
│   │   │       ├── l6_text_template.py
│   │   │       ├── legacy_image_agents.py  # 旧版 s2（qzq）图片维度 I1-I6
│   │   │       └── legacy_text_agents.py   # 旧版 s2（qzq）文本维度 L1/L3-L6
│   │   │
│   │   │       └── image_classifier.py
│   │   │
│   │   ├── pipeline/                 # Pipeline 实现
│   │   │   ├── audit.py              # 审核 Pipeline（主流程）
│   │   │   ├── scenario_router.py    # 场景路由（s1/s2：audit 入口按场景分发）
│   │   │   └── image_pipeline.py     # 场景二（s2）审核：图片/多模态相关流程
│   │   │
│   │   ├── harness/                  # 打标引擎（2+1 Agent，仅 label）
│   │   │   ├── pipeline/
│   │   │   │   └── label_pipeline.py # 打标 Pipeline
│   │   │   ├── agent_group/
│   │   │   │   ├── explorer.py       # Explorer A/B 并行执行
│   │   │   │   ├── critic.py         # CrossDimensionCritic 仲裁
│   │   │   │   ├── sub_agent.py      # SubAgent 封装
│   │   │   │   ├── orchestrator.py   # 编排器
│   │   │   │   ├── dim_supervisor.py # 维度主管
│   │   │   │   └── roles.py          # 角色定义
│   │   │   ├── tools/                # Agent 工具
│   │   │   │   ├── retrieval.py      # RAG 检索
│   │   │   │   ├── verification.py   # 证据验证
│   │   │   │   ├── skills.py        # Skill 管理
│   │   │   │   └── registry.py      # 工具注册表
│   │   │   ├── guardrails/           # 安全护栏
│   │   │   │   ├── human_review.py  # 人工复核判断
│   │   │   │   ├── retry_policy.py  # 重试策略
│   │   │   │   └── schemas.py       # 输出 Schema
│   │   │   ├── memory/               # 记忆管理
│   │   │   │   ├── context_builder.py
│   │   │   │   └── skills_store.py
│   │   │   ├── session/              # 会话管理
│   │   │   │   ├── doc_session.py
│   │   │   │   └── batch_manager.py
│   │   │   └── hooks/               # 事件钩子
│   │   │       ├── registry.py
│   │   │       └── built_in.py
│   │   │
│   │   ├── llm/                      # LLM 集成
│   │   │   ├── provider.py           # LLMProvider 抽象接口
│   │   │   ├── api_provider.py      # OpenAI-compatible 实现
│   │   │   ├── mock_provider.py     # Mock 测试用
│   │   │   └── factory.py           # Provider 工厂
│   │   │
│   │   ├── store/                    # 数据持久化
│   │   │   ├── repository.py        # SQLite CRUD
│   │   │   └── schema.sql           # 数据库 Schema
│   │   │
│   │   ├── chunk/                    # 文档切块
│   │   │   ├── models.py            # Chunk 数据模型
│   │   │   ├── text_chunk.py
│   │   │   └── image_chunk.py
│   │   │
│   │   ├── parse/                    # 文档解析
│   │   │   ├── docx_parser.py      # DOCX 解析
│   │   │   ├── pdf_parser.py       # PDF 解析
│   │   │   ├── doc_converter.py     # DOC → DOCX 转换
│   │   │   ├── scan_detector.py    # 扫描件检测 + OCR
│   │   │   └── mineru_parser.py    # MinerU 解析（可选）
│   │   │
│   │   ├── metrics/                  # 技术指标（T1-T3）
│   │   │   └── compute.py
│   │   │
│   │   ├── retrieve/                 # 检索模块
│   │   │   └── fts_search.py        # FTS5 全文检索
│   │   │
│   │   ├── standards_lib/            # 标准库
│   │   │   ├── loader.py            # 标准加载
│   │   │   ├── embedder.py         # Embedding 模型
│   │   │   ├── chroma_importer.py  # ChromaDB 导入
│   │   │   ├── ingest_chroma.py    # 批量导入
│   │   │   ├── hybrid_search.py    # 混合检索
│   │   │   └── normalizer.py       # 标准号规范化
│   │   │
│   │   └── output/                   # 输出模块
│   │       ├── json_writer.py       # JSON 写入
│   │       ├── contest_formatter.py # 赛题格式输出
│   │       └── annotator.py        # DOCX 批注生成
│   │
│   └── config/
│       └── default.yaml             # 默认配置
│
├── frontend/
│   ├── src/
│   │   ├── pages/                   # 页面组件
│   │   │   ├── UploadPage.tsx       # 文件上传页
│   │   │   ├── AuditStatusPage.tsx  # 审核状态页
│   │   │   ├── ResultsPage.tsx      # 结果展示页
│   │   │   └── ...
│   │   ├── components/              # 通用组件
│   │   ├── api/                      # API 客户端
│   │   ├── context/                  # React Context
│   │   │   ├── AuthContext.tsx
│   │   │   └── I18nContext.tsx
│   │   └── App.tsx
│   └── src-tauri/                   # Tauri 桌面端
│
├── deploy/                           # 部署脚本
│   └── install.sh                   # 一键安装脚本
│
├── PROMPTS.md                        # Agent Prompt 集合
├── QUICKSTART.md                     # 快速入门
└── README.md                         # 本文档
```

---

## Pipeline 详解

### 审核 Pipeline（AuditPipeline）

```
文档输入
    │
    ▼
┌─────────────────┐
│  文档解析        │  python-docx / pdfplumber / PyMuPDF / MinerU
│  .doc/.docx/.pdf │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  文档切块        │  按章节/段落切分，max_tokens=500
│  chunk_docx_... │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  入库（FTS5）    │  存入 SQLite，实现全文检索
│  upsert_chunks   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  标准库预热      │  并行预加载 C2/E2/L2 相关标准条款
│  prewarm cache  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              8 维度 Agent 并行执行                    │
│  ThreadPoolExecutor(max_workers=8)                  │
│                                                      │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │
│  │   C1   │ │   C2   │ │   C3   │ │   C4   │       │
│  │结构完整│ │内容完整│ │语言规范│ │引用追溯│       │
│  └────────┘ └────────┘ └────────┘ └────────┘       │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │
│  │   C5   │ │   E1   │ │   E2   │ │   L2   │       │
│  │业务逻辑│ │人员配备│ │应急措施│ │标准合规│       │
│  └────────┘ └────────┘ └────────┘ └────────┘       │
└───────────────────────┬─────────────────────────────┘
                        │
         ┌──────────────┴──────────────┐
         ▼                              ▼
┌─────────────────┐          ┌─────────────────┐
│  T1-T3 Metrics  │          │  结果聚合       │
│ （规则，无LLM） │          │  _aggregate()   │
└────────┬────────┘          └────────┬────────┘
         │                             │
         └──────────────┬──────────────┘
                        ▼
┌─────────────────┐
│  LLM Judgment   │  生成人工可读审核意见
│  AuditJudgment  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  AuditReport    │  总体意见 + 关键问题 + 建议
│  _build_audit.. │
└────────┬────────┘
         │
         ▼
      输出 JSON + Markdown 报告 + 带批注 DOCX
```

#### 场景二（s2）在 Audit 中的入口说明

- **结论**：s2 的 **审核（audit）** 属于 `src/pipeline/` 体系，通过场景路由进入图片/多模态流程，**不经过 `src/harness/`**。
- **路径**：`src/pipeline/audit.py` → `src/pipeline/scenario_router.py` → `src/pipeline/image_pipeline.py`（以及 `src/agents/scene2/*`）。

### 打标 Pipeline（LabelPipeline）

```
文档输入
    │
    ▼
┌─────────────────┐
│  文档解析        │  同 Audit（统一入口）
│  + 图片提取      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  图片分类       │  classify_images（I1-I8 类型）
│  (场景二 s2)    │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│          Explorer A ‖ Explorer B 并发               │
│  ThreadPoolExecutor(max_workers=2)                 │
│                                                      │
│    Explorer A (temp=0.2)  │  Explorer B (temp=0.0) │
│    高召回                  │  高精度                  │
│    全部 SubAgent 并行      │  全部 SubAgent 并行      │
└───────────────────────┬─────────────────────────────┘
                        │
         ┌──────────────┴──────────────┐
         ▼                              ▼
┌─────────────────┐          ┌─────────────────┐
│   A_results     │          │   B_results     │
│ {dim: AgentRes} │          │ {dim: AgentRes} │
└────────┬────────┘          └────────┬────────┘
         │                            │
         └──────────────┬─────────────┘
                        ▼
┌─────────────────────────────────────────────────────┐
│              CrossDimensionCritic                    │
│                                                      │
│  1. 规则仲裁（快速，无 LLM 调用）                     │
│     - A=B → 合并，取平均置信度                       │
│     - A≠B → 保守选择（fail > partial > uncertain > pass）│
│                                                      │
│  2. LLM 仲裁（仅分歧维度，最多 6 个）                  │
│     - 高分歧维度调用 critic_model                    │
│     - 输出裁决理由 + evidence 验证                   │
│                                                      │
│  3. 跨维度一致性检查                                  │
│     - 降级矛盾维度的置信度                           │
└───────────────────────┬─────────────────────────────┘
                        │
                        ▼
               {dim: AgentResult}
                        │
                        ▼
┌─────────────────┐
│  持久化 GT       │  写入 labels 表（pipeline="label"）
│  upsert_label   │
└────────┬────────┘
         │
         ▼
       输出赛题格式 JSON
```

#### 场景二（s2）旧版流程：走 `harness`（legacy/qzq）

你记得的“旧版 s2 走 harness”是对的：在 **LabelPipeline（打标）** 里，s2 的维度集合由 `src/harness/agent_group/sub_agent.py:_build_s2_agents()` 构建，\n当环境变量满足以下任一值时，会切到 **旧版（qzq 对齐）** 流程：

- `INDUSTRY_S2_FLOW_MODE=legacy`
- `INDUSTRY_S2_FLOW_MODE=qzq`
- `INDUSTRY_S2_FLOW_MODE=legacy_qzq`

旧版 s2 的维度（对齐 qzq_addwork2）大致为：

- **图片类（I1-I6）**：来自 `src/agents/scene2/legacy_image_agents.py`
  - `I1_evacuation_route`（疏散路线图）
  - `I2_assembly_point`（集结点示意）
  - `I3_material`（应急物资/装备）
  - `I4_entry_route`（进场路线/地形）
  - `I5_hca_aerial`（高后果区航拍/俯视）
  - `I6_approval_page`（审批页/签批页）
- **文本类（L1/L3/L4/L5/L6）**：来自 `src/agents/scene2/legacy_text_agents.py`
  - `L1_format`、`L3_semantic`、`L4_risk_identification`、`L5_emergency_measures`、`L6_professional`
- **标准合规（L2）**：仍复用 `src/agents/scene2/l2_standards.py`

同时，旧版还会做一层 **image_type 映射过滤**（把解析出的 `image_chunks` 按类型喂给对应 I 维度），映射逻辑在 `sub_agent.py` 内部的 `legacy_dim_to_image_types`。

---

## Agent 设计

### 数据模型

```python
# 核心数据结构（src/agents/base.py）

@dataclass
class Finding:
    severity: str           # "high" | "medium" | "low"
    description: str       # 问题描述
    evidence: str          # 证据文本
    rule_id: str | None    # 对应规则 ID
    section_path: str       # 章节路径 "3.2.1"
    paragraph_index: int    # 段落索引（用于精确定位）
    # 赛题格式
    is_problem: bool       # 是否有问题
    problem_type: str      # 问题类型
    rule_basis: str        # 规则依据
    correction_suggestion: str  # 修改建议

@dataclass
class AgentResult:
    dimension: str         # 维度名 "C1_structure_completeness"
    verdict: str           # "pass" | "partial" | "fail" | "uncertain"
    score: int | None      # 分数 0-12
    confidence: int        # 置信度 0-100
    findings: list[Finding]
    need_human_review: bool
```

### 维度分类

| 类别 | 维度 | 类型 | 实现方式 |
|------|------|------|----------|
| **Content（C）** | C1 结构完整性 | 规则 | 正则 + 章节检测 |
| | C2 内容完整性 | LLM+RAG | FTS5 检索 + LLM 判断 |
| | C3 语言规范 | LLM+RAG | FTS5 检索 + LLM 判断 |
| | C4 引用追溯 | 规则 | 正则 + 交叉引用验证 |
| | C5 业务逻辑 | LangGraph | 多步推理状态机 |
| **Execution（E）** | E1 人员配备 | 公式 | 配置公式 + 参数提取 |
| | E2 应急措施 | LLM+RAG | FTS5 检索 + LLM 判断 |
| **Standards（L）** | L2 标准合规 | RAG | ChromaDB 向量检索 |
| **Metrics（T）** | T1 处理时长 | 规则 |计时测算 |
| | T2 格式规范 | 规则 | 文件格式检测 |
| | T3 文件完整 | 规则 | 必填字段检测 |

### Agent 执行流程

```
输入: chunks (list[dict])
    │
    ▼
┌─────────────────┐
│  向量检索       │  从 ChromaDB/FTS5 检索相关标准条款
│  retrieve_std.. │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  构建 Prompt   │  注入标准条款 + chunk 内容
│  _build_prompt  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  LLM 调用       │  provider.call_text(messages, model, temp)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  JSON 解析      │  parse_json_response() 处理 markdown/json
│  parse_json_res │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  结果组装       │  转换为 AgentResult + Finding
│  _to_result     │
└────────┬────────┘
         │
         ▼
   返回 AgentResult
```

---

## 数据库设计

### 核心表结构（SQLite + FTS5）

```sql
-- 文档切块表（支持全文检索）
CREATE VIRTUAL TABLE chunks USING fts5(
    chunk_id, doc_id, chunk_type, section_path, title,
    content, paragraph_index, anchor_text, dimensions,
    cross_refs, word_count, parent_id,
    tokenize='unicode61'
);

-- 审核/打标结果表
CREATE TABLE labels (
    label_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    pipeline TEXT NOT NULL,  -- 'audit' | 'label'
    final_verdict TEXT,
    score INTEGER,
    confidence INTEGER,
    explorer_a TEXT,  -- JSON
    explorer_b TEXT,  -- JSON
    findings TEXT,    -- JSON list
    extra TEXT,       -- JSON
    need_human_review INTEGER,
    human_signoff INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 行业标准条款库
CREATE TABLE standards (
    standard_id TEXT PRIMARY KEY,
    standard_type TEXT,     -- 'GB' | 'QSY' | 'SY'
    standard_number TEXT,
    title TEXT,
    clauses TEXT,          -- JSON array
    full_text TEXT,
    created_at TIMESTAMP
);

-- 文档缓存（避免重复解析）
CREATE TABLE document_cache (
    file_hash TEXT PRIMARY KEY,
    source_name TEXT,
    doc_id TEXT,
    converted_docx_path TEXT,
    parsed_with TEXT,
    created_at TIMESTAMP
);

-- 可复用审核技能库
CREATE TABLE skills (
    skill_id TEXT PRIMARY KEY,
    dimension TEXT,
    description TEXT,
    trigger_conditions TEXT,  -- JSON
    actions TEXT,            -- JSON
    success_rate REAL,
    use_count INTEGER
);
```

### FTS5 检索示例

```python
# 检索相关标准条款
results = repo.search_chunks(
    doc_id=doc_id,
    query="应急演练 人员配备",
    dimension="E2_emergency",
    top_k=5
)
```

---

## API 参考

### 认证相关

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| POST | `/api/auth/register` | 注册用户 | `{"username", "email", "password"}` |
| POST | `/api/auth/login` | 登录 | `{"username", "password"}` |
| POST | `/api/auth/logout` | 登出 | - |
| GET | `/api/auth/me` | 获取当前用户 | - |

### 文档操作

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|-------------|
| POST | `/api/upload` | 上传文档 | multipart/form-data |
| GET | `/api/documents` | 文档列表 | `?page=1&limit=20` |
| GET | `/api/documents/{id}` | 文档详情 | - |
| DELETE | `/api/documents/{id}` | 删除文档 | - |

### 审核操作

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| POST | `/api/audit/start` | 启动审核 | `{"doc_id", "scenario"}` |
| GET | `/api/audit/{task_id}` | 查询结果 | - |
| POST | `/api/audit/batch` | 批量审核 | `{"doc_ids": []}` |
| GET | `/api/audit/history` | 审核历史 | `?page=1&limit=20` |

### WebSocket 实时进度

```
WS /ws/audit/{task_id}

发送消息格式:
{
    "type": "progress" | "complete" | "error",
    "dimension": "C1",
    "verdict": "pass",
    "progress": 0.75,
    "message": "C1 审核完成"
}
```

### 规则管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/rules` | 获取规则集列表 |
| GET | `/api/rules/{id}` | 规则详情 |
| POST | `/api/rules` | 创建规则 |
| PUT | `/api/rules/{id}` | 更新规则 |
| DELETE | `/api/rules/{id}` | 删除规则 |

### 监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/monitor/stats` | 系统统计 |
| GET | `/api/monitor/logs` | 实时日志 |

---

## 快速启动

### 环境要求

- Python 3.10+
- Node.js 18+
- npm 或 yarn
- SQLite（Python 内置）

### 后端启动

```bash
cd backend

# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境（Windows）
venv\Scripts\activate

# 3. 安装依赖
pip install -e .

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填写必要的 API Key 和 SECRET_KEY（≥32字符）

# 5. 启动服务
uvicorn app.main:app --reload --port 8001

# 验证运行
curl http://localhost:8001/health
```

### 前端启动

```bash
cd frontend

# 1. 安装依赖
npm install

# 2. 启动开发服务器
npm run dev

# 访问 http://localhost:5173
```

### Mock 模式（无需真实 API）

在 `.env` 中设置 `LLM_USE_MOCK=true`，系统将使用 Mock LLM Provider，直接运行规则引擎，无需任何 API Key。

---

## CLI 使用

### 审核模式（单 LLM，有前端）

```bash
cd backend

# 基本用法
python -m src.cli audit path/to/document.docx

# 指定输出目录
python -m src.cli audit path/to/doc.docx --out results/

# 仅生成 JSON + Markdown 报告（跳过 DOCX 批注）
python -m src.cli audit path/to/doc.docx --report-only

# 使用自定义配置
python -m src.cli audit path/to/doc.docx --config config/custom.yaml -v
```

### 打标模式（2+1 Agent，Ground Truth）

```bash
# 场景一：作业指导书（纯文本）
python -m src.cli label path/to/instruction.docx --scenario s1

# 场景二：风险管控方案（文本 + 图片）
python -m src.cli label path/to/risk_plan.docx --scenario s2

# 指定输出路径
python -m src.cli label path/to/doc.docx --out results/gt.json -v

# 查看赛题格式输出
python -m src.cli label path/to/doc.docx --scenario s1 --out results/out.json
```

### 其他命令

```bash
# 重建 ChromaDB 标准库
python -m src.cli ingest-chroma --force

# 查看帮助
python -m src.cli --help
python -m src.cli audit --help
python -m src.cli label --help
```

---

## 配置说明

### 默认配置（config/default.yaml）

```yaml
# LLM 配置
llm:
  text_model: "DeepSeek-V3"        # 文本模型
  vision_model: "Qwen-VL"          # 视觉模型
  judgment_model: "DeepSeek-V3"     # Judgment 模型
  
  explorer_a:
    model: "DeepSeek-V3"           # A 模型
    temperature: 0.2               # 高召回
  explorer_b:
    model: "Qwen3.5-Plus"          # B 模型
    temperature: 0.0               # 高精度
  critic:
    model: "deepseek-reasoner"     # 仲裁模型

# 路径配置
paths:
  data_dir: "data"                 # 数据目录
  images_dir: "data/images"        # 图片目录
  db_path: "data/industry_agent.db" # SQLite 路径
  results_dir: "results"           # 结果目录

# 切块配置
chunk:
  max_tokens: 500                  # 最大 token 数
  table_inline_rows: 3             # 表格内联行数

# 解析配置
parse:
  doc_to_docx_timeout: 60          # DOC 转 DOCX 超时（秒）
  use_mineru: false               # 是否使用 MinerU

# 审核配置
audit:
  dim_concurrency: 8              # 维度并发数

# 向量检索配置
vector:
  model: "text2vec-base-chinese"  # Embedding 模型
  top_k: 5                        # 检索数量
```

### 环境变量（.env）

```bash
# API 配置
OPENAI_API_KEY=sk-xxxxx           # API Key
OPENAI_BASE_URL=https://api.openai.com/v1  # API 地址

# 安全配置
SECRET_KEY=your-secret-key-at-least-32-chars # ≥32 字符

# 调试模式
DEBUG=true
LLM_USE_MOCK=false               # 是否使用 Mock LLM

# 日志级别
LOG_LEVEL=INFO
```

---

## 安全特性

| 特性 | 实现位置 | 说明 |
|------|----------|------|
| **SECRET_KEY 校验** | `app/config.py` | SECRET_KEY < 32 字符拒绝启动 |
| **路径穿越防护** | `app/security.py` | `safe_upload_path()` 防止 `../` 攻击 |
| **CSRF 校验** | `app/auth/deps.py` | `verify_csrf()` 验证 CSRF Token |
| **密码哈希** | `app/auth/core.py` | `hash_password()` 使用 bcrypt |
| **Cookie 安全** | `app/routes/auth_routes.py` | HttpOnly + Secure + SameSite |
| **CORS 白名单** | `app/config.py` | `check_cors_prod()` 显式白名单 |
| **WebSocket 限速** | `app/routes/ws.py` | `_check_ws_rate()` 限制连接频率 |

---

## 输出格式

### 审核结果 JSON

```json
{
  "doc_id": "作业指导书_2024_001",
  "doc_name": "管道巡护作业指导书.docx",
  "scenario": "s1",
  "review_timestamp": "2024-01-15T10:30:00",
  "overall_verdict": "partial",
  "overall_score": 78,
  "raw_score": 102,
  "max_score": 132,
  "dimensions": {
    "C1_structure_completeness": {
      "verdict": "pass",
      "score": 12,
      "confidence": 95,
      "findings": []
    },
    "C2_content_completeness": {
      "verdict": "partial",
      "score": 8,
      "confidence": 85,
      "findings": [
        {
          "severity": "medium",
          "description": "应急响应流程描述不完整",
          "evidence": "...",
          "section_path": "5.2"
        }
      ]
    }
  },
  "audit_report": {
    "overall_opinion": "文档存在 3 项待改进之处，建议按建议优化后可投入使用。",
    "critical_issues": ["应急响应流程缺少关键联系人"],
    "recommendations": ["补充应急联系人信息"]
  },
  "navigation": {
    "sections": [
      {"path": "1", "title": "目的与范围"},
      {"path": "2", "title": "作业步骤"}
    ],
    "total_sections": 12
  }
}
```

### 打标结果 JSON（赛题格式）

```json
{
  "metadata": {
    "doc_id": "...",
    "scenario": "s1",
    "pipeline": "label",
    "timestamp": "..."
  },
  "dimensions": {
    "C1_structure_completeness": {
      "verdict": "pass",
      "score": 12,
      "standards": {
        "C1.required_modules": {
          "verdict": "pass",
          "findings": []
        }
      }
    }
  }
}
```

---

## 部署指南

### 生产环境部署

```bash
# 1. 打包前端
cd frontend && npm run build

# 2. 一键安装（需 root 权限）
sudo bash deploy/install.sh your-domain.com admin@email.com

# 脚本自动完成：
# - Python 虚拟环境创建
# - Let's Encrypt 证书申请
# - Nginx 反向代理配置
# - systemd 服务配置（开机自启）
# - 防火墙规则配置
```

### Docker 部署（可选）

```bash
# 构建镜像
docker build -t industry-agent .

# 运行容器
docker run -d -p 8001:8001 -p 5173:80 \
  -e SECRET_KEY=your-secret-key \
  -e OPENAI_API_KEY=sk-xxxxx \
  industry-agent
```

### 目录权限

```bash
# 确保数据目录可写
chmod 755 data/
chmod 755 data/images/
chmod 755 results/
```

---

## 目录结构总览图
```
industry-demo/
│
├── backend/                     # Python FastAPI 后端
│   ├── app/                     # Web 层（路由/鉴权/WebSocket）
│   │   ├── auth/                # 认证模块
│   │   ├── routes/              # API 路由
│   │   └── main.py              # 入口
│   │
│   ├── src/                     # 核心引擎
│   │   ├── agents/              # 11 维度 Agent
│   │   │   ├── scene1/          # 场景一（C1-C5, E1-E2, L2）
│   │   │   └── scene2/          # 场景二（I1-I8, L1-L6）
│   │   ├── pipeline/            # Pipeline
│   │   │   ├── audit.py         # 审核 Pipeline
│   │   │   ├── scenario_router.py
│   │   │   └── image_pipeline.py # s2 审核图片/多模态流程（audit）
│   │   ├── harness/            # 打标引擎（2+1，仅 label）
│   │   │   ├── agent_group/    # Explorer/Critic/SubAgent
│   │   │   └── pipeline/
│   │   ├── llm/                 # LLM 集成
│   │   ├── store/              # SQLite 存储
│   │   └── parse/              # 文档解析
│   │
│   └── config/
│       └── default.yaml         # 默认配置
│
├── frontend/                    # React + TypeScript 前端
│   ├── src/
│   │   ├── pages/              # 页面组件
│   │   ├── components/         # 通用组件
│   │   └── api/                # API 客户端
│   └── src-tauri/              # Tauri 桌面端
│
└── deploy/                      # 部署脚本
    └── install.sh               # 一键安装脚本
```
