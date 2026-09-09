<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  workspace: { type: Object, default: null },
  datasets: { type: Array, default: () => [] },
  selectedDatasetId: { type: String, default: '' },
})
const emit = defineEmits(['dataset-created', 'start-analysis', 'notice'])

const leftId = ref('')
const rightId = ref('')
const leftKey = ref('')
const rightKey = ref('')
const joinType = ref('left')
const rightPrefix = ref('right')
const resultName = ref('')
const preview = ref(null)
const loading = ref(false)
const applying = ref(false)
const acknowledged = ref(false)
const error = ref('')
const relations = ref([])
const requestBody = computed(() => JSON.stringify({ workspace_id: props.workspace?.id,
  left_dataset_id: leftId.value, right_dataset_id: rightId.value,
  left_keys: [leftKey.value], right_keys: [rightKey.value], join_type: joinType.value, right_prefix: rightPrefix.value }))
const previewBody = ref('')

const left = computed(() => props.datasets.find(item => item.id === leftId.value))
const right = computed(() => props.datasets.find(item => item.id === rightId.value))
const leftColumns = computed(() => left.value?.profile?.columns || [])
const rightColumns = computed(() => right.value?.profile?.columns || [])
const canApply = computed(() => previewBody.value === requestBody.value && preview.value?.safe && (!preview.value.non_additive_columns?.length || acknowledged.value))

async function api(path, options = {}) {
  const response = await fetch(path, options)
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || '请求失败')
  return response.json()
}

function chooseDefaults() {
  if (!props.datasets.length) return
  if (!leftId.value || !props.datasets.some(item => item.id === leftId.value)) leftId.value = props.selectedDatasetId || props.datasets[0].id
  if (!rightId.value || rightId.value === leftId.value || !props.datasets.some(item => item.id === rightId.value)) {
    rightId.value = props.datasets.find(item => item.id !== leftId.value)?.id || ''
  }
  suggestKeys()
}

function suggestKeys() {
  preview.value = null; acknowledged.value = false; error.value = ''
  const rightNames = new Set(rightColumns.value.map(item => item.name))
  // Row sequence IDs (e.g. Bike Sharing instant) are not cross-grain keys.
  // Prefer shared date fields, but still require an explicit preview/confirmation.
  const commonFields = leftColumns.value.filter(item => rightNames.has(item.name))
  const common = (commonFields.find(item => /date|日期|时间/i.test(item.name))
    || commonFields.find(item => !/^(instant|index|row[ _]?id)$/i.test(item.name))
    || commonFields[0])?.name || ''
  leftKey.value = common || leftColumns.value[0]?.name || ''
  rightKey.value = common || rightColumns.value[0]?.name || ''
  rightPrefix.value = (right.value?.name || 'right').replace(/[^0-9A-Za-z_\u4e00-\u9fff]+/g, '_').slice(0, 40)
  resultName.value = left.value && right.value ? `${left.value.name} + ${right.value.name}` : ''
}

async function loadRelations() {
  if (!props.workspace) return
  try { relations.value = await api(`/api/v1/dataset-relationships?workspace_id=${props.workspace.id}`) }
  catch (err) { emit('notice', `关联历史加载失败：${err.message}`) }
}

async function previewRelationship() {
  if (!props.workspace || !leftId.value || !rightId.value || !leftKey.value || !rightKey.value) return
  loading.value = true; preview.value = null; acknowledged.value = false; error.value = ''
  const body = requestBody.value
  try {
    const result = await api('/api/v1/dataset-relationships/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body,
    })
    if (body === requestBody.value) { preview.value = result; previewBody.value = body }
  } catch (err) { error.value = err.message }
  finally { loading.value = false }
}

async function applyRelationship() {
  if (!canApply.value || applying.value) return
  applying.value = true; error.value = ''
  try {
    const relation = await api('/api/v1/dataset-relationships', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: props.workspace.id, left_dataset_id: leftId.value, right_dataset_id: rightId.value, left_keys: [leftKey.value], right_keys: [rightKey.value], join_type: joinType.value, right_prefix: rightPrefix.value, name: resultName.value, acknowledge_non_additive: acknowledged.value }),
    })
    emit('dataset-created', relation.result_dataset)
    emit('notice', `已生成关联副本“${relation.result_dataset.name}”，两个原始数据集保持不变`)
    await loadRelations()
  } catch (err) { error.value = err.message }
  finally { applying.value = false }
}

watch(() => [props.datasets.map(item => item.id).join(','), props.selectedDatasetId], chooseDefaults, { immediate: true })
watch([leftId, rightId], suggestKeys)
watch(requestBody, () => { preview.value = null; acknowledged.value = false })
watch(() => props.workspace?.id, loadRelations, { immediate: true })
</script>

<template>
  <section class="relationship-builder">
    <header><div><b>多表关联</b><span>先验证关系和匹配率，再生成可分析的独立副本</span></div><small>当前仅支持 1:1 与明细 N:1</small></header>
    <div v-if="datasets.length < 2" class="relationship-empty">至少上传两个数据集后才能建立关系。</div>
    <template v-else>
      <div class="relationship-grid">
        <article><strong>左表：分析粒度</strong><label>数据集<select v-model="leftId"><option v-for="item in datasets" :key="item.id" :value="item.id" :disabled="item.id === rightId">{{ item.name }} · {{ item.profile.row_count?.toLocaleString() }} 行</option></select></label><label>关联键<select v-model="leftKey" @change="preview=null"><option v-for="field in leftColumns" :key="field.name" :value="field.name">{{ field.name }} · {{ field.unique_count }} 个唯一值</option></select></label></article>
        <div class="relationship-arrow">N → 1<small>右表键必须唯一</small><button :disabled="applying || loading" @click="[leftId, rightId] = [rightId, leftId]">交换左右表</button></div>
        <article><strong>右表：补充字段</strong><label>数据集<select v-model="rightId"><option v-for="item in datasets" :key="item.id" :value="item.id" :disabled="item.id === leftId">{{ item.name }} · {{ item.profile.row_count?.toLocaleString() }} 行</option></select></label><label>关联键<select v-model="rightKey" @change="preview=null"><option v-for="field in rightColumns" :key="field.name" :value="field.name">{{ field.name }} · {{ field.unique_count }} 个唯一值</option></select></label></article>
      </div>
      <div class="relationship-options"><label>连接方式<select v-model="joinType" @change="preview=null"><option value="left">左连接（保留全部左表行）</option><option value="inner">内连接（只保留匹配行）</option></select></label><label>右表字段前缀<input v-model="rightPrefix" @input="preview=null"></label><label>结果名称<input v-model="resultName"></label><button class="outline-btn" :disabled="loading" @click="previewRelationship">{{ loading ? '正在验证…' : '验证关系' }}</button></div>
      <div v-if="error" class="relationship-error"><b>无法建立关系</b><p>{{ error }}</p></div>
      <div v-if="preview" class="relationship-preview">
        <div class="relationship-kpis"><article><span>关系类型</span><b>{{ preview.cardinality === 'many_to_one' ? 'N:1' : '1:1' }}</b></article><article><span>左表匹配率</span><b>{{ (preview.match_rate * 100).toFixed(2) }}%</b></article><article><span>未匹配左表行</span><b>{{ preview.unmatched_left_rows.toLocaleString() }}</b></article><article><span>结果行数</span><b>{{ preview.output_rows.toLocaleString() }}</b></article></div>
        <div v-if="preview.warnings.length" class="relationship-warnings"><b>应用前必须理解</b><p v-for="warning in preview.warnings" :key="warning">{{ warning }}</p></div>
        <label v-if="preview.non_additive_columns.length" class="relationship-ack"><input v-model="acknowledged" type="checkbox">我明白右表数值在明细行会重复；系统将禁止直接求和这些字段。</label>
        <div class="relationship-actions"><button class="primary" :disabled="!canApply || applying || !resultName.trim()" @click="applyRelationship">{{ applying ? '正在生成副本…' : '确认并生成关联副本' }}</button></div>
      </div>
      <div v-if="relations.length" class="relationship-history"><b>已生成的关联副本</b><article v-for="item in relations" :key="item.id"><div><strong>{{ item.name }}</strong><span>{{ item.cardinality === 'many_to_one' ? 'N:1' : '1:1' }} · 匹配率 {{ (item.profile.match_rate * 100).toFixed(2) }}% · {{ item.profile.output_rows.toLocaleString() }} 行</span></div><button v-if="item.result_dataset" @click="emit('start-analysis', item.result_dataset.id)">交给 AI 分析</button></article></div>
    </template>
  </section>
</template>
