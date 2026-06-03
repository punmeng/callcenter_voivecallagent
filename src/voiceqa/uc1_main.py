from __future__ import annotations

import asyncio
import traceback
from pathlib import Path

from .config import load_settings
from .uc1_blob_reader import BlobReader
from .uc1_markdown_writer import MarkdownWriter
from .models import CallMetadata, CallMetrics, CallReport, TokenUsage
from .uc1_qa_judge import QaJudge
from .uc1_stt_agent import SttAgent


async def run_uc1() -> int:
    settings = load_settings()

    reader = BlobReader(settings)
    writer = MarkdownWriter(settings)
    stt = SttAgent(settings)
    judge = QaJudge(settings)

    rubric = reader.read_rubric()
    rules_json_path = writer.write_scoring_rules_json(rubric)
    print(f"Scoring rules JSON generated: {rules_json_path}")

    input_items = reader.list_input_audio_items()
    if not input_items:
        if settings.input_source == "local":
            print("No local audio files found. Set LOCAL_AUDIO_PATH or LOCAL_AUDIO_DIR.")
        else:
            print("No input blobs found. Set INPUT_BLOB_NAME or INPUT_PREFIX.")
        return 1

    generated_reports: list[tuple[str, Path]] = []
    error_count = 0

    for item in input_items:
        call_id = Path(item).stem
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
            local_path = writer.write_local(call_id, markdown)
            details_json_path = writer.write_scoring_details_json(report)
            metrics_json_path = writer.write_call_metrics_json(report)
            generated_reports.append((call_id, local_path))
            if settings.output_to_blob:
                reader.write_report_blob(f"{call_id}.md", markdown)

            print(f"Report generated: {local_path}")
            print(f"Scoring details JSON generated: {details_json_path}")
            print(f"Call metrics JSON generated: {metrics_json_path}")
        except Exception as exc:
            error_count += 1
            print(f"Failed to process {item}: {exc}")
            print(traceback.format_exc())
        finally:
            if should_cleanup and temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    if generated_reports and (len(generated_reports) > 1 or settings.input_prefix):
        index_md = writer.render_index(generated_reports)
        index_local = writer.write_local("index", index_md)
        if settings.output_to_blob:
            reader.write_report_blob("index.md", index_md)
        print(f"Index generated: {index_local}")

    if error_count:
        print(f"Completed with {error_count} failed call(s).")
        return 2

    print("Completed successfully.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run_uc1()))


if __name__ == "__main__":
    main()