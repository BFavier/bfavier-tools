import re
import pathlib
import inspect
import asyncio
import threading
from types import ModuleType
from typing import Awaitable, TypeVar, Callable, Any, AsyncIterable, Iterable


T = TypeVar("T")


def _run_async(coro: Awaitable[T]) -> T:
    """
    Run coroutine safely even if already inside an event loop
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    else:
        return asyncio.run(coro)


def _async_iter_to_sync(async_iter: AsyncIterable[T]) -> Iterable[T]:
    """
    Converts an async iterator into a sync iterator
    """
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    queue = asyncio.Queue(maxsize=1)
    sentinel = object()  # put in the queue when an error is raised
    exception_holder = []

    async def produce():
        try:
            async for item in async_iter:
                await queue.put(item)
        except Exception as e:
            exception_holder.append(e)
        finally:
            await queue.put(sentinel)

    asyncio.run_coroutine_threadsafe(produce(), loop)

    def iterator():
        try:
            while True:
                future = asyncio.run_coroutine_threadsafe(queue.get(), loop)
                item = future.result()
                if item is sentinel:
                    if exception_holder:
                        raise exception_holder[0]
                    break
                yield item
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join()
            loop.close()

    return iterator()


async def _sync_iter_to_async(sync_iter: Iterable[T]) -> AsyncIterable[T]:
    """
    Converts a synchrone iterable into an sync one
    """
    for obj in sync_iter:
        yield obj
        await asyncio.sleep(0)


def _function_definition_from_source(source: str) -> Iterable[str]:
    """
    Recursively extract a function definition from source
    """
    open_parenthesis: int=0
    characters = (c for c in source)
    for c in characters:
        yield c
        if c == "(":
            open_parenthesis += 1
        elif c == ")":
            open_parenthesis -= 1
            if open_parenthesis == 0:
                break
    for c in characters:
        yield c
        if c == ":":
            break


def _generate_sync_wrapper_code(async_func: Callable[[Any], Awaitable[T]]) -> str:
    """
    Returns a string representation of a sync function wrapper
    around an async function, preserving the original type hints
    exactly as written in the source file.
    """
    assert inspect.iscoroutinefunction(async_func) or inspect.isasyncgenfunction(async_func)
    # Copy the function definition in format: "async def copy_object_async(obj: FileSystemObjectTypes, parent: FileSystemObjectTypes | None):"
    source = "".join(_function_definition_from_source(inspect.getsource(async_func)))
    source = source.replace("AsyncIterable", "Iterable").replace("AsyncIterator", "Iterator")
    # Strip "async " from the front
    signature_line = re.sub(r"^async\s+", "", source)
    # Replace function name
    func_name = async_func.__name__.removesuffix("_async")
    signature_line = signature_line.replace(async_func.__name__, func_name, 1)
    # Get docstring if present
    doc = inspect.getdoc(async_func)
    if (doc is not None) and len(doc.strip()) > 0:
        doc = '    """\n    ' + "\n    ".join(doc.split("\n")) + '\n    """\n'
    else:
        doc = ""
    # Build wrapper body
    if inspect.iscoroutinefunction(async_func):
        body = f"return _run_async({async_func.__name__}({', '.join(p.name + '=' + p.name for p in inspect.signature(async_func).parameters.values())}))"
    else:  # async generator
        body = f"return _async_iter_to_sync({async_func.__name__}({', '.join(p.name + '=' + p.name for p in inspect.signature(async_func).parameters.values())}))"

    return f"{signature_line}\n{doc}    {body}"


def _generate_sync_module(module: ModuleType) -> str:
    """
    generate a sync module alongside
    """
    code = ""
    code += f"\"\"\"\nThis module was automatically generated from {module.__name__}\n\"\"\"\n"
    code += f"from {__name__} import _run_async, _async_iter_to_sync, _sync_iter_to_async\n"
    code += f"from typing import Iterable, Iterator\n"
    code += f"from {module.__name__} import {', '.join(name for name, obj in vars(module).items())}\n"
    for filter in (inspect.isasyncgenfunction, inspect.iscoroutinefunction):
        for name, obj in inspect.getmembers(module, filter):
            if not name.startswith("_") and obj.__code__.co_filename == module.__file__:
                code += f"\n\n{_generate_sync_wrapper_code(obj)}\n"
    return code
