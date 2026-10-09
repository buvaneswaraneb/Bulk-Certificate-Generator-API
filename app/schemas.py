from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class RecipientInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    course: str = Field(min_length=1, max_length=180)
    issue_date: date

    @field_validator("name", "course")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class CreateJobRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=160)
    event_name: str = Field(min_length=1, max_length=160)
    recipients: list[RecipientInput] = Field(min_length=1, max_length=1000)

    @field_validator("organization_name", "event_name")
    @classmethod
    def shared_text_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def unique_recipients(self) -> "CreateJobRequest":
        identities = [(r.name.casefold(), r.course.casefold(), r.issue_date) for r in self.recipients]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate recipients are not allowed")
        return self


class CertificateStatus(BaseModel):
    id: str
    recipient_name: str
    course_name: str
    issue_date: date
    status: Literal["pending", "processing", "completed", "failed"]
    error_message: str | None = None


class JobResponse(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "completed_with_errors", "failed"]
    organization_name: str
    event_name: str
    total_count: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    certificates: list[CertificateStatus]
