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

const TEMPLATE_META: Record<string, {
  tone: 'default' | 'primary'
  summary: string
  fit: string
  preview: string[]
}> = {
  gitflow: {
    tone: 'default',
    summary: '按 Git Flow 分支分层执行审核、单测和合并。',
    fit: '适合 feature / release / hotfix 分支管理明确的团队。',
    preview: ['feature/*: 审核+单测', 'release/develop/main: 审核+单测+合并', '*: 仅审核兜底'],
  },
  trunk: {
    tone: 'default',
    summary: '主干和 feature 分支执行审核+单测，其它分支仅审查。',
    fit: '适合小步快跑、主干集成的项目。',
    preview: ['main: 审核+单测', 'feature/*: 审核+单测', '*: 仅审核兜底'],
  },
  github_flow: {
    tone: 'default',
    summary: '围绕 main 主干和短生命周期分支进行 PR 校验。',
    fit: '适合持续交付、Web/SaaS、小团队快速迭代。',
    preview: ['main/master: 审核+单测+合并', 'feature/*/bugfix/*/hotfix/*: 审核+单测', '*: 仅审核兜底'],
  },
  gitlab_flow: {
    tone: 'default',
    summary: '按 main、staging、production 环境分支逐级增强校验。',
    fit: '适合有预发/生产环境发布链路的团队。',
    preview: ['feature/*: 审核+单测', 'main/master: 审核+单测', 'staging/production: 审核+单测+合并'],
  },
}

export default function RulesPage() {
  const [repos, setRepos] = useState<any[]>([])
  const [repoId, setRepoId] = useState<number | null>(null)
  const [rules, setRules] = useState<Rule[]>([])
  const [templates, setTemplates] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<Rule | null>(null)
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string>()
  const [form] = Form.useForm()

  useEffect(() => {
    listRepos().then(r => { setRepos(r); if (r.length) setRepoId(r[0].id) })
    listTemplates().then(t => {
      setTemplates(t)
      if (t.length) setSelectedTemplateKey(t[0].key)
    })
  }, [])

  useEffect(() => {
    if (!repoId) return
    setLoading(true)
    listRules(repoId).then(setRules).finally(() => setLoading(false))
  }, [repoId])

  const reload = () => { if (repoId) listRules(repoId).then(setRules) }

  const selectedTemplateMeta = selectedTemplateKey ? TEMPLATE_META[selectedTemplateKey] : undefined

  const repoOptions = repos.map(r => ({
    value: r.id,
    label: (
      <Space size={6}>
        <Tag color="blue" style={{ marginInlineEnd: 0 }}>{r.platform}</Tag>
        <span>{r.name}</span>
      </Space>
    ),
  }))

  const handleTemplate = async (key: string) => {
    if (!repoId) return
    const tpl = templates.find(t => t.key === key)
    const meta = TEMPLATE_META[key]
    Modal.confirm({
      title: `套用「${tpl?.label || key}」模板？`,
      content: (
        <div>
          <p style={{ marginBottom: 8 }}>
            此操作会替换当前仓库已有的全部流水线规则。
          </p>
          {meta && (
            <div style={{ color: '#595959' }}>
              <div>{meta.summary}</div>
              <ul style={{ margin: '8px 0 0 18px', padding: 0 }}>
                {meta.preview.map(item => <li key={item}>{item}</li>)}
              </ul>
            </div>
          )}
        </div>
      ),
      okText: '确认套用',
      cancelText: '取消',
      async onOk() {
        await applyTemplate(key, repoId)
        message.success('模板已应用')
        reload()
      },
    })
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
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Space wrap>
            <Text strong>仓库：</Text>
            <Select
              style={{ width: 260 }}
              value={repoId}
              options={repoOptions}
              onChange={setRepoId}
            />
          </Space>

          <div
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 6,
              padding: '10px 12px',
              background: '#fff',
            }}
          >
            <Space wrap size={[12, 8]} style={{ width: '100%' }}>
              <ThunderboltOutlined style={{ color: '#1677ff' }} />
              <Text strong>快速套用模板</Text>
              <Select
                style={{ width: 220 }}
                value={selectedTemplateKey}
                options={templates.map(t => ({ value: t.key, label: t.label }))}
                onChange={setSelectedTemplateKey}
              />
              <Space wrap size={[4, 4]} style={{ flex: 1 }}>
                {(selectedTemplateMeta?.preview || []).map(item => <Tag key={item}>{item}</Tag>)}
              </Space>
              <Tooltip title="套用后会替换当前仓库全部规则">
                <Button
                  icon={<ThunderboltOutlined />}
                  onClick={() => selectedTemplateKey && handleTemplate(selectedTemplateKey)}
                  disabled={!selectedTemplateKey}
                >
                  套用
                </Button>
              </Tooltip>
            </Space>
          </div>
        </Space>
      </Card>

      {/* Rules table */}
      <Card
        title={`流水线分支规则（共 ${rules.length} 条，按优先级降序匹配首条）`}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>新增规则</Button>}
      >
        <div style={{
          background: '#f0f5ff', border: '1px solid #d6e4ff',
          borderRadius: 6, padding: '10px 14px', marginBottom: 14,
          fontSize: 12, color: '#666', lineHeight: 1.7,
        }}>
          流水线规则是控制<strong>各分支执行哪些阶段</strong>的唯一入口。下方勾选的阶段对应后端
          <strong>Agent</strong> 自动执行——你不需要手动绑定 Agent，只需在规则中按需勾选。
          「单元测试」在内部会自动展开为变更分析、上下文构建、测试生成、验证修复和质量评分等多个 Agent 链路。
        </div>
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
            暂无规则。可套用分支策略模板；仅审查项目可新增一条 * 规则并只选择「代码审查」。
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
