# UC1 批次流程：Blob 音檔到 Markdown QA 報告

UC1 為已實作的批次評分流程，使用共用 Microsoft Agent Framework runtime。

## 功能重點

- 從 Azure Blob 或本機讀取音檔
- Azure Speech 語音轉文字（支援 zh-TW / en-US）
- STT 優化流程：
  - Continuous Language ID
  - Phrase List 提升關鍵詞辨識
  - Detailed output + N-best
  - `assets/corrections.json` 後處理修正
  - 可選 custom speech endpoint
- 使用 Agent Framework 進行 rubric 判定（exception-first）
- 產生每通電話 Markdown 報告（可選 `index.md`）

## 設定

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

將 `.env.example` 複製為 `.env` 後填入值。

## 執行

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main
```

## 必要環境變數

- Blob：`BLOB_ACCOUNT_URL`, `BLOB_CONTAINER_IN`, `BLOB_CONTAINER_OUT`
- Speech（擇一）：
  - `SPEECH_KEY` + `SPEECH_REGION`
  - `SPEECH_KEY` + `SPEECH_ENDPOINT`
  - `SPEECH_ENDPOINT`（僅 Entra ID / `az login`）
- 模型：`AOAI_API_KEY`, `AOAI_ENDPOINT`, `AOAI_DEPLOYMENT`

若使用 Entra ID（不使用 API Key）：

- 先執行 `az login`
- 設定 `AOAI_USE_ENTRA_ID=true`
- 保留 `AOAI_ENDPOINT`, `AOAI_DEPLOYMENT`, `AOAI_API_VERSION`
- `AOAI_API_KEY` 可留空

## UC1 Foundry Portal Agent（選用）

若要在 Foundry 看到 UC1 portal agent 活動，設定：

- `FOUNDRY_PROJECT_ENDPOINT`
- `FOUNDRY_AGENT_NAME`
- `FOUNDRY_AGENT_VERSION`

UC1 也接受 UC1 專用命名：

- `UC1_FOUNDRY_AGENT_NAME`
- `UC1_FOUNDRY_AGENT_VERSION`

更多步驟可參考：

- [P9_UC1_FOUNDRY_AGENT_PROCEDURE.md](P9_UC1_FOUNDRY_AGENT_PROCEDURE.md)

## 語音優化技巧

UC1 疊加以下 Azure Speech 優化技術，以提升中英混合通話音訊的轉寫準確度（實作於 [../src/voiceqa/uc1_stt_agent.py](../src/voiceqa/uc1_stt_agent.py)）：

| 技巧 | 功能說明 | 設定位置 |
| --- | --- | --- |
| 持續語言辨識 (LID) | 以 `AutoDetectSourceLanguageConfig` 逐句自動判斷 zh-TW 或 en-US，支援通話中途轉換語言。 | `SPEECH_LANGUAGES` 環境變數或 `config/stt_config.toml` 的 `[uc1].languages`。 |
| 說話者辨識 (Diarization) | `ConversationTranscriber` 為每個輪次標記說話者 ID，在報告中區分專員與客戶。 | `[uc1]` 使用 `azure-speech-stt` 提供者。 |
| 片語清單加權 (Phrase List) | 載入領域術語 / 產品名稱，導引辨識偏向預期詞彙。 | `assets/phrase_list.txt`（`PHRASE_LIST_PATH`）；以 `[uc1].phrase_list` 開關。 |
| 詳細輸出 + 詞級時間戳 | 請求 `Detailed` 輸出、詞級時間戳與詞級修正，提供更豐富的評分依據。 | UC1 預設啟用。 |
| N-best 擷取 | 保留每段前三名候選轉寫結果供後續檢視。 | UC1 預設啟用。 |
| STT 後處理修正 | 辨識後依規則將已知誤辨（例如品牌名）歸一化。 | `assets/corrections.json`（`CORRECTIONS_PATH`）。 |
| 自訂語音模型 (Custom Speech) | 可選接至微調的 Custom Speech 端點，針對領域聲學/詞彙優化。 | `SPEECH_CUSTOM_ENDPOINT_ID`。 |
| 可插拔 STT 提供者 | 無需改程式即可切換 STT 引擎（即時 SDK、快速 SDK、REST 快速轉寫、MAI-Transcribe、GPT audio、Custom Speech）。 | `config/stt_config.toml` 的 `[uc1].provider`。 |

## 畫面截圖

UC1 品質檢查頁面（整合式儀表板）：

![UC1 品質檢查頁面](images/02_uc1_qualitycheck.png)

產生的 QA 報告檢視：

![UC1 品質檢查報告](images/03_uc1_qualitycheck_report.png)
