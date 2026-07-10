import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Card, Descriptions, Tag, Spin, Alert, Typography, Collapse, Badge,
  Row, Col, Statistic, Progress, Divider,
} from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, ExperimentOutlined,
  MergeCellsOutlined, CodeOutlined, BulbOutlined, TrophyOutlined,
  WarningOutlined, FileTextOutlined, BugOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { getTask } from '../../services/api'
import PipelineChain from '../../components/PipelineChain'

const { Text, Paragraph } = Typography

// Sprint D: 7-state status + legacy compatibility
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

const ACTIVE_STATUS = ['created', 'analyzing', 'generating', 'executing', 'repairing', 'pending', 'running']

// Sprint B: Risk level colors
const RISK_COLOR: Record<string, string> = {
  high: 'red', medium: 'orange', low: 'green', none: 'default',
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

// Sprint B: Change Intelligence panel
function ChangeIntelligencePanel({ data }: { data: any }) {
  if (!data) return <Text type="secondary">未启用或暂无数据</Text>
  if (!data.need_test) return <Text type="secondary"><CheckCircleOutlined /> 变更分析：无需生成测试</Text>
  const targets = data.targets || []
  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col>
          <Statistic
            title="风险等级"
            valueRender={() => <Tag color={RISK_COLOR[data.risk_level] || 'default'} style={{ fontSize: 14 }}>{(data.risk_level || 'none').toUpperCase()}</Tag>}
          />
        </Col>
        <Col><Statistic title="影响文件数" value={data.impact_radius ?? 0} /></Col>
        <Col><Statistic title="测试目标" value={targets.length} /></Col>
      </Row>
      {targets.length > 0 && (
        <div>
          <Text strong>测试目标文件：</Text>
          <div style={{ marginTop: 8 }}>
            {targets.map((t: any, i: number) => (
              <Tag key={i} color="blue" style={{ marginBottom: 4 }}>
                <code style={{ fontSize: 11 }}>{typeof t === 'string' ? t : t.path || t.file || JSON.stringify(t)}</code>
              </Tag>
            ))}
          </div>
        </div>
      )}
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
        <Col>
          <Statistic
            title="实测覆盖率"
            value={wr.measured_coverage_delta || '—'}
            valueStyle={{ color: wr.measured_coverage_delta ? '#52c41a' : '#888', fontSize: 14 }}
          />
        </Col>
        <Col><Statistic title="LLM 预估" value={data.estimated_coverage_delta || '—'} /></Col>
        <Col>
          <Statistic
            title="pytest 结果"
            value={wr.status === 'passed' ? '全部通过' : wr.status === 'failed' ? '有用例失败' : wr.status || '未执行'}
            valueStyle={{ color: passed ? '#52c41a' : wr.status === 'failed' ? '#ff4d4f' : '#888', fontSize: 14 }}
          />
        </Col>
      </Row>
      {data.repair_rounds != null && data.repair_rounds > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Tag color="orange"><WarningOutlined /> 自动修复 {data.repair_rounds} 轮</Tag>
          {data.repair_history?.length > 0 && (
            <Collapse size="small" style={{ marginTop: 8 }} items={[{
              key: 'rh',
              label: '修复历史',
              children: data.repair_history.map((rh: any, i: number) => (
                <div key={i} style={{ fontSize: 12, marginBottom: 4 }}>
                  <Tag color={rh.success ? 'success' : 'error'}>轮次 {i + 1}</Tag>
                  {rh.error && <Text type="secondary">{rh.error.slice(0, 200)}</Text>}
                </div>
              )),
            }]} />
          )}
        </div>
      )}
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

// Sprint B: Quality Score panel with 4 dimensions
function QualityScorePanel({ data }: { data: any }) {
  if (!data) return <Text type="secondary">暂无质量评分数据</Text>
  const dims = data.dimensions || {}
  const dimList = [
    { key: 'business_coverage', label: '业务覆盖度', weight: '3.0', color: '#1677ff' },
    { key: 'scenario_coverage', label: '场景覆盖度', weight: '2.5', color: '#52c41a' },
    { key: 'maintainability', label: '可维护性', weight: '2.5', color: '#722ed1' },
    { key: 'execution_success', label: '执行成功率', weight: '2.0', color: '#fa8c16' },
  ]
  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col>
          <Statistic
            title="综合评分"
            value={data.total_score ?? '—'}
            suffix="/10"
            valueStyle={{ color: (data.total_score ?? 0) >= 7 ? '#52c41a' : '#ff4d4f', fontSize: 28 }}
          />
        </Col>
        <Col>
          <Statistic
            title="风险等级"
            valueRender={() => <Tag color={RISK_COLOR[data.risk_level] || 'default'} style={{ fontSize: 14 }}>{(data.risk_level || 'none').toUpperCase()}</Tag>}
          />
        </Col>
      </Row>
      <Divider style={{ margin: '12px 0' }} />
      <Row gutter={[16, 16]}>
        {dimList.map(d => {
          const val = dims[d.key]
          const pct = val != null ? (val / 10) * 100 : 0
          return (
            <Col xs={24} sm={12} key={d.key}>
              <div style={{ marginBottom: 8 }}>
                <Text strong style={{ fontSize: 13 }}>{d.label}</Text>
                <Tag style={{ marginLeft: 8, fontSize: 11 }}>权重 {d.weight}</Tag>
                <Text style={{ float: 'right', fontSize: 13, color: val != null ? d.color : '#bfbfbf' }}>
                  {val != null ? `${val.toFixed(1)}/10` : '—'}
                </Text>
              </div>
              <Progress
                percent={pct}
                strokeColor={d.color}
                size="small"
                showInfo={false}
              />
            </Col>
          )
        })}
      </Row>
      {data.suggestions && data.suggestions.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Text strong><WarningOutlined style={{ marginRight: 6, color: '#fa8c16' }} />改进建议</Text>
          <div style={{ marginTop: 8 }}>
            {data.suggestions.map((s: string, i: number) => (
              <div key={i} style={{ padding: '4px 0', fontSize: 13 }}>
                <Tag color="orange">{i + 1}</Tag>
                <Text>{s}</Text>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// Sprint C: Context panel — project rules + historical defects
function ContextPanel({ data }: { data: any }) {
  if (!data) return <Text type="secondary">暂无上下文信息</Text>
  const rules = data.project_rules || ''
  const defects = data.historical_defects || []
  if (!rules && defects.length === 0) return <Text type="secondary">暂无上下文信息</Text>
  return (
    <div>
      {rules && (
        <div style={{ marginBottom: 16 }}>
          <Text strong><FileTextOutlined style={{ marginRight: 6, color: '#1677ff' }} />项目测试规则</Text>
          <pre style={{ fontSize: 12, background: '#f5f5f5', padding: 12, borderRadius: 4, marginTop: 8, maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{rules}</pre>
        </div>
      )}
      {defects.length > 0 && (
        <div>
          <Text strong><BugOutlined style={{ marginRight: 6, color: '#ff4d4f' }} />历史缺陷记录（{defects.length} 条）</Text>
          <div style={{ marginTop: 8 }}>
            {defects.map((d: any, i: number) => (
              <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid #f0f0f0', fontSize: 12 }}>
                <code style={{ marginRight: 8 }}>{d.file || d.path || '—'}</code>
                <Text>{d.message || d.summary || '—'}</Text>
                {d.commit && <Tag style={{ marginLeft: 8, fontSize: 11 }}>{d.commit.slice(0, 8)}</Tag>}
              </div>
            ))}
          </div>
        </div>
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

  // Poll while in active status
  useEffect(() => {
    if (!task || !ACTIVE_STATUS.includes(task.status)) return
    const timer = setInterval(() => getTask(taskId!).then(setTask), 3000)
    return () => clearInterval(timer)
  }, [task, taskId])

  if (loading) return <Spin style={{ display: 'block', margin: '60px auto' }} />
  if (!task) return <Alert type="error" message="Task not found" />

  const od = task.output_data || {}
  const ctx = task.input_data?.context || task.input_data || {}

  return (
    <div style={{ maxWidth: 960 }}>
      {/* Header */}
      <Card style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="Task ID"><code style={{ fontSize: 12 }}>{task.task_id}</code></Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={STATUS_COLOR[task.status] || 'default'}>
              {STATUS_LABEL[task.status] || task.status}
            </Tag>
          </Descriptions.Item>
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
          taskId={ACTIVE_STATUS.includes(task.status) ? task.task_id : undefined}
          pipeline={task.pipeline}
          taskStatus={task.status}
        />
      </Card>

      {/* Per-node detail panels */}
      <Collapse
        defaultActiveKey={['cr']}
        items={[
          {
            key: 'ctx',
            label: (
              <span>
                <FileTextOutlined style={{ marginRight: 8, color: '#1677ff' }} />
                上下文信息（项目规则 & 历史缺陷）
              </span>
            ),
            children: <ContextPanel data={ctx} />,
          },
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
            key: 'ci',
            label: (
              <span>
                <BulbOutlined style={{ marginRight: 8, color: '#faad14' }} />
                变更智能分析
                {od.change_intelligence && (
                  <Tag
                    color={od.change_intelligence.need_test ? 'orange' : 'default'}
                    style={{ marginLeft: 8 }}
                  >
                    {od.change_intelligence.need_test ? '需测试' : '无需测试'}
                  </Tag>
                )}
              </span>
            ),
            children: <ChangeIntelligencePanel data={od.change_intelligence} />,
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
                {od.test_generation?.repair_rounds > 0 && (
                  <Tag color="orange" style={{ marginLeft: 4 }}>
                    修复 {od.test_generation.repair_rounds} 轮
                  </Tag>
                )}
              </span>
            ),
            children: <TestGenPanel data={od.test_generation} />,
          },
          {
            key: 'qs',
            label: (
              <span>
                <TrophyOutlined style={{ marginRight: 8, color: '#722ed1' }} />
                质量评分
                {od.quality_score?.total_score != null && (
                  <Tag color={od.quality_score.total_score >= 7 ? 'success' : 'warning'} style={{ marginLeft: 8 }}>
                    {od.quality_score.total_score.toFixed(1)}/10
                  </Tag>
                )}
              </span>
            ),
            children: <QualityScorePanel data={od.quality_score} />,
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
