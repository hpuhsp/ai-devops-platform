import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card, Descriptions, Tag, Typography, Spin, Alert } from 'antd'
import dayjs from 'dayjs'
import { getTask } from '../../services/api'

const STATUS_COLOR: Record<string, string> = {
  pending: 'default', running: 'processing', success: 'success', failed: 'error',
}

export default function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const [task, setTask] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!taskId) return
    getTask(taskId).then(setTask).catch(console.error).finally(() => setLoading(false))
  }, [taskId])

  if (loading) return <Spin style={{ display: 'block', margin: '60px auto' }} />
  if (!task) return <Alert type="error" message="Task not found" />

  return (
    <div style={{ maxWidth: 900 }}>
      <Card title={`任务详情 — ${task.task_type}`} style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="Task ID"><code>{task.task_id}</code></Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={STATUS_COLOR[task.status]}>{task.status}</Tag></Descriptions.Item>
          <Descriptions.Item label="类型"><Tag>{task.task_type}</Tag></Descriptions.Item>
          <Descriptions.Item label="耗时">{task.duration_ms ? `${(task.duration_ms / 1000).toFixed(2)}s` : '-'}</Descriptions.Item>
          <Descriptions.Item label="Tokens">
            prompt: {task.prompt_tokens} / completion: {task.completion_tokens}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{dayjs(task.created_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
        </Descriptions>
      </Card>

      {task.error_message && (
        <Alert type="error" message="错误信息" description={task.error_message} style={{ marginBottom: 16 }} />
      )}

      {task.output_data && (
        <Card title="输出结果" size="small">
          <Typography.Text type="secondary">{task.output_data?.summary}</Typography.Text>
          <pre style={{ marginTop: 12, fontSize: 12, background: '#f5f5f5', padding: 12, borderRadius: 4, overflow: 'auto' }}>
            {JSON.stringify(task.output_data, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  )
}
