<script setup>
defineProps({ value: { type: Object, required: true }, mode: String, status: String, busy: Boolean, ready: Boolean })
const emit = defineEmits(['change', 'mode'])
const defaults = { deep_analysis: false, max_rounds: 1, content_review: true, chart_layout: true, alternatives: false }
const switches = [
  ['deep_analysis', '深入分析', '依据当前证据补充固定只读诊断，最多增加所选轮数的模型调用。'],
  ['content_review', '报告内容审阅', '检查遗漏和矛盾；有模型时最多增加一次调用，只提供审阅意见。'],
  ['chart_layout', '图表排版优化', '统一本次新报告的布局与配色，使用本地规则，0 模型 Token。'],
  ['alternatives', '多方案对比', '比较分析过程优先与行动优先的章节顺序，0 模型 Token。'],
]
</script>

<template>
  <details class="capability-menu">
    <summary>分析能力 ▾ <small>{{ busy ? '保存中…' : status }}</small></summary>
    <div class="capability-popover">
      <b>本次对话的分析能力</b>
      <p>选择会保存到当前对话；已生成的计划保持原配置。</p>
      <fieldset :disabled="busy || !ready">
        <div class="capability-presets">
          <button type="button" @click="emit('change', { ...defaults, content_review: false, chart_layout: false })">快速分析</button>
          <button type="button" @click="emit('change', { ...defaults })">完整报告</button>
        </div>
        <label class="clarification-mode">需求澄清
          <select :value="mode" @change="emit('mode', $event.target.value)"><option value="auto">自动</option><option value="always">每次检查</option><option value="off">关闭</option></select>
        </label>
        <label v-for="[key, title, hint] in switches" :key="key" class="capability-switch">
          <input type="checkbox" :checked="value[key]" @change="emit('change', { ...value, [key]: $event.target.checked })">
          <span><b>{{ title }}</b><small>{{ hint }}</small></span>
        </label>
        <label v-if="value.deep_analysis">补充分析上限
          <select :value="value.max_rounds" @change="emit('change', { ...value, max_rounds: Number($event.target.value) })"><option :value="1">1 轮</option><option :value="2">2 轮</option><option :value="3">3 轮</option></select>
        </label>
        <label class="capability-switch unavailable"><input type="checkbox" disabled><span><b>多表关联助手 · 暂不可用</b><small>需要先接通 CSV 关联引擎。</small></span></label>
      </fieldset>
      <p>完整报告预设启用审阅和排版；仍需发送生成报告的需求。权限、基础质量检查与确认保存始终生效。</p>
    </div>
  </details>
</template>

<style scoped>
.capability-menu{position:relative;font-size:11px}.capability-menu>summary{cursor:pointer;border:1px solid #d9dcef;background:#f8f8ff;border-radius:7px;padding:7px 10px;color:#5355b6;list-style:none}.capability-menu summary small{color:#7c8499;margin-left:5px}.capability-popover{position:absolute;bottom:calc(100% + 8px);left:0;z-index:40;width:340px;max-width:calc(100vw - 45px);max-height:65vh;overflow:auto;padding:16px;border:1px solid #dfe3ef;border-radius:12px;background:var(--panel,#fff);box-shadow:0 10px 35px #24334b25;color:var(--text,#354257)}.capability-popover p{font-size:10px;line-height:1.5;color:#7d889b}.capability-popover fieldset{padding:0;border:0;margin:0;min-width:0}.capability-popover label{display:flex;gap:9px;align-items:center;margin:13px 0}.capability-switch{align-items:flex-start!important}.capability-switch input{margin-top:3px}.capability-switch small{display:block;font-size:10px;color:#7d889b;line-height:1.5;margin-top:3px}.capability-popover select{margin-left:auto;border:1px solid #dce1ec;border-radius:5px;padding:5px;background:var(--panel,#fff);color:inherit}.capability-presets{display:flex;gap:8px}.capability-presets button{flex:1;padding:7px;border:1px solid #dce1ec;border-radius:6px;background:#f6f7ff;color:#5355b6;cursor:pointer}.unavailable{opacity:.55}
</style>
