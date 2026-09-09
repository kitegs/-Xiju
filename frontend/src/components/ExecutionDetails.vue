<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
const props = defineProps({ runs: {type:Array,default:()=>[]}, tools: {type:Array,default:()=>[]}, evidence: {type:Array,default:()=>[]}, request: Function, workspaceId: String })
const opened=ref(false), events=ref([]), error=ref('')
let timer, generation=0
const label = s => ({completed:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断',running:'执行中',queued:'排队中'})[s] || s
const details=computed(()=>events.value.filter(e=>e.event_type==='step.completed').map(e=>({...(e.data?.execution || {title:e.step_id,tool:e.data?.tool,status:e.data?.result_status,output_summary:e.message}), attempt:e.attempt, evidence:e.data?.evidence || []})))
const entries=computed(()=>details.value.length ? details.value : props.tools.map(t=>({...t,evidence:props.evidence.filter(e=>t.evidence_ids?.includes(e.id))})))
async function load() {
  clearTimeout(timer)
  const current=++generation
  if(!opened.value || !props.request) return
  try {
    const rows=await Promise.all(props.runs.map(async r=>(await props.request(`/api/v1/analysis-runs/${r.id}/events?workspace_id=${encodeURIComponent(props.workspaceId)}`)).map(e=>({...e,attempt:r.attempt}))))
    if(current!==generation) return
    events.value=rows.flat(); error.value=''
  } catch(e) { if(current===generation) error.value=e.message }
  finally { if(current===generation && opened.value && props.runs.some(r=>['queued','running'].includes(r.status))) timer=setTimeout(load,1500) }
}
function toggle(event) { opened.value=event.target.open; if(opened.value) load(); else { ++generation; clearTimeout(timer) } }
watch(()=>props.runs.map(r=>`${r.id}:${r.status}`).join(),()=>{if(opened.value) load()})
onBeforeUnmount(()=>{++generation;clearTimeout(timer)})
</script>
<template>
  <details class="execution-details" @toggle="toggle">
    <summary>查看实际执行记录 <span v-if="tools.length">（成功 {{ tools.filter(t=>t.status==='completed').length }} / {{ tools.length }} 步）</span></summary>
    <p>这里显示真实工具调用及已保存结果，不是计划或模型内部思维。中断不会回滚已经完成的操作；中间报告可能保留为未完成草稿。已返回的 Token 保留计数，服务商未返回用量时不能按零计费，也不能保证取消立即停止远端计费。</p>
    <p v-if="error" role="alert">{{ error }} <button @click="load">重试</button></p>
    <div v-for="run in runs" :key="run.id">第 {{ run.attempt }} 次：{{ run.progress?.outcome === 'degraded' ? '已结束（存在失败或降级）' : label(run.status) }} <small>{{ run.id }}</small><p v-if="run.error">{{ run.error }}</p></div>
    <details v-for="(step,index) in entries" :key="index" class="execution-step">
      <summary>{{ label(step.status) }} · {{ step.title }} <small>{{ step.tool }} · {{ step.duration_ms || 0 }} ms</small></summary>
      <b>输入</b><pre>{{ step.input_summary || '旧记录未保存详细输入' }}</pre>
      <b>输出 / 错误</b><pre>{{ step.output_summary }}</pre>
      <small>数据引用：{{ step.data_version || '未记录' }} · 证据：{{ step.evidence_ids?.join('、') || '无' }}</small>
      <details v-if="step.code"><summary>执行代码 / 可复现方法</summary><pre>{{ step.code }}</pre></details>
      <details v-for="e in step.evidence" :key="e.id"><summary>证据 {{ e.statement || e.id }}</summary><p>{{ e.method }}</p><pre>{{ e.value }}</pre><pre v-if="e.code">{{ e.code }}</pre><details v-if="e.data?.length"><summary>结果数据（已保存的预览）</summary><pre>{{ JSON.stringify(e.data,null,2) }}</pre></details></details>
    </details>
    <details v-if="events.length"><summary>事件时间线（{{ events.length }}）</summary><p v-for="(e,i) in events" :key="i">{{ e.created_at }} · {{ e.event_type }} · {{ e.message }}</p></details>
    <p v-if="!entries.length">尚无已完成步骤，或旧运行未保存步骤明细。运行中可查看事件时间线，完成后展开回复中的工具记录。</p>
  </details>
</template>
<style scoped>
.execution-details{border:1px solid #dce2ed;border-radius:10px;padding:14px;margin:12px 0;background:#fff}.execution-details summary{cursor:pointer;color:#4256a5}.execution-details p,.execution-details small{font-size:12px;color:#63718b}.execution-step{border-top:1px solid #e6eaf0;padding:12px 0}.execution-step pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto;background:#f5f7fa;padding:10px;font-size:12px}.execution-step b{font-size:12px}
</style>
