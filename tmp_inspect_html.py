import requests
import re

url = 'https://www.comingsoon.it/cinema/boxoffice/'
headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.get(url, timeout=30, headers=headers)
text = r.text
print('status', r.status_code)
print('final_url', r.url)
for match in re.finditer(r'https?://[^"\'\s<>]+', text):
    href = match.group(0)
    if 'boxoffice' in href.lower() or 'cinema' in href.lower():
        if 'comingsoon.it' in href:
            print(href)
