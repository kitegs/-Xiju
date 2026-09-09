<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  intake: { type: Object, required: true },
  submitting: { type: Boolean, default: false },
})
const emit = defineEmits(['submit'])
const answers = reactive({})

watch(() => props.intake, value => {
  Object.keys(answers).forEach(key => delete answers[key])
  for (const question of value?.questions || []) answers[question.question_key] = ''
}, { immediate: true })

function submit(useDefaults) {
  emit('submit', { answers: Object.fromEntries(Object.entries(answers).filter(([, value]) => value.trim())), useDefaults })
}
</script>

<template>
  <section class="intake-card">
    <header><div><span>ANALYSIS BRIEF</span><h3>开始前一次确认这些信息</h3><p>回答会明显影响结论的问题；不确定的项目可以采用推荐值，报告会明确标记为未经确认的业务假设。</p></div><b>{{ intake.questions.length }} 项</b></header>
    <div class="intake-questions">
      <label v-for="(question, index) in intake.questions" :key="question.question_key"><span>{{ index + 1 }}</span><div><b>{{ question.prompt }}</b><input v-model="answers[question.question_key]" :placeholder="question.recommended_default"><small>{{ question.reason }} · 影响：{{ question.affects.join('、') }}</small><button type="button" @click="answers[question.question_key] = question.recommended_default">采用推荐值：{{ question.recommended_default }}</button></div></label>
    </div>
    <footer><button class="outline-btn" :disabled="submitting" @click="submit(true)">使用推荐默认值继续</button><button class="primary" :disabled="submitting" @click="submit(false)">{{ submitting ? '正在继续…' : '提交回答并继续' }}</button></footer>
  </section>
</template>
