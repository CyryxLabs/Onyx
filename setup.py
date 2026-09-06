import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

print("Installing requirements...")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")],
    check=True,
    cwd=ROOT,
)

print("Installing Playwright Chromium...")
subprocess.run(
    [
        sys.executable,
        "-m",
        "playwright",
        "install",
        "--no-shell",
        "chromium",
    ],
    check=True,
    cwd=ROOT,
)

if sys.platform.startswith("linux"):
    print(
        "\nLinux note: Chromium may need distribution packages. Review and run "
        "'python -m playwright install-deps chromium' explicitly with the privileges "
        "required by your distribution. setup.py never elevates privileges."
    )

print("\n✅ Setup complete!")
print("Run 'python -m core.readiness' for safe offline diagnostics.")
print("Run 'python main.py' to start Onyx.")

