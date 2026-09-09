<script setup>
import { ref } from 'vue'

defineProps({
  workspace: { type: Object, default: null },
  context: { type: Object, default: null },
  audit: { type: Array, default: () => [] },
})
const emit = defineEmits(['invite', 'update-role', 'remove-member', 'refresh'])
const email = ref('')
const displayName = ref('')
const role = ref('viewer')
function invite() {
  if (!email.value.trim() || !displayName.value.trim()) return
  emit('invite', { email: email.value.trim(), display_name: displayName.value.trim(), role: role.value })
  email.value = ''; displayName.value = ''; role.value = 'viewer'
}
const roleLabel = value => ({ owner: '所有者', admin: '管理员', analyst: '分析师', viewer: '查看者' })[value] || value
</script>

<template>
  <div class="team-workspace">
    <header class="simple-header team-header">
      <div><span>TEAM WORKSPACE</span><h1>团队与治理</h1><p>成员、角色、报告审核和操作审计集中在当前工作区。</p></div>
      <div class="team-current"><small>当前身份</small><b>{{ context?.members?.find(m => m.user_id === context?.current_user_id)?.display_name || '本机所有者' }}</b><span>{{ roleLabel(context?.current_role) }}</span></div>
    </header>
    <div class="team-grid">
      <section class="team-panel">
        <div class="panel-title"><div><h2>成员</h2><p>{{ workspace?.name }} · {{ context?.members?.length || 0 }} 人</p></div><button class="outline-btn" @click="emit('refresh')">刷新</button></div>
        <div v-if="context?.permissions?.includes('member.manage')" class="invite-row">
          <input v-model.trim="displayName" placeholder="姓名" aria-label="成员姓名">
          <input v-model.trim="email" type="email" placeholder="name@company.com" aria-label="成员邮箱">
          <select v-model="role" aria-label="成员角色"><option value="admin">管理员</option><option value="analyst">分析师</option><option value="viewer">查看者</option></select>
          <button class="primary" @click="invite">添加成员</button>
        </div>
        <div class="member-list">
          <article v-for="member in context?.members || []" :key="member.id">
            <span class="member-avatar">{{ member.display_name.slice(0, 1) }}</span>
            <div><b>{{ member.display_name }}</b><small>{{ member.email }}</small></div>
            <span v-if="member.role === 'owner'" class="status-pill">所有者</span>
            <select v-else :value="member.role" :disabled="!context?.permissions?.includes('member.manage')" @change="emit('update-role', member, $event.target.value)"><option value="admin">管理员</option><option value="analyst">分析师</option><option value="viewer">查看者</option></select>
            <button v-if="member.role !== 'owner' && context?.permissions?.includes('member.manage')" class="danger-link" @click="emit('remove-member', member)">移除</button>
          </article>
        </div>
      </section>
      <section class="team-panel permission-panel">
        <div class="panel-title"><div><h2>角色边界</h2><p>权限由后端检查，界面隐藏不能替代授权。</p></div></div>
        <div class="role-matrix">
          <div><b>Owner</b><span>工作区、成员、数据、审核、发布、审计</span></div>
          <div><b>Admin</b><span>成员、数据、审核、发布、审计</span></div>
          <div><b>Analyst</b><span>数据分析、报告编辑、提交审核与批注</span></div>
          <div><b>Viewer</b><span>只读查看已授权报告</span></div>
        </div>
      </section>
      <section class="team-panel audit-panel">
        <div class="panel-title"><div><h2>审计日志</h2><p>成员、审核、发布、分享和批注操作均可追溯。</p></div></div>
        <div v-if="audit.length" class="audit-list">
          <article v-for="item in audit" :key="item.id"><span>{{ item.action }}</span><div><b>{{ item.actor_name }}</b><small>{{ item.resource_type }} · {{ new Date(item.created_at).toLocaleString() }}</small></div></article>
        </div>
        <div v-else class="settings-empty">还没有审计记录。</div>
      </section>
    </div>
  </div>
</template>
