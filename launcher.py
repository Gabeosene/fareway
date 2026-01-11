import subprocess
import sys
import time
import os
import signal

def main():
    print("[Launcher] Starting Silent Photon System...")
    
    # 1. Start Backend
    print("[Launcher] Launching Backend Server (port 8000)...")
    backend = subprocess.Popen([sys.executable, "server.py"], cwd=".")
    
    # 2. Start Frontend Server
    print("[Launcher] Launching Frontend Server (port 3000)...")
    web_dir = os.path.join(os.getcwd(), "web")
    frontend = subprocess.Popen([sys.executable, "-m", "http.server", "3000"], cwd=web_dir)
    
    print("\n" + "="*40)
    print("[Launcher] SYSTEM READY")
    print("[Launcher] Access the Dashboard at: http://localhost:3000")
    print("="*40 + "\n")
    print("[Launcher] Press Ctrl+C to stop both servers.")
    
    try:
        # Keep alive
        while True:
            time.sleep(1)
            if backend.poll() is not None:
                print("[Launcher] Backend died unexpectedly!")
                break
            if frontend.poll() is not None:
                print("[Launcher] Frontend died unexpectedly!")
                break
    except KeyboardInterrupt:
        print("\n[Launcher] Stopping...")
    finally:
        # Kill both
        backend.terminate()
        frontend.terminate()
        try:
           backend.wait(timeout=2)
           frontend.wait(timeout=2)
        except:
           backend.kill()
           frontend.kill()
        print("[Launcher] Stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()
