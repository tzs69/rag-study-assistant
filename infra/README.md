# Infra (AWS SAM)

This folder contains the AWS infrastructure (SAM/CloudFormation) for the backend event-driven ingestion/deletion pipeline.

## Current Scope (SAM-managed)

- General purpose S3 bucket for raw docs / chunk artifacts
- S3 bucket notifications (`ObjectCreated:*`, `ObjectRemoved:*`) -> SQS
- Ingestion + deletion SQS queues and DLQs
- Queue policies allowing S3 to publish to SQS
- Lambda ingestion worker + deletion worker
- Lambda event source mappings (SQS -> Lambda)
- DynamoDB manifest table (`doc_id` keyed)
- S3 Vectors vector bucket + vector index
- IAM policies for S3 / SQS / DynamoDB / Bedrock / S3 Vectors worker access

## Handler Entrypoints (current)

The template currently deploys these handlers:

- `backend/src/indexing/workers/ingest_lambda_worker.py` -> `ingestion_handler`
- `backend/src/indexing/workers/delete_lambda_worker.py` -> `deletion_handler`

In SAM:

- `IngestionFunction` handler: `indexing.workers.ingest_lambda_worker.ingestion_handler`
- `DeletionFunction` handler: `indexing.workers.delete_lambda_worker.deletion_handler`

## Naming Convention

Most resource names are created as:

`<ProjectName>-<EnvironmentName>-<SuffixName>`

Examples:

- GP bucket: `${ProjectName}-${EnvironmentName}-${S3GeneralPurposeBucketName}`
- Vector bucket: `${ProjectName}-${EnvironmentName}-${S3VectorBucketName}`
- Vector index: `${ProjectName}-${EnvironmentName}-${S3VectorIndexName}`
- Queues / DLQs / Lambdas / DynamoDB table follow the same pattern

Because of this, `samconfig.toml` should store **suffix/base** values (for example `document-upload-sam`), not already-prefixed full names.

## Lambda Environment Variables (current)

SAM injects app runtime env vars into both Lambda workers, including:

- `S3_GP_BUCKET_NAME` (actual created GP bucket name)
- `S3_GP_RAW_PREFIX`
- `S3_GP_CHUNK_PREFIX`
- `S3_VECTOR_BUCKET_NAME` (actual created vector bucket name)
- `S3_VECTOR_INDEX_NAME` (actual created vector index name)
- `DYNAMODB_MANIFEST_TABLE_NAME` (actual created DynamoDB table name)
- `CHUNKING_MODEL_ID`
- `EMBEDDING_MODEL_ID`

## Event Flow (implemented infra)

1. App uploads a raw document to the GP S3 bucket under `raws/`
2. S3 emits `ObjectCreated:*`
3. S3 sends notification to ingestion SQS queue
4. Ingestion Lambda is invoked via SQS event source mapping
5. (To be implemented in handler) process document -> chunk -> embed -> upsert vectors -> write manifest
6. On delete (`ObjectRemoved:*`), S3 sends event to deletion queue
7. Deletion Lambda is invoked and performs cleanup (manifest + vectors/chunks)

## Local Workflow (Windows / SAM)

Validate:

```powershell
cd infra
sam validate -t template.yaml --lint
```

Build:

If `.aws-sam/` is locked (common on Windows/OneDrive), build outside the repo:

```powershell
sam build --build-dir C:\temp\rag-sam-build
```

Deploy:

```powershell
sam deploy --profile <your-profile>
```

If using external build dir:

```powershell
sam deploy --template-file C:\temp\rag-sam-build\template.yaml --profile <your-profile>
```

## Notes / Remaining Work

- Worker handler implementations are still stubs (`ingest_lambda_worker.py`, `delete_lambda_worker.py`)
- `infra/env/dev-params.example.txt` may need syncing if template parameter names change
- Consider adding `.aws-sam/` to `.gitignore` (generated build artifacts should not be committed)
- Consider explicit CloudWatch log group resources if you want stack deletion to remove logs too
- For destructive teardown behavior, ensure buckets/vector resources are empty before deleting the stack
