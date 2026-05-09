# 快速启动指南

## 目录结构

```
industry-demo/
├── backend/
│   ├── app/           Web 层（FastAPI 路由、鉴权、WebSocket）
│   ├── src/
│   │   ├── pipeline/
│   │   │   ├── audit.py          审核 pipeline（单 LLM，有 Web 前端）
│   │   │   └── label.py          旧版打标（已弃用，保留兼容）
│   │   ├── harness/pipeline/
│   │   │   └── label_pipeline.py 打标 pipeline（2+1 Agent，CLI 专用）
│   │   └── agents/               11 维度 Agent（C1-C5, E1-E2, L2, T1-T3）
│   └── src/cli.py     命令行入口（audit / label）
├── frontend/          React + Vite + TypeScript
│   └── src-tauri/     Tauri v2 Windows .exe（可选）
└── deploy/            Nginx + systemd + HTTPS
```

---

## 两种模式说明

| 模式 | 启动方式 | Agent 架构 | 前端 | 输出 |
|------|----------|-----------|------|------|
| **审核** | `uvicorn` 或 `cli audit` | 单 LLM Provider，8 维度并行 | 有 | JSON + Web |
| **打标** | `cli label` | 2+1（Explorer A ‖ B → Critic） | 无 | GT JSON |

---

## 本地开发（3 步启动）

### 1. 后端

```bash
cd backend
cp .env.example .env
# 编辑 .env：设置 SECRET_KEY（≥32字符），LLM_USE_MOCK=true 可跳过 API Key
python -m venv venv
venv\Scripts\activate         # Windows
# source venv/bin/activate    # macOS/Linux
pip install -e .
uvicorn app.main:app --reload --port 8001
```

访问 http://localhost:8001/health 确认运行。

### 2. 前端

```bash
cd frontend
cp .env.example .env          # VITE_API_BASE=http://localhost:8001
npm install
npm run dev                   # http://localhost:5173
```

### 3. Mock 模式（无需真实 API Key）

`.env` 中设置 `LLM_USE_MOCK=true`，直接跑规则维度，无需 GPU 或 API 账号。

---

## CLI 打标（2+1 Agent，不启动前端）

```bash
cd backend

# 场景一：作业书（文本）
python -m src.cli label path/to/doc.docx --scenario s1

# 场景二：风险管控方案（文本 + 图片）
python -m src.cli label path/to/doc.docx --scenario s2

# 指定输出路径 + 详细日志
python -m src.cli label path/to/doc.docx --scenario s1 --out results/out.json -v
```

打标输出为 JSON，写入 `labels` 表（`pipeline="label"`），`human_signoff=false` 表示待人工签字确认为 GT。

## CLI 审核（单 LLM，不启动前端）

```bash
cd backend
python -m src.cli audit path/to/doc.docx
```

---

## 生产部署（Ubuntu VPS）

```bash
# 1. 前端打包
cd frontend && npm run build

# 2. 一键部署
sudo bash deploy/install.sh your-domain.com admin@your-domain.com
```

脚本自动完成：
- 安装 Python 虚拟环境
- 生成随机 SECRET_KEY
- 申请 Let's Encrypt 证书（HTTPS）
- 配置 Nginx 反代
- 注册 systemd 服务（开机自启）

---

## API 快速参考

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/login` | 登录（设置 httponly cookie） |
| POST | `/api/upload` | 上传文档（需 X-CSRF-Token） |
| POST | `/api/audit/start` | 启动单文档审核 |
| GET  | `/api/audit/{task_id}` | 查询审核状态/结果 |
| POST | `/api/audit/batch` | 批量审核 |
| WS   | `/ws/audit/{task_id}` | 实时进度推送 |
| GET  | `/api/rules` | 查看审核规则集 |
| POST | `/api/rules` | 创建规则集 |

---

## Tauri Windows .exe

```bash
cd frontend
npm run tauri build
# 输出：src-tauri/target/release/bundle/
```

权限已收紧到 `core:default`（无 shell/fs 访问）。

---

## 安全特性

| 特性 | 实现位置 |
|------|----------|
| SECRET_KEY < 32 拒绝启动 | `app/config.py:check_secret_key` |
| 路径穿越防护 | `app/security.py:safe_upload_path` |
| 鉴权统一依赖 | `app/auth/deps.py:current_user` |
| CSRF 校验 | `app/auth/deps.py:verify_csrf` |
| bcrypt 密码哈希 | `app/auth/core.py:hash_password` |
| Cookie HttpOnly+Secure | `app/routes/auth_routes.py` |
| CORS 显式列表 | `app/config.py:check_cors_prod` |
| WS 速率限制 | `app/routes/ws.py:_check_ws_rate` |
| Secret 扫描 Hook | `8307-Group/src/harness/hooks/built_in.py` |
