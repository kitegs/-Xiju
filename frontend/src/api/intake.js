export function saveAnalysisBrief(request, projectId, payload) {
  return request(`/api/v1/projects/${projectId}/brief`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
