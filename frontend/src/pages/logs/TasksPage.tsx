import { useEffect, useState } from 'react'
import { Table, Tag, Button, Select, Space } from 'antd'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { listTasks } from '../../services/api'

const STATUS_COLOR: Record<string, string> = {
  pending: 'default', running: 'processing', success: 'success', failed: 'error',
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
    { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={STATUS_COLOR[v]}>{v}</Tag> },
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
          options={['pending', 'running', 'success', 'failed'].map(s => ({ value: s, label: s }))}
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
