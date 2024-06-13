import aiohttp
import asyncio
import os
import time
from datetime import datetime, timedelta

# Read configuration from environment variables
API_URL = str(os.getenv("API_URL"))
BEARER_TOKEN = str(os.getenv("BEARER_TOKEN")) # Bearer token for authorization
TEST_URL = str(os.getenv("TEST_URL", "http://cp.cloudflare.com"))
TIMEOUT = int(os.getenv("TIMEOUT", 5000)) # Timeout in milliseconds
RETRIES = int(os.getenv("RETRIES", 15 * 4))
RETRY_DELAY = int(os.getenv("RETRY_DELAY", 10)) # Delay between retries in seconds
MIN_UPTIME = int(os.getenv("MIN_UPTIME", 90)) # in percent
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60)) # Fallback check interval in seconds
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", 4 * 60 * 60)) # Update delay info every 4 hours
LIGHTMODE_MAXIMUM_SERVERS = int(os.getenv("LIGHTMODE_MAXIMUM_SERVERS", 10))
PROXY_GROUP_NAME = str(os.getenv("PROXY_GROUP_NAME", "select"))

# Function to get headers with the Bearer token
def get_headers():
    return {
        "Authorization": f"Bearer {BEARER_TOKEN}"
    }

async def get_proxies(session):
    """Gets all proxies from the Clash API."""
    async with session.get(f"{API_URL}/proxies", headers=get_headers()) as response:
        if response.status == 200:
            result = await response.json(content_type=None)
            return result["proxies"]
        else:
            raise Exception(f"Failed to get proxies: {response.status}")

async def get_real_delay_multi(session, proxy_name):
    """Gets the real delay of a proxy by averaging multiple measurements."""
    delays = []
    for i in range(RETRIES):
        try:
            async with session.get(
                f"{API_URL}/proxies/{proxy_name}/delay",
                headers=get_headers(),
                params={"timeout": TIMEOUT, "url": TEST_URL},
                timeout=TIMEOUT/1000
            ) as response:
                if response.status == 200:
                    delays.append((await response.json())["delay"])
                else:
                    delays.append(TIMEOUT)

        except asyncio.TimeoutError:
            delays.append(TIMEOUT)

        except Exception as e:
            print(f"Error getting delay for {proxy_name}: {e}")

        if delays.count(TIMEOUT) >= max(1, RETRIES * (1 - (MIN_UPTIME/100))):
            break

        if i < RETRIES - 1:
            await asyncio.sleep(RETRY_DELAY)

    if len(delays) == RETRIES:
        print(delays)
        return sum(delays) / len(delays)
    else:
        return float("inf")  # Return infinity if all retries fail

async def get_real_delay_single(session, proxy_name):
    """Gets the real delay of a proxy by single measurements, with retries on TimeoutError."""
    number_of_attemps = 3
    for attempt in range(number_of_attemps):
        try:
            async with session.get(
                f"{API_URL}/proxies/{proxy_name}/delay",
                headers=get_headers(),
                params={"timeout": TIMEOUT, "url": TEST_URL},
                timeout=TIMEOUT/1000
            ) as response:
                if response.status == 200:
                    return (await response.json())["delay"]
                else:
                    return TIMEOUT
        except asyncio.TimeoutError:
            if attempt < number_of_attemps - 1:
                print(f"Timeout error for {proxy_name}, retrying in 10 seconds...")
                await asyncio.sleep(10)
            else:
                return TIMEOUT

async def update_delay_info(session, proxies, sampling_type):
    """Updates the delay information for all proxies in parallel."""
    tasks = []
    for proxy_name, proxy_data in proxies.items():
        if proxy_data["type"] in ("VLESS", "Trojan", "Shadowsocks", "VMess", "TUIC"):
            tasks.append(update_proxy_delay(session, proxy_name, proxy_data, sampling_type))
    await asyncio.gather(*tasks)

async def update_proxy_delay(session, proxy_name, proxy_data, sampling_type):
    """Updates the delay for a single proxy."""
    if sampling_type == "multi":
        delay = await get_real_delay_multi(session, proxy_name)
        proxy_data["delay_multi"] = delay
        print(f"Updated multi delay for {proxy_name}: {delay} ms")
    elif sampling_type == "single":
        delay = await get_real_delay_single(session, proxy_name)
        proxy_data["delay_single"] = delay
        print(f"Updated single delay for {proxy_name}: {delay} ms")

def sort_proxies_by_delay(proxies, sampling_type):
    """Sorts the proxies by their delay, excluding Direct, Reject, and DNS types."""
    sortable_proxies = [
        (proxy_name, proxy_data)
        for proxy_name, proxy_data in proxies.items()
        if proxy_data["type"] in ("VLESS", "Trojan", "Shadowsocks", "VMess", "TUIC")
    ]
    return sorted(sortable_proxies, key=lambda item: item[1].get("delay_multi" if sampling_type == "multi" else "delay_single", float("inf")))

def filter_single_working_proxies(proxies):
    working_proxies = [
        (proxy_name, proxy_data)
        for proxy_name, proxy_data in proxies.items()
        if proxy_data["type"] in ("VLESS", "Trojan", "Shadowsocks", "VMess", "TUIC")
        and proxy_data.get("delay_single", float("inf")) < TIMEOUT
    ]
    return sorted(working_proxies, key=lambda item: item[1].get("delay_single", float("inf")))

async def fallback_to_working_proxy_by_order(session, sorted_proxies):
    """Finds the first working proxy in the sorted list and switches to it."""
    for proxy_name, _ in sorted_proxies:
        try:
            async with session.get(
                f"{API_URL}/proxies/{proxy_name}/delay",
                headers=get_headers(),
                params={"timeout": TIMEOUT, "url": TEST_URL}
            ) as response:
                if response.status == 200:
                    print(f"Switching to {proxy_name}")
                    await session.put(
                        f"{API_URL}/proxies/{PROXY_GROUP_NAME}",
                        headers=get_headers(),
                        json={"name": proxy_name}
                    )
                    return
                else:
                    print(f"{proxy_name} is not responding. Trying the next one...")
        except Exception as e:
            print(f"Error checking {proxy_name}: {e}")
    print("No working proxies found.")

async def fallback_to_working_proxy_by_latency(session, sorted_proxies):
    """Finds the lowest delay working proxy in the sorted list and switches to it."""
    top_proxies = sorted_proxies[:10]
    await update_delay_info(session, dict(top_proxies), sampling_type="single")
    sorted_top_proxies = sort_proxies_by_delay(dict(top_proxies), sampling_type="single")

    proxy_name = sorted_top_proxies[0][0]
    print(f"Switching to {proxy_name}")
    await session.put(
        f"{API_URL}/proxies/{PROXY_GROUP_NAME}",
        headers=get_headers(),
        json={"name": proxy_name}
    )

async def main():
    """Main loop for updating delay info and performing fallback."""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                proxies = await get_proxies(session)
                # Update delay info in parallel
                await update_delay_info(session, proxies, sampling_type="multi")
                sorted_proxies = sort_proxies_by_delay(proxies, sampling_type="multi")

                # Run fallback check every CHECK_INTERVAL seconds
                start_time = datetime.now()
                while datetime.now() - start_time < timedelta(seconds=UPDATE_INTERVAL):
                    await fallback_to_working_proxy_by_order(session, sorted_proxies)
                    # await fallback_to_working_proxy_by_latency(session, sorted_proxies)
                    await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"An error occurred: {e}")
                await asyncio.sleep(60)  # Wait for a minute before trying again

async def light_main():
    """Main loop for updating delay info and performing fallback."""
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                proxies = await get_proxies(session)
                await update_delay_info(session, proxies, sampling_type="single")
                working_proxies = filter_single_working_proxies(proxies)
                working_proxies = dict(working_proxies[:LIGHTMODE_MAXIMUM_SERVERS])
                await update_delay_info(session, working_proxies, sampling_type="multi")
                sorted_proxies = sort_proxies_by_delay(working_proxies, sampling_type="multi")

                # Run fallback check every CHECK_INTERVAL seconds
                start_time = datetime.now()
                while datetime.now() - start_time < timedelta(seconds=UPDATE_INTERVAL):
                    await fallback_to_working_proxy_by_order(session, sorted_proxies)
                    # await fallback_to_working_proxy_by_latency(session, sorted_proxies)
                    await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                print(f"An error occurred: {e}")
                await asyncio.sleep(60)  # Wait for a minute before trying again

if __name__ == "__main__":
    # asyncio.run(main())
    asyncio.run(light_main())
