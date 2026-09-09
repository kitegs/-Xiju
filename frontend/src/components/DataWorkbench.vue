<script setup>
import { computed, ref, watch } from 'vue'
import RelationshipBuilder from './RelationshipBuilder.vue'
import DatasetSemanticsEditor from './DatasetSemanticsEditor.vue'

const props = defineProps({
  workspace: { type: Object, default: null },
  datasets: { type: Array, default: () => [] },
  selectedDatasetId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['select-dataset', 'upload', 'import-sample', 'start-analysis', 'dataset-created', 'notice'])

const preview = ref(null)
const previewLoading = ref(false)
const previewError = ref('')
const recipeSteps = ref([])
const recipePreview = ref(null)
const recipeName = ref('')
const applying = ref(false)
const previewingRecipe = ref(false)
const activePanel = ref('quality')
const recipes = ref([])
const historyLoading = ref(false)
const undoStack = ref([])
const redoStack = ref([])
let committedRecipe = '[]'
let previewRequestId = 0

const operationOptions = [
  { value: 'drop_duplicates', label: '删除重复行' },
  { value: 'fill_missing', label: '填充缺失值' },
  { value: 'convert_type', label: '转换字段类型' },
  { value: 'trim_text', label: '修剪文本空格' },
  { value: 'replace_value', label: '替换字段值' },
  { value: 'rename_column', label: '重命名字段' },
  { value: 'filter_rows', label: '筛选保留行' },
]

const selectedDataset = computed(() => props.datasets.find(item => item.id === props.selectedDatasetId) || props.datasets[0])
const columns = computed(() => preview.value?.columns || [])

function makeStep(operation = 'drop_duplicates') {
  return { id: `step-${Date.now()}-${Math.random()}`, operation, column: columns.value[0] || '', columns: [], method: 'constant', value: '', old_value: '', new_value: '', new_name: '', target_type: 'text', date_format: '', operator: 'eq' }
}

function cleanStep(step) {
  const base = { operation: step.operation }
  if (step.operation === 'drop_duplicates') return { ...base, columns: step.columns || [] }
  base.column = step.column
  if (step.operation === 'fill_missing') return { ...base, method: step.method, value: step.method === 'constant' ? step.value : null }
  if (step.operation === 'convert_type') return { ...base, target_type: step.target_type, date_format: step.target_type === 'date' ? (step.date_format || null) : null }
  if (step.operation === 'trim_text') return base
  if (step.operation === 'replace_value') return { ...base, old_value: step.old_value, new_value: step.new_value }
  if (step.operation === 'rename_column') return { ...base, new_name: step.new_name }
  return { ...base, operator: step.operator, value: step.operator === 'not_empty' ? null : step.value }
}

async function api(path, options = {}) {
  const response = await fetch(path, options)
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '请求失败')
  return response.json()
}

async function loadPreview(datasetId = selectedDataset.value?.id) {
  if (!datasetId || !props.workspace) return
  const requestId = ++previewRequestId
  previewLoading.value = true; previewError.value = ''
  try {
    const result = await api(`/api/v1/datasets/${datasetId}/preview?workspace_id=${props.workspace.id}&limit=50`)
    if (requestId !== previewRequestId) return
    preview.value = result
    if (!recipeName.value) recipeName.value = `${result.dataset.name} · 已清洗`
    await loadRecipes(datasetId)
  } catch (error) {
    if (requestId === previewRequestId) previewError.value = error.message
  } finally {
    if (requestId === previewRequestId) previewLoading.value = false
  }
}

async function loadRecipes(datasetId = selectedDataset.value?.id) {
  if (!datasetId || !props.workspace) return
  historyLoading.value = true
  try { recipes.value = await api(`/api/v1/cleaning-recipes?workspace_id=${props.workspace.id}&dataset_id=${datasetId}`) }
  catch (error) { emit('notice', `配方历史加载失败：${error.message}`) } finally { historyLoading.value = false }
}

function cloneSteps(steps = recipeSteps.value) { return JSON.parse(JSON.stringify(steps)) }
function setCommitted() { committedRecipe = JSON.stringify(recipeSteps.value) }
function resetEditHistory() { undoStack.value = []; redoStack.value = []; setCommitted() }
function mutateRecipe(mutator) {
  const before = cloneSteps()
  mutator()
  if (JSON.stringify(before) !== JSON.stringify(recipeSteps.value)) {
    undoStack.value.push(before); redoStack.value = []; setCommitted(); recipePreview.value = null
  }
}
function commitFieldEdit() {
  const current = JSON.stringify(recipeSteps.value)
  if (current === committedRecipe) return
  undoStack.value.push(JSON.parse(committedRecipe)); redoStack.value = []; committedRecipe = current; recipePreview.value = null
}
function undoRecipe() {
  if (!undoStack.value.length) return
  redoStack.value.push(cloneSteps()); recipeSteps.value = undoStack.value.pop(); setCommitted(); recipePreview.value = null
}
function redoRecipe() {
  if (!redoStack.value.length) return
  undoStack.value.push(cloneSteps()); recipeSteps.value = redoStack.value.pop(); setCommitted(); recipePreview.value = null
}
function moveStep(index, offset) {
  const target = index + offset
  if (target < 0 || target >= recipeSteps.value.length) return
  mutateRecipe(() => { const [step] = recipeSteps.value.splice(index, 1); recipeSteps.value.splice(target, 0, step) })
}

function selectDataset(id) {
  emit('select-dataset', id)
  recipeSteps.value = []; recipePreview.value = null; recipeName.value = ''; recipes.value = []; resetEditHistory()
}

function addStep(operation = 'drop_duplicates') {
  mutateRecipe(() => recipeSteps.value.push(makeStep(operation))); activePanel.value = 'recipe'
}

function removeStep(index) { mutateRecipe(() => recipeSteps.value.splice(index, 1)) }

function replayRecipe(recipe) {
  recipeSteps.value = recipe.steps.map(step => ({ ...makeStep(step.operation), ...step }))
  recipeName.value = `${selectedDataset.value.name} · 重放`
  recipePreview.value = null; activePanel.value = 'recipe'; resetEditHistory()
  emit('notice', `已载入历史配方“${recipe.name}”，请先预览再执行`)
}

async function previewRecipe() {
  if (!recipeSteps.value.length) return
  previewingRecipe.value = true
  try {
    recipePreview.value = await api(`/api/v1/datasets/${selectedDataset.value.id}/cleaning/preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: props.workspace.id, steps: recipeSteps.value.map(cleanStep), sample_limit: 20 }),
    })
  } catch (error) { emit('notice', error.message) } finally { previewingRecipe.value = false }
}

async function applyRecipe() {
  if (!recipePreview.value || applying.value) return
  applying.value = true
  try {
    const result = await api(`/api/v1/datasets/${selectedDataset.value.id}/cleaning/apply`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: props.workspace.id, name: recipeName.value, steps: recipeSteps.value.map(cleanStep), sample_limit: 20 }),
    })
    emit('dataset-created', result.dataset)
    emit('notice', `已生成新数据版本“${result.dataset.name}”，原始数据未修改`)
    recipeSteps.value = []; recipePreview.value = null; recipeName.value = ''
    resetEditHistory(); await loadRecipes(selectedDataset.value.id)
  } catch (error) { emit('notice', error.message) } finally { applying.value = false }
}

function addFix(issue) {
  if (issue.issue_type === 'duplicates') addStep('drop_duplicates')
  else if (issue.issue_type === 'whitespace') mutateRecipe(() => recipeSteps.value.push({ ...makeStep('trim_text'), column: issue.columns[0] }))
  else if (issue.issue_type === 'missing') mutateRecipe(() => recipeSteps.value.push({ ...makeStep('fill_missing'), column: issue.columns[0] }))
  activePanel.value = 'recipe'
}

watch([
  () => selectedDataset.value?.id,
  () => props.workspace?.id,
], ([datasetId, workspaceId]) => {
  if (datasetId && workspaceId) loadPreview(datasetId)
}, { immediate: true })
</script>

<template>
  <div class="data-workbench">
    <header class="data-workbench-header">
      <div><span>DATA WORKSPACE</span><h1>数据准备</h1><p>直接预览数据、发现质量问题，并用可追溯步骤生成清洗后的新版本。</p></div>
      <div><button class="outline-btn" @click="emit('import-sample')">载入示例</button><button class="primary" @click="emit('upload')">＋ 上传数据</button></div>
    </header>

    <div v-if="!datasets.length" class="data-first-run">
      <span>◫</span><h2>先添加一份数据</h2><p>上传 CSV / Excel，或用 48 条完全虚构的零售记录体验预览、质量检查和清洗。</p>
      <div><button class="primary" @click="emit('import-sample')">载入示例数据</button><button class="outline-btn" @click="emit('upload')">上传我的数据</button></div>
    </div>

    <div v-else class="data-workbench-grid">
      <aside class="dataset-sidebar">
        <header><b>数据集</b><span>{{ datasets.length }}</span></header>
        <button v-for="item in datasets" :key="item.id" :class="{ active: selectedDataset?.id === item.id }" @click="selectDataset(item.id)">
          <i>▤</i><div><b>{{ item.name }}</b><small>{{ item.profile.row_count?.toLocaleString() }} 行 · {{ item.profile.column_count }} 列</small></div><span>›</span>
        </button>
        <div class="dataset-sidebar-note"><b>版本策略</b><p>每次执行清洗都会生成新数据集，原始上传永不覆盖。</p></div>
      </aside>

      <main class="data-canvas">
        <div v-if="previewLoading" class="data-loading">正在读取数据预览…</div>
        <div v-else-if="previewError" class="data-error"><b>预览失败</b><span>{{ previewError }}</span><button @click="loadPreview()">重试</button></div>
        <template v-else-if="preview">
          <header class="dataset-titlebar">
            <div><h2>{{ preview.dataset.name }}</h2><p>{{ preview.dataset.original_name }} · {{ preview.total_rows.toLocaleString() }} 行 · {{ preview.columns.length }} 列</p></div>
            <button class="outline-btn" @click="emit('start-analysis', preview.dataset.id)">交给 AI 分析 →</button>
          </header>
          <div class="data-kpis">
            <article><span>质量评分</span><strong :class="{ warning: preview.quality.score < 90 }">{{ preview.quality.score }}</strong><small>/ 100</small></article>
            <article><span>缺失单元格</span><strong>{{ preview.quality.missing_cells }}</strong><small>个</small></article>
            <article><span>重复记录</span><strong>{{ preview.quality.duplicate_rows }}</strong><small>行</small></article>
            <article><span>清洗步骤</span><strong>{{ recipeSteps.length }}</strong><small>步</small></article>
          </div>
          <nav class="data-tabs"><button :class="{ active: activePanel === 'quality' }" @click="activePanel = 'quality'">数据预览与质量</button><button :class="{ active: activePanel === 'semantics' }" @click="activePanel = 'semantics'">字段口径</button><button :class="{ active: activePanel === 'recipe' }" @click="activePanel = 'recipe'">清洗配方 <span v-if="recipeSteps.length">{{ recipeSteps.length }}</span></button><button :class="{ active: activePanel === 'history' }" @click="activePanel = 'history'">历史配方 <span v-if="recipes.length">{{ recipes.length }}</span></button><button :class="{ active: activePanel === 'relationship' }" @click="activePanel = 'relationship'">多表关联</button></nav>

          <section v-if="activePanel === 'quality'" class="data-preview-panel">
            <div class="quality-strip">
              <div><b>质量检查</b><span v-if="preview.quality.issues.length">发现 {{ preview.quality.issues.length }} 个建议处理的问题</span><span v-else>未发现缺失、重复或文本空格问题</span></div>
              <div v-if="!preview.quality.issues.length" class="quality-ok">✓ 当前数据质量良好</div>
            </div>
            <div v-if="preview.quality.issues.length" class="quality-issues">
              <article v-for="issue in preview.quality.issues" :key="issue.id" :class="issue.severity"><span>{{ issue.severity === 'error' ? '!' : issue.severity === 'warning' ? '△' : 'i' }}</span><div><b>{{ issue.title }}</b><p>{{ issue.detail }}</p></div><button @click="addFix(issue)">添加修复步骤</button></article>
            </div>
            <div class="data-grid-scroll"><table><thead><tr><th>#</th><th v-for="column in preview.columns" :key="column">{{ column }}<small>{{ preview.dataset.profile.columns?.find(item => item.name === column)?.dtype }}</small></th></tr></thead><tbody><tr v-for="(row,index) in preview.rows" :key="index"><td>{{ index + 1 }}</td><td v-for="column in preview.columns" :key="column" :class="{ missing: row[column] === null }">{{ row[column] === null ? '空值' : row[column] }}</td></tr></tbody></table></div>
            <p class="preview-footnote">显示前 {{ preview.rows.length }} 行，共 {{ preview.total_rows.toLocaleString() }} 行。清洗前请通过配方预览确认影响。</p>
          </section>

          <section v-else-if="activePanel === 'recipe'" class="recipe-builder">
            <div class="recipe-toolbar"><div><b>清洗步骤</b><span>按顺序执行；支持上移、下移、撤销和重做</span></div><div class="recipe-toolbar-actions"><button :disabled="!undoStack.length" title="撤销" @click="undoRecipe">↶ 撤销</button><button :disabled="!redoStack.length" title="重做" @click="redoRecipe">↷ 重做</button><select @change="addStep($event.target.value); $event.target.value = ''"><option value="">＋ 添加步骤…</option><option v-for="option in operationOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></div></div>
            <div v-if="!recipeSteps.length" class="recipe-empty"><span>⌁</span><h3>还没有清洗步骤</h3><p>从上方选择操作，或返回质量页点击“添加修复步骤”。</p><button @click="addStep('drop_duplicates')">先添加“删除重复行”</button></div>
            <div v-else class="recipe-steps">
              <article v-for="(step,index) in recipeSteps" :key="step.id">
                <span class="step-number">{{ index + 1 }}</span>
                <div class="step-body"><header><select v-model="step.operation" @change="commitFieldEdit"><option v-for="option in operationOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><div class="step-order-actions"><button :disabled="index === 0" title="上移步骤" @click="moveStep(index,-1)">↑</button><button :disabled="index === recipeSteps.length - 1" title="下移步骤" @click="moveStep(index,1)">↓</button><button title="删除步骤" @click="removeStep(index)">×</button></div></header>
                  <div v-if="step.operation === 'drop_duplicates'" class="step-fields"><label>判断字段<select v-model="step.columns" multiple @change="commitFieldEdit"><option v-for="column in columns" :key="column" :value="column">{{ column }}</option></select><small>不选字段表示整行去重</small></label></div>
                  <div v-else class="step-fields"><label>字段<select v-model="step.column" @change="commitFieldEdit"><option v-for="column in columns" :key="column" :value="column">{{ column }}</option></select></label>
                    <label v-if="step.operation === 'fill_missing'">填充方式<select v-model="step.method" @change="commitFieldEdit"><option value="constant">固定值</option><option value="mean">平均值</option><option value="median">中位数</option><option value="mode">众数</option></select></label><label v-if="step.operation === 'fill_missing' && step.method === 'constant'">填充值<input v-model="step.value" @change="commitFieldEdit"></label>
                    <label v-if="step.operation === 'convert_type'">目标类型<select v-model="step.target_type" @change="commitFieldEdit"><option value="text">文本</option><option value="integer">整数</option><option value="float">小数</option><option value="date">日期</option><option value="boolean">布尔值</option></select></label><label v-if="step.operation === 'convert_type' && step.target_type === 'date'">日期格式<input v-model="step.date_format" placeholder="例如 %Y-%m-%d" @change="commitFieldEdit"><small>留空时自动识别</small></label>
                    <template v-if="step.operation === 'replace_value'"><label>原值<input v-model="step.old_value" @change="commitFieldEdit"></label><label>新值<input v-model="step.new_value" @change="commitFieldEdit"></label></template>
                    <label v-if="step.operation === 'rename_column'">新字段名<input v-model="step.new_name" @change="commitFieldEdit"></label>
                    <template v-if="step.operation === 'filter_rows'"><label>条件<select v-model="step.operator" @change="commitFieldEdit"><option value="eq">等于</option><option value="neq">不等于</option><option value="gt">大于</option><option value="gte">大于等于</option><option value="lt">小于</option><option value="lte">小于等于</option><option value="contains">包含文本</option><option value="not_empty">非空</option></select></label><label v-if="step.operator !== 'not_empty'">比较值<input v-model="step.value" @change="commitFieldEdit"></label></template>
                  </div>
                </div>
              </article>
            </div>
            <div v-if="recipeSteps.length" class="recipe-actions"><label>新数据版本名称<input v-model="recipeName"></label><button class="outline-btn" :disabled="previewingRecipe" @click="previewRecipe">{{ previewingRecipe ? '计算中…' : '预览影响' }}</button><button class="primary" :disabled="!recipePreview || applying" @click="applyRecipe">{{ applying ? '正在生成…' : '确认并生成新版本' }}</button></div>
            <div v-if="recipePreview" class="recipe-result"><header><div><b>预览结果</b><span>尚未写入任何文件</span></div><div><strong>{{ recipePreview.before_rows }}</strong> → <strong>{{ recipePreview.after_rows }}</strong> 行 · 改变 {{ recipePreview.changed_cells }} 个单元格</div></header><div class="step-results"><span v-for="item in recipePreview.step_results" :key="item.index">{{ item.index }}. {{ item.description }}</span></div><div class="data-grid-scroll compact"><table><thead><tr><th v-for="column in recipePreview.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row,index) in recipePreview.rows" :key="index"><td v-for="column in recipePreview.columns" :key="column" :class="{ missing: row[column] === null }">{{ row[column] === null ? '空值' : row[column] }}</td></tr></tbody></table></div></div>
          </section>
          <section v-else-if="activePanel === 'history'" class="recipe-history">
            <header><div><b>历史配方</b><span>重放会载入原步骤，不会立即修改数据</span></div><button class="outline-btn" :disabled="historyLoading" @click="loadRecipes()">{{ historyLoading ? '刷新中…' : '刷新' }}</button></header>
            <div v-if="!recipes.length" class="recipe-empty"><span>◷</span><h3>暂无历史配方</h3><p>确认执行一次清洗后，来源、步骤和影响会保存在这里。</p></div>
            <div v-else class="recipe-history-list"><article v-for="recipe in recipes" :key="recipe.id"><div class="recipe-history-icon">⌁</div><div><h3>{{ recipe.name }}</h3><p>{{ recipe.steps.length }} 步 · {{ recipe.impact.before_rows }} → {{ recipe.impact.after_rows }} 行 · {{ new Date(recipe.created_at).toLocaleString() }}</p><div><span v-for="(step,index) in recipe.steps" :key="index">{{ index + 1 }}. {{ operationOptions.find(item => item.value === step.operation)?.label || step.operation }}</span></div></div><button class="primary" @click="replayRecipe(recipe)">载入并重放</button></article></div>
          </section>
          <DatasetSemanticsEditor v-else-if="activePanel === 'semantics'" :workspace="workspace" :dataset="selectedDataset" @saved="emit('dataset-created',$event)" @notice="emit('notice',$event)" />
          <RelationshipBuilder v-else :workspace="workspace" :datasets="datasets" :selected-dataset-id="selectedDatasetId" @dataset-created="emit('dataset-created',$event)" @start-analysis="emit('start-analysis',$event)" @notice="emit('notice',$event)" />
        </template>
      </main>
    </div>
  </div>
</template>
