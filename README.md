### README
#### If you want to use sing box as relay (e.g in OpenVPN) then setup a simple http server in your OpenVPN server and set TEST_URL to your http://Server-IP
#### How To Run:
```
docker build -t singbox-server-selector .

docker run -d \
  -e API_URL="http://API:PORT?" \
  -e BEARER_TOKEN="TOKEN?" \
  -e TEST_URL="TESTURL?" \
  -e TIMEOUT=5000 \
  -e RETRIES=60 \
  -e RETRY_DELAY=10 \
  -e MIN_UPTIME=90 \
  -e CHECK_INTERVAL=60 \
  -e UPDATE_INTERVAL=14400 \
  -e LIGHTMODE_MAXIMUM_SERVERS=10 \
  -e PROXY_GROUP_NAME="select" \
  --name singbox-server-selector-container \
  singbox-server-selector
  ```

#### TODO: 
- Parallel fallback check
- Load balance the top 5
- Add Sampling_type for OpenVPN delay check
