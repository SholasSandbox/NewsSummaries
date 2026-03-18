# Cost Estimation — NewsSummaries

All prices are **US East (N. Virginia) — us-east-1** as of early 2025.
Actual costs vary by region. Prices shown are public on-demand rates.

---

## Assumptions (Light Usage)

| Metric | Value |
|---|---|
| Runs per day | 2 (06:00 and 18:00 UTC) |
| RSS feeds polled per run | 10 |
| Articles ingested per run | ~100 (after dedup: ~50 new) |
| Articles per month | ~3,000 |
| Average summary tokens | 500 input + 150 output = 650 tokens |
| Average TTS characters | 400 chars per episode |
| Average MP3 file size | ~800 KB |
| CloudFront downloads per month | ~500 |

---

## 1. Lambda

**Free tier**: 1,000,000 requests/month + 400,000 GB-seconds/month (perpetual, not just the first year).

| Function | Invocations/month | Duration | Memory | GB-sec |
|---|---|---|---|---|
| IngestNews | 60 (2/day × 30) | 30 s avg | 512 MB | 60 × 30 × 0.5 = **900** |
| GenerateSummaries | 3,000 (per article) | 5 s avg | 1,024 MB | 3000 × 5 × 1 = **15,000** |
| GenerateAudio | 3,000 (per episode) | 10 s avg | 1,024 MB | 3000 × 10 × 1 = **30,000** |
| **Total** | **6,060** | | | **45,900 GB-sec** |

- Invocations: 6,060 vs 1,000,000 free → **$0.00**
- GB-seconds: 45,900 vs 400,000 free → **$0.00**

> **Lambda cost: $0.00/month** (entirely within free tier)

---

## 2. S3

**Storage:**

| Tier | Objects | Avg size | Total |
|---|---|---|---|
| Standard (< 30 days) | 3 types × 3,000 | 10 KB / 10 KB / 800 KB | ~2.46 GB |
| Standard-IA (30–90 days) | rolling 2 months | same | ~4.9 GB |

Monthly storage cost:
- Standard: 2.46 GB × $0.023 = **$0.057**
- Standard-IA: 4.9 GB × $0.0125 = **$0.061**

**PUT/GET requests:**
- PUTs (ingest + summaries + audio): ~9,000 × $0.005/1000 = **$0.045**
- GETs (reading back objects): ~15,000 × $0.0004/1000 = **$0.006**

> **S3 cost: ~$0.17/month**

---

## 3. DynamoDB

**On-demand pricing:**

| Operation | Count/month | Cost per million | Cost |
|---|---|---|---|
| Write Request Units (WRU) | 3,000 | $1.25 | $0.004 |
| Read Request Units (RRU) | 9,000 | $0.25 | $0.002 |
| Storage | < 1 GB | $0.25/GB | $0.00 |

DynamoDB also has a **free tier**: 25 WCU + 25 RCU (provisioned). On on-demand at this scale, it's sub-penny.

> **DynamoDB cost: ~$0.01/month**

---

## 4. CloudFront

**Free tier (first 12 months)**: 1 TB data transfer out, 10 million HTTP requests.

After free tier:
- Data transfer: 500 downloads × 800 KB = 0.4 GB × $0.0085/GB = **$0.003**
- HTTP requests: 500 × $0.0075/10,000 = **$0.0004**

> **CloudFront cost: ~$0.00/month** (within free tier; ~$0.003/month after)

---

## 5. OpenAI API

### o3-mini (summarisation)

Pricing (as of early 2025): $1.10 per 1M input tokens, $4.40 per 1M output tokens.

| | Tokens | Cost |
|---|---|---|
| Input (500 tokens × 3,000 articles) | 1,500,000 | $1.65 |
| Output (150 tokens × 3,000 articles) | 450,000 | $1.98 |
| **Subtotal** | | **$3.63** |

### TTS tts-1 (audio generation)

Pricing: $15.00 per 1M characters.

- 400 chars × 3,000 episodes = 1,200,000 chars
- 1.2M × $0.015/1000 chars = **$18.00**

> **OpenAI cost: ~$21.63/month**

---

## 6. Other AWS Services (Near-Zero)

| Service | Cost |
|---|---|
| EventBridge Scheduler | $1.00 per 14M invocations; 60/month → **$0.00** |
| SQS DLQs | 1M free requests/month → **$0.00** |
| SNS | 1M free publishes/month → **$0.00** |
| SSM Parameter Store | Standard parameters free → **$0.00** |
| CloudWatch Logs | 5 GB/month free; logs here are KB-range → **$0.00** |
| CloudWatch Alarms | $0.10 per alarm × 3 = **$0.30** |

---

## 7. Summary

| Service | Monthly Cost |
|---|---|
| Lambda | $0.00 |
| S3 | $0.17 |
| DynamoDB | $0.01 |
| CloudFront | $0.00 |
| EventBridge, SQS, SNS, SSM | $0.00 |
| CloudWatch Alarms | $0.30 |
| **AWS Total** | **~$0.48** |
| OpenAI (summarisation) | $3.63 |
| OpenAI (TTS) | $18.00 |
| **OpenAI Total** | **$21.63** |
| **Grand Total** | **~$22.11/month** |

---

## Cost Reduction Strategies

### Reduce OpenAI TTS cost (largest line item)
- Process only `importance: high` articles through TTS → reduces volume by ~60%
- Estimated saving: ~**$10.80/month**
- Use `tts-1` (not `tts-1-hd`) — already chosen; `hd` would double TTS cost

### Reduce o3-mini cost
- Filter articles to top 10 per run (instead of ~50) → reduces 80%
- Estimated saving: ~**$2.90/month**

### Optimised scenario (high-importance only, top 10/run)

| Scenario | Monthly Cost |
|---|---|
| Full pipeline (~50 articles/run, all TTS) | ~$22.11 |
| High-importance only (~20 articles/run, TTS) | ~$9.00 |
| Top 10/run (all TTS) | ~$5.00 |
| Top 10/run (high-importance TTS only) | **~$2.50** |

### DynamoDB on-demand vs provisioned

At the current scale, on-demand is cheaper. If you scale to 10,000+ writes/month consistently, switch to provisioned with auto-scaling for ~40% savings.

---

## Cost Monitoring

Set up an AWS Budget to alert if costs exceed $30/month:

```bash
aws budgets create-budget \
  --account-id $(aws sts get-caller-identity --query Account --output text) \
  --budget '{
    "BudgetName": "NewsSummaries-Monthly",
    "BudgetLimit": {"Amount": "30", "Unit": "USD"},
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST"
  }' \
  --notifications-with-subscribers '[{
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80
    },
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "you@example.com"}]
  }]'
```
