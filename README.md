# Antigravity Multi-Panel Token Monitor v3

> **For [Antigravity](https://antigravity.dev) v1.23.2**

[繁體中文](#繁體中文) | [English](#english)

---

## 繁體中文

這是一個輕量級的桌面監控小程式，使用 Python (Tkinter) 撰寫。它能在背景自動掃描 Google Gemini (Antigravity 系統) 各個面板的對話記錄，即時粗估 Token 消耗量與檔案大小，並以深色主題的進度條和列表呈現在桌面上。

### 🌟 功能特色
* **Multi-Panel Detection**：Auto-detects and tags which panel a conversation belongs to (e.g. `[Editor]`, `[Agent Manager]`) via Chrome DevTools Protocol (CDP).
* **即時 Token 估算**：採用 CJK 漢字與英文字詞的加權模型，在離線狀態下高精度估算對話歷史總 token 數，協助掌控 100 萬的 Token 額度限制。
* **低干擾深色介面**：緊湊的 Tkinter 排版，不影響程式撰寫或日常操作。
* **進程管理 (PID Cooldown)**：啟動時自動寫入進程 PID 快取，防止重複執行多個視窗。

### ⚙️ 系統需求與依賴
* **作業系統**：Windows / macOS / Linux (本機需支援 Python 視窗程式 Tkinter)。
* **Python 版本**：Python 3.10 或以上。
* **外部套件**：
  ```bash
  pip install -r requirements.txt
  ```

### 🚀 快速啟動
1. 確保您的編輯器 (VS Code/Cursor) 或瀏覽器已開啟 Chrome DevTools Protocol (CDP)，預設連接埠為 `9087`。
2. 執行指令：
   ```bash
   pythonw token_monitor_gui.py
   ```
   *(使用 `pythonw` 可以隱藏背後的 CMD 黑色終端機視窗，僅顯示面板)*。

---

## English

A lightweight desktop monitoring widget written in Python (Tkinter) to track and visualize your Google Gemini (Antigravity system) conversation sizes, estimated token usage, and active execution panels in real time.

### 🌟 Key Features
* **Multi-Panel Detection**: Auto-detects and tags which panel a conversation belongs to (e.g. `[Editor]`, `[Agent Manager]`) by querying Chrome DevTools Protocol (CDP) execution contexts.
* **Real-time Token Estimation**: High-fidelity offline approximations using CJK/English word weights to keep you informed of the 1M token limit.
* **Compact Dark-Mode GUI**: Clean dark aesthetics designed to sit unobtrusively on your desktop.
* **Process Safeguard**: Writes a PID lock file on startup to prevent duplicate running instances.

### ⚙️ Prerequisites & Dependencies
* **OS**: Windows / macOS / Linux (supporting Python Tkinter GUI).
* **Python**: Python 3.10+
* **Dependencies**:
  ```bash
  pip install -r requirements.txt
  ```

### 🚀 Quick Start
1. Ensure your browser or IDE (VS Code / Cursor) has Chrome DevTools Protocol (CDP) enabled on port `9087`.
2. Run the application:
   ```bash
   pythonw token_monitor_gui.py
   ```
   *(Using `pythonw` runs the script in windowless mode, showing only the GUI window).*
