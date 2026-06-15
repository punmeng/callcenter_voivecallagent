"""Generate C:/temp/001_voice.wav with real TTS speech for benchmark testing."""
import urllib.request
import wave
from azure.identity import AzureCliCredential

cred = AzureCliCredential()
token = cred.get_token("https://cognitiveservices.azure.com/.default").token

ssml = (
    '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-TW">'
    '<voice name="zh-TW-HsiaoChenNeural">測試測試 一 二 三 四 五 六 七 八 九 十 通話測試</voice>'
    "</speak>"
)

req = urllib.request.Request(
    "https://ai-speech-alexpun-resource.cognitiveservices.azure.com/cognitiveservices/v1",
    data=ssml.encode("utf-8"),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm",
    },
    method="POST",
)

with urllib.request.urlopen(req, timeout=30) as resp:
    audio = resp.read()

out_path = "C:/temp/001_voice.wav"
with open(out_path, "wb") as f:
    f.write(audio)

with wave.open(out_path, "rb") as w:
    dur = w.getnframes() / w.getframerate()
    print(f"OK: {out_path}  {dur:.2f}s  {w.getnchannels()}ch  {w.getframerate()}Hz  {len(audio)} bytes")
