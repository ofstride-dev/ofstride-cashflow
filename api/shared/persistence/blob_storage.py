import os
import uuid
import logging
from azure.storage.blob import BlobServiceClient

def upload_resume(file_bytes: bytes, filename: str, container_name: str | None = None) -> str:
    connection_string = (
        os.environ.get("CAREERS_BLOB_CONNECTION_STRING")
        or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        or os.environ.get("AzureWebJobsStorage")
    )
    if not connection_string:
        raise ValueError("Blob storage connection string is not set")

    resolved_container = (container_name or os.environ.get("CAREERS_BLOB_CONTAINER") or "resumes").strip().lower()
    if not resolved_container:
        resolved_container = "resumes"

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service.get_container_client(resolved_container)
    
    if not container_client.exists():
        container_client.create_container()

    safe_filename = os.path.basename((filename or "resume").strip()) or "resume"
    unique_blob_name = f"{uuid.uuid4()}-{safe_filename}"
    blob_client = container_client.get_blob_client(unique_blob_name)
    blob_client.upload_blob(file_bytes, overwrite=True)

    if not blob_client.exists():
        raise RuntimeError(f"Blob upload verification failed for container '{resolved_container}'")

    logging.info("Resume uploaded to blob container '%s' as '%s'", resolved_container, unique_blob_name)
    
    return blob_client.url