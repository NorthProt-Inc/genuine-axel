import functools
import inspect
import logging
from typing import Callable, TypeVar, ParamSpec

P = ParamSpec('P')
T = TypeVar('T')


def logged(
    entry: bool = True,
    exit: bool = True,
    level: int = logging.DEBUG,
    log_args: bool = False,
    log_result: bool = False,
):
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        module = func.__module__
        if module.startswith("backend."):
            module = module[8:]
        logger_name = module

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            from .structured_logger import get_logger
            _log = get_logger(logger_name)
            fn_name = func.__name__

            if entry:
                if log_args:

                    sig = inspect.signature(func)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()

                    arg_info = {
                        k: v for k, v in bound.arguments.items()
                        if k != 'self' and not k.startswith('_')
                    }
                    _log._log(level, f"→ {fn_name}", **arg_info)
                else:
                    _log._log(level, f"→ {fn_name}")

            try:
                result = await func(*args, **kwargs)  # type: ignore[misc]
                if exit:
                    if log_result and result is not None:
                        _log._log(level, f"← {fn_name}", result=result)
                    else:
                        _log._log(level, f"← {fn_name}")
                return result
            except Exception as e:
                _log.error(f"✗ {fn_name}", error=str(e)[:100])
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            from .structured_logger import get_logger
            _log = get_logger(logger_name)
            fn_name = func.__name__

            if entry:
                if log_args:
                    sig = inspect.signature(func)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    arg_info = {
                        k: v for k, v in bound.arguments.items()
                        if k != 'self' and not k.startswith('_')
                    }
                    _log._log(level, f"→ {fn_name}", **arg_info)
                else:
                    _log._log(level, f"→ {fn_name}")

            try:
                result = func(*args, **kwargs)
                if exit:
                    if log_result and result is not None:
                        _log._log(level, f"← {fn_name}", result=result)
                    else:
                        _log._log(level, f"← {fn_name}")
                return result
            except Exception as e:
                _log.error(f"✗ {fn_name}", error=str(e)[:100])
                raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    return decorator
