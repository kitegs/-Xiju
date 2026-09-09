<script setup>
import { computed } from 'vue'
import { VChart } from '../plugins/echarts'
import { buildChartOption, chartFields, SUPPORTED_CHART_TYPES } from '../lib/chartOptions'

const props = defineProps({ chart: { type: Object, required: true }, compact: Boolean, selected: Boolean })
const emit = defineEmits(['select', 'context-menu'])
const rows = computed(() => props.chart?.data || [])
const dimension = computed(() => props.chart?.x?.column || 'label')
const measures = computed(() => chartFields(props.chart))
const option = computed(() => buildChartOption(props.chart))
const isTable = computed(() => props.chart?.chart_type === 'table')
const isKpi = computed(() => props.chart?.chart_type === 'kpi')
const isSupported = computed(() => SUPPORTED_CHART_TYPES.has(props.chart?.chart_type || 'bar'))
const number = value => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })
const label = row => row[dimension.value] ?? row.label ?? '值'
const value = (row, key = measures.value[0]) => Number(row[key] ?? row.value ?? 0)
</script>

<template>
  <div class="viz" :class="[{ compact, selected }, `viz-${chart.chart_type}`]" @click.stop="emit('select')" @contextmenu.prevent="emit('context-menu', $event)">
    <header><div><b>{{ chart.title }}</b><small>{{ chart.description }}</small></div><span>{{ chart.chart_type }}</span></header>
    <div v-if="!isSupported" class="viz-upgrade-note"><b>暂不支持此图表类型</b><p>请选择智能显示面板中已开放的 ECharts 图表。</p></div>
    <div v-else-if="isKpi" class="viz-kpi"><strong>{{ number(value(rows[0] || {})) }}{{ rows[0]?.suffix }}</strong><small>{{ label(rows[0] || {}) }}</small></div>
    <div v-else-if="isTable" class="viz-table"><div class="viz-tr viz-th"><span>{{ dimension }}</span><span v-for="key in measures" :key="key">{{ key }}</span></div><div v-for="row in rows.slice(0, compact ? 6 : 14)" :key="JSON.stringify(row)" class="viz-tr"><span>{{ label(row) }}</span><b v-for="key in measures" :key="key">{{ number(value(row,key)) }}</b></div></div>
    <VChart v-else class="echarts-preview" :option="option" autoresize />
  </div>
</template>
