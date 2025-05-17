import os
import shutil
import subprocess
import time

import requests

SERVICE_NAME = "agent"
FLAG_FILE = "restart.flag"
CHECK_INTERVAL = 10  # seconds
APP_URL = "http://host.docker.internal"
VERSION_FILE = "version.txt"
VERSION_ENDPOINT = "/api/agent/version"


def main():
    while True:
        if os.path.exists(FLAG_FILE):
            # Stop the agent service using nssm
            subprocess.run(["nssm", "stop", SERVICE_NAME], check=True)

            # Extract the update zip file
            zip_path = "agent_new.zip"
            extract_dir = "update"

            if os.path.exists(zip_path):
                # Create extract directory if it doesn't exist
                os.makedirs(extract_dir, exist_ok=True)

                # Extract the zip file
                shutil.unpack_archive(zip_path, extract_dir)

                # Remove the zip file after extraction
                os.remove(zip_path)

            # Move all files from update folder to current directory, overwriting if necessary
            update_path = "update"
            current_path = "."
            if os.path.exists(update_path):
                for item in os.listdir(update_path):
                    src = os.path.join(update_path, item)
                    dst = os.path.join(current_path, item)
                    if os.path.isfile(src):
                        shutil.move(src, dst)  # Move and overwrite files

            # Delete the restart.flag file
            if os.path.exists(FLAG_FILE):
                os.remove(FLAG_FILE)

            # Rewrite the version file
            with open(VERSION_FILE, "w") as f:
                f.write(requests.get(f"{APP_URL}{VERSION_ENDPOINT}").text)

            # Start the agent service using nssm
            subprocess.run(["nssm", "start", SERVICE_NAME], check=True)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
