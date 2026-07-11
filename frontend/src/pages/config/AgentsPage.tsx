import { useEffect, useState } from 'react'
import {
  Table, Button, Modal, Form, Input, Select, Switch, Space,
  Popconfirm, message, Tag, Divider, Typography, Tooltip,
} from 'antd'
import { PlusOutlined, CopyOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  listAgents, createAgent, updateAgent, deleteAgent, cloneAgent,
  listAgentSkills, listAgentStages, listModels, listAgentMcpTools, validateAgent,
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
  const [mcpTools, setMcpTools] = useState<any[]>([])
  const [stageFilter, setStageFilter] = useState<string | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const selectedStage = Form.useWatch('stage_type', form)

  const load = async () => {
    try {
      const [agentData, modelData, skillData, stageData, mcpData] = await Promise.all([
        listAgents(stageFilter ? { stage_type: stageFilter } : undefined),
        listModels(),
        listAgentSkills(),
        listAgentStages(),
        listAgentMcpTools(),
      ])
      setAgents(agentData)
      setModels(modelData)
      setSkills(skillData)
      setStages(stageData)
      setMcpTools(mcpData)
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

    const parseJson = (label: string, v: string | object | undefined, fallback: object | any[] = {}) => {
      if (!v || (typeof v === 'string' && !v.trim())) return fallback
      if (typeof v === 'object') return v
      try { return JSON.parse(v) } catch { throw new Error(`${label} JSON 格式不正确`) }
    }

    let payload: any
    try {
      payload = {
        ...values,
        model_id: values.model_id ?? null,
        skills: parseJson('Skills', values.skills, []),
        mcp_tools: parseJson('MCP Tools', values.mcp_tools, []),
        guardrails: parseJson('Guardrails', values.guardrails, {}),
        skill_config: parseJson('Skill Config', values.skill_config),
        model_config: parseJson('Model Config', values.model_config),
        policy_config: parseJson('Policy Config', values.policy_config),
      }
    } catch (e: any) {
      message.error(e.message || 'JSON 配置格式不正确')
      return
    }
    if ((!payload.skills || payload.skills.length === 0) && payload.skill_name) {
      payload.skills = [{ name: payload.skill_name, version: '1.0.0', config: {} }]
    }
    if (editing?.is_system) {
      payload.stage_type = editing.stage_type
      payload.skill_name = editing.skill_name
      payload.skills = editing.skills || [{ name: editing.skill_name, version: '1.0.0', config: {} }]
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

  const handleValidate = async (id: number) => {
    try {
      const result = await validateAgent(id)
      if (result.valid) {
        message.success(result.warnings?.length ? `验证通过，${result.warnings.length} 条提醒` : '验证通过')
      } else {
        message.error(result.errors?.join('；') || '验证失败')
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '验证失败')
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
    {
      title: 'Skill', dataIndex: 'skills', width: 180,
      render: (_: any, r: any) => (
        <Space size={4} wrap>
          {((r.skills?.length ? r.skills : [{ name: r.skill_name }]) || []).slice(0, 2).map((s: any) => (
            <Tag key={s.name || r.skill_name}>{s.name || r.skill_name}</Tag>
          ))}
          {r.skills?.length > 2 && <Tag>+{r.skills.length - 2}</Tag>}
        </Space>
      ),
    },
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
      title: '操作', width: 240,
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" onClick={() => {
            setEditing(record)
            form.setFieldsValue({
              ...record,
              skills: JSON.stringify(record.skills || [{ name: record.skill_name, version: '1.0.0', config: {} }], null, 2),
              mcp_tools: JSON.stringify(record.mcp_tools || [], null, 2),
              guardrails: JSON.stringify(record.guardrails || {}, null, 2),
              skill_config: JSON.stringify(record.skill_config || {}, null, 2),
              model_config: JSON.stringify(record.model_config || {}, null, 2),
              policy_config: JSON.stringify(record.policy_config || {}, null, 2),
            })
            setOpen(true)
          }}>编辑</Button>
          <Tooltip title="验证 Agent 配置">
            <Button size="small" icon={<SafetyCertificateOutlined />} onClick={() => handleValidate(record.id)} />
          </Tooltip>
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
          form.setFieldsValue({
            skill_type: 'builtin',
            enabled: true,
            skills: '[]',
            mcp_tools: '[]',
            guardrails: '{}',
            skill_config: '{}',
            model_config: '{}',
            policy_config: '{}',
          })
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
          <Form.Item name="stage_type" label="阶段类型" rules={[{ required: true }]}
            extra={editing?.is_system ? '系统 Agent 的阶段类型不可修改' : undefined}
          >
            <Select
              placeholder="选择流水线阶段"
              options={stages.map((s: any) => ({ value: s.value, label: s.label }))}
              disabled={editing?.is_system}
            />
          </Form.Item>
          <Form.Item name="skill_name" label="Skill" rules={[{ required: true }]}>
            <Select
              placeholder="选择 Skill"
              options={(selectedStage ? getSkillsForStage(selectedStage) : skills).map((s: any) => ({
                value: s.name, label: `${s.name} — ${s.description || ''}`,
              }))}
              disabled={editing?.is_system}
              onChange={(name) => {
                if (!editing?.is_system) {
                  form.setFieldValue('skills', JSON.stringify([{ name, version: '1.0.0', config: {} }], null, 2))
                }
              }}
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

          <Form.Item name="instructions" label="Instructions">
            <TextArea rows={3} placeholder="Agent 执行该阶段时使用的补充指令或 Prompt 约束" />
          </Form.Item>

          <Divider orientation="left" plain><Text type="secondary">Skills</Text></Divider>
          <Form.Item
            name="skills"
            label="Skills (JSON)"
            extra="系统 Agent 的核心 Skill 不可修改；自定义 Agent 可配置同阶段不同 Skill 实现。"
          >
            <TextArea rows={4} disabled={editing?.is_system} placeholder='[{"name":"test_generation","version":"1.0.0","config":{}}]' />
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

          <Divider orientation="left" plain><Text type="secondary">MCP / Guardrails</Text></Divider>
          <Form.Item
            name="mcp_tools"
            label="MCP Tools (JSON)"
            extra={mcpTools.length ? `当前预留 ${mcpTools.length} 个只读工具描述` : '当前阶段仅预留结构，不执行写操作工具'}
          >
            <TextArea rows={4} placeholder='[{"server":"codegraph","tools":["refs","impact"],"permission":"read"}]' />
          </Form.Item>
          <Form.Item name="guardrails" label="Guardrails (JSON)">
            <TextArea rows={4} placeholder='{"allowed_write_patterns":["tests/**"],"deny_shell":true,"max_tool_calls":20}' />
          </Form.Item>

          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
