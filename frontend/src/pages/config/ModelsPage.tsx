import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Switch, Space, Popconfirm, message, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { listModels, createModel, updateModel, deleteModel } from '../../services/api'

const PROVIDERS = ['openai', 'deepseek', 'ollama', 'azure', 'custom']

export default function ModelsPage() {
  const [models, setModels] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const load = () => listModels().then(setModels).catch(console.error)
  useEffect(() => { load() }, [])

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      if (editing) {
        await updateModel(editing.id, values)
        message.success('更新成功')
      } else {
        await createModel(values)
        message.success('创建成功')
      }
      setOpen(false)
      form.resetFields()
      setEditing(null)
      load()
    } catch (e) {
      message.error('操作失败')
    } finally {
      setLoading(false)
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name' },
    { title: '供应商', dataIndex: 'provider', render: (v: string) => <Tag>{v}</Tag> },
    { title: '模型 ID', dataIndex: 'model_id' },
    { title: 'API Base', dataIndex: 'api_base', render: (v: string) => v || '-' },
    { title: '默认', dataIndex: 'is_default', render: (v: boolean) => v ? <Tag color="blue">默认</Tag> : '-' },
    {
      title: '操作',
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" onClick={() => { setEditing(record); form.setFieldsValue(record); setOpen(true) }}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={() => deleteModel(record.id).then(load)}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ background: '#fff', padding: 24, borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 16, fontWeight: 600 }}>AI 模型配置</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>
          添加模型
        </Button>
      </div>
      <Table dataSource={models} columns={columns} rowKey="id" size="small" />

      <Modal title={editing ? '编辑模型' : '添加模型'} open={open} onOk={handleSubmit} onCancel={() => setOpen(false)} confirmLoading={loading}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="如: Deepseek-V3" />
          </Form.Item>
          <Form.Item name="provider" label="供应商" rules={[{ required: true }]}>
            <Select options={PROVIDERS.map(p => ({ value: p, label: p }))} />
          </Form.Item>
          <Form.Item name="model_id" label="模型 ID" rules={[{ required: true }]}>
            <Input placeholder="如: deepseek-chat / gpt-4o-mini" />
          </Form.Item>
          <Form.Item name="api_base" label="API Base URL (可选)">
            <Input placeholder="如: https://api.deepseek.com/v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key (留空保持不变)">
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
