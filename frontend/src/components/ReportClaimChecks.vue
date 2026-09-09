<script setup>
defineProps({ quality:Object, dirty:Boolean, proposal:Object, busy:Boolean })
const emit=defineEmits(['locate','preview','apply','discard'])
const types={fact:'事实',inference:'推测/解释',prediction:'预测',recommendation:'建议',assumption:'未经确认的假设'}
</script>
<template>
  <details class="claim-checks">
    <summary>结论与证据核验 · {{ dirty ? '内容已修改，保存后重新检查' : quality?.passed ? '当前规则检查通过' : '待核验 / 不可标为可交付' }}</summary>
    <p>本轮校验确定性生成基线、引用完整性及结构化计算。文字改写后不自动认证；检查通过不代表因果、业务假设或外部数据真实性已获证明。</p>
    <p v-if="dirty">下方是上次保存的检查结果，不能用于认证当前未保存内容。</p>
    <button :disabled="dirty || busy" @click="emit('preview')">{{ busy ? '正在重算…' : '重算并预览修复' }}</button>
    <section v-if="proposal" class="repair-proposal">
      <h4>修复提案 · {{ proposal.changes.length }} 项差异</h4>
      <p>{{ proposal.note }}</p>
      <small>数据版本：{{ proposal.dataset_version_id }} · SHA-256：{{ proposal.data_hash }}</small>
      <details v-for="(change,index) in proposal.changes" :key="index"><summary>{{ change.target }} · {{ change.field }}</summary><b>修复前</b><pre>{{ typeof change.before==='string'?change.before:JSON.stringify(change.before,null,2) }}</pre><b>修复后</b><pre>{{ typeof change.after==='string'?change.after:JSON.stringify(change.after,null,2) }}</pre></details>
      <p>修复后：{{ proposal.quality.passed?'当前规则检查通过':`${proposal.quality.issues.length} 项仍需处理` }}</p>
      <button :disabled="dirty || busy" @click="emit('apply')">确认修复并保存版本</button>
      <button :disabled="busy" @click="emit('discard')">放弃提案</button>
    </section>
    <article v-for="(item,index) in quality?.claim_checks || []" :key="index">
      <b>{{ types[item.type] || '未分类' }} · {{ item.status==='verified'?'基线/计算一致':item.status==='assumption'?'未确认':'待核验' }}</b>
      <p>{{ item.text }}</p><small>{{ item.reason }} 依据：{{ item.evidence_ids.join('、') || '报告生成基线' }}</small>
      <button v-if="['block','finding','interpretation','recommendation'].includes(item.target_kind)" @click="emit('locate',item)">定位内容</button>
    </article>
    <p v-if="!quality?.claim_checks?.length">暂无结论校验记录，请保存检查或重新生成报告。</p>
  </details>
</template>
<style scoped>
.repair-proposal{border:1px solid #dce1ed;padding:12px;margin:10px 0}.repair-proposal pre{white-space:pre-wrap;max-height:180px;overflow:auto}.repair-proposal small{overflow-wrap:anywhere}
.claim-checks{padding:10px 22px;background:#f7f8fd;border-bottom:1px solid #dce1ed;font-size:12px;max-height:35vh;overflow:auto}.claim-checks summary{cursor:pointer;color:#5155a8}.claim-checks article{padding:9px 0;border-top:1px solid #dce1ed}.claim-checks p{margin:6px 0}.claim-checks small{color:#687487}.claim-checks button{margin-left:10px;cursor:pointer}
</style>
