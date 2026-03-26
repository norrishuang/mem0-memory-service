# Vector Stores

mem0 Memory Service supports two vector store backends. Switch between them with the `VECTOR_STORE` environment variable.

## OpenSearch (Default)

OpenSearch is the default vector engine. Requires a cluster with the k-NN plugin enabled (2.x or 3.x).

```env
VECTOR_STORE=opensearch
OPENSEARCH_HOST=your-opensearch-host.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=your-password
OPENSEARCH_USE_SSL=true
```

## AWS S3 Vectors

[Amazon S3 Vectors](https://aws.amazon.com/s3/features/vectors/) is a cost-optimized vector storage service from AWS with S3-level elasticity and durability, supporting sub-second query performance.

### Configuration

```env
VECTOR_STORE=s3vectors
S3VECTORS_BUCKET_NAME=your-bucket-name
S3VECTORS_INDEX_NAME=mem0
AWS_REGION=us-east-1
```

### Required IAM Permissions

Least-privilege policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3vectors:CreateIndex",
        "s3vectors:GetIndex",
        "s3vectors:DeleteIndex",
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors",
        "s3vectors:ListVectors"
      ],
      "Resource": "arn:aws:s3vectors:*:*:vector-bucket/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:CreateBucket",
      "Resource": "arn:aws:s3:::your-bucket-name"
    }
  ]
}
```

::: tip References
- [S3 Vectors Security & Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-security-access.html)
- [mem0 S3 Vectors Config](https://docs.mem0.ai/components/vectordbs/dbs/s3_vectors)
:::
