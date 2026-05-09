export type Lang = "zh" | "en";

export interface TranslationKeys {
  // Nav
  nav_upload: string;
  nav_history: string;
  nav_batch: string;
  nav_rules: string;
  nav_monitor: string;
  // App title
  app_title: string;
  // User
  logged_in: string;
  logout: string;
  // Status
  pending: string;
  running: string;
  done: string;
  failed: string;
  // Audit result
  audit_overview: string;
  doc_name: string;
  audit_complete: string;
  audit_time: string;
  risk_dist: string;
  total_score: string;
  module_content: string;
  module_deep: string;
  module_template: string;
  pass_dims: string;
  problem_list: string;
  all: string;
  serious_only: string;
  content_audit: string;
  deep_audit: string;
  template_audit: string;
  no_issue_found: string;
  no_problem: string;
  check_pass: string;
  check_pass_with_issues: string;
  check_fail: string;
  need_human_review: string;
  export_pdf: string;
  export_annotated: string;
  locate_doc: string;
  dimension: string;
  evidence: string;
  position: string;
  serious: string;
  medium: string;
  low: string;
  items: string;
  // Filters
  filter_all: string;
  filter_serious: string;
  filter_content: string;
  filter_deep: string;
  filter_template: string;
  filter_scene2_visual: string;
  filter_scene2_text: string;
  filter_scene2_risk: string;
  // Dimension names
  dim_C1: string;
  dim_C2: string;
  dim_C3: string;
  dim_C4: string;
  dim_C5: string;
  dim_E1: string;
  dim_E2: string;
  dim_L1: string;
  dim_L2: string;
  dim_L3: string;
  dim_L4: string;
  dim_L5: string;
  dim_L6: string;
  dim_I1: string;
  dim_I2: string;
  dim_I3: string;
  dim_I4: string;
  dim_I5: string;
  dim_I6: string;
  dim_I7: string;
  dim_I8: string;
  dim_T1: string;
  dim_T2: string;
  dim_T3: string;
  // Verdict badge
  verdict_pass: string;
  verdict_fail: string;
  verdict_partial: string;
  verdict_uncertain: string;
  // Login page
  login_title: string;
  login_subtitle_login: string;
  login_subtitle_register: string;
  username: string;
  password: string;
  username_placeholder: string;
  password_placeholder: string;
  password_min_8: string;
  login_btn: string;
  register_btn: string;
  processing: string;
  no_account: string;
  has_account: string;
  go_register: string;
  go_login: string;
  password_req: string;
  operation_failed: string;
  // History page
  history_title: string;
  refresh: string;
  loading: string;
  no_history: string;
  go_upload: string;
  col_filename: string;
  col_scenario: string;
  col_status: string;
  col_progress: string;
  col_submit_time: string;
  col_finish_time: string;
  col_actions: string;
  view_result: string;
  view_progress: string;
  confirm_delete: string;
  deleting: string;
  delete_fail: string;
  delete: string;
  unknown_file: string;
  scenario_1: string;
  scenario_2: string;
  // Upload page
  upload_title: string;
  scenario_1_title: string;
  scenario_1_desc: string;
  scenario_2_title: string;
  scenario_2_desc: string;
  drag_or_click: string;
  supported_formats: string;
  uploading: string;
  uploading_hint: string;
  re_upload: string;
  audit_failed: string;
  retry: string;
  audit_in_progress: string;
  audit_pending: string;
  new_audit: string;
  // Batch page
  batch_title: string;
  files_selected: string;
  start_batch: string;
  task_status: string;
  task_id_col: string;
  status_col: string;
  progress_col: string;
  // Rules page
  rules_title: string;
  new_rule_set: string;
  rule_set_id: string;
  create: string;
  json_error: string;
  // Audit status page
  audit_in_progress_title: string;
  waiting: string;
  dimension_complete: string;
  audit_failed_title: string;
  return_reupload: string;
  live_log: string;
  waiting_dispatch: string;
  audit_running_wait: string;
  no_log: string;
  // Monitor page
  monitor_title: string;
  connected: string;
  not_connected: string;
  healthy: string;
  degraded: string;
  critical: string;
  unknown: string;
  monitor_llm: string;
  analyzed_events: string;
  input_token: string;
  output_token: string;
  error_count: string;
  api_cost_estimate: string;
  bottleneck_stage: string;
  avg_time: string;
  recommendations: string;
  stage_avg_time: string;
  event_stream: string;
  clear: string;
  waiting_events: string;
  // Results page
  results_title: string;
  audit_report: string;
  dimension_details: string;
  load_report: string;
  loading_report: string;
  report_load_fail: string;
  score_col: string;
  confidence_col: string;
  part1_content_issues: string;
  part1_desc: string;
  part2_deep_issues: string;
  part2_desc: string;
  part3_template_issues: string;
  part3_desc: string;
  part1_scene2_visual_issues: string;
  part1_scene2_visual_desc: string;
  part2_scene2_text_issues: string;
  part2_scene2_text_desc: string;
  part3_scene2_risk_issues: string;
  part3_scene2_risk_desc: string;
  no_issues_this: string;
  location: string;
  section: string;
  full_text: string;
  // Verdict badge
  badge_pass: string;
  badge_fail: string;
}

const zh: TranslationKeys = {
  nav_upload: "📄 上传审核",
  nav_history: "🕘 审核历史",
  nav_batch: "📋 批量任务",
  nav_rules: "📐 审核规则",
  nav_monitor: "📡 实时监控",
  app_title: "🏭 工业文档审核",
  logged_in: "已登录",
  logout: "退出登录",
  pending: "等待",
  running: "审核中",
  done: "完成",
  failed: "失败",
  audit_overview: "审核概况",
  doc_name: "文档名称",
  audit_complete: "审核完成",
  audit_time: "审核耗时",
  risk_dist: "风险分布",
  total_score: "总分",
  module_content: "内容审核",
  module_deep: "深度审核",
  module_template: "模板检测",
  pass_dims: "通过维度",
  problem_list: "具体问题清单",
  all: "全部",
  serious_only: "仅严重",
  content_audit: "内容审核",
  deep_audit: "深度审核",
  template_audit: "模板检测",
  no_issue_found: "✅ 未发现问题",
  no_problem: "✅ 无问题",
  check_pass: "审核通过",
  check_pass_with_issues: "审核通过（含需整改问题）",
  check_fail: "审核未通过",
  need_human_review: "需人工复核",
  export_pdf: "📥 导出审核报告（PDF）",
  export_annotated: "📝 导出批注版文档",
  locate_doc: "定位到文档",
  dimension: "维度",
  evidence: "证据",
  position: "位置",
  serious: "严重",
  medium: "中等",
  low: "轻度",
  items: "项",
  filter_all: "全部",
  filter_serious: "仅严重",
  filter_content: "内容审核",
  filter_deep: "深度审核",
  filter_template: "模板检测",
  filter_scene2_visual: "图片识别能力",
  filter_scene2_text: "上下文逻辑识别能力",
  filter_scene2_risk: "模板",
  dim_C1: "结构完整性",
  dim_C2: "内容完整性",
  dim_C3: "文字语法",
  dim_C4: "引用可追溯",
  dim_C5: "业务逻辑",
  dim_E1: "人员配备",
  dim_E2: "应急处置",
  dim_L1: "上下文一致性",
  dim_L2: "标准遵从度",
  dim_L3: "必备章节完整",
  dim_L4: "时间逻辑一致",
  dim_L5: "数据逻辑正确",
  dim_L6: "文字模板一致",
  dim_I1: "签字页手签识别",
  dim_I2: "必备图完整性",
  dim_I3: "影像图标注",
  dim_I4: "入场线路标注",
  dim_I5: "逃生路线+集结点",
  dim_I6: "水体敏感图",
  dim_I7: "市政管网交叉图",
  dim_I8: "图文一致性",
  dim_T1: "模板使用",
  dim_T2: "格式兼容",
  dim_T3: "识别效率",
  verdict_pass: "通过",
  verdict_fail: "未通过",
  verdict_partial: "部分通过",
  verdict_uncertain: "不确定",
  login_title: "工业文档审核系统",
  login_subtitle_login: "登录你的账号",
  login_subtitle_register: "创建新账号",
  username: "用户名",
  password: "密码",
  username_placeholder: "请输入用户名",
  password_placeholder: "至少 8 位",
  password_min_8: "至少 8 位",
  login_btn: "登录",
  register_btn: "注册",
  processing: "处理中…",
  no_account: "还没有账号？",
  has_account: "已有账号？",
  go_register: "立即注册",
  go_login: "去登录",
  password_req: "密码要求：至少 8 位，建议包含大小写字母、数字和特殊字符",
  operation_failed: "操作失败，请重试",
  history_title: "审核历史",
  refresh: "刷新",
  loading: "加载中…",
  no_history: "暂无审核历史，去",
  go_upload: "上传文档",
  col_filename: "文件名",
  col_scenario: "场景",
  col_status: "状态",
  col_progress: "进度",
  col_submit_time: "提交时间",
  col_finish_time: "完成时间",
  col_actions: "操作",
  view_result: "查看结果 →",
  view_progress: "查看进度 →",
  confirm_delete: "确认删除这条审核记录？",
  deleting: "删除中…",
  delete_fail: "删除失败",
  delete: "删除",
  unknown_file: "未知文件",
  scenario_1: "场景一",
  scenario_2: "场景二",
  upload_title: "上传文档审核",
  scenario_1_title: "场景一：作业指导书",
  scenario_1_desc: "文本审核（11 个维度）",
  scenario_2_title: "场景二：高后果区方案",
  scenario_2_desc: "多模态审核（文本 + 图片）",
  drag_or_click: "拖放文件到这里",
  supported_formats: "支持 .doc / .docx / .pdf",
  uploading: "上传中…",
  uploading_hint: "上传中…",
  re_upload: "重新上传",
  audit_failed: "审核失败",
  retry: "重新上传",
  audit_in_progress: "审核中…",
  audit_pending: "等待审核开始…",
  new_audit: "＋ 新建审核",
  batch_title: "批量审核",
  files_selected: "已选 {count} 个文件",
  start_batch: "开始批量审核",
  task_status: "任务状态",
  task_id_col: "任务 ID",
  status_col: "状态",
  progress_col: "进度",
  rules_title: "审核规则管理",
  new_rule_set: "新建规则集",
  rule_set_id: "规则集 ID",
  create: "创建",
  json_error: "JSON 格式错误或请求失败",
  audit_in_progress_title: "审核进行中",
  waiting: "等待中",
  dimension_complete: "维度完成（{pct}%）",
  audit_failed_title: "审核失败",
  return_reupload: "返回重新上传",
  live_log: "实时日志",
  waiting_dispatch: "等待任务调度…",
  audit_running_wait: "审核进行中，等待维度结果…",
  no_log: "无日志",
  monitor_title: "全链路实时监控",
  connected: "已连接",
  not_connected: "未连接",
  healthy: "✅ 健康",
  degraded: "⚠️ 降级",
  critical: "🚨 告警",
  unknown: "❓ 未知",
  monitor_llm: "Monitor LLM",
  analyzed_events: "已分析 {count} 条事件",
  input_token: "输入 Token",
  output_token: "输出 Token",
  error_count: "错误次数",
  api_cost_estimate: "API 费用估算",
  bottleneck_stage: "瓶颈阶段",
  avg_time: "平均",
  recommendations: "建议",
  stage_avg_time: "各阶段平均耗时",
  event_stream: "事件流（最近 200 条）",
  clear: "清空",
  waiting_events: "等待事件…上传文档后这里会实时显示各阶段执行状态",
  results_title: "审核结果",
  audit_report: "审核报告",
  dimension_details: "维度详情",
  load_report: "加载审核报告…",
  loading_report: "加载审核报告…",
  report_load_fail: "（无法加载审核报告）",
  score_col: "分数",
  confidence_col: "置信度",
  part1_content_issues: "第一部分：内容审核问题",
  part1_desc: "结构完整性、内容准确性、文字语法、引用文件可追溯性、业务逻辑",
  part2_deep_issues: "第二部分：深度审核问题",
  part2_desc: "人员配备审核、应急处置审核",
  part3_template_issues: "第三部分：模板检测问题",
  part3_desc: "模板使用、格式兼容性、识别效率",
  part1_scene2_visual_issues: "第一部分：图片识别能力",
  part1_scene2_visual_desc: "签字页、必备图、影像图、入场线路、疏散路线集结点、水体敏感图、市政管网交叉图、图文一致性（I1-I8）",
  part2_scene2_text_issues: "第二部分：上下文逻辑识别能力",
  part2_scene2_text_desc: "上下文一致性、标准遵从度、必备章节完整、时间逻辑一致、数据逻辑正确（L1-L5）",
  part3_scene2_risk_issues: "第三部分：模板",
  part3_scene2_risk_desc: "文字模板一致性（L6）",
  no_issues_this: "（本项无问题）",
  location: "位置",
  section: "第 {path} 节",
  full_text: "全文",
  badge_pass: "通过",
  badge_fail: "未通过",
};

const en: TranslationKeys = {
  nav_upload: "📄 Upload & Audit",
  nav_history: "🕘 Audit History",
  nav_batch: "📋 Batch Tasks",
  nav_rules: "📐 Audit Rules",
  nav_monitor: "📡 Live Monitor",
  app_title: "🏭 Industrial Doc Audit",
  logged_in: "Logged in",
  logout: "Logout",
  pending: "Pending",
  running: "Running",
  done: "Done",
  failed: "Failed",
  audit_overview: "Audit Overview",
  doc_name: "Document",
  audit_complete: "Audit Complete",
  audit_time: "Audit Time",
  risk_dist: "Risk Distribution",
  total_score: "Total Score",
  module_content: "Content Audit",
  module_deep: "Deep Audit",
  module_template: "Template Check",
  pass_dims: "Passed Dims",
  problem_list: "Issue Details",
  all: "All",
  serious_only: "Serious Only",
  content_audit: "Content Audit",
  deep_audit: "Deep Audit",
  template_audit: "Template Audit",
  no_issue_found: "✅ No Issues Found",
  no_problem: "✅ No Issues",
  check_pass: "Passed",
  check_pass_with_issues: "Passed (with issues)",
  check_fail: "Failed",
  need_human_review: "Needs Human Review",
  export_pdf: "📥 Export Report (PDF)",
  export_annotated: "📝 Export Annotated Doc",
  locate_doc: "Locate in Doc",
  dimension: "Dimension",
  evidence: "Evidence",
  position: "Position",
  serious: "Serious",
  medium: "Medium",
  low: "Low",
  items: "items",
  filter_all: "All",
  filter_serious: "Serious Only",
  filter_content: "Content Audit",
  filter_deep: "Deep Audit",
  filter_template: "Template Check",
  filter_scene2_visual: "Image Recognition",
  filter_scene2_text: "Context & Logic",
  filter_scene2_risk: "Template",
  dim_C1: "Structural Integrity",
  dim_C2: "Content Completeness",
  dim_C3: "Language & Grammar",
  dim_C4: "Citation Traceability",
  dim_C5: "Business Logic",
  dim_E1: "Staffing",
  dim_E2: "Emergency Response",
  dim_L1: "Context Consistency",
  dim_L2: "Standard Compliance",
  dim_L3: "Required Sections",
  dim_L4: "Time Sequence",
  dim_L5: "Data Logic",
  dim_L6: "Text Template",
  dim_I1: "Signature Page",
  dim_I2: "Required Images",
  dim_I3: "Aerial Image Annotation",
  dim_I4: "Entry Route Annotation",
  dim_I5: "Evacuation Route + Assembly",
  dim_I6: "Water Containment",
  dim_I7: "Municipal Crossing",
  dim_I8: "Image-Text Consistency",
  dim_T1: "Template Usage",
  dim_T2: "Format Compatibility",
  dim_T3: "Recognition Efficiency",
  verdict_pass: "Pass",
  verdict_fail: "Fail",
  verdict_partial: "Partial",
  verdict_uncertain: "Uncertain",
  login_title: "Industrial Doc Audit System",
  login_subtitle_login: "Sign in to your account",
  login_subtitle_register: "Create new account",
  username: "Username",
  password: "Password",
  username_placeholder: "Enter username",
  password_placeholder: "Min 8 characters",
  password_min_8: "Min 8 characters",
  login_btn: "Sign In",
  register_btn: "Register",
  processing: "Processing…",
  no_account: "No account?",
  has_account: "Have an account?",
  go_register: "Register now",
  go_login: "Sign in",
  password_req: "Password: min 8 chars, recommend uppercase + lowercase + number + special char",
  operation_failed: "Operation failed, please retry",
  history_title: "Audit History",
  refresh: "Refresh",
  loading: "Loading…",
  no_history: "No audit history, ",
  go_upload: "upload a document",
  col_filename: "File Name",
  col_scenario: "Scenario",
  col_status: "Status",
  col_progress: "Progress",
  col_submit_time: "Submitted",
  col_finish_time: "Finished",
  col_actions: "Actions",
  view_result: "View Result →",
  view_progress: "View Progress →",
  confirm_delete: "Delete this audit record?",
  deleting: "Deleting…",
  delete_fail: "Delete failed",
  delete: "Delete",
  unknown_file: "Unknown",
  scenario_1: "Scenario 1",
  scenario_2: "Scenario 2",
  upload_title: "Upload & Audit",
  scenario_1_title: "Scenario 1: Work Instruction",
  scenario_1_desc: "Text audit (11 dimensions)",
  scenario_2_title: "Scenario 2: High-Consequence Area",
  scenario_2_desc: "Multi-modal audit (text + images)",
  drag_or_click: "Drop file here",
  supported_formats: "Supports .doc / .docx / .pdf",
  uploading: "Uploading…",
  uploading_hint: "Uploading…",
  re_upload: "Re-upload",
  audit_failed: "Audit Failed",
  retry: "Retry",
  audit_in_progress: "Auditing…",
  audit_pending: "Waiting for audit to start…",
  new_audit: "＋ New Audit",
  batch_title: "Batch Audit",
  files_selected: "{count} files selected",
  start_batch: "Start Batch Audit",
  task_status: "Task Status",
  task_id_col: "Task ID",
  status_col: "Status",
  progress_col: "Progress",
  rules_title: "Audit Rules",
  new_rule_set: "New Rule Set",
  rule_set_id: "Rule Set ID",
  create: "Create",
  json_error: "JSON format error or request failed",
  audit_in_progress_title: "Audit in Progress",
  waiting: "Waiting",
  dimension_complete: "dimensions complete ({pct}%)",
  audit_failed_title: "Audit Failed",
  return_reupload: "Return to Re-upload",
  live_log: "Live Log",
  waiting_dispatch: "Waiting for task scheduling…",
  audit_running_wait: "Audit in progress, waiting for dimension results…",
  no_log: "No log",
  monitor_title: "Full-Chain Real-time Monitor",
  connected: "Connected",
  not_connected: "Disconnected",
  healthy: "✅ Healthy",
  degraded: "⚠️ Degraded",
  critical: "🚨 Critical",
  unknown: "❓ Unknown",
  monitor_llm: "Monitor LLM",
  analyzed_events: "Analyzed {count} events",
  input_token: "Input Tokens",
  output_token: "Output Tokens",
  error_count: "Errors",
  api_cost_estimate: "Est. API Cost",
  bottleneck_stage: "Bottleneck Stage",
  avg_time: "avg",
  recommendations: "Recommendations",
  stage_avg_time: "Stage Avg Time",
  event_stream: "Event Stream (Last 200)",
  clear: "Clear",
  waiting_events: "Waiting for events… Upload a document to see real-time stage status here",
  results_title: "Audit Results",
  audit_report: "Audit Report",
  dimension_details: "Dimension Details",
  load_report: "Loading audit report…",
  loading_report: "Loading audit report…",
  report_load_fail: "(Failed to load audit report)",
  score_col: "Score",
  confidence_col: "Confidence",
  part1_content_issues: "Part 1: Content Audit Issues",
  part1_desc: "Structural integrity, content accuracy, language & grammar, citation traceability, business logic",
  part2_deep_issues: "Part 2: Deep Audit Issues",
  part2_desc: "Staffing review, emergency response review",
  part3_template_issues: "Part 3: Template Check Issues",
  part3_desc: "Template usage, format compatibility, recognition efficiency",
  part1_scene2_visual_issues: "Part 1: Image Recognition",
  part1_scene2_visual_desc: "Signature page, required images, aerial, entry route, evacuation, water containment, municipal crossing, image-text consistency (I1-I8)",
  part2_scene2_text_issues: "Part 2: Context & Logic",
  part2_scene2_text_desc: "Context consistency, standard compliance, required sections, time sequence, data logic (L1-L5)",
  part3_scene2_risk_issues: "Part 3: Template",
  part3_scene2_risk_desc: "Text template consistency (L6)",
  no_issues_this: "(No issues in this section)",
  location: "Location",
  section: "Section {path}",
  full_text: "Full text",
  badge_pass: "Pass",
  badge_fail: "Fail",
};

export const translations: Record<Lang, TranslationKeys> = { zh, en };