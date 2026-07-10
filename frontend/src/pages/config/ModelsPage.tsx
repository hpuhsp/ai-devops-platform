import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Switch, Space, Popconfirm, message, Tag, InputNumber, Divider, Tooltip, Alert } from 'antd'
import { PlusOutlined, ExperimentOutlined, EditOutlined, DeleteOutlined, SearchOutlined } from '@ant-design/icons'
import { listModels, listModelPresets, createModel, updateModel, deleteModel, validateModel, validateSavedModel, discoverModels } from '../../services/api'

const PROVIDERS = ['openai', 'deepseek', 'ollama', 'azure', 'custom']

export default function ModelsPage() {
  const [models, setModels] = useState<any[]>([])
  const [presets, setPresets] = useState<Record<string, any>>({})
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const selectedModelIds = Form.useWatch('model_ids', form) || []
  const [loading, setLoading] = useState(false)
  const [provider, setProvider] = useState<string>('openai')
  const [testing, setTesting] = useState(false)
  const [testingModelId, setTestingModelId] = useState<number | null>(null)
  const [discovering, setDiscovering] = useState(false)
  const [discoveredModels, setDiscoveredModels] = useState<any[]>([])
  const [discoverResult, setDiscoverResult] = useState<any>(null)

  const load = () => listModels().then(setModels).catch(console.error)
  useEffect(() => {
    load()
    listModelPresets().then(setPresets).catch(console.error)
  }, [])

  const resetDiscovery = () => {
    setDiscoveredModels([])
    setDiscoverResult(null)
  }

  const applyProviderDefaults = (nextProvider: string) => {
    setProvider(nextProvider)
    resetDiscovery()
    const preset = presets[nextProvider]
    form.setFieldsValue({
      provider: nextProvider,
      api_base: preset?.api_base || undefined,
      model_id: undefined,
      model_ids: [],
      default_model_id: undefined,
    })
  }

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    resetDiscovery()
    const defaultProvider = 'openai'
    setProvider(defaultProvider)
    const preset = presets[defaultProvider]
    form.setFieldsValue({
      provider: defaultProvider,
      api_base: preset?.api_base,
      model_ids: [],
      default_model_id: undefined,
      is_default: false,
      config: { temperature: 0.3, max_tokens: 4096 },
    })
    setOpen(true)
  }

  const openEdit = (record: any) => {
    setEditing(record)
    setProvider(record.provider)
    resetDiscovery()
    form.setFieldsValue({
      ...record,
      config: {
        temperature: record.config?.temperature ?? 0.3,
        max_tokens: record.config?.max_tokens ?? 4096,
      },
    })
    setOpen(true)
  }

  const buildModelName = (prefix: string | undefined, modelId: string, total: number) => {
    const trimmed = prefix?.trim()
    if (!trimmed) return modelId
    return total > 1 ? `${trimmed} - ${modelId}` : trimmed
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      if (editing) {
        await updateModel(editing.id, values)
        message.success('更新成功')
      } else {
        const modelIds: string[] = values.model_ids || []
        const defaultModelId = values.default_model_id
        for (const modelId of modelIds) {
          await createModel({
            name: buildModelName(values.name, modelId, modelIds.length),
            provider: values.provider,
            model_id: modelId,
            api_base: values.api_base,
            api_key: values.api_key,
            is_default: defaultModelId === modelId,
            config: values.config || {},
          })
        }
        message.success(`已创建 ${modelIds.length} 个模型配置`)
      }
      setOpen(false)
      form.resetFields()
      setEditing(null)
      resetDiscovery()
      load()
    } catch (e) {
      message.error('操作失败')
    } finally {
      setLoading(false)
    }
  }

  const handleDiscover = async () => {
    const values = await form.validateFields(['provider', 'api_base'])
    setDiscovering(true)
    try {
      const result = await discoverModels({
        provider: values.provider,
        api_base: values.api_base,
        api_key: form.getFieldValue('api_key'),
      })
      setDiscoverResult(result)
      if (result.success && result.models?.length) {
        setDiscoveredModels(result.models)
        if (result.source === 'remote') {
          message.success(`已获取 ${result.models.length} 个模型`)
        } else {
          message.warning('远端查询失败，已使用本地兜底模型列表')
        }
      } else {
        setDiscoveredModels([])
        Modal.error({
          title: '获取模型列表失败',
          content: result.error || '该服务未返回模型列表，可手动输入模型 ID。',
          width: 640,
        })
      }
    } catch (e: any) {
      setDiscoveredModels([])
      Modal.error({
        title: '获取模型列表失败',
        content: e?.response?.data?.detail || e?.message || '请求失败，可手动输入模型 ID。',
        width: 640,
      })
    } finally {
      setDiscovering(false)
    }
  }

  const handleValidate = async () => {
    const values = await form.validateFields()
    const modelId = editing ? values.model_id : (values.default_model_id || values.model_ids?.[0])
    if (!modelId) {
      message.warning('请先选择或输入模型 ID')
      return
    }
    setTesting(true)
    try {
      const result = await validateModel({ ...values, model_id: modelId })
      if (result.success) {
        message.success(`验证通过：${result.model || modelId}`)
      } else {
        Modal.error({
          title: '验证失败',
          content: result.error || '模型连接失败',
          width: 640,
        })
      }
    } catch (e: any) {
      Modal.error({
        title: '验证请求失败',
        content: e?.response?.data?.detail || e?.message || '请求失败',
      })
    } finally {
      setTesting(false)
    }
  }

  const handleValidateSaved = async (record: any) => {
    setTestingModelId(record.id)
    try {
      const result = await validateSavedModel(record.id)
      if (result.success) {
        message.success(`验证通过：${result.model || record.model_id}`)
      } else {
        Modal.error({
          title: `验证失败：${record.name}`,
          content: result.error || '模型连接失败',
          width: 640,
        })
      }
    } catch (e: any) {
      Modal.error({
        title: `验证请求失败：${record.name}`,
        content: e?.response?.data?.detail || e?.message || '请求失败',
      })
    } finally {
      setTestingModelId(null)
    }
  }

  const candidateModels = discoveredModels.length
    ? discoveredModels
    : editing
      ? (presets[provider]?.models || [])
      : []

  const modelOptions = candidateModels.map((m: any) => ({
    value: m.id,
    label: m.label && m.label !== m.id ? `${m.label} (${m.id})` : m.id,
  }))

  const selectedModelOptions = selectedModelIds.map((id: string) => ({ value: id, label: id }))

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
          <Tooltip title="测试连接">
            <Button
              size="small"
              icon={<ExperimentOutlined />}
              loading={testingModelId === record.id}
              onClick={() => handleValidateSaved(record)}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Popconfirm title="确认删除？" onConfirm={() => deleteModel(record.id).then(load)}>
            <Tooltip title="删除">
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ background: '#fff', padding: 24, borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontSize: 16, fontWeight: 600 }}>AI 模型配置</span>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          添加模型
        </Button>
      </div>
      <Table dataSource={models} columns={columns} rowKey="id" size="small" />

      <Modal
        title={editing ? '编辑模型' : '添加模型'}
        open={open}
        onOk={handleSubmit}
        onCancel={() => setOpen(false)}
        confirmLoading={loading}
        width={720}
        footer={[
          <Button key="test" icon={<ExperimentOutlined />} loading={testing} onClick={handleValidate}>
            验证连接
          </Button>,
          <Button key="cancel" onClick={() => setOpen(false)}>取消</Button>,
          <Button key="submit" type="primary" loading={loading} onClick={handleSubmit}>保存</Button>,
        ]}
      >
        <Form
          form={form}
          layout="vertical"
          onValuesChange={(changedValues, allValues) => {
            if ('model_ids' in changedValues) {
              const ids = allValues.model_ids || []
              if (!ids.includes(allValues.default_model_id)) {
                form.setFieldValue('default_model_id', ids[0])
              }
            }
          }}
        >
          <Form.Item
            name="name"
            label={editing ? '显示名称' : '名称前缀（可选）'}
            rules={editing ? [{ required: true, message: '请输入显示名称' }] : []}
          >
            <Input placeholder={editing ? '如 DeepSeek V4 Pro' : '留空时自动使用模型 ID'} />
          </Form.Item>
          <Form.Item name="provider" label="供应商" rules={[{ required: true }]}>
            <Select
              options={PROVIDERS.map(p => ({ value: p, label: presets[p]?.label || p }))}
              onChange={applyProviderDefaults}
            />
          </Form.Item>
          <Form.Item
            name="api_base"
            label="API Base URL"
            rules={[{ required: true, message: '请输入 API Base URL' }]}
            extra="选择供应商后会自动填入推荐地址，可按实际网关或私有部署地址修改。"
          >
            <Input placeholder="如 https://api.deepseek.com/v1 或 http://localhost:8000/v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key（编辑时留空保持不变）">
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          {!editing && (
            <Space direction="vertical" style={{ width: '100%', marginBottom: 16 }}>
              <Button icon={<SearchOutlined />} loading={discovering} onClick={handleDiscover}>
                获取模型列表
              </Button>
              {discoverResult?.source === 'remote' && (
                <Alert type="success" showIcon message={`已从远端获取 ${discoveredModels.length} 个模型`} />
              )}
              {discoverResult?.source === 'fallback' && (
                <Alert
                  type="warning"
                  showIcon
                  message="远端查询失败，当前显示本地兜底模型列表；也可以手动输入模型 ID。"
                />
              )}
            </Space>
          )}
          {editing ? (
            <Form.Item name="model_id" label="模型 ID" rules={[{ required: true, message: '请选择或输入模型 ID' }]}>
              <Input placeholder="输入模型 ID" />
            </Form.Item>
          ) : (
            <>
              <Form.Item
                name="model_ids"
                label="模型 ID（可多选）"
                rules={[{ required: true, message: '请选择或输入至少一个模型 ID' }]}
                extra="点击获取模型列表后选择；如果服务不支持列表接口，可直接输入模型 ID 后回车。"
              >
                <Select
                  mode="tags"
                  showSearch
                  options={modelOptions}
                  optionFilterProp="label"
                  placeholder="先获取模型列表，或手动输入模型 ID"
                />
              </Form.Item>
              <Form.Item
                name="default_model_id"
                label="默认模型"
                rules={[{ required: true, message: '请选择默认模型' }]}
              >
                <Select options={selectedModelOptions} placeholder="从已选模型中选择默认模型" />
              </Form.Item>
            </>
          )}
          <Divider style={{ margin: '12px 0' }}>调用参数</Divider>
          <Space size={12} style={{ width: '100%' }}>
            <Form.Item name={['config', 'temperature']} label="Temperature" style={{ flex: 1 }}>
              <InputNumber min={0} max={2} step={0.1} style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name={['config', 'max_tokens']} label="Max Tokens" style={{ flex: 1 }}>
              <InputNumber min={128} max={32000} step={128} style={{ width: 160 }} />
            </Form.Item>
          </Space>
          {editing && (
            <Form.Item name="is_default" label="设为默认" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  )
}
