"""Optional Cloud Tasks dispatch for async worker jobs."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings


@dataclass(frozen=True)
class TaskDispatch:
    dispatched: bool
    task_name: str = ""
    reason: str = ""


def dispatch_job(settings: Settings, *, job_id: str) -> TaskDispatch:
    """Create a Cloud Task that asks the worker to run one durable job.

    Local/test environments intentionally omit Cloud Tasks settings; in that case the
    durable job row is still created and can be run by the worker CLI or direct worker
    endpoint. Cloud Run dev sets all three values and gets HTTP/OIDC dispatch.
    """
    task_queue = getattr(settings, "task_queue", "")
    raw_worker_url = getattr(settings, "worker_url", "")
    oidc_service_account = getattr(settings, "task_oidc_service_account", "")
    if not task_queue or not raw_worker_url:
        return TaskDispatch(dispatched=False, reason="cloud tasks not configured")

    from google.cloud import tasks_v2  # type: ignore[import-not-found]

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(settings.project_id, settings.region, task_queue)
    worker_url = raw_worker_url.rstrip("/")
    http_request = tasks_v2.HttpRequest(
        http_method=tasks_v2.HttpMethod.POST,
        url=f"{worker_url}/jobs/{job_id}/run",
    )
    if oidc_service_account:
        http_request.oidc_token = tasks_v2.OidcToken(
            service_account_email=oidc_service_account,
            audience=worker_url,
        )
    task = tasks_v2.Task(http_request=http_request)
    response = client.create_task(parent=parent, task=task)
    return TaskDispatch(dispatched=True, task_name=response.name)
