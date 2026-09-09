<script setup>
import { computed, ref, watch } from 'vue'
import ChartPreview from './ChartPreview.vue'
import ContextMenu from './ContextMenu.vue'
import ChartEditorDrawer from './ChartEditorDrawer.vue'

const props = defineProps({ workspace: Object, dataset: Object })
const emit = defineEmits(['insert-chart', 'notice', 'open-report'])
const x = ref(''); const y = ref(''); const secondMeasure = ref(''); const aggregate = ref('sum')
const chartType = ref('bar'); const data = ref([]); const loading = ref(false); const sql = ref('SELECT * FROM dataset LIMIT 20')
const sqlResult = ref(null); const sqlLoading = ref(false); const search = ref(''); const dropTarget = ref('')
const contextMenu = ref(null)
const editorOpen = ref(false); const chartTitle = ref(''); const chartDescription = ref('由图表工作台基于完整数据生成。')
const style = ref({ palette: 'insight', show_legend: true, show_labels: false, number_format: 'compact', height: 360 })
const fields = computed(() => props.dataset?.profile?.columns || [])
const allMeasures = computed(() => fields.value.filter(item => item.semantic_type === 'measure' || /int|float|double|decimal/i.test(item.dtype)))
const dimensions = computed(() => fields.value.filter(item => !allMeasures.value.some(measure => measure.name === item.name) && matches(item)))
const measures = computed(() => allMeasures.value.filter(matches))
const chartTypes = [
  { id:'bar', label:'柱状图', icon:'▥', enabled:true }, { id:'line', label:'折线图', icon:'⌁', enabled:true },
  { id:'area', label:'面积图', icon:'◫', enabled:true }, { id:'combo', label:'组合图', icon:'◫', enabled:true },
  { id:'scatter', label:'散点图', icon:'·', enabled:true }, { id:'bubble', label:'气泡图', icon:'◌', enabled:true },
  { id:'pie', label:'饼图', icon:'◕', enabled:true }, { id:'donut', label:'环形图', icon:'◉', enabled:true },
  { id:'table', label:'数据表', icon:'▦', enabled:true }, { id:'highlight_table', label:'高亮表', icon:'▦', enabled:true },
  { id:'heatmap', label:'热力图', icon:'▦', enabled:true }, { id:'treemap', label:'树图', icon:'▤', enabled:true },
  { id:'histogram', label:'直方图', icon:'▥', enabled:true }, { id:'boxplot', label:'盒须图', icon:'┼', enabled:true },
  { id:'waterfall', label:'瀑布图', icon:'↕', enabled:true }, { id:'pareto', label:'帕累托', icon:'⌁', enabled:true },
  { id:'control_chart', label:'控制图', icon:'⌁', enabled:true }, { id:'gauge', label:'仪表盘', icon:'◴', enabled:true },
  { id:'radar', label:'雷达图', icon:'✧', enabled:true }, { id:'density_plot', label:'密度散点', icon:'⁙', enabled:true },
  { id:'kpi', label:'指标卡', icon:'12', enabled:true },
]
const chart = computed(() => ({ id: `chart-${Date.now()}`, title: chartTitle.value || (x.value ? `按 ${x.value} 对比 ${[y.value,secondMeasure.value].filter(Boolean).join(' / ')}` : `${y.value || '未选择指标'}`), chart_type: chartType.value, x: x.value ? { column: x.value } : null, y: y.value ? { column: y.value, aggregate: aggregate.value } : null, series: [y.value, secondMeasure.value].filter(Boolean).map(column => ({ column, aggregate: aggregate.value })), description: chartDescription.value, data: data.value, evidence_ids: [], position: { x:0,y:0,w:12,h:5 }, style: style.value }))

function matches(field) { return !search.value || field.name.toLowerCase().includes(search.value.toLowerCase()) }
function fieldKind(name) { return allMeasures.value.some(item => item.name === name) ? 'measure' : 'dimension' }
async function api(path, options={}) { const response=await fetch(path,options); if(!response.ok) throw new Error((await response.json().catch(()=>null))?.detail || '请求失败'); return response.json() }
async function refreshChart() {
  if (!props.dataset || !y.value) { data.value=[]; return }
  loading.value = true
  try {
    const result = await api(`/api/v1/datasets/${props.dataset.id}/chart-preview`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ workspace_id:props.workspace.id, x_column:x.value || null, y_column:y.value, series_columns:secondMeasure.value ? [secondMeasure.value] : [], aggregate:aggregate.value, limit:20 }) })
    data.value = result.data
  } catch(error) { emit('notice', error.message) } finally { loading.value=false }
}
function addField(field, preferredAxis='') {
  const kind = fieldKind(field.name); const axis = preferredAxis || (kind === 'dimension' ? 'x' : (!y.value ? 'y' : 'series'))
  const supportsNumericX = ['scatter', 'bubble', 'density_plot'].includes(chartType.value)
  if (axis === 'x' && kind !== 'dimension' && !supportsNumericX) return emit('notice', '当前图表的列槽只接受维度字段；散点、气泡和密度散点可使用连续数值作为 X 轴。')
  if ((axis === 'y' || axis === 'series') && kind !== 'measure') return emit('notice', '指标槽只接受数值度量字段。')
  if (axis === 'x') x.value=field.name; else if (axis === 'y') y.value=field.name; else secondMeasure.value=field.name
  refreshChart()
}
function drag(field,event) {
  const payload=JSON.stringify({name:field.name, kind:fieldKind(field.name)})
  event.dataTransfer.effectAllowed='copy'; event.dataTransfer.setData('application/x-insight-field',payload); event.dataTransfer.setData('text/plain',field.name)
}
function drop(axis,event) {
  dropTarget.value=''
  let payload; try { payload=JSON.parse(event.dataTransfer.getData('application/x-insight-field')) } catch (_) { payload={name:event.dataTransfer.getData('text/plain')} }
  const field=fields.value.find(item=>item.name===payload?.name); if (!field) return emit('notice','未识别到拖入字段，请直接点击字段添加。')
  addField(field,axis)
}
function clear(axis) { if(axis==='x')x.value=''; else if(axis==='y')y.value=''; else secondMeasure.value=''; refreshChart() }
function insert() { if(!y.value)return emit('notice','请先选择指标'); emit('insert-chart', JSON.parse(JSON.stringify(chart.value))) }
function chooseChart(item) { chartType.value=item.id; if (['bubble','heatmap','highlight_table','combo'].includes(item.id) && !secondMeasure.value) emit('notice', `${item.label}已使用 ECharts 真实渲染；添加“第二指标”可获得更完整的视觉编码。`); if (['scatter','density_plot'].includes(item.id) && fieldKind(x.value)==='dimension') emit('notice', '散点类图表当前以分类 X 轴绘制；将连续数值设为列可获得连续坐标。') }
function openFieldMenu(event,field) { event.preventDefault(); contextMenu.value={x:event.clientX,y:event.clientY,kind:'field',field,items:[{id:'to-x',label:'添加到列 / 维度',disabled:fieldKind(field.name)!=='dimension'},{id:'to-y',label:'添加到行 / 指标',disabled:fieldKind(field.name)!=='measure'},{id:'to-series',label:'添加为第二指标',disabled:fieldKind(field.name)!=='measure'},{id:'info',label:`字段信息 · ${field.dtype || field.semantic_type || '未知'}`}] } }
function openShelfMenu(event,axis) { event.preventDefault(); contextMenu.value={x:event.clientX,y:event.clientY,kind:'shelf',axis,items:[{id:'clear',label:'清空此槽位',disabled:!({x:x.value,y:y.value,series:secondMeasure.value})[axis]},{id:'edit',label:'编辑字段绑定'}] } }
function openChartMenu(event) { event.preventDefault(); contextMenu.value={x:event.clientX,y:event.clientY,kind:'chart',items:[{id:'edit',label:'编辑图表',icon:'✎'},{id:'refresh',label:'刷新完整数据'},{id:'insert',label:'插入当前报告'},{id:'bar',label:'切换为柱状图'},{id:'line',label:'切换为折线图'},{id:'pie',label:'切换为饼图'},{id:'heatmap',label:'切换为热力图'},{id:'table',label:'切换为数据表'}] } }
function applyChartDraft(draft) {
  chartTitle.value=draft.title; chartDescription.value=draft.description; chartType.value=draft.chart_type; x.value=draft.x; y.value=draft.y; secondMeasure.value=draft.second; aggregate.value=draft.aggregate
  style.value={...style.value,...draft.style}; refreshChart(); emit('notice','图表编辑已应用；可继续插入报告或保存。')
}
function runContextCommand(id) {
  const menu=contextMenu.value; contextMenu.value=null; if(!menu) return
  if(menu.kind==='field') { if(id==='info') return emit('notice', `${menu.field.name}：${menu.field.dtype || '未知类型'}，${fieldKind(menu.field.name)==='measure'?'数值度量':'维度字段'}`); return addField(menu.field, id.replace('to-','')) }
  if(menu.kind==='shelf') { if(id==='clear') clear(menu.axis); else emit('notice','可在此槽位右侧 × 清除绑定，或从字段栏拖入新字段替换。'); return }
  if(id==='edit') editorOpen.value=true; else if(id==='refresh') refreshChart(); else if(id==='insert') insert(); else chartType.value=id
}
async function runSql() {
  if(!props.dataset)return
  sqlLoading.value=true
  try { sqlResult.value=await api(`/api/v1/datasets/${props.dataset.id}/sql`, { method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ workspace_id:props.workspace.id,sql:sql.value,max_rows:100 }) }) }
  catch(error){emit('notice',error.message)} finally{sqlLoading.value=false}
}
watch(() => props.dataset?.id, () => { x.value=dimensions.value[0]?.name || ''; y.value=measures.value.find(item=>/sales|销售额/i.test(item.name))?.name || measures.value[0]?.name || ''; secondMeasure.value=''; chartTitle.value=''; chartDescription.value='由图表工作台基于完整数据生成。'; refreshChart() }, { immediate:true })
</script>

<template>
  <div class="chart-workbench">
    <header class="chart-workbench-head"><div><span>VISUAL ANALYSIS</span><h1>图表工作台</h1><p>可点击或拖拽字段；每次图表计算都基于完整数据并保留 ChartSpec。</p></div><div><button class="outline-btn" @click="editorOpen=true">编辑图表</button><button class="outline-btn" @click="refreshChart">{{ loading ? '计算中…' : '刷新数据' }}</button><button class="primary" @click="insert">插入当前报告</button></div></header>
    <div v-if="!dataset" class="blank-page"><span>▥</span><h2>请选择数据集</h2><p>图表必须绑定到一个确定的数据版本。</p></div>
    <div v-else class="chart-workbench-grid">
      <aside class="field-shelf"><header><b>{{ dataset.name }}</b><small>{{ dataset.profile.row_count?.toLocaleString() }} 行 · 完整读取</small></header><label class="field-search"><span>字段搜索</span><input v-model="search" placeholder="查找字段…"></label><section class="field-section"><label>维度 <small>{{ dimensions.length }}</small></label><div class="field-list-scroll"><button v-for="field in dimensions" :key="field.name" draggable="true" @click="addField(field)" @dragstart="drag(field,$event)" @contextmenu="openFieldMenu($event,field)"><i>Abc</i><span>{{ field.name }}</span><small>{{ field.semantic_type }}</small></button><p v-if="!dimensions.length">没有匹配的维度</p></div></section><section class="field-section"><label>度量 <small>{{ measures.length }}</small></label><div class="field-list-scroll"><button v-for="field in measures" :key="field.name" draggable="true" @click="addField(field)" @dragstart="drag(field,$event)" @contextmenu="openFieldMenu($event,field)"><i class="measure">#</i><span>{{ field.name }}</span><small>{{ field.dtype }}</small></button><p v-if="!measures.length">没有匹配的度量</p></div></section></aside>
      <main class="viz-builder"><div class="shelves"><div :class="{dropping:dropTarget==='x'}" @contextmenu="openShelfMenu($event,'x')" @dragover.prevent="dropTarget='x'" @dragleave="dropTarget=''" @drop="drop('x',$event)"><b>列 / 维度</b><span v-if="x">{{ x }} <button @click="clear('x')">×</button></span><em v-else>拖入维度，或点击字段</em></div><div :class="{dropping:dropTarget==='y'}" @contextmenu="openShelfMenu($event,'y')" @dragover.prevent="dropTarget='y'" @dragleave="dropTarget=''" @drop="drop('y',$event)"><b>行 / 指标</b><span v-if="y">{{ aggregate.toUpperCase() }}({{ y }}) <button @click="clear('y')">×</button></span><em v-else>拖入数值度量</em></div><div :class="{dropping:dropTarget==='series'}" @contextmenu="openShelfMenu($event,'series')" @dragover.prevent="dropTarget='series'" @dragleave="dropTarget=''" @drop="drop('series',$event)"><b>第二指标</b><span v-if="secondMeasure">{{ secondMeasure }} <button @click="clear('series')">×</button></span><em v-else>可选数值度量</em></div></div><section class="viz-canvas" @contextmenu="openChartMenu"><ChartPreview :chart="chart"/><div v-if="loading" class="canvas-loading">正在计算完整数据…</div></section><details class="sql-lab"><summary>SQL 证据查询</summary><p>表名固定为 <code>dataset</code>，只允许 SELECT/WITH，不允许访问外部文件。</p><textarea v-model="sql" rows="5"/><button class="primary" :disabled="sqlLoading" @click="runSql">{{ sqlLoading ? '执行中…' : '运行 SQL' }}</button><div v-if="sqlResult" class="sql-result"><b>{{ sqlResult.row_count }} 行 · {{ sqlResult.duration_ms }}ms</b><div class="viz-table"><div class="viz-tr viz-th"><span v-for="column in sqlResult.columns" :key="column">{{ column }}</span></div><div v-for="(row,index) in sqlResult.rows.slice(0,12)" :key="index" class="viz-tr"><span v-for="column in sqlResult.columns" :key="column">{{ row[column] }}</span></div></div></div></details></main>
      <aside class="show-me"><h3>智能显示</h3><p>稳定类型已开放；其余等待真实图表引擎接入。</p><div class="show-grid"><button v-for="item in chartTypes" :key="item.id" :class="{ active:chartType===item.id, disabled:!item.enabled }" :title="item.enabled ? item.label : '真实图表引擎接入后开放'" @click="chooseChart(item)"><span>{{ item.icon }}</span>{{ item.label }}<small v-if="!item.enabled">升级中</small></button></div><h3>标记与格式</h3><label>聚合<select v-model="aggregate" @change="refreshChart"><option value="sum">求和</option><option value="avg">平均</option><option value="count">计数</option><option value="min">最小</option><option value="max">最大</option></select></label><label>配色<select v-model="style.palette"><option value="insight">Insight</option><option value="business">商务</option><option value="risk">风险</option></select></label><label class="check"><input v-model="style.show_legend" type="checkbox">显示图例</label><label class="check"><input v-model="style.show_labels" type="checkbox">显示标签</label></aside>
    </div>
    <ContextMenu :menu="contextMenu" @close="contextMenu=null" @select="runContextCommand"/>
    <ChartEditorDrawer :open="editorOpen" :chart="chart" :fields="fields" :dimensions="dimensions" :measures="allMeasures" :chart-types="chartTypes" @close="editorOpen=false" @save="applyChartDraft"/>
  </div>
</template>
