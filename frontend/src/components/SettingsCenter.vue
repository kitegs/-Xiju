<script setup>
import { reactive, ref } from 'vue'
import TokenCenter from './TokenCenter.vue'

defineProps({
  workspace: { type: Object, default: null },
  providers: { type: Array, default: () => [] },
  appSettings: { type: Object, default: null },
  providerKeys: { type: Object, required: true },
  providerStatus: { type: Object, required: true },
  integrations: { type: Object, default: null },
  toolPolicy: { type: Object, default: null },
  mcpServers: { type: Array, default: () => [] },
  request: { type: Function, required: true },
})

const emit = defineEmits(['save-provider', 'test-provider', 'save-general', 'refresh-integrations', 'create-mcp', 'update-mcp', 'discover-mcp'])

const settingsTab = ref('models')
const showIntegrationHelp = ref(false)
const mcpDraft = reactive({ name: '本机 Superset MCP', url: 'http://localhost:5008/mcp', bearer_token: '' })

function addMcpServer() {
  if (!mcpDraft.name.trim() || !mcpDraft.url.trim()) return
  emit('create-mcp', { name: mcpDraft.name.trim(), url: mcpDraft.url.trim(), bearer_token: mcpDraft.bearer_token.trim() || null, transport: 'streamable_http', enabled: true, tool_allowlist: [] })
  mcpDraft.bearer_token = ''
}

const tabs = [
  { id: 'models', icon: '✦', label: '模型与 API', description: 'OpenAI 与 DeepSeek' },
  { id: 'general', icon: '⌁', label: '常规', description: '外观、保存与导出' },
  { id: 'tokens', icon: '◎', label: 'Token 中心', description: '阶段与模型用量' },
  { id: 'privacy', icon: '▣', label: '数据与隐私', description: '外发与执行边界' },
  { id: 'integrations', icon: '◇', label: '集成', description: 'Cube 与 Superset' },
]

function chooseDefault(target, providers) {
  if (!target.is_default) return
  providers.forEach(provider => { provider.is_default = provider.provider === target.provider })
}
</script>

<template>
  <header class="simple-header settings-header">
    <div>
      <span>SETTINGS</span>
      <h1>设置</h1>
      <p>配置模型、使用偏好、隐私边界与团队集成。修改仅作用于当前工作区。</p>
    </div>
    <div class="settings-workspace-chip">
      <small>当前工作区</small>
      <b>{{ workspace?.name || '正在载入…' }}</b>
    </div>
  </header>

  <div class="settings-layout">
    <aside class="settings-nav" aria-label="设置分类">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="{ active: settingsTab === tab.id }"
        :aria-current="settingsTab === tab.id ? 'page' : undefined"
        @click="settingsTab = tab.id"
      >
        <span>{{ tab.icon }}</span>
        <div><b>{{ tab.label }}</b><small>{{ tab.description }}</small></div>
        <i>›</i>
      </button>
    </aside>

    <section class="settings-content">
      <div v-if="settingsTab === 'models'" class="settings-section">
        <div class="settings-section-title">
          <div><h2>模型与 API</h2><p>接入对话推理服务；数据计算和证据生成仍由本地确定性工具完成。</p></div>
          <span class="status-pill">{{ providers.filter(item => item.enabled).length }} 个已启用</span>
        </div>
        <div class="privacy-notice"><b>密钥保护</b><span>API Key 只提交给本地后端并加密保存，前端不会读回明文。测试连接会向所选服务发起一次请求。</span></div>
        <div class="provider-grid">
          <article v-for="provider in providers" :key="provider.provider" class="provider-card">
            <header>
              <div :class="['provider-logo', provider.provider]">{{ provider.provider === 'openai' ? 'O' : 'D' }}</div>
              <div><h3>{{ provider.provider === 'openai' ? 'OpenAI' : 'DeepSeek' }}</h3><span>{{ provider.has_api_key ? `已保存 ${provider.masked_api_key}` : '尚未配置密钥' }}</span></div>
              <label class="switch" :title="provider.enabled ? '已启用' : '未启用'"><input v-model="provider.enabled" type="checkbox"><i /></label>
            </header>
            <label>API 地址<input v-model.trim="provider.base_url" spellcheck="false"></label>
            <label>模型<input v-model.trim="provider.model" spellcheck="false"><small>{{ provider.provider === 'openai' ? '填写账号可用的 OpenAI 模型 ID' : '填写 DeepSeek 控制台支持的模型 ID' }}</small></label>
            <label>API Key<input v-model="providerKeys[provider.provider]" type="password" autocomplete="new-password" :placeholder="provider.has_api_key ? '留空则保留当前密钥' : '输入 API Key'"></label>
            <label v-if="provider.provider === 'openai'">推理强度<select v-model="provider.options.reasoning_effort"><option value="low">Low · 更快</option><option value="medium">Medium · 平衡</option><option value="high">High · 更深入</option></select></label>
            <label class="default-check"><input v-model="provider.is_default" type="checkbox" @change="chooseDefault(provider, providers)"> 设为默认模型</label>
            <div class="provider-actions"><button class="outline-btn" @click="emit('test-provider', provider)">测试连接</button><button class="primary" @click="emit('save-provider', provider)">保存设置</button></div>
            <p v-if="providerStatus[provider.provider]" class="provider-status" role="status">{{ providerStatus[provider.provider] }}</p>
          </article>
        </div>
        <div v-if="!providers.length" class="settings-empty">模型配置正在载入。如果长时间没有显示，请确认 API 服务运行在 8010 端口。</div>
      </div>

      <div v-else-if="settingsTab === 'general'" class="settings-section">
        <div class="settings-section-title"><div><h2>常规</h2><p>调整界面、草稿保存和默认导出行为。</p></div></div>
        <template v-if="appSettings">
          <div class="setting-row"><div><b>界面语言</b><p>用于菜单、提示和默认报告语言。</p></div><select v-model="appSettings.language"><option value="zh-CN">简体中文</option><option value="en-US">English</option></select></div>
          <div class="setting-row"><div><b>外观主题</b><p>深色主题会立即应用；系统模式跟随操作系统。</p></div><select v-model="appSettings.theme"><option value="light">浅色</option><option value="dark">深色</option><option value="system">跟随系统</option></select></div>
          <div class="setting-row"><div><b>自动保存报告</b><p>编辑过程中定期保存草稿。</p></div><label class="switch"><input v-model="appSettings.autosave" type="checkbox"><i /></label></div>
          <div class="setting-row" :class="{ muted: !appSettings.autosave }"><div><b>自动保存间隔</b><p>频繁保存更安全，也会增加本地写入。</p></div><select v-model.number="appSettings.autosave_interval_seconds" :disabled="!appSettings.autosave"><option :value="15">15 秒</option><option :value="30">30 秒</option><option :value="60">1 分钟</option><option :value="120">2 分钟</option></select></div>
          <div class="setting-row"><div><b>默认导出格式</b><p>尚未实现的格式会明确提示，不会生成伪文件。</p></div><select v-model="appSettings.default_export"><option value="pdf">PDF</option><option value="docx">Word DOCX</option><option value="pptx">PowerPoint</option></select></div>
          <div class="setting-row"><div><b>新对话默认澄清方式</b><p>只影响之后创建的对话；当前对话可在输入框左侧单独调整。</p></div><select v-model="appSettings.default_clarification_mode"><option value="auto">自动检查</option><option value="always">每次检查</option><option value="off">关闭</option></select></div>
          <div class="settings-footer"><span>设置保存在本地工作区，刷新后仍然有效。</span><button class="primary" @click="emit('save-general')">保存常规设置</button></div>
        </template>
      </div>

      <div v-else-if="settingsTab === 'tokens'" class="settings-section">
        <TokenCenter :workspace="workspace" :request="request" />
      </div>

      <div v-else-if="settingsTab === 'privacy'" class="settings-section">
        <div class="settings-section-title"><div><h2>数据与隐私</h2><p>明确哪些操作留在本机，哪些操作可能访问外部模型。</p></div></div>
        <template v-if="appSettings">
          <div class="privacy-policy-card"><span>当前策略</span><h3>本地计算优先</h3><p>上传文件、字段画像、聚合计算和图表证据均在本机处理。仅在启用模型并主动发送消息后，才向对应服务发送问题和最小必要的数据摘要。</p></div>
          <div class="setting-row"><div><b>安全模式</b><p>禁止在宿主机直接执行模型生成的代码。此基线不可在界面关闭。</p></div><label class="switch"><input v-model="appSettings.safe_mode" type="checkbox" disabled><i /></label></div>
          <div class="privacy-policy-card"><span>对话权限选择</span><h3>在输入框左侧即时设置</h3><p>安全模式只直接运行画像、质量与固定统计，SQL 需批准，Python、MCP 和发布被禁止；部分允许直接运行只读 SQL，沙箱 Python、数据副本修改与 MCP 需批准；副本完全访问开放受控副本工具，但 MCP 仍受白名单限制，Superset 始终单独批准。任何模式都不修改原始文件。</p></div>
          <div class="setting-row"><div><b>外部请求前提示</b><p>每次向模型服务发送数据摘要前显示服务来源。</p></div><label class="switch"><input v-model="appSettings.confirm_external_requests" type="checkbox"><i /></label></div>
          <div class="setting-row"><div><b>匿名遥测</b><p>本地版默认关闭；当前实现不会上传使用统计。</p></div><label class="switch"><input v-model="appSettings.telemetry" type="checkbox"><i /></label></div>
          <div class="data-boundary-list"><b>默认不会发送</b><span>原始文件</span><span>完整数据表</span><span>API Key</span><span>本机路径</span></div>
          <div class="settings-footer"><span>团队版将增加按数据源审批、脱敏策略和管理员审计。</span><button class="primary" @click="emit('save-general')">保存隐私设置</button></div>
        </template>
      </div>

      <div v-else-if="settingsTab === 'team'" class="settings-section">
        <div class="settings-section-title"><div><h2>团队</h2><p>阶段 4 已启用成员角色、审核发布、批注分享与审计基础能力。</p></div><span class="status-pill">已启用</span></div>
        <div class="team-summary"><div class="team-avatar">{{ workspace?.name?.slice(0, 1) || 'I' }}</div><div><small>工作区</small><h3>{{ workspace?.name || '我的分析工作区' }}</h3><p>本地单用户 · 数据和密钥保存在当前计算机</p></div></div>
        <div class="readiness-list">
          <div><span class="done">✓</span><div><b>本地工作区与持久化</b><p>数据集、会话、报告和偏好已按工作区保存。</p></div><em>可用</em></div>
          <div><span class="done">✓</span><div><b>成员与角色权限</b><p>Owner / Admin / Analyst / Viewer，敏感团队 API 由后端校验。</p></div><em>可用</em></div>
          <div><span class="done">✓</span><div><b>评论、审核与发布</b><p>版本历史、对象批注、审核状态和限时只读分享。</p></div><em>可用</em></div>
          <div><span class="done">✓</span><div><b>操作审计</b><p>成员、批注、审核、发布与分享操作可查询。</p></div><em>可用</em></div>
        </div>
        <div class="settings-callout"><b>部署边界</b><p>本机版使用受信任的本地所有者身份，团队入口适合局域网试运行。公网部署前仍需接入企业身份提供方、HTTPS、PostgreSQL、Alembic、备份与密钥管理。</p></div>
      </div>

      <div v-else class="settings-section">
        <div class="settings-section-title"><div><h2>集成</h2><p>Cube 负责正式指标语义，Superset 负责专业仪表盘编辑；两者均为可选外部服务。</p></div><button class="outline-btn" @click="emit('refresh-integrations')">刷新状态</button></div>
        <div class="integration-cards">
          <article><div class="integration-logo cube">C</div><div><h3>Cube 语义层</h3><p>指标、维度、权限、缓存和预聚合。</p><code>{{ integrations?.cube?.url || '尚未配置 AIBI_CUBE_API_URL' }}</code></div><span :class="['integration-state', { on: integrations?.cube?.reachable }]">{{ integrations?.cube?.reachable ? '在线' : integrations?.cube?.configured ? '不可达' : '未配置' }}</span></article>
          <article><div class="integration-logo superset">S</div><div><h3>Apache Superset</h3><p>专业图表、仪表盘、筛选和嵌入式分析。</p><code>{{ integrations?.superset?.url || '运行 start-professional.bat' }}</code></div><span :class="['integration-state', { on: integrations?.superset?.reachable }]">{{ integrations?.superset?.reachable ? '在线' : integrations?.superset?.configured ? '不可达' : '未配置' }}</span></article>
          <article><div class="integration-logo sandbox">▣</div><div><h3>隔离代码沙箱</h3><p>只在确定性工具不能覆盖的高级分析中按策略启用。</p><code>网络默认拒绝 · 数据只读挂载 · 超时与资源限制</code></div><span :class="['integration-state', { on: toolPolicy?.tiers?.find(item => item.id === 'sandbox')?.available }]">{{ toolPolicy?.tiers?.find(item => item.id === 'sandbox')?.available ? '可用' : '默认关闭' }}</span></article>
        </div>
        <section class="mcp-gateway">
          <header><div><span>MCP TOOL GATEWAY</span><h3>AI 工具连接</h3><p>登记 Streamable HTTP MCP 服务。令牌只保存于本机后端；发现工具后，AI 才能在计划中调用。</p></div></header>
          <div class="mcp-add"><label>名称<input v-model.trim="mcpDraft.name" placeholder="例如：Superset MCP"></label><label>服务地址<input v-model.trim="mcpDraft.url" placeholder="http://localhost:5008/mcp"></label><label>Bearer Token（可选）<input v-model="mcpDraft.bearer_token" type="password" autocomplete="new-password" placeholder="只提交到后端保存"></label><button class="primary" @click="addMcpServer">添加服务</button></div>
          <div v-if="mcpServers.length" class="mcp-server-list"><article v-for="server in mcpServers" :key="server.id"><div><b>{{ server.name }}</b><code>{{ server.url }}</code><small>{{ server.tool_cache?.tools?.length || 0 }} 个已发现工具{{ server.last_checked_at ? ` · ${new Date(server.last_checked_at).toLocaleString()}` : '' }}</small></div><label class="switch" title="启用后工具会提供给 AI 计划"><input v-model="server.enabled" type="checkbox" @change="emit('update-mcp', server)"><i /></label><button class="outline-btn" @click="emit('discover-mcp', server)">发现工具</button></article></div>
          <p v-else class="mcp-empty">还没有 MCP 服务。Superset MCP 启动后可先添加 <code>http://localhost:5008/mcp</code>。</p>
          <small class="mcp-safety">所有 MCP 调用默认属于外部操作：会展示在 AI 计划、需要批准、记录参数与结果。当前支持 Streamable HTTP；stdio/SSE 适配器将在下一阶段加入。</small>
        </section>
        <button class="help-toggle" :aria-expanded="showIntegrationHelp" @click="showIntegrationHelp = !showIntegrationHelp">{{ showIntegrationHelp ? '收起配置说明' : '查看配置说明' }} <span>{{ showIntegrationHelp ? '⌃' : '⌄' }}</span></button>
        <div v-if="showIntegrationHelp" class="integration-help">
          <p>在 <code>backend/.env</code> 中配置服务地址后重启 API：</p>
          <pre>AIBI_CUBE_API_URL=http://localhost:4000/cubejs-api/v1
AIBI_SUPERSET_URL=http://localhost:8088
AIBI_SANDBOX_ENABLED=false</pre>
          <p>Superset 已支持实时健康检查、Embedded Dashboard 初始化和服务端 Guest Token。Cube 仍需在阶段 5 完成 Meta 同步、短期令牌、指标目录与一致性测试。</p>
        </div>
      </div>
    </section>
  </div>
</template>
