# AI单元测试Agent平台建设方案规格文档 V1.0

## 1. 建设定位

本项目建设目标不是传统CI测试自动化，而是构建面向AI Native研发流程的 **AI
Unit Test Agent（AI单元测试智能代理）**。

核心理念：

> AI负责理解代码变更价值，决定是否介入，并完成测试生成、验证和反馈闭环。

------------------------------------------------------------------------

# 2. 建设目标

实现：

-   GitLab Merge Request级触发
-   AI代码变更影响分析
-   自动判断测试必要性
-   基于代码上下文生成单元测试
-   自动执行测试
-   自动分析失败原因并修复
-   MR反馈测试报告

------------------------------------------------------------------------

# 3. 总体架构

    Developer

        |

    GitLab Merge Request

        |

    AI Quality Orchestrator

        |

    Change Intelligence Agent

        |

    Repository Intelligence
    (CodeGraph / RepoWiki)

        |

    AI Test Agent

        |

    Git Worktree

        |

    Test Sandbox

        |

    MR Feedback

------------------------------------------------------------------------

# 4. 触发策略

## 不采用

Commit/PUSH触发。

原因：

-   提交频率高
-   大量无价值变更
-   AI成本浪费

------------------------------------------------------------------------

## 推荐

Merge Request事件触发。

MR代表：

-   业务变更意图
-   代码评审节点
-   质量控制入口

------------------------------------------------------------------------

# 5. Change Intelligence设计

负责判断：

是否需要生成测试。

输入：

-   git diff
-   修改文件
-   调用关系
-   历史缺陷
-   覆盖率变化

输出：

``` json
{
 "need_test": true,
 "risk_level": "high",
 "target":["OrderService"]
}
```

------------------------------------------------------------------------

# 6. AI Test Agent

包含：

## Test Manager Agent

负责流程编排。

## Context Agent

负责获取：

-   CodeGraph
-   Repo规则
-   已有测试

## Generator Agent

负责生成测试。

## Validator Agent

负责执行验证。

## Repair Agent

负责失败修复。

------------------------------------------------------------------------

# 7. Git Worktree定位

Git Worktree作为AI Agent代码隔离环境。

作用：

-   多Agent并行
-   避免污染开发分支
-   支持AI自动修改代码

流程：

    Create Worktree

    ↓

    Generate Test

    ↓

    Execute Test

    ↓

    Create AI Branch

    ↓

    MR反馈

------------------------------------------------------------------------

# 8. 分阶段实施

## Phase 1

实现：

-   GitLab接入
-   MR分析
-   测试生成
-   自动执行
-   MR反馈

## Phase 2

增加：

-   CodeGraph
-   自动修复
-   测试质量评分

## Phase 3

演进：

AI Quality Platform

------------------------------------------------------------------------

# 9. 验收指标

关注：

-   测试生成成功率
-   编译通过率
-   自动修复能力
-   开发采纳率
