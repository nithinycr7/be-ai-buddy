import urllib.request
import json

url = "http://localhost:8000/api/classes/daily?class_no=8&section=A"
headers = {"x-api-key": "dev-local-key"}

req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req) as response:
        print("Status Code:", response.getcode())
        data = json.loads(response.read().decode())
        if isinstance(data, list) and len(data) > 0:
            print("First item keys:", list(data[0].keys()))
            print("First item _id:", data[0].get("_id"))
            print("First item id:", data[0].get("id"))
        else:
            print("Data is empty or not a list:", data)
except Exception as e:
    print("Request failed:", e)
