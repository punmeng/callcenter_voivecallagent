from __future__ import annotations

import asyncio
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import load_settings
from .uc1_blob_reader import BlobReader
from .uc1_markdown_writer import MarkdownWriter
from .models import CallMetadata, CallMetrics, CallReport, TokenUsage
from .uc1_qa_judge import QaJudge
from .stt_config import build_uc1_stt, load_stt_config


@dataclass
class Uc1CallRunResult:
    item: str
    call_id: str
    stt_status: str
    report_path: str | None
    pass_count: int
    fail_count: int
    llm_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    error: str | None = None


@dataclass
class Uc1RunSummary:
    exit_code: int
    provider: str
    source_mode: str
    source_path: str | None
    total_items: int
    success_count: int
    error_count: int
    rules_json_path: str | None = None
    index_path: str | None = None
    message: str = ""
    calls: list[Uc1CallRunResult] = field(default_factory=list)


def _apply_source_override(settings, source_path_override: str | None) -> str | None:
    if not source_path_override:
        return None

    source_path = Path(source_path_override).expanduser()
    settings.input_source = "local"
    settings.input_blob_name = None
    settings.input_prefix = None

    if source_path.exists():
        if source_path.is_file():
            settings.local_audio_path = source_path
            settings.local_audio_dir = None
            return str(source_path)
        if source_path.is_dir():
            settings.local_audio_path = None
            settings.local_audio_dir = source_path
            return str(source_path)

    if source_path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
        settings.local_audio_path = source_path
        settings.local_audio_dir = None
    else:
        settings.local_audio_path = None
        settings.local_audio_dir = source_path
    return str(source_path)


async def run_uc1(
    source_path_override: str | None = None,
    stt_provider_override: str | None = None,
) -> Uc1RunSummary:
    settings = load_settings()
    source_path = _apply_source_override(settings, source_path_override)

    stt_cfg = load_stt_config()
    if stt_provider_override and stt_provider_override.strip():
        stt_cfg.uc1.provider = stt_provider_override.strip()

    print(f"STT provider (UC1): {stt_cfg.uc1.provider}")

    reader = BlobReader(settings)
    writer = MarkdownWriter(settings)
    stt = build_uc1_stt(settings, stt_cfg)
    judge = QaJudge(settings)

    rubric = reader.read_rubric()
    rules_json_path = writer.write_scoring_rules_json(rubric)
    print(f"Scoring rules JSON generated: {rules_json_path}")

    input_items = reader.list_input_audio_items()
    if not input_items:
        message = ""
        if settings.input_source == "local":
            message = "No local audio files found. Set LOCAL_AUDIO_PATH or LOCAL_AUDIO_DIR."
        else:
            message = "No input blobs found. Set INPUT_BLOB_NAME or INPUT_PREFIX."
        print(message)
        return Uc1RunSummary(
            exit_code=1,
            provider=stt_cfg.uc1.provider,
            source_mode=settings.input_source,
            source_path=source_path,
            total_items=0,
            success_count=0,
            error_count=0,
            rules_json_path=str(rules_json_path),
            message=message,
        )

    generated_reports: list[tuple[str, Path]] = []
    call_results: list[Uc1CallRunResult] = []
    error_count = 0

    for item in input_items:
        call_id = Path(item).stem
        _provider_slug = re.sub(r"[^\w-]", "_", stt_cfg.uc1.provider)
        _daytime = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_name = f"{call_id}_{_provider_slug}_{_daytime}"
        print(f"Processing call: {call_id} ({item})")

        temp_path: Path | None = None
        should_cleanup = False
        try:
            temp_path, should_cleanup = reader.load_audio_for_processing(item)
            transcript = await asyncio.to_thread(stt.transcribe_audio, temp_path)

            call_length_seconds = transcript.duration_seconds if transcript else 0.0

            if not transcript.turns:
                report = CallReport(
                    metadata=CallMetadata(call_id=call_id, blob_name=item),
                    transcript=transcript,
                    item_results=[],
                    stt_status="empty transcript",
                    metrics=CallMetrics(
                        stt_incoming_call_length_seconds=call_length_seconds,
                        llm_requests=0,
                        token_usage=TokenUsage(),
                    ),
                )
            else:
                item_results = await judge.judge_items(transcript, rubric)
                token_usage = judge.get_last_token_usage()
                llm_requests = judge.get_last_request_count()
                report = CallReport(
                    metadata=CallMetadata(call_id=call_id, blob_name=item),
                    transcript=transcript,
                    item_results=item_results,
                    stt_status="OK",
                    metrics=CallMetrics(
                        stt_incoming_call_length_seconds=call_length_seconds,
                        llm_requests=llm_requests,
                        token_usage=token_usage,
                    ),
                )

            markdown = writer.render_report(report)
            local_path = writer.write_local(report_name, markdown)
            details_json_path = writer.write_scoring_details_json(report)
            metrics_json_path = writer.write_call_metrics_json(report)
            generated_reports.append((call_id, local_path))

            verdict_items = [row for row in report.item_results if row.item_type == "verdict"]
            pass_count = sum(1 for row in verdict_items if row.verdict == "符合")
            fail_count = sum(1 for row in verdict_items if row.verdict == "不符合")

            call_results.append(
                Uc1CallRunResult(
                    item=item,
                    call_id=call_id,
                    stt_status=report.stt_status,
                    report_path=str(local_path),
                    pass_count=pass_count,
                    fail_count=fail_count,
                    llm_requests=report.metrics.llm_requests,
                    input_tokens=report.metrics.token_usage.input_tokens,
                    output_tokens=report.metrics.token_usage.output_tokens,
                    total_tokens=report.metrics.token_usage.total_tokens,
                )
            )

            if settings.output_to_blob:
                reader.write_report_blob(f"{report_name}.md", markdown)

            print(f"Report generated: {local_path}")
            print(f"Scoring details JSON generated: {details_json_path}")
            print(f"Call metrics JSON generated: {metrics_json_path}")
        except Exception as exc:
            error_count += 1
            print(f"Failed to process {item}: {exc}")
            print(traceback.format_exc())
            call_results.append(
                Uc1CallRunResult(
                    item=item,
                    call_id=call_id,
                    stt_status="ERROR",
                    report_path=None,
                    pass_count=0,
                    fail_count=0,
                    llm_requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    error=str(exc),
                )
            )
        finally:
            if should_cleanup and temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    index_local: Path | None = None
    if generated_reports and (len(generated_reports) > 1 or settings.input_prefix):
        index_md = writer.render_index(generated_reports)
        index_local = writer.write_local("index", index_md)
        if settings.output_to_blob:
            reader.write_report_blob("index.md", index_md)
        print(f"Index generated: {index_local}")

    success_count = len(generated_reports)
    exit_code = 0
    message = "Completed successfully."
    if error_count:
        exit_code = 2
        message = f"Completed with {error_count} failed call(s)."
        print(message)
    else:
        print(message)

    return Uc1RunSummary(
        exit_code=exit_code,
        provider=stt_cfg.uc1.provider,
        source_mode=settings.input_source,
        source_path=source_path,
        total_items=len(input_items),
        success_count=success_count,
        error_count=error_count,
        rules_json_path=str(rules_json_path),
        index_path=str(index_local) if index_local else None,
        message=message,
        calls=call_results,
    )


def main() -> None:
    summary = asyncio.run(run_uc1())
    raise SystemExit(summary.exit_code)


if __name__ == "__main__":
    main()