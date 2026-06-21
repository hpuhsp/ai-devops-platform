import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Card, Descriptions, Tag, Spin, Alert, Typography, Collapse, Badge,
  Row, Col, Statistic,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, ExperimentOutlined,
  MergeCellsOutlined, CodeOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { getTask } from '../../services/api'
import PipelineChain from '../../components/PipelineChain'

const { Text, Paragraph } = Typography

const STATUS_COLOR: Record<string, string> = {
  pending: 'default', running: 'processing', success: 'success', failed: 'error',
}

function CodeReviewPanel({ data }: { data: any }) {
  if (!data) return <Text type="secondary">暂无数据</Text>
  const findings = data.findings || []
  const SEV_COLOR: Record<string, string> = { critical: 'red', high: 'orange', medium: 'gold', low: 'blue' }
  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col><Statistic title="评分" value={data.score ?? '—'} suffix="/100" valueStyle={{ color: data.score >= 80 ? '#52c41a' : '#ff4d4f' }} /></Col>
        <Col><Statistic title="Critical" value={data.critical_count ?? 0} valueStyle={{ color: data.critical_count ? '#ff4d4f' : '#52c41a' }} /></Col>
        <Col><Statistic title="High" value={data.high_count ?? 0} valueStyle={{ color: data.high_count ? '#fa8c16' : '#52c41a' }} /></Col>
        <Col><Statistic title="问题总数" value={findings.length} /></Col>
      </Row>
      {findings.length > 0 && (
        <div>
          {findings.map((f: any, i: number) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
              <Tag color={SEV_COLOR[f.severity] || 'default'}>{(f.severity || 'LOW').toUpperCase()}</Tag>
              <code style={{ fontSize: 12 }}>{f.file}:{f.line}</code>
              <Text style={{ marginLeft: 8 }}>{f.message}</Text>
              {f.suggestion && <Paragraph type="secondary" style={{ margin: '4px 0 0 0', fontSize: 12 }}>{f.suggestion}</Paragraph>}
            </div>
          ))}
        </div>
      )}
      {findings.length === 0 && <Text type="success"><CheckCircleOutlined /> 无问题，代码质量良好</Text>}
    </div>
  )
}

function TestGenPanel({ data }: { data: any }) {
  if (!data) return <Text type="secondary">未启用或暂无数据</Text>
  const wr = data.worktree_run || {}
  const files = data.generated_files || []
  const passed = wr.status === 'passed'
  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col><Statistic title="框架" value={data.framework || '—'} /></Col>
        <Col><Statistic title="生成文件" value={files.length} /></Col>
        <Col><Statistic title="预估覆盖率提升" value={data.estimated_coverage_delta || '—'} /></Col>
        <Col>
          <Statistic
            title="pytest 结果"
            value={wr.status === 'passed' ? '全部通过' : wr.status === 'failed' ? '有用例失败' : wr.status || '未执行'}
            valueStyle={{ color: passed ? '#52c41a' : wr.status === 'failed' ? '#ff4d4f' : '#888', fontSize: 14 }}
          />
        </Col>
      </Row>
      {wr.stdout && (
        <Collapse size="small" items={[{
          key: '1',
          label: <span>{passed ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />} pytest 输出</span>,
          children: <pre style={{ fontSize: 11, background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 4, overflow: 'auto', maxHeight: 300 }}>{wr.stdout}</pre>,
        }]} />
      )}
      {files.length > 0 && (
        <Collapse size="small" style={{ marginTop: 8 }} items={files.map((f: any, i: number) => ({
          key: i,
          label: <span><CodeOutlined style={{ marginRight: 6 }} />{f.path}</span>,
          children: <pre style={{ fontSize: 11, background: '#f5f5f5', padding: 12, borderRadius: 4, overflow: 'auto', maxHeight: 300 }}>{f.content}</pre>,
        }))} />
      )}
    </div>
  )
}

function AutoMergePanel({ data }: { data: any }) {
  if (!data) return <Text type="secondary">本次未触发智能合并</Text>
  return (
    <div>
      <Tag color={data.success ? 'success' : 'error'}>{data.success ? '合并成功' : '合并失败'}</Tag>
      <Text style={{ marginLeft: 8 }}>{data.message}</Text>
      {data.merged_sha && <div style={{ marginTop: 8 }}><Text type="secondary">SHA: </Text><code>{data.merged_sha}</code></div>}
    </div>
  )
}

export default function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const [task, setTask] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!taskId) return
    getTask(taskId).then(setTask).catch(console.error).finally(() => setLoading(false))
  }, [taskId])

  // Poll while running
  useEffect(() => {
    if (!task || ['success', 'failed'].includes(task.status)) return
    const timer = setInterval(() => getTask(taskId!).then(setTask), 3000)
    return () => clearInterval(timer)
  }, [task, taskId])

  if (loading) return <Spin style={{ display: 'block', margin: '60px auto' }} />
  if (!task) return <Alert type="error" message="Task not found" />

  const od = task.output_data || {}

  return (
    <div style={{ maxWidth: 960 }}>
      {/* Header */}
      <Card style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="Task ID"><code style={{ fontSize: 12 }}>{task.task_id}</code></Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={STATUS_COLOR[task.status]}>{task.status}</Tag></Descriptions.Item>
          <Descriptions.Item label="仓库 ID">#{task.repo_id}</Descriptions.Item>
          <Descriptions.Item label="耗时">{task.duration_ms ? `${(task.duration_ms / 1000).toFixed(2)}s` : '运行中…'}</Descriptions.Item>
          <Descriptions.Item label="分支"><code>{task.branch || task.input_data?.branch || '—'}</code></Descriptions.Item>
          <Descriptions.Item label="提交"><code>{task.commit_sha || (task.input_data?.commit_sha || '').slice(0, 8) || '—'}</code></Descriptions.Item>
          <Descriptions.Item label="Token">prompt {task.prompt_tokens} / completion {task.completion_tokens}</Descriptions.Item>
          <Descriptions.Item label="触发时间">{dayjs(task.created_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
        </Descriptions>
      </Card>

      {task.error_message && (
        <Alert type="error" message="任务错误" description={task.error_message} style={{ marginBottom: 16 }} />
      )}

      {/* Pipeline chain overview */}
      <Card title="流水线进度" style={{ marginBottom: 16 }}>
        <PipelineChain
          taskId={['running', 'pending'].includes(task.status) ? task.task_id : undefined}
          pipeline={task.pipeline}
          taskStatus={task.status}
        />
      </Card>

      {/* Per-node detail panels */}
      <Collapse
        defaultActiveKey={['cr', 'tg']}
        items={[
          {
            key: 'cr',
            label: (
              <span>
                <CheckCircleOutlined style={{ marginRight: 8, color: '#1677ff' }} />
                代码审查详情
                {od.code_review?.score != null && (
                  <Tag color={od.code_review.score >= 80 ? 'success' : 'warning'} style={{ marginLeft: 8 }}>
                    {od.code_review.score}/100
                  </Tag>
                )}
              </span>
            ),
            children: <CodeReviewPanel data={od.code_review} />,
          },
          {
            key: 'tg',
            label: (
              <span>
                <ExperimentOutlined style={{ marginRight: 8, color: '#52c41a' }} />
                单元测试详情
                {od.test_generation?.worktree_run?.status && (
                  <Tag
                    color={od.test_generation.worktree_run.status === 'passed' ? 'success' : 'error'}
                    style={{ marginLeft: 8 }}
                  >
                    pytest {od.test_generation.worktree_run.status}
                  </Tag>
                )}
              </span>
            ),
            children: <TestGenPanel data={od.test_generation} />,
          },
          {
            key: 'am',
            label: (
              <span>
                <MergeCellsOutlined style={{ marginRight: 8, color: '#722ed1' }} />
                智能合并详情
                {!od.auto_merge && <Tag color="default" style={{ marginLeft: 8 }}>未触发</Tag>}
              </span>
            ),
            children: <AutoMergePanel data={od.auto_merge} />,
          },
        ]}
      />
    </div>
  )
}
