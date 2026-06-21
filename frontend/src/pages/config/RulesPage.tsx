import { useEffect, useState } from 'react'
import {
  Card, Table, Button, Select, Space, Tag, Modal, Form, Input,
  Checkbox, InputNumber, message, Tooltip, Popconfirm, Typography,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EditOutlined,
  ArrowUpOutlined, ArrowDownOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Text } = Typography

const ALL_STAGES = ['code_review', 'test_generation', 'auto_merge', 'build', 'deploy']
const STAGE_COLOR: Record<string, string> = {
  code_review: 'blue', test_generation: 'green', auto_merge: 'purple',
  build: 'orange', deploy: 'red',
}
const STAGE_LABEL: Record<string, string> = {
  code_review: '代码审查', test_generation: '单元测试', auto_merge: '智能合并',
  build: 'CI构建(二期)', deploy: '自动发布(二期)',
}

interface Rule {
  id: number; repo_id: number; name: string; pattern: string
  stages: string[]; priority: number; enabled: boolean
}

const listRules   = (repoId: number) => api.get('/api/v1/rules', { params: { repo_id: repoId } }).then(r => r.data)
const createRule  = (data: any) => api.post('/api/v1/rules', data).then(r => r.data)
const updateRule  = (id: number, data: any) => api.put(`/api/v1/rules/${id}`, data).then(r => r.data)
const deleteRule  = (id: number) => api.delete(`/api/v1/rules/${id}`)
const listRepos   = () => api.get('/api/v1/repositories').then(r => r.data)
const listTemplates = () => api.get('/api/v1/rules/templates').then(r => r.data)
const applyTemplate = (key: string, repoId: number) =>
  api.post(`/api/v1/rules/templates/${key}/apply`, null, { params: { repo_id: repoId } }).then(r => r.data)
const batchPriority = (items: any[]) => api.post('/api/v1/rules/batch-priority', items).then(r => r.data)

export default function RulesPage() {
  const [repos, setRepos] = useState<any[]>([])
  const [repoId, setRepoId] = useState<number | null>(null)
  const [rules, setRules] = useState<Rule[]>([])
  const [templates, setTemplates] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<Rule | null>(null)
  const [form] = Form.useForm()

  useEffect(() => {
    listRepos().then(r => { setRepos(r); if (r.length) setRepoId(r[0].id) })
    listTemplates().then(setTemplates)
  }, [])

  useEffect(() => {
    if (!repoId) return
    setLoading(true)
    listRules(repoId).then(setRules).finally(() => setLoading(false))
  }, [repoId])

  const reload = () => repoId && listRules(repoId).then(setRules)

  const handleTemplate = async (key: string) => {
    if (!repoId) return
    await applyTemplate(key, repoId)
    message.success('模板已应用')
    reload()
  }

  const openAdd = () => {
    setEditingRule(null)
    form.resetFields()
    form.setFieldsValue({ repo_id: repoId, priority: 50, enabled: true, stages: ['code_review'] })
    setModalOpen(true)
  }

  const openEdit = (rule: Rule) => {
    setEditingRule(rule)
    form.setFieldsValue(rule)
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    if (editingRule) {
      await updateRule(editingRule.id, values)
      message.success('已更新')
    } else {
      await createRule({ ...values, repo_id: repoId })
      message.success('已创建')
    }
    setModalOpen(false)
    reload()
  }

  const move = async (index: number, dir: -1 | 1) => {
    const arr = [...rules]
    const target = index + dir
    if (target < 0 || target >= arr.length) return
    // swap priorities
    const ap = arr[index].priority, bp = arr[target].priority
    await batchPriority([
      { id: arr[index].id, priority: bp },
      { id: arr[target].id, priority: ap },
    ])
    reload()
  }

  const columns = [
    {
      title: '优先级',
      width: 90,
      render: (_: any, r: Rule, i: number) => (
        <Space size={2}>
          <Tag color="default">{r.priority}</Tag>
          <Button size="small" icon={<ArrowUpOutlined />}   onClick={() => move(i, -1)} />
          <Button size="small" icon={<ArrowDownOutlined />} onClick={() => move(i, 1)}  />
        </Space>
      ),
    },
    { title: '规则名称', dataIndex: 'name', width: 160 },
    {
      title: '分支匹配',
      dataIndex: 'pattern',
      width: 150,
      render: (v: string) => <code style={{ background: '#f5f5f5', padding: '1px 6px', borderRadius: 4 }}>{v}</code>,
    },
    {
      title: '执行阶段',
      dataIndex: 'stages',
      render: (stages: string[]) => (
        <>
          {stages.map(s => (
            <Tag key={s} color={STAGE_COLOR[s] || 'default'} style={{ marginBottom: 2 }}>
              {STAGE_LABEL[s] || s}
            </Tag>
          ))}
        </>
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 70,
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作',
      width: 100,
      render: (_: any, r: Rule) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title="确认删除？" onConfirm={() => deleteRule(r.id).then(reload)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* Repo selector + template apply */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text strong>仓库：</Text>
          <Select
            style={{ width: 240 }}
            value={repoId}
            options={repos.map(r => ({ value: r.id, label: r.name }))}
            onChange={setRepoId}
          />
          <Text strong style={{ marginLeft: 16 }}>快速套用模板：</Text>
          {templates.map(t => (
            <Tooltip key={t.key} title={t.description}>
              <Button
                icon={<ThunderboltOutlined />}
                onClick={() => handleTemplate(t.key)}
                size="small"
              >
                {t.label}
              </Button>
            </Tooltip>
          ))}
        </Space>
      </Card>

      {/* Rules table */}
      <Card
        title={`流水线分支规则（共 ${rules.length} 条，按优先级降序匹配首条）`}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>新增规则</Button>}
      >
        <Table
          dataSource={rules}
          columns={columns}
          rowKey="id"
          size="small"
          loading={loading}
          pagination={false}
        />
        {rules.length === 0 && !loading && (
          <div style={{ textAlign: 'center', padding: '24px 0', color: '#bbb' }}>
            暂无规则，点击「快速套用模板」可一键初始化 Git Flow 配置
          </div>
        )}
      </Card>

      {/* Add/Edit modal */}
      <Modal
        title={editingRule ? '编辑规则' : '新增规则'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        width={520}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="规则名称" rules={[{ required: true }]}>
            <Input placeholder="如：feature 分支审核+单测" />
          </Form.Item>
          <Form.Item
            name="pattern"
            label="分支匹配模式"
            rules={[{ required: true }]}
            extra="支持 fnmatch 通配符，如 feature/* 、hotfix/* 、develop、* (兜底)"
          >
            <Input placeholder="feature/*" />
          </Form.Item>
          <Form.Item name="stages" label="执行阶段" rules={[{ required: true }]}>
            <Checkbox.Group>
              <Space direction="vertical">
                {ALL_STAGES.map(s => (
                  <Checkbox key={s} value={s}>
                    <Tag color={STAGE_COLOR[s]}>{STAGE_LABEL[s] || s}</Tag>
                  </Checkbox>
                ))}
              </Space>
            </Checkbox.Group>
          </Form.Item>
          <Form.Item name="priority" label="优先级（数字越大越优先）" rules={[{ required: true }]}>
            <InputNumber min={1} max={999} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="enabled" valuePropName="checked">
            <Checkbox>启用此规则</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
