"""Requirements Analysis & Compliance Check — first workflow template.

This module provides a function that returns the workflow definition JSON
for the 7-step requirements compliance workflow.
"""

TEMPLATE_NAME = "Requirements Analysis & Compliance Check"
TEMPLATE_SLUG = "requirements-compliance"
TEMPLATE_DESCRIPTION = (
    "End-to-end workflow: fetch Polarion schema, parse & classify requirements PDF, "
    "import to Polarion, wait for human review, export canonical requirements, "
    "run RAG compliance check, write results back, and generate compliance matrix."
)


def get_definition() -> dict:
    """Return the workflow definition JSON for the requirements compliance workflow."""
    return {
        "version": "1.0",
        "inputs": {
            "requirements_pdf": {
                "type": "file",
                "description": "Customer requirements PDF",
                "required": True,
            },
            "corpus_workspace_id": {
                "type": "string",
                "description": "Workspace with uploaded corpus documents",
                "required": True,
            },
            "polarion_project_id": {
                "type": "string",
                "description": "Polarion project to import into",
                "required": True,
            },
        },
        "outputs": {
            "compliance_report": {
                "type": "file",
                "from": "$steps.generate_matrix.output.file_url",
            },
        },
        "steps": [
            {
                "id": "fetch_schema",
                "name": "Fetch Polarion Schema",
                "tool": "alm.get_schema",
                "inputs": {
                    "project_id": "$inputs.polarion_project_id",
                },
                "outputs": ["schema"],
                "timeout_seconds": 30,
            },
            {
                "id": "parse_classify",
                "name": "Parse & Classify Requirements",
                "tool": "llm.classify",
                "inputs": {
                    "file": "$inputs.requirements_pdf",
                    "schema": "$steps.fetch_schema.output.schema",
                    "instructions": (
                        "Parse the requirements document and classify each requirement block "
                        "using the provided ALM schema. For each block, determine the work-item "
                        "type, extract the title and description, and map any relevant custom "
                        "fields. Return an array of work items ready for ALM import."
                    ),
                },
                "outputs": ["workitems"],
                "timeout_seconds": 600,
            },
            {
                "id": "import_to_polarion",
                "name": "Import to Polarion",
                "tool": "alm.create_workitems",
                "inputs": {
                    "project_id": "$inputs.polarion_project_id",
                    "workitems": "$steps.parse_classify.output.workitems",
                },
                "outputs": ["polarion_ids"],
                "checkpoint": {
                    "type": "approval",
                    "message": "Review imported requirements in Polarion before compliance check",
                    "required_role": "manager",
                    "show_data": "$steps.parse_classify.output.workitems",
                },
                "retry": {"max_attempts": 3, "backoff_seconds": 10},
            },
            {
                "id": "export_from_polarion",
                "name": "Export from Polarion (Source of Truth)",
                "tool": "alm.get_workitems",
                "inputs": {
                    "project_id": "$inputs.polarion_project_id",
                    "module_id": "$steps.import_to_polarion.output.module_id",
                },
                "outputs": ["canonical_requirements"],
            },
            {
                "id": "compliance_check",
                "name": "Check Compliance via RAG",
                "tool": "rag.batch_query",
                "inputs": {
                    "queries": "$steps.export_from_polarion.output.canonical_requirements",
                    "workspace_id": "$inputs.corpus_workspace_id",
                    "system_prompt": (
                        "Determine if this requirement is met by the corpus. "
                        "Respond with: status (Met/Partially Met/Not Met/Insufficient Evidence), "
                        "confidence (0-1), evidence (specific excerpts), gaps (what is missing), "
                        "suggested_action."
                    ),
                },
                "outputs": ["compliance_results"],
                "loop": {
                    "over": "$steps.export_from_polarion.output.canonical_requirements",
                    "as": "requirement",
                    "batch_size": 5,
                    "concurrency": 3,
                },
                "timeout_seconds": 1800,
            },
            {
                "id": "write_back",
                "name": "Write Compliance Results to Polarion",
                "tool": "alm.update_workitems",
                "inputs": {
                    "project_id": "$inputs.polarion_project_id",
                    "updates": "$steps.compliance_check.output.compliance_results",
                },
                "outputs": ["updated_count"],
                "retry": {"max_attempts": 3, "backoff_seconds": 10},
            },
            {
                "id": "generate_matrix",
                "name": "Generate Compliance Matrix",
                "tool": "export.excel",
                "inputs": {
                    "requirements": "$steps.export_from_polarion.output.canonical_requirements",
                    "compliance": "$steps.compliance_check.output.compliance_results",
                    "template": "compliance_matrix",
                    "filename": "compliance_report.xlsx",
                },
                "outputs": ["file_url", "file_path"],
            },
        ],
        "error_policy": {
            "default": "fail",
            "on_step_failure": {
                "import_to_polarion": "pause",
                "write_back": "pause",
            },
        },
    }
