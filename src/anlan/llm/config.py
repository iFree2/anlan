"""Fixed provider configuration, independent of workflow composition."""
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr
    model: Literal["deepseek-flash", "deepseek-v4-pro"] = "deepseek-flash"
    timeout_seconds: float = Field(default=20, gt=0, le=60)
    max_requests: int = Field(default=3, ge=1, le=3)

    @classmethod
    def from_env(cls):
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise ValueError("未配置 DEEPSEEK_API_KEY；请在进程环境中设置，勿写入仓库")
        return cls(api_key=key)
