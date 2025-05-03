import requests
import logging

# Configure logging
logger = logging.getLogger("UpdateServer")


class UpdateServer:
    """
    Component responsible for communicating with the custom update server.
    - Uses the routes:
      - GET api/agent/version - For checking the latest version
      - POST api/agent/update - For requesting updates with hash tables
    """

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.version_endpoint = "/api/agent/version"
        self.update_endpoint = "/api/agent/update"

    def send_hash_table(
        self, file_hashes, current_version, framework_version=None, is_first_run=False
    ):
        """
        Send hash table to the update server and get delta package information.
        Uses the POST api/agent/update endpoint.

        Parameters:
        - file_hashes: Dictionary of file paths and their hashes
        - current_version: Current application version
        - framework_version: Current framework version (optional)
        - is_first_run: Flag to indicate if this is the first run of the updater

        If is_first_run is True, the server may send a full application package
        instead of just delta updates.
        """
        try:
            payload = {
                "version": current_version,
                "hashes": file_hashes,
                "platform": self._get_platform(),
                "is_first_run": is_first_run,
            }

            # Add framework version if provided
            if framework_version:
                payload["framework_version"] = framework_version

            # Construct update endpoint URL
            update_url = f"{self.base_url}{self.update_endpoint}"

            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            response = requests.post(
                update_url, json=payload, headers=headers, timeout=30
            )
            response.raise_for_status()

            result = response.json()

            if "version" in result:
                logger.info(
                    f"Nhận được thông tin gói từ server: {result.get('version', 'unknown')}"
                )

                # Log whether this is a full package or delta update
                if result.get("update_available", False):
                    is_full_package = result.get("is_full_package", False)
                    if is_full_package:
                        logger.info("Sẽ tải về gói đầy đủ chứa toàn bộ ứng dụng")
                    else:
                        logger.info("Sẽ tải về gói cập nhật delta")
                    return result
                else:
                    return {"update_available": False, "version": result.get("version")}
            else:
                logger.warning("Không nhận được thông tin phiên bản từ server")
                return None

        except requests.RequestException as e:
            logger.error(f"Lỗi kết nối với server khi gửi bảng hash: {e}")

            # Fallback: If server doesn't support delta updates, check for latest version
            logger.info("Thử phương thức kiểm tra phiên bản thông thường...")
            return self._check_latest_version_fallback()
        except Exception as e:
            logger.error(f"Lỗi khi gửi bảng hash đến server: {e}")
            return None

    def _check_latest_version_fallback(self):
        """Fallback method to check latest version."""
        try:
            latest_version, download_url = self.check_latest_version()
            return {
                "update_available": True,
                "version": latest_version,
                "download_url": download_url,
                "is_delta": False,
            }
        except Exception as e:
            logger.error(f"Lỗi khi thực hiện phương thức dự phòng: {e}")
            return None

    def check_latest_version(self):
        """
        Check for the latest version from the update server.
        Uses the GET api/agent/version endpoint.
        """
        try:
            version_url = f"{self.base_url}{self.version_endpoint}"
            headers = {"Accept": "application/json"}
            response = requests.get(version_url, headers=headers, timeout=5)
            response.raise_for_status()

            version_info = response.json()
            latest_version = version_info.get("version")
            download_url = version_info.get("download_url")

            if not latest_version or not download_url:
                logger.error(
                    "Server không trả về thông tin phiên bản hoặc URL tải xuống"
                )
                raise ValueError("Invalid server response format")

            return latest_version, download_url
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra phiên bản: {e}")
            raise

    def download_update(self, download_url, target_file="agent_new.zip"):
        """Download the update package from the server."""
        try:
            # If download_url is relative, make it absolute
            if download_url.startswith("/"):
                download_url = f"{self.base_url}{download_url}"

            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()

            with open(target_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Đã tải về gói cập nhật: {target_file}")
            return target_file
        except Exception as e:
            logger.error(f"Lỗi khi tải về gói cập nhật: {e}")
            raise

    def _get_platform(self):
        """Get the current platform information."""
        import platform

        return {
            "os": platform.system(),
            "architecture": platform.architecture()[0],
            "machine": platform.machine(),
        }
