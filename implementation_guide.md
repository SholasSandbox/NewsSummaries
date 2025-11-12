# AWS News Summarizer - Implementation Guide

## Phase 1: Setup & Prerequisites

### 1. AWS Account Setup
- [ ] AWS account with appropriate permissions
- [ ] AWS CLI installed and configured
- [ ] Enable Bedrock model access (Claude/Titan)
- [ ] Get NewsAPI key (newsapi.org)

### 2. Local Development Setup
```bash
# Install required tools
pip install boto3 aws-sam-cli
npm install -g aws-cdk  # if using CDK
```

## Phase 2: Core Infrastructure (30 mins)

### 1. S3 Buckets
```bash
# Create S3 bucket for content storage
aws s3 mb s3://your-news-app-content-bucket
```

### 2. DynamoDB Table
```python
# Table for metadata and run logs
Table: news-summarizer-metadata
Partition Key: run_id (String)
Sort Key: timestamp (String)
```

### 3. Secrets Manager
```bash
# Store NewsAPI key
aws secretsmanager create-secret \
  --name "news-api-credentials" \
  --secret-string '{"api_key":"YOUR_NEWS_API_KEY"}'
```

## Phase 3: Lambda Functions (2 hours)

### 1. Ingestion Function
**File: `lambda/ingest/handler.py`**
- Pull from NewsAPI/RSS
- Normalize and deduplicate
- Store raw data in S3

### 2. Summarization Function  
**File: `lambda/summarize/handler.py`**
- Call Bedrock (Claude) for summarization
- Apply custom prompts
- Store processed content

### 3. Voice Generation Function
**File: `lambda/voice/handler.py`**
- Call Polly for text-to-speech
- Generate MP3 files
- Store audio in S3

### 4. Publishing Function
**File: `lambda/publish/handler.py`**
- Create web JSON/RSS feeds
- Update DynamoDB index
- Trigger CloudFront invalidation

## Phase 4: Orchestration (45 mins)

### 1. Step Functions State Machine
```json
{
  "Comment": "News Summarizer Workflow",
  "StartAt": "IngestNews",
  "States": {
    "IngestNews": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:news-ingest",
      "Next": "SummarizeNews"
    },
    "SummarizeNews": {
      "Type": "Task", 
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:news-summarize",
      "Next": "GenerateVoice"
    },
    "GenerateVoice": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:news-voice", 
      "Next": "PublishContent"
    },
    "PublishContent": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:REGION:ACCOUNT:function:news-publish",
      "End": true
    }
  }
}
```

### 2. EventBridge Scheduler
```bash
# Schedule for AM (6:30) and PM (18:00)
aws events put-rule \
  --name "news-summarizer-am" \
  --schedule-expression "cron(30 6 * * ? *)"
```

## Phase 5: Frontend & Delivery (1 hour)

### 1. CloudFront Distribution
- Origin: S3 bucket
- Enable compression
- Cache policies for static content

### 2. Simple Web Interface
**File: `web/index.html`**
- Display latest summaries
- Audio player for podcasts
- RSS feed links

## Phase 6: Testing & Deployment

### 1. Local Testing
```bash
# Test individual Lambda functions
sam local invoke IngestFunction --event test-event.json
```

### 2. Deploy Infrastructure
```bash
# Using SAM template
sam deploy --guided
```

## Quick Start Commands

Would you like me to:
1. **Start with Phase 1** - Set up AWS prerequisites?
2. **Create the Lambda functions** - Core processing logic?
3. **Build infrastructure templates** - SAM/CDK deployment files?
4. **Focus on a specific component** - Which interests you most?

## Estimated Timeline
- **MVP (basic functionality)**: 4-6 hours
- **Full featured**: 8-12 hours
- **Production ready**: 2-3 days

Let me know which phase you'd like to start with!