<script setup>
defineProps({ results: { type: Array, default: () => [] } })
const names = { 'analysis.deepen': '深入分析', 'report.review': '内容审阅', 'report.layout': '图表排版', 'report.alternatives': '多方案比较' }
</script>
<template>
  <section v-if="results.length" class="component-results">
    <h4>分析能力执行结果</h4>
    <details v-for="(item, index) in results" :key="index">
      <summary>{{ names[item.tool] || item.tool }} · {{ ({completed:'完成',failed:'失败',skipped:'未执行'})[item.status] }}<small v-if="item.usage"> · {{ item.usage.unavailable ? '部分用量未返回' : `${item.usage.total_tokens} Token` }} · {{ item.usage.calls }} 次模型调用</small></summary>
      <p v-if="item.error">{{ item.error }}</p>
      <template v-if="item.result">
        <p>{{ item.result.note || item.result.stop_reason }}</p>
        <ul v-if="item.result.rounds"><li v-for="(round, i) in item.result.rounds" :key="i">{{ round.tool }}：{{ round.reason }} <small>{{ round.evidence_id }}</small></li></ul>
        <template v-if="item.result.local"><b>基础检查：{{ item.result.local.passed ? '通过' : '需处理' }}</b><ul><li v-for="issue in item.result.local.issues" :key="issue.id">{{ issue.title }}：{{ issue.detail }}</li></ul><p v-if="!item.result.model">未调用模型，已执行本地检查。</p></template>
        <template v-if="item.result.model"><div v-for="(label, key) in {omissions:'可能遗漏',contradictions:'可能矛盾',recommendations:'修改建议'}" :key="key"><b>{{ label }}</b><ul><li v-for="(text, i) in item.result.model[key]" :key="i">{{ text }}</li></ul></div></template>
        <div v-if="item.result.changes">已调整 {{ item.result.changes.length }} 张图表。<details><summary>查看前后配置</summary><pre>{{ JSON.stringify(item.result.changes, null, 2) }}</pre></details></div>
        <div v-for="proposal in item.result.proposals || []" :key="proposal.label"><b>{{ proposal.label }}</b><p>{{ proposal.description }}</p><ol><li v-for="id in proposal.block_ids.filter(id => item.result.sections.some(s => s.block_ids[0] === id))" :key="id">{{ item.result.sections.find(s => s.block_ids[0] === id)?.title }}</li></ol></div>
      </template>
    </details>
  </section>
</template>
<style scoped>
.component-results{border:1px solid #dfe4ef;border-radius:9px;padding:12px;margin:12px 0;font-size:11px;line-height:1.6}.component-results h4{margin:0 0 8px}.component-results>details{border-top:1px solid #e6e9ef;padding:8px 0}.component-results summary{cursor:pointer;color:#585abd}.component-results small{color:#7c8696}.component-results pre{overflow:auto;max-height:220px;white-space:pre-wrap}.component-results ul,.component-results ol{padding-left:20px}
</style>
