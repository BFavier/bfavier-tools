from time import time
from dataclasses import dataclass
from typing import AsyncIterable, Iterable


@dataclass
class StreamedFile:
    """
    A StreamedFile is a named file, of known size, the content of which is not loaded all at once in memory
    """
    name: str
    bytes_size: int
    data_stream: AsyncIterable[bytes]


def _pad_blocks(section_bytes_size: int) -> bytes:
    """
    Pad the file data of a tar archive to the next block size
    """
    BLOCK_SIZE = 512
    padding = (BLOCK_SIZE - (section_bytes_size % BLOCK_SIZE)) % BLOCK_SIZE
    return b"\0" * padding


def _tar_file_header(file_name: str, file_bytes_size: int, type_flag: bytes=b"0") -> bytes:
    """
    Create a ustar tar header for a block in the tar file
    """
    header = bytearray(512)
    name_bytes = file_name.encode("utf-8")[:100]
    # fill in the header
    header[0:len(name_bytes)] = name_bytes  # Name
    header[100:108] = b"0000777\0"  # mode
    header[108:116] = b"0000000\0"  # uid
    header[116:124] = b"0000000\0"  # gid
    header[124:136] = bytes(f"{file_bytes_size:o}".rjust(11, "0"), "ascii") + b"\0"  # Size (octal)
    header[136:148] = bytes(f"{int(time()):o}".rjust(11, "0"), "ascii") + b"\0"  # mtime
    header[148:156] = b"        "  # Checksum field initially with spaces
    header[156:157] = type_flag  # Typeflag (0 = regular file, 1 = hard link, 2 = symbolic link, b"x" = extended header)
    header[257:263] = b"ustar\0"  # Magic
    header[263:265] = b"00"  # Magic
    # Compute checksum
    checksum = sum(header)
    header[148:156] = bytes(f"{checksum:o}".rjust(6, "0"), "ascii") + b"\0" + b" "
    # return
    return bytes(header)


def _pax_header(file_bytes_size: int) -> bytes:
    """
    Build a PAX extended header block with a size=... record.
    """
    # Each record is "<length> <key>=<value>\n"
    record = f" size={file_bytes_size}\n"
    length = len(record) + len(str(len(record)))
    payload = f"{length}{record}".encode("utf-8")
    # pad the pax header as a separate block
    padded = payload + _pad_blocks(len(payload))
    # Make a header block of type 'x' (extended header)
    return _tar_file_header(file_name="PaxHeader", file_bytes_size=len(padded), type_flag=b"x") + padded


def _tar_file_extended_header(file_name: str, file_bytes_size: int) -> bytes:
    """
    Returns the file header, handling the logic of whether pax header is required or not
    """
    # If size exceeds tar limit, emit PAX header first
    if file_bytes_size > (8**11 - 1):
        return _pax_header(file_bytes_size) + _tar_file_header(file_name, 0)
    else:
        return _tar_file_header(file_name, file_bytes_size)


async def _targz_file_chunks_async(streamed_file: StreamedFile) -> AsyncIterable[bytes]:
    """
    yields the chunks of the data corresponding to one file of a .tar archive
    """
    yield _tar_file_extended_header(streamed_file.name, streamed_file.bytes_size)
    async for chunk in streamed_file.data_stream:
        yield chunk
    yield _pad_blocks(streamed_file.bytes_size)


async def tar_stream_async(streamed_files: AsyncIterable[StreamedFile] | Iterable[StreamedFile]) -> AsyncIterable[bytes]:
    """
    Creates a tar archive from a stream of files, without ever loading any file completly in memory
    """
    if isinstance(streamed_files, AsyncIterable):
        async for file in streamed_files:
            async for chunk in _targz_file_chunks_async(file):
                yield chunk 
    else:
        for file in streamed_files:
            async for chunk in _targz_file_chunks_async(file):
                yield chunk
    yield b"\0" * 1024
