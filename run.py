import os
import sys
import socket
import webbrowser
import threading
import time
import uvicorn

def get_local_ip():
    """LAN内のローカルIPアドレスを取得"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def open_browser():
    time.sleep(1.5)
    url = "http://localhost:8000"
    print(f"\n[INFO] Opening browser on PC: {url}")
    webbrowser.open(url)

def main():
    local_ip = get_local_ip()
    port = 8000

    print("=" * 65)
    print("  Daily Candle Stock Monitor (日足監視＆市場スキャナー)")
    print("=" * 65)
    print(f"[PC Access]     http://localhost:{port}")
    print(f"[Mobile Access] http://{local_ip}:{port}")
    print("=" * 65)
    print("★ スマートフォンからアクセスする方法:")
    print(f"  1. スマホをPCと同じWi-Fiに接続してください")
    print(f"  2. スマホのブラウザで上記URL (http://{local_ip}:{port}) を開いてください")
    print("=" * 65)

    # 別スレッドでPCブラウザを自動起動
    threading.Thread(target=open_browser, daemon=True).start()

    # 外部（スマホ等）からもアクセスできるように 0.0.0.0 でバインド
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)

if __name__ == "__main__":
    main()
