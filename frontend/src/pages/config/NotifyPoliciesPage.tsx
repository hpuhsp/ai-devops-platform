import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, Switch, Space,
  Popconfirm, message, Tag, InputNumber, Divider, Typography, Checkbox,
} from 'antd'
import { PlusOutlined, SendOutlined } from '@ant-design/icons'
import { listNotify, listRepos } from '../../services/api'
import api from '../../services/api'

const { Text } = Typography

const EVENT_OPTIONS = [
  { value: 'code_review_result', label: '代码审查结果' },
  { value: 'test_generation_result', label: '单元测试结果' },
  { value: 'quality_score_result', label: '质量评分结果' },
  { value: 'pipeline_failed', label: '流水线失败' },
  { value: 'pipeline_success', label: '流水线成功' },
  { value: 'mr_comment_posted', label: 'MR 评论已发布' },
]

const STAGE_OPTIONS = [
  { value: 'code_review', label: '代码审查' },
  { value: 'test_generation', label: '单元测试' },
  { value: 'auto_merge', label: '智能合并' },
  { value: 'quality_scorer', label: '质量评分' },
]

const STATUS_OPTIONS = [
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'blocked', label: '已拦截' },
]

const SEVERITY_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
]

const listPolicies = () => api.get('/api/v1/notification-policies').then(r => r.data)
const createPolicy = (data: any) => api.post('/api/v1/notification-policies', data).then(r => r.data)
const updatePolicy = (id: number, data: any) => api.put(`/api/v1/notification-policies/${id}`, data).then(r => r.data)
const deletePolicy = (id: number) => api.delete(`/api/v1/notification-policies/${id}`)
const testPolicy = (id: number) => api.post(`/api/v1/notification-policies/${id}/test`).then(r => r.data)

export default function NotifyPoliciesPage() {
  const [policies, setPolicies] = useState<any[]>([])
  const [repos, setRepos] = useState<any[]>([])
  const [notifyConfigs, setNotifyConfigs] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const load = () => Promise.all([
    listPolicies().then(setPolicies),
    listRepos().then(setRepos),
    listNotify().then(setNotifyConfigs),
  ])

  useEffect(() => { load() }, [])

  const getRepoName = (ids: number[]) => {
    if (!ids || ids.length === 0) return '全部仓库'
    return ids.map(id => repos.find(r => r.id === id)?.name || `#${id}`).join(', ')
  }

  const getNotifyName = (id?: number) => {
    if (!id) return '—'
    return notifyConfigs.find(n => n.id === id)?.name || `#${id}`
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      if (editing) {
        await updatePolicy(editing.id, values)
        message.success('更新成功')
      } else {
        await createPolicy(values)
        message.success('创建成功')
      }
      setOpen(false); form.resetFields(); setEditing(null); load()
    } catch { message.error('操作失败') } finally { setLoading(false) }
  }

  const handleTest = async (id: number) => {
    try {
      await testPolicy(id)
      message.success('测试发送成功')
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '测试发送失败')
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', width: 180 },
    {
      title: '仓库', dataIndex: 'repo_ids', width: 150,
      render: (v: number[]) => <Text style={{ fontSize: 12 }}>{getRepoName(v)}</Text>,
    },
    {
      title: '事件类型', dataIndex: 'event_types', width: 180,
      render: (v: string[]) => (
        <Space size={2} wrap>
          {(v || []).slice(0, 2).map(e => (
            <Tag key={e} color="blue" style={{ fontSize: 11 }}>{EVENT_OPTIONS.find(o => o.value === e)?.label || e}</Tag>
          ))}
          {v && v.length > 2 && <Tag style={{ fontSize: 11 }}>+{v.length - 2}</Tag>}
          {(!v || v.length === 0) && <Tag>全部</Tag>}
        </Space>
      ),
    },
    {
      title: '条件', width: 150,
      render: (_: any, r: any) => (
        <Space size={2} wrap>
          {r.min_severity !== 'all' && <Tag color="orange">{r.min_severity}+</Tag>}
          {r.blocked_only && <Tag color="red">仅拦截</Tag>}
          {(r.status_filter || []).map((s: string) => <Tag key={s}>{STATUS_OPTIONS.find(o => o.value === s)?.label || s}</Tag>)}
        </Space>
      ),
    },
    {
      title: '通知渠道', dataIndex: 'notify_config_id', width: 120,
      render: (v: number) => <Tag color={v ? 'green' : 'default'}>{getNotifyName(v)}</Tag>,
    },
    {
      title: '优先级', dataIndex: 'priority', width: 80,
      sorter: (a: any, b: any) => a.priority - b.priority,
    },
    {
      title: '状态', dataIndex: 'enabled', width: 70,
      render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作', width: 180,
      render: (_: any, r: any) => (
        <Space>
          <Button size="small" onClick={() => {
            setEditing(r); form.setFieldsValue(r); setOpen(true)
          }}>编辑</Button>
          <Button size="small" icon={<SendOutlined />} onClick={() => handleTest(r.id)}>测试</Button>
          <Popconfirm title="确认删除？" onConfirm={() => deletePolicy(r.id).then(load)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ background: '#fff', padding: 24, borderRadius: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 16, fontWeight: 600 }}>通知策略</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          setEditing(null); form.resetFields(); form.setFieldsValue({ enabled: true, priority: 50, min_severity: 'all', repo_ids: [], event_types: [], stage_types: [], status_filter: [], targets: [] }); setOpen(true)
        }}>
          创建策略
        </Button>
      </div>

      <Table dataSource={policies} columns={columns} rowKey="id" size="small" scroll={{ x: 1000 }} />

      <Modal
        title={editing ? '编辑策略' : '创建策略'}
        open={open}
        onOk={handleSubmit}
        onCancel={() => setOpen(false)}
        confirmLoading={loading}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="策略名称" rules={[{ required: true }]}>
            <Input placeholder="如: 高危审查通知" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>

          <Divider style={{ margin: '8px 0' }}>匹配条件</Divider>

          <Form.Item name="repo_ids" label="仓库（空=全部）">
            <Select mode="multiple" allowClear placeholder="全部仓库"
              options={repos.map(r => ({ value: r.id, label: r.name }))} />
          </Form.Item>
          <Form.Item name="event_types" label="事件类型（空=全部）">
            <Select mode="multiple" allowClear placeholder="全部事件" options={EVENT_OPTIONS} />
          </Form.Item>
          <Form.Item name="stage_types" label="流水线阶段（空=全部）">
            <Select mode="multiple" allowClear placeholder="全部阶段" options={STAGE_OPTIONS} />
          </Form.Item>

          <Space size={12} style={{ width: '100%' }}>
            <Form.Item name="min_severity" label="最低严重度" style={{ flex: 1 }}>
              <Select options={SEVERITY_OPTIONS} />
            </Form.Item>
            <Form.Item name="status_filter" label="状态过滤" style={{ flex: 1 }}>
              <Select mode="multiple" allowClear placeholder="全部状态" options={STATUS_OPTIONS} />
            </Form.Item>
          </Space>

          <Form.Item name="blocked_only" label="仅拦截时发送" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Divider style={{ margin: '8px 0' }}>发送配置</Divider>

          <Form.Item name="notify_config_id" label="通知渠道" rules={[{ required: true, message: '请选择通知渠道' }]}>
            <Select placeholder="选择通知渠道"
              options={notifyConfigs.map(n => ({ value: n.id, label: n.name }))} />
          </Form.Item>

          <Space>
            <Form.Item name="priority" label="优先级">
              <InputNumber min={1} max={999} />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}
