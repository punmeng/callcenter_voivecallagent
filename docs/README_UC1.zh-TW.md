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

- [UC1_FOUNDRY_AGENT_PROCEDURE.md](UC1_FOUNDRY_AGENT_PROCEDURE.md)
