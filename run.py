"""Start both SafeRoute services after installing their dependencies."""
from pathlib import Path
import subprocess, sys, shutil, time, webbrowser
root = Path(__file__).resolve().parent
npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
if not npm:
    raise SystemExit("Install Node.js and npm first.")
processes = []
try:
    processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=root / "backend"))
    processes.append(subprocess.Popen([npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort"], cwd=root / "frontend"))
    print("SafeRoute: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs")
    print("Press Ctrl+C to stop both services.")
    while all(p.poll() is None for p in processes):
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill()
