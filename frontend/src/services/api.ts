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
export const createModel = (data: any) => api.post('/api/v1/models', data).then(r => r.data)
export const updateModel = (id: number, data: any) => api.put(`/api/v1/models/${id}`, data).then(r => r.data)
export const deleteModel = (id: number) => api.delete(`/api/v1/models/${id}`)

// ── Repositories ───────────────────────────────────────────────────────
export const listRepos = () => api.get('/api/v1/repositories').then(r => r.data)
export const createRepo = (data: any) => api.post('/api/v1/repositories', data).then(r => r.data)
export const updateRepo = (id: number, data: any) => api.put(`/api/v1/repositories/${id}`, data).then(r => r.data)
export const deleteRepo = (id: number) => api.delete(`/api/v1/repositories/${id}`)

// ── Notify Configs ─────────────────────────────────────────────────────
export const listNotify = () => api.get('/api/v1/notify-configs').then(r => r.data)
export const createNotify = (data: any) => api.post('/api/v1/notify-configs', data).then(r => r.data)
export const deleteNotify = (id: number) => api.delete(`/api/v1/notify-configs/${id}`)

// ── Tasks ──────────────────────────────────────────────────────────────
export const listTasks = (params?: any) => api.get('/api/v1/tasks', { params }).then(r => r.data)
export const getTask = (taskId: string) => api.get(`/api/v1/tasks/${taskId}`).then(r => r.data)

// ── Push event pipeline list ───────────────────────────────────────────
export const listEvents = (params?: any) => api.get('/api/v1/tasks/events', { params }).then(r => r.data)

/** Subscribe to live pipeline updates via SSE. Returns an EventSource. */
export const streamEvent = (taskId: string): EventSource =>
  new EventSource(`/api/v1/tasks/events/${taskId}/stream`)

export default api
