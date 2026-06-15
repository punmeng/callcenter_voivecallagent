# Voice Use Cases Design Concept (Build 2026 後)

## 背景與原則

過去一段時間，我們持續協助客戶做 call center 現代化轉型，累積了大量 Speech/Voice 整合經驗。面對 FY27 台灣市場的需求成長，和客戶討論時建議遵循同一個原則：

- 不要只看 Model 或 API 名稱做選型。
- 回到客戶問題本質與應用場景，再決定技術層次。

## Build 2026 後的語音技術三層次

微軟 Voice 技術線可分成三個層次：

1. 模型（Model）
- Whisper
- MAI-Transcribe
- MAI-Voice-1
- MAI-Voice-2
- GPT-4o Realtime

2. 服務（Service）
- Azure Speech Service
- Azure OpenAI Realtime API

3. 平台（Orchestration Platform）
- Voice Live API

`Voice Live API` 的定位是 `STT + LLM + TTS` 的 Managed Runtime，不是單一模型。

參考文件：
- Voice Live API for real-time voice agents
- https://learn.microsoft.com/zh-tw/azure/ai-services/speech-service/voice-live-webrtc

## 能力對照（整合常見問題）

| 項目 | Azure Speech API | Whisper | MAI-Transcribe | GPT-4o Realtime | Voice Live API | MAI-Voice-1 | MAI-Voice-2 |
|---|---|---|---|---|---|---|---|
| 類型 | Service | Model | Model | Model + API | Managed Service | Model | Model |
| STT | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| TTS | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Speech-to-Speech | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| LLM 推理 | ❌ | ❌ | ❌ | ✅ | 可選擇 GPT/Phi 等模型 | ❌ | ❌ |
| Tool Calling | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| Avatar | Speech Avatar | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| 即時對話 | 部分支援 | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| 多輪記憶 | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| 電話中心 | ACS 整合 | ❌ | ❌ | ACS 搭配 | ACS 原生整合 | ❌ | ❌ |
| WebSocket | ✅ | 部分 | 部分 | ✅ | ✅ | ❌ | ❌ |
| WebRTC | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |

## 對金融/製造/政府客戶的一句話版本

- Azure Speech 是語音元件。
- GPT-4o Realtime 是即時對話模型。
- Voice Live API 是企業級語音 Agent 平台。
- MAI-Transcribe 與 MAI-Voice 是底層 STT/TTS 模型家族。

## 元件適用場景建議

### Azure Speech API 適合
- 字幕
- 語音辨識
- 語音合成
- 翻譯

### GPT-4o Realtime 適合
- 即時語音 Copilot
- 即時翻譯
- Voice Agent

### Voice Live API 適合
- Enterprise Voice Agent
- Contact Center
- Avatar Agent
- ACS / PSTN 整合

### MAI-Transcribe 適合
- 逐字稿
- Call Recording
- Teams Meeting

### MAI-Voice-2 適合
- AI 主播
- 品牌語音
- 高擬真語音生成

## 設計建議（實務）

和客戶做 Voice 用例設計時，建議用以下順序：

1. 先定義業務結果（降 AHT、提升一次解決率、縮短訓練時間）。
2. 再定義互動型態（離線轉錄、即時對話、語音代理、電話整合）。
3. 最後才選模型/服務/平台。

這樣可避免「看見新模型就套用」的反模式，改用「場景驅動」做現代化設計。