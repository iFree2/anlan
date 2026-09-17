"""规则与语义分析分开，offline 不伪装为模型理解。"""

from typing import Literal, Protocol

from pydantic import Field

from anlan.contracts import QUESTIONS, Application, Issue, StrictModel


class Analysis(StrictModel):
    issues: list[Issue] = Field(default_factory=list, max_length=4)
    semantic_status: Literal["offline_not_checked", "checked", "failed"]
    error: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    usage: dict[str, int | None] | None = None


class AnalysisFailure(Exception):
    def __init__(self, category: str, usage: dict[str, int | None] | None = None,
                 model: str | None = None, prompt_version: str | None = None):
        super().__init__(category)
        self.category = category
        self.usage = usage
        self.model = model
        self.prompt_version = prompt_version


class Analyzer(Protocol):
    async def analyze(self, application: Application) -> Analysis: ...


class OfflineAnalyzer:
    async def analyze(self, application: Application) -> Analysis:
        return Analysis(semantic_status="offline_not_checked")


def missing_issues(application: Application) -> list[Issue]:
    return [
        Issue(field=name, kind="missing", quote="", reason="字段为空（合成填报规则）",
              question=QUESTIONS[name], source="rule")
        for name, value in application.model_dump().items() if not value
    ]
