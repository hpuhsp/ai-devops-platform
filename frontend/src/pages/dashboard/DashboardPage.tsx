import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Typography, Tag, Spin, Empty } from 'antd'
import { CheckCircleOutlined, StopOutlined, ExperimentOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { getOverview } from '../../services/api'

const { Title, Text } = Typography

interface Overview {
  total_reviews: number
  total_test_gen: number
  blocked_count: number
  block_rate: number
  total_tokens_used: number
  week_tasks: number
  jenkins_builds_total: null | number
  jenkins_success_rate: null | number
  deploy_count: null | number
}

export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getOverview()
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '80px auto' }} />

  return (
    <div>
      <Title level={4} style={{ marginTop: 0, marginBottom: 24 }}>一期数据总览</Title>

      {/* Phase 1 Metrics */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="AI 代码审核次数"
              value={data?.total_reviews ?? 0}
              prefix={<CheckCircleOutlined style={{ color: '#1677ff' }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="AI 单测生成次数"
              value={data?.total_test_gen ?? 0}
              prefix={<ExperimentOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="拦截次数"
              value={data?.blocked_count ?? 0}
              prefix={<StopOutlined style={{ color: '#ff4d4f' }} />}
              suffix={<Text type="secondary" style={{ fontSize: 14 }}>({data?.block_rate ?? 0}%)</Text>}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Token 消耗"
              value={data?.total_tokens_used ?? 0}
              prefix={<ThunderboltOutlined style={{ color: '#fa8c16' }} />}
            />
          </Card>
        </Col>
      </Row>

      {/* Phase 2 Reserved Panels */}
      <Title level={4} style={{ marginTop: 32, marginBottom: 16 }}>
        二期预留面板
        <Tag color="orange" style={{ marginLeft: 12, fontSize: 12 }}>Coming in Phase 2</Tag>
      </Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={8}>
          <Card
            title="🏗️ Jenkins 构建统计"
            extra={<Tag color="default">待接入</Tag>}
            style={{ opacity: 0.6 }}
          >
            <Empty description="Jenkins 数据接入后自动展示" imageStyle={{ height: 48 }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card
            title="🚀 自动发布记录"
            extra={<Tag color="default">待接入</Tag>}
            style={{ opacity: 0.6 }}
          >
            <Empty description="发布流水线接入后自动展示" imageStyle={{ height: 48 }} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card
            title="📊 构建成功率趋势"
            extra={<Tag color="default">待接入</Tag>}
            style={{ opacity: 0.6 }}
          >
            <Empty description="Jenkins 数据接入后展示图表" imageStyle={{ height: 48 }} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
