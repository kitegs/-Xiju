<script setup>
import { computed, reactive, watch } from 'vue'

const props = defineProps({
  open: Boolean, chart: { type: Object, default: null }, fields: { type: Array, default: () => [] },
  dimensions: { type: Array, default: () => [] }, measures: { type: Array, default: () => [] }, chartTypes: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'save'])
const draft = reactive({ title:'', description:'', chart_type:'bar', x:'', y:'', second:'', aggregate:'sum', style:{} })
const numericX = computed(() => ['scatter', 'bubble', 'density_plot'].includes(draft.chart_type))
const xFields = computed(() => numericX.value ? props.fields : props.dimensions)
const secondLabel = computed(() => ['bubble', 'combo', 'heatmap', 'highlight_table'].includes(draft.chart_type) ? '第二指标 / 视觉编码' : '第二指标（可选）')

function load(chart) {
  if (!chart) return
  draft.title = chart.title || ''; draft.description = chart.description || ''; draft.chart_type = chart.chart_type || 'bar'
  draft.x = chart.x?.column || ''; draft.y = chart.y?.column || ''; draft.second = (chart.series || []).map(item => item.column).find(item => item && item !== draft.y) || ''
  draft.aggregate = chart.y?.aggregate || 'sum'
  draft.style = { palette:'insight', show_legend:true, show_labels:false, show_toolbox:true, show_data_zoom:false, stack:false, orientation:'vertical', label_position:'top', unit:'', source_label:'', dual_axis:false, show_error_bars:false, scenario:'auto', ...(chart.style || {}) }
}
function save() {
  emit('save', JSON.parse(JSON.stringify(draft)))
  emit('close')
}
watch(() => [props.open, props.chart], () => { if (props.open) load(props.chart) }, { immediate:true, deep:true })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="chart-editor-overlay" @click.self="emit('close')">
      <aside class="chart-editor-drawer" role="dialog" aria-modal="true" aria-label="编辑图表">
        <header><div><span>CHART INSPECTOR</span><h2>编辑图表</h2><p>所有设置会写回当前 ChartSpec，并立即作用于预览和报告。</p></div><button aria-label="关闭编辑器" @click="emit('close')">×</button></header>
        <main>
          <section><h3>基础</h3><label>标题<input v-model="draft.title" placeholder="图表标题"></label><label>图表说明<textarea v-model="draft.description" rows="3" placeholder="说明分析口径或结论…"/></label><label>图表类型<select v-model="draft.chart_type"><option v-for="item in chartTypes" :key="item.id" :value="item.id">{{ item.label }}</option></select></label></section>
          <section><h3>字段与计算</h3><div class="editor-grid"><label>列 / X 轴<select v-model="draft.x"><option value="">无（单指标）</option><option v-for="field in xFields" :key="field.name" :value="field.name">{{ field.name }}</option></select></label><label>行 / 主指标<select v-model="draft.y"><option value="" disabled>选择数值指标</option><option v-for="field in measures" :key="field.name" :value="field.name">{{ field.name }}</option></select></label></div><div class="editor-grid"><label>聚合<select v-model="draft.aggregate"><option value="sum">求和</option><option value="avg">平均值</option><option value="count">计数</option><option value="min">最小值</option><option value="max">最大值</option></select></label><label>{{ secondLabel }}<select v-model="draft.second"><option value="">不使用</option><option v-for="field in measures" :key="field.name" :value="field.name">{{ field.name }}</option></select></label></div></section>
          <section><h3>视觉与交互</h3><div class="editor-grid"><label>配色<select v-model="draft.style.palette"><option value="insight">Insight</option><option value="business">商务</option><option value="risk">风险</option><option value="accessible">无障碍</option></select></label><label>柱形方向<select v-model="draft.style.orientation"><option value="vertical">纵向</option><option value="horizontal">横向（柱状图）</option></select></label></div><div class="editor-grid"><label>标签位置<select v-model="draft.style.label_position"><option value="top">顶部</option><option value="inside">内部</option><option value="right">右侧</option></select></label><label>数值精度<select v-model="draft.style.decimal_places"><option :value="0">0 位小数</option><option :value="1">1 位小数</option><option :value="2">2 位小数</option></select></label></div><div class="editor-grid"><label>指标单位<input v-model="draft.style.unit" placeholder="元、件、%、万元…"></label><label>分析场景<select v-model="draft.style.scenario"><option value="auto">自动</option><option value="business">商务</option><option value="research">科研</option><option value="survey">问卷</option></select></label></div><label>数据来源说明<input v-model="draft.style.source_label" placeholder="例如：2026 年销售订单数据"></label><div class="editor-checks"><label><input v-model="draft.style.show_legend" type="checkbox">显示图例</label><label><input v-model="draft.style.show_labels" type="checkbox">显示数据标签</label><label><input v-model="draft.style.show_toolbox" type="checkbox">显示导出工具栏</label><label><input v-model="draft.style.show_data_zoom" type="checkbox">启用缩放（趋势图）</label><label><input v-model="draft.style.stack" type="checkbox">堆叠系列</label><label><input v-model="draft.style.dual_axis" type="checkbox">组合图使用双轴</label><label><input v-model="draft.style.show_error_bars" type="checkbox">标记科研误差线需求</label></div></section>
          <section class="editor-tip"><b>类型提示</b><p>散点、气泡和密度散点支持连续数值 X 轴；热力/高亮表与组合图加入第二指标后信息更完整。字段不足时仍会显示真实图表和可解释的空状态。</p></section>
        </main>
        <footer><button class="outline-btn" @click="emit('close')">取消</button><button class="primary" @click="save">应用更改</button></footer>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.chart-editor-overlay{position:fixed;inset:0;z-index:1200;background:#17233b4d;display:flex;justify-content:flex-end}.chart-editor-drawer{width:min(500px,100vw);height:100%;background:#fff;box-shadow:-14px 0 38px #17243a38;display:flex;flex-direction:column}.chart-editor-drawer>header{display:flex;justify-content:space-between;gap:16px;padding:23px 25px 17px;border-bottom:1px solid #e4e8ee}.chart-editor-drawer header span{color:#6264cc;font-size:9px;font-weight:800;letter-spacing:1px}.chart-editor-drawer h2{margin:5px 0;font-size:20px;color:#263247}.chart-editor-drawer p{margin:0;color:#8591a1;font-size:10px;line-height:1.55}.chart-editor-drawer header>button{width:28px;height:28px;border:0;border-radius:7px;background:#f2f4f7;color:#687587;font-size:20px}.chart-editor-drawer main{flex:1;overflow:auto;padding:17px 25px}.chart-editor-drawer section{padding:0 0 17px;margin-bottom:17px;border-bottom:1px solid #edf0f4}.chart-editor-drawer h3{margin:0 0 11px;color:#455268;font-size:12px}.chart-editor-drawer label{display:block;color:#708094;font-size:10px;margin:9px 0}.chart-editor-drawer input:not([type=checkbox]),.chart-editor-drawer select,.chart-editor-drawer textarea{box-sizing:border-box;width:100%;margin-top:4px;padding:8px 9px;border:1px solid #dbe1e9;border-radius:6px;background:#fff;color:#3d4a5d;font:11px inherit}.chart-editor-drawer textarea{resize:vertical}.editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.editor-grid label{min-width:0}.editor-checks{display:grid;grid-template-columns:1fr 1fr;gap:3px 10px}.editor-checks label{display:flex;align-items:center;gap:6px;margin:2px 0;font-size:10px}.editor-tip{border:0!important;background:#f4f5ff;border-left:3px solid #696ad6;padding:11px 12px!important;color:#66728a;font-size:10px;line-height:1.6}.editor-tip b{color:#5153ba}.chart-editor-drawer footer{display:flex;justify-content:flex-end;gap:8px;padding:15px 25px;border-top:1px solid #e4e8ee}@media(max-width:560px){.editor-grid,.editor-checks{grid-template-columns:1fr}.chart-editor-drawer main{padding:15px 18px}.chart-editor-drawer>header,.chart-editor-drawer footer{padding-left:18px;padding-right:18px}}
</style>
