# IAM Policy for Next.js Web App

The Next.js web app (`web/`) needs an IAM identity with the following permissions to bridge
into the existing AWS Lambda pipeline.

## Minimum IAM Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3RawAndSummaries",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws:s3:::news-summaries-{stage}-content-{account}/*"
      ],
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "raw/*",
            "summaries/*",
            "unified/*"
          ]
        }
      }
    },
    {
      "Sid": "LambdaInvoke",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:{region}:{account}:function:news-summaries-{stage}-generate-summaries"
    },
    {
      "Sid": "DynamoDedup",
      "Effect": "Allow",
      "Action": [
        "dynamodb:BatchGetItem",
        "dynamodb:PutItem"
      ],
      "Resource": "arn:aws:dynamodb:{region}:{account}:table/news-summaries-{stage}-episodes"
    }
  ]
}
```

## DynamoDB Table (existing — no schema changes needed)

The web pipeline reuses the **same** `news-summaries-{stage}-episodes` table that
the Python Lambda pipeline writes to.

| Attribute        | Type   | Notes                                                         |
|------------------|--------|---------------------------------------------------------------|
| `episode_id`     | String | **Partition key.** For articles: `article_hash` (16-char hex). For unified summaries: `unified-{date}-{uuid}`. |
| `date`           | String | **Sort key.** `YYYY-MM-DD`                                    |
| `category`       | String | `"unified"` for distilled summaries                          |
| `status`         | String | `"distilled"` for unified summaries                          |
| `s3_key`         | String | `unified/{date}/{uuid}.json` — full content stored in S3      |
| `ttl`            | Number | Unix timestamp — 90-day automatic expiry                      |

## S3 Key Structure (no changes needed)

```
{bucket}/
  raw/{YYYY-MM-DD}/{article_hash}.json       ← Lambda 1 + web pipeline write here
  summaries/{YYYY-MM-DD}/{article_hash}.json ← Lambda 2 writes here
  audio/{YYYY-MM-DD}/{episode_id}.mp3        ← Lambda 3 writes here
  unified/{YYYY-MM-DD}/{uuid}.json           ← NEW: web pipeline unified summaries
```
