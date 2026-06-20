# aws-ec2-startstop

🌐 [English](README.md) | [Português](README.pt-BR.md)

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python)
![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-orange?logo=amazon-aws)

A single AWS Lambda function that automatically **starts and stops EC2 instances** across all regions on a schedule, using EventBridge (CloudWatch Events) rules.

---

## How it works

Two EventBridge rules invoke the same Lambda function at configured times, passing a JSON payload that tells it which action to perform. The Lambda then scans every enabled AWS region and starts or stops instances tagged with `ScheduledStartStop = True`.

```
EventBridge (EC2start, cron)  ──► Lambda (lambda_function) ──► EC2 instances (all regions)
EventBridge (EC2stop,  cron)  ──►         │
                                          └── Filters by tag: ScheduledStartStop = True
```

---

## Features

- Single Lambda handles both start and stop actions
- Scans **all enabled AWS regions** automatically
- Server-side filtering — only tagged instances are returned by the API
- Paginated API calls — works correctly at any scale
- Adaptive retry — handles AWS API throttling automatically
- Dry run mode — test without affecting any instance
- Structured JSON logs — compatible with CloudWatch Insights queries
- Configurable via environment variables — no code changes needed

---

## Prerequisites

- An AWS account with permissions to create Lambda functions, IAM roles, and EventBridge rules
- Python 3.12+ (for local development only)
- AWS CLI configured (optional, for CLI-based deployment)

---

## 1. Tag your EC2 instances

Add the following tag to every instance you want managed:

| Key                  | Value  |
|----------------------|--------|
| `ScheduledStartStop` | `True` |

> Instances **without** this tag are ignored entirely.

---

## 2. Create the IAM execution role

The Lambda needs a role with the following policy. You can create it via the AWS Console (IAM → Roles → Create role → Lambda) or with the AWS CLI:

**Policy document** — save as `ec2-startstop-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeRegions",
        "ec2:DescribeInstances",
        "ec2:StartInstances",
        "ec2:StopInstances"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

**AWS CLI:**

```bash
# Create the role
aws iam create-role \
  --role-name ec2-startstop-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach the policy
aws iam put-role-policy \
  --role-name ec2-startstop-role \
  --policy-name ec2-startstop-policy \
  --policy-document file://ec2-startstop-policy.json
```

---

## 3. Deploy the Lambda function

### Option A — AWS Console

1. Go to **Lambda → Create function**
2. Name: `ec2-startstop` | Runtime: **Python 3.12** | Architecture: `x86_64`
3. Execution role: select the role created in step 2
4. Upload `lambda_function.py` (or paste the code directly in the inline editor)
5. Handler: `lambda_function.lambda_handler`
6. Timeout: **5 minutes** (default 3 s is too short for multi-region scans)
7. Save

### Option B — AWS CLI

```bash
# Package the function
zip lambda_function.zip lambda_function.py

# Get your role ARN (replace with your account ID)
ROLE_ARN=$(aws iam get-role --role-name ec2-startstop-role --query Role.Arn --output text)

# Create the function
aws lambda create-function \
  --function-name ec2-startstop \
  --runtime python3.12 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_function.zip \
  --timeout 300

# To update after changes:
aws lambda update-function-code \
  --function-name ec2-startstop \
  --zip-file fileb://lambda_function.zip
```

---

## 4. Configure EventBridge rules

Create two rules that invoke the same Lambda with different payloads.

### AWS Console

1. Go to **EventBridge → Rules → Create rule**
2. Select **Schedule** and set your cron expression
3. Target: **Lambda function** → `ec2-startstop`
4. Under **Configure input**, select **Constant (JSON text)** and enter the payload below

| Rule name  | Cron example (UTC)      | Constant JSON input     | Description       |
|------------|-------------------------|-------------------------|-------------------|
| `EC2start` | `cron(0 11 ? * MON-FRI *)` | `{"action": "start"}` | Start at 08:00 BRT |
| `EC2stop`  | `cron(0 23 ? * MON-FRI *)` | `{"action": "stop"}`  | Stop at 20:00 BRT  |

> Adjust the cron expressions to match your timezone and schedule.

### AWS CLI

```bash
LAMBDA_ARN=$(aws lambda get-function --function-name ec2-startstop --query Configuration.FunctionArn --output text)

# EC2start rule
aws events put-rule \
  --name EC2start \
  --schedule-expression "cron(0 11 ? * MON-FRI *)" \
  --state ENABLED

aws events put-targets \
  --rule EC2start \
  --targets "Id=1,Arn=$LAMBDA_ARN,Input={\"action\":\"start\"}"

# EC2stop rule
aws events put-rule \
  --name EC2stop \
  --schedule-expression "cron(0 23 ? * MON-FRI *)" \
  --state ENABLED

aws events put-targets \
  --rule EC2stop \
  --targets "Id=1,Arn=$LAMBDA_ARN,Input={\"action\":\"stop\"}"

# Grant EventBridge permission to invoke the Lambda
aws lambda add-permission \
  --function-name ec2-startstop \
  --statement-id AllowEventBridgeStart \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn $(aws events describe-rule --name EC2start --query RuleArn --output text)

aws lambda add-permission \
  --function-name ec2-startstop \
  --statement-id AllowEventBridgeStop \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn $(aws events describe-rule --name EC2stop --query RuleArn --output text)
```

---

## Configuration

The function behavior can be adjusted via **Lambda environment variables** — no code changes required.

| Variable    | Default              | Description                                        |
|-------------|----------------------|----------------------------------------------------|
| `TAG_KEY`   | `ScheduledStartStop` | Tag key used to identify managed instances         |
| `TAG_VALUE` | `True`               | Expected tag value (case-sensitive)                |
| `DRY_RUN`   | `false`              | Set to `true` to log actions without executing them |

To set via CLI:

```bash
aws lambda update-function-configuration \
  --function-name ec2-startstop \
  --environment "Variables={TAG_KEY=ScheduledStartStop,TAG_VALUE=True,DRY_RUN=false}"
```

---

## Testing

### Dry run via Lambda console

Go to **Lambda → Test** and use the following payloads:

```json
{ "action": "start", "dry_run": true }
```

```json
{ "action": "stop", "dry_run": true }
```

No instances will be started or stopped. The log will show which instances _would_ have been affected.

### Dry run via AWS CLI

```bash
aws lambda invoke \
  --function-name ec2-startstop \
  --payload '{"action":"stop","dry_run":true}' \
  --cli-binary-format raw-in-base64-out \
  response.json && cat response.json
```

---

## Monitoring

All log entries are structured JSON, making them easy to query in **CloudWatch Logs Insights**.

**Find all instances affected today:**

```
fields @timestamp, action, region, instances
| filter ispresent(instances)
| sort @timestamp desc
| limit 50
```

**Find errors:**

```
fields @timestamp, region, error
| filter ispresent(error)
| sort @timestamp desc
```

---

## Local development

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Dry run locally (requires AWS credentials configured)
python -c "
from lambda_function import lambda_handler
result = lambda_handler({'action': 'stop', 'dry_run': True}, None)
print(result)
"
```

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'Add your feature'`
4. Push: `git push origin feature/your-feature`
5. Open a Pull Request

Please keep PRs focused — one feature or fix per PR.

---

## License

[MIT](LICENSE) — © Júlio César Santos

