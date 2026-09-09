const palettes = {
  insight: ['#5b5bd6', '#24a17a', '#ee8d45', '#d95878', '#3f8fc5', '#8f65c8'],
  business: ['#2457a6', '#3c9a76', '#d88438', '#bb4d62', '#75859a', '#775b3d'],
  risk: ['#a93847', '#dd7948', '#d5aa35', '#548a75', '#4f6ea7', '#87658e'],
  accessible: ['#0072B2', '#E69F00', '#009E73', '#CC79A7', '#56B4E9', '#D55E00'],
}

const number = value => Number.isFinite(Number(value)) ? Number(value) : 0
const unique = values => [...new Set(values)]
const clamp = (value, min, max) => Math.max(min, Math.min(max, value))
const quantile = (values, q) => {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b)
  if (!sorted.length) return 0
  const index = (sorted.length - 1) * q; const base = Math.floor(index); const rest = index - base
  return sorted[base + 1] === undefined ? sorted[base] : sorted[base] + rest * (sorted[base + 1] - sorted[base])
}

export const SUPPORTED_CHART_TYPES = new Set([
  'bar', 'line', 'area', 'combo', 'scatter', 'bubble', 'pie', 'donut',
  'highlight_table', 'heatmap', 'treemap', 'histogram', 'boxplot', 'kpi',
  'waterfall', 'pareto', 'control_chart', 'gauge', 'radar', 'density_plot', 'table',
])

export function chartFields(chart) {
  const primary = chart?.y?.column
  const series = (chart?.series || []).map(item => item.column).filter(Boolean)
  return [...new Set(series.length ? series : primary ? [primary] : ['value'])]
}

function base(chart, colors) {
  const showLegend = chart?.style?.show_legend !== false
  const decimals = Number.isInteger(chart?.style?.decimal_places) ? chart.style.decimal_places : 2
  const showZoom = Boolean(chart?.style?.show_data_zoom)
  return {
    color: colors, animationDuration: 420, animationDurationUpdate: 250,
    tooltip: { trigger: 'axis', confine: true, valueFormatter: value => Number(value).toLocaleString(undefined, { maximumFractionDigits: decimals }) },
    legend: { show: showLegend, bottom: 0, type: 'scroll', textStyle: { fontSize: 10, color: '#657286' } },
    toolbox: { show: chart?.style?.show_toolbox !== false, right: 10, top: 4, feature: { restore: {}, saveAsImage: { title: '导出图片' } } },
    ...(showZoom ? { dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: showLegend ? 27 : 4, height: 14 }] } : {}),
    grid: { left: 52, right: 28, top: 40, bottom: showLegend ? 52 : 30, containLabel: true },
  }
}

function categoryAxis(labels) {
  return { type: 'category', data: labels, axisLabel: { color: '#718096', fontSize: 10, rotate: labels.length > 9 ? 28 : 0, overflow: 'truncate', width: 90 }, axisLine: { lineStyle: { color: '#dbe1e9' } } }
}

function valueAxis(name = '') {
  return { type: 'value', name, nameTextStyle: { color: '#8190a1', fontSize: 10 }, axisLabel: { color: '#718096', fontSize: 10 }, splitLine: { lineStyle: { color: '#edf0f4' } } }
}

function histogram(values) {
  const min = Math.min(...values, 0); const max = Math.max(...values, 1); const width = Math.max((max - min) / Math.min(12, Math.max(5, Math.ceil(Math.sqrt(values.length)))), 1)
  const bins = Array.from({ length: Math.max(1, Math.ceil((max - min) / width)) }, (_, index) => ({ start: min + index * width, count: 0 }))
  values.forEach(value => { bins[Math.min(bins.length - 1, Math.max(0, Math.floor((value - min) / width)))].count += 1 })
  return { labels: bins.map(bin => `${bin.start.toFixed(1)}–${(bin.start + width).toFixed(1)}`), counts: bins.map(bin => bin.count) }
}

function heatmapOption(option, labels, fields, rows, labelVisible) {
  const values = fields.flatMap(field => rows.map(row => Math.abs(number(row[field]))))
  const maximum = Math.max(...values, 1)
  option.tooltip = { position: 'top', confine: true }
  option.grid = { left: 62, right: 30, top: 35, bottom: 75, containLabel: true }
  option.xAxis = categoryAxis(labels)
  option.yAxis = categoryAxis(fields)
  option.visualMap = { min: 0, max: maximum, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#eef1ff', '#9c9de8', '#4c4eb9'] }, textStyle: { fontSize: 9 } }
  option.series = [{ type: 'heatmap', data: fields.flatMap((field, y) => rows.map((row, x) => [x, y, number(row[field])])), label: { show: labelVisible, fontSize: 9, formatter: item => Number(item.value[2]).toLocaleString() }, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,.25)' } } }]
  return option
}

export function buildChartOption(chart) {
  const rows = chart?.data || []; const fields = chartFields(chart); const type = chart?.chart_type || 'bar'
  const dimension = chart?.x?.column || 'label'; const labels = rows.map((row, index) => String(row[dimension] ?? row.label ?? index + 1))
  const colors = palettes[chart?.style?.palette] || palettes.insight; const labelVisible = Boolean(chart?.style?.show_labels)
  const option = base(chart, colors)
  const seriesValues = field => rows.map(row => number(row[field] ?? row.value))
  const standardSeries = (kind, extra = {}) => fields.map((field, index) => ({ name: field, type: kind, data: seriesValues(field), smooth: kind === 'line', stack: chart?.style?.stack ? 'total' : undefined, label: labelVisible ? { show: true, position: chart?.style?.label_position || 'top', fontSize: 9 } : undefined, emphasis: { focus: 'series' }, ...extra, itemStyle: { color: colors[index % colors.length], ...(extra.itemStyle || {}) } }))
  if (!rows.length) return { ...option, title: { text: '等待选择字段并计算数据', left: 'center', top: 'middle', textStyle: { color: '#94a0ae', fontSize: 13, fontWeight: 'normal' } }, xAxis: { show: false }, yAxis: { show: false }, series: [] }

  if (type === 'pie' || type === 'donut') return { ...option, tooltip: { trigger: 'item', formatter: '{b}<br/>{c}（{d}%）' }, legend: { ...option.legend, orient: 'vertical', right: 10, top: 'middle' }, series: [{ name: fields[0], type: 'pie', radius: type === 'donut' ? ['42%', '70%'] : '68%', center: ['42%', '50%'], data: rows.map(row => ({ name: String(row[dimension] ?? row.label ?? '值'), value: number(row[fields[0]] ?? row.value) })), label: { show: labelVisible, formatter: '{b}: {d}%' }, emphasis: { itemStyle: { shadowBlur: 12, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,.25)' } } }] }
  if (type === 'treemap') return { ...option, tooltip: { formatter: item => `${item.name}<br/>${Number(item.value).toLocaleString()}` }, legend: { show: false }, series: [{ type: 'treemap', roam: false, breadcrumb: { show: false }, label: { show: true, formatter: '{b}', fontSize: 10 }, data: rows.map(row => ({ name: String(row[dimension] ?? row.label ?? '值'), value: Math.abs(number(row[fields[0]] ?? row.value)) })) }] }
  if (type === 'heatmap' || type === 'highlight_table') return heatmapOption(option, labels, fields, rows, type === 'highlight_table' || labelVisible)
  if (type === 'histogram') { const values = seriesValues(fields[0]); const bins = histogram(values); return { ...option, xAxis: categoryAxis(bins.labels), yAxis: valueAxis('频数'), series: [{ name: fields[0], type: 'bar', data: bins.counts, label: labelVisible ? { show: true, position: 'top' } : undefined, itemStyle: { color: colors[0] } }] } }
  if (type === 'boxplot') return { ...option, xAxis: categoryAxis(fields), yAxis: valueAxis(), tooltip: { trigger: 'item', confine: true }, series: [{ type: 'boxplot', data: fields.map(field => { const values = seriesValues(field); return [Math.min(...values), quantile(values, .25), quantile(values, .5), quantile(values, .75), Math.max(...values)] }), itemStyle: { color: colors[0] } }] }
  if (type === 'gauge') { const value = number(rows[0]?.[fields[0]] ?? rows[0]?.value); return { ...option, legend: { show: false }, series: [{ type: 'gauge', progress: { show: true, width: 18 }, axisLine: { lineStyle: { width: 18, color: [[.6, colors[1]], [.8, colors[2]], [1, colors[3]]] } }, detail: { valueAnimation: true, formatter: value => Number(value).toLocaleString(), fontSize: 20 }, data: [{ value, name: fields[0] }], title: { fontSize: 11 } }] } }
  if (type === 'radar') { const maximum = Math.max(...fields.flatMap(seriesValues).map(Math.abs), 1) * 1.15; return { ...option, radar: { indicator: labels.map(name => ({ name, max: maximum })), axisName: { fontSize: 9 }, splitArea: { areaStyle: { color: ['#fafbff', '#f3f5ff'] } } }, series: [{ type: 'radar', data: fields.map((field, index) => ({ name: field, value: seriesValues(field), areaStyle: { color: `${colors[index % colors.length]}33` } })) }] } }
  if (type === 'scatter' || type === 'bubble' || type === 'density_plot') {
    const xNumbers = rows.map((row, index) => Number(row[dimension])).every(Number.isFinite)
    const third = fields[1] || fields[0]; const bubbleValues = seriesValues(third); const bubbleMax = Math.max(...bubbleValues.map(Math.abs), 1)
    const scatterSeries = fields.slice(0, type === 'bubble' ? 1 : Math.max(1, fields.length)).map((field, index) => ({ name: field, type: 'scatter', data: rows.map((row, rowIndex) => xNumbers ? [number(row[dimension]), number(row[field])] : [labels[rowIndex], number(row[field])]), symbolSize: type === 'bubble' ? (_value, indexValue) => clamp(7 + Math.abs(bubbleValues[indexValue.dataIndex] || 0) / bubbleMax * 28, 7, 35) : type === 'density_plot' ? 5 : 10, itemStyle: { color: colors[index % colors.length], opacity: type === 'density_plot' ? .34 : .78 } }))
    return { ...option, xAxis: xNumbers ? valueAxis(dimension) : categoryAxis(labels), yAxis: valueAxis(fields[0]), series: scatterSeries }
  }
  if (type === 'waterfall') { const values = seriesValues(fields[0]); let running = 0; const offsets = values.map(value => { const before = running; running += value; return value >= 0 ? before : running }); return { ...option, xAxis: categoryAxis(labels), yAxis: valueAxis(fields[0]), series: [{ name: '辅助', type: 'bar', stack: 'total', data: offsets, itemStyle: { color: 'transparent' }, emphasis: { disabled: true } }, { name: '增加', type: 'bar', stack: 'total', data: values.map(value => value >= 0 ? value : '-'), itemStyle: { color: '#24a17a' } }, { name: '减少', type: 'bar', stack: 'total', data: values.map(value => value < 0 ? -value : '-'), itemStyle: { color: '#d95878' } }] } }
  if (type === 'pareto') { const sorted = rows.map((row, index) => ({ label: labels[index], value: number(row[fields[0]]) })).sort((a, b) => b.value - a.value); const total = sorted.reduce((sum, row) => sum + row.value, 0) || 1; let running = 0; const percentages = sorted.map(row => { running += row.value; return +(running / total * 100).toFixed(1) }); return { ...option, xAxis: categoryAxis(sorted.map(row => row.label)), yAxis: [valueAxis(fields[0]), { ...valueAxis('累计 %'), max: 100 }], series: [{ name: fields[0], type: 'bar', data: sorted.map(row => row.value), itemStyle: { color: colors[0] } }, { name: '累计 %', type: 'line', yAxisIndex: 1, data: percentages, smooth: true, label: labelVisible ? { show: true, formatter: '{c}%' } : undefined, itemStyle: { color: colors[3] } }] } }
  if (type === 'control_chart') { const values = seriesValues(fields[0]); const mean = values.reduce((sum, value) => sum + value, 0) / values.length; const deviation = Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(values.length - 1, 1)); return { ...option, xAxis: categoryAxis(labels), yAxis: valueAxis(fields[0]), series: [{ name: fields[0], type: 'line', data: values, smooth: true, itemStyle: { color: colors[0] } }, { name: '均值', type: 'line', data: values.map(() => mean), symbol: 'none', lineStyle: { type: 'dashed', color: colors[1] } }, { name: 'UCL +3σ', type: 'line', data: values.map(() => mean + 3 * deviation), symbol: 'none', lineStyle: { type: 'dashed', color: colors[3] } }, { name: 'LCL −3σ', type: 'line', data: values.map(() => mean - 3 * deviation), symbol: 'none', lineStyle: { type: 'dashed', color: colors[3] } }] } }
  if (type === 'combo') {
    const dualAxis = Boolean(chart?.style?.dual_axis && fields.length > 1)
    return { ...option, xAxis: categoryAxis(labels), yAxis: dualAxis ? [valueAxis(chart?.style?.unit || fields[0]), valueAxis(fields[1])] : valueAxis(chart?.style?.unit || ''), series: fields.map((field, index) => ({ name: field, type: index ? 'line' : 'bar', yAxisIndex: dualAxis && index ? 1 : 0, data: seriesValues(field), smooth: index > 0, label: labelVisible ? { show: true, position: 'top', fontSize: 9 } : undefined, itemStyle: { color: colors[index % colors.length] } })) }
  }
  if (type === 'bar' && chart?.style?.orientation === 'horizontal') return { ...option, xAxis: valueAxis(), yAxis: categoryAxis(labels), series: standardSeries('bar') }
  const line = type === 'line' || type === 'area'
  return { ...option, xAxis: categoryAxis(labels), yAxis: valueAxis(), series: standardSeries(line ? 'line' : 'bar', type === 'area' ? { areaStyle: { opacity: .2 } } : {}) }
}
