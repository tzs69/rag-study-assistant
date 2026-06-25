# Infra (AWS SAM)

## Scope

This folder contains the AWS infrastructure (SAM/CloudFormation) for the backend event-driven indexing lifecycle.

It does not directly provision the frontend UI or retrieval-related application service runtimes, which are containerized for local/dev with Docker Compose at the repo root. However, the AWS resources provisioned here are still required by those application services at runtime.

<br/>

## Provisioned Resources

- General purpose S3 bucket for raw docs / chunk artifacts
- S3 bucket notifications (`ObjectCreated:*`, `ObjectRemoved:*`) -> SQS
- Ingestion, deletion, and BM25 update SQS queues and DLQs
- Queue policies allowing S3 to publish to SQS
- Lambda ingestion worker, deletion worker, and BM25 update worker
- Lambda event source mappings (SQS -> Lambda)
- DynamoDB manifest table (`doc_id` keyed)
- DynamoDB corpus change table (`pk + change_id` keyed change stream)
- DynamoDB domain lexicon tables:
  - `collection_term_stats` (`term` keyed collection stats)
  - `doc_term_stats` (`doc_id + term` keyed doc-level term frequencies)
- S3 Vectors vector bucket + vector index
- IAM policies for S3 / SQS / DynamoDB / Bedrock / S3 Vectors worker access

<br/>


## Lambda Worker Sources

| SAM function | Source file |
| --- | --- |
| `IngestionFunction` | `backend/src/indexing/workers/ingest_lambda_worker.py` |
| `DeletionFunction` | `backend/src/indexing/workers/delete_lambda_worker.py` |
| `BM25UpdateFunction` | `backend/src/indexing/workers/bm25_update_lambda_worker.py` |

<br/>

## Lambda Environment Variables

SAM injects app runtime env vars into both Lambda workers, including:

- `S3_GP_BUCKET_NAME`
- `S3_GP_RAW_PREFIX`
- `S3_GP_CHUNK_PREFIX`
- `S3_VECTOR_BUCKET_NAME`
- `S3_VECTOR_INDEX_NAME`
- `DYNAMODB_MANIFEST_TABLE_NAME`
- `DYNAMODB_CORPUS_CHANGE_TABLE_NAME`
- `DYNAMODB_COLLECTION_TERM_STATS_TABLE_NAME`
- `DYNAMODB_DOC_TERM_STATS_TABLE_NAME`
- `CHUNKING_MODEL_ID`
- `EMBEDDING_MODEL_ID`
- `SQS_BM25_UPDATE_QUEUE_URL`
- `BM25_POINTER_KEY`
- `BM25_SNAPSHOT_KEY`

<br/>

## Naming Convention

Inside template file, most resource names are created as:

`<ProjectName>-<EnvironmentName>-<SuffixName>`

Examples:

- GP bucket: `${ProjectName}-${EnvironmentName}-${S3GeneralPurposeBucketName}`
- Vector bucket: `${ProjectName}-${EnvironmentName}-${S3VectorBucketName}`
- Vector index: `${ProjectName}-${EnvironmentName}-${S3VectorIndexName}`
- Queues / DLQs / Lambdas / DynamoDB table follow the same pattern

Because of this, `samconfig.toml` stores **suffix/base** values (for example `document-upload-sam`), not already-prefixed full names.

<br/>

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

<br/>

## Additional Notes

- If stack replacement is needed, clean up stack-associated managed artifact bucket in CloudFormation before redeploy.
- For destructive teardown behavior, ensure S3/vector resources are empty before stack deletion.

<br/>

## Source-of-Truth Files

- `infra/template.yaml`