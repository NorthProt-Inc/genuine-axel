"""API 공통 유틸리티."""
from fastapi import HTTPException, UploadFile


async def read_upload_file(file: UploadFile, max_bytes: int) -> bytes:
    """업로드 파일을 바이트로 읽되 크기 제한 적용.

    Args:
        file: FastAPI UploadFile 객체
        max_bytes: 최대 허용 바이트 수

    Returns:
        파일 내용 바이트

    Raises:
        HTTPException: 파일이 max_bytes를 초과할 경우 (413)
    """
    content = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)  # 1MB 청크
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="File too large")
    return bytes(content)
