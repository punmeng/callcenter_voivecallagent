# VoiceCall Verify

此專案提供兩個處理中英夾雜（zh-TW + English）客服通話的方案。

## 快速開始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
```

## 目前功能

### UC1：Blob 音檔到 Markdown QA 報告

UC1 為批次流程，支援：

- 從 Azure Blob Storage 或本機讀取音檔
- 使用 Azure AI Speech 進行語音轉文字
- 套用術語片語與後處理修正規則
- 透過 Microsoft Agent Framework 進行評分判定
- 產出 Markdown 報告與 JSON 評分結果

執行入口：

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc1_main
```

### UC2：即時通話輔助

UC2 為即時輔助流程，支援：

- 透過 WebSocket 接收逐字稿事件
- 維持每通電話的滾動視窗上下文
- 產生 next-best-action / compliance / answer 卡片
- 視需求產出通話結束摘要
- 在 UI 顯示 STT 模式、LLM 模式、Token 與音訊秒數指標

執行入口：

```powershell
$env:PYTHONPATH = "src"
python -m voiceqa.uc2_main
```

## 主要檔案

- [../src/voiceqa/uc1_main.py](../src/voiceqa/uc1_main.py) - UC1 流程主程式
- [../src/voiceqa/uc1_stt_agent.py](../src/voiceqa/uc1_stt_agent.py) - UC1 語音轉文字
- [../src/voiceqa/uc1_qa_judge.py](../src/voiceqa/uc1_qa_judge.py) - UC1 判定邏輯
- [../src/voiceqa/uc2_live_assistant.py](../src/voiceqa/uc2_live_assistant.py) - UC2 即時助理邏輯
- [../src/voiceqa/agent_runtime.py](../src/voiceqa/agent_runtime.py) - 共用 Agent Runtime
- [../agent.yaml](../agent.yaml) - Foundry Agent 設定

## 相關文件

- [P1_README.md](P1_README.md)（英文）
- [P7_README_UC1.md](P7_README_UC1.md)
- [P8_README_UC2.md](P8_README_UC2.md)
- [P7_README_UC1.zh-TW.md](P7_README_UC1.zh-TW.md)
- [P8_README_UC2.zh-TW.md](P8_README_UC2.zh-TW.md)
- [P3_VOICE_USE_CASES_DESIGN_CONCEPT.zh-TW.md](P3_VOICE_USE_CASES_DESIGN_CONCEPT.zh-TW.md)
- [P11_STT_BENCHMARK.md](P11_STT_BENCHMARK.md)
- [P12_cost_estimate.md](P12_cost_estimate.md)
- [P12_cost_estimate.zh-TW.md](P12_cost_estimate.zh-TW.md)
- [P14_REPO_ORGANIZATION.md](P14_REPO_ORGANIZATION.md)
- [P13_PROCESS_SUMMARY.md](P13_PROCESS_SUMMARY.md)
- [../catalog/README.md](../catalog/README.md)
- [../catalog/voice_catalogs.yaml](../catalog/voice_catalogs.yaml)
- [P4_architecture.md](P4_architecture.md)
- [P2_scope.md](P2_scope.md)
