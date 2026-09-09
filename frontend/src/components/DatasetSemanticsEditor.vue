<script setup>
import { ref, watch } from 'vue'
const props = defineProps({ dataset: Object, workspace: Object })
const emit = defineEmits(['saved', 'notice'])
const draft = ref({}), rows = ref([]), busy = ref(false), error = ref('')
watch(() => [props.dataset?.id, props.dataset?.current_version_id], () => {
  const semantics = props.dataset?.semantics || {}
  draft.value = JSON.parse(JSON.stringify(semantics))
  rows.value = (props.dataset?.profile?.columns || []).map(field => ({name: field.name,
    role: semantics.column_roles?.[field.name] || '', label: semantics.column_labels?.[field.name] || '',
    unit: semantics.column_units?.[field.name] || '', format: semantics.date_formats?.[field.name] || '',
    restricted: semantics.non_additive_columns?.includes(field.name)}))
  error.value = ''
}, {immediate: true})
async function save() {
  if(busy.value) return
  busy.value = true; error.value = ''
  const datasetId = props.dataset.id
  try {
    const body = {workspace_id: props.workspace.id, unit: draft.value.unit || '', currency: draft.value.currency || '',
      grain: draft.value.grain || '', column_roles: {}, column_labels: {}, column_units: {}, date_formats: {},
      value_labels: draft.value.value_labels || {}}
    for(const row of rows.value) {
      if(row.role) body.column_roles[row.name] = row.role
      if(row.label.trim()) body.column_labels[row.name] = row.label.trim()
      if(row.unit.trim()) body.column_units[row.name] = row.unit.trim()
      if(row.format.trim()) body.date_formats[row.name] = row.format.trim()
    }
    const response = await fetch(`/api/v1/datasets/${datasetId}/semantics`, {method: 'PATCH',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
    const result = await response.json()
    if(!response.ok) throw new Error(result.detail || '保存失败')
    emit('saved', result)
    emit('notice', '字段口径已保存为数据新版本；已有报告保持原口径，新报告使用新设置。')
  } catch(err) { error.value = err.message } finally { busy.value = false }
}
</script>
<template>
  <section class="semantics-editor">
    <h3>字段口径</h3><p>数字编码不一定是度量。请把季节、小时等分类字段设为维度，记录编号设为标识符。设置不会改写 CSV 原件。</p>
    <div class="metadata"><label>数据粒度<input v-model="draft.grain" placeholder="例如每小时一行"></label><label>默认单位<input v-model="draft.unit" placeholder="例如次、元"></label><label>币种<input v-model="draft.currency" placeholder="非金额数据可留空"></label></div>
    <div class="fields"><table><thead><tr><th>原字段</th><th>中文名称</th><th>分析角色</th><th>单位</th><th>日期格式</th></tr></thead><tbody>
      <tr v-for="row in rows" :key="row.name"><td>{{ row.name }}<small v-if="row.restricted">关联重复指标，禁止直接累计</small></td>
        <td><input v-model="row.label" :aria-label="`${row.name} 显示名称`"></td>
        <td><select v-model="row.role" :aria-label="`${row.name} 角色`"><option value="">自动识别</option><option value="dimension">维度</option><option value="measure">度量</option><option value="date">日期</option><option value="id">标识符</option><option value="ignore">忽略</option></select></td>
        <td><input v-model="row.unit" :aria-label="`${row.name} 单位`"></td><td><input v-model="row.format" :aria-label="`${row.name} 日期格式`" placeholder="%Y-%m-%d"></td></tr>
    </tbody></table></div>
    <p>日期格式按 Python strptime 规则填写；解析率不足 80% 时不会保存。转换原值请使用“清洗配方”预览并生成副本。</p>
    <p v-if="error" role="alert">{{ error }}</p><button class="primary" :disabled="busy" @click="save">{{ busy ? '保存中…' : '保存字段口径' }}</button>
  </section>
</template>
<style scoped>
.semantics-editor{padding:24px}.semantics-editor p{color:#63748b;font-size:13px;line-height:1.7}.metadata{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0}.metadata label{display:grid;gap:6px}.fields{max-height:48vh;overflow:auto}.fields table{width:100%;border-collapse:collapse}.fields th{position:sticky;top:0;background:#f3f6fc}.fields td,.fields th{padding:9px;text-align:left;border-bottom:1px solid #e4e9f2}.fields small{display:block;color:#9a6100;font-size:11px}.semantics-editor input,.semantics-editor select{box-sizing:border-box;width:100%;min-width:85px;padding:8px;border:1px solid #dce2ed;border-radius:6px}.semantics-editor [role=alert]{color:#ac2939}
</style>
