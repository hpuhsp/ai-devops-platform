# AI单元测试Agent API接口设计文档 V1.0

## 1. 文档目标

定义AI单元测试Agent平台内部接口规范。

覆盖： - GitLab Webhook接入 - AI测试任务管理 - Agent状态管理 -
测试结果回传 - MR反馈

## 2. API架构

    GitLab
     |
    Webhook API
     |
    AI Orchestrator
     |
    Agent Services
     |
    Test Runner
     |
    Report Service
     |
    MR Comment

## 3. GitLab Webhook接口

POST /api/webhook/gitlab/mr

请求示例：

``` json
{
 "event_type":"merge_request",
 "project_id":1001,
 "mr_id":25,
 "commit_sha":"xxxx"
}
```

处理流程：

1.  校验事件
2.  获取代码变化
3.  创建AI分析任务

## 4. 创建AI测试任务

POST /api/test/tasks

请求：

``` json
{
 "project_id":1001,
 "mr_id":25,
 "changed_files":["OrderService.java"]
}
```

响应：

``` json
{
 "task_id":"task-001",
 "status":"CREATED"
}
```

## 5. Agent状态

GET /api/test/tasks/{id}

状态：

CREATED

ANALYZING

GENERATING

EXECUTING

REPAIRING

SUCCESS

FAILED

## 6. 测试结果

POST /api/test/result

示例：

``` json
{
 "task_id":"task-001",
 "compile":"SUCCESS",
 "test":"SUCCESS",
 "coverage_after":86
}
```

## 7. MR反馈

POST /api/report/mr/comment

输出：

-   风险等级
-   生成测试数量
-   执行结果
-   覆盖变化
-   风险建议

## 8. 安全要求

-   Token最小权限
-   API鉴权
-   日志脱敏
-   Agent任务隔离
