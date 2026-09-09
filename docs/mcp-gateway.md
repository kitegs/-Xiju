# MCP 工具网关（阶段 1）

Insight Studio 可将符合 **Streamable HTTP** 协议的 MCP 服务登记到当前工作区。服务地址、Bearer Token 和工具发现均在后端处理；浏览器不会取得令牌。

## 个人版使用

1. 使用 `start-professional.bat` 启动 Superset 与 MCP 服务。
2. 在“设置 → 集成 → AI 工具连接”保留默认地址 `http://localhost:5008/mcp`，点击“添加服务”。
3. 点击“发现工具”。Superset 的 `generate_chart`、`update_chart`、`generate_dashboard` 等工具会被缓存为可审计目录。
4. 在对话中提出具体需求。模型只能从已发现且启用的目录中选择 `mcp.call`。
5. 计划卡会将 MCP 调用标为外部操作；批准后才会发送，执行过程和结果会写入工具运行记录与审计日志。

## 安全边界

- 仅允许 HTTPS，或 `localhost` / `127.0.0.1` 的 HTTP 地址。
- MCP 服务配置仅限 Owner/Admin（`report.publish` 权限）修改。
- 所有 MCP 调用暂按高风险外部操作处理，即使“完全访问”模式也不会自动执行。
- 可在服务配置中维护工具允许清单；空清单表示使用已发现工具，但模型计划仍只能使用缓存目录。
- 当前仅实现 Streamable HTTP；stdio、旧 SSE transport 和 OAuth 交互授权属于下一阶段。

## Superset 本机接入

`scripts/run-superset.ps1` 会额外启动 `aibi-v2-superset-mcp` 容器，将 MCP 暴露为 `127.0.0.1:5008/mcp`。本机版本使用 `MCP_DEV_USERNAME=admin` 仅用于单机开发；公网部署必须改用 Superset 的 MCP Token/JWT 认证。
