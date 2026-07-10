import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, Switch, Space,
  Popconfirm, message, Tag, InputNumber, Divider, Typography,
} from 'antd'
import { PlusOutlined, CopyOutlined } from '@ant-design/icons'
import {
  listAgents, createAgent, updateAgent, deleteAgent, cloneAgent,
  listAgentSkills, listAgentStages, listModels,
} from '../../services/api'

const { TextArea } = Input
const { Text } = Typography

const STAGE_LABELS: Record<string, string> = {
  code_review: '代码审查',
  change_intelligence: '变更智能',
  generator: '测试生成',
  validate_repair: '验证修复',
  quality_scorer: '质量评分',
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<any[]>([])
  const [models, setModels] = useState<any[]>([])
  const [skills, setSkills] = useState<any[]>([])
  const [stages, setStages] = useState<any[]>([])
  const [stageFilter, setStageFilter] = useState<string | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const load = async () => {
    try {
      const [agentData, modelData, skillData, stageData] = await Promise.all([
        listAgents(stageFilter ? { stage_type: stageFilter } : undefined),
        listModels(),
        listAgentSkills(),
        listAgentStages(),
      ])
      setAgents(agentData)
      setModels(modelData)
      setSkills(skillData)
      setStages(stageData)
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => { load() }, [stageFilter])

  const getSkillsForStage = (stageType: string) => {
    if (!stageType) return skills
    return skills.filter((s: any) => s.stage_type === stageType)
  }

  const getModelName = (modelId: number | null) => {
    if (!modelId) return '使用默认'
    const m = models.find((m: any) => m.id === modelId)
    return m ? m.name : `#${modelId}`
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()

    // Parse JSON config fields
    const parseJson = (v: string | object | undefined, fallback: object = {}) => {
      if (!v || (typeof v === 'string' && !v.trim())) return fallback
      if (typeof v === 'object') return v
      try { return JSON.parse(v) } catch { return fallback }
    }

    const payload = {
      ...values,
      skill_config: parseJson(values.skill_config),
      model_config: parseJson(values.model_config),
      policy_config: parseJson(values.policy_config),
    }

    setLoading(true)
    try {
      if (editing) {
        await updateAgent(editing.id, payload)
        message.success('更新成功')
      } else {
        await createAgent(payload)
        message.success('创建成功')
      }
      setOpen(false)
      form.resetFields()
      setEditing(null)
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  const handleClone = async (id: number) => {
    try {
      await cloneAgent(id)
      message.success('克隆成功')
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '克隆失败')
    }
  }

  const columns = [
    {
      title: '名称', dataIndex: 'name', width: 180,
      render: (v: string, r: any) => (
        <Space>
          <span>{v}</span>
          {r.is_system && <Tag color="blue">系统</Tag>}
        </Space>
      ),
    },
    {
      title: '阶段类型', dataIndex: 'stage_type', width: 120,
      render: (v: string) => <Tag color="cyan">{STAGE_LABELS[v] || v}</Tag>,
    },
    { title: 'Skill', dataIndex: 'skill_name', width: 150 },
    {
      title: '绑定模型', dataIndex: 'model_id', width: 120,
      render: (v: number) => (
        <Tag color={v ? 'green' : 'default'}>{getModelName(v)}</Tag>
      ),
    },
    {
      title: '状态', dataIndex: 'enabled', width: 80,
      render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag>禁用</Tag>,
    },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '操作', width: 200,
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" onClick={() => {
            setEditing(record)
            form.setFieldsValue({
              ...record,
              skill_config: JSON.stringify(record.skill_config || {}, null, 2),
              model_config: JSON.stringify(record.model_config || {}, null, 2),
              policy_config: JSON.stringify(record.policy_config || {}, null, 2),
            })
            setOpen(true)
          }}>编辑</Button>
          <Button size="small" icon={<CopyOutlined />} onClick={() => handleClone(record.id)}>
            克隆
          </Button>
          {!record.is_system && (
            <Popconfirm title="确认删除？" onConfirm={() => deleteAgent(record.id).then(() => { message.success('删除成功'); load() })}>
              <Button size="small" danger>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ background: '#fff', padding: 24, borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <span style={{ fontSize: 16, fontWeight: 600 }}>Agent 管理</span>
          <Select
            allowClear
            placeholder="按阶段筛选"
            style={{ width: 150 }}
            value={stageFilter}
            onChange={(v) => setStageFilter(v)}
            options={stages.map((s: any) => ({ value: s.value, label: s.label }))}
          />
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          setEditing(null)
          form.resetFields()
          setOpen(true)
        }}>
          创建 Agent
        </Button>
      </div>

      <Table dataSource={agents} columns={columns} rowKey="id" size="small" scroll={{ x: 900 }} />

      <Modal
        title={editing ? '编辑 Agent' : '创建 Agent'}
        open={open}
        onOk={handleSubmit}
        onCancel={() => { setOpen(false); setEditing(null) }}
        confirmLoading={loading}
        width={680}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ skill_type: 'builtin', enabled: true }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如: 安全审查 Agent" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="Agent 用途说明" />
          </Form.Item>
          <Form.Item name="stage_type" label="阶段类型" rules={[{ required: true }]}>
            <Select
              placeholder="选择流水线阶段"
              options={stages.map((s: any) => ({ value: s.value, label: s.label }))}
              disabled={editing?.is_system}
            />
          </Form.Item>
          <Form.Item name="skill_name" label="Skill" rules={[{ required: true }]}>
            <Select
              placeholder="选择 Skill"
              options={(form.getFieldValue('stage_type') ? getSkillsForStage(form.getFieldValue('stage_type')) : skills).map((s: any) => ({
                value: s.name, label: `${s.name} — ${s.description || ''}`,
              }))}
              disabled={editing?.is_system}
            />
          </Form.Item>
          <Form.Item name="model_id" label="绑定模型">
            <Select
              allowClear
              placeholder="使用仓库默认模型"
              options={models.map((m: any) => ({
                value: m.id, label: `${m.name} (${m.provider})`,
              }))}
            />
          </Form.Item>

          <Divider orientation="left" plain><Text type="secondary">Skill 配置</Text></Divider>
          <Form.Item name="skill_config" label="Skill Config (JSON)">
            <TextArea rows={3} placeholder='{"max_diff_lines": 500, "prompt_override": "..."}' />
          </Form.Item>

          <Divider orientation="left" plain><Text type="secondary">模型配置</Text></Divider>
          <Form.Item name="model_config" label="Model Config (JSON)">
            <TextArea rows={3} placeholder='{"temperature": 0.3, "max_tokens": 4096}' />
          </Form.Item>

          <Divider orientation="left" plain><Text type="secondary">策略配置</Text></Divider>
          <Form.Item name="policy_config" label="Policy Config (JSON)">
            <TextArea rows={3} placeholder='{"max_retry": 3, "require_review": false, "allow_code_modify": true}' />
          </Form.Item>

          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
