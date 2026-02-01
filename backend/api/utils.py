from fastapi import HTTPException, UploadFile


async def read_upload_file(file: UploadFile, max_bytes: int) -> bytes:
    content = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="File too large")
    return bytes(content)
