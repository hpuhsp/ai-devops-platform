import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Space, Popconfirm, message, Tag, Switch } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { listRepos, createRepo, updateRepo, deleteRepo, listModels } from '../../services/api'

const PLATFORMS = ['gitlab', 'github', 'gitea']

export default function RepositoriesPage() {
  const [repos, setRepos] = useState<any[]>([])
  const [models, setModels] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const load = () => Promise.all([listRepos().then(setRepos), listModels().then(setModels)])
  useEffect(() => { load() }, [])

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      if (editing) { await updateRepo(editing.id, values); message.success('更新成功') }
      else { await createRepo(values); message.success('添加成功') }
      setOpen(false); form.resetFields(); setEditing(null); load()
    } catch { message.error('操作失败') } finally { setLoading(false) }
  }

  const columns = [
    { title: '名称', dataIndex: 'name' },
    { title: '平台', dataIndex: 'platform', render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '仓库地址', dataIndex: 'repo_url', ellipsis: true },
    { title: 'AI 模型', dataIndex: 'ai_model_id', render: (v: number) => models.find(m => m.id === v)?.name || '默认' },
    { title: '状态', dataIndex: 'enabled', render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
    {
      title: '操作', render: (_: any, r: any) => (
        <Space>
          <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); setOpen(true) }}>编辑</Button>
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
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>
          添加仓库
        </Button>
      </div>
      <Table dataSource={repos} columns={columns} rowKey="id" size="small" />

      <Modal title={editing ? '编辑仓库' : '添加仓库'} open={open} onOk={handleSubmit} onCancel={() => setOpen(false)} confirmLoading={loading} width={600}>
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
          <Form.Item name="ai_model_id" label="AI 模型 (留空使用默认)">
            <Select allowClear options={models.map(m => ({ value: m.id, label: m.name }))} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
