import { Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import MainLayout from './components/MainLayout'
import DashboardPage from './pages/dashboard/DashboardPage'
import ModelsPage from './pages/config/ModelsPage'
import AgentsPage from './pages/config/AgentsPage'
import RepositoriesPage from './pages/config/RepositoriesPage'
import NotifyPage from './pages/config/NotifyPage'
import NotifyPoliciesPage from './pages/config/NotifyPoliciesPage'
import RulesPage from './pages/config/RulesPage'
import TasksPage from './pages/logs/TasksPage'
import TaskDetailPage from './pages/logs/TaskDetailPage'

const theme = {
  token: {
    colorPrimary: '#3b5ccc',
    colorSuccess: '#2da44e',
    colorWarning: '#d97706',
    colorError: '#cf222e',
    colorInfo: '#3b5ccc',
    colorBgBase: '#ffffff',
    colorTextBase: '#1a1a2e',
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    borderRadius: 6,
    borderRadiusLG: 10,
    borderRadiusSM: 4,
    wireframe: false,
    controlHeight: 36,
    lineHeight: 1.6,
    fontSize: 14,
  },
  components: {
    Layout: {
      bodyBg: '#f2f3f7',
      headerBg: '#ffffff',
      siderBg: '#0f1222',
    },
    Menu: {
      darkItemBg: '#0f1222',
      darkItemSelectedBg: 'rgba(59,92,204,0.18)',
      darkItemHoverBg: 'rgba(255,255,255,0.06)',
      itemBorderRadius: 6,
    },
    Card: {
      paddingLG: 20,
      borderRadiusLG: 10,
    },
    Table: {
      borderRadiusLG: 10,
      headerBg: '#f8f9fc',
    },
    Button: {
      borderRadius: 6,
      controlHeight: 36,
      fontWeight: 500,
    },
    Tag: {
      borderRadius: 4,
    },
    Modal: {
      borderRadiusLG: 12,
    },
  },
}

export default function App() {
  return (
    <ConfigProvider theme={theme}>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="config/models" element={<ModelsPage />} />
          <Route path="config/agents" element={<AgentsPage />} />
          <Route path="config/repositories" element={<RepositoriesPage />} />
          <Route path="config/notify" element={<NotifyPage />} />
          <Route path="config/notify-policies" element={<NotifyPoliciesPage />} />
          <Route path="config/rules" element={<RulesPage />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="tasks/:taskId" element={<TaskDetailPage />} />
        </Route>
      </Routes>
    </ConfigProvider>
  )
}
