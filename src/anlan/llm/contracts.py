"""Provider-independent bounded model failure contract."""


class AnalysisFailure(Exception):
    def __init__(self, category: str, usage: dict[str, int | None] | None = None,
                 model: str | None = None, prompt_version: str | None = None):
        super().__init__(category)
        self.category = category
        self.usage = usage
        self.model = model
        self.prompt_version = prompt_version
