from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class WorkspaceOut(WorkspaceCreate):
    id: str
    created_at: datetime


class ProjectCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    scenario: str = Field(default="general", max_length=40)


class ProjectOut(ProjectCreate):
    id: str
    status: str
    is_default: bool
    analysis_brief: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


ClarificationMode = Literal["auto", "always", "off"]


class IntakeQuestion(BaseModel):
    question_key: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=500)
    recommended_default: str = Field(min_length=1, max_length=1000)
    reason: str = Field(default="", max_length=1000)
    affects: list[str] = Field(default_factory=list, max_length=8)


class AnalysisBrief(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    confirmed_keys: list[str] = Field(default_factory=list)
    defaulted_keys: list[str] = Field(default_factory=list)
    asked_keys: list[str] = Field(default_factory=list)
    skill_version: str = "analysis-intake-v1"
    objective_fingerprint: str = ""
    request_summary: str = ""
    updated_at: str = ""


class BriefQuestionsRequest(BaseModel):
    workspace_id: str
    conversation_id: str
    dataset_id: str | None = None
    objective: str = Field(min_length=1, max_length=12_000)
    mode: ClarificationMode | None = None


class AnalysisBriefUpdate(BaseModel):
    workspace_id: str
    conversation_id: str | None = None
    dataset_id: str | None = None
    objective: str = Field(default="", max_length=12_000)
    answers: dict[str, str] = Field(default_factory=dict)
    use_recommended_defaults: bool = False


class IntakeDecision(BaseModel):
    mode: ClarificationMode
    should_pause: bool
    status: Literal["pending", "completed", "not_needed", "disabled"]
    questions: list[IntakeQuestion] = Field(default_factory=list, max_length=8)
    defaults: dict[str, str] = Field(default_factory=dict)
    objective_fingerprint: str = ""
    skill_version: str = "analysis-intake-v1"


class DatasetOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    current_version_id: str | None = None
    name: str
    original_name: str
    size_bytes: int
    profile: dict[str, Any]
    semantics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DatasetSemanticsUpdate(BaseModel):
    workspace_id: str
    unit: str = Field(default="", max_length=80)
    currency: str = Field(default="", max_length=20)
    grain: str = Field(default="", max_length=200)
    date_formats: dict[str, str] = Field(default_factory=dict)
    column_roles: dict[str, Literal["id", "dimension", "measure", "date", "ignore"]] = Field(default_factory=dict)
    column_units: dict[str, str] = Field(default_factory=dict)
    column_labels: dict[str, str] = Field(default_factory=dict)
    value_labels: dict[str, dict[str, str]] = Field(default_factory=dict)


class RelationshipPreviewRequest(BaseModel):
    workspace_id: str
    left_dataset_id: str
    right_dataset_id: str
    left_keys: list[str] = Field(min_length=1, max_length=4)
    right_keys: list[str] = Field(min_length=1, max_length=4)
    join_type: Literal["left", "inner"] = "left"
    right_prefix: str = Field(default="right", min_length=1, max_length=40)


class RelationshipProfile(BaseModel):
    safe: bool
    cardinality: Literal["one_to_one", "many_to_one"]
    join_type: Literal["left", "inner"]
    left_keys: list[str]
    right_keys: list[str]
    left_rows: int
    right_rows: int
    left_distinct_keys: int
    right_distinct_keys: int
    left_duplicate_key_rows: int
    right_duplicate_key_rows: int
    matched_key_count: int
    matched_left_rows: int
    matched_right_rows: int
    unmatched_left_rows: int
    unmatched_right_rows: int
    match_rate: float
    output_rows: int
    right_prefix: str
    right_column_names: dict[str, str]
    non_additive_columns: list[str]
    warnings: list[str]


class RelationshipApplyRequest(RelationshipPreviewRequest):
    name: str = Field(min_length=1, max_length=255)
    acknowledge_non_additive: bool = False


class DatasetRelationshipOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    name: str
    left_dataset_id: str
    right_dataset_id: str
    left_version_id: str
    right_version_id: str
    left_keys: list[str]
    right_keys: list[str]
    join_type: str
    cardinality: str
    right_prefix: str
    profile: RelationshipProfile
    result_dataset_id: str | None = None
    result_dataset: DatasetOut | None = None
    created_at: datetime


class DatasetVersionOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    dataset_id: str
    parent_version_id: str | None
    content_hash: str
    storage_format: str
    size_bytes: int
    row_count: int
    column_schema: list[dict[str, Any]]
    profile: dict[str, Any]
    created_at: datetime


class DataQualityIssue(BaseModel):
    id: str
    severity: Literal["info", "warning", "error"]
    issue_type: str
    title: str
    detail: str
    columns: list[str] = Field(default_factory=list)


class DataQualitySummary(BaseModel):
    score: int
    missing_cells: int
    duplicate_rows: int
    issues: list[DataQualityIssue] = Field(default_factory=list)


class DatasetPreviewOut(BaseModel):
    dataset: DatasetOut
    columns: list[str]
    rows: list[dict[str, Any]]
    offset: int
    limit: int
    total_rows: int
    quality: DataQualitySummary


class CleaningStep(BaseModel):
    operation: Literal[
        "drop_duplicates", "fill_missing", "convert_type", "trim_text",
        "replace_value", "rename_column", "filter_rows",
    ]
    column: str | None = None
    columns: list[str] = Field(default_factory=list)
    method: Literal["constant", "mean", "median", "mode"] | None = None
    value: Any = None
    old_value: Any = None
    new_value: Any = None
    new_name: str | None = None
    target_type: Literal["text", "integer", "float", "date", "boolean"] | None = None
    date_format: str | None = Field(default=None, max_length=80)
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte", "contains", "not_empty"] | None = None


class CleaningPreviewRequest(BaseModel):
    workspace_id: str
    steps: list[CleaningStep] = Field(min_length=1, max_length=30)
    sample_limit: int = Field(default=20, ge=1, le=100)


class CleaningPreviewOut(BaseModel):
    source_dataset_id: str
    before_rows: int
    after_rows: int
    removed_rows: int
    changed_cells: int
    columns: list[str]
    rows: list[dict[str, Any]]
    profile: dict[str, Any]
    quality: DataQualitySummary
    step_results: list[dict[str, Any]]


class CleaningApplyRequest(CleaningPreviewRequest):
    name: str | None = Field(default=None, max_length=255)


class CleaningRecipeOut(BaseModel):
    id: str
    workspace_id: str
    source_dataset_id: str
    result_dataset_id: str
    source_version_id: str | None = None
    result_version_id: str | None = None
    name: str
    steps: list[dict[str, Any]]
    impact: dict[str, Any]
    created_at: datetime


class CleaningApplyOut(BaseModel):
    dataset: DatasetOut
    recipe: CleaningRecipeOut


class Evidence(BaseModel):
    calculation: dict[str, Any] | None = None
    id: str
    statement: str
    method: str
    value: str
    source_columns: list[str] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)
    code: str = ""


class ChartField(BaseModel):
    column: str
    aggregate: str | None = None


ChartType = Literal[
    "bar", "line", "area", "scatter", "bubble", "pie", "donut", "table",
    "highlight_table", "heatmap", "treemap", "histogram", "boxplot", "combo", "kpi",
    "waterfall", "pareto", "control_chart", "gauge", "radar", "density_plot",
]


class ChartStyle(BaseModel):
    """Portable presentation options shared by the report editor and ECharts renderer.

    Extra keys are intentionally retained for backward compatibility with reports created
    before the style contract was formalised.  Renderers must still ignore unknown keys.
    """
    palette: Literal["insight", "business", "risk", "accessible"] = "insight"
    show_legend: bool = True
    show_labels: bool = False
    show_toolbox: bool = True
    show_data_zoom: bool = False
    stack: bool = False
    orientation: Literal["vertical", "horizontal"] = "vertical"
    label_position: Literal["top", "inside", "right"] = "top"
    decimal_places: int = Field(default=2, ge=0, le=6)
    number_format: str = "auto"
    height: int = Field(default=320, ge=120, le=1600)
    unit: str = Field(default="", max_length=80)
    source_label: str = Field(default="", max_length=255)
    dual_axis: bool = False
    show_error_bars: bool = False
    scenario: Literal["auto", "business", "research", "survey"] = "auto"

    model_config = ConfigDict(extra="allow")


class ChartSpec(BaseModel):
    id: str
    title: str
    chart_type: ChartType
    x: ChartField | None = None
    y: ChartField | None = None
    series: list[ChartField] = Field(default_factory=list)
    description: str = ""
    data: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    position: dict[str, int] = Field(default_factory=lambda: {"x": 0, "y": 0, "w": 6, "h": 4})
    style: ChartStyle = Field(default_factory=ChartStyle)


class ChartPatch(BaseModel):
    """A deliberately narrow, server-validated change to one ChartSpec.

    The patch cannot contain raw renderer JavaScript or arbitrary data.  Data is always
    recomputed from the report's immutable dataset by the server.
    """
    title: str | None = Field(default=None, min_length=1, max_length=255)
    chart_type: ChartType | None = None
    x: ChartField | None = None
    y: ChartField | None = None
    series: list[ChartField] | None = Field(default=None, max_length=4)
    description: str | None = Field(default=None, max_length=3000)
    style: ChartStyle | None = None
    limit: int | None = Field(default=None, ge=1, le=200)


class ChartQualityIssue(BaseModel):
    id: str
    severity: Literal["info", "warning", "error"]
    title: str
    detail: str
    suggestion: str = ""


class ChartQualityReport(BaseModel):
    score: int = Field(ge=0, le=100)
    issues: list[ChartQualityIssue] = Field(default_factory=list)


class ChartContextOut(BaseModel):
    report_id: str
    report_title: str
    dataset_id: str
    chart: ChartSpec
    fields: list[dict[str, Any]]
    quality: ChartQualityReport
    report_version_hint: str


class ChartProposalRequest(BaseModel):
    workspace_id: str
    instruction: str = Field(min_length=1, max_length=2000)


class ChartProposalAlternative(BaseModel):
    """One reviewable option for the same immutable chart and dataset."""
    id: str
    label: str = Field(min_length=1, max_length=80)
    patch: ChartPatch
    rationale: list[str] = Field(default_factory=list)


class ChartProposalOut(BaseModel):
    patch: ChartPatch
    rationale: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    alternatives: list[ChartProposalAlternative] = Field(default_factory=list, max_length=3)
    provider: str = "builtin"
    usage: dict[str, Any] | None = None


class ChartPatchPreviewRequest(BaseModel):
    workspace_id: str
    base_version: str
    patch: ChartPatch


class ChartPatchPreviewOut(BaseModel):
    report_id: str
    chart_id: str
    chart: ChartSpec
    data: list[dict[str, Any]]
    quality: ChartQualityReport
    evidence: dict[str, Any]
    base_version: str


class ChartPatchApplyRequest(ChartPatchPreviewRequest):
    approved: Literal[True]


class ReportBlock(BaseModel):
    id: str
    kind: Literal["heading", "paragraph", "insight", "chart", "table", "page_break", "callout"]
    content: str = ""
    chart_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    style: dict[str, Any] = Field(default_factory=dict)


class ReportFinding(BaseModel):
    id: str
    headline: str = Field(min_length=1, max_length=255)
    statement: str = Field(min_length=1, max_length=3000)
    business_impact: str = Field(default="", max_length=2000)
    recommendation: str = Field(default="", max_length=2000)
    confidence: Literal["high", "medium", "low"] = "high"
    caveats: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ReportActionItem(BaseModel):
    id: str
    action: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(default="", max_length=2000)
    priority: Literal["high", "medium", "low"] = "medium"
    owner: str = Field(default="待指定", max_length=120)
    expected_impact: str = Field(default="待验证", max_length=1000)
    validation_metric: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list)


class ClaimValue(BaseModel):
    role: str = Field(max_length=80)
    value: float
    unit: str = Field(default="", max_length=40)


class ReportClaim(BaseModel):
    """Server-owned facts that remain stable when prose is legitimately rewritten."""
    id: str
    target_kind: Literal["summary", "finding", "block"]
    target_id: str
    claim_type: Literal["fact", "inference", "recommendation", "assumption"] = "fact"
    operation: str = ""
    metric: str = ""
    dimension: str = ""
    member: str = ""
    periods: list[str] = Field(default_factory=list)
    required_terms: list[str] = Field(default_factory=list)
    values: list[ClaimValue] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ReportQualityIssue(BaseModel):
    id: str
    severity: Literal["info", "warning", "error"]
    title: str
    detail: str
    suggestion: str = ""


class ReportQualityReport(BaseModel):
    claim_checks: list[dict[str, Any]] = Field(default_factory=list)
    score: int = Field(ge=0, le=100)
    passed: bool
    issues: list[ReportQualityIssue] = Field(default_factory=list)
    checked_at: str = ""
    version: str = "report-quality-v2"


class ReportDocument(BaseModel):
    version: Literal["1.0", "2.0"] = "2.0"
    title: str
    summary: str
    blocks: list[ReportBlock]
    charts: list[ChartSpec]
    evidence: list[Evidence]
    findings: list[ReportFinding] = Field(default_factory=list)
    actions: list[ReportActionItem] = Field(default_factory=list)
    claims: list[ReportClaim] = Field(default_factory=list)
    quality: ReportQualityReport | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisRequest(BaseModel):
    workspace_id: str
    dataset_id: str
    prompt: str = Field(default="请分析这份数据并生成一份可编辑报告。", max_length=4000)
    report_title: str | None = Field(default=None, max_length=255)


class AnalysisResult(BaseModel):
    report_id: str
    document: ReportDocument
    execution_mode: Literal["deterministic", "sandbox"]


class ChartPreviewRequest(BaseModel):
    workspace_id: str
    x_column: str | None = None
    y_column: str | None = None
    aggregate: Literal["sum", "avg", "count", "min", "max"] = "sum"
    series_columns: list[str] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=20, ge=1, le=200)


class ChartPreviewResult(BaseModel):
    data: list[dict[str, Any]]


class ReportOut(BaseModel):
    deleted_at: datetime | None = None
    id: str
    workspace_id: str
    project_id: str | None = None
    dataset_id: str | None
    dataset_version_id: str | None = None
    run_id: str | None = None
    title: str
    document: ReportDocument
    created_at: datetime
    updated_at: datetime


class ReportUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    document: ReportDocument


class ReportCreate(BaseModel):
    workspace_id: str
    title: str = Field(default="未命名报告", min_length=1, max_length=255)
    dataset_id: str | None = None
    source_report_id: str | None = None


class ReportRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ReportLayoutRequest(BaseModel):
    workspace_id: str


class ReportLayoutProposal(BaseModel):
    chart_id: str
    title: str
    position: dict[str, int]
    reason: str


class ReportLayoutProposalOut(BaseModel):
    report_id: str
    proposals: list[ReportLayoutProposal]
    summary: str


class ReportLayoutApplyRequest(ReportLayoutRequest):
    proposals: list[ReportLayoutProposal] = Field(min_length=1, max_length=100)
    approved: Literal[True]


class ReportVersionOut(BaseModel):
    id: str
    report_id: str
    title: str
    document: ReportDocument
    created_at: datetime


class SqlRunRequest(BaseModel):
    workspace_id: str
    sql: str = Field(min_length=1, max_length=20_000)
    max_rows: int = Field(default=200, ge=1, le=2000)


class SqlRunOut(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    evidence: Evidence


class PythonRunRequest(BaseModel):
    workspace_id: str
    code: str = Field(min_length=1, max_length=40_000)
    timeout_seconds: int = Field(default=20, ge=1, le=60)


class PythonRunOut(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


class AnalysisCapabilities(BaseModel):
    deep_analysis: bool = False
    max_rounds: int = Field(default=1, ge=1, le=3)
    content_review: bool = True
    chart_layout: bool = True
    alternatives: bool = False


class ConversationCreate(BaseModel):
    workspace_id: str
    dataset_id: str | None = None
    title: str = Field(default="新分析", min_length=1, max_length=160)
    clarification_mode: ClarificationMode = "auto"
    analysis_capabilities: AnalysisCapabilities = Field(default_factory=AnalysisCapabilities)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    clarification_mode: ClarificationMode | None = None
    analysis_capabilities: AnalysisCapabilities | None = None


class ConversationOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    dataset_id: str | None
    title: str
    archived: bool
    clarification_mode: ClarificationMode = "auto"
    analysis_capabilities: AnalysisCapabilities = Field(default_factory=AnalysisCapabilities)
    created_at: datetime
    updated_at: datetime


class TokenUsageTotals(BaseModel):
    prompt_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0


class TokenUsageGroup(TokenUsageTotals):
    key: str


class TokenUsageItem(TokenUsageTotals):
    id: str
    conversation_id: str | None = None
    plan_id: str | None = None
    run_id: str | None = None
    report_id: str | None = None
    dashboard_id: str | None = None
    stage: str
    purpose: str
    provider: str
    model: str
    request_id: str
    latency_ms: int
    status: str
    usage_unavailable: bool
    created_at: datetime


class TokenUsageSummary(BaseModel):
    workspace_id: str
    range: Literal["today", "7d", "all"]
    group_by: Literal["stage", "model", "run", "report", "dashboard"]
    totals: TokenUsageTotals
    groups: list[TokenUsageGroup]
    unavailable_call_count: int
    latest: list[TokenUsageItem]


class ChatMessageOut(BaseModel):
    id: str
    conversation_id: str
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    message_meta: dict[str, Any]
    created_at: datetime


class ChatRequest(BaseModel):
    workspace_id: str
    conversation_id: str
    message: str = Field(min_length=1, max_length=12_000)
    dataset_id: str | None = None
    analysis_mode: Literal[
        "auto", "explore", "deep", "cleaning", "business", "research", "survey", "professional",
    ] = "auto"
    analysis_options: "AnalysisOptions" = Field(default_factory=lambda: AnalysisOptions())


class ForecastOptions(BaseModel):
    enabled: bool = False
    date_column: str | None = Field(default=None, max_length=255)
    target_column: str | None = Field(default=None, max_length=255)
    horizon: int = Field(default=6, ge=1, le=36)
    frequency: Literal["D", "W", "MS", "QS"] = "MS"
    aggregate: Literal["sum", "mean"] = "sum"


class ReportRequirements(BaseModel):
    depth: Literal['auto','brief','standard','detailed'] = 'auto'
    focus: Literal['auto','general','loss','hourly','reconciliation'] = 'auto'
    audience: Literal['auto','manager','analyst'] = 'auto'
    exclude_trend: bool = False
    exclude_forecast: bool = False
    must_include: str = Field(default='', max_length=1000)
    must_exclude: str = Field(default='', max_length=1000)


class AnalysisOptions(BaseModel):
    report_requirements: ReportRequirements = Field(default_factory=ReportRequirements)
    capabilities: AnalysisCapabilities = Field(default_factory=AnalysisCapabilities)
    include_recommendations: bool = False
    include_report: bool = False
    show_code: bool = True
    template_id: str | None = Field(default=None, max_length=36)
    forecast: ForecastOptions = Field(default_factory=ForecastOptions)


class AnalysisPlanStep(BaseModel):
    id: str
    title: str
    description: str
    tool: str
    risk: Literal["low", "medium", "high"] = "low"
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolPolicyDecision(BaseModel):
    tool: str
    decision: Literal["allow", "approval", "forbid"]
    reason: str


class AnalysisPlan(BaseModel):
    report_requirements: ReportRequirements = Field(default_factory=ReportRequirements)
    id: str
    objective: str
    dataset_id: str | None = None
    analysis_mode: Literal[
        "auto", "explore", "deep", "cleaning", "business", "research", "survey", "professional",
    ] = "auto"
    mode_reason: str = ""
    status: Literal["pending", "running", "completed", "cancelled", "failed"] = "pending"
    execution_mode: Literal["safe", "partial", "full"] = "safe"
    requires_approval: bool = True
    blocked: bool = False
    policy: list[ToolPolicyDecision] = Field(default_factory=list)
    steps: list[AnalysisPlanStep]


class ChatPlanRequest(ChatRequest):
    idempotency_key: str | None = Field(default=None,min_length=1,max_length=100)
    # Present only when the user asks to change the chart currently selected in the editor.
    # These references are validated server-side and never grant access outside the workspace.
    report_id: str | None = None
    chart_id: str | None = None
    execution_mode: Literal["safe", "partial", "full"] = "safe"
    resume_message_id: str | None = None


class ChatPlanResult(BaseModel):
    user_message: ChatMessageOut
    plan: AnalysisPlan
    intake: IntakeDecision | None = None


class ChatExecuteRequest(BaseModel):
    workspace_id: str
    conversation_id: str
    plan_message_id: str
    approved: bool = False


class AnalysisRunOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str | None = None
    conversation_id: str
    plan_message_id: str
    status: str
    attempt: int
    idempotency_key: str | None = None
    approval_granted: bool = False
    cancel_requested: bool
    result_message_id: str | None
    report_id: str | None
    error: str
    progress: dict[str, Any]
    dataset_version_ids: list[str] = Field(default_factory=list)
    analysis_spec: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class RunEventOut(BaseModel):
    id: str
    run_id: str
    sequence: int
    event_type: str
    step_id: str | None
    status: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class ForecastRequest(BaseModel):
    workspace_id: str
    date_column: str | None = Field(default=None, max_length=255)
    target_column: str | None = Field(default=None, max_length=255)
    horizon: int = Field(default=6, ge=1, le=36)
    frequency: Literal["D", "W", "MS", "QS"] = "MS"
    aggregate: Literal["sum", "mean"] = "sum"


class ForecastOut(BaseModel):
    date_column: str
    target_column: str
    frequency: str
    aggregate: str
    method: str
    horizon: int
    metrics: dict[str, float | None]
    history: list[dict[str, Any]]
    forecast: list[dict[str, Any]]
    candidate_metrics: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    warnings: list[str]
    code: str


class SupersetPublishPreviewRequest(BaseModel):
    workspace_id: str
    dataset_id: str
    report_id: str | None = None
    title: str | None = Field(default=None, max_length=255)


class SupersetPublishRequest(SupersetPublishPreviewRequest):
    allowed_domains: list[str] = Field(default_factory=lambda: ["http://localhost:5174", "http://localhost:5175"], max_length=10)


class SupersetPublishResult(BaseModel):
    status: Literal["published", "reused"]
    dataset_id: str
    database_id: int
    superset_dataset_id: int
    dashboard_id: int
    embedded_id: str
    title: str
    charts: list[dict[str, Any]]
    dashboard_url: str


class ReportTemplateOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    original_name: str
    size_bytes: int
    placeholders: list[str]
    metadata: dict[str, Any]
    created_at: datetime


class TemplateRenderRequest(BaseModel):
    workspace_id: str
    report_id: str
    mapping: dict[str, Any] = Field(default_factory=dict)


class ArtifactOut(BaseModel):
    id: str
    workspace_id: str
    report_id: str | None
    kind: str
    name: str
    metadata: dict[str, Any]
    download_url: str
    created_at: datetime


class ArtifactRecordOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    run_id: str | None
    report_id: str | None
    legacy_artifact_id: str | None
    kind: str
    name: str
    version: int
    content_uri: str | None
    content: dict[str, Any]
    source_dataset_version_ids: list[str]
    supersedes_artifact_id: str | None
    created_at: datetime


class EvidenceRecordOut(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    run_id: str | None
    artifact_id: str | None
    report_id: str | None
    evidence_key: str
    statement: str
    method: str
    value: str
    source_columns: list[str]
    data: list[dict[str, Any]]
    code: str
    dataset_version_ids: list[str]
    created_at: datetime


class ChatResult(BaseModel):
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
    report_id: str | None = None
    provider: str


class ProviderConfigUpdate(BaseModel):
    enabled: bool = False
    is_default: bool = False
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    api_key: str | None = Field(default=None, max_length=1000)
    clear_api_key: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class ProviderConfigOut(BaseModel):
    provider: Literal["openai", "deepseek"]
    enabled: bool
    is_default: bool
    base_url: str
    model: str
    has_api_key: bool
    masked_api_key: str
    options: dict[str, Any]
    updated_at: datetime | None = None


class ProviderTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None


class McpServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=500)
    transport: Literal["streamable_http"] = "streamable_http"
    enabled: bool = True
    bearer_token: str | None = Field(default=None, max_length=4000)
    tool_allowlist: list[str] = Field(default_factory=list, max_length=200)


class McpServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=8, max_length=500)
    transport: Literal["streamable_http"] | None = None
    enabled: bool | None = None
    bearer_token: str | None = Field(default=None, max_length=4000)
    clear_bearer_token: bool = False
    tool_allowlist: list[str] | None = Field(default=None, max_length=200)


class McpServerOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    url: str
    transport: Literal["streamable_http"]
    enabled: bool
    tool_allowlist: list[str] = Field(default_factory=list)
    tool_cache: dict[str, Any] = Field(default_factory=dict)
    has_bearer_token: bool = False
    masked_bearer_token: str = ""
    last_checked_at: datetime | None = None
    updated_at: datetime | None = None


class McpServerTestOut(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)


class AppSettingsUpdate(BaseModel):
    language: Literal["zh-CN", "en-US"] = "zh-CN"
    theme: Literal["system", "light", "dark"] = "light"
    autosave: bool = True
    autosave_interval_seconds: int = Field(default=30, ge=10, le=600)
    safe_mode: bool = True
    autonomy_mode: Literal["safe", "balanced", "autonomous_copy"] = "balanced"
    telemetry: bool = False
    default_export: Literal["pdf", "docx", "pptx"] = "pdf"
    confirm_external_requests: bool = True
    default_clarification_mode: ClarificationMode = "auto"


class AppSettingsOut(AppSettingsUpdate):
    workspace_id: str


class TeamMemberCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "analyst", "viewer"] = "viewer"


class TeamMemberUpdate(BaseModel):
    role: Literal["admin", "analyst", "viewer"]


class TeamMemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    display_name: str
    role: Literal["owner", "admin", "analyst", "viewer"]
    created_at: datetime


class TeamContextOut(BaseModel):
    current_user_id: str
    current_role: Literal["owner", "admin", "analyst", "viewer"]
    members: list[TeamMemberOut]
    permissions: list[str]


class ReportCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    block_id: str | None = Field(default=None, max_length=80)


class ReportCommentOut(BaseModel):
    id: str
    report_id: str
    author_id: str
    author_name: str
    block_id: str | None
    body: str
    resolved: bool
    created_at: datetime


class ReportWorkflowOut(BaseModel):
    report_id: str
    status: Literal["draft", "in_review", "approved", "published"]
    submitted_by: str | None = None
    approved_by: str | None = None
    published_by: str | None = None
    updated_at: datetime | None = None


class ShareLinkCreate(BaseModel):
    expires_in_hours: int = Field(default=168, ge=1, le=2160)


class ShareLinkOut(BaseModel):
    id: str
    report_id: str
    url: str
    expires_at: datetime | None
    revoked: bool


class AuditLogOut(BaseModel):
    id: str
    actor_id: str | None
    actor_name: str
    action: str
    resource_type: str
    resource_id: str | None
    detail: dict[str, Any]
    created_at: datetime
