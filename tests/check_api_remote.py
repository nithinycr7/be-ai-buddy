import urllib.request
import json
import sys

# Default URL from user, but can be overridden
DEFAULT_URL = "https://backend-core-dev.internal.nicebush-580b7b55.southindia.azurecontainerapps.io"

def check_url(base_url):
    print(f"Checking API at: {base_url}")
    
    # 1. Check Health Header
    health_url = f"{base_url}/" # Assuming root is health check per main.py: @app.get("/")
    print(f"1. Testing Health Endpoint: {health_url}")
    try:
        req = urllib.request.Request(health_url)
        with urllib.request.urlopen(req) as response:
            print(f"   Status: {response.getcode()}")
            content = response.read().decode()
            print(f"   Response: {content}")
    except Exception as e:
        print(f"   FAILED: {e}")

    # 2. Check Daily Classes (requires auth usually, but we check if it's reachable)
    # Using the key from config default, user might need to change it
    api_url = f"{base_url}/api/classes/daily?class_no=8&section=A"
    print(f"\n2. Testing Daily Classes API: {api_url}")
    headers = {"x-api-key": "dev-local-key"} # Update if you changed the key in Azure
    
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as response:
            print(f"   Status: {response.getcode()}")
            data = json.loads(response.read().decode())
            print(f"   Response Data Length: {len(data) if isinstance(data, list) else 'Not a list'}")
    except urllib.error.HTTPError as e:
        print(f"   HTTP Error: {e.code} - {e.reason}")
        # print(e.read().decode())
    except Exception as e:
        print(f"   FAILED: {e}")

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    check_url(url.rstrip('/'))
