<script setup>
import { computed, ref } from 'vue'

const props = defineProps({ workspace: Object, reports: Array, templates: Array, selectedReport: Object })
const emit = defineEmits(['upload', 'render', 'notice'])
const fileInput = ref(null)
const selectedTemplateId = ref('')
const selectedReportId = ref('')
const mapping = ref({})
const selectedTemplate = computed(() => props.templates?.find(item => item.id === selectedTemplateId.value))

function chooseTemplate(id) {
  selectedTemplateId.value = id
  const item = props.templates?.find(row => row.id === id)
  mapping.value = Object.fromEntries((item?.placeholders || []).map(key => [key, '']))
}
function upload(event) { const file = event.target.files?.[0]; if (file) emit('upload', file); event.target.value = '' }
function placeholdersPreview(item) { return (item.placeholders || []).slice(0, 4).map(key => '{' + '{ ' + key + ' }' + '}').join(' · ') || '未检测到占位符' }
function placeholderLabel(key) { return '{' + '{ ' + key + ' }' + '}' }
function render() {
  if (!selectedTemplateId.value || !(selectedReportId.value || props.selectedReport?.id)) return emit('notice', '请先选择模板和报告')
  emit('render', { templateId: selectedTemplateId.value, reportId: selectedReportId.value || props.selectedReport.id, mapping: mapping.value })
}
</script>

<template>
  <main class="template-center">
    <header class="simple-header"><div><span>WORD TEMPLATE CENTER</span><h1>报告模板</h1><p>仅接受安全 DOCX；保留版式、页眉页脚和表格，使用占位符填充数据与结论。</p></div><button class="primary" @click="fileInput?.click()">＋ 上传 Word 模板</button><input ref="fileInput" type="file" accept=".docx" hidden @change="upload" /></header>
    <section class="template-safety"><b>安全边界</b><span>拒绝 DOCM、宏、嵌入对象和外部链接；填充只生成新文件，不会改写原模板。</span></section>
    <div class="template-layout">
      <section class="template-list"><article v-for="item in templates" :key="item.id" :class="{active:selectedTemplateId===item.id}" @click="chooseTemplate(item.id)"><span>W</span><div><b>{{ item.name }}</b><small>{{ item.placeholders.length }} 个占位符 · {{ Math.ceil(item.size_bytes / 1024) }} KB</small><p>{{ placeholdersPreview(item) }}</p></div></article><div v-if="!templates?.length" class="empty-card">还没有模板。建议在 Word 中使用 <code v-pre>{{ report.title }}</code>、<code v-pre>{{ metric.sales }}</code>、<code v-pre>{{ recommendations }}</code> 作为占位符。</div></section>
      <section class="template-map"><template v-if="selectedTemplate"><h2>{{ selectedTemplate.name }}</h2><p>选择报告后，可为未自动映射的占位符填入固定文字；系统会自动提供报告标题、摘要、指标、建议和图表。</p><label>报告<select v-model="selectedReportId"><option value="">{{ selectedReport?.title || '选择报告' }}</option><option v-for="report in reports" :key="report.id" :value="report.id">{{ report.title }}</option></select></label><div class="mapping-grid"><label v-for="key in selectedTemplate.placeholders" :key="key"><code>{{ placeholderLabel(key) }}</code><input v-model="mapping[key]" :placeholder="key.startsWith('chart.') ? '图表占位符自动填充' : '留空则使用自动映射'" /></label></div><button class="primary" @click="render">生成固定格式 DOCX</button></template><div v-else class="empty-card">选择左侧模板，查看占位符并生成报告。</div></section>
    </div>
  </main>
</template>
