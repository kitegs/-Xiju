export function loadTokenUsage(request, workspaceId, range = '7d', groupBy = 'stage') {
  const query = new URLSearchParams({ workspace_id: workspaceId, range, group_by: groupBy })
  return request(`/api/v1/usage/tokens?${query}`)
}
