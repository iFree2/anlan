"""Shared access and state-transition errors; one definition across features."""


class AccessDenied(Exception):
    """任务不存在与无权访问返回同一个错误。"""

class InvalidTransition(Exception):
    pass

class TaskBusy(Exception):
    pass
