import { useEffect, useState, useCallback } from 'react'
import {
  Row, Col, Card, Statistic, Typography, Tag, Spin, Table, Button, Badge,
} from 'antd'
import {
  CheckCircleOutlined, ExperimentOutlined, MergeCellsOutlined,
  ThunderboltOutlined, ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { getOverview, listEvents } from '../../services/api'
import PipelineChain from '../../components/PipelineChain'
import { useNavigate } from 'react-router-dom'

const { Title, Text } = Typography

const TASK_STATUS_BADGE: Record<string, 'success' | 'processing' | 'default' | 'error' | 'warning'> = {
  created: 'default', analyzing: 'processing', generating: 'processing',
  executing: 'processing', repairing: 'processing',
  success: 'success', failed: 'error',
  pending: 'default', running: 'processing',
}

const ACTIVE_STATUS = ['created', 'analyzing', 'generating', 'executing', 'repairing', 'pending', 'running']

export default function DashboardPage() {
  const [overview, setOverview] = useState<any>(null)
  const [events, setEvents] = useState<any>({ items: [], total: 0 })
  const [loading, setLoading] = useState(true)
  const [eventsLoading, setEventsLoading] = useState(false)
  const [page, setPage] = useState(1)
  const navigate = useNavigate()

  const fetchOverview = useCallback(() => {
    getOverview().then(setOverview).catch(console.error)
  }, [])

  const fetchEvents = useCallback((p = 1) => {
    setEventsLoading(true)
    listEvents({ page: p, page_size: 10 })
      .then(setEvents)
      .catch(console.error)
      .finally(() => setEventsLoading(false))
  }, [])

  useEffect(() => {
    Promise.all([getOverview(), listEvents({ page: 1, page_size: 10 })])
      .then(([ov, ev]) => { setOverview(ov); setEvents(ev) })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  // Auto-refresh every 8s if any event is running
  useEffect(() => {
    const hasRunning = events.items.some((e: any) => ACTIVE_STATUS.includes(e.status))
    if (!hasRunning) return
    const timer = setInterval(() => { fetchOverview(); fetchEvents(page) }, 8000)
    return () => clearInterval(timer)
  }, [events.items, page, fetchOverview, fetchEvents])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />

  const cr = overview?.code_review || {}
  const tg = overview?.test_generation || {}
  const am = overview?.auto_merge || {}

  const columns = [
    {
      title: '提交',
      width: 160,
      render: (_: any, r: any) => (
        <span>
          <Badge status={TASK_STATUS_BADGE[r.status] || 'default'} />
          <code style={{ fontSize: 11 }}>{r.commit_sha || '——'}</code>
          <br />
          <Text type="secondary" style={{ fontSize: 11 }}>{r.branch}</Text>
        </span>
      ),
    },
    {
      title: '作者',
      dataIndex: 'author',
      width: 90,
      render: (v: string) => <Text style={{ fontSize: 12 }}>{v || '—'}</Text>,
    },
    {
      title: '流水线节点',
      render: (_: any, r: any) => (
        <PipelineChain
          taskId={ACTIVE_STATUS.includes(r.status) ? r.task_id : undefined}
          pipeline={r.pipeline}
          taskStatus={r.status}
          compact
        />
      ),
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 70,
      render: (v: number) => v ? `${(v / 1000).toFixed(1)}s` : '—',
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 110,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '',
      width: 60,
      render: (_: any, r: any) => (
        <Button size="small" type="link" onClick={() => navigate(`/tasks/${r.task_id}`)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24, gap: 12 }}>
        <Title level={4} style={{ margin: 0 }}>智能 DevOps 驾驶舱</Title>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => { fetchOverview(); fetchEvents(page) }}
        >
          刷新
        </Button>
      </div>

      {/* ── Phase 1 Three Dimensions ── */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title={<span><CheckCircleOutlined style={{ color: '#1677ff', marginRight: 6 }} />代码审查</span>}
              value={cr.total ?? 0}
              suffix={<Text type="secondary" style={{ fontSize: 13 }}>次</Text>}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#888', display: 'flex', gap: 12 }}>
              <span>拦截 <strong style={{ color: '#ff4d4f' }}>{cr.blocked ?? 0}</strong>次</span>
              <span>拦截率 <strong>{cr.block_rate ?? 0}%</strong></span>
              <span>均分 <strong style={{ color: '#52c41a' }}>{cr.avg_score ?? '—'}</strong></span>
            </div>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title={<span><ExperimentOutlined style={{ color: '#52c41a', marginRight: 6 }} />单元测试</span>}
              value={tg.total ?? 0}
              suffix={<Text type="secondary" style={{ fontSize: 13 }}>次</Text>}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#888', display: 'flex', gap: 12 }}>
              <span>通过 <strong style={{ color: '#52c41a' }}>{tg.passed ?? 0}</strong>次</span>
              <span>通过率 <strong>{tg.pass_rate ?? 0}%</strong></span>
            </div>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title={<span><MergeCellsOutlined style={{ color: '#722ed1', marginRight: 6 }} />智能合并</span>}
              value={am.total ?? 0}
              suffix={<Text type="secondary" style={{ fontSize: 13 }}>次</Text>}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#888', display: 'flex', gap: 12 }}>
              <span>成功 <strong style={{ color: '#52c41a' }}>{am.success ?? 0}</strong>次</span>
              <span>成功率 <strong>{am.success_rate ?? 0}%</strong></span>
            </div>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card bodyStyle={{ padding: '16px 20px' }}>
            <Statistic
              title={<span><ThunderboltOutlined style={{ color: '#fa8c16', marginRight: 6 }} />Token 消耗</span>}
              value={overview?.total_tokens_used ?? 0}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#888' }}>
              近7天 <strong>{overview?.week_tasks ?? 0}</strong> 次触发
            </div>
          </Card>
        </Col>
      </Row>

      {/* ── Recent Push Events with Pipeline Chain ── */}
      <Title level={5} style={{ marginTop: 28, marginBottom: 12 }}>近期推送事件 · 流水线进度</Title>
      <Card bodyStyle={{ padding: 0 }}>
        <Table
          dataSource={events.items}
          columns={columns}
          rowKey="task_id"
          size="small"
          loading={eventsLoading}
          scroll={{ x: 800 }}
          pagination={{
            total: events.total,
            current: page,
            pageSize: 10,
            showSizeChanger: false,
            onChange: (p) => { setPage(p); fetchEvents(p) },
          }}
        />
      </Card>

      {/* ── Phase 2 Reserved Panels ── */}
      <Title level={5} style={{ marginTop: 28, marginBottom: 12 }}>
        二期预留面板
        <Tag color="orange" style={{ marginLeft: 10, fontSize: 11 }}>Coming in Phase 2</Tag>
      </Title>
      <Row gutter={[16, 16]}>
        {['🏗️ Jenkins 构建统计', '🚀 自动发布记录', '📊 构建成功率趋势'].map(title => (
          <Col key={title} xs={24} sm={12} lg={8}>
            <Card title={title} extra={<Tag color="default">待接入</Tag>} style={{ opacity: 0.55 }}>
              <div style={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#bbb', fontSize: 13 }}>
                数据接入后自动展示
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
