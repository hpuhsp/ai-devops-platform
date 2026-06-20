"""Notification provider interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class NotifyMessage:
    title: str
    content: str
    message_type: str   # code_review_result/test_generation_result/auto_merge/pipeline_status
    data: dict = None
    color: str = "blue"  # blue/green/red/yellow


class NotificationProvider(ABC):
    """All notification adapters implement this interface."""

    @abstractmethod
    async def send(self, message: NotifyMessage) -> bool:
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        pass
