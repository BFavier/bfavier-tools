import zlib
from typing import AsyncIterable, Iterable


async def gz_stream_async(data: AsyncIterable[bytes] | Iterable[bytes]) -> AsyncIterable[bytes]:
    """
    Compress a stream of data into a gz archive, without ever loading the data entirely in memory
    """
    compressor = zlib.compressobj(method=zlib.DEFLATED, wbits=16+15)
    if isinstance(data, AsyncIterable):
        async for chunk in data:
            yield compressor.compress(chunk)
    else:
        for chunk in data:
            yield compressor.compress(chunk)
    yield compressor.flush()
