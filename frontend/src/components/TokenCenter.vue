<script setup>
import { onMounted, ref, watch } from 'vue'
import { loadTokenUsage } from '../api/usage.js'

const props = defineProps({
  workspace: { type: Object, default: null },
  request: { type: Function, required: true },
})

const range = ref('7d')
const groupBy = ref('stage')
const summary = ref(null)
const loading = ref(false)
const error = ref('')
const stageNames = { intake: '需求澄清', planning: '分析计划', synthesis: '证据结论', chart: '图表设计', report: '报告修改', dashboard: '看板设计', unknown: '旧记录' }

function number(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

async function refresh() {
  if (!props.workspace?.id || loading.value) return
  loading.value = true
  error.value = ''
  try {
    summary.value = await loadTokenUsage(props.request, props.workspace.id, range.value, groupBy.value)
  } catch (reason) {
    error.value = reason.message
  } finally {
    loading.value = false
  }
}

watch(() => props.workspace?.id, refresh)
watch([range, groupBy], refresh)
onMounted(refresh)
</script>

<template>
  <section class="token-center">
    <header>
      <div><span>TOKEN CENTER</span><h2>Token 中心</h2><p>只统计模型服务商实际返回的 Token；本地计算不消耗模型 Token。</p></div>
      <div><select v-model="range" aria-label="统计范围"><option value="today">今天</option><option value="7d">近 7 天</option><option value="all">全部</option></select><select v-model="groupBy" aria-label="分组方式"><option value="stage">按阶段</option><option value="model">按模型</option><option value="run">按运行</option><option value="report">按报告</option><option value="dashboard">按看板</option></select><button class="outline-btn" :disabled="loading" @click="refresh">刷新</button></div>
    </header>
    <p v-if="error" class="token-error">{{ error }}</p>
    <template v-else-if="summary">
      <div class="token-kpis"><article><small>总 Token</small><b>{{ number(summary.totals.total_tokens) }}</b><span>{{ summary.totals.call_count }} 次模型调用</span></article><article><small>输入 Token</small><b>{{ number(summary.totals.prompt_tokens) }}</b><span>缓存命中 {{ number(summary.totals.cache_hit_tokens) }}</span></article><article><small>输出 Token</small><b>{{ number(summary.totals.completion_tokens) }}</b><span>缓存未命中 {{ number(summary.totals.cache_miss_tokens) }}</span></article><article><small>未返回 Usage</small><b>{{ summary.unavailable_call_count }}</b><span>不会用字符数估算</span></article></div>
      <div v-if="!summary.totals.call_count" class="token-empty"><b>0 模型 Token</b><p>当前范围内只有本地确定性计算，或尚未调用模型。</p></div>
      <div v-else class="token-grid">
        <section><h3>分阶段用量</h3><div class="token-groups"><article v-for="item in summary.groups" :key="item.key"><div><b>{{ groupBy === 'stage' ? (stageNames[item.key] || item.key) : item.key }}</b><small>{{ item.call_count }} 次</small></div><strong>{{ number(item.total_tokens) }}</strong></article></div></section>
        <section><h3>最近调用</h3><div class="token-calls"><article v-for="item in summary.latest" :key="item.id"><div><b>{{ stageNames[item.stage] || item.stage }} · {{ item.purpose || '未标注用途' }}</b><small>{{ item.provider }} / {{ item.model }} · {{ new Date(item.created_at).toLocaleString() }}</small></div><strong v-if="!item.usage_unavailable">{{ number(item.total_tokens) }}</strong><em v-else>服务商未返回 Token</em></article></div></section>
      </div>
    </template>
    <div v-else class="token-empty">正在读取 Token 使用记录…</div>
  </section>
</template>
