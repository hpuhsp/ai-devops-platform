# AI Unit Test Engine CLI

The CLI is the GitLab CI integration surface for the AI unit test workflow.
It does not replace GitLab Runner. In the current phase it can trigger the
platform workflow through the API and always writes a structured report file.

## Local Wrapper

```bash
python tools/ai_test_engine.py run \
  --repo-url "$CI_REPOSITORY_URL" \
  --branch "$CI_COMMIT_REF_NAME" \
  --commit "$CI_COMMIT_SHA" \
  --before "$CI_COMMIT_BEFORE_SHA" \
  --output ai-test-report.json
```

Without `--api-url`, the CLI writes a deterministic `skipped` report explaining
that standalone AI execution is not configured yet.

## Platform Trigger Mode

```bash
python tools/ai_test_engine.py run \
  --api-url "http://ai-devops-platform:8090" \
  --repo-id "$AI_DEVOPS_REPO_ID" \
  --repo-url "$CI_REPOSITORY_URL" \
  --branch "$CI_COMMIT_REF_NAME" \
  --commit "$CI_COMMIT_SHA" \
  --before "$CI_COMMIT_BEFORE_SHA" \
  --output ai-test-report.json
```

This mode calls `POST /api/v1/unit-test/trigger` and stores the accepted
`task_id` in the report.

## GitLab CI Example

```yaml
ai_unit_test:
  stage: test
  image: python:3.11
  script:
    - python tools/ai_test_engine.py run --api-url "$AI_DEVOPS_API_URL" --repo-id "$AI_DEVOPS_REPO_ID" --repo-url "$CI_REPOSITORY_URL" --branch "$CI_COMMIT_REF_NAME" --commit "$CI_COMMIT_SHA" --before "$CI_COMMIT_BEFORE_SHA" --output ai-test-report.json
  artifacts:
    when: always
    paths:
      - ai-test-report.json
```
