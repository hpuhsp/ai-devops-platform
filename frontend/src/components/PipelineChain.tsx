import { useEffect, useRef, useState } from 'react'
import { Tooltip, Spin } from 'antd'
import {
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  StopOutlined, ExperimentOutlined, MergeCellsOutlined,
  BuildOutlined, RocketOutlined, CodeOutlined, MinusCircleOutlined,
  BulbOutlined, TrophyOutlined, WarningOutlined,
} from '@ant-design/icons'
import '../styles/pipeline.css'
import { streamEvent } from '../services/api'

export interface QualityDimensions {
  business_coverage?: number
  scenario_coverage?: number
  maintainability?: number
  execution_success?: number
}

export interface PipelineNode {
  status: string
  score?: number; findings?: number; critical_count?: number; high_count?: number
  framework?: string; files_count?: number
  pytest_status?: string; pytest_passed?: number; pytest_failed?: number
  message?: string
  reason?: string
  need_test?: boolean; risk_level?: string; impact_radius?: number; targets_count?: number
  total_score?: number; dimensions?: QualityDimensions; suggestions?: string[]
  repair_rounds?: number; repair_history?: any[]
}

export interface Pipeline {
  code_review: PipelineNode
  change_intelligence?: PipelineNode
  test_generation: PipelineNode
  quality_score?: PipelineNode
  auto_merge: PipelineNode
  ci_build?: PipelineNode
  deploy?: PipelineNode
}

interface Props {
  taskId?: string
  pipeline?: Pipeline
  taskStatus?: string
  compact?: boolean
  onUpdate?: (pipeline: Pipeline) => void
}

// ── Per-node metadata ────────────────────────────────────────────────────────

const NODE_META: Array<{
  key: keyof Pipeline
  label: string
  shortLabel: string
  Icon: React.ComponentType<any>
  phase2?: boolean
}> = [
  { key: 'code_review',         label: '代码审查', shortLabel: '审查', Icon: CodeOutlined },
  { key: 'change_intelligence', label: '变更智能', shortLabel: '变更', Icon: BulbOutlined },
  { key: 'test_generation',     label: '单元测试', shortLabel: '单测', Icon: ExperimentOutlined },
  { key: 'quality_score',       label: '质量评分', shortLabel: '质量', Icon: TrophyOutlined },
  { key: 'auto_merge',          label: '智能合并', shortLabel: '合并', Icon: MergeCellsOutlined },
  { key: 'ci_build',            label: 'CI 构建',  shortLabel: '构建', Icon: BuildOutlined,  phase2: true },
  { key: 'deploy',              label: '自动发布', shortLabel: '发布', Icon: RocketOutlined, phase2: true },
]

// ── Status → CSS class ───────────────────────────────────────────────────────

function nodeClass(node: PipelineNode | undefined, phase2?: boolean): string {
  if (phase2) return 'pipeline-node pipeline-node-phase2'
  if (!node)  return 'pipeline-node pipeline-node-pending'
  const raw = node.pytest_status === 'passed' ? 'done'
           : node.pytest_status === 'failed' ? 'failed'
           : node.status
  const s = raw === 'skip' ? 'skipped' : raw
  return `pipeline-node pipeline-node-${s}`
}

function NodeIcon({ node, Meta, phase2 }: { node: PipelineNode | undefined; Meta: typeof NODE_META[0]; phase2?: boolean }) {
  const { Icon } = Meta
  if (phase2) return <Icon className="pipeline-icon" style={{ color: '#bfbfbf', fontSize: 14 }} />
  if (!node || node.status === 'pending') return <ClockCircleOutlined className="pipeline-icon" style={{ color: '#d9d9d9', fontSize: 14 }} />
  if (node.status === 'running') return <Spin size="small" />
  if (node.status === 'skipped' || node.status === 'skip') return <MinusCircleOutlined className="pipeline-icon" style={{ color: '#bfbfbf', fontSize: 14 }} />
  const s = node.pytest_status || node.status
  if (s === 'passed' || s === 'done')    return <CheckCircleOutlined  className="pipeline-icon" style={{ fontSize: 14 }} />
  if (s === 'blocked') return <StopOutlined className="pipeline-icon" style={{ fontSize: 14 }} />
  if (s === 'failed') return <CloseCircleOutlined  className="pipeline-icon" style={{ fontSize: 14 }} />
  return <Icon className="pipeline-icon" style={{ fontSize: 14 }} />
}

function nodeTooltip(key: string, node: PipelineNode | undefined): string {
  if (!node || node.status === 'pending') return '等待中'
  if (node.status === 'skipped' || node.status === 'skip') return node.reason || '已跳过'
  if (node.status === 'running') return '执行中…'
  if (key === 'code_review') {
    if (node.status === 'blocked') return `拦截 | Critical:${node.critical_count} High:${node.high_count}`
    return `评分 ${node.score}/100 | ${node.findings} 个问题`
  }
  if (key === 'change_intelligence') {
    if (node.status === 'skip') return '无需测试'
    return `风险: ${node.risk_level || '—'} | 影响: ${node.impact_radius ?? 0} 文件 | 目标: ${node.targets_count ?? 0}`
  }
  if (key === 'test_generation') {
    if (node.pytest_status === 'passed') return `pytest ✅ ${node.pytest_passed} 个用例通过`
    if (node.pytest_status === 'failed') return `pytest ❌ ${node.pytest_failed} 个用例失败`
    return `生成 ${node.files_count} 个文件`
  }
  if (key === 'quality_score') {
    return `总分 ${node.total_score ?? '—'}/10 | 风险: ${node.risk_level || '—'}`
  }
  if (key === 'auto_merge') return node.message || '智能合并完成'
  return node.status
}

function connectorClass(prev: PipelineNode | undefined, cur: PipelineNode | undefined): string {
  if (!prev || prev.status === 'pending') return 'pipeline-connector'
  if (prev.status === 'running') return 'pipeline-connector flowing'
  const ps = prev.pytest_status || prev.status
  if (ps === 'done' || ps === 'passed' || ps === 'skip') return 'pipeline-connector done'
  if (ps === 'failed' || ps === 'blocked') return 'pipeline-connector failed'
  return 'pipeline-connector'
}

// Terminal statuses where SSE streaming should stop
const TERMINAL_STATUS = ['success', 'failed']
// Active statuses that should trigger SSE streaming
const ACTIVE_STATUS = ['created', 'analyzing', 'generating', 'executing', 'repairing', 'pending', 'running']

// ── Main component ───────────────────────────────────────────────────────────

export default function PipelineChain({ taskId, pipeline: initPipeline, taskStatus: initStatus, compact = false, onUpdate }: Props) {
  const [pipeline, setPipeline] = useState<Pipeline | undefined>(initPipeline)
  const [taskStatus, setTaskStatus] = useState(initStatus || 'pending')
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (initPipeline) setPipeline(initPipeline)
    if (initStatus) setTaskStatus(initStatus)
  }, [initPipeline, initStatus])

  useEffect(() => {
    if (!taskId || TERMINAL_STATUS.includes(initStatus || '')) return

    const es = streamEvent(taskId)
    esRef.current = es
    es.onmessage = (e) => {
      const item = JSON.parse(e.data)
      if (item.pipeline) {
        setPipeline(item.pipeline)
        setTaskStatus(item.status)
        onUpdate?.(item.pipeline)
      }
      if (TERMINAL_STATUS.includes(item.status)) es.close()
    }
    return () => { es.close() }
  }, [taskId])

  const nodes = NODE_META.map(meta => ({
    meta,
    node: pipeline?.[meta.key] as PipelineNode | undefined,
  }))

  return (
    <div className="pipeline-row">
      {nodes.map(({ meta, node }, i) => (
        <>
          {i > 0 && (
            <div key={`conn-${i}`} className={connectorClass(
              nodes[i - 1].node,
              node
            )} />
          )}
          <Tooltip key={meta.key} title={meta.phase2 ? '二期接入' : nodeTooltip(meta.key, node)}>
            <div className={nodeClass(node, meta.phase2)}>
              <div className="pipeline-dot">
                <NodeIcon node={node} Meta={meta} phase2={meta.phase2} />
              </div>
              <div className="pipeline-node-label">{compact ? meta.shortLabel : meta.label}</div>
              {!compact && (
                <div className="pipeline-node-desc">
                  {meta.phase2 ? '二期' : nodeTooltip(meta.key, node).slice(0, 12)}
                </div>
              )}
            </div>
          </Tooltip>
        </>
      ))}
    </div>
  )
}
