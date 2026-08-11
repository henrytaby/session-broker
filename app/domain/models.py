from __future__ import annotations

from pydantic import BaseModel


class Cookie(BaseModel):
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float = -1
    httpOnly: bool = False
    secure: bool = False
    sameSite: str = "None"


class Origin(BaseModel):
    origin: str
    localStorage: list[dict] = []


class StorageState(BaseModel):
    cookies: list[Cookie] = []
    origins: list[Origin] = []


class Fingerprint(BaseModel):
    user_agent: str
    platform: str
    languages: list[str]
    timezone: str
    locale: str
    screen_width: int
    screen_height: int
    color_depth: int
    hardware_concurrency: int
    device_memory: int
    webgl_vendor: str
    webgl_renderer: str
    sec_ch_ua: str


class InstanceInfo(BaseModel):
    name: str
    chrome_port: int
    alive: bool


class LockResult(BaseModel):
    locked: bool
    client: str | None = None
    holder: str | None = None
    renewed: bool = False
    remaining_sec: int = 0


class UnlockResult(BaseModel):
    unlocked: bool
    holder: str | None = None


class ChatMessage(BaseModel):
    prompt: str


class ChatChunk(BaseModel):
    type: str  # "chunk" | "complete" | "error"
    text: str | None = None
    message: str | None = None


__all__ = [
    "Cookie",
    "Origin",
    "StorageState",
    "Fingerprint",
    "InstanceInfo",
    "LockResult",
    "UnlockResult",
    "ChatMessage",
    "ChatChunk",
]
