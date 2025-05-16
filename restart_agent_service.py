import os
import subprocess
import time

SERVICE_NAME = "agent"
FLAG_FILE = "restart.flag"
CHECK_INTERVAL = 10  # seconds


def main():
    while True:
        if os.path.exists(FLAG_FILE):
            print("Restart flag detected. Restarting service...")
            subprocess.run(["nssm", "restart", SERVICE_NAME], check=True)
            os.remove(FLAG_FILE)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
