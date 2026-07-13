import { Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined, SettingOutlined, BranchesOutlined,
  BellOutlined, RobotOutlined, FileTextOutlined, ApartmentOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'

const { Sider, Header, Content } = Layout

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '驾驶舱' },
  {
    key: 'config', icon: <SettingOutlined />, label: '配置管理',
    children: [
      { key: '/config/models', icon: <RobotOutlined />, label: 'AI 模型' },
      { key: '/config/agents', icon: <RobotOutlined />, label: 'Agent 管理' },
      { key: '/config/repositories', icon: <BranchesOutlined />, label: '代码仓库' },
      { key: '/config/notify', icon: <BellOutlined />, label: '通知配置' },
      { key: '/config/rules', icon: <ApartmentOutlined />, label: '流水线规则' },
    ],
  },
  { key: '/tasks', icon: <FileTextOutlined />, label: '任务日志' },
]

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  const getBreadcrumb = () => {
    if (location.pathname === '/dashboard') return '动态驾驶舱'
    if (location.pathname.startsWith('/config')) return '配置管理'
    return '任务日志'
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={224}
        style={{
          background: 'linear-gradient(180deg, #0f1222 0%, #161a2e 100%)',
          borderRight: '1px solid rgba(255,255,255,0.06)',
          boxShadow: '2px 0 24px rgba(0,0,0,0.15)',
        }}
      >
        <div
          style={{
            padding: '20px 24px 16px',
            borderBottom: '1px solid rgba(255,255,255,0.08)',
          }}
        >
          <Typography.Text
            strong
            style={{
              color: '#fff',
              fontSize: 17,
              letterSpacing: '-0.3px',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <span style={{ fontSize: 20 }}>⚡</span>
            AI DevOps
          </Typography.Text>
          <Typography.Text
            style={{
              color: 'rgba(255,255,255,0.35)',
              fontSize: 11,
              display: 'block',
              marginTop: 2,
              letterSpacing: '0.5px',
            }}
          >
            效能平台
          </Typography.Text>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          defaultOpenKeys={['config']}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{
            background: 'transparent',
            marginTop: 8,
            padding: '0 10px',
          }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 28px',
            borderBottom: '1px solid rgba(0,0,0,0.06)',
            display: 'flex',
            alignItems: 'center',
            height: 52,
            lineHeight: '52px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
            position: 'sticky',
            top: 0,
            zIndex: 10,
          }}
        >
          <Typography.Text
            style={{ fontSize: 13, color: '#888', fontWeight: 500, letterSpacing: '0.3px' }}
          >
            {getBreadcrumb()}
          </Typography.Text>
        </Header>
        <Content
          style={{
            margin: '20px',
            minHeight: 'calc(100vh - 92px)',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
