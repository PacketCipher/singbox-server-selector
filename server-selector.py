import requests
import time
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# API
API_URL = "http://192.168.27.1:6756"
BEARER_TOKEN = ""  # Bearer token for authorization

# If you want to use sing box as relay (e.g in OpenVPN) then setup a simple http server in your OpenVPN server and set this to your http://Server-IP
# TEST_URL = "https://www.gstatic.com/generate_204"
TEST_URL = "http://cp.cloudflare.com"
TIMEOUT = 5000  # Timeout in milliseconds
RETRIES = 15 * 6
RETRY_DELAY = 5  # Delay between retries in seconds
MIN_UPTIME = 90  # in percent
CHECK_INTERVAL = 60  # Fallback check interval in seconds
UPDATE_INTERVAL = 4 * 60 * 60  # Update delay info every 4 hours
MAX_WORKERS = 1000  # Maximum number of threads for parallel processing


# Function to get headers with the Bearer token
def get_headers():
    return {
        "Authorization": f"Bearer {BEARER_TOKEN}"
    }


def get_proxies():
    """Gets all proxies from the Clash API."""
    response = requests.get(f"{API_URL}/proxies", headers=get_headers())
    if response.status_code == 200:
        return response.json()["proxies"]
    else:
        raise Exception(f"Failed to get proxies: {response.status_code}")


def get_real_delay_multi(proxy_name):
    """Gets the real delay of a proxy by averaging multiple measurements."""
    delays = []
    for i in range(RETRIES):
        try:
            response = requests.get(
                f"{API_URL}/proxies/{proxy_name}/delay",
                headers=get_headers(),
                params={"timeout": TIMEOUT, "url": TEST_URL},
            )
            if response.status_code == 200:
                delays.append(response.json()["delay"])
            else:
                delays.append(TIMEOUT)
        except requests.exceptions.RequestException as e:
            print(f"Error getting delay for {proxy_name}: {e}")

        if delays.count(TIMEOUT) >= max(1, RETRIES * (1 - (MIN_UPTIME/100))):
            break

        if i < RETRIES - 1:
            time.sleep(RETRY_DELAY)

    if len(delays) == RETRIES:
        print(delays)
        return sum(delays) / len(delays)
    else:
        return float("inf")  # Return infinity if all retries fail


def get_real_delay_single(proxy_name):
    """Gets the real delay of a proxy by single measurements."""
    response = requests.get(
        f"{API_URL}/proxies/{proxy_name}/delay",
        headers=get_headers(),
        params={"timeout": TIMEOUT, "url": TEST_URL},
    )
    if response.status_code == 200:
        return response.json()["delay"]
    else:
        return TIMEOUT


def update_delay_info(proxies, sampling_type):
    """Updates the delay information for all proxies in parallel."""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for proxy_name, proxy_data in proxies.items():
            if proxy_data["type"] in ("VLESS", "Trojan", "Shadowsocks", "VMess", "TUIC"):
                executor.submit(update_proxy_delay, proxy_name,
                                proxy_data, sampling_type)


def update_proxy_delay(proxy_name, proxy_data, sampling_type):
    """Updates the delay for a single proxy."""
    if sampling_type == "multi":
        delay = get_real_delay_multi(proxy_name)
        proxy_data["delay_multi"] = delay
        print(f"Updated multi delay for {proxy_name}: {delay} ms")
    elif sampling_type == "single":
        delay = get_real_delay_single(proxy_name)
        proxy_data["delay_single"] = delay
        print(f"Updated single delay for {proxy_name}: {delay} ms")
    # TODO: Add Sampling_type for OpenVPN delay check


def sort_proxies_by_delay(proxies, sampling_type):
    """Sorts the proxies by their delay, excluding Direct, Reject, and DNS types."""
    sortable_proxies = [
        (proxy_name, proxy_data)
        for proxy_name, proxy_data in proxies.items()
        if proxy_data["type"] in ("VLESS", "Trojan", "Shadowsocks", "VMess", "TUIC")
    ]
    return sorted(sortable_proxies, key=lambda item: item[1].get("delay_multi" if sampling_type == "multi" else "delay_single", float("inf")))


def fallback_to_working_proxy_by_order(sorted_proxies):
    """Finds the first working proxy in the sorted list and switches to it."""
    for proxy_name, _ in sorted_proxies:
        try:
            response = requests.get(f"{API_URL}/proxies/{proxy_name}/delay",
                                    headers=get_headers(),
                                    params={"timeout": TIMEOUT, "url": TEST_URL})
            if response.status_code == 200:
                print(f"Switching to {proxy_name}")
                requests.put(f"{API_URL}/proxies/proxy",
                             headers=get_headers(),
                             json={"name": proxy_name})
                return
            else:
                print(f"{proxy_name} is not responding. Trying the next one...")
        except requests.exceptions.RequestException as e:
            print(f"Error checking {proxy_name}: {e}")
    print("No working proxies found.")


def fallback_to_working_proxy_by_latency(sorted_proxies):
    """Finds the lowest delay working proxy in the sorted list and switches to it."""
    top_proxies = sorted_proxies[:10]
    update_delay_info(dict(top_proxies), sampling_type="single")
    sorted_top_proxies = sort_proxies_by_delay(
        dict(top_proxies), sampling_type="single")

    proxy_name = sorted_top_proxies[0][0]
    print(f"Switching to {proxy_name}")
    requests.put(f"{API_URL}/proxies/proxy",
                 headers=get_headers(),
                 json={"name": proxy_name})
    return


def main():
    """Main loop for updating delay info and performing fallback."""
    while True:
        try:
            proxies = get_proxies()
            # Update delay info in parallel
            update_delay_info(proxies, sampling_type="multi")
            sorted_proxies = sort_proxies_by_delay(
                proxies, sampling_type="multi")

            # Run fallback check every CHECK_INTERVAL seconds
            start_time = datetime.now()
            while datetime.now() - start_time < timedelta(seconds=UPDATE_INTERVAL):
                fallback_to_working_proxy_by_order(sorted_proxies)
                # fallback_to_working_proxy_by_latency(sorted_proxies)
                time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"An error occurred: {e}")
            time.sleep(60)  # Wait for a minute before trying again


if __name__ == "__main__":
    main()

# TODO: Parallel fallback check
# TODO: load balance the top 5
