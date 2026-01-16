import hashlib
import hmac
import os
import random
import time

import requests
from dotenv import load_dotenv

load_dotenv()
ACCESS_KEY = os.getenv("EF_ACCESS_KEY")
SECRET_KEY = os.getenv("EF_SECRET_KEY")
HOST = os.getenv("HOST")  # eurepoean - https://api-e.ecoflow.com


def create_headers(query_params=None):
    if query_params is None:
        query_params = {}

    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sorted_keys = sorted(query_params.keys())

    param_str = ""
    for key in sorted_keys:
        param_str += f"{key}={query_params[key]}&"

    sign_str = (
        f"{param_str}accessKey={ACCESS_KEY}&" f"nonce={nonce}&" f"timestamp={timestamp}"
    )
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    return {
        "accessKey": ACCESS_KEY,
        "nonce": nonce,
        "timestamp": timestamp,
        "sign": signature,
    }


def get_sn():
    url = f"{HOST}/iot-open/sign/device/list"
    resp = requests.get(url, headers=create_headers())
    data = resp.json()
    if data["code"] == "0" and data["data"]:
        return data["data"][0]["sn"]
    return None


def check_power_status(sn):
    url = f"{HOST}/iot-open/sign/device/quota/all"

    params = {"sn": sn}
    headers = create_headers(params)

    resp = requests.get(url, headers=headers, params=params)
    data = resp.json()

    if data["code"] == "0":
        metrics = data["data"]
        soc = metrics.get("cmsBattSoc", 0)
        grid_in = metrics.get("powGetSysGrid", 0)
        load_out = metrics.get("powGetSysLoad", 0)

        print(f"\n--- station status (sn: {sn}) ---")
        print(f"Battery: {soc}%")
        print(f"Grid Input: {grid_in} W")
        print(f"Load Output: {load_out} W")

        if grid_in > 10:
            print("✅ light is ON. Grid connected")
        elif grid_in < 10 and load_out > 0:
            print("light is OFF. running on battery")
        else:
            print("💤 IDLE (station is asleep or nothing plugged in)")

    else:
        print("Error getting data:", data)


if __name__ == "__main__":
    my_sn = get_sn()
    if my_sn:
        check_power_status(my_sn)
    else:
        print("Device not found.")
