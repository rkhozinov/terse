"""Bench corpus: 10 self-contained prompts.

Shapes and wording are taken from the user's real session transcripts
(status checks, log diagnosis, architecture explain, compare-and-decide,
diff review, runbooks, quick facts, risk calls, output summarisation, and
an underspecified ask). Every prompt carries its own context inline so a
run needs no tools and no repo state -- the only thing varying between
arms is the output style.

Published prompts are SANITIZED equivalents of the ones the recorded run used:
service, bucket and PR identifiers were replaced with neutral ones after the
fact. Shape, length and difficulty are unchanged, but the numbers in
RESULTS.md come from the pre-sanitization wording. Re-run the matrix if you
need results that provably match these exact strings.
"""

TASKS = {
    # 1. "what's left?" -- the single most common ask in the transcripts
    "status": {
        "class": "status",
        "prompt": """Here is the current state of the KEDA rollout:

- PR #121 (keda operator terraform, us-west-2 test) - merged, applied
- PR #122 (keda operator terraform, us-west-2 stage) - merged, apply failed: IRSA role missing trust policy for stage OIDC provider
- PR #123 (ScaledObject for tracking-service, test) - open, 1 approval, CI green
- PR #124 (ScaledObject for tracking-service, stage) - draft, blocked on #122
- PR #125 (prod operator + ScaledObjects) - not written yet
- Soak test on test env: running since 14:02Z, 6h window, no scale-down redelivery so far

What's left?""",
    },

    # 2. diagnose from a log paste
    "diagnose": {
        "class": "diagnose",
        "prompt": """A pod keeps restarting. Events and logs:

    Events:
      Normal   Pulled     4m (x5 over 9m)   kubelet  Container image "1234.dkr.ecr.us-east-2.amazonaws.com/auth-service:prod-20260802-49a152c" already present on machine
      Normal   Created    4m (x5 over 9m)   kubelet  Created container auth-service
      Normal   Started    4m (x5 over 9m)   kubelet  Started container auth-service
      Warning  BackOff    2m (x18 over 8m)  kubelet  Back-off restarting failed container

    auth-service logs (last 12 lines):
      {"level":"info","msg":"starting auth-service","version":"prod-20260802-49a152c"}
      {"level":"info","msg":"connected to postgres","host":"auth-prod.cluster-abc.us-east-2.rds.amazonaws.com"}
      {"level":"info","msg":"loaded 14 config keys from secret auth-service/prod"}
      {"level":"fatal","msg":"config validation failed: required key OIDC_CLIENT_SECRET missing"}

    kubectl get secret -n auth auth-service-prod -o jsonpath='{.data}' | jq keys
      ["DATABASE_URL","JWT_SIGNING_KEY","OIDC_CLIENT_ID","REDIS_URL","SENTRY_DSN", ... 9 more, no OIDC_CLIENT_SECRET]

What is wrong and how do I fix it?""",
    },

    # 3. explain an architecture / algorithm from config
    "explain": {
        "class": "explain",
        "prompt": """Explain how this autoscaling behaves - what drives scale up and down, and what the
worst case is.

    apiVersion: keda.sh/v1alpha1
    kind: ScaledObject
    metadata:
      name: tracking-service
    spec:
      scaleTargetRef:
        name: tracking-service
      minReplicaCount: 3
      maxReplicaCount: 30
      pollingInterval: 30
      cooldownPeriod: 300
      advanced:
        horizontalPodAutoscalerConfig:
          behavior:
            scaleDown:
              stabilizationWindowSeconds: 600
              policies:
                - type: Percent
                  value: 25
                  periodSeconds: 60
      triggers:
        - type: kafka
          metadata:
            topic: location-updates
            consumerGroup: tracking-service
            lagThreshold: "500"
        - type: cpu
          metricType: Utilization
          metadata:
            value: "70" """,
    },

    # 4. compare two options and pick one
    "decide": {
        "class": "decide",
        "prompt": """We keep 400 days of metrics in a single VictoriaMetrics instance (VMSingle) on a 256Gi
gp3 EBS volume in us-east-2. Current ingest 180k samples/s, disk 61% full, growing ~4%/month.
Two proposals:

A) Stay on VMSingle, grow the volume, keep the vmbackup sidecar shipping snapshots to S3.
   Restore = pull the snapshot, ~40 min for the current data size. Single AZ. One process to run.

B) Move to VictoriaMetrics cluster mode (vminsert/vmselect/vmstorage, 3 storage nodes across AZs),
   replicationFactor 2. Survives one node or AZ loss with no restore. Roughly 2.4x the compute
   cost, and we would be running a stateful set we have never operated before.

Availability target for the metrics stack is 99% monthly. Team is 2 platform engineers.
Which one, and why?""",
    },

    # 5. review a diff
    "review-diff": {
        "class": "review",
        "prompt": """Review this Terraform change:

    +resource "aws_security_group_rule" "vmsingle_ingress" {
    +  type              = "ingress"
    +  from_port         = 8428
    +  to_port           = 8428
    +  protocol          = "tcp"
    +  cidr_blocks       = ["0.0.0.0/0"]
    +  security_group_id = aws_security_group.monitoring.id
    +}
    +
    +resource "aws_s3_bucket" "vm_backups" {
    +  bucket = "metrics-backups"
    +}
    +
    +resource "aws_iam_role_policy" "vmbackup" {
    +  role = aws_iam_role.vmbackup.id
    +  policy = jsonencode({
    +    Version = "2012-10-17"
    +    Statement = [{
    +      Effect   = "Allow"
    +      Action   = ["s3:*"]
    +      Resource = "*"
    +    }]
    +  })
    +}
    -variable "retention_days" { default = 180 }
    +variable "retention_days" { default = 400 }""",
    },

    # 6. ordered procedure -- fragments must not scramble the order
    "runbook": {
        "class": "procedure",
        "prompt": """A Grafana Cloud API token with admin scope was committed to a public repo 20 minutes ago
and the commit is already pushed. We use that token in three places: a GitHub Actions secret, a
Terraform provider config reading from AWS Secrets Manager, and one engineer's local shell profile.
Give me the exact steps to handle this, in the order I should do them.""",
    },

    # 7. quick fact -- the compression floor
    "quickfact": {
        "class": "status",
        "prompt": """Our regions map like this: us-east-2 = production, us-west-2 = test and stage,
europe-west1 (GCP) = production EU. Which region do I run a prod-only smoke test in?""",
    },

    # 8. risk / trade-off call
    "risk": {
        "class": "decide",
        "prompt": """Proposal: enable GitHub auto-merge on the infrastructure repo for PRs that only bump a
service image tag, gated on CI green and one approval from the owning team. Today those PRs are
merged by hand, usually within a few hours; prod applies run from master on a manual dispatch.
About 25 such PRs land per week. What are the real risks, and would you turn it on?""",
    },

    # 9. summarise a long tool output
    "summarize": {
        "class": "explain",
        "prompt": """Summarise what matters in this terraform plan output:

    Terraform will perform the following actions:

      # aws_ecs_service.api will be updated in-place
      ~ resource "aws_ecs_service" "api" {
            id = "arn:aws:ecs:us-east-2:1234:service/prod/api"
          ~ desired_count = 4 -> 6
            name = "api"
        }

      # aws_db_instance.main will be updated in-place
      ~ resource "aws_db_instance" "main" {
            id = "auth-prod"
          ~ backup_retention_period = 7 -> 1
          ~ apply_immediately = false -> true
            engine_version = "15.5"
        }

      # aws_security_group_rule.db_ingress must be replaced
      -/+ resource "aws_security_group_rule" "db_ingress" {
          ~ cidr_blocks = ["10.0.0.0/16"] -> ["10.0.0.0/8"] # forces replacement
          ~ id = "sgrule-2841" -> (known after apply)
        }

      # aws_cloudwatch_log_group.api will be destroyed
      - resource "aws_cloudwatch_log_group" "api" {
          - name = "/ecs/prod/api"
          - retention_in_days = 90
        }

    Plan: 1 to add, 2 to change, 2 to destroy.""",
    },

    # 10. underspecified -- a good answer asks before acting.
    # The no-tools line is appended identically for every arm: without it the model
    # tries to call a tool it does not have and emits tool-call syntax as prose,
    # which measures the harness, not the style.
    "underspecified": {
        "class": "clarify",
        "prompt": """The disk alert is noisy. Fix it.

(You have no tools and no access to any repo in this session. Answer in chat.)""",
    },
}
