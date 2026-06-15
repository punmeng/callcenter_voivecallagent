# UC2 即時通話助理

UC2 是即時客服通話輔助路徑，使用 Microsoft Agent Framework 與 Foundry 執行設定，且不影響 UC1 批次流程。

## UC2 功能

- 透過 WebSocket 端點 `/invocations_ws` 接收逐字稿事件
- 產生精簡助理卡片（next_best_action / compliance / answer）
- 支援通話結束後摘要
- 在內建 UI 顯示執行模型與用量指標

## 執行模式

UC2 支援兩種模式：

1. Portal Agent 模式（建議）
   - 設定 `VOICE_ASSIST_AGENT_NAME` 與 `VOICE_ASSIST_AGENT_VERSION`
2. Model Deployment 模式
   - 設定 `VOICE_ASSIST_MODEL_DEPLOYMENT_NAME`

## 本機設定

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
```

必要環境變數：

- `VOICE_ASSIST_PROJECT_ENDPOINT`
- 以下擇一：
  - Portal Agent：`VOICE_ASSIST_AGENT_NAME` + `VOICE_ASSIST_AGENT_VERSION`
  - Deployment：`VOICE_ASSIST_MODEL_DEPLOYMENT_NAME`

相容別名（選用）：

- `FOUNDRY_VOICE_ASSIST_AGENT_NAME`
- `FOUNDRY_VOICE_ASSIST_AGENT_VERSION`

## 執行

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc2_main
```

預設端點：

- UI：`http://127.0.0.1:8080/`
- WebSocket：`ws://127.0.0.1:8080/invocations_ws`

## 畫面截圖

即時通話主控台（閒置）：

![UC2 即時通話主控台](images/04_uc2_live-console.png)

通話進行中：

![UC2 即時通話主控台通話中](images/05_uc2_live-console_incall.png)

通話結束摘要：

![UC2 即時通話主控台通話摘要](images/06_uc2_live-console_callsummary.png)

## 語音優化技巧

UC2 將麥克風語音串流至伺服器，並即時執行 Azure Speech 者辨識（實作於 [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py)）：

| 技巧 | 功能說明 | 設定位置 |
| --- | --- | --- |
| 即時說話者辨識 | 瀏覽器透過 `/audio_ws` WebSocket 串流 PCM 音訊，伺服器以 `ConversationTranscriber` 依說話者 ID 標記每段。 | 點選「啟動麥克風」後自動進行。 |
| 自動專員/客戶對映 | 第一位說話者對映為專員，第二位為客戶，整通通話標籤穩定。 | 自動；若顓倒可按「交換專員/客戶」。 |
| 持續語言辨識 (LID) | `AutoDetectSourceLanguageConfig` 逐句判斷 zh-TW 或 en-US，支援語言轉換。 | `SPEECH_LANGUAGES` 環境變數。 |
| PCM 音訊串流 | 麥克風音訊在瀏覽器端降頻為 16 kHz / 16-bit / 單聲道 PCM，逐幀串流以降低延遲。 | 自動。 |
| 滾動記錄視窗 | 保留最近 N 個輪次作為輔助 LLM 的上下文，平衡延遲與相關性。 | `VOICE_ASSIST_WINDOW_TURNS`（預設 12）。 |
| 共用語音認證階層 | 重用 UC1 認證（端點+金鑰、無金鑰 Entra ID 透過 `az login`、或金鑰+區域）與可選 Custom Speech 端點。 | `SPEECH_ENDPOINT` / `SPEECH_KEY` / `SPEECH_REGION`、`SPEECH_CUSTOM_ENDPOINT_ID`。 |
| STT 提供者標籤 | 控制指標 UI 顯示的 STT 服務名稱。 | `config/stt_config.toml` 的 `[uc2].provider` 或 `VOICE_ASSIST_STT_SERVICE`。 |

## 啟動檢查清單

- `az login` 成功
- `.env` 設定 `VOICE_ASSIST_*` 完整
- 服務啟動於 `8080`
- 可開啟 `http://127.0.0.1:8080/`
- UI 點擊 Connect 後狀態為 Connected

## UI 指標說明

Runtime Models 區塊：

- STT 模式
- LLM / Foundry 模型

Token Metrics 區塊：

- STT 模式
- LLM 模式
- 累積音訊秒數
- LLM 請求次數
- Session 累積 Token（input / output / total）
- 最後一次請求 Token（input / output / total）

UC2 的 STT 模式解析順序：

1. 每筆訊息 `stt_service`
2. `VOICE_ASSIST_STT_SERVICE`
3. 共用 `SPEECH_ENDPOINT`（與 UC1 相同）

## 訊息格式範例

```json
{
  "type": "transcript",
  "call_id": "001",
  "speaker": "agent",
  "text": "...",
  "partial": false
}
```

回應會包含 `status`、`cards`、可選 `summary_markdown`，以及供 UI 使用的 runtime / token metrics 欄位。
