import requests
url = 'https://ip.decodo.com/json'
# proxy = f"http://il.decodo.com:30001"
proxy = f"104.207.59.173:3129"

result = requests.get(url, proxies = {
    'http': proxy,
    'https': proxy
})
print(result.text)