"""Dedicated A2A SDK adapter for Coordinator-to-specialist calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.types import CancelTaskRequest, Role, SendMessageRequest, TaskState
from a2a.utils.constants import TransportProtocol
from a2a.utils.errors import A2AError
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, ValidationError

from agents.coordinator.registry import RegisteredAgent
from packages.contracts import ArtifactEnvelope

RemoteErrorCode = Literal[
    "timeout",
    "transport_failure",
    "remote_task_failed",
    "invalid_artifact",
]


class RemoteCallError(RuntimeError):
    """Typed failure from one remote A2A execution."""

    def __init__(
        self,
        code: RemoteErrorCode,
        message: str,
        *,
        agent_id: str,
        remote_task_id: str | None = None,
    ) -> None:
        self.code = code
        self.agent_id = agent_id
        self.remote_task_id = remote_task_id
        super().__init__(message)


class RemoteTimeoutError(RemoteCallError):
    def __init__(self, *, agent_id: str, remote_task_id: str | None = None) -> None:
        super().__init__(
            "timeout",
            f"Remote agent {agent_id} exceeded its execution deadline.",
            agent_id=agent_id,
            remote_task_id=remote_task_id,
        )


class RemoteTransportError(RemoteCallError):
    def __init__(self, *, agent_id: str, remote_task_id: str | None = None) -> None:
        super().__init__(
            "transport_failure",
            f"Remote agent {agent_id} could not be reached over A2A.",
            agent_id=agent_id,
            remote_task_id=remote_task_id,
        )


@dataclass(frozen=True)
class RemoteTaskResult[PayloadT: BaseModel]:
    """Validated terminal artifact plus remote correlation identifiers."""

    agent_id: str
    remote_task_id: str
    remote_context_id: str
    artifact: ArtifactEnvelope[PayloadT]


RemoteTaskStartedHandler = Callable[[str], Awaitable[None]]


class A2AClientAdapter:
    """Execute one typed request through the official A2A SDK."""

    async def execute[PayloadT: BaseModel](
        self,
        *,
        agent: RegisteredAgent,
        request: BaseModel,
        artifact_name: str,
        payload_model: type[PayloadT],
        timeout_seconds: float,
        on_task_started: RemoteTaskStartedHandler | None = None,
    ) -> RemoteTaskResult[PayloadT]:
        if timeout_seconds <= 0:
            raise ValueError("Remote execution timeout must be positive.")
        http_client = httpx.AsyncClient(timeout=None)
        client = None
        started_task_id: str | None = None

        async def report_task_started(remote_task_id: str) -> None:
            nonlocal started_task_id
            started_task_id = remote_task_id
            if on_task_started is not None:
                await on_task_started(remote_task_id)

        try:
            client = ClientFactory(
                ClientConfig(
                    streaming=True,
                    httpx_client=http_client,
                    supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
                )
            ).create(agent.card)
            async with asyncio.timeout(timeout_seconds):
                return await self._consume_stream(
                    client,
                    agent=agent,
                    request=request,
                    artifact_name=artifact_name,
                    payload_model=payload_model,
                    on_task_started=report_task_started,
                )
        except RemoteCallError:
            raise
        except TimeoutError as error:
            raise RemoteTimeoutError(
                agent_id=agent.agent_id, remote_task_id=started_task_id
            ) from error
        except (A2AError, httpx.HTTPError, OSError, ValueError) as error:
            raise RemoteTransportError(
                agent_id=agent.agent_id, remote_task_id=started_task_id
            ) from error
        finally:
            if client is not None:
                with suppress(Exception):
                    await client.close()
            elif not http_client.is_closed:
                await http_client.aclose()

    async def cancel(
        self,
        *,
        agent: RegisteredAgent,
        remote_task_id: str,
        timeout_seconds: float,
    ) -> None:
        """Request cancellation of one known remote A2A task."""
        if timeout_seconds <= 0:
            raise ValueError("Remote cancellation timeout must be positive.")
        if not remote_task_id.strip():
            raise ValueError("Remote task ID cannot be blank.")
        http_client = httpx.AsyncClient(timeout=None)
        client = None
        try:
            client = ClientFactory(
                ClientConfig(
                    streaming=True,
                    httpx_client=http_client,
                    supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
                )
            ).create(agent.card)
            async with asyncio.timeout(timeout_seconds):
                cancelled_task = await client.cancel_task(
                    CancelTaskRequest(id=remote_task_id)
                )
            if cancelled_task.status.state != TaskState.TASK_STATE_CANCELED:
                raise RemoteCallError(
                    "remote_task_failed",
                    f"Remote agent {agent.agent_id} did not cancel task {remote_task_id}.",
                    agent_id=agent.agent_id,
                    remote_task_id=remote_task_id,
                )
        except RemoteCallError:
            raise
        except TimeoutError as error:
            raise RemoteTimeoutError(
                agent_id=agent.agent_id, remote_task_id=remote_task_id
            ) from error
        except (A2AError, httpx.HTTPError, OSError, ValueError) as error:
            raise RemoteTransportError(
                agent_id=agent.agent_id, remote_task_id=remote_task_id
            ) from error
        finally:
            if client is not None:
                with suppress(Exception):
                    await client.close()
            elif not http_client.is_closed:
                await http_client.aclose()

    async def _consume_stream[PayloadT: BaseModel](
        self,
        client: Any,
        *,
        agent: RegisteredAgent,
        request: BaseModel,
        artifact_name: str,
        payload_model: type[PayloadT],
        on_task_started: RemoteTaskStartedHandler | None = None,
    ) -> RemoteTaskResult[PayloadT]:
        remote_task_id: str | None = None
        remote_context_id: str | None = None
        artifact: ArtifactEnvelope[PayloadT] | None = None
        completed = False
        task_started_notified = False
        send_request = SendMessageRequest(
            message=new_text_message(
                request.model_dump_json(),
                media_type="application/json",
                role=Role.ROLE_USER,
            )
        )
        async for response in client.send_message(send_request):
            if response.HasField("task"):
                remote_task_id = response.task.id
                remote_context_id = response.task.context_id
                if not task_started_notified and on_task_started is not None:
                    await on_task_started(remote_task_id)
                    task_started_notified = True
                continue
            if response.HasField("artifact_update"):
                update = response.artifact_update
                remote_task_id = remote_task_id or update.task_id
                if update.artifact.name == artifact_name:
                    if artifact is not None:
                        raise self._invalid_artifact(agent, remote_task_id, "duplicate artifact")
                    try:
                        if not update.last_chunk:
                            raise ValueError("final artifact was not marked as the last chunk")
                        part = update.artifact.parts[0]
                        if part.WhichOneof("content") != "data":
                            raise ValueError("final artifact did not contain structured data")
                        data = MessageToDict(part.data)
                        artifact = ArtifactEnvelope[payload_model].model_validate(data)
                    except (ValidationError, IndexError, ValueError) as error:
                        raise self._invalid_artifact(
                            agent, remote_task_id, "artifact schema mismatch"
                        ) from error
                continue
            if response.HasField("status_update"):
                update = response.status_update
                remote_task_id = remote_task_id or update.task_id
                state = update.status.state
                if state == TaskState.TASK_STATE_COMPLETED:
                    completed = True
                elif state in {
                    TaskState.TASK_STATE_FAILED,
                    TaskState.TASK_STATE_REJECTED,
                    TaskState.TASK_STATE_CANCELED,
                }:
                    detail = (
                        get_message_text(update.status.message)
                        if update.status.HasField("message")
                        else TaskState.Name(state)
                    )
                    raise RemoteCallError(
                        "remote_task_failed",
                        f"Remote agent {agent.agent_id} ended unsuccessfully: {detail}",
                        agent_id=agent.agent_id,
                        remote_task_id=remote_task_id,
                    )

        if remote_task_id is None or remote_context_id is None:
            raise self._invalid_artifact(agent, remote_task_id, "missing task identifiers")
        if not completed or artifact is None:
            raise self._invalid_artifact(agent, remote_task_id, "missing completed artifact")
        if artifact.provenance.remote_task_id != remote_task_id:
            raise self._invalid_artifact(agent, remote_task_id, "provenance task mismatch")
        return RemoteTaskResult(
            agent_id=agent.agent_id,
            remote_task_id=remote_task_id,
            remote_context_id=remote_context_id,
            artifact=artifact,
        )

    @staticmethod
    def _invalid_artifact(
        agent: RegisteredAgent,
        remote_task_id: str | None,
        detail: str,
    ) -> RemoteCallError:
        return RemoteCallError(
            "invalid_artifact",
            f"Remote agent {agent.agent_id} returned an invalid artifact ({detail}).",
            agent_id=agent.agent_id,
            remote_task_id=remote_task_id,
        )
