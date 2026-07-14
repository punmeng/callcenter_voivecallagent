from src.voiceqa import tts_benchmark as t

print(t.build_tts_provider("azure-speech-tts", "en-US-JennyNeural").display_name())
print(t.build_tts_provider("mai-voice").display_name())
print(t.build_tts_provider("gpt-realtime", "cedar").display_name())
print(repr(t._ssml_to_plain_text("<speak><prosody rate='fast'>Hello &amp; hi</prosody></speak>")))

s = t.TtsSample(sample_id="x", text="hello", language="en")
s.ssml = "<speak>hi</speak>"
print("ssml field ok:", s.ssml)
print("OK")
