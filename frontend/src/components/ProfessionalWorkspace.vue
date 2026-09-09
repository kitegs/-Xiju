<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  integrations: { type: Object, default: null }, dashboard: { type: Object, default: null },
  dataset: { type: Object, default: null }, report: { type: Object, default: null },
  preview: { type: Object, default: null }, publishing: { type: Boolean, default: false },
  getGuestToken: { type: Function, default: null },
})
const emit = defineEmits(['refresh', 'bootstrap', 'repair-embed', 'preview-publish', 'publish', 'select-data'])
const frame = ref(null)
const embedError = ref('')
const embedLoading = ref(false)
let port = null
let tokenRefresh = null
const embedOrigin = computed(() => {
  try { return new URL(props.integrations?.superset?.url || '').origin } catch (_) { return '' }
})
const embedUrl = computed(() => {
  if (!props.dashboard?.embedded_id || !embedOrigin.value) return ''
  return `${embedOrigin.value}/embedded/${props.dashboard.embedded_id}?uiConfig=11`
})
function openSuperset() {
  const url = props.dashboard?.dashboard_url || props.integrations?.superset?.url
  if (url) window.open(url, '_blank')
}
function openSupersetLogin() {
  const base = props.integrations?.superset?.url
  const target = props.dashboard?.dashboard_url || base
  if (!base) return
  const login = `${base.replace(/\/$/, '')}/login/?next=${encodeURIComponent(target?.replace(base, '') || '/')}`
  window.open(login, '_blank')
}
function tokenExpiryDelay(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return Math.max(30_000, (Number(payload.exp) * 1000) - Date.now() - 60_000)
  } catch (_) { return 240_000 }
}
async function sendGuestToken() {
  if (!port || !props.getGuestToken || !props.dashboard?.dashboard_id) return
  const result = await props.getGuestToken(props.dashboard.dashboard_id)
  if (!result?.token) throw new Error('服务未返回 Superset 访客令牌')
  port.postMessage({ switchboardAction: 'emit', method: 'guestToken', args: { guestToken: result.token } })
  if (tokenRefresh) window.clearTimeout(tokenRefresh)
  tokenRefresh = window.setTimeout(() => sendGuestToken().catch(error => { embedError.value = error.message }), tokenExpiryDelay(result.token))
}
async function connectEmbed() {
  if (!frame.value?.contentWindow || !embedOrigin.value || !embedUrl.value) return
  embedLoading.value = true; embedError.value = ''
  try {
    if (port) port.close()
    const channel = new MessageChannel(); port = channel.port1; port.start()
    frame.value.contentWindow.postMessage({ type: '__embedded_comms__', handshake: 'port transfer' }, embedOrigin.value, [channel.port2])
    await sendGuestToken()
  } catch (error) {
    embedError.value = error.message || '嵌入式看板连接失败'
  } finally { embedLoading.value = false }
}
onBeforeUnmount(() => { if (tokenRefresh) window.clearTimeout(tokenRefresh); if (port) port.close() })
</script>

<template>
  <div class="professional-workspace">
    <header class="simple-header"><div><span>PROFESSIONAL MODE</span><h1>AI 专业看板</h1><p>AI 先生成可审查草稿，再把只读数据副本、图表和布局发布到 Superset。</p></div><button class="outline-btn" @click="emit('refresh')">刷新连接</button></header>

    <section class="professional-hero professional-onboarding">
      <div class="professional-brand">S</div>
      <div class="professional-main">
        <span :class="['integration-state',{on:integrations?.superset?.reachable}]">{{ integrations?.superset?.reachable ? 'Superset 在线' : integrations?.superset?.configured ? 'Superset 连接失败' : '尚未启动 Superset' }}</span>
        <h2>{{ dashboard?.published ? dashboard.title : '让 AI 生成第一版专业看板' }}</h2>
        <p v-if="dashboard?.published">已发布 {{ dashboard.chart_count || dashboard.charts?.length || 0 }} 个图表。你可以继续在 Superset 调整布局、筛选器、颜色和图表细节。</p>
        <p v-else>不需要先学习 Database、Dataset 或 SQL Lab。选择数据后预览计划，确认后由 AI 完成初始化。</p>

        <div class="publish-steps">
          <article :class="{done:dataset}"><span>1</span><div><b>选择数据</b><small>{{ dataset ? `${dataset.name} · ${(dataset.profile?.row_count || 0).toLocaleString()} 行` : '尚未选择数据集' }}</small></div></article>
          <article :class="{done:preview || dashboard?.published}"><span>2</span><div><b>预览 AI 方案</b><small>检查将创建的图表和外部操作</small></div></article>
          <article :class="{done:dashboard?.published}"><span>3</span><div><b>确认并发布</b><small>原始文件保持不变，可在 Superset 精修</small></div></article>
        </div>

        <div v-if="preview" class="publish-preview">
          <header><div><small>待发布草稿</small><b>{{ preview.title }}</b></div><span>{{ preview.chart_count }} 图表</span></header>
          <div class="preview-chart-list"><article v-for="chart in preview.charts" :key="chart.id"><i>▥</i><div><b>{{ chart.title }}</b><small>{{ chart.chart_type }}</small></div></article></div>
          <details><summary>查看将执行的操作</summary><ol><li v-for="item in preview.operations" :key="item">{{ item }}</li></ol><p>只写入分析副本和 Superset 资源，不修改上传的原始文件。</p></details>
        </div>

        <div class="professional-actions">
          <button v-if="!dataset" class="primary" @click="emit('select-data')">选择或上传数据</button>
          <button v-else-if="!preview" class="primary" :disabled="!integrations?.superset?.reachable" @click="emit('preview-publish')">AI 生成看板方案</button>
          <button v-else class="primary" :disabled="publishing" @click="emit('publish')">{{ publishing ? '正在发布数据集与图表…' : '确认并发布到 Superset' }}</button>
          <button v-if="dashboard" class="outline-btn" :disabled="!integrations?.superset?.reachable" @click="emit('repair-embed')">修复嵌入配置</button>
          <button v-if="integrations?.superset?.reachable" class="outline-btn" @click="openSupersetLogin">登录本机 Superset ↗</button>
          <button v-if="dashboard" class="outline-btn" :disabled="!integrations?.superset?.reachable" @click="openSuperset">使用本机 Superset 账户编辑 ↗</button>
          <button v-if="integrations?.superset?.reachable && !dashboard" class="outline-btn" @click="emit('bootstrap')">只创建空看板</button>
        </div>
      </div>
    </section>

    <section v-if="dashboard?.embedded_id && integrations?.superset?.reachable" class="embedded-dashboard">
      <header><div><span>EMBEDDED DASHBOARD</span><h2>{{ dashboard.title || 'Superset 专业看板' }}</h2><p>已使用短时访客令牌嵌入；筛选、全屏、导出和图表交互在此处完成。完整编辑器需使用 Superset 本机账户。</p></div><div class="embed-actions"><button class="outline-btn" @click="emit('repair-embed')">修复嵌入</button><button class="outline-btn" @click="openSupersetLogin">登录 ↗</button><button class="outline-btn" @click="openSuperset">完整编辑器 ↗</button></div></header>
      <div v-if="embedError" class="embed-error"><b>无法嵌入看板</b><p>{{ embedError }}</p><p>可直接打开 Superset 登录页；账号和密码只提交给本机 Superset，不会发送或保存到 Insight Studio。</p><button class="outline-btn" @click="connectEmbed">重新连接</button><button class="outline-btn" @click="emit('repair-embed')">修复浏览器来源</button><button class="outline-btn" @click="openSupersetLogin">打开登录页 ↗</button><button class="outline-btn" @click="openSuperset">直接进入完整编辑器 ↗</button></div>
      <div v-else class="embed-frame-wrap"><div v-if="embedLoading" class="embed-loading">正在获取短时访问令牌…</div><iframe ref="frame" :src="embedUrl" title="Superset 专业看板" sandbox="allow-same-origin allow-scripts allow-presentation allow-downloads allow-forms allow-popups" allow="fullscreen; clipboard-write" @load="connectEmbed" /></div>
    </section>

    <div class="professional-grid">
      <article><b>AI 负责首稿</b><p>识别维度与度量、生成指标、推荐图表并排出第一版 Dashboard。</p></article>
      <article><b>Superset 负责精修</b><p>调整筛选联动、图表细节、SQL、布局和团队共享。</p></article>
      <article><b>发布有边界</b><p>使用只读数据副本；外部发布必须在预览后确认，并保留资源映射和审计记录。</p></article>
    </div>
    <div v-if="!integrations?.superset?.reachable" class="settings-callout"><b>如何开始</b><p>运行 start-professional.bat，等待状态变为“Superset 在线”，再选择数据并让 AI 生成看板方案。</p></div>
  </div>
</template>

<style scoped>
.embedded-dashboard{max-width:920px;margin:0 auto 18px;background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden}.embedded-dashboard>header{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:18px 20px;border-bottom:1px solid var(--line)}.embedded-dashboard span{color:#6566cf;font-size:8px;font-weight:800;letter-spacing:.8px}.embedded-dashboard h2{font-size:15px;margin:4px 0}.embedded-dashboard p{margin:0;color:var(--muted);font-size:9px;line-height:1.6}.embed-actions{display:flex;gap:7px;white-space:nowrap}.embed-frame-wrap{height:690px;position:relative;background:#f8fafc}.embed-frame-wrap iframe{border:0;width:100%;height:100%;display:block}.embed-loading{position:absolute;z-index:2;top:12px;left:12px;background:#f0f1ff;color:#5b5cc9;border-radius:16px;padding:6px 10px;font-size:9px}.embed-error{margin:16px;padding:14px;border:1px solid #f0c9b9;background:#fff7f2;border-radius:9px;color:#8b5138}.embed-error b{font-size:11px}.embed-error p{margin:5px 0 10px}.embed-error button+button{margin-left:7px}@media(max-width:900px){.embedded-dashboard{margin:0 18px 18px}.embedded-dashboard>header{align-items:flex-start;flex-direction:column}.embed-frame-wrap{height:560px}}
</style>
