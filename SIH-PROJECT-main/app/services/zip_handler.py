import zipfile
from pathlib import Path

def safe_extract_zip(zip_path: Path, evaluation_id: str) -> Path:
    extract_dir = Path("extracted") / evaluation_id
    extract_dir.mkdir(parents=True, exist_ok=True)

    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Uploaded file is not a valid zip")

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target_path = (extract_dir / info.filename).resolve()
            if not str(target_path).startswith(str(extract_dir.resolve())):
                raise ValueError(f"Blocked unsafe path in zip: {info.filename}")

        zf.extractall(extract_dir)

    return extract_dir