<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ReportLibrary from './components/ReportLibrary.vue'
import ExecutionDetails from './components/ExecutionDetails.vue'
import ReportRequirements from './components/ReportRequirements.vue'
import ReportClaimChecks from './components/ReportClaimChecks.vue'
import ChartPreview from './components/ChartPreview.vue'
import ChartWorkbench from './components/ChartWorkbench.vue'
import DataWorkbench from './components/DataWorkbench.vue'
import SettingsCenter from './components/SettingsCenter.vue'
import TeamWorkspace from './components/TeamWorkspace.vue'
import ProfessionalWorkspace from './components/ProfessionalWorkspace.vue'
import TemplateCenter from './components/TemplateCenter.vue'
import ContextMenu from './components/ContextMenu.vue'
import ChartAiAssistantDrawer from './components/ChartAiAssistantDrawer.vue'
import AnalysisIntakeCard from './components/AnalysisIntakeCard.vue'
import AnalysisCapabilities from './components/AnalysisCapabilities.vue'
import AnalysisComponentResults from './components/AnalysisComponentResults.vue'
import { saveAnalysisBrief } from './api/intake.js'
import './team.css'
import './run-history.css'

const section = ref('chat')
const workspace = ref(null)
const datasets = ref([])
const reports = ref([])
const trashedReports = ref([])
const reportBusy = ref(false)
const savedReportContent = ref('')
const reportRepair = ref(null)
const repairBusy = ref(false)
async function previewReportRepair() {
  if(!selectedReport.value || repairBusy.value) return
  if(reportDirty.value) { notice.value='请先保存当前草稿，再生成重算修复提案。'; return }
  const id=selectedReport.value.id
  repairBusy.value=true
  try {
    const proposal=await api(`/api/v1/reports/${id}/repair/preview`,{method:'POST'})
    if(selectedReport.value?.id===id) reportRepair.value={...proposal,report_id:id}
  } catch(error) { notice.value=error.message } finally { repairBusy.value=false }
}
async function applyReportRepair() {
  if(!reportRepair.value || repairBusy.value || reportDirty.value) return
  if(reportRepair.value.report_id!==selectedReport.value?.id) { reportRepair.value=null; return }
  if(!window.confirm('按已展示差异修复系统结论？会保存当前版本，自定义内容与图表排序保留。')) return
  const id=selectedReport.value.id
  repairBusy.value=true
  try {
    await api(`/api/v1/reports/${id}/repair/apply`,jsonOptions({proposal_hash:reportRepair.value.proposal_hash,approved:true}))
    reportRepair.value=null
    await openReport(id)
    reports.value=reports.value.map(r=>r.id===id?selectedReport.value:r)
    notice.value=reportQuality.value?.passed?'已重算并修复，当前规则检查通过':'已修复可重算内容，仍有自定义内容需要核验'
  } catch(error) { notice.value=error.message; reportRepair.value=null } finally { repairBusy.value=false }
}
function reportContent() { return selectedReport.value ? JSON.stringify({title:selectedReport.value.title,document:selectedReport.value.document}) : '' }
const reportDirty = computed(() => !!savedReportContent.value && reportContent() !== savedReportContent.value)
function allowReportLeave() { return !reportDirty.value || window.confirm('报告有未保存的修改，离开将丢弃这些修改。继续？') }
function beforeReportUnload(event) { if(reportDirty.value) { event.preventDefault(); event.returnValue='' } }
watch(section, (value, old) => {
  if(old === 'editor' && value !== 'editor' && reportDirty.value) {
    if(!allowReportLeave()) section.value = 'editor'
    else { selectedReport.value = null; savedReportContent.value = '' }
  }
}, {flush:'sync'})
async function loadReportTrash() {
  try { trashedReports.value = (await api(`/api/v1/report-catalog?workspace_id=${workspace.value.id}&deleted=true&limit=100`)).items }
  catch(error) { notice.value=error.message }
}
async function refreshReportCatalog() {
  if (!workspace.value) return
  try { reports.value = (await api(`/api/v1/report-catalog?workspace_id=${workspace.value.id}&limit=100`)).items }
  catch(error) { notice.value=error.message }
}
async function manageReport(action, report) {
  if(reportBusy.value || !workspace.value) return
  if(!allowReportLeave()) return
  let title
  if(['create','copy','rename'].includes(action)) {
    title = window.prompt('报告标题', action==='create'?'未命名报告':action==='copy'?`${report.title}（副本）`:report.title)
    if(title === null) return
    title = title.trim()
    if(!title || title.length>255) { notice.value='标题须为 1–255 个字符'; return }
  }
  if(action==='delete' && !window.confirm(`将“${report.title}”移入回收站？原始数据与历史证据不会删除。`)) return
  reportBusy.value=true
  try {
    let result
    if(action==='create'||action==='copy') result=await api('/api/v1/reports',jsonOptions({workspace_id:workspace.value.id,title,dataset_id:action==='create'?(selectedDatasetId.value||null):null,source_report_id:action==='copy'?report.id:null}))
    if(action==='rename') result=await api(`/api/v1/reports/${report.id}`,{...jsonOptions({title}),method:'PATCH'})
    if(action==='delete') await api(`/api/v1/reports/${report.id}`,{method:'DELETE'})
    if(action==='restore') result=await api(`/api/v1/reports/${report.id}/restore`,{method:'POST'})
    if(selectedReport.value?.id===report?.id) { selectedReport.value=null; savedReportContent.value='' }
    reports.value=(await api(`/api/v1/report-catalog?workspace_id=${workspace.value.id}&limit=100`)).items
    await loadReportTrash()
    notice.value={create:'空白报告已创建',copy:'报告副本已创建',rename:'报告已重命名',delete:'已移入回收站，可恢复',restore:'报告已恢复'}[action]
    if(action==='create'||action==='copy') await openReport(result)
  } catch(error) { notice.value=error.message } finally { reportBusy.value=false }
}
const conversations = ref([])
const conversationSelection = ref([]), conversationTrash = ref([]), showConversationTrash = ref(false), conversationBatchBusy = ref(false)
const visibleConversations = computed(()=>showConversationTrash.value ? conversationTrash.value : conversations.value)
let planningController = null
const stopBusy = ref(false)
const activeChatRuns = computed(()=>analysisRuns.value.filter(r=>r.conversation_id===activeConversationId.value && ['queued','running'].includes(r.status)))
async function stopChat() {
  if(stopBusy.value) return
  stopBusy.value=true
  planningController?.abort()
  try {
    for(const run of activeChatRuns.value) await cancelAnalysisRun(run)
    notice.value='已请求中断；已完成操作不会回滚，上游模型可能仍产生消耗。'
  } finally { stopBusy.value=false }
}
async function toggleConversationTrash() {
  showConversationTrash.value=!showConversationTrash.value; conversationSelection.value=[]
  if(showConversationTrash.value) {
    try { conversationTrash.value=await api(`/api/v1/conversations?workspace_id=${workspace.value.id}&archived=true`) }
    catch(e) { notice.value=e.message }
  }
}
async function batchConversations() {
  const targets=visibleConversations.value.filter(c=>conversationSelection.value.includes(c.id))
  if(!targets.length || conversationBatchBusy.value || !window.confirm(`${showConversationTrash.value?'恢复':'移入回收站'}选中的 ${targets.length} 个会话？保留消息、报告和数据。`)) return
  const restore=showConversationTrash.value, failed=[]
  conversationBatchBusy.value=true
  try {
    for(const item of targets) {
      try {
        await api(`/api/v1/conversations/${item.id}${restore?'/restore':''}`,{method:restore?'POST':'DELETE'})
        if(!restore && activeConversationId.value===item.id) {activeConversationId.value='';messages.value=[];analysisRuns.value=[]}
        conversationSelection.value=conversationSelection.value.filter(id=>id!==item.id)
      } catch(e) {failed.push(`${item.title}：${e.message}`)}
    }
    conversations.value=await api(`/api/v1/conversations?workspace_id=${workspace.value.id}`)
    conversationTrash.value=await api(`/api/v1/conversations?workspace_id=${workspace.value.id}&archived=true`)
    notice.value=`完成 ${targets.length-failed.length}/${targets.length}。${failed.join('；')}`
  } catch(e) {notice.value=e.message} finally {conversationBatchBusy.value=false}
}
const messages = ref([])
const providers = ref([])
const appSettings = ref(null)
const samples = ref([])
const toolPolicy = ref(null)
const integrations = ref(null)
const mcpServers = ref([])
const analysisModes = ref([])
const selectedAnalysisMode = ref(localStorage.getItem('insight-analysis-mode') || 'auto')
const executionPermissionMode = ref(localStorage.getItem('insight-execution-mode') || 'safe')
const activeConversationId = ref('')
const selectedDatasetId = ref('')
const selectedReport = ref(null)
const selectedBlockId = ref('')
const selectedChartId = ref('')
const composer = ref('')
const sending = ref(false)
const executingPlanId = ref('')
const loading = ref(false)
const saving = ref(false)
const contextMenu = ref(null)
const notice = ref('')
const bootError = ref('')
const booting = ref(false)
const fileInput = ref(null)
const chatScroll = ref(null)
const providerKeys = ref({ openai: '', deepseek: '' })
const providerStatus = ref({})
const ribbonTab = ref('开始')
const fontSize = ref('14')
const reportUndo = ref([])
const reportRedo = ref([])
const reportSort = ref(localStorage.getItem('insight-report-sort') || 'updated_desc')
const draggedBlockId = ref('')
const reportVersions = ref([])
const showVersionHistory = ref(false)
const pageMode = ref('a4-portrait')
const teamContext = ref(null)
const auditLogs = ref([])
const reportWorkflow = ref(null)
const reportComments = ref([])
const showCollaboration = ref(false)
const commentDraft = ref('')
const shareUrl = ref('')
const professionalDashboard = ref(null)
const professionalPreview = ref(null)
const professionalPublishing = ref(false)
const reportTemplates = ref([])
const analysisRuns = ref([])
const aiChartDrawerOpen = ref(false)
const aiChartInstruction = ref('')
const intakeSubmittingId = ref('')
let conversationCreation = null
let conversationLoadSequence = 0
const capabilitySaving = ref(false)
let capabilitySave = null
const analysisOptions = ref({ include_recommendations: false, include_report: false, show_code: true, template_id: null, forecast: { enabled: false, date_column: null, target_column: null, horizon: 6, frequency: 'MS', aggregate: 'sum' } })

const activeConversation = computed(() => conversations.value.find(item => item.id === activeConversationId.value))
const selectedDataset = computed(() => datasets.value.find(item => item.id === selectedDatasetId.value))
const activeProvider = computed(() => providers.value.find(item => item.enabled && item.is_default) || providers.value.find(item => item.enabled))
const reportDocument = computed(() => selectedReport.value?.document)
const reportQuality = computed(() => reportDirty.value && reportDocument.value?.quality ? {...reportDocument.value.quality,passed:false} : reportDocument.value?.quality)
const reportQualityHint = computed(() => {
  if(reportDirty.value) return '存在未保存修改，请保存后重新核验；上次检查不代表当前稿件。'
  const issues = reportQuality.value?.issues || []
  if (!issues.length) return '结论、数字、图表和证据引用已通过检查'
  return issues.slice(0, 5).map(item => `${item.severity === 'error' ? '错误' : '提醒'}：${item.title}`).join('\n')
})
const selectedBlock = computed(() => reportDocument.value?.blocks?.find(item => item.id === selectedBlockId.value))
const selectedChart = computed(() => reportDocument.value?.charts?.find(item => item.id === selectedChartId.value))
const sortedReports = computed(() => [...reports.value].sort((left, right) => {
  if (reportSort.value === 'title_asc') return left.title.localeCompare(right.title, 'zh-CN')
  if (reportSort.value === 'created_desc') return new Date(right.created_at || 0) - new Date(left.created_at || 0)
  if (reportSort.value === 'charts_desc') return (right.chart_count ?? right.document?.charts?.length ?? 0) - (left.chart_count ?? left.document?.charts?.length ?? 0)
  return new Date(right.updated_at || 0) - new Date(left.updated_at || 0)
}))
const selectedColumns = computed(() => selectedDataset.value?.profile?.columns || [])
const selectedMode = computed(() => analysisModes.value.find(item => item.id === selectedAnalysisMode.value))
const permissionMode = computed(() => ({
  safe: { label: '安全模式', hint: '画像、质量和固定统计可直接运行；SQL 需批准，Python、MCP 和发布被禁止。' },
  partial: { label: '部分允许', hint: '只读 SQL 可运行；沙箱 Python、数据副本修改和 MCP 需批准，发布单独批准。' },
  full: { label: '副本完全访问', hint: '仅对数据副本开放受控工具；MCP 受白名单限制，外部发布仍需单独批准，原文件永不修改。' },
}[executionPermissionMode.value] || { label: '安全模式', hint: '' }))
const clarificationMode = computed(() => activeConversation.value?.clarification_mode || appSettings.value?.default_clarification_mode || 'auto')
const analysisCapabilities = computed(() => ({ deep_analysis: false, max_rounds: 1, content_review: true, chart_layout: true, alternatives: false, ...activeConversation.value?.analysis_capabilities }))
const pendingIntakeCount = computed(() => [...messages.value].reverse().find(item => item.message_meta?.intake?.should_pause)?.message_meta.intake.questions?.length || 0)
const intakeCompleted = computed(() => messages.value.some(item => item.message_meta?.intake_completed))
const clarificationLabel = computed(() => pendingIntakeCount.value ? `${pendingIntakeCount.value} 项待回答` : clarificationMode.value === 'off' ? '已关闭' : intakeCompleted.value ? '已完成' : clarificationMode.value === 'always' ? '每次检查' : '自动')

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {})
  if (teamContext.value?.current_user_id) headers.set('X-Actor-ID', teamContext.value.current_user_id)
  const response = await fetch(path, { ...options, headers })
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '请求失败')
  return response.status === 204 ? null : response.json()
}

const jsonOptions = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

async function refresh() {
  if (booting.value) return
  booting.value = true; bootError.value = ''
  try {
    workspace.value = await api('/api/v1/workspaces/bootstrap', { method: 'POST' })
    const workspaceId = workspace.value.id
    const [nextDatasets, nextReports, nextConversations, nextProviders, nextSettings, nextSamples, tools, nextIntegrations, modeManifest, nextTemplates, nextMcpServers] = await Promise.all([
      api(`/api/v1/datasets?workspace_id=${workspaceId}`), api(`/api/v1/report-catalog?workspace_id=${workspaceId}&limit=100`).then(page => page.items),
      api(`/api/v1/conversations?workspace_id=${workspaceId}`), api(`/api/v1/settings/providers?workspace_id=${workspaceId}`),
      api(`/api/v1/settings/app?workspace_id=${workspaceId}`), api('/api/v1/samples'), api('/api/v1/tools'), api('/api/v1/integrations'), api('/api/v1/analysis-modes'), api(`/api/v1/report-templates?workspace_id=${workspaceId}`).catch(() => []), api(`/api/v1/mcp/servers?workspace_id=${workspaceId}`).catch(() => [])
    ])
    datasets.value = nextDatasets; reports.value = nextReports; conversations.value = nextConversations
    providers.value = nextProviders; appSettings.value = nextSettings; samples.value = nextSamples
    toolPolicy.value = tools; integrations.value = nextIntegrations; mcpServers.value = nextMcpServers
    analysisModes.value = modeManifest.modes || []
    reportTemplates.value = nextTemplates
    if (!analysisModes.value.some(item => item.id === selectedAnalysisMode.value)) selectedAnalysisMode.value = modeManifest.default || 'auto'
    teamContext.value = await api(`/api/v1/team/context?workspace_id=${workspaceId}`)
    const resources = await api(`/api/v1/integrations/superset/resources?workspace_id=${workspaceId}`).catch(() => [])
    professionalDashboard.value = resources.find(item => item.resource_type === 'dashboard') || null
    if (!selectedDatasetId.value && datasets.value[0]) selectedDatasetId.value = datasets.value[0].id
    if (!selectedReport.value && reports.value[0]) selectedReport.value = await api(`/api/v1/reports/${reports.value[0].id}`)
    if (!conversationCreation && !activeConversationId.value && conversations.value[0]) await openConversation(conversations.value[0], false)
  } catch (error) {
    bootError.value = `本地 API 未连接：${error.message}`
  } finally { booting.value = false }
}

async function newConversation() {
  if (conversationCreation) return conversationCreation
  conversationLoadSequence += 1
  conversationCreation = (async () => {
    const item = await api('/api/v1/conversations', jsonOptions({ workspace_id: workspace.value.id, dataset_id: selectedDatasetId.value || null, title: '新分析' }))
    conversations.value.unshift(item); activeConversationId.value = item.id; messages.value = []; section.value = 'chat'; composer.value = ''
    return item
  })()
  try { return await conversationCreation }
  finally { conversationCreation = null }
}

async function openConversation(item, navigate = true) {
  const sequence = ++conversationLoadSequence
  activeConversationId.value = item.id
  selectedDatasetId.value = item.dataset_id || selectedDatasetId.value
  messages.value = []
  const loaded = await api(`/api/v1/conversations/${item.id}/messages`)
  if(sequence!==conversationLoadSequence || activeConversationId.value!==item.id) return
  messages.value = loaded
  await refreshAnalysisRuns()
  if (navigate) section.value = 'chat'
  await scrollChat()
}

async function renameConversation(item) {
  const title = window.prompt('重命名会话', item.title)
  if (!title?.trim()) return
  const saved = await api(`/api/v1/conversations/${item.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title.trim() }) })
  conversations.value = conversations.value.map(row => row.id === saved.id ? saved : row)
}

async function removeConversation(item) {
  if (!window.confirm(`将会话“${item.title}”移入回收站？消息保留，可恢复；报告和数据集不会被删除。`)) return
  try { await api(`/api/v1/conversations/${item.id}`, { method: 'DELETE' }) }
  catch(e) { notice.value=e.message; return }
  conversations.value = conversations.value.filter(row => row.id !== item.id)
  if (activeConversationId.value === item.id) { activeConversationId.value = ''; messages.value = [] }
}

function chatPlanPayload(message, extra = {}) {
  return {
    workspace_id: workspace.value.id, conversation_id: activeConversationId.value,
    dataset_id: selectedDatasetId.value || null, analysis_mode: selectedAnalysisMode.value,
    analysis_options: { ...analysisOptions.value, capabilities: { ...analysisCapabilities.value } }, message, execution_mode: executionPermissionMode.value,
    ...extra,
  }
}

async function setClarificationMode(mode) {
  if (!['auto', 'always', 'off'].includes(mode)) return
  if (conversationCreation) await conversationCreation
  if (!activeConversation.value) await newConversation()
  const conversation = activeConversation.value
  if (!conversation || conversation.clarification_mode === mode) return
  const previousMode = conversation.clarification_mode || 'auto'
  conversations.value = conversations.value.map(item => item.id === conversation.id ? { ...item, clarification_mode: mode } : item)
  try {
    const saved = await api(`/api/v1/conversations/${conversation.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ clarification_mode: mode }),
    })
    conversations.value = conversations.value.map(item => item.id === saved.id ? saved : item)
  } catch (error) {
    conversations.value = conversations.value.map(item => item.id === conversation.id ? { ...item, clarification_mode: previousMode } : item)
    notice.value = error.message
  }
}

async function saveCapabilities(value) {
  if (capabilitySaving.value) return
  capabilitySaving.value = true
  capabilitySave = (async () => {
    if (conversationCreation) await conversationCreation
    if (!activeConversation.value) await newConversation()
    const id = activeConversationId.value
    const saved = await api(`/api/v1/conversations/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ analysis_capabilities: value }),
    })
    conversations.value = conversations.value.map(item => item.id === saved.id ? saved : item)
  })()
  try { await capabilitySave }
  catch (error) { notice.value = `分析能力未保存：${error.message}` }
  finally { capabilitySaving.value = false; capabilitySave = null }
}

async function resolveIntake(item, { answers, useDefaults }) {
  const conversation = activeConversation.value
  if (!conversation?.project_id || intakeSubmittingId.value) return
  intakeSubmittingId.value = item.id
  try {
    await saveAnalysisBrief(api, conversation.project_id, {
      workspace_id: workspace.value.id, conversation_id: conversation.id,
      dataset_id: selectedDatasetId.value || null, objective: item.content,
      answers, use_recommended_defaults: useDefaults,
    })
    const result = await api('/api/v1/chat/plan', jsonOptions(chatPlanPayload(item.content, { resume_message_id: item.id, analysis_options: item.message_meta.analysis_options })))
    messages.value = messages.value.map(message => message.id === item.id ? result.user_message : message)
    if (result.intake?.should_pause) {
      notice.value = '仍有未回答的关键信息；可继续填写或使用推荐默认值。'
    } else if (!result.plan.requires_approval) {
      await executePlan(result.user_message, false)
    }
  } catch (error) { notice.value = error.message }
  finally { intakeSubmittingId.value = ''; await scrollChat() }
}

async function sendMessage(text = composer.value) {
  if(conversationCreation) await conversationCreation
  if (capabilitySave) {
    try { await capabilitySave } catch { notice.value = '请先重新保存分析能力，再发送消息。'; return }
  }
  const message = text.trim()
  if (!message || sending.value) return
  const chartEditIntent = /改(?:当前|这张|这个|本)?图表|优化(?:当前|这张|这个)?图表|图表.*(?:修改|优化|改成)/.test(message) && selectedReport.value && selectedChart.value
  if (!activeConversationId.value) await newConversation()
  const tempId = `temp-${Date.now()}`
  messages.value.push({ id: tempId, role: 'user', content: message, message_meta: {}, created_at: new Date().toISOString() })
  const controller = new AbortController()
  planningController = controller
  composer.value = ''; sending.value = true; await scrollChat()
  try {
    localStorage.setItem('insight-analysis-mode', selectedAnalysisMode.value)
    localStorage.setItem('insight-execution-mode', executionPermissionMode.value)
    const result = await planInBackground(chatPlanPayload(message, { report_id: chartEditIntent ? selectedReport.value.id : null, chart_id: chartEditIntent ? selectedChart.value.id : null }),controller.signal)
    if(controller.signal.aborted) return
    if(result.user_message.conversation_id!==activeConversationId.value) { notice.value='计划已保存在原会话，请切回原会话查看'; return }
    messages.value = messages.value.filter(item => item.id !== tempId)
    messages.value.push(result.user_message)
    if (!result.intake?.should_pause && !result.plan.requires_approval && !chartEditIntent) {
      notice.value = '计划内工具已通过服务端策略检查，正在运行。'
      await executePlan(result.user_message, false)
    }
    const current = conversations.value.find(item => item.id === activeConversationId.value)
    if (current?.title === '新分析') current.title = message.replace(/\n/g, ' ').slice(0, 32)
  } catch (error) {
    messages.value.push({ id: `error-${Date.now()}`, role: 'assistant', content: error.name==='AbortError' ? '已停止等待规划，不会自动执行其结果。服务端规划可能仍在完成，重新打开会话可查看；上游消耗不保证立即停止。' : `请求失败：${error.message}`, message_meta: { error: true } })
  } finally { planningController=null; sending.value = false; await scrollChat() }
}

async function planInBackground(payload, signal) {
  payload.idempotency_key ||= crypto.randomUUID()
  const run=await api('/api/v1/chat/plan-async',{...jsonOptions(payload),signal})
  analysisRuns.value=[run,...analysisRuns.value]
  while(true) {
    if(signal.aborted) {
      try {await api(`/api/v1/analysis-runs/${run.id}/cancel?workspace_id=${payload.workspace_id}`,{method:'POST'})} catch(_) { /* already terminal */ }
      throw new DOMException('规划已中断','AbortError')
    }
    const rows=await api(`/api/v1/analysis-runs?workspace_id=${payload.workspace_id}&conversation_id=${payload.conversation_id}`)
    if(activeConversationId.value===payload.conversation_id) analysisRuns.value=rows
    const current=rows.find(r=>r.id===run.id)
    if(current?.status==='completed') {
      const history=await api(`/api/v1/conversations/${payload.conversation_id}/messages`)
      const item=history.find(m=>m.id===current.result_message_id)
      if(!item?.message_meta?.analysis_plan) throw new Error('规划结果未保存，请从运行历史重试')
      return {user_message:item,plan:item.message_meta.analysis_plan,intake:item.message_meta.intake}
    }
    if(current && ['failed','cancelled','interrupted'].includes(current.status)) throw new Error(current.error || '规划已中断，可从运行历史重试')
    await new Promise(resolve=>setTimeout(resolve,400))
  }
}

async function openChartPlan(item) {
  const target = item.message_meta?.chart_edit
  if (!target) return
  if (!selectedReport.value || selectedReport.value.id !== target.report_id) await openReport(target.report_id)
  selectedChartId.value = target.chart_id
  aiChartInstruction.value = target.instruction
  section.value = 'editor'
  aiChartDrawerOpen.value = true
}

async function optimizeDashboardLayout() {
  if (!selectedReport.value) return
  try {
    const proposal = await api(`/api/v1/reports/${selectedReport.value.id}/layout/proposals`, jsonOptions({ workspace_id: workspace.value.id }))
    const details = proposal.proposals.map(item => `• ${item.title}：${item.reason}`).join('\n')
    if (!window.confirm(`${proposal.summary}\n\n${details}\n\n应用布局会创建一个可恢复的报告历史版本。是否应用？`)) return
    const saved = await api(`/api/v1/reports/${selectedReport.value.id}/layout/apply`, jsonOptions({ workspace_id: workspace.value.id, proposals: proposal.proposals, approved: true }))
    selectedReport.value = saved
    notice.value = '已应用仪表板布局优化，并保留了可恢复的历史版本。'
  } catch (error) { notice.value = error.message }
}

async function executePlan(item, approved = true) {
  if (executingPlanId.value) return
  executingPlanId.value = item.id
  await scrollChat()
  try {
    const run = await api('/api/v1/chat/execute-async', jsonOptions({
      workspace_id: workspace.value.id, conversation_id: activeConversationId.value, plan_message_id: item.id,
      approved,
    }))
    item.message_meta.analysis_plan.status = 'running'
    analysisRuns.value = [run, ...analysisRuns.value.filter(row => row.id !== run.id)]
    monitorAnalysisRun(run, item)
  } catch (error) {
    item.message_meta.analysis_plan.status = 'pending'
    messages.value.push({ id: `error-${Date.now()}`, role: 'assistant', content: `执行失败：${error.message}`, message_meta: { error: true } })
  } finally { executingPlanId.value = ''; await scrollChat() }
}

async function cancelPlan(item) {
  try {
    const run = analysisRuns.value.find(row => row.plan_message_id === item.id && ['queued', 'running'].includes(row.status))
    if (run) {
      await cancelAnalysisRun(run)
      return
    }
    const saved = await api(`/api/v1/chat/plans/${item.id}/cancel?workspace_id=${workspace.value.id}&conversation_id=${activeConversationId.value}`, { method: 'POST' })
    messages.value = messages.value.map(message => message.id === saved.id ? saved : message)
  } catch (error) { notice.value = error.message }
}

async function cancelAnalysisRun(run) {
  try {
    const savedRun = await api(`/api/v1/analysis-runs/${run.id}/cancel?workspace_id=${workspace.value.id}`, { method: 'POST' })
    analysisRuns.value = analysisRuns.value.map(row => row.id === savedRun.id ? savedRun : row)
  } catch (error) { notice.value = error.message }
}

function runForPlan(planMessageId) { return analysisRuns.value.find(row => row.plan_message_id === planMessageId) }

async function refreshAnalysisRuns() {
  if (!workspace.value || !activeConversationId.value) return
  try {
    analysisRuns.value = await api(`/api/v1/analysis-runs?workspace_id=${workspace.value.id}&conversation_id=${activeConversationId.value}`)
    analysisRuns.value.filter(row => ['queued', 'running'].includes(row.status)).forEach(run => monitorAnalysisRun(run))
  } catch (_) { /* API may be restarting; chat remains usable */ }
}

async function refreshFinishedRun(run, planItem) {
  if(run.conversation_id!==activeConversationId.value) return
  const rows = await api(`/api/v1/analysis-runs?workspace_id=${workspace.value.id}&conversation_id=${activeConversationId.value}`)
  analysisRuns.value = rows
  const current = rows.find(row => row.id === run.id) || run
  if (current.analysis_spec?.kind !== 'planning' && planItem?.message_meta?.analysis_plan) planItem.message_meta.analysis_plan.status = current.status
  if (['cancelled','interrupted','failed'].includes(current.status)) messages.value = await api(`/api/v1/conversations/${activeConversationId.value}/messages`)
  if (current.status === 'completed') {
    messages.value = await api(`/api/v1/conversations/${activeConversationId.value}/messages`)
    if (current.report_id) {
      const report = await api(`/api/v1/reports/${current.report_id}`)
      reports.value = [report, ...reports.value.filter(row => row.id !== report.id)]
    }
    notice.value = current.progress?.outcome === 'degraded' ? '运行已结束，但存在失败或降级，请展开实际执行记录。' : current.report_id ? '分析完成，报告已生成。' : '分析完成，结论与证据已更新。'
  } else if (current.status === 'failed') notice.value = `分析运行失败：${current.error || '请查看历史后重试'}`
  else if (current.status === 'interrupted') notice.value = '应用上次退出时中断了该任务，可在运行历史中重试。'
  await scrollChat()
}

async function pollAnalysisRun(run, planItem) {
  window.setTimeout(async () => {
    if(run.conversation_id!==activeConversationId.value) return
    try {
      const rows = await api(`/api/v1/analysis-runs?workspace_id=${workspace.value.id}&conversation_id=${activeConversationId.value}`)
      analysisRuns.value = rows
      const current = rows.find(row => row.id === run.id)
      if (!current) return
      if (['queued', 'running'].includes(current.status)) {
        if (planItem?.message_meta?.analysis_plan) planItem.message_meta.analysis_plan.status = 'running'
        return pollAnalysisRun(current, planItem)
      }
      await refreshFinishedRun(current, planItem)
    } catch (_) { return pollAnalysisRun(run, planItem) }
  }, 850)
}

function monitorAnalysisRun(run, planItem = messages.value.find(item => item.id === run.plan_message_id)) {
  if (!window.EventSource) return pollAnalysisRun(run, planItem)
  const source = new EventSource(`/api/v1/analysis-runs/${run.id}/events/stream?workspace_id=${encodeURIComponent(workspace.value.id)}`)
  let received = false
  source.onmessage = async event => {
    if(run.conversation_id!==activeConversationId.value) {source.close();return}
    received = true
    const update = JSON.parse(event.data)
    const current = analysisRuns.value.find(row => row.id === run.id) || run
    current.status = update.status
    if (update.event_type === 'step.started') current.progress = { ...(current.progress || {}), current_step: update.step_id, title: update.message, ...(update.data || {}) }
    if (update.event_type === 'step.completed') current.progress = { ...(current.progress || {}), completed_steps: (current.progress?.completed_steps || 0) + 1 }
    analysisRuns.value = [current, ...analysisRuns.value.filter(row => row.id !== run.id)]
    if (planItem?.message_meta?.analysis_plan && ['queued', 'running'].includes(update.status)) planItem.message_meta.analysis_plan.status = 'running'
    if (['completed', 'failed', 'cancelled', 'interrupted'].includes(update.status)) {
      source.close()
      await refreshFinishedRun(current, planItem)
    }
  }
  source.onerror = () => {
    source.close()
    if (!received || ['queued', 'running'].includes((analysisRuns.value.find(row => row.id === run.id) || run).status)) pollAnalysisRun(run, planItem)
  }
}

async function retryAnalysisRun(run) {
  try {
    const saved = await api(`/api/v1/analysis-runs/${run.id}/retry?workspace_id=${workspace.value.id}`, { method: 'POST' })
    analysisRuns.value = [saved, ...analysisRuns.value]
    const item = messages.value.find(row => row.id === saved.plan_message_id)
    if (item?.message_meta?.analysis_plan) item.message_meta.analysis_plan.status = 'running'
    monitorAnalysisRun(saved, item)
  } catch (error) { notice.value = error.message }
}

async function scrollChat() { await nextTick(); if (chatScroll.value) chatScroll.value.scrollTop = chatScroll.value.scrollHeight }

function planStatusLabel(status) {
  return ({ pending: '等待批准', running: '执行中', completed: '已完成', cancelled: '已取消', failed: '失败', interrupted: '被中断' })[status] || status
}

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])) }
function inlineMarkdown(value) { return escapeHtml(value).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/\*([^*]+)\*/g,'<em>$1</em>') }
function renderMarkdown(source) {
  const lines=String(source || '').split(/\r?\n/); const html=[]
  for(let i=0;i<lines.length;) {
    const line=lines[i]
    if(!line.trim()){i++;continue}
    const heading=line.match(/^(#{1,4})\s+(.+)/)
    if(heading){const level=Math.min(4,heading[1].length+1);html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);i++;continue}
    if(/^\|.+\|$/.test(line.trim()) && i+1<lines.length && /^\|?[\s:|-]+\|$/.test(lines[i+1].trim())) {
      const cells=row=>row.trim().replace(/^\||\|$/g,'').split('|').map(cell=>inlineMarkdown(cell.trim()))
      const headers=cells(line); i+=2; const rows=[]
      while(i<lines.length && /^\|.+\|$/.test(lines[i].trim())){rows.push(cells(lines[i]));i++}
      html.push(`<div class="markdown-table-wrap"><table><thead><tr>${headers.map(cell=>`<th>${cell}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);continue
    }
    if(/^\d+\.\s+/.test(line)){const items=[];while(i<lines.length&&/^\d+\.\s+/.test(lines[i])){items.push(lines[i].replace(/^\d+\.\s+/,''));i++}html.push(`<ol>${items.map(item=>`<li>${inlineMarkdown(item)}</li>`).join('')}</ol>`);continue}
    if(/^[-*]\s+/.test(line)){const items=[];while(i<lines.length&&/^[-*]\s+/.test(lines[i])){items.push(lines[i].replace(/^[-*]\s+/,''));i++}html.push(`<ul>${items.map(item=>`<li>${inlineMarkdown(item)}</li>`).join('')}</ul>`);continue}
    if(/^>\s?/.test(line)){html.push(`<blockquote>${inlineMarkdown(line.replace(/^>\s?/,''))}</blockquote>`);i++;continue}
    const paragraph=[];while(i<lines.length&&lines[i].trim()&&!/^(#{1,4})\s+|^\|.+\|$|^\d+\.\s+|^[-*]\s+|^>\s?/.test(lines[i])){paragraph.push(lines[i]);i++}
    html.push(`<p>${paragraph.map(inlineMarkdown).join('<br>')}</p>`)
  }
  return html.join('')
}

function composerKey(event) { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage() } }

async function upload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  loading.value = true
  const form = new FormData(); form.append('workspace_id', workspace.value.id); form.append('file', file)
  try {
    const dataset = await api('/api/v1/datasets/upload', { method: 'POST', body: form })
    datasets.value.unshift(dataset); selectedDatasetId.value = dataset.id; notice.value = `已载入 ${dataset.original_name}`; section.value = 'chat'
  } catch (error) { notice.value = error.message } finally { loading.value = false; event.target.value = '' }
}

async function uploadReportTemplate(file) {
  if (!workspace.value) return
  const form = new FormData(); form.append('workspace_id', workspace.value.id); form.append('name', file.name.replace(/\.docx$/i, '')); form.append('file', file)
  try {
    const item = await api('/api/v1/report-templates/upload', { method: 'POST', body: form })
    reportTemplates.value = [item, ...reportTemplates.value]; notice.value = `已上传模板：${item.name}`
  } catch (error) { notice.value = error.message }
}

async function renderTemplateReport({ templateId, reportId, mapping }) {
  try {
    const artifact = await api(`/api/v1/report-templates/${templateId}/render`, jsonOptions({ workspace_id: workspace.value.id, report_id: reportId, mapping }))
    const response = await fetch(artifact.download_url, { headers: teamContext.value?.current_user_id ? { 'X-Actor-ID': teamContext.value.current_user_id } : {} })
    if (!response.ok) throw new Error('报告已生成，但下载失败')
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = artifact.name; link.click(); URL.revokeObjectURL(url)
    notice.value = `已生成固定格式报告：${artifact.name}`
  } catch (error) { notice.value = error.message }
}

async function downloadArtifact(artifact) {
  try {
    const response = await fetch(artifact.download_url, { headers: teamContext.value?.current_user_id ? { 'X-Actor-ID': teamContext.value.current_user_id } : {} })
    if (!response.ok) throw new Error('下载失败')
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = artifact.name; link.click(); URL.revokeObjectURL(url)
  } catch (error) { notice.value = error.message }
}

async function importSample() {
  loading.value = true
  try {
    const dataset = await api(`/api/v1/samples/retail-sales-2026/import?workspace_id=${workspace.value.id}`, { method: 'POST' })
    datasets.value.unshift(dataset); selectedDatasetId.value = dataset.id; notice.value = '示例数据已载入。可以直接发送下方推荐问题。'; section.value = 'chat'
    if (!activeConversationId.value) await newConversation()
  } catch (error) { notice.value = error.message } finally { loading.value = false }
}

function selectDataWorkbenchDataset(id) { selectedDatasetId.value = id }
function acceptCreatedDataset(dataset) {
  datasets.value = [dataset, ...datasets.value.filter(item => item.id !== dataset.id)]
  selectedDatasetId.value = dataset.id
}
function startDatasetAnalysis(id) { selectedDatasetId.value = id; section.value = 'chat' }

async function openReport(reportOrId) {
  if(!allowReportLeave()) return
  reportRepair.value=null
  const id = typeof reportOrId === 'string' ? reportOrId : reportOrId.id
  selectedReport.value = await api(`/api/v1/reports/${id}`)
  selectedReport.value.document.charts = (selectedReport.value.document.charts || []).map(chart => ({
    series: chart.y ? [chart.y] : [], style: { palette:'insight',show_legend:true,show_labels:false,number_format:'compact',height:320 }, ...chart,
  }))
  selectedReport.value.document.blocks = (selectedReport.value.document.blocks || []).map(block => ({ style:{}, ...block }))
  if (selectedReport.value.dataset_id) selectedDatasetId.value = selectedReport.value.dataset_id
  selectedBlockId.value = selectedReport.value.document.blocks?.[0]?.id || ''
  selectedChartId.value = selectedReport.value.document.charts?.[0]?.id || ''
  reportUndo.value = []; reportRedo.value = []; showVersionHistory.value = false
  savedReportContent.value = reportContent()
  const collaboration = await Promise.all([api(`/api/v1/reports/${id}/workflow`), api(`/api/v1/reports/${id}/comments`)]).catch(() => [null, []])
  reportWorkflow.value = collaboration[0]; reportComments.value = collaboration[1]; shareUrl.value = ''
  section.value = 'editor'
}

async function refreshTeam() {
  if (!workspace.value) return
  teamContext.value = await api(`/api/v1/team/context?workspace_id=${workspace.value.id}`)
  auditLogs.value = teamContext.value.permissions.includes('audit.view') ? await api(`/api/v1/audit?workspace_id=${workspace.value.id}`) : []
}
async function inviteMember(payload) {
  try { await api(`/api/v1/team/members?workspace_id=${workspace.value.id}`, jsonOptions(payload)); await refreshTeam(); notice.value='成员已添加' }
  catch(error){ notice.value=error.message }
}
async function updateMemberRole(member, role) {
  try { await api(`/api/v1/team/members/${member.id}?workspace_id=${workspace.value.id}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({role})}); await refreshTeam(); notice.value='角色已更新' }
  catch(error){ notice.value=error.message }
}
async function removeMember(member) {
  if(!window.confirm(`移除成员“${member.display_name}”？`)) return
  try { await api(`/api/v1/team/members/${member.id}?workspace_id=${workspace.value.id}`, {method:'DELETE'}); await refreshTeam(); notice.value='成员已移除' }
  catch(error){ notice.value=error.message }
}
async function transitionReport(action) {
  try { reportWorkflow.value=await api(`/api/v1/reports/${selectedReport.value.id}/workflow/${action}`,{method:'POST'}); notice.value={submit:'已提交审核',approve:'已批准',publish:'已发布',return:'已退回草稿'}[action]; await refreshTeam() }
  catch(error){ notice.value=error.message }
}
async function addReportComment() {
  if(!commentDraft.value.trim()) return
  try { const item=await api(`/api/v1/reports/${selectedReport.value.id}/comments`,jsonOptions({body:commentDraft.value.trim(),block_id:selectedBlockId.value||null})); reportComments.value.push(item); commentDraft.value=''; notice.value='批注已添加' }
  catch(error){ notice.value=error.message }
}
async function resolveReportComment(item) {
  try { const saved=await api(`/api/v1/reports/${selectedReport.value.id}/comments/${item.id}/resolve`,{method:'PATCH'}); reportComments.value=reportComments.value.map(row=>row.id===saved.id?saved:row) }
  catch(error){ notice.value=error.message }
}
async function createShareLink() {
  try { const result=await api(`/api/v1/reports/${selectedReport.value.id}/share`,jsonOptions({expires_in_hours:168})); shareUrl.value=result.url; await navigator.clipboard?.writeText(result.url); notice.value='只读链接已生成并复制' }
  catch(error){ notice.value=error.message }
}

function reportSnapshot() { return selectedReport.value ? JSON.parse(JSON.stringify(selectedReport.value)) : null }
function rememberReport() { const snapshot=reportSnapshot(); if(!snapshot)return; reportUndo.value.push(snapshot); if(reportUndo.value.length>40)reportUndo.value.shift(); reportRedo.value=[] }
function undoReport() { if(!reportUndo.value.length)return; reportRedo.value.push(reportSnapshot()); selectedReport.value=reportUndo.value.pop(); selectedBlockId.value=''; selectedChartId.value='' }
function redoReport() { if(!reportRedo.value.length)return; reportUndo.value.push(reportSnapshot()); selectedReport.value=reportRedo.value.pop(); selectedBlockId.value=''; selectedChartId.value='' }
async function loadReportVersions() { if(!selectedReport.value)return; reportVersions.value=await api(`/api/v1/reports/${selectedReport.value.id}/versions`); showVersionHistory.value=true }
async function restoreVersion(version) { if(!window.confirm('恢复此历史版本？当前内容会先自动保存为一个版本。'))return; selectedReport.value=await api(`/api/v1/reports/${selectedReport.value.id}/versions/${version.id}/restore`,{method:'POST'}); reportVersions.value=await api(`/api/v1/reports/${selectedReport.value.id}/versions`); savedReportContent.value=reportContent(); reports.value=reports.value.map(r=>r.id===selectedReport.value.id?selectedReport.value:r); notice.value='历史版本已恢复' }

async function saveReport() {
  if (!selectedReport.value) return
  saving.value = true
  try {
    selectedReport.value.document.title = selectedReport.value.title
    const saved = await api(`/api/v1/reports/${selectedReport.value.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: selectedReport.value.title, document: selectedReport.value.document }) })
    selectedReport.value = saved; reports.value = reports.value.map(item => item.id === saved.id ? saved : item); notice.value = '报告已保存'
    savedReportContent.value = reportContent()
  } catch (error) { notice.value = error.message } finally { saving.value = false }
}

function selectBlock(block) { selectedBlockId.value = block.id; if (block.chart_id) selectedChartId.value = block.chart_id }
async function locateClaim(item) {
  const id=item.target_kind==='block'?item.target_id:`block-${item.target_id}`
  const block=reportDocument.value?.blocks.find(b=>b.id===id)
  if(!block) { notice.value='对应正文已删除；请检查结构化结论与正文是否一致'; return }
  selectBlock(block)
  await nextTick()
  document.querySelector('.paper .canvas-block.selected')?.scrollIntoView({block:'center',behavior:'smooth'})
}
function updateBlock(block, event) { block.content = event.target.innerText }
function addTextBlock(kind = 'paragraph') {
  if (!reportDocument.value) return
  rememberReport()
  const block = { id: `block-${Date.now()}`, kind, content: kind === 'heading' ? '新标题' : '在这里输入报告内容…', chart_id: null, evidence_ids: [] }
  reportDocument.value.blocks.push(block); selectedBlockId.value = block.id
}
function addChart(type = 'bar') {
  if (!reportDocument.value) return
  rememberReport()
  const chart = { id: `chart-${Date.now()}`, title: '新图表', chart_type: type, x: null, y: null, series: [], description: '从右侧属性面板选择字段。', data: [], evidence_ids: [], position: { x: 0, y: 0, w: 8, h: 5 }, style: { palette:'insight',show_legend:true,show_labels:false,number_format:'compact',height:320 } }
  const block = { id: `block-${Date.now() + 1}`, kind: 'chart', content: '', chart_id: chart.id, evidence_ids: [] }
  reportDocument.value.charts.push(chart); reportDocument.value.blocks.push(block); selectedChartId.value = chart.id; selectedBlockId.value = block.id
}
function removeSelectedBlock() {
  if (!selectedBlock.value || !window.confirm('从报告中删除选中的对象？')) return
  rememberReport()
  const chartId = selectedBlock.value.chart_id
  reportDocument.value.blocks = reportDocument.value.blocks.filter(item => item.id !== selectedBlockId.value)
  if (chartId) reportDocument.value.charts = reportDocument.value.charts.filter(item => item.id !== chartId)
  selectedBlockId.value = reportDocument.value.blocks[0]?.id || ''; selectedChartId.value = ''
}
function moveBlock(offset) {
  const blocks = reportDocument.value?.blocks || []; const index = blocks.findIndex(item => item.id === selectedBlockId.value); const target = index + offset
  if (index < 0 || target < 0 || target >= blocks.length) return
  rememberReport()
  const [item] = blocks.splice(index, 1); blocks.splice(target, 0, item)
}
function startBlockDrag(event, block) {
  draggedBlockId.value = block.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', block.id)
}
function dropBlock(event, targetBlock) {
  const blocks = reportDocument.value?.blocks || []
  const sourceId = event.dataTransfer.getData('text/plain') || draggedBlockId.value
  const sourceIndex = blocks.findIndex(item => item.id === sourceId)
  const targetIndex = blocks.findIndex(item => item.id === targetBlock.id)
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return
  rememberReport()
  const [item] = blocks.splice(sourceIndex, 1)
  blocks.splice(targetIndex, 0, item)
  selectedBlockId.value = item.id
  draggedBlockId.value = ''
  notice.value = '报告对象顺序已调整，保存后写入版本历史。'
}
function finishBlockDrag() { draggedBlockId.value = '' }
function persistReportSort() { localStorage.setItem('insight-report-sort', reportSort.value) }
function duplicateSelectedBlock() {
  const block = selectedBlock.value
  if (!block || !reportDocument.value) return
  rememberReport()
  const copy = JSON.parse(JSON.stringify(block)); copy.id = `block-${Date.now()}`
  if (copy.chart_id) {
    const original = reportDocument.value.charts.find(item => item.id === copy.chart_id)
    if (original) { const chart = JSON.parse(JSON.stringify(original)); chart.id = `chart-${Date.now()+1}`; chart.title = `${chart.title}（副本）`; reportDocument.value.charts.push(chart); copy.chart_id = chart.id }
  }
  const index = reportDocument.value.blocks.findIndex(item => item.id === block.id)
  reportDocument.value.blocks.splice(index + 1, 0, copy); selectBlock(copy)
}
function openBlockMenu(event, block) {
  event.preventDefault(); selectBlock(block)
  contextMenu.value = { x:event.clientX, y:event.clientY, kind:'block', blockId:block.id, items:[
    {id:'edit',label:block.kind==='chart'?'编辑图表':'编辑对象',icon:'✎'},
    ...(block.kind==='chart' ? [{id:'ai-optimize',label:'AI 优化图表',icon:'✦'}] : []), {id:'duplicate',label:'复制对象',icon:'□'},
    {id:'up',label:'上移',icon:'↑'}, {id:'down',label:'下移',icon:'↓'}, {id:'remove',label:'删除对象',icon:'×',danger:true},
  ] }
}
function openAiChartAssistant() {
  if (!selectedReport.value || !selectedChart.value) return notice.value='请先在报告中选择一张已保存的图表。'
  aiChartInstruction.value = ''
  section.value = 'editor'
  aiChartDrawerOpen.value = true
}
function closeAiChartAssistant() { aiChartDrawerOpen.value = false; aiChartInstruction.value = '' }
function acceptAiChartSaved(report) {
  selectedReport.value = report
  savedReportContent.value = reportContent()
  reports.value = reports.value.map(item => item.id === report.id ? report : item)
  selectedChartId.value = selectedChartId.value || report.document.charts?.[0]?.id || ''
}
function openConversationMenu(event, conversation) {
  event.preventDefault()
  contextMenu.value={x:event.clientX,y:event.clientY,kind:'conversation',conversation,items:[{id:'rename',label:'重命名对话',icon:'✎'},{id:'delete',label:'删除对话',icon:'×',danger:true}]}
}
function handleContextCommand(id) {
  const menu=contextMenu.value; contextMenu.value=null; if (!menu) return
  if (menu.kind === 'block') {
    const block=reportDocument.value?.blocks.find(item=>item.id===menu.blockId); if (!block) return; selectBlock(block)
    if (id==='edit') { section.value='editor'; notice.value=block.kind==='chart'?'已选中图表，可在右侧属性面板编辑。':'已选中对象，可直接在画布或右侧属性面板编辑。' }
    else if (id==='ai-optimize') openAiChartAssistant()
    else if (id==='duplicate') duplicateSelectedBlock(); else if (id==='up') moveBlock(-1); else if (id==='down') moveBlock(1); else if (id==='remove') removeSelectedBlock()
    return
  }
  if (menu.kind === 'conversation') {
    if (id==='rename') renameConversation(menu.conversation)
    else if (id==='delete') removeConversation(menu.conversation)
  }
}
function blockFromContextTarget(target) {
  const source = target.closest?.('.canvas-block, .object-tree > button')
  if (!source || !reportDocument.value) return null
  const chartTitle = source.querySelector('.viz > header b')?.textContent?.trim()
  if (chartTitle) {
    const chart = reportDocument.value.charts.find(item => item.title === chartTitle)
    return reportDocument.value.blocks.find(item => item.chart_id === chart?.id) || null
  }
  const content = source.querySelector('h2, p, b')?.textContent?.trim()
  return reportDocument.value.blocks.find(item => item.content === content) || null
}
function captureEditorContextMenu(event) {
  if (section.value !== 'editor') return
  const block = blockFromContextTarget(event.target)
  if (block) openBlockMenu(event, block)
}
function addPageBreak() { if(!reportDocument.value)return; rememberReport(); const block={id:`break-${Date.now()}`,kind:'page_break',content:'',chart_id:null,evidence_ids:[],style:{}}; reportDocument.value.blocks.push(block); selectedBlockId.value=block.id }
async function insertWorkbenchChart(chart) {
  if(!selectedDatasetId.value)return notice.value='请先选择数据集'
  if(!selectedReport.value) {
    const result=await api('/api/v1/analysis/run',jsonOptions({workspace_id:workspace.value.id,dataset_id:selectedDatasetId.value,prompt:'创建一份用于承载人工图表的分析报告。',report_title:`${selectedDataset.value.name} 分析报告`}))
    selectedReport.value=await api(`/api/v1/reports/${result.report_id}`)
    reports.value=[selectedReport.value,...reports.value.filter(item=>item.id!==selectedReport.value.id)]
  }
  rememberReport()
  const next={...chart,id:`chart-${Date.now()}`}; const block={id:`block-${Date.now()+1}`,kind:'chart',content:'',chart_id:next.id,evidence_ids:next.evidence_ids||[],style:{}}
  reportDocument.value.charts.push(next); reportDocument.value.blocks.push(block); selectedChartId.value=next.id; selectedBlockId.value=block.id; section.value='editor'; notice.value='图表已插入报告，保存后生成历史版本'
}
function format(command, value = null) { document.execCommand(command, false, value) }
function exportPdf() {
  if(!reportQuality.value?.passed) { notice.value='当前稿件尚未通过质量核验，请先保存并处理待核验项。'; return }
  window.print()
}
function exportDocx() { if(selectedReport.value) window.location.href=`/api/v1/reports/${selectedReport.value.id}/export.docx` }

async function updateChartBinding(axis, value) {
  if (!selectedChart.value || !selectedDatasetId.value) return
  const xColumn = axis === 'x' ? value || null : selectedChart.value.x?.column || null
  const yColumn = axis === 'y' ? value || null : selectedChart.value.y?.column || null
  if (!yColumn) { selectedChart.value.x = xColumn ? { column: xColumn } : null; return }
  try {
    const aggregate = selectedChart.value.y?.aggregate || 'sum'
    const extraSeries = (selectedChart.value.series || []).map(item => item.column).filter(column => column && column !== yColumn).slice(0, 3)
    const result = await api(`/api/v1/datasets/${selectedDatasetId.value}/chart-preview`, jsonOptions({ workspace_id: workspace.value.id, x_column: xColumn, y_column: yColumn, series_columns: extraSeries, aggregate, limit: 20 }))
    selectedChart.value.x = xColumn ? { column: xColumn } : null
    selectedChart.value.y = { column: yColumn, aggregate }
    selectedChart.value.series = [{ column: yColumn, aggregate }, ...extraSeries.map(column => ({ column, aggregate }))]
    selectedChart.value.data = result.data
    selectedChart.value.title = xColumn ? `按 ${xColumn} 对比 ${yColumn}` : `${yColumn} ${aggregate}`
  } catch (error) { notice.value = error.message }
}

async function updateChartAggregate(value) {
  if (!selectedChart.value?.y?.column) return
  selectedChart.value.y.aggregate = value
  await updateChartBinding('x', selectedChart.value.x?.column || '')
}

async function saveProvider(provider) {
  const payload = { enabled: provider.enabled, is_default: provider.is_default, base_url: provider.base_url, model: provider.model, api_key: providerKeys.value[provider.provider] || null, clear_api_key: false, options: provider.options || {} }
  try {
    const saved = await api(`/api/v1/settings/providers/${provider.provider}?workspace_id=${workspace.value.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    providerKeys.value[provider.provider] = ''; providerStatus.value[provider.provider] = '设置已保存'
    if (saved.is_default) providers.value.forEach(item => { item.is_default = item.provider === saved.provider })
    providers.value = providers.value.map(item => item.provider === saved.provider ? saved : item)
  } catch (error) { providerStatus.value[provider.provider] = error.message }
}

async function testProvider(provider) {
  providerStatus.value[provider.provider] = '正在连接…'
  try {
    const result = await api(`/api/v1/settings/providers/${provider.provider}/test?workspace_id=${workspace.value.id}`, { method: 'POST' })
    providerStatus.value[provider.provider] = result.message + (result.latency_ms ? ` · ${result.latency_ms}ms` : '')
  } catch (error) { providerStatus.value[provider.provider] = error.message }
}

async function saveGeneralSettings() {
  const { workspace_id, ...payload } = appSettings.value
  try { appSettings.value = await api(`/api/v1/settings/app?workspace_id=${workspace.value.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); notice.value = '常规设置已保存' }
  catch (error) { notice.value = error.message }
}

async function createMcpServer(payload) {
  try {
    const saved = await api(`/api/v1/mcp/servers?workspace_id=${workspace.value.id}`, jsonOptions(payload))
    mcpServers.value = [saved, ...mcpServers.value]
    notice.value = 'MCP 服务已保存。点击“发现工具”后，AI 才能在计划中使用它。'
  } catch (error) { notice.value = error.message }
}

async function updateMcpServer(server) {
  try {
    const saved = await api(`/api/v1/mcp/servers/${server.id}?workspace_id=${workspace.value.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: server.name, url: server.url, enabled: server.enabled, transport: server.transport, tool_allowlist: server.tool_allowlist || [] }),
    })
    mcpServers.value = mcpServers.value.map(item => item.id === saved.id ? saved : item)
  } catch (error) { notice.value = error.message }
}

async function discoverMcpServer(server) {
  try {
    const result = await api(`/api/v1/mcp/servers/${server.id}/discover?workspace_id=${workspace.value.id}`, { method: 'POST' })
    mcpServers.value = await api(`/api/v1/mcp/servers?workspace_id=${workspace.value.id}`)
    notice.value = result.message
  } catch (error) { notice.value = error.message }
}

async function refreshIntegrations() {
  try {
    const [nextIntegrations, tools, resources] = await Promise.all([api('/api/v1/integrations'), api('/api/v1/tools'), workspace.value ? api(`/api/v1/integrations/superset/resources?workspace_id=${workspace.value.id}`).catch(()=>[]) : []])
    integrations.value = nextIntegrations
    toolPolicy.value = tools
    professionalDashboard.value = resources.find?.(item => item.resource_type === 'dashboard') || professionalDashboard.value
    notice.value = '集成状态已刷新'
  } catch (error) { notice.value = error.message }
}
async function getSupersetGuestToken(dashboardId) {
  return api(`/api/v1/integrations/superset/guest-token?workspace_id=${workspace.value.id}`, jsonOptions({ dashboard_id: dashboardId }))
}
async function bootstrapProfessionalDashboard() {
  try { professionalDashboard.value=await api(`/api/v1/integrations/superset/bootstrap-dashboard?workspace_id=${workspace.value.id}`,jsonOptions({title:`${workspace.value.name} 专业看板`,allowed_domains:[window.location.origin]})); notice.value='Superset 专业看板已创建或已修复嵌入配置' }
  catch(error){ notice.value=error.message }
}
async function repairProfessionalEmbed() {
  try { const result=await api(`/api/v1/integrations/superset/repair-embed?workspace_id=${workspace.value.id}`,jsonOptions({allowed_domains:[window.location.origin]})); if(professionalDashboard.value) professionalDashboard.value.embedded_id=result.embedded_id || professionalDashboard.value.embedded_id; notice.value='Superset 嵌入来源已修复，请稍候或刷新看板页面' }
  catch(error){ notice.value=error.message }
}

async function previewProfessionalPublish() {
  if (!selectedDataset.value) { notice.value='请先选择要发布的数据集'; return }
  try {
    professionalPreview.value=await api('/api/v1/integrations/superset/publish-preview',jsonOptions({
      workspace_id:workspace.value.id,dataset_id:selectedDataset.value.id,report_id:selectedReport.value?.dataset_id===selectedDataset.value.id?selectedReport.value.id:null,
      title:`${selectedDataset.value.name} 专业分析看板`,
    }))
  } catch(error){ notice.value=error.message }
}
async function publishProfessionalDashboard() {
  if (!professionalPreview.value || professionalPublishing.value) return
  professionalPublishing.value=true
  try {
    professionalDashboard.value=await api('/api/v1/integrations/superset/publish',jsonOptions({
      workspace_id:workspace.value.id,dataset_id:selectedDataset.value.id,report_id:selectedReport.value?.dataset_id===selectedDataset.value.id?selectedReport.value.id:null,
      title:professionalPreview.value.title,allowed_domains:[window.location.origin],
    }))
    professionalPreview.value=null; notice.value=`已发布 ${professionalDashboard.value.charts.length} 个 Superset 图表`
    await refreshIntegrations()
  } catch(error){ notice.value=error.message } finally { professionalPublishing.value=false }
}

onMounted(() => { refresh(); window.addEventListener('contextmenu', captureEditorContextMenu); window.addEventListener('beforeunload',beforeReportUnload) })
onBeforeUnmount(() => { window.removeEventListener('contextmenu', captureEditorContextMenu); window.removeEventListener('beforeunload',beforeReportUnload) })
</script>

<template>
  <div class="product-shell" :data-theme="appSettings?.theme || 'light'">
    <aside class="app-rail">
      <button class="logo" title="Insight Studio">I</button>
      <button :class="{ active: section === 'chat' }" title="AI 分析" @click="section = 'chat'">✦<small>分析</small></button>
      <button :class="{ active: section === 'charts' }" title="图表工作台" @click="section = 'charts'">▥<small>图表</small></button>
      <button :class="{ active: section === 'professional' }" title="Superset 专业模式" @click="section = 'professional'; refreshIntegrations()">S<small>专业</small></button>
      <button :class="{ active: section === 'editor' }" title="报告编辑" @click="section = 'editor'">▤<small>编辑</small></button>
      <button :class="{ active: section === 'reports' }" title="报告库" @click="section = 'reports'">▦<small>报告</small></button>
      <button :class="{ active: section === 'templates' }" title="Word 报告模板" @click="section = 'templates'">W<small>模板</small></button>
      <button :class="{ active: section === 'data' }" title="数据" @click="section = 'data'">◫<small>数据</small></button>
      <button class="rail-bottom" :class="{ active: section === 'settings' }" title="设置" @click="section = 'settings'">⚙<small>设置</small></button>
    </aside>

    <aside v-if="section === 'chat'" class="conversation-panel">
      <div class="conversation-head"><div class="wordmark"><b>Insight</b><span>Studio</span></div><button class="square-btn" @click="newConversation">＋</button></div>
      <button class="new-chat" @click="newConversation"><span>✎</span> 新建分析对话 <kbd>Ctrl K</kbd></button>
      <div class="conversation-label">最近对话 <span>{{ conversations.length }}</span></div>
      <div class="batch-controls"><button :disabled="conversationBatchBusy" @click="toggleConversationTrash">{{ showConversationTrash?'返回对话':'对话回收站' }}</button><button @click="conversationSelection=visibleConversations.map(c=>c.id)">全选当前列表</button><button @click="conversationSelection=[]">清空选择</button><button :disabled="conversationBatchBusy || !conversationSelection.length || sending" @click="batchConversations">{{ showConversationTrash?'恢复':'删除' }}所选（{{ conversationSelection.length }}）</button></div>
      <div class="conversation-list">
        <div v-for="item in visibleConversations" :key="item.id" class="conversation-row" :class="{ active: activeConversationId === item.id }" @contextmenu="!showConversationTrash && openConversationMenu($event,item)">
          <input v-model="conversationSelection" type="checkbox" :value="item.id" :aria-label="`选择会话 ${item.title}`" :disabled="conversationBatchBusy">
          <button @click="openConversation(item)"><span>◌</span><div><b>{{ item.title }}</b><small>{{ new Date(item.updated_at).toLocaleDateString() }}</small></div></button>
          <div v-if="!showConversationTrash" class="row-actions"><button title="重命名" @click="renameConversation(item)">✎</button><button title="删除" @click="removeConversation(item)">×</button></div>
        </div>
      </div>
      <div class="workspace-summary"><span class="avatar">我</span><div><b>{{ workspace?.name }}</b><small>{{ datasets.length }} 数据集 · {{ reports.length }} 报告</small></div></div>
    </aside>

    <main class="workspace-main">
      <div v-if="notice" class="toast" @click="notice = ''">{{ notice }} <span>×</span></div>
      <div v-if="bootError" class="service-error" role="alert"><div><b>工作台数据未载入</b><span>{{ bootError }}。请确认 start.bat 的 API 窗口仍在运行。</span></div><button :disabled="booting" @click="refresh">{{ booting ? '正在重试…' : '重新连接' }}</button></div>

      <template v-if="section === 'chat'">
        <ReportRequirements :value="analysisOptions.report_requirements" :disabled="sending" @change="analysisOptions.report_requirements=$event" />
        <header class="chat-topbar"><div><b>{{ activeConversation?.title || '新分析' }}</b><span>所有计算均保留证据链</span></div><div class="topbar-controls"><label>数据<select v-model="selectedDatasetId"><option value="">未选择</option><option v-for="item in datasets" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><button class="model-chip" @click="section = 'settings'"><i :class="{ on: activeProvider }" />{{ activeProvider ? `${activeProvider.provider} · ${activeProvider.model}` : '本地助手' }}⌄</button></div></header>
        <div class="chat-layout">
          <section ref="chatScroll" class="message-flow">
            <div v-if="!messages.length" class="chat-welcome"><span class="welcome-mark">✦</span><h1>今天想从数据里发现什么？</h1><p>像与分析师对话一样逐步追问。系统会选择受控工具、展示依据，并把成熟结论送入报告编辑器。</p><div class="welcome-actions"><button @click="importSample"><b>载入示例数据</b><span>48 条虚构零售记录，一键体验</span></button><button @click="fileInput?.click()"><b>上传我的数据</b><span>CSV / Excel，最大 50 MB</span></button></div><div v-if="selectedDataset" class="prompt-starters"><button @click="sendMessage('先介绍数据质量和字段含义，再告诉我最值得关注的三个问题。')">检查数据质量与关键问题 →</button><button @click="sendMessage('分析各区域销售额和利润差异，指出高退货率品类。')">比较区域、利润与退货 →</button><button @click="sendMessage('生成一份管理层月度经营报告，包含结论、图表和行动建议。')">生成管理层报告 →</button></div></div>
            <article v-for="item in messages" :key="item.id" :class="['message', item.role]">
              <div class="message-avatar">{{ item.role === 'user' ? '我' : '✦' }}</div>
              <div class="message-body">
                <div class="message-label">{{ item.role === 'user' ? '你' : 'Insight AI' }}<span v-if="item.message_meta?.provider">{{ item.message_meta.provider }}</span></div>
                <div class="markdown-content" v-html="renderMarkdown(item.content)" />
                <AnalysisComponentResults :results="item.message_meta?.component_results || []" />
                <div v-if="item.message_meta?.usage" class="usage-strip"><span>{{ item.message_meta.usage.model }}</span><b v-if="item.message_meta.usage.usage_available !== false">{{ item.message_meta.usage.total_tokens.toLocaleString() }} tokens</b><em v-else>服务商未返回 Token</em><span>{{ (item.message_meta.usage.latency_ms / 1000).toFixed(1) }}s</span><details><summary>Token 明细</summary><div>输入 {{ item.message_meta.usage.prompt_tokens }} · 缓存命中 {{ item.message_meta.usage.cache_hit_tokens }} · 缓存未命中 {{ item.message_meta.usage.cache_miss_tokens }} · 输出 {{ item.message_meta.usage.completion_tokens }}</div></details></div>
                <AnalysisIntakeCard v-if="item.message_meta?.intake?.should_pause" :intake="item.message_meta.intake" :submitting="intakeSubmittingId === item.id" @submit="resolveIntake(item, $event)" />
                <section v-else-if="item.message_meta?.analysis_plan" class="analysis-plan-card">
                  <header><div><span>AI 分析计划 <em v-if="item.message_meta.planning?.provider">· {{ item.message_meta.planning.provider }}</em></span><b>{{ item.message_meta.analysis_plan.objective }}</b><small class="plan-mode">{{ ({safe:'安全模式',partial:'部分允许',full:'副本完全访问'})[item.message_meta.analysis_plan.execution_mode] || '安全模式' }} · {{ item.message_meta.analysis_plan.mode_reason }}</small></div><i :class="item.message_meta.analysis_plan.status">{{ planStatusLabel(item.message_meta.analysis_plan.status) }}</i></header>
                  <ol><li v-for="(step,index) in item.message_meta.analysis_plan.steps" :key="step.id"><span>{{ index + 1 }}</span><div><b>{{ step.title }}</b><small>{{ step.description }}</small><code>{{ step.tool }}</code></div><em :class="step.risk">{{ step.risk === 'high' ? '外部发布' : step.risk === 'medium' ? '生成草稿' : '只读' }}</em></li></ol>
                  <footer v-if="item.message_meta.analysis_plan.status === 'pending'"><button class="plan-cancel" @click="cancelPlan(item)">放弃计划</button><span v-if="item.message_meta.analysis_plan.blocked" class="plan-running">当前权限禁止计划中的工具，请切换权限模式后重新生成计划。</span><button v-else-if="item.message_meta.chart_edit" class="plan-approve" @click="openChartPlan(item)">查看并比较方案 →</button><button v-else-if="item.message_meta.analysis_plan.requires_approval" class="plan-approve" @click="executePlan(item, true)">批准并运行 →</button><span v-else class="plan-running">服务端策略已允许，正在自动运行…</span></footer>
                  <div v-else-if="item.message_meta.analysis_plan.status === 'running'" class="plan-running"><i/><span>正在执行 {{ runForPlan(item.id)?.progress?.title || '受控工具' }}（{{ runForPlan(item.id)?.progress?.completed_steps || 0 }}/{{ runForPlan(item.id)?.progress?.total_steps || item.message_meta.analysis_plan.steps.length }}）…</span><button @click="cancelPlan(item)">取消运行</button></div>
                </section>
                <ExecutionDetails v-if="item.message_meta?.analysis_plan" :runs="analysisRuns.filter(r=>r.plan_message_id===item.id)" :request="api" :workspace-id="workspace?.id" />
                <ExecutionDetails v-if="item.message_meta?.tool_runs?.length" :tools="item.message_meta.tool_runs" :evidence="item.message_meta.evidence || []" />
                <details v-if="item.message_meta?.evidence?.length" class="chat-evidence-card">
                  <summary>查看 {{ item.message_meta.evidence.length }} 条结论证据</summary>
                  <article v-for="evidence in item.message_meta.evidence" :key="evidence.id"><header><b>{{ evidence.statement }}</b><code>{{ evidence.id }}</code></header><p>{{ evidence.method }}</p><div><span>计算值</span><strong>{{ evidence.value }}</strong></div><small v-if="evidence.source_columns?.length">来源字段：{{ evidence.source_columns.join('、') }}</small><details v-if="evidence.code" class="run-code"><summary>查看代码 / 方法</summary><pre>{{ evidence.code }}</pre></details></article>
                </details>
                <section v-if="item.message_meta?.recommendations?.length" class="recommendation-card"><header><b>可执行建议</b><span>含风险与验证方法</span></header><article v-for="advice in item.message_meta.recommendations" :key="advice.id"><div><b>{{ advice.recommendation }}</b><p>{{ advice.finding }}</p><small>风险：{{ advice.risk }}</small><small>验证：{{ advice.validation }}</small></div><em :class="advice.priority">{{ advice.priority }}</em></article></section>
                <button v-if="item.message_meta?.template_artifact" class="artifact-card" @click="downloadArtifact(item.message_meta.template_artifact)"><span>W</span><div><b>固定格式 Word 报告已生成</b><small>下载已填充的 DOCX 模板</small></div><strong>下载 →</strong></button>
                <button v-if="item.message_meta?.report_id" class="artifact-card" @click="openReport(item.message_meta.report_id)"><span>▤</span><div><b>可编辑分析报告已生成</b><small>打开 Word / Tableau 式专业编辑器</small></div><strong>打开 →</strong></button>
              </div>
            </article>
            <button v-if="sending || activeChatRuns.length" class="chat-stop outline-btn" :disabled="stopBusy" @click="stopChat">■ {{ stopBusy?'正在请求中断…':'停止当前对话任务' }}</button>
            <article v-if="sending" class="message assistant"><div class="message-avatar">✦</div><div class="message-body"><div class="message-label">Insight AI</div><div class="thinking"><i/><i/><i/> 正在理解问题并生成计划</div></div></article>
          </section>
          <aside class="context-panel"><div class="context-title"><b>当前上下文</b><span class="live-dot">已连接</span></div><template v-if="selectedDataset"><div class="dataset-card"><span>▤</span><div><b>{{ selectedDataset.name }}</b><small>{{ selectedDataset.profile.row_count?.toLocaleString() }} 行 · {{ selectedDataset.profile.column_count }} 列</small></div></div><div class="context-section"><b>字段</b><div class="field-list"><div v-for="field in selectedColumns.slice(0, 12)" :key="field.name"><span>{{ field.name }}</span><code>{{ field.dtype }}</code></div></div></div><div class="context-section"><b>快捷操作</b><button @click="sendMessage('检查缺失值、重复值和可能的数据质量问题。')">⌁ 数据质量检查</button><button @click="sendMessage('生成一份管理层报告，包含图表和行动建议。')">▤ 生成专业报告</button></div></template><div v-else class="context-empty"><span>◫</span><p>选择一份数据，AI 才能基于真实字段和统计结果回答。</p><button @click="importSample">载入示例</button></div><details v-if="analysisRuns.length" class="run-history"><summary>运行历史（{{ analysisRuns.length }}）</summary><article v-for="run in analysisRuns" :key="run.id"><div><b>{{ run.status === 'completed' ? '已完成' : run.status === 'failed' ? '失败' : run.status === 'cancelled' ? '已取消' : run.status === 'interrupted' ? '被中断' : '运行中' }}</b><small>第 {{ run.attempt }} 次 · {{ new Date(run.created_at).toLocaleString() }}</small></div><button v-if="['queued','running'].includes(run.status)" @click="cancelAnalysisRun(run)">取消</button><button v-else-if="['failed','cancelled','interrupted'].includes(run.status)" @click="retryAnalysisRun(run)">重试</button></article></details><div class="safety-card"><b>{{ permissionMode.label }}</b><p>{{ permissionMode.hint }} 生成代码始终只在隔离沙箱中运行，不会直接在宿主机执行。</p></div></aside>
        </div>
        <div class="composer-wrap"><div class="analysis-toolbelt"><button :class="{active:analysisOptions.forecast.enabled}" @click="analysisOptions.forecast.enabled=!analysisOptions.forecast.enabled">⌁ 预测</button><button :class="{active:analysisOptions.include_recommendations}" @click="analysisOptions.include_recommendations=!analysisOptions.include_recommendations">✓ 行动建议</button><button :class="{active:analysisOptions.include_report}" @click="analysisOptions.include_report=!analysisOptions.include_report">▤ 生成报告</button><button :disabled="!selectedReport || !selectedChart" title="先在报告中选择一张图表" @click="openAiChartAssistant">✦ 优化当前图表</button><label class="template-select">W 模板<select v-model="analysisOptions.template_id"><option :value="null">不使用</option><option v-for="template in reportTemplates" :key="template.id" :value="template.id">{{ template.name }}</option></select></label><button @click="section='templates'">管理模板</button><span>图表修改会先生成计划、预览，保存仍需单独批准</span></div><div v-if="analysisOptions.forecast.enabled" class="forecast-options"><label>日期<select v-model="analysisOptions.forecast.date_column"><option :value="null">自动识别</option><option v-for="field in selectedColumns" :key="field.name" :value="field.name">{{ field.name }}</option></select></label><label>指标<select v-model="analysisOptions.forecast.target_column"><option :value="null">自动识别</option><option v-for="field in selectedColumns" :key="field.name" :value="field.name">{{ field.name }}</option></select></label><label>周期<input v-model.number="analysisOptions.forecast.horizon" type="number" min="1" max="36" /></label><label>频率<select v-model="analysisOptions.forecast.frequency"><option value="MS">月</option><option value="QS">季度</option><option value="W">周</option><option value="D">日</option></select></label></div><div class="composer"><textarea v-model="composer" rows="1" placeholder="向数据提问，或要求生成报告…" @keydown="composerKey"/><div class="composer-actions"><div><label class="permission-mode" :title="permissionMode.hint">权限<select v-model="executionPermissionMode"><option value="safe">安全</option><option value="partial">部分允许</option><option value="full">副本完全访问</option></select></label><AnalysisCapabilities :value="analysisCapabilities" :mode="clarificationMode" :status="clarificationLabel" :busy="capabilitySaving" :ready="!!workspace &amp;&amp; !booting" @change="saveCapabilities" @mode="setClarificationMode" /><button title="上传数据" @click="fileInput?.click()">＋</button><span v-if="selectedDataset">▤ {{ selectedDataset.name }}</span></div><button class="send-btn" :disabled="sending || !composer.trim()" @click="sendMessage()">↑</button></div></div><small>{{ permissionMode.hint }} · Enter 发送 · Shift+Enter 换行 · 模型结论可能出错，请核对证据</small></div>
      </template>

      <template v-else-if="section === 'editor'">
        <div v-if="!selectedReport" class="blank-page"><span>▤</span><h2>还没有打开报告</h2><p>在对话中生成报告，或从报告库选择一份。</p><button class="primary" @click="section = 'reports'">打开报告库</button></div>
        <div v-else class="editor-shell">
          <header class="document-titlebar"><button class="back-btn" @click="section = 'reports'">‹</button><div><input v-model="selectedReport.title"/><span>{{ ({draft:'草稿',in_review:'审核中',approved:'已批准',published:'已发布'})[reportWorkflow?.status] || '草稿' }} · {{ workspace?.name }}</span><span v-if="reportQuality" :title="reportQualityHint" :class="['report-quality-badge',{failed:!reportQuality.passed}]">质量检查 {{ reportQuality.score }}/100 · {{ reportQuality.passed ? '通过' : `${reportQuality.issues?.length || 0} 项待修复` }}</span></div><div><button class="outline-btn" @click="showCollaboration=!showCollaboration">协作 {{ reportComments.filter(i=>!i.resolved).length || '' }}</button><button class="outline-btn" @click="section='charts'">图表工作台</button><button class="outline-btn" :disabled="reportQuality && !reportQuality.passed" :title="reportQuality && !reportQuality.passed ? reportQualityHint : '导出通过质量检查的 DOCX'" @click="exportDocx">导出 DOCX</button><button class="outline-btn" @click="exportPdf">打印 / PDF</button><button class="primary" :disabled="saving" @click="saveReport">{{ saving ? '保存中…' : '保存' }}</button></div></header>
          <ReportClaimChecks :quality="reportQuality" :dirty="reportDirty" :proposal="reportRepair" :busy="repairBusy" @locate="locateClaim" @preview="previewReportRepair" @apply="applyReportRepair" @discard="reportRepair=null" />
          <nav class="ribbon-tabs"><button v-for="tab in ['开始','插入','布局','数据','审阅']" :key="tab" :class="{ active: ribbonTab === tab }" @click="ribbonTab = tab">{{ tab }}</button></nav>
          <div class="ribbon">
            <template v-if="ribbonTab === '开始'"><div class="ribbon-group"><button :disabled="!reportUndo.length" @click="undoReport">↶ 撤销</button><button :disabled="!reportRedo.length" @click="redoReport">↷ 重做</button><select><option>微软雅黑</option><option>宋体</option><option>Arial</option></select><select v-model="fontSize" @change="format('fontSize', 3)"><option>12</option><option>14</option><option>16</option><option>20</option><option>28</option></select></div><div class="ribbon-group icon-buttons"><button @mousedown.prevent="format('bold')"><b>B</b></button><button @mousedown.prevent="format('italic')"><i>I</i></button><button @mousedown.prevent="format('underline')"><u>U</u></button><button @mousedown.prevent="format('foreColor', '#1d6b4f')">A̲</button></div><div class="ribbon-group icon-buttons"><button @mousedown.prevent="format('justifyLeft')">≡</button><button @mousedown.prevent="format('justifyCenter')">≣</button><button @mousedown.prevent="format('insertUnorderedList')">☷</button></div><div class="ribbon-group"><button @click="moveBlock(-1)">上移</button><button @click="moveBlock(1)">下移</button><button class="danger" @click="removeSelectedBlock">删除对象</button></div></template>
            <template v-else-if="ribbonTab === '插入'"><div class="ribbon-group insert-buttons"><button @click="addTextBlock('heading')"><span>T</span>标题</button><button @click="addTextBlock('paragraph')"><span>¶</span>正文</button><button @click="addTextBlock('callout')"><span>!</span>提示</button><button @click="section='charts'"><span>▥</span>图表工作台</button><button @click="addChart('kpi')"><span>12</span>指标卡</button><button @click="addChart('table')"><span>▦</span>表格</button><button @click="addPageBreak"><span>↵</span>分页符</button></div></template>
            <template v-else-if="ribbonTab === '布局'"><div class="ribbon-group"><label>页面<select v-model="pageMode"><option value="a4-portrait">A4 纵向</option><option value="a4-landscape">A4 横向</option><option value="screen">16:9 画布</option></select></label><label>页边距<select><option>标准</option><option>窄</option><option>宽</option></select></label></div><div class="ribbon-group"><button @click="optimizeDashboardLayout">AI 优化仪表板布局</button><span class="ribbon-hint">按 12 列栅格生成建议，应用前确认并保留历史版本。</span></div></template>
            <template v-else-if="ribbonTab === '数据'"><div class="ribbon-group"><label>数据集<select v-model="selectedDatasetId"><option v-for="item in datasets" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><button :disabled="!selectedChart" @click="openAiChartAssistant">AI 优化当前图表</button><button :disabled="!selectedChart" @click="updateChartBinding('x', selectedChart?.x?.column || '')">刷新完整数据</button><button disabled title="筛选器编辑将在下一阶段接入">编辑筛选器</button></div></template>
            <template v-else><div class="ribbon-group"><button @click="loadReportVersions">版本历史</button><button v-if="reportWorkflow?.status==='draft'" @click="transitionReport('submit')">提交审核</button><button v-if="reportWorkflow?.status==='in_review' && teamContext?.permissions?.includes('report.publish')" @click="transitionReport('approve')">批准</button><button v-if="reportWorkflow?.status==='approved' && teamContext?.permissions?.includes('report.publish')" @click="transitionReport('publish')">正式发布</button><button v-if="['in_review','approved'].includes(reportWorkflow?.status)" @click="transitionReport('return')">退回草稿</button><button v-if="reportWorkflow?.status==='published'" @click="createShareLink">生成分享链接</button><span class="ribbon-hint">发布必须经过提交、批准，所有操作进入审计日志</span></div></template>
          </div>
          <div class="editor-workspace">
            <aside class="object-tree"><header><div><b>文档结构</b><small>拖拽对象可排序</small></div><button @click="addTextBlock('paragraph')">＋</button></header><button v-for="(block,index) in reportDocument.blocks" :key="block.id" draggable="true" :class="{ active: selectedBlockId === block.id, dragging: draggedBlockId === block.id }" :aria-label="`对象 ${index + 1}：${block.content || reportDocument.charts.find(c => c.id === block.chart_id)?.title || '图表'}`" @click="selectBlock(block)" @dragstart="startBlockDrag($event, block)" @dragover.prevent @drop.prevent="dropBlock($event, block)" @dragend="finishBlockDrag"><span class="drag-handle" title="拖拽排序">⋮⋮</span><span>{{ block.kind === 'chart' ? '▥' : block.kind === 'heading' ? 'H' : '¶' }}</span><div><b>{{ block.content || reportDocument.charts.find(c => c.id === block.chart_id)?.title || '图表' }}</b><small>对象 {{ index + 1 }}</small></div></button></aside>
            <section class="page-stage"><article :class="['paper',pageMode]"><div class="paper-kicker">析据 XIJU · 数据分析报告</div><h1 contenteditable @focus="rememberReport" @blur="selectedReport.title = $event.target.innerText">{{ selectedReport.title }}</h1><p class="paper-summary" contenteditable @focus="rememberReport" @blur="reportDocument.summary = $event.target.innerText">{{ reportDocument.summary }}</p><div v-for="block in reportDocument.blocks" :key="block.id" :class="['canvas-block', block.kind, { selected: selectedBlockId === block.id }]" @click="selectBlock(block)"><h2 v-if="block.kind === 'heading'" contenteditable @focus="rememberReport" @blur="updateBlock(block,$event)">{{ block.content }}</h2><div v-else-if="block.kind === 'page_break'" class="page-break-line"><span>分页符</span></div><div v-else-if="block.kind !== 'chart'" class="narrative-block"><h3 v-if="block.style?.headline">{{ block.style.headline }}</h3><p contenteditable @focus="rememberReport" @blur="updateBlock(block,$event)">{{ block.content }}</p></div><ChartPreview v-else :chart="reportDocument.charts.find(item => item.id === block.chart_id)" :selected="selectedChartId === block.chart_id" @select="selectedChartId = block.chart_id"/><details v-if="block.evidence_ids?.length" class="evidence-disclosure" @click.stop><summary>查看 {{ block.evidence_ids.length }} 条依据</summary><article v-for="id in block.evidence_ids" :key="id"><b>{{ reportDocument.evidence.find(item => item.id === id)?.statement || id }}</b><p>{{ reportDocument.evidence.find(item => item.id === id)?.method }}</p><code>{{ reportDocument.evidence.find(item => item.id === id)?.value }}</code><pre v-if="reportDocument.evidence.find(item => item.id === id)?.code">{{ reportDocument.evidence.find(item => item.id === id)?.code }}</pre></article></details></div><footer>由析据 Xiju 生成 · {{ new Date().toLocaleDateString() }}</footer></article></section>
            <aside class="property-panel"><header><b>属性</b><span>{{ selectedBlock?.kind || '文档' }}</span></header><template v-if="selectedBlock && selectedBlock.kind !== 'chart'"><label>对象类型<select v-model="selectedBlock.kind"><option value="heading">标题</option><option value="paragraph">正文</option><option value="insight">洞察卡片</option><option value="callout">提示框</option><option value="page_break">分页符</option></select></label><label v-if="selectedBlock.style?.headline">结论标题<input v-model="selectedBlock.style.headline"/></label><label v-if="selectedBlock.kind!=='page_break'">内容<textarea v-model="selectedBlock.content" rows="7"/></label><label>证据引用<input :value="selectedBlock.evidence_ids?.join(', ')" disabled/></label><div v-if="selectedBlock.evidence_ids?.length" class="evidence-box"><b>证据链</b><details v-for="id in selectedBlock.evidence_ids" :key="id"><summary>{{ reportDocument.evidence.find(item => item.id === id)?.statement || id }}</summary><p>{{ reportDocument.evidence.find(item => item.id === id)?.method }}</p><code>{{ reportDocument.evidence.find(item => item.id === id)?.value }}</code></details></div></template><template v-else-if="selectedChart"><button class="primary ai-chart-action" @click="openAiChartAssistant">✦ AI 优化当前图表</button><label>图表标题<input v-model="selectedChart.title"/></label><label>图表类型<select v-model="selectedChart.chart_type"><option v-for="item in [['bar','柱状图'],['line','折线图'],['area','面积图'],['combo','组合图'],['scatter','散点图'],['bubble','气泡图'],['pie','饼图'],['donut','环形图'],['table','数据表'],['highlight_table','高亮表'],['heatmap','热力图'],['treemap','树状图'],['histogram','直方图'],['boxplot','盒须图'],['waterfall','瀑布图'],['pareto','帕累托图'],['control_chart','控制图'],['gauge','仪表盘'],['radar','雷达图'],['density_plot','密度散点'],['kpi','指标卡']]" :key="item[0]" :value="item[0]">{{ item[1] }}</option></select></label><div class="property-grid"><label>维度<select :value="selectedChart.x?.column || ''" @change="updateChartBinding('x', $event.target.value)"><option value="">无（显示单指标）</option><option v-for="field in selectedColumns" :key="field.name" :value="field.name">{{ field.name }}</option></select></label><label>指标<select :value="selectedChart.y?.column || ''" @change="updateChartBinding('y', $event.target.value)"><option value="" disabled>选择指标</option><option v-for="field in selectedColumns" :key="field.name" :value="field.name">{{ field.name }}</option></select></label></div><label>聚合<select :value="selectedChart.y?.aggregate || 'sum'" @change="updateChartAggregate($event.target.value)"><option value="sum">求和</option><option value="avg">平均值</option><option value="count">计数</option><option value="min">最小值</option><option value="max">最大值</option></select></label><label>配色<select v-model="selectedChart.style.palette"><option value="insight">Insight</option><option value="business">商务</option><option value="risk">风险</option><option value="accessible">无障碍</option></select></label><label class="check"><input v-model="selectedChart.style.show_legend" type="checkbox">显示图例</label><label>图表说明<textarea v-model="selectedChart.description" rows="4"/></label><ChartPreview :chart="selectedChart" compact/><div class="evidence-box"><b>证据链</b><details v-for="id in selectedChart.evidence_ids" :key="id"><summary>{{ reportDocument.evidence.find(item => item.id === id)?.statement || id }}</summary><p>{{ reportDocument.evidence.find(item => item.id === id)?.method }}</p><code>{{ reportDocument.evidence.find(item => item.id === id)?.value }}</code></details></div></template><div v-else class="property-empty">选择页面中的文本或图表进行编辑。</div></aside>
            <aside v-if="showVersionHistory" class="version-drawer"><header><b>版本历史</b><button @click="showVersionHistory=false">×</button></header><p>保存前的内容会自动形成一个可恢复版本。</p><article v-for="version in reportVersions" :key="version.id"><div><b>{{ version.title }}</b><small>{{ new Date(version.created_at).toLocaleString() }}</small></div><button @click="restoreVersion(version)">恢复</button></article><div v-if="!reportVersions.length" class="property-empty">保存一次报告后将在这里看到历史版本。</div></aside>
            <aside v-if="showCollaboration" class="version-drawer collaboration-drawer"><header><b>审核与批注</b><button @click="showCollaboration=false">×</button></header><div class="workflow-state"><small>当前状态</small><b>{{ ({draft:'草稿',in_review:'审核中',approved:'已批准',published:'已发布'})[reportWorkflow?.status] }}</b></div><textarea v-model="commentDraft" rows="3" placeholder="对当前选中对象添加批注…"/><button class="primary" @click="addReportComment">添加批注</button><article v-for="item in reportComments" :key="item.id" :class="{resolved:item.resolved}"><div><b>{{ item.author_name }}</b><small>{{ item.block_id ? '对象批注' : '全文批注' }} · {{ new Date(item.created_at).toLocaleString() }}</small><p>{{ item.body }}</p></div><button v-if="!item.resolved" @click="resolveReportComment(item)">解决</button></article><label v-if="shareUrl">只读分享链接<input :value="shareUrl" readonly></label></aside>
          </div>
        </div>
      </template>

      <template v-else-if="section === 'reports'">
        <ReportLibrary :reports="sortedReports" :datasets="datasets" :trash="trashedReports" :busy="reportBusy" :sort="reportSort" :workspace-id="workspace?.id" :request="api" @open="openReport" @action="manageReport" @changed="refreshReportCatalog" @trash="loadReportTrash" @sort="reportSort=$event; persistReportSort()" />
      </template>

      <template v-else-if="section === 'templates'">
        <TemplateCenter :workspace="workspace" :reports="reports" :templates="reportTemplates" :selected-report="selectedReport" @upload="uploadReportTemplate" @render="renderTemplateReport" @notice="notice=$event" />
      </template>

      <template v-else-if="section === 'charts'">
        <ChartWorkbench :workspace="workspace" :dataset="selectedDataset" @insert-chart="insertWorkbenchChart" @notice="notice=$event" />
      </template>

      <template v-else-if="section === 'data'">
        <DataWorkbench
          :workspace="workspace" :datasets="datasets" :selected-dataset-id="selectedDatasetId" :loading="loading"
          @select-dataset="selectDataWorkbenchDataset" @upload="fileInput?.click()" @import-sample="importSample"
          @start-analysis="startDatasetAnalysis" @dataset-created="acceptCreatedDataset" @notice="notice = $event"
        />
      </template>

      <template v-else-if="section === 'professional'">
        <ProfessionalWorkspace :integrations="integrations" :dashboard="professionalDashboard" :dataset="selectedDataset" :report="selectedReport" :preview="professionalPreview" :publishing="professionalPublishing" :get-guest-token="getSupersetGuestToken" @refresh="refreshIntegrations" @bootstrap="bootstrapProfessionalDashboard" @repair-embed="repairProfessionalEmbed" @preview-publish="previewProfessionalPublish" @publish="publishProfessionalDashboard" @select-data="section='data'" />
      </template>

      <template v-else-if="section === 'team'">
        <TeamWorkspace :workspace="workspace" :context="teamContext" :audit="auditLogs" @invite="inviteMember" @update-role="updateMemberRole" @remove-member="removeMember" @refresh="refreshTeam" />
      </template>

      <template v-else>
        <SettingsCenter
          :workspace="workspace"
          :providers="providers"
          :app-settings="appSettings"
          :provider-keys="providerKeys"
          :provider-status="providerStatus"
          :integrations="integrations"
          :tool-policy="toolPolicy"
          :mcp-servers="mcpServers"
          :request="api"
          @save-provider="saveProvider"
          @test-provider="testProvider"
          @save-general="saveGeneralSettings"
          @refresh-integrations="refreshIntegrations"
          @create-mcp="createMcpServer"
          @update-mcp="updateMcpServer"
          @discover-mcp="discoverMcpServer"
        />
      </template>
    </main>
    <input ref="fileInput" hidden type="file" accept=".csv,.xlsx,.xls" @change="upload">
    <ChartAiAssistantDrawer
      :open="aiChartDrawerOpen" :report="selectedReport" :chart="selectedChart" :workspace="workspace" :request="api" :initial-instruction="aiChartInstruction"
      @close="closeAiChartAssistant" @saved="acceptAiChartSaved" @notice="notice=$event"
    />
    <ContextMenu :menu="contextMenu" @close="contextMenu=null" @select="handleContextCommand" />
  </div>
</template>
