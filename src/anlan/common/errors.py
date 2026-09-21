"""Shared access and state-transition errors; one definition across features."""


class AccessDenied(Exception):
    """Same error for absent and inaccessible tasks."""

class InvalidTransition(Exception):
    pass

class TaskBusy(Exception):
    pass
