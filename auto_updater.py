import requests
import os
import zipfile
import shutil

CURRENT_VERSION = "1.0.0"
REPO = "your_username/your_repo"  # Thay bằng tên repo
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def check_and_update():
    """Kiểm tra và cài đặt bản cập nhật từ GitHub."""
    try:
        headers = {"Accept": "application/vnd.github+json"}
        response = requests.get(RELEASES_API_URL, headers=headers, timeout=5)
        response.raise_for_status()
        latest_version = response.json()["tag_name"].lstrip("v")
        if latest_version > CURRENT_VERSION:
            print(f"[*] Phiên bản mới: {latest_version}. Đang cập nhật...")
            download_url = response.json()["assets"][0]["browser_download_url"]

            response = requests.get(download_url, stream=True, timeout=10)
            response.raise_for_status()
            with open("agent_new.zip", "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            with zipfile.ZipFile("agent_new.zip", "r") as zip_ref:
                zip_ref.extractall("agent_update")

            for root, dirs, files in os.walk("agent_update"):
                for file in files:
                    src = os.path.join(root, file)
                    dst = os.path.join(os.getcwd(), file)
                    os.replace(src, dst)

            os.remove("agent_new.zip")
            shutil.rmtree("agent_update", ignore_errors=True)
            print("[*] Đã cài đặt bản cập nhật.")
            return True
        else:
            print("[*] Agent đã ở phiên bản mới nhất.")
            return False
    except Exception as e:
        print(f"[!] Lỗi khi cập nhật: {e}")
        return False
