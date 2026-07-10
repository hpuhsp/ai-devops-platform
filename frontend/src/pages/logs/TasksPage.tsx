import { useEffect, useState } from 'react'
import { Table, Tag, Button, Select, Space } from 'antd'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { listTasks } from '../../services/api'

const STATUS_COLOR: Record<string, string> = {
  created: 'default', analyzing: 'processing', generating: 'processing',
  executing: 'processing', repairing: 'warning',
  success: 'success', failed: 'error',
  pending: 'default', running: 'processing',
}

const STATUS_LABEL: Record<string, string> = {
  created: '已创建', analyzing: '分析中', generating: '生成中',
  executing: '执行中', repairing: '修复中',
  success: '成功', failed: '失败',
  pending: '已创建', running: '分析中',
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<any>({ items: [], total: 0 })
  const [filters, setFilters] = useState({ page: 1, page_size: 20, status: undefined, task_type: undefined })
  const navigate = useNavigate()

  useEffect(() => {
    listTasks(filters).then(setTasks).catch(console.error)
  }, [filters])

  const columns = [
    { title: 'Task ID', dataIndex: 'task_id', render: (v: string) => <code style={{ fontSize: 12 }}>{v.slice(0, 8)}...</code> },
    { title: '类型', dataIndex: 'task_type', render: (v: string) => <Tag>{v}</Tag> },
    { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v] || v}</Tag> },
    { title: 'Tokens', render: (_: any, r: any) => r.prompt_tokens + r.completion_tokens },
    { title: '耗时', dataIndex: 'duration_ms', render: (v: number) => v ? `${(v / 1000).toFixed(1)}s` : '-' },
    { title: '创建时间', dataIndex: 'created_at', render: (v: string) => dayjs(v).format('MM-DD HH:mm:ss') },
    { title: '操作', render: (_: any, r: any) => <Button size="small" onClick={() => navigate(`/tasks/${r.task_id}`)}>详情</Button> },
  ]

  return (
    <div style={{ background: '#fff', padding: 24, borderRadius: 8 }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Select
          allowClear placeholder="状态筛选" style={{ width: 140 }}
          options={[
            { value: 'created', label: '已创建' },
            { value: 'analyzing', label: '分析中' },
            { value: 'generating', label: '生成中' },
            { value: 'executing', label: '执行中' },
            { value: 'repairing', label: '修复中' },
            { value: 'success', label: '成功' },
            { value: 'failed', label: '失败' },
          ]}
          onChange={status => setFilters(f => ({ ...f, status, page: 1 }))}
        />
        <Select
          allowClear placeholder="类型筛选" style={{ width: 160 }}
          options={['code_review', 'test_generation', 'mr_review', 'auto_merge'].map(t => ({ value: t, label: t }))}
          onChange={task_type => setFilters(f => ({ ...f, task_type, page: 1 }))}
        />
      </div>
      <Table
        dataSource={tasks.items}
        columns={columns}
        rowKey="task_id"
        size="small"
        pagination={{ total: tasks.total, current: filters.page, pageSize: filters.page_size,
          onChange: (page) => setFilters(f => ({ ...f, page })) }}
      />
    </div>
  )
}
