"""Antigravity Multi-Panel Token Monitor v3

For Antigravity v1.23.2
Desktop widget to monitor all panels (Editor, Agent Manager, etc.) conversation sizes and estimated token usage.
- Queries active panels via CDP
- Estimates tokens from actual overview.txt text content (fallback: .pb file size)
- Automatically maps recently updated conversations to active panels
"""
import os
import sys
import json
import time
import re
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import threading
import queue
import shutil
import urllib.request
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# ─── Constants ───────────────────────────────────────────────────
DEFAULT_CDP_PORT = 9087
POLL_INTERVAL = 3  # seconds
MAX_DISPLAY_CONVS = 8
MAX_KEEP_LOGS = 5
# Runtime directory for PID + config
RUNTIME_DIR = Path.home() / ".gemini" / "antigravity" / "token-monitor"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = RUNTIME_DIR / "config.json"


def load_config() -> dict:
    """讀取設定檔，不存在就回傳預設值"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"cdp_port": DEFAULT_CDP_PORT}


def save_config(config: dict):
    """儲存設定到檔案"""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


# Load saved config on startup
_config = load_config()
CDP_PORT = _config.get("cdp_port", DEFAULT_CDP_PORT)
CDP_URL = f"http://127.0.0.1:{CDP_PORT}/json"

# Panel name mapping from CDP page titles
PANEL_TITLE_MAP = {
    "Manager": "AM (Agent Manager)",
    "Launchpad": "Launchpad",
}


def guess_panel_label(title: str) -> str:
    """從 CDP page title 推斷面板名稱"""
    if not title:
        return "Unknown"
    for key, label in PANEL_TITLE_MAP.items():
        if key.lower() in title.lower():
            return label
    if "antigravity" in title.lower() and ("扩展" in title or "extension" in title.lower()):
        return "Editor"

    if "claude" in title.lower():
        return "Claude"
    if "codex" in title.lower():
        return "Codex"
    return title[:20]


def query_cdp_panels(cdp_url: str = None) -> list[dict]:
    """查詢 CDP endpoint 取得目前開啟的面板清單"""
    if cdp_url is None:
        cdp_url = CDP_URL
    try:
        req = urllib.request.Request(cdp_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        panels = []
        for item in data:
            if item.get("type") == "page":
                panels.append({
                    "title": item.get("title", ""),
                    "label": guess_panel_label(item.get("title", "")),
                    "url": item.get("url", ""),
                })
        return panels
    except Exception:
        return []


def query_cdp_convo_mappings(cdp_url: str = None) -> dict:
    """透過 CDP 連線取得 UUID 到面板名稱的對應關係"""
    if cdp_url is None:
        cdp_url = CDP_URL
    mapping = {}
    try:
        import websockets
        import asyncio
    except ImportError:
        return mapping

    async def _async_scan():
        try:
            req = urllib.request.Request(cdp_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                targets = json.loads(resp.read())
        except Exception:
            return {}

        res_map = {}
        for t in targets:
            title = t.get("title", "")
            t_type = t.get("type", "")
            ws_url = t.get("webSocketDebuggerUrl", "")
            target_url = t.get("url", "")
            if not ws_url or t_type not in ("page", "iframe"):
                continue

            try:
                async with asyncio.timeout(1.5):
                    async with websockets.connect(ws_url) as ws:
                        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
                        
                        # 收集 execution contexts (等待 0.4 秒)
                        contexts = []
                        start_time = asyncio.get_event_loop().time()
                        while asyncio.get_event_loop().time() - start_time < 0.4:
                            try:
                                msg_raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
                                msg = json.loads(msg_raw)
                                if msg.get("method") == "Runtime.executionContextCreated":
                                    contexts.append(msg["params"]["context"])
                            except asyncio.TimeoutError:
                                pass
                        
                        if not contexts:
                            contexts = [{"id": 1}]

                        for ctx in contexts:
                            ctx_id = ctx["id"]
                            js_code = ""
                            panel_name = ""

                            if "manager" in title.lower():
                                panel_name = "AM"
                                js_code = """
                                (function() {
                                    let results = [];
                                    let pills = document.querySelectorAll('[data-testid^="convo-pill-"]');
                                    pills.forEach(pill => {
                                        let uuid = pill.getAttribute('data-testid').replace('convo-pill-', '');
                                        let opacity = window.getComputedStyle(pill).opacity;
                                        let isSelected = opacity === '1' || opacity === '1.0';
                                        results.push({ uuid: uuid, isSelected: isSelected });
                                    });
                                    return JSON.stringify(results);
                                })()
                                """
                            elif "antigravity" in title.lower() and ("扩展" in title or "extension" in title.lower()):
                                panel_name = "Editor"
                                js_code = """
                                (function() {
                                    let results = [];
                                    let uuidRegex = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
                                    let all = document.querySelectorAll('*');
                                    all.forEach(el => {
                                        for (let attr of el.attributes) {
                                            let val = attr.value || '';
                                            let match = val.match(uuidRegex);
                                            if (match) {
                                                results.push({ uuid: match[0], isSelected: true });
                                            }
                                        }
                                    });
                                    return JSON.stringify(results);
                                })()
                                """

                            elif "codex" in target_url.lower() or "codex" in title.lower() or "chatgpt" in target_url.lower():
                                panel_name = "Codex"
                                js_code = """
                                (function() {
                                    let html = document.documentElement.outerHTML;
                                    let uuidRegex = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
                                    let matches = html.match(uuidRegex);
                                    if (matches) {
                                        return JSON.stringify(Array.from(new Set(matches)).map(u => ({ uuid: u, isSelected: true })));
                                    }
                                    return "[]";
                                })()
                                """
                            elif "claude" in target_url.lower() or "claude" in title.lower():
                                panel_name = "Claude"
                                js_code = """
                                (function() {
                                    let html = document.documentElement.outerHTML;
                                    let uuidRegex = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
                                    let matches = html.match(uuidRegex);
                                    if (matches) {
                                        return JSON.stringify(Array.from(new Set(matches)).map(u => ({ uuid: u, isSelected: true })));
                                    }
                                    return "[]";
                                })()
                                """

                            if not js_code or not panel_name:
                                continue

                            req_id = 9000 + ctx_id
                            await ws.send(json.dumps({
                                "id": req_id,
                                "method": "Runtime.evaluate",
                                "params": {
                                    "expression": js_code,
                                    "contextId": ctx_id,
                                    "returnByValue": True
                                }
                            }))

                            # 接收結果
                            for _ in range(20):
                                msg_raw = await ws.recv()
                                msg = json.loads(msg_raw)
                                if msg.get("id") == req_id:
                                    val = msg.get("result", {}).get("result", {}).get("value")
                                    if val:
                                        try:
                                            items = json.loads(val)
                                            for item in items:
                                                uuid = item["uuid"]
                                                is_sel = item.get("isSelected", False)
                                                if uuid not in res_map or is_sel:
                                                    res_map[uuid] = {
                                                        "panel": panel_name,
                                                        "active": is_sel
                                                    }
                                        except Exception:
                                            pass
                                    break
            except Exception:
                pass
        return res_map

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(_async_scan())
        loop.close()
        return res
    except Exception:
        return mapping



def estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from actual text content
    
    CJK characters: ~1.5 tokens per character
    ASCII/English: ~1 token per 4 characters
    """
    if not text:
        return 0
    cjk_count = 0
    ascii_count = 0
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF):
            cjk_count += 1
        elif 32 <= cp <= 126:
            ascii_count += 1
    return int(cjk_count * 1.5 + ascii_count * 0.25)


def estimate_tokens_from_size(size_bytes: int) -> int:
    """Fallback: rough estimate from .pb file size when overview.txt is unavailable"""
    return int(size_bytes * 0.05)


class MultiPanelMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("Antigravity Multi-Panel Token Monitor v3")
        self.root.geometry("580x460")
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(True, True)
        self.root.minsize(500, 350)

        self.convo_panel_cache = {}
        self.cdp_port = CDP_PORT
        self.cdp_url = CDP_URL

        # Save PID to runtime directory
        try:
            pid_file = RUNTIME_DIR / "token-monitor.pid"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(os.getpid()))
            self.pid_file = pid_file
        except Exception:
            self.pid_file = None

        self.ui_queue = queue.Queue()
        self.running = True

        self.setup_ui()

        self.root.after(200, self.flush_ui_queue)
        self.thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.thread.start()

    def _apply_port(self, event=None):
        """使用者修改 Port 後套用並儲存"""
        try:
            new_port = int(self.port_entry.get().strip())
            if 1 <= new_port <= 65535:
                self.cdp_port = new_port
                self.cdp_url = f"http://127.0.0.1:{new_port}/json"
                save_config({"cdp_port": new_port})
                self.port_status.config(text="✓ Saved", fg="#4ecca3")
                self.root.after(2000, lambda: self.port_status.config(text=""))
            else:
                self.port_status.config(text="Invalid", fg="#e94560")
        except ValueError:
            self.port_status.config(text="Invalid", fg="#e94560")

    def setup_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg="#1a1a2e")
        hdr.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(hdr, text="⚡ Antigravity Token Monitor",
                 fg="#e94560", bg="#1a1a2e", font=("Arial", 15, "bold")).pack(side="left")

        # Panel info
        self.panels_var = tk.StringVar(value="Detecting panels...")
        tk.Label(hdr, textvariable=self.panels_var,
                 fg="#888", bg="#1a1a2e", font=("Arial", 9)).pack(side="right")

        # Port settings row
        port_frame = tk.Frame(self.root, bg="#1a1a2e")
        port_frame.pack(fill="x", padx=16, pady=(2, 0))
        tk.Label(port_frame, text="CDP Port:", fg="#888", bg="#1a1a2e",
                 font=("Arial", 9)).pack(side="left")
        self.port_entry = tk.Entry(port_frame, width=7, bg="#16213e", fg="#fff",
                                   insertbackground="#fff", font=("Consolas", 10),
                                   relief="flat", bd=1, highlightbackground="#333",
                                   highlightcolor="#4ecca3", highlightthickness=1)
        self.port_entry.insert(0, str(self.cdp_port))
        self.port_entry.pack(side="left", padx=(4, 4))
        self.port_entry.bind("<Return>", self._apply_port)
        apply_btn = tk.Button(port_frame, text="Apply", command=self._apply_port,
                              bg="#16213e", fg="#4ecca3", font=("Arial", 8, "bold"),
                              relief="flat", cursor="hand2", padx=6, pady=1)
        apply_btn.pack(side="left", padx=(0, 6))
        self.port_status = tk.Label(port_frame, text="", fg="#4ecca3", bg="#1a1a2e",
                                     font=("Arial", 8))
        self.port_status.pack(side="left")

        # Separator
        sep = tk.Frame(self.root, bg="#333", height=1)
        sep.pack(fill="x", padx=16, pady=4)

        # Table header
        cols_frame = tk.Frame(self.root, bg="#1a1a2e")
        cols_frame.pack(fill="x", padx=16, pady=(4, 0))
        col_widths = [("Panel / Conv", 22, "w", (8, 4)),
                      ("Size", 8, "e", (4, 4)),
                      ("Est. Tokens", 16, "e", (4, 4)),
                      ("Last Update", 11, "center", (4, 4)),
                      ("Status", 8, "center", (4, 4))]
        for text, w, anc, px in col_widths:
            tk.Label(cols_frame, text=text, fg="#666", bg="#1a1a2e",
                     font=("Consolas", 9, "bold"), width=w, anchor=anc).pack(side="left", padx=px)

        # Scrollable rows
        self.rows_frame = tk.Frame(self.root, bg="#1a1a2e")
        self.rows_frame.pack(fill="both", expand=True, padx=16, pady=4)

        self.row_widgets = []  # list of dicts {frame, labels...}
        for i in range(MAX_DISPLAY_CONVS):
            row_bg = "#16213e" if i % 2 == 0 else "#1a1a2e"
            rf = tk.Frame(self.rows_frame, bg=row_bg, height=32)
            rf.pack(fill="x", pady=1)
            rf.pack_propagate(False)

            lbl_name = tk.Label(rf, text="—", fg="#ccc", bg=row_bg,
                                font=("Consolas", 10), anchor="w", width=22)
            lbl_name.pack(side="left", padx=(8, 4), pady=4)

            lbl_size = tk.Label(rf, text="—", fg="#aaa", bg=row_bg,
                                font=("Consolas", 10), anchor="e", width=8)
            lbl_size.pack(side="left", padx=4, pady=4)

            lbl_tokens = tk.Label(rf, text="—", fg="#4ecca3", bg=row_bg,
                                  font=("Consolas", 10, "bold"), anchor="e", width=16)
            lbl_tokens.pack(side="left", padx=4, pady=4)

            lbl_time = tk.Label(rf, text="—", fg="#aaa", bg=row_bg,
                                font=("Consolas", 10), anchor="center", width=11)
            lbl_time.pack(side="left", padx=4, pady=4)

            lbl_status = tk.Label(rf, text="", fg="#888", bg=row_bg,
                                  font=("Arial", 9), anchor="center", width=8)
            lbl_status.pack(side="left", padx=4, pady=4)

            self.row_widgets.append({
                "frame": rf, "name": lbl_name, "size": lbl_size,
                "tokens": lbl_tokens, "time": lbl_time, "status": lbl_status,
            })

        # Bottom summary bar
        self.summary_var = tk.StringVar(value="Initializing...")
        summary_bar = tk.Label(self.root, textvariable=self.summary_var,
                               fg="#888", bg="#0f0f23", font=("Arial", 9), anchor="w")
        summary_bar.pack(side="bottom", fill="x", ipady=3, padx=0)

    def flush_ui_queue(self):
        while not self.ui_queue.empty():
            try:
                payload = self.ui_queue.get_nowait()
                if "panels_text" in payload:
                    self.panels_var.set(payload["panels_text"])
                if "rows" in payload:
                    self._update_rows(payload["rows"])
                if "summary" in payload:
                    self.summary_var.set(payload["summary"])
            except queue.Empty:
                break
        if self.running:
            self.root.after(300, self.flush_ui_queue)

    def _update_rows(self, rows_data):
        for i, w in enumerate(self.row_widgets):
            if i < len(rows_data):
                r = rows_data[i]
                w["name"].config(text=r.get("name", "—"), fg=r.get("name_color", "#ccc"))
                w["size"].config(text=r.get("size_text", "—"))
                w["tokens"].config(text=r.get("tokens_text", "—"))
                w["time"].config(text=r.get("time_text", "—"))
                w["status"].config(text=r.get("status", ""), fg=r.get("status_color", "#888"))
                w["frame"].pack(fill="x", pady=1)
            else:
                # Hide unused rows
                w["name"].config(text="")
                w["size"].config(text="")
                w["tokens"].config(text="")
                w["time"].config(text="")
                w["status"].config(text="")

    def monitor_loop(self):
        user_home = Path.home()
        conv_dir = user_home / ".gemini" / "antigravity" / "conversations"
        brain_root = user_home / ".gemini" / "antigravity" / "brain"

        while self.running:
            try:
                # 1. Query CDP for active panels
                panels = query_cdp_panels(self.cdp_url)
                panel_labels = [p["label"] for p in panels if p["label"] not in ("Launchpad",)]
                panels_text = f"Panels: {', '.join(panel_labels)}" if panel_labels else "No panels detected"

                # Update conversation-to-panel mapping cache via CDP
                try:
                    new_mappings = query_cdp_convo_mappings(self.cdp_url)
                    if new_mappings:
                        self.convo_panel_cache.update(new_mappings)
                except Exception:
                    pass

                # 2. List all conversations
                if not conv_dir.exists():
                    self.ui_queue.put({
                        "panels_text": panels_text,
                        "summary": "Status: conversations directory not found",
                    })
                    time.sleep(5)
                    continue

                convs = []
                for pb in conv_dir.glob("*.pb"):
                    stat = pb.stat()
                    conv_id = pb.stem
                    overview_path = brain_root / conv_id / ".system_generated" / "logs" / "overview.txt"
                    overview_text = ""
                    if overview_path.exists():
                        try:
                            with open(overview_path, "r", encoding="utf-8", errors="replace") as f:
                                overview_text = f.read()
                        except Exception:
                            pass

                    convs.append({
                        "id": conv_id,
                        "pb_size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "overview_text": overview_text,
                    })

                # Sort by most recently updated
                convs.sort(key=lambda c: c["mtime"], reverse=True)

                # 3. Try to match conversations to panels by recency
                # The most recently updated conversation is likely the active main chat
                now = time.time()
                rows_data = []
                for idx, conv in enumerate(convs[:MAX_DISPLAY_CONVS]):
                    age_secs = now - conv["mtime"]
                    dt_str = datetime.fromtimestamp(conv["mtime"]).strftime("%m-%d %H:%M")

                    # Size formatting
                    mb = conv["pb_size"] / (1024 * 1024)
                    size_text = f"{mb:.1f} MB"

                    # Token estimate (prefer text-based, fallback to size-based)
                    overview_text = conv.get("overview_text", "")
                    if overview_text:
                        est_tokens = estimate_tokens_from_text(overview_text)
                    else:
                        est_tokens = estimate_tokens_from_size(conv["pb_size"])
                    pct = est_tokens / 1_000_000 * 100
                    if est_tokens >= 1_000_000:
                        tokens_text = f"{est_tokens / 1_000_000:.2f}M ({pct:.0f}%)"
                    elif est_tokens >= 1000:
                        tokens_text = f"{est_tokens / 1000:.1f}K ({pct:.1f}%)"
                    else:
                        tokens_text = f"{est_tokens} ({pct:.1f}%)"

                    # Panel label guess
                    if age_secs < 30:
                        # Very recently updated — likely the active panel
                        label = "🟢 Active"
                        name_color = "#4ecca3"
                        status = "ACTIVE"
                        status_color = "#4ecca3"
                    elif age_secs < 300:
                        label = "🟡 Recent"
                        name_color = "#ffc107"
                        status = f"{int(age_secs)}s ago"
                        status_color = "#ffc107"
                    elif age_secs < 3600:
                        label = ""
                        name_color = "#aaa"
                        status = f"{int(age_secs // 60)}m ago"
                        status_color = "#888"
                    else:
                        label = ""
                        name_color = "#666"
                        hours = age_secs / 3600
                        if hours < 24:
                            status = f"{int(hours)}h ago"
                        else:
                            status = f"{int(hours // 24)}d ago"
                        status_color = "#555"

                    # Short conv ID for display & Panel matching
                    conv_id = conv["id"]
                    cache_info = self.convo_panel_cache.get(conv_id, {})
                    panel_name = cache_info.get("panel", "Unknown")

                    short_id = conv_id[:8]
                    display_name = f"[{panel_name}] {short_id}  {label}".strip()

                    rows_data.append({
                        "name": display_name,
                        "name_color": name_color,
                        "size_text": size_text,
                        "tokens_text": tokens_text,
                        "time_text": dt_str,
                        "status": status,
                        "status_color": status_color,
                    })

                # Summary
                total_size = sum(c["pb_size"] for c in convs)
                total_tokens = estimate_tokens_from_size(total_size)
                active_count = sum(1 for c in convs if now - c["mtime"] < 3600)

                self.ui_queue.put({
                    "panels_text": panels_text,
                    "rows": rows_data,
                    "summary": (
                        f"  Total: {len(convs)} convs | "
                        f"{total_size / (1024 * 1024):.0f} MB | "
                        f"~{total_tokens / 1_000_000:.1f}M est. tokens | "
                        f"{active_count} active in last 1hr | "
                        f"Refreshed: {datetime.now().strftime('%H:%M:%S')}"
                    ),
                })

            except Exception as e:
                self.ui_queue.put({
                    "summary": f"  Error: {str(e)[:60]}",
                })

            time.sleep(POLL_INTERVAL)

    def close(self):
        self.running = False
        if hasattr(self, 'pid_file') and self.pid_file and self.pid_file.exists():
            try:
                self.pid_file.unlink()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MultiPanelMonitor(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()
