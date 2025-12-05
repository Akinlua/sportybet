import requests
url = 'https://ip.decodo.com/json'
proxy = f"http://ng.decodo.com:42054"
# proxy = f"http://brd-customer-hl_3fa1037b-zone-datacenter_proxy1-country-ng:be0682squyj3@brd.superproxy.io:33335"

result = requests.get(url, proxies = {
    'http': proxy,
    'https': proxy
})
print(result.text)