import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30000,
})

// ── Stats ──────────────────────────────────────────────────────────────
export const getOverview = () => api.get('/api/v1/stats/overview').then(r => r.data)
export const getTrends = (days = 7) => api.get('/api/v1/stats/trends', { params: { days } }).then(r => r.data)

// ── Models ─────────────────────────────────────────────────────────────
export const listModels = () => api.get('/api/v1/models').then(r => r.data)
export const listModelPresets = () => api.get('/api/v1/models/presets').then(r => r.data)
export const createModel = (data: any) => api.post('/api/v1/models', data).then(r => r.data)
export const updateModel = (id: number, data: any) => api.put(`/api/v1/models/${id}`, data).then(r => r.data)
export const deleteModel = (id: number) => api.delete(`/api/v1/models/${id}`)
export const validateModel = (data: any) => api.post('/api/v1/models/validate', data).then(r => r.data)
export const validateSavedModel = (id: number) => api.post(`/api/v1/models/${id}/validate`).then(r => r.data)
export const discoverModels = (data: any) => api.post('/api/v1/models/discover', data).then(r => r.data)

// ── Repositories ───────────────────────────────────────────────────────
export const listRepos = () => api.get('/api/v1/repositories').then(r => r.data)
export const createRepo = (data: any) => api.post('/api/v1/repositories', data).then(r => r.data)
export const updateRepo = (id: number, data: any) => api.put(`/api/v1/repositories/${id}`, data).then(r => r.data)
export const deleteRepo = (id: number) => api.delete(`/api/v1/repositories/${id}`)

// ── Agents ─────────────────────────────────────────────────────────────
export const listAgents = (params?: any) => api.get('/api/v1/agents', { params }).then(r => r.data)
export const createAgent = (data: any) => api.post('/api/v1/agents', data).then(r => r.data)
export const getAgent = (id: number) => api.get(`/api/v1/agents/${id}`).then(r => r.data)
export const updateAgent = (id: number, data: any) => api.put(`/api/v1/agents/${id}`, data).then(r => r.data)
export const deleteAgent = (id: number) => api.delete(`/api/v1/agents/${id}`)
export const cloneAgent = (id: number) => api.post(`/api/v1/agents/${id}/clone`).then(r => r.data)
export const listAgentSkills = () => api.get('/api/v1/agents/skills').then(r => r.data)
export const listAgentStages = () => api.get('/api/v1/agents/stages').then(r => r.data)
export const validateAgent = (id: number) => api.post(`/api/v1/agents/${id}/validate`).then(r => r.data)

// ── Notify Configs ─────────────────────────────────────────────────────
export const listNotify = () => api.get('/api/v1/notify-configs').then(r => r.data)
export const createNotify = (data: any) => api.post('/api/v1/notify-configs', data).then(r => r.data)
export const updateNotify = (id: number, data: any) => api.put(`/api/v1/notify-configs/${id}`, data).then(r => r.data)
export const setDefaultNotify = (id: number) => api.post(`/api/v1/notify-configs/${id}/default`).then(r => r.data)
export const deleteNotify = (id: number) => api.delete(`/api/v1/notify-configs/${id}`)
export const listNotifyLogs = (params?: any) => api.get('/api/v1/notify-logs', { params }).then(r => r.data)

// ── Tasks ──────────────────────────────────────────────────────────────
export const listTasks = (params?: any) => api.get('/api/v1/tasks', { params }).then(r => r.data)
export const getTask = (taskId: string) => api.get(`/api/v1/tasks/${taskId}`).then(r => r.data)
export const getTaskStages = (taskId: string) => api.get(`/api/v1/tasks/${taskId}/stages`).then(r => r.data)
export const getTaskArtifacts = (taskId: string) => api.get(`/api/v1/tasks/${taskId}/artifacts`).then(r => r.data)
export const getTaskEvents = (taskId: string) => api.get(`/api/v1/tasks/${taskId}/events`).then(r => r.data)

// ── Unit test workflow ─────────────────────────────────────────────────
export const triggerUnitTest = (data: any) => api.post('/api/v1/unit-test/trigger', data).then(r => r.data)

// ── Push event pipeline list ───────────────────────────────────────────
export const listEvents = (params?: any) => api.get('/api/v1/tasks/events', { params }).then(r => r.data)

/** Subscribe to live pipeline updates via SSE. Returns an EventSource. */
export const streamEvent = (taskId: string): EventSource =>
  new EventSource(`/api/v1/tasks/events/${taskId}/stream`)

export default api
