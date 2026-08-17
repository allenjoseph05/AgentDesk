"""Narrow A2A task boundary used by the AG-UI cancellation spike."""

from typing import Protocol


class ActiveA2ATask(Protocol):
    """One remote task whose lifetime is owned by an AG-UI run."""

    @property
    def remote_task_id(self) -> str:
        """Return the remote task identifier exposed in projected state."""

    async def wait(self) -> None:
        """Wait until the remote task reaches a terminal state."""

    async def cancel(self) -> None:
        """Send cancellation to the active remote task."""

    async def aclose(self) -> None:
        """Release clients and stream resources held by the task."""


class A2ATaskFactory(Protocol):
    """Start the single remote task exercised by the protocol spike."""

    async def start(self, question: str) -> ActiveA2ATask:
        """Start a task for the accepted research question."""
