import { Routes, Route, Navigate } from 'react-router-dom'
import MainLayout from './components/MainLayout'
import DashboardPage from './pages/dashboard/DashboardPage'
import ModelsPage from './pages/config/ModelsPage'
import RepositoriesPage from './pages/config/RepositoriesPage'
import NotifyPage from './pages/config/NotifyPage'
import TasksPage from './pages/logs/TasksPage'
import TaskDetailPage from './pages/logs/TaskDetailPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="config/models" element={<ModelsPage />} />
        <Route path="config/repositories" element={<RepositoriesPage />} />
        <Route path="config/notify" element={<NotifyPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="tasks/:taskId" element={<TaskDetailPage />} />
      </Route>
    </Routes>
  )
}
