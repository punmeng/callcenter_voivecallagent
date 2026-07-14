from src.voiceqa import web_ui

html = web_ui._tts_benchmark_page(
    selected_providers_override=["voice-live-api", "azure-speech-tts"],
    selected_voices_override={"azure-speech-tts": "en-US-GuyNeural", "voice-live-api": "shimmer"},
    ssml_override="<speak>{text}</speak>",
)
checks = {
    "voice select present": 'name="voice__azure-speech-tts"' in html,
    "voice selected": '<option value="en-US-GuyNeural" selected>' in html,
    "ssml textarea": 'name="ssml"' in html,
    "ssml value kept": "<speak>{text}</speak>" in html or "&lt;speak&gt;{text}&lt;/speak&gt;" in html,
    "play toggle js": "toggleTtsPlay" in html,
    "voice label i18n": 'data-i18n-text="tts_voice_label"' in html,
    "ssml title i18n": 'data-i18n-text="tts_ssml_title"' in html,
}
for k, v in checks.items():
    print(("PASS" if v else "FAIL"), k)
print("ALL OK" if all(checks.values()) else "SOME FAILED")
