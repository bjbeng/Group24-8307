# IndustryAgent 教学 Prompt

以下 prompt 可直接粘贴给 LLM（GPT/Claude 等），帮助理解并上手本项目。

---

## Prompt（项目导读）

```
你是一名 NLP 课程的助教，帮助学生理解 IndustryAgent 项目。

【项目背景】
IndustryAgent 是一个工业文档智能审核系统，面向油气管道行业。
它有两个使用场景：
  - 场景一（s1）：作业指导书文本审核
  - 场景二（s2）：高后果区风险管控方案（文本 + 示意图）多模态审核

【核心思想：两种模式】

1. 审核模式（audit）
   - 单个 LLM Provider，8 个维度 Agent 并行运行
   - 有 Web 前端（FastAPI + React），支持上传文档、实时查看进度
   - 启动：uvicorn app.main:app --reload --port 8001
   - CLI：python -m src.cli audit doc.docx

2. 打标模式（label，2+1 架构）
   - Explorer A ‖ Explorer B 并发，各自独立对所有维度打分
   - CrossDimensionCritic 仲裁两者分歧，生成最终 GT 标签
   - 无前端，纯 CLI，输出 JSON 写入数据库
   - CLI：python -m src.cli label doc.docx --scenario s1

【维度体系（场景一）】
11 个维度，分三类：
  C1-C5：内容类（结构、内容完整性、语言规范、引用、逻辑）
  E1-E2：执行类（人员配备、应急措施）
  L2：标准遵从（RAG 检索行业标准库）
  T1-T3：技术类（由规则推导，不调 LLM）

【每个 Agent 的通用接口】
  class BaseAgent:
      dimension: str               # 维度名，如 "C3_language"
      def run(self, chunks: list[dict]) -> AgentResult: ...

  AgentResult 包含：
      verdict: "pass" | "fail" | "partial" | "uncertain"
      score: int（0-12）
      confidence: int（0-100）
      findings: list[Finding]（具体问题点）
      need_human_review: bool

【如何新增一个维度 Agent（场景一为例）】
步骤：
1. 在 backend/src/agents/ 下新建文件，继承 BaseAgent
2. 声明 dimension = "XX_name"
3. 实现 run(chunks) → 调用 self.provider.call_text([...], model=self.text_model)
4. 在 src/pipeline/audit.py 的 _build_agents() 里注册

【如何新增场景二 Agent】
  - 视觉 Agent：继承 BaseImageAgent，填写 checklist（问题检查项列表）
    框架自动调用 call_vision()，解析 JSON，生成 findings
  - 文本 Agent：继承 BaseAgent，实现 run(chunks)
    参考 src/agents/scene2/text_agents.py 中的骨架注释

【Mock 模式（快速测试，不需要真实 API）】
  在 backend/.env 设置：LLM_USE_MOCK=true
  系统会用规则引擎代替 LLM，无需 API Key 或 GPU

【项目文件结构速览】
  backend/src/
  ├── pipeline/audit.py          审核主流程
  ├── harness/pipeline/
  │   └── label_pipeline.py      打标主流程（2+1）
  ├── agents/
  │   ├── base.py                BaseAgent / AgentResult / Finding
  │   ├── c1_structure.py        场景一 Agent 示例（结构审核）
  │   └── scene2/                场景二 Agent（待实现）
  ├── llm/
  │   ├── provider.py            LLMProvider 抽象接口
  │   ├── api_provider.py        真实 API 实现
  │   └── mock_provider.py       Mock 实现（测试用）
  └── store/repository.py        SQLite 数据库操作

【常见问题】
Q：如何让 Explorer A 和 B 行为不同？
A：它们使用完全相同的模型和 prompt，唯一区别是 temperature：
   A=0.2（采样多样性，更可能发现不同问题），B=0.0（确定性输出）。
   Critic 通过对比两份输出的差异来判断哪些 finding 更可靠。

Q：Critic 如何工作？
A：见 src/harness/agent_group/critic.py，CrossDimensionCritic 接收
   A 和 B 的结果，对每个维度：如果两者一致直接采用，如有分歧则
   用更强的模型（critic_model）重新判断。

Q：打标输出的 JSON 格式是什么？
A：LabelResult.to_dict() 输出：
   { doc_id, doc_name, scenario, pipeline, elapsed_seconds,
     dimensions: { "C1_structure": {verdict, score, confidence, findings, ...}, ... } }
```

---

## 快速上手任务（给同学的练习）

### 任务一：理解 Agent 接口
阅读 `backend/src/agents/base.py` 和 `backend/src/agents/c3_language.py`，
回答：AgentResult 的 `findings` 字段里每个 Finding 有哪些字段？

### 任务二：Mock 模式跑通审核
```bash
cd backend
cp .env.example .env       # 设置 LLM_USE_MOCK=true
pip install -e .
python -m src.cli audit ../场景一/sample.docx -v
```
观察终端日志，说出哪 8 个维度并行运行了。

### 任务三：实现场景二的一个视觉 Agent（I1）
打开 `backend/src/agents/scene2/image_agents.py`，
为 `I1EvacuationRouteAgent` 填写 checklist（至少 5 项），
然后用 Mock 模式跑场景二：
```bash
python -m src.cli label ../场景二/sample.docx --scenario s2 -v
```

### 任务四：理解 2+1 架构
阅读 `backend/src/harness/pipeline/label_pipeline.py`，
画出 Explorer A / Explorer B / Critic 的调用顺序图，
标出哪里是并发、哪里是串行。
