from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "src")

from voiceqa.tts_benchmark import (  # noqa: E402
    build_tts_provider,
    parse_tts_dataset,
    run_tts_benchmark,
)

DEFAULT_PROVIDERS = ["voice-live-api", "azure-speech-tts"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark TTS providers (Voice Live API, GPT Realtime, Azure Speech neural "
            "TTS, MAI-Voice-2) on latency/performance. Generated audio is kept for "
            "manual/MOS review."
        )
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to JSONL dataset with rows of {sample_id, text, language?}.",
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        default=None,
        choices=["voice-live-api", "gpt-realtime", "azure-speech-tts", "mai-voice"],
        help=f"Provider(s) to benchmark. Default: {', '.join(DEFAULT_PROVIDERS)}.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/tts_benchmarks",
        help="Directory for benchmark outputs.",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        default=False,
        help="Run providers concurrently (one thread per provider).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    samples = parse_tts_dataset(dataset_path)

    provider_names = args.providers or DEFAULT_PROVIDERS
    providers = [build_tts_provider(name) for name in provider_names]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output_dir) / run_id
    max_workers = len(providers) if args.parallel else 1
    summary_path = run_tts_benchmark(
        providers=providers,
        samples=samples,
        output_dir=output_dir,
        max_workers=max_workers,
    )

    print(f"TTS benchmark complete: {summary_path}")
    print("Providers:", ", ".join(provider.name for provider in providers))
    print(f"Samples: {len(samples)}")
    print(f"Audio artifacts saved under: {output_dir}")


if __name__ == "__main__":
    main()
