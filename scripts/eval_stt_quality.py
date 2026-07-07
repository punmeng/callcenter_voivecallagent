from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "src")

from voiceqa.stt_benchmark import (
    append_cost_report,
    build_provider,
    parse_dataset,
    run_benchmark,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate STT quality across providers: Azure Speech STT variants, "
            "Voice Live API, MAI-Transcribe-1.5, and GPT audio transcription."
        )
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to JSONL benchmark dataset.",
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        default=None,
        choices=[
            "azure-speech-stt",
            "azure-speech-stt-fast",
            "azure-speech-stt-fast-phrase-list",
            "azure-speech-stt-rest",
            "azure-speech-stt-custom",
            "mai-transcribe-1.5",
            "gpt-audio-transcribe",
            "voice-live-realtime-azure-speech",
            "voice-live-realtime-azure-speech-phrase-list",
            "voice-live-realtime-gpt4o-transcribe",
            "voice-live-realtime-gpt4o-transcribe-phrase-list",
            "voice-live-api-gpt-4o-transcribe",
            "voice-live-api-mai-transcribe-1",
        ],
        help="Provider(s) to benchmark. Ranking uses raw transcript accuracy, latency, and estimated cost; corrected transcript metrics are reported separately.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/stt_benchmarks",
        help="Directory for benchmark outputs.",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        default=False,
        help=(
            "Run providers concurrently (one thread per provider). "
            "Reduces total wall-clock time when bottleneck is network I/O. "
            "stderr output from different providers may interleave."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    samples = parse_dataset(dataset_path)

    # When --providers is omitted, use benchmark.default_providers from stt_config.toml.
    if args.providers is None:
        try:
            import sys as _sys
            _sys.path.insert(0, "src")
            from voiceqa.stt_config import load_stt_config
            cfg = load_stt_config()
            provider_names = cfg.benchmark.default_providers
            if cfg.benchmark.parallel:
                args.parallel = True
            print(f"Using providers from config/stt_config.toml: {', '.join(provider_names)}")
        except Exception as exc:
            print(f"Warning: could not load stt_config.toml ({exc}); using default provider.", file=sys.stderr)
            provider_names = ["azure-speech-stt"]
    else:
        provider_names = args.providers

    providers = [build_provider(name) for name in provider_names]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output_dir) / run_id
    max_workers = len(providers) if args.parallel else 1
    summary_path = run_benchmark(providers=providers, samples=samples, output_dir=output_dir, max_workers=max_workers)
    append_cost_report(summary_path, samples, providers)

    print(f"Benchmark complete: {summary_path}")
    print("Providers:", ", ".join(provider.name for provider in providers))
    print(f"Samples: {len(samples)}")


if __name__ == "__main__":
    main()