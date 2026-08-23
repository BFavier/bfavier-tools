from typing import Type


class check_fail:
    """
    Context that exit silently at the first error.
    If there was no error on leaving the context, raise one.
    """

    def __init__(self, exception_type: Type[Exception] = Exception):
        self.exception_type = exception_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if isinstance(exc_value, self.exception_type):
            return True
        elif exc_value is not None:
            raise exc_value
        raise RuntimeError("This should have raised an error.")