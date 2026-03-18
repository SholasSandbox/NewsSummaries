# Remote state stored in S3 with DynamoDB locking.
#
# Before first use, create the backend resources with:
#   aws s3api create-bucket \
#     --bucket <your-tf-state-bucket> \
#     --region us-east-1
#   aws s3api put-bucket-versioning \
#     --bucket <your-tf-state-bucket> \
#     --versioning-configuration Status=Enabled
#   aws dynamodb create-table \
#     --table-name terraform-state-lock \
#     --attribute-definitions AttributeName=LockID,AttributeType=S \
#     --key-schema AttributeName=LockID,KeyType=HASH \
#     --billing-mode PAY_PER_REQUEST \
#     --region us-east-1
#
# Then replace the placeholder values below and run `terraform init`.

terraform {
  backend "s3" {
    # Replace with your actual state bucket name (must be globally unique).
    bucket         = "news-summaries-tf-state-ACCOUNT_ID"
    key            = "news-summaries/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}
