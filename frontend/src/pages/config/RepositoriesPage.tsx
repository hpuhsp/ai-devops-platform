import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Space, Popconfirm, message, Tag, Switch, Divider, Typography, Checkbox } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { listRepos, createRepo, updateRepo, deleteRepo, listModels, listAgents, listNotify } from '../../services/api'

const { Text } = Typography

const PLATFORMS = ['gitlab', 'github', 'gitea']

const STAGE_OPTIONS = [
  { value: 'code_review', label: '代码审查' },
  { value: 'change_intelligence', label: '变更智能' },
  { value: 'generator', label: '测试生成' },
  { value: 'validate_repair', label: '验证修复' },
  { value: 'quality_scorer', label: '质量评分' },
]

const NOTIFY_EVENT_OPTIONS = [
  { value: 'code_review_result', label: '代码审查' },
  { value: 'test_generation_result', label: '单元测试' },
  { value: 'quality_score_result', label: '质量评分' },
]

const SEVERITY_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'low', label: 'Low 及以上' },
  { value: 'medium', label: 'Medium 及以上' },
  { value: 'high', label: 'High 及以上' },
  { value: 'critical', label: 'Critical' },
]

const DEFAULT_NOTIFICATION_SETTINGS = {
  enabled_events: ['code_review_result', 'test_generation_result', 'quality_score_result'],
  min_severity: 'all',
  blocked_only: false,
}

export default function RepositoriesPage() {
  const [repos, setRepos] = useState<any[]>([])
  const [models, setModels] = useState<any[]>([])
  const [agents, setAgents] = useState<any[]>([])
  const [notifyConfigs, setNotifyConfigs] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const load = () => Promise.all([
    listRepos().then(setRepos),
    listModels().then(setModels),
    listAgents().then(setAgents),
    listNotify().then(setNotifyConfigs),
  ])
  useEffect(() => { load() }, [])

  const handleSubmit = async () => {
    const values = await form.validateFields()
    const agentBindings: Record<string, number> = {}
    const rawBindings = values.agent_bindings || {}
    for (const [stage, agentId] of Object.entries(rawBindings)) {
      if (agentId) agentBindings[stage] = agentId as number
    }
    const payload = {
      ...values,
      skills_config: {
        ...(values.skills_config || {}),
        notifications: {
          ...DEFAULT_NOTIFICATION_SETTINGS,
          ...((values.skills_config || {}).notifications || {}),
        },
      },
      agent_bindings: agentBindings,
    }
    setLoading(true)
    try {
      if (editing) { await updateRepo(editing.id, payload); message.success('更新成功') }
      else { await createRepo(payload); message.success('添加成功') }
      setOpen(false); form.resetFields(); setEditing(null); load()
    } catch { message.error('操作失败') } finally { setLoading(false) }
  }

  const getAgentName = (agentId: number) => {
    const a = agents.find(a => a.id === agentId)
    return a ? a.name : `#${agentId}`
  }

  const getNotifyName = (id?: number) => {
    if (!id) return '默认渠道'
    return notifyConfigs.find(n => n.id === id)?.name || `#${id}`
  }

  const columns = [
    { title: '名称', dataIndex: 'name' },
    { title: '平台', dataIndex: 'platform', render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '仓库地址', dataIndex: 'repo_url', ellipsis: true },
    {
      title: 'Agent 绑定',
      render: (_: any, r: any) => {
        const bindings = r.agent_bindings || {}
        const count = Object.keys(bindings).length
        if (count === 0) return <Tag>默认</Tag>
        return (
          <Space direction="vertical" size={0}>
            {Object.entries(bindings).map(([stage, id]: [string, any]) => (
              <Tag key={stage} color="cyan" style={{ fontSize: 11 }}>
                {STAGE_OPTIONS.find(s => s.value === stage)?.label || stage}: {getAgentName(id)}
              </Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '通知策略',
      width: 190,
      render: (_: any, r: any) => {
        const cfg = r.skills_config?.notifications || {}
        const events = cfg.enabled_events || []
        return (
          <Space direction="vertical" size={0}>
            <Tag color={cfg.notify_config_id ? 'blue' : 'default'}>{getNotifyName(cfg.notify_config_id)}</Tag>
            {events.length > 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {events.map((e: string) => NOTIFY_EVENT_OPTIONS.find(opt => opt.value === e)?.label || e).join(' / ')}
              </Text>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>未单独配置</Text>
            )}
            {cfg.min_severity && cfg.min_severity !== 'all' && (
              <Tag color="orange" style={{ fontSize: 11 }}>审查: {cfg.min_severity}+</Tag>
            )}
          </Space>
        )
      },
    },
    { title: '状态', dataIndex: 'enabled', render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
    {
      title: '操作', render: (_: any, r: any) => (
        <Space>
          <Button size="small" onClick={() => {
            setEditing(r)
            form.setFieldsValue({
              ...r,
              agent_bindings: r.agent_bindings || {},
              skills_config: {
                ...(r.skills_config || {}),
                notifications: {
                  ...DEFAULT_NOTIFICATION_SETTINGS,
                  ...((r.skills_config || {}).notifications || {}),
                },
              },
            })
            setOpen(true)
          }}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => deleteRepo(r.id).then(load)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ background: '#fff', padding: 24, borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 16, fontWeight: 600 }}>代码仓库配置</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          setEditing(null)
          form.resetFields()
          form.setFieldsValue({
            enabled: true,
            skills_config: { notifications: DEFAULT_NOTIFICATION_SETTINGS },
          })
          setOpen(true)
        }}>
          添加仓库
        </Button>
      </div>
      <Table dataSource={repos} columns={columns} rowKey="id" size="small" scroll={{ x: 800 }} />

      <Modal title={editing ? '编辑仓库' : '添加仓库'} open={open} onOk={handleSubmit} onCancel={() => setOpen(false)} confirmLoading={loading} width={640}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="仓库名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
            <Select options={PLATFORMS.map(p => ({ value: p, label: p }))} />
          </Form.Item>
          <Form.Item name="repo_url" label="仓库地址 (HTTPS)" rules={[{ required: true }]}>
            <Input placeholder="https://gitlab.com/org/repo.git" />
          </Form.Item>
          <Form.Item name="git_token" label="Git Token (留空保持不变)">
            <Input.Password placeholder="glpat-xxxx" />
          </Form.Item>
          <Form.Item name="webhook_secret" label="Webhook Secret">
            <Input.Password />
          </Form.Item>

          <Divider style={{ margin: '12px 0' }}>Agent 绑定</Divider>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
            为不同流水线阶段绑定专属 Agent，Agent 可独立配置模型、Skill 和策略。
            留空则使用系统默认 Agent。在「Agent 管理」页面创建自定义 Agent。
          </Text>
          {STAGE_OPTIONS.map(stage => (
            <Form.Item
              key={stage.value}
              name={['agent_bindings', stage.value]}
              label={stage.label}
            >
              <Select
                allowClear
                placeholder="使用默认 Agent"
                options={agents
                  .filter(a => a.stage_type === stage.value)
                  .map(a => ({
                    value: a.id,
                    label: `${a.name}${a.model_id ? ` [${models.find(m => m.id === a.model_id)?.name || ''}]` : ''}`,
                  }))}
              />
            </Form.Item>
          ))}

          <Divider style={{ margin: '12px 0' }}>通知策略</Divider>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
            仓库未选择通知渠道时使用默认通知。普通结果建议写入 MR，群消息可按事件和严重等级过滤。
          </Text>
          <Form.Item name={['skills_config', 'notifications', 'notify_config_id']} label="通知渠道">
            <Select
              allowClear
              placeholder="使用默认通知渠道"
              options={notifyConfigs.map(n => ({
                value: n.id,
                label: `${n.name}${n.is_default ? '（默认）' : ''}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name={['skills_config', 'notifications', 'enabled_events']}
            label="发送事件"
            initialValue={DEFAULT_NOTIFICATION_SETTINGS.enabled_events}
          >
            <Checkbox.Group options={NOTIFY_EVENT_OPTIONS} />
          </Form.Item>
          <Form.Item
            name={['skills_config', 'notifications', 'min_severity']}
            label="代码审查通知等级"
            initialValue={DEFAULT_NOTIFICATION_SETTINGS.min_severity}
          >
            <Select options={SEVERITY_OPTIONS} />
          </Form.Item>
          <Form.Item
            name={['skills_config', 'notifications', 'blocked_only']}
            label="仅拦截时发送代码审查通知"
            valuePropName="checked"
            initialValue={DEFAULT_NOTIFICATION_SETTINGS.blocked_only}
          >
            <Switch />
          </Form.Item>

          <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
