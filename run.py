import os
import sys
import subprocess

# Ensure we use the virtual environment's Python interpreter
venv_python = os.path.join("venv", "Scripts", "python.exe") if sys.platform == "win32" else os.path.join("venv", "bin", "python")

if os.path.exists(venv_python) and sys.executable != os.path.abspath(venv_python):
    print("Restarting server inside the virtual environment...")
    subprocess.call([venv_python] + sys.argv)
    sys.exit()

import uvicorn
from src.config import HOST, PORT

if __name__ == "__main__":
    print("=" * 60)
    print("   Starting DSGVO Privacy Gateway for LLMs Backend...")
    print(f"   URL: http://{HOST}:{PORT}")
    print("=" * 60)
    
    # Run Uvicorn server
    uvicorn.run(
        "src.main:app",
        host=HOST,
        port=PORT,
        reload=True
    )
