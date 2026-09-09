<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import ContextMenu from './ContextMenu.vue'
const props = defineProps({ reports: Array, datasets: Array, trash: Array, busy: Boolean, sort: String, workspaceId: String, request: Function })
const emit = defineEmits(['open', 'action', 'sort', 'trash', 'changed'])
const selection=ref([]), batchBusy=ref(false), batchResult=ref('')
async function batchAction() {
  const targets=rows.value.filter(r=>selection.value.includes(r.id))
  if(!targets.length || batchBusy.value || !window.confirm(`${recycled.value?'恢复':'移入回收站'}选中的 ${targets.length} 份报告？原始数据和历史证据保留。`)) return
  batchBusy.value=true; const failed=[], restoring=recycled.value
  try {
    for(const r of targets) {
      try { await props.request(`/api/v1/reports/${r.id}${restoring?'/restore':''}`,{method:restoring?'POST':'DELETE'}); selection.value=selection.value.filter(id=>id!==r.id) }
      catch(e) { failed.push(`${r.title}：${e.message}`) }
    }
    batchResult.value=`完成 ${targets.length-failed.length}/${targets.length}。${failed.join('；')}`
    await load(); emit('changed')
  } finally {batchBusy.value=false}
}
const query = ref(''), dataset = ref(''), recycled = ref(false), menu = ref(null)
const rows = ref([]), total = ref(0), offset = ref(0), loading = ref(false), error = ref('')
const pageSize = 24
let generation = 0, timer
async function load() {
  if (!props.workspaceId || !props.request) return
  const current = ++generation
  loading.value = true; error.value = ''
  try {
    const params = new URLSearchParams({workspace_id: props.workspaceId, deleted: String(recycled.value),
      q: query.value.trim(), offset: String(offset.value), limit: String(pageSize), sort: props.sort || 'updated_desc'})
    if (dataset.value) params.set('dataset_id', dataset.value)
    const page = await props.request(`/api/v1/report-catalog?${params}`)
    if (current !== generation) return
    rows.value = page.items; total.value = page.total
    if (!page.items.length && offset.value > 0) { offset.value = Math.max(0, offset.value-pageSize); return load() }
  } catch(err) { if(current === generation) error.value = err.message }
  finally { if(current === generation) loading.value = false }
}
watch([query, dataset, recycled, () => props.sort, () => props.workspaceId], () => {
  selection.value=[]
  loading.value=true
  ++generation; clearTimeout(timer); offset.value = 0; timer = setTimeout(load, 150)
}, {immediate: true})
watch(() => props.reports, load)
onBeforeUnmount(() => { ++generation; clearTimeout(timer) })
function page(delta) { selection.value=[]; offset.value += delta * pageSize; load() }
function actions(report) { return report.deleted_at ? [{id:'restore', label:'恢复报告'}] : [
  {id:'open',label:'编辑报告'}, {id:'rename',label:'重命名'}, {id:'copy',label:'复制报告'}, {id:'delete',label:'移入回收站',danger:true}] }
function command(id, report) { menu.value = null; if(id === 'open') emit('open',report); else emit('action',id,report) }
</script>
<template>
  <header class="simple-header"><div><span>REPORT LIBRARY</span><h1>报告库</h1><p>新建、编辑和管理报告；删除后可从回收站恢复。</p></div>
    <button class="primary" :disabled="busy" @click="emit('action','create')">＋ 新建空白报告</button>
  </header>
  <div class="library-controls">
    <input v-model="query" aria-label="搜索报告" placeholder="搜索报告标题">
    <select v-model="dataset" aria-label="报告数据集筛选"><option value="">全部数据集</option><option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.name }}</option></select>
    <label>排序 <select :value="sort" aria-label="报告排序" @change="emit('sort',$event.target.value)"><option value="updated_desc">最近更新</option><option value="created_desc">最近创建</option><option value="title_asc">标题 A–Z</option><option value="charts_desc">图表数量</option></select></label>
    <button class="outline-btn" :disabled="busy" @click="recycled=!recycled; emit('trash',recycled)">{{ recycled ? '返回报告库' : '回收站' }}</button>
  </div>
  <div v-if="error" role="alert" class="library-controls">{{ error }} <button @click="load">重试</button></div>
  <div class="library-controls"><button :disabled="loading || batchBusy" @click="selection=rows.map(r=>r.id)">全选本页</button><button :disabled="batchBusy" @click="selection=[]">清空选择</button><button :disabled="loading || batchBusy || busy || !selection.length" @click="batchAction">{{ recycled?'恢复':'删除' }}所选（{{ selection.length }}）</button><span role="status">{{ batchResult }}</span></div>
  <div class="card-grid report-library">
    <article v-for="report in rows" :key="report.id" class="report-card" @contextmenu.prevent="menu={x:$event.clientX,y:$event.clientY,report,items:actions(report)}">
      <label><input v-model="selection" type="checkbox" :value="report.id" :disabled="loading || batchBusy" :aria-label="`选择报告 ${report.title}`"> 选择报告</label>
      <div class="report-cover"><span>{{ recycled ? '回收站' : 'INSIGHT REPORT' }}</span><i>▥</i></div>
      <div><small>{{ report.chart_count || 0 }} 图表 · {{ new Date(report.updated_at || report.created_at).toLocaleDateString() }}</small><h3>{{ report.title }}</h3><p>{{ report.summary || '空白报告，可添加标题、说明和图表。' }}</p>
        <div class="report-actions"><button v-for="action in actions(report)" :key="action.id" class="outline-btn" :disabled="busy" @click="command(action.id,report)">{{ action.label }}</button></div>
      </div>
    </article>
    <div v-if="!rows.length && !loading" class="empty-card">{{ recycled ? '回收站暂无匹配报告。' : '暂无匹配报告。可以新建空白报告，或在 AI 对话中生成。' }}</div>
  </div>
  <nav class="library-controls" aria-label="报告分页"><button class="outline-btn" :disabled="loading || offset===0" @click="page(-1)">上一页</button><span>{{ loading ? '加载摘要中…' : `共 ${total} 份 · 第 ${Math.floor(offset/pageSize)+1} 页` }}</span><button class="outline-btn" :disabled="loading || offset+pageSize>=total" @click="page(1)">下一页</button></nav>
  <ContextMenu :menu="menu" @close="menu=null" @select="command($event,menu.report)" />
</template>
<style scoped>
.library-controls{display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:20px 30px}.library-controls input,.library-controls select{padding:9px;border:1px solid #dce2eb;border-radius:7px;background:white;color:#354257}.report-actions{display:flex;flex-wrap:wrap;gap:8px}.report-card{text-align:left}.report-actions button{font-size:12px}
</style>
