import { Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined, SettingOutlined, BranchesOutlined,
  BellOutlined, RobotOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'

const { Sider, Header, Content } = Layout

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '驾驶舱' },
  {
    key: 'config', icon: <SettingOutlined />, label: '配置管理',
    children: [
      { key: '/config/models', icon: <RobotOutlined />, label: 'AI 模型' },
      { key: '/config/repositories', icon: <BranchesOutlined />, label: '代码仓库' },
      { key: '/config/notify', icon: <BellOutlined />, label: '通知配置' },
    ],
  },
  { key: '/tasks', icon: <FileTextOutlined />, label: '任务日志' },
]

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={220} theme="dark">
        <div style={{ padding: '16px 24px', borderBottom: '1px solid #333' }}>
          <Typography.Text strong style={{ color: '#fff', fontSize: 16 }}>
            🤖 AI DevOps 平台
          </Typography.Text>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          defaultOpenKeys={['config']}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ marginTop: 8 }}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0' }}>
          <Typography.Text type="secondary">
            {location.pathname === '/dashboard' ? '动态驾驶舱' :
             location.pathname.startsWith('/config') ? '配置管理' : '任务日志'}
          </Typography.Text>
        </Header>
        <Content style={{ margin: '24px', background: '#f5f5f5', minHeight: 'calc(100vh - 112px)' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
