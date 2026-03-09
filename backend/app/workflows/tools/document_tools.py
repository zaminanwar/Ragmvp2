"""Document workflow tools — parse and extract content from files."""

from __future__ import annotations

import base64

import structlog

from app.rag.chunking.document_parser import DocumentParser
from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput

logger = structlog.get_logger(__name__)


class DocumentParseTool(BaseTool):
    name = "document.parse"
    description = "Parse a document (PDF, DOCX, etc.) into plain text."
    input_schema = {
        "type": "object",
        "properties": {
            "file_content": {"type": "string", "description": "Base64-encoded file bytes"},
            "filename": {"type": "string", "description": "Original filename with extension"},
        },
        "required": ["file_content", "filename"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "char_count": {"type": "integer"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            file_bytes = base64.b64decode(params["file_content"])
            parser = DocumentParser()
            text = parser.parse(file_bytes, params["filename"])
            return ToolOutput(
                success=True,
                data={"text": text, "char_count": len(text)},
            )
        except Exception as e:
            logger.exception("document_parse_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class DocumentExtractTool(BaseTool):
    name = "document.extract"
    description = "Extract structured sections or blocks from parsed text."
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Parsed document text"},
            "pattern": {"type": "string", "description": "Extraction pattern (e.g. 'sections', 'requirements', 'tables')"},
        },
        "required": ["text"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "blocks": {"type": "array"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        text = params["text"]
        pattern = params.get("pattern", "sections")

        try:
            blocks = []
            if pattern == "sections":
                # Split by markdown-style headings or numbered sections
                import re
                parts = re.split(r'\n(?=#{1,4}\s|(?:\d+\.)+\s)', text)
                for i, part in enumerate(parts):
                    part = part.strip()
                    if part:
                        lines = part.split("\n", 1)
                        blocks.append({
                            "index": i,
                            "heading": lines[0].strip().lstrip("# "),
                            "content": lines[1].strip() if len(lines) > 1 else "",
                        })
            elif pattern == "requirements":
                # Look for requirement-like patterns (REQ-xxx, SHALL, MUST)
                import re
                req_pattern = re.compile(
                    r'((?:REQ|RQ|R)-?\d+[^\n]*\n(?:.*?(?=(?:REQ|RQ|R)-?\d+|\Z)))',
                    re.DOTALL | re.IGNORECASE,
                )
                for i, match in enumerate(req_pattern.finditer(text)):
                    blocks.append({
                        "index": i,
                        "content": match.group(0).strip(),
                    })
                # Fallback: split by lines containing SHALL/MUST
                if not blocks:
                    for i, line in enumerate(text.split("\n")):
                        if any(kw in line.upper() for kw in ("SHALL", "MUST", "REQUIRED")):
                            blocks.append({"index": i, "content": line.strip()})
            else:
                # Default: split by double newlines
                for i, chunk in enumerate(text.split("\n\n")):
                    chunk = chunk.strip()
                    if chunk:
                        blocks.append({"index": i, "content": chunk})

            return ToolOutput(
                success=True,
                data={"blocks": blocks, "count": len(blocks)},
            )
        except Exception as e:
            logger.exception("document_extract_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))
