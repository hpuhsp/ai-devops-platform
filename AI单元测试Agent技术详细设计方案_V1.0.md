# AI单元测试Agent技术详细设计方案 V1.0

## 1. 系统架构

    ai-unit-test-platform

    ├── webhook-service
    │
    ├── orchestrator-service
    │
    ├── change-analyzer
    │
    ├── context-service
    │
    ├── test-agent
    │
    ├── worktree-manager
    │
    ├── test-runner
    │
    ├── llm-gateway
    │
    └── report-service

------------------------------------------------------------------------

# 2. 服务职责

## webhook-service

负责：

-   GitLab Webhook接收
-   MR事件解析

## orchestrator-service

负责：

-   Agent任务编排
-   状态管理

## change-analyzer

负责：

-   Diff分析
-   风险评估
-   是否触发测试

## context-service

负责：

-   CodeGraph查询
-   Repository上下文构建

## worktree-manager

负责：

-   创建隔离目录
-   Branch管理
-   生命周期清理

## test-runner

负责：

-   Docker测试执行
-   日志采集

------------------------------------------------------------------------

# 3. GitLab流程设计

    MR Created

    ↓

    Webhook

    ↓

    AI Orchestrator

    ↓

    Change Analyzer

    ↓

    Decision

    ↓

    AI Test Agent

    ↓

    MR Comment

------------------------------------------------------------------------

# 4. Agent流程

    Test Manager Agent

            |

    Context Agent

            |

    Generator Agent

            |

    Validator Agent

            |

    Repair Agent

------------------------------------------------------------------------

# 5. Worktree规范

创建：

    git worktree add
    ../ai-worktree-task
    -b ai/test/task-id

执行完成：

    git worktree remove

------------------------------------------------------------------------

# 6. 数据模型

## ai_test_task

字段：

-   id
-   project_id
-   mr_id
-   commit_sha
-   status
-   risk_level
-   result

## agent_execution

字段：

-   task_id
-   agent_type
-   input
-   output
-   duration

------------------------------------------------------------------------

# 7. LLM Gateway

职责：

-   模型统一接入
-   路由选择
-   Token统计

模型策略：

复杂分析：

Claude/Gemini

代码生成：

Claude/DeepSeek

修复：

DeepSeek

------------------------------------------------------------------------

# 8. Prompt规范

测试生成要求：

-   理解业务逻辑
-   优先覆盖异常场景
-   避免无意义Mock
-   保证可维护性

------------------------------------------------------------------------

# 9. 测试沙箱

要求：

-   Docker隔离
-   CPU限制
-   内存限制
-   超时控制
-   网络隔离

------------------------------------------------------------------------

# 10. MVP开发计划

## Sprint 1

完成：

-   GitLab Webhook
-   MR解析

## Sprint 2

完成：

-   Worktree管理
-   AI测试生成

## Sprint 3

完成：

-   自动执行
-   MR反馈

## Sprint 4

完成：

-   自动修复
-   效果优化
