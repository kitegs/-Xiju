"""API serialization shared by routes and execution; never imports the composition root."""
from .models import Report, ReportVersion, GeneratedArtifact, ChatMessage
from .schemas import ReportOut, ReportVersionOut, ReportDocument, ArtifactOut, ChatMessageOut
from .services import assess_report_quality

def as_report(item: Report) -> ReportOut:
    document = ReportDocument.model_validate(item.document)
    document.quality = assess_report_quality(document)
    return ReportOut(
        deleted_at=item.deleted_at,
        id=item.id, workspace_id=item.workspace_id, project_id=item.project_id,
        dataset_id=item.dataset_id, dataset_version_id=item.dataset_version_id, run_id=item.run_id,
        title=item.title, document=document, created_at=item.created_at, updated_at=item.updated_at,
    )


def as_report_version(item: ReportVersion) -> ReportVersionOut:
    return ReportVersionOut(id=item.id, report_id=item.report_id, title=item.title, document=item.document, created_at=item.created_at)


def as_artifact(item: GeneratedArtifact) -> ArtifactOut:
    return ArtifactOut(
        id=item.id, workspace_id=item.workspace_id, report_id=item.report_id, kind=item.kind,
        name=item.name, metadata=item.metadata_json or {}, download_url=f"/api/v1/artifacts/{item.id}/download",
        created_at=item.created_at,
    )


def as_message(item: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(id=item.id, conversation_id=item.conversation_id, role=item.role, content=item.content, message_meta=item.message_meta or {}, created_at=item.created_at)
