#!/bin/bash

# Load environment variables from .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Disable the AWS CLI pager to prevent it from opening an editor/less for every result
export AWS_PAGER=""

BUCKET_NAME=$S3_BUCKET_NAME

if [ -z "$BUCKET_NAME" ]; then
  echo "Error: S3_BUCKET_NAME is not set in .env"
  exit 1
fi


echo "Updating .mp4 files in s3://$BUCKET_NAME..."

aws s3 ls "s3://$BUCKET_NAME" --recursive | awk '{print substr($0, index($0, $4))}' | grep ".mp4" | while read -r line; do
  echo "Processing: $line"
  
  aws s3api copy-object \
    --bucket "$BUCKET_NAME" \
    --content-type "video/mp4" \
    --content-disposition "inline" \
    --copy-source "$BUCKET_NAME/$line" \
    --key "$line" \
    --metadata-directive "REPLACE"
done