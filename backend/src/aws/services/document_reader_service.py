from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

from botocore.exceptions import ClientError, ParamValidationError
from ..clients.s3_client import S3ClientModular

from pypdf import PdfReader
from docx import Document as DocxDocument


class UnsupportedDocumentTypeError(ValueError):
    pass

class S3ExpiredTokenError(PermissionError):
    pass


@dataclass(frozen=True)
class DocumentText:
    doc_id: str
    bucket: str
    content_type: str
    text: str


class DocumentReaderService:
    """
    S3 Bucket document reading service
    """

    def __init__(self, bucket_name: str) -> None:
        self.bucket = bucket_name
        self.s3 = S3ClientModular(bucket_name, vectors=False)

    def read_document_from_s3(self, doc_id: str) -> DocumentText:
        """
            Reads a document within s3 bucket and DocumentText payload to be chunked
            Valid file types:
             1) .pdf
             2) .docx
             3) .txt
             4) .md
        """
        if not doc_id:
            raise ValueError("doc_id is required")

        try:
            response = self.s3.client.get_object(Bucket=self.bucket, Key=doc_id)

            # Extract raw file bytes from response
            raw_bytes = response["Body"].read()
            text = self._extract_text(doc_id=doc_id, raw_bytes=raw_bytes)

            # Build DocumentText object to be passed as input to chunking service
            content_type = response.get("ContentType", "application/octet-stream")
            return DocumentText(
                doc_id=doc_id,
                bucket=self.bucket,
                content_type=content_type,
                text=self._normalize_text(text),
            )
        
        except ParamValidationError as e:
            raise ValueError(f"Invalid parameters: (Key={doc_id})") from e
        
        except ClientError as e:

            error_code = e.response.get("Error", {}).get("Code", "")
            
            if error_code == "ExpiredToken":
                raise S3ExpiredTokenError(
                    f"S3 token expired while reading bucket='{self.bucket}', key='{doc_id}'"
                ) from e
            raise


    def _extract_text(self, doc_id: str, raw_bytes: bytes) -> str:
        """
        Dispatch raw file bytes to the appropriate text extractor based on the document file extension
        """
        suffix = PurePosixPath(doc_id).suffix.lower()

        if suffix == ".pdf":
            return self._read_pdf_bytes(raw_bytes)
        if suffix == ".docx":
            return self._read_docx_bytes(raw_bytes)
        if suffix in {".txt", ".md"}:
            return raw_bytes.decode("utf-8", errors="replace")

        raise UnsupportedDocumentTypeError(f"Unsupported file type: {suffix or '<none>'}")



    @staticmethod
    def _read_pdf_bytes(raw_bytes: bytes) -> str:
        """Helper function to read and parse .pdf files"""
        reader = PdfReader(BytesIO(raw_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    @staticmethod
    def _read_docx_bytes(raw_bytes: bytes) -> str:
        """Helper function to read and parse .docx files"""
        if DocxDocument is None:
            raise RuntimeError("python-docx is required to read DOCX files")

        doc = DocxDocument(BytesIO(raw_bytes))
        return "\n".join(paragraph.text for paragraph in doc.paragraphs)

    @staticmethod
    def _normalize_text(text: str) -> str:
        """"""
        return " ".join((text or "").split())
