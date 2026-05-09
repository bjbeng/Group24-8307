# IndustryAgent — Prompt 指南

本文件分两部分：
1. **项目上下文 Prompt**：粘贴给任意 LLM，让它立刻理解本项目背景，可直接开始协作。
2. **如何为本项目生成 Prompt**：针对不同任务（实现 Agent、调 Debug、写测试等）的 prompt 构造方法。

---

## 一、项目上下文 Prompt（粘贴即用）

将以下内容完整粘贴到 LLM 对话的第一条消息，之后的问题它都能准确定位到本项目。

```
【项目背景】
IndustryAgent 是一个面向油气管道行业的工业文档智能审核系统，
基于多 Agent 架构，支持两个场景：
  - 场景一（s1）：作业指导书文本审核
  - 场景二（s2）：高后果区风险管控方案多模态审核（文本 + 示意图）

技术栈：Python 3.12、FastAPI、SQLite、React + Vite、Tauri（可选桌面端）

【两种运行模式】

1. 审核模式（audit）
   - 入口：uvicorn app.main:app  /  python -m src.cli audit doc.docx
   - 架构：单个 LLM Provider → 8 个维度 Agent 并行（ThreadPoolExecutor）→ 汇总
   - 有 Web 前端，支持上传文档、WebSocket 实时进度

2. 打标模式（label，2+1 架构）
   - 入口：python -m src.cli label doc.docx --scenario s1
   - 架构：Explorer A（temperature=0.2）‖ Explorer B（temperature=0.0）并发
           → CrossDimensionCritic 仲裁分歧 → 写入 GT 标签库
   - 无前端，纯 CLI，输出 JSON

【维度体系（场景一，共 11 维度）】
  C1 结构完整性        — 章节/目录/标题层级（规则+LLM）
  C2 内容完整性        — 安全措施/风险识别/操作步骤覆盖度
  C3 语言规范          — 术语/用语/歧义（+标准库 RAG）
  C4 引用一致性        — 文内引用（图表/附件/章节）是否悬空
  C5 逻辑一致性        — LangGraph 多步推理，检查前后矛盾
  E1 人员配备合规      — 人员数量与管道里程比核算
  E2 应急措施完整性    — 应急预案要素覆盖（+标准库 RAG）
  L2 标准遵从          — 检索行业标准库（GB/QSY/SY/T）
  T1 处理时长          — 规则推导，不调 LLM
  T2 格式合规          — 规则推导
  T3 文件完整性        — 规则推导

【核心数据结构】

# 单维度审核结果
@dataclass
class AgentResult:
    dimension: str
    verdict: str          # "pass" | "partial" | "fail" | "uncertain"
    score: int | None     # 0-12，None 表示未评分
    confidence: int       # 0-100
    findings: list[Finding]
    details: str
    extra: dict
    need_human_review: bool

@dataclass
class Finding:
    severity: str         # "high" | "medium" | "low"
    description: str
    evidence: str
    rule_id: str | None
    chunk_id: str | None
    section_path: str     # 如 "3.2.1"
    paragraph_index: int  # 文档中段落顺序

【如何新增一个场景一 Agent（最小实现）】
  # 1. 继承 BaseAgent
  class MyNewAgent(BaseAgent):
      dimension = "XX_my_check"

      def run(self, chunks: list[dict]) -> AgentResult:
          # chunks 是文档切块列表，每块包含：
          #   chunk_id, doc_id, content, block_type, heading_path, paragraph_index
          excerpt = "\n".join(c["content"] for c in chunks[:20])
          raw = self.provider.call_text(
              [Message(role="system", content="你是审核专家..."),
               Message(role="user", content=excerpt)],
              model=self.text_model,
              temperature=self.temperature,
              max_tokens=800,
          )
          data = parse_json_response(raw)
          return agent_result_from_llm_json(data, dimension=self.dimension, max_score=12)

  # 2. 在 src/pipeline/audit.py 的 _build_agents() 里注册：
  MyNewAgent(self.provider, text_model),

【Critic 仲裁规则（2+1 打标）】
  A = B（verdict 相同）→ 取平均置信度，合并 findings（去重）
  A ≠ B（高分歧）→ 先规则选保守侧（fail > partial > uncertain > pass），
                    若分歧维度 ≤6 个则额外调 LLM（critic_model）复核
  跨维度矛盾（如 C1 pass 但 C4 严重失败）→ 降低置信度 -15，标 need_human_review

【LLM 调用约定】
  self.provider.call_text(messages, model=..., temperature=..., max_tokens=...)
  self.provider.call_vision(image_path=..., prompt=..., model=...)  # 场景二
  所有 Agent 要求 LLM 只输出 JSON（不要代码围栏），用 parse_json_response() 解析

【Mock 模式】
  backend/.env 设置 LLM_USE_MOCK=true，无需 API Key，直接本地测试
```

---

## 二、如何为本项目生成 Prompt

### 2.1 通用公式

```
[角色定位] + [项目上下文（从第一部分粘贴）] + [具体任务] + [输出格式要求]
```

良好的 prompt = 让 LLM **知道它在哪里、要做什么、交付什么格式**。

---

### 2.2 任务模板库

#### ▶ 实现一个新的维度 Agent

```
[粘贴第一部分的项目上下文]

现在请帮我实现场景一的 [维度名] Agent。

审核目标：[用 1-2 句话描述这个维度要检查什么]
关键词列表：[与该维度相关的中文关键词，用于过滤 chunks]
评分说明：12=完全合规，8-11=小问题，4-7=较多缺陷，0-3=严重不足

要求：
- 继承 BaseAgent，dimension = "[XX_name]"
- 用 collect_excerpt(chunks, KEYWORDS, max_chars=4000) 提取相关段落
- system prompt 要具体说明检查项（至少 4 条）
- 调用 agent_result_from_llm_json() 返回 AgentResult
- 文件放在 backend/src/agents/[文件名].py
```

---

#### ▶ 实现场景二视觉 Agent

```
[粘贴第一部分的项目上下文]

请为场景二实现 [I1/I2/.../I6] 的视觉 Agent。

图片类型：[图片名称，如"紧急疏散路线示意图"]
这类图片应该包含哪些要素：[列举 5-8 项，用中文描述]

要求：
- 继承 BaseImageAgent，填写 dimension 和 checklist
- checklist 每项格式：英文字段名（中文说明）
- 如需自定义 prompt（如手写识别），覆写 _analyze_image()
- 文件：backend/src/agents/scene2/image_agents.py
```

---

#### ▶ Debug 一个 Agent 输出异常

```
[粘贴第一部分的项目上下文]

我在运行 [维度名] Agent 时遇到以下问题：

错误信息/异常行为：
[粘贴报错或异常输出]

相关代码（backend/src/agents/[文件].py）：
[粘贴出问题的函数代码]

LLM 返回的原始文本：
[粘贴 raw 变量内容]

请分析：
1. parse_json_response() 失败的原因
2. AgentResult 字段填充是否有问题
3. 给出修复建议
```

---

#### ▶ 为 Agent 写单元测试

```
[粘贴第一部分的项目上下文]

请为以下 Agent 写 pytest 单元测试：

[粘贴 Agent 代码]

要求：
- 用 Mock LLM Provider（不调真实 API）
- 至少覆盖：正常 pass、有 findings 的 partial、chunks 为空的 uncertain 三个分支
- 断言 AgentResult 的 verdict、score、confidence、findings 字段
- 文件放在 backend/tests/test_agents/test_[维度名].py
- 用 pytest.mark.parametrize 参数化多个 case
```

---

#### ▶ 调优 Critic 仲裁逻辑

```
[粘贴第一部分的项目上下文]

我观察到 Critic 在以下情况下仲裁结果不稳定：
[描述具体场景，如"C3 维度 A=partial B=pass 时频繁选错"]

相关代码（backend/src/harness/agent_group/critic.py）：
[粘贴 _merge_two 或 _llm_arbitrate 函数]

Explorer A 输出：
[JSON]

Explorer B 输出：
[JSON]

期望的仲裁结果：[描述你认为正确的结论和理由]

请分析规则仲裁的逻辑是否合理，并提出改进方案。
```

---

#### ▶ 扩展标准库（RAG 检索增强）

```
[粘贴第一部分的项目上下文]

请帮我为 L2/E2/C3 等依赖 RAG 的 Agent 新增标准条目。

标准文本（来源：[标准编号/名称]）：
[粘贴原文片段]

要求：
1. 将条目添加到 backend/src/agents/standards_seed.py 的 DEMO_STANDARDS 列表
2. 格式：{"std_id": "...", "title": "...", "content": "...", "dimension": "..."}
3. dimension 字段应与调用该标准的 Agent 维度名一致
4. content 控制在 500 字以内，去掉表格头、页眉页脚等噪声
```

---

### 2.3 提示词质量自检清单

写完 prompt 后，对照以下问题检查：

| 检查项 | 说明 |
|--------|------|
| 有没有粘贴项目上下文？ | 不粘贴，LLM 不知道 BaseAgent/AgentResult 的接口 |
| 有没有说明输出格式？ | 要 Python 代码还是 JSON 还是纯文字分析 |
| 有没有提供具体的代码/错误文本？ | 越具体越准确，避免"参考上面的代码"这种指代 |
| 任务是否单一？ | 一个 prompt 只做一件事（实现 OR 测试 OR debug） |
| 有没有说明文件放哪里？ | 明确路径，LLM 生成的代码才能直接使用 |

---

### 2.4 生成 Prompt 的 Prompt（元 Prompt）

如果你想让 LLM 帮你写针对本项目的 prompt，可以这样说：

```
你是一名熟悉 IndustryAgent 项目的工程师。
[粘贴第一部分的项目上下文]

我想完成的任务是：[用一句话描述，如"实现 C5 逻辑一致性 Agent"]

请帮我生成一个高质量的 prompt，要求：
1. 包含必要的项目上下文（只保留与任务相关的部分）
2. 给出清晰的输入/输出约定
3. 包含至少 3 个具体的实现约束
4. 结尾注明生成代码的目标文件路径
```
