<script setup>
const props=defineProps({value:{type:Object,default:()=>({})},disabled:Boolean})
const emit=defineEmits(['change'])
function set(key,value){emit('change',{...props.value,[key]:value})}
</script>
<template><details class="report-requirements"><summary>报告要求 · {{ {brief:'简要',standard:'标准',detailed:'详细'}[value.depth] || '自动识别' }}</summary>
<div><label>篇幅<select :disabled="disabled" :value="value.depth || 'auto'" @change="set('depth',$event.target.value)"><option value="auto">从对话识别</option><option value="brief">简要</option><option value="standard">标准</option><option value="detailed">详细</option></select></label>
<label>主题<select :disabled="disabled" :value="value.focus || 'auto'" @change="set('focus',$event.target.value)"><option value="auto">从对话识别</option><option value="general">综合分析</option><option value="loss">亏损专题</option><option value="hourly">小时需求</option></select></label>
<label>受众<select :disabled="disabled" :value="value.audience || 'auto'" @change="set('audience',$event.target.value)"><option value="auto">从对话识别</option><option value="manager">管理者</option><option value="analyst">分析人员</option></select></label>
<label><input type="checkbox" :disabled="disabled" :checked="value.exclude_trend" @change="set('exclude_trend',$event.target.checked)">不含趋势</label><label><input type="checkbox" :disabled="disabled" :checked="value.exclude_forecast" @change="set('exclude_forecast',$event.target.checked)">不做预测</label>
<label>必须包含<input :disabled="disabled" :value="value.must_include" maxlength="1000" @input="set('must_include',$event.target.value)" placeholder="自由要求仍需人工核验"></label><label>不要包含<input :disabled="disabled" :value="value.must_exclude" maxlength="1000" @input="set('must_exclude',$event.target.value)"></label></div>
<small>明确选择优先于自动识别。简报隐藏附录但保留证据；自定义文字要求不保证自动满足。</small></details></template>
<style scoped>.report-requirements{padding:10px 24px;background:#f5f7fc;border-top:1px solid #dde3ef}.report-requirements summary{cursor:pointer;color:#4655a7}.report-requirements div{display:flex;flex-wrap:wrap;gap:12px;padding:12px 0}.report-requirements label{font-size:12px}.report-requirements input,.report-requirements select{padding:5px;border:1px solid #dce2ed;border-radius:5px}.report-requirements small{color:#77849b}</style>
