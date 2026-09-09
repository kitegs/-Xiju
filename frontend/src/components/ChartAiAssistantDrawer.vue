<script setup>
import { computed, ref, watch } from 'vue'
import ChartPreview from './ChartPreview.vue'

const props = defineProps({
  open: Boolean,
  report: { type: Object, default: null },
  chart: { type: Object, default: null },
  workspace: { type: Object, default: null },
  request: { type: Function, required: true },
  initialInstruction: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved', 'notice'])
const instruction = ref('')
const context = ref(null)
const proposal = ref(null)
const preview = ref(null)
const loading = ref(false)
const applying = ref(false)
const error = ref('')

const patchEntries = computed(() => Object.entries(proposal.value?.patch || {}).filter(([key]) => key !== 'style'))
const styleEntries = computed(() => Object.entries(proposal.value?.patch?.style || {}))
const chartPath = computed(() => props.report && props.chart ? `/api/v1/reports/${props.report.id}/charts/${props.chart.id}` : '')

async function loadContext() {
  if (!chartPath.value) return
  loading.value = true; error.value = ''; proposal.value = null; preview.value = null
  try { context.value = await props.request(`${chartPath.value}/context`) }
  catch (cause) { error.value = cause.message }
  finally { loading.value = false }
}
async function requestProposal() {
  if (!instruction.value.trim() || !chartPath.value || !props.workspace) return
  loading.value = true; error.value = ''; preview.value = null
  try {
    proposal.value = await props.request(`${chartPath.value}/proposals`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: props.workspace.id, instruction: instruction.value.trim() }),
    })
    await requestPreview()
  } catch (cause) { error.value = cause.message }
  finally { loading.value = false }
}
async function requestPreview() {
  if (!proposal.value?.patch || !context.value || !props.workspace) return
  preview.value = await props.request(`${chartPath.value}/preview`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: props.workspace.id, base_version: context.value.report_version_hint, patch: proposal.value.patch }),
  })
}
async function selectAlternative(option) {
  if (!proposal.value || !option?.patch) return
  proposal.value = {
    ...proposal.value,
    patch: option.patch,
    rationale: option.rationale?.length ? option.rationale : proposal.value.rationale,
    selectedAlternative: option.id,
  }
  loading.value = true; error.value = ''; preview.value = null
  try { await requestPreview() }
  catch (cause) { error.value = cause.message }
  finally { loading.value = false }
}
async function applyProposal() {
  if (!proposal.value?.patch || !context.value || !props.workspace) return
  applying.value = true; error.value = ''
  try {
    const saved = await props.request(`${chartPath.value}/apply`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: props.workspace.id, base_version: context.value.report_version_hint, patch: proposal.value.patch, approved: true }),
    })
    emit('saved', saved)
    emit('notice', 'AI 图表修改已批准、完整数据已重新计算，并已创建报告历史版本。')
    emit('close')
  } catch (cause) { error.value = cause.message }
  finally { applying.value = false }
}
watch(() => [props.open, props.chart?.id, props.initialInstruction], async ([open]) => {
  if (!open) return
  await loadContext()
  if (props.initialInstruction.trim()) {
    instruction.value = props.initialInstruction.trim()
    await requestProposal()
  }
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="ai-chart-overlay" @click.self="emit('close')">
      <aside class="ai-chart-drawer" role="dialog" aria-modal="true" aria-label="AI 优化图表">
        <header>
          <div><span>AI CHART COPILOT</span><h2>优化当前图表</h2><p>AI 只提出受控配置；预览和保存均会基于完整数据重新计算。</p></div>
          <button aria-label="关闭" @click="emit('close')">×</button>
        </header>
        <main>
          <section v-if="error" class="ai-error">{{ error }}</section>
          <section class="request-box">
            <label>希望如何修改？</label>
            <textarea v-model="instruction" rows="4" placeholder="例如：改成横向条形图，只显示前十项，使用商务配色，并显示标签。" :disabled="loading || applying" />
            <button class="primary" :disabled="loading || !instruction.trim()" @click="requestProposal">{{ loading ? '正在生成与验证…' : '生成优化方案' }}</button>
          </section>
          <section v-if="context" class="quality-box">
            <div><b>当前图表质量 {{ context.quality.score }}/100</b><small>当前字段、样式和数据版本已经锁定。</small></div>
            <ul v-if="context.quality.issues.length"><li v-for="issue in context.quality.issues" :key="issue.id"><b>{{ issue.title }}</b><span>{{ issue.suggestion }}</span></li></ul>
            <p v-else>未发现阻止发布的图表质量问题。</p>
          </section>
          <section v-if="proposal" class="proposal-box">
            <div class="section-title"><b>AI 修改方案</b><small>{{ proposal.provider }}{{ proposal.usage ? ` · ${proposal.usage.total_tokens || 0} tokens` : '' }}</small></div>
            <div v-if="proposal.alternatives?.length" class="alternative-list">
              <button v-for="option in proposal.alternatives" :key="option.id" :class="{active: proposal.selectedAlternative === option.id}" :disabled="loading || applying" @click="selectAlternative(option)">
                <b>{{ option.label }}</b><small>{{ option.rationale?.[0] || '基于相同完整数据生成预览' }}</small>
              </button>
            </div>
            <ul><li v-for="item in proposal.rationale" :key="item">{{ item }}</li></ul>
            <p v-for="warning in proposal.warnings" :key="warning" class="proposal-warning">{{ warning }}</p>
            <div class="patch-list"><span v-for="[key,value] in patchEntries" :key="key"><b>{{ key }}</b> {{ typeof value === 'object' ? JSON.stringify(value) : value }}</span><span v-for="[key,value] in styleEntries" :key="`style-${key}`"><b>style.{{ key }}</b> {{ value }}</span></div>
          </section>
          <section v-if="preview" class="preview-box">
            <div class="section-title"><b>修改后预览</b><small>完整数据 · {{ preview.evidence.value }}</small></div>
            <ChartPreview :chart="preview.chart" compact />
            <div class="quality-box"><b>修改后质量 {{ preview.quality.score }}/100</b><ul v-if="preview.quality.issues.length"><li v-for="issue in preview.quality.issues" :key="issue.id">{{ issue.title }}：{{ issue.suggestion }}</li></ul></div>
            <details><summary>查看正式计算依据</summary><p>{{ preview.evidence.method }}</p><code>{{ preview.evidence.code }}</code><small>字段：{{ preview.evidence.source_columns.join('、') }}</small></details>
          </section>
        </main>
        <footer><button class="outline-btn" @click="emit('close')">取消</button><button class="primary" :disabled="!preview || applying" @click="applyProposal">{{ applying ? '正在保存…' : '批准并应用' }}</button></footer>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.ai-chart-overlay{position:fixed;inset:0;z-index:1250;background:#17233b4d;display:flex;justify-content:flex-end}.ai-chart-drawer{width:min(580px,100vw);height:100%;background:#fff;display:flex;flex-direction:column;box-shadow:-14px 0 38px #17243a38}.ai-chart-drawer>header{display:flex;justify-content:space-between;gap:16px;padding:23px 25px 17px;border-bottom:1px solid #e4e8ee}.ai-chart-drawer header span{color:#6264cc;font-size:9px;font-weight:800;letter-spacing:1px}.ai-chart-drawer h2{margin:5px 0;font-size:20px;color:#263247}.ai-chart-drawer p{margin:0;color:#738096;font-size:11px;line-height:1.5}.ai-chart-drawer header>button{width:28px;height:28px;border:0;border-radius:7px;background:#f2f4f7;color:#687587;font-size:20px}.ai-chart-drawer main{flex:1;overflow:auto;padding:17px 25px}.ai-chart-drawer section{margin-bottom:15px}.request-box,.proposal-box,.quality-box,.preview-box{padding:13px;border:1px solid #e2e7ef;border-radius:10px;background:#fff}.request-box label{display:block;font-size:11px;font-weight:700;color:#4b5970;margin-bottom:7px}.request-box textarea{box-sizing:border-box;width:100%;resize:vertical;border:1px solid #d6dde8;border-radius:7px;padding:9px;font:12px inherit;color:#354257}.request-box button{margin-top:9px}.section-title{display:flex;justify-content:space-between;gap:10px;color:#3c4a61;font-size:12px}.section-title small,.quality-box small{color:#7f8b9c;font-size:10px}.quality-box>div{display:flex;justify-content:space-between;gap:8px}.quality-box ul,.proposal-box ul{margin:9px 0 0;padding-left:17px;color:#657286;font-size:11px;line-height:1.55}.quality-box li span{display:block;color:#8490a0}.proposal-warning,.ai-error{margin:8px 0 0;padding:8px;border-radius:6px;background:#fff5e8;color:#9a651c;font-size:11px}.ai-error{background:#fff0f2;color:#a33e50}.alternative-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px;margin-top:10px}.alternative-list button{min-width:0;text-align:left;border:1px solid #dfe4ec;border-radius:7px;background:#f8f9fc;padding:7px;color:#4d5a70;font-size:10px}.alternative-list button.active{border-color:#696ad6;background:#f0f0ff;color:#4f51a9}.alternative-list button small{display:block;overflow:hidden;margin-top:3px;color:#7d899b;font-size:9px;line-height:1.35;text-overflow:ellipsis;white-space:nowrap}.patch-list{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}.patch-list span{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:4px 6px;background:#eef0ff;border-radius:5px;color:#5658a9;font-size:10px}.preview-box :deep(.viz){margin-top:10px;min-height:230px}.preview-box details{margin-top:9px;color:#657286;font-size:10px}.preview-box code,.preview-box details small{display:block;margin-top:5px;white-space:pre-wrap;word-break:break-word}.ai-chart-drawer footer{display:flex;justify-content:flex-end;gap:8px;padding:15px 25px;border-top:1px solid #e4e8ee}@media(max-width:600px){.ai-chart-drawer main{padding:15px 18px}.ai-chart-drawer>header,.ai-chart-drawer footer{padding-left:18px;padding-right:18px}}
</style>
