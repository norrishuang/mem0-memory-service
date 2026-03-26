# 向量存储

mem0 Memory Service 支持两种向量存储后端。通过 `VECTOR_STORE` 环境变量进行切换。

## OpenSearch（默认）

OpenSearch 是默认的向量引擎。需要启用 k-NN 插件的集群（2.x 或 3.x）。

```env
VECTOR_STORE=opensearch
OPENSEARCH_HOST=your-opensearch-host.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=your-password
OPENSEARCH_USE_SSL=true
```

## AWS S3 Vectors

[Amazon S3 Vectors](https://aws.amazon.com/s3/features/vectors/) 是 AWS 推出的低成本向量存储服务，具备 S3 级别的弹性和持久性，支持亚秒级查询性能。

### 配置

```env
VECTOR_STORE=s3vectors
S3VECTORS_BUCKET_NAME=your-bucket-name
S3VECTORS_INDEX_NAME=mem0
AWS_REGION=us-east-1
```

### 所需 IAM 权限

最小权限策略：

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

::: tip 参考资料
- [S3 Vectors 安全与访问控制](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-security-access.html)
- [mem0 S3 Vectors 配置](https://docs.mem0.ai/components/vectordbs/dbs/s3_vectors)
:::
