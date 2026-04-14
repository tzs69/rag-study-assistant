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
- DynamoDB corpus change table (`pk + change_id` keyed change stream)
- DynamoDB domain lexicon tables:
  - `collection_term_stats` (`term` keyed collection stats)
  - `doc_term_stats` (`doc_id + term` keyed doc-level term frequencies)
- S3 Vectors vector bucket + vector index
- IAM policies for S3 / SQS / DynamoDB / Bedrock / S3 Vectors worker access

## Handler Entrypoints

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

Because of this, `samconfig.toml` stores **suffix/base** values (for example `document-upload-sam`), not already-prefixed full names.

## Lambda Environment Variables (current)

SAM injects app runtime env vars into both Lambda workers, including:

- `S3_GP_BUCKET_NAME` (actual created GP bucket name)
- `S3_GP_RAW_PREFIX`
- `S3_GP_CHUNK_PREFIX`
- `S3_VECTOR_BUCKET_NAME` (actual created vector bucket name)
- `S3_VECTOR_INDEX_NAME` (actual created vector index name)
- `DYNAMODB_MANIFEST_TABLE_NAME` (actual created DynamoDB table name)
- `DYNAMODB_CORPUS_CHANGE_TABLE_NAME` (actual created DynamoDB table name)
- `DYNAMODB_COLLECTION_TERM_STATS_TABLE_NAME` (actual created DynamoDB table name)
- `DYNAMODB_DOC_TERM_STATS_TABLE_NAME` (actual created DynamoDB table name)
- `CHUNKING_MODEL_ID`
- `EMBEDDING_MODEL_ID`

## Event Flow (implemented infra)

1. App uploads a raw document to the GP S3 bucket under `raws/`
2. S3 emits `ObjectCreated:*`
3. S3 sends notification to ingestion SQS queue
4. Ingestion Lambda is invoked via SQS event source mapping
5. Ingestion handler processes document -> chunk -> embed -> upsert vectors -> update manifest -> append corpus change record
6. On delete (`ObjectRemoved:*`), S3 sends event to deletion queue
7. Deletion handler performs cleanup (manifest + vectors/chunks) and appends corpus change record

## Local Workflow (Windows / SAM)

Validate:

```powershell
cd infra
sam validate -t template.yaml --lint
```

To build artifacts (before deploy):

```powershell
# First time
sam build -t template.yaml

# Subsequent iterations (delete previous build artifacts, then rebuild)
Remove-Item .aws-sam -Recurse -Force
sam build -t template.yaml
```

To deploy the SAM:

```powershell
# First time
sam deploy --profile <aws-profile>
```

```powershell
# Subsequent iterations
sam deploy --guided --profile <aws-profile> --template-file .aws-sam/build/template.yaml --config-file <absolute-path-to>\infra\samconfig.toml
```

Notes:
- `Remove-Item .aws-sam -Recurse -Force` must run from the `infra/` directory.
- If PowerShell blocks folder removal due to lock/permissions, close any process using `.aws-sam/` and retry.
- Replace `<aws-profile>` and `<absolute-path-to>` with values from your local environment.

## Notes / Remaining Work

- Keep `infra/env/dev-params.example.txt` in sync whenever template parameter names change.
- Keep `samconfig.toml` aligned with current deploy flags/profile and template path usage.
- If stack replacement is needed, clean up stack-associated managed artifact bucket in CloudFormation before redeploy.
- For destructive teardown behavior, ensure S3/vector resources are empty before stack deletion.
