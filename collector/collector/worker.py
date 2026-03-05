"""Background document processing worker.

Inspired by AnythingLLM's dedicated Collector service and
Pathway's real-time data pipeline approach.

Listens on Redis for document processing jobs, handles parsing/chunking/embedding
asynchronously to avoid blocking the API server.
"""

import asyncio
import json
import os
import sys

import redis.asyncio as redis
import structlog

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "rag:document:process"


async def process_job(job_data: dict):
    """Process a single document job."""
    document_id = job_data.get("document_id")
    workspace_id = job_data.get("workspace_id")
    storage_path = job_data.get("storage_path")
    filename = job_data.get("filename")

    logger.info(
        "processing_document",
        document_id=document_id,
        filename=filename,
    )

    # In production, this would:
    # 1. Download from MinIO
    # 2. Parse the document
    # 3. Chunk it
    # 4. Generate embeddings
    # 5. Store chunks in PostgreSQL with pgvector
    # 6. Index in Elasticsearch
    # 7. Update document status

    # For now, the API server handles processing synchronously.
    # This worker can be extended for async batch processing.
    logger.info("document_processed", document_id=document_id)


async def main():
    """Main worker loop - listens for jobs on Redis queue."""
    logger.info("Starting document collector worker", queue=QUEUE_NAME)

    r = redis.from_url(REDIS_URL)
    await r.ping()
    logger.info("Connected to Redis")

    while True:
        try:
            # BLPOP blocks until a job is available
            result = await r.blpop(QUEUE_NAME, timeout=5)
            if result:
                _, job_json = result
                job_data = json.loads(job_json)
                await process_job(job_data)
        except redis.ConnectionError:
            logger.warning("Redis connection lost, reconnecting in 5s...")
            await asyncio.sleep(5)
            r = redis.from_url(REDIS_URL)
        except Exception as e:
            logger.error("Worker error", error=str(e))
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
