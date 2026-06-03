from __future__ import annotations

import json
import tempfile
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from .config import Settings


class BlobReader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._service: BlobServiceClient | None = None

        if settings.blob_connection_string:
            self._service = BlobServiceClient.from_connection_string(settings.blob_connection_string)
        elif settings.blob_account_url:
            self._service = BlobServiceClient(settings.blob_account_url, credential=DefaultAzureCredential())

    def list_input_audio_items(self) -> list[str]:
        if self.settings.input_source == "local":
            return self._list_local_audio_items()

        container = self._blob_service().get_container_client(self.settings.blob_container_in)

        if self.settings.input_blob_name:
            return [self.settings.input_blob_name]

        prefix = self.settings.input_prefix or ""
        return [blob.name for blob in container.list_blobs(name_starts_with=prefix)]

    def load_audio_for_processing(self, item: str) -> tuple[Path, bool]:
        if self.settings.input_source == "local":
            audio_path = Path(item)
            if not audio_path.exists() or not audio_path.is_file():
                raise FileNotFoundError(f"Local audio file does not exist: {audio_path}")
            return audio_path, False

        return self.download_audio_to_temp(item), True

    def download_audio_to_temp(self, blob_name: str) -> Path:
        container = self._blob_service().get_container_client(self.settings.blob_container_in)
        blob_client = container.get_blob_client(blob_name)
        suffix = Path(blob_name).suffix or ".wav"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            data = blob_client.download_blob().readall()
            temp_file.write(data)
            return Path(temp_file.name)

    def read_rubric(self) -> dict:
        if self.settings.rubric_local_path:
            local_path = self.settings.rubric_local_path
            if not local_path.exists() or not local_path.is_file():
                raise FileNotFoundError(f"RUBRIC_LOCAL_PATH does not exist: {local_path}")
            return json.loads(local_path.read_text(encoding="utf-8"))

        container = self._blob_service().get_container_client(self.settings.blob_container_in)
        blob_client = container.get_blob_client(self.settings.rubric_blob_path)
        content = blob_client.download_blob().readall().decode("utf-8")
        return json.loads(content)

    def write_report_blob(self, blob_name: str, markdown_content: str) -> None:
        container = self._blob_service().get_container_client(self.settings.blob_container_out)
        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(markdown_content.encode("utf-8"), overwrite=True)

    def _blob_service(self) -> BlobServiceClient:
        if self._service is None:
            raise ValueError(
                "Blob client is not configured. Set BLOB_CONNECTION_STRING or BLOB_ACCOUNT_URL for blob operations."
            )
        return self._service

    def _list_local_audio_items(self) -> list[str]:
        if self.settings.local_audio_path:
            path = self.settings.local_audio_path
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"LOCAL_AUDIO_PATH does not exist: {path}")
            return [str(path.resolve())]

        if self.settings.local_audio_dir:
            directory = self.settings.local_audio_dir
            if not directory.exists() or not directory.is_dir():
                raise NotADirectoryError(f"LOCAL_AUDIO_DIR does not exist: {directory}")

            audio_files: list[Path] = []
            patterns = ["*.wav", "*.mp3", "*.m4a", "*.flac", "*.ogg"]
            for pattern in patterns:
                audio_files.extend(sorted(directory.glob(pattern)))

            return [str(path.resolve()) for path in audio_files if path.is_file()]

        raise ValueError(
            "For INPUT_SOURCE=local, set LOCAL_AUDIO_PATH (single file) or LOCAL_AUDIO_DIR (folder)."
        )