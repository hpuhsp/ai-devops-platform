import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Space, Popconfirm, message, Tag, Switch, Typography } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { listNotify, createNotify, deleteNotify, setDefaultNotify, listNotifyLogs } from '../../services/api'

const { Text } = Typography

export default function NotifyPage() {
  const [items, setItems] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [provider, setProvider] = useState('feishu_webhook')
  const [loading, setLoading] = useState(false)
  const [logs, setLogs] = useState<any[]>([])

  const load = () => listNotify().then(setItems).catch(console.error)
  const loadLogs = () => listNotifyLogs({ limit: 80 }).then(setLogs).catch(console.error)
  useEffect(() => { load(); loadLogs() }, [])

  const handleSubmit = async () => {
    const { name, provider: p, is_default, enabled, ...rest } = await form.validateFields()
    setLoading(true)
    try {
      await createNotify({ name, provider: p, config: rest, is_default, enabled })
      message.success('创建成功')
      setOpen(false)
      form.resetFields()
      load(); loadLogs()
    } catch {
      message.error('操作失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSetDefault = async (id: number) => {
    try {
      await setDefaultNotify(id)
      message.success('设置默认成功')
      load(); loadLogs()
    } catch {
      message.error('设置默认失败')
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteNotify(id)
      message.success('删除成功')
      load(); loadLogs()
    } catch {
      message.error('删除失败')
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name' },
    { title: '类型', dataIndex: 'provider', render: (v: string) => <Tag>{v}</Tag> },
    { title: '默认', dataIndex: 'is_default', render: (v: boolean) => v ? <Tag color="blue">默认</Tag> : '-' },
    { title: '状态', dataIndex: 'enabled', render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
    {
      title: '操作',
      render: (_: any, record: any) => (
        <Space size={6}>
          <Button size="small" disabled={record.is_default} onClick={() => handleSetDefault(record.id)}>
            设为默认
          </Button>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const logColumns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => v ? new Date(v).toLocaleString() : '-',
    },
    { title: '任务', dataIndex: 'task_id', width: 180, render: (v: string) => v || '-' },
    { title: '事件', dataIndex: 'event_type', width: 140, render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '目标',
      dataIndex: 'target',
      width: 180,
      render: (v: string) => <Text style={{ fontSize: 12 }}>{v || '-'}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const color = v === 'sent' ? 'green' : v === 'failed' ? 'red' : 'orange'
        const label = v === 'sent' ? '已发送' : v === 'failed' ? '失败' : '已跳过'
        return <Tag color={color}>{label}</Tag>
      },
    },
    {
      title: '原因 / 错误',
      render: (_: any, r: any) => (
        <Text type={r.error ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
          {r.error || r.reason || '-'}
        </Text>
      ),
    },
  ]

  return (
    <div style={{ background: '#fff', padding: 24, borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 16, fontWeight: 600 }}>通知配置</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setProvider('feishu_webhook'); setOpen(true) }}>
          添加通知
        </Button>
      </div>
      <Table dataSource={items} columns={columns} rowKey="id" size="small" />

      <div style={{ display: 'flex', justifyContent: 'space-between', margin: '24px 0 12px' }}>
        <span style={{ fontSize: 16, fontWeight: 600 }}>通知日志</span>
        <Button size="small" icon={<ReloadOutlined />} onClick={loadLogs}>刷新</Button>
      </div>
      <Table
        dataSource={logs}
        columns={logColumns}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 10 }}
        scroll={{ x: 900 }}
      />

      <Modal title="添加通知配置" open={open} onOk={handleSubmit} onCancel={() => setOpen(false)} confirmLoading={loading}>
        <Form form={form} layout="vertical" initialValues={{ provider: 'feishu_webhook', is_default: false, enabled: true }}>
          <Form.Item name="name" label="配置名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="provider" label="通知类型" rules={[{ required: true }]}>
            <Select onChange={setProvider} options={[
              { value: 'feishu_webhook', label: '飞书机器人 Webhook' },
              { value: 'feishu_app', label: '飞书企业应用 (Phase 2)' },
              { value: 'slack', label: 'Slack (Phase 2)' },
            ]} />
          </Form.Item>
          {provider === 'feishu_webhook' && (
            <>
              <Form.Item name="webhook_url" label="Webhook URL" rules={[{ required: true }]}>
                <Input placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
              </Form.Item>
              <Form.Item name="sign_key" label="签名密钥 (可选)">
                <Input.Password />
              </Form.Item>
            </>
          )}
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
