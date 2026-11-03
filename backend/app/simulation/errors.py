class SimulationError(Exception):
    """Safe-to-expose failure (message is written by us, never from user data or a traceback)."""
    code = "simulation_error"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class ResourceLimitError(SimulationError):
    code = "resource_limit"
