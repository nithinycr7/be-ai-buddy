
import requests
import sys

API_URL = "http://localhost:8000/api"

def check_ncert_api():
    print("Checking NCERT API...")
    
    # 1. Get Subjects for Class 6
    try:
        print("\n1. Fetching Subjects for Class 6...")
        resp = requests.get(f"{API_URL}/ncert/subjects", params={"class_no": "6"})
        if resp.status_code == 200:
            subjects = resp.json().get("subjects", [])
            print(f"SUCCESS: Found subjects: {subjects}")
            if not subjects:
                print("WARNING: No subjects found. Is DB populated?")
                return
            
            selected_subject = subjects[0]
        else:
            print(f"FAILED: Status {resp.status_code}, {resp.text}")
            return

        # 2. Get Chapters
        print(f"\n2. Fetching MChapters for Class 6, {selected_subject}...")
        resp = requests.get(f"{API_URL}/ncert/chapters", params={"class_no": "6", "subject": selected_subject})
        if resp.status_code == 200:
            chapters = resp.json().get("chapters", [])
            print(f"SUCCESS: Found {len(chapters)} chapters.")
            if chapters:
                print(f"Sample Chapter: {chapters[0]}")
                selected_chapter_id = chapters[0]['chapter_unique_id']
            else:
                print("WARNING: No chapters found.")
                return
        else:
            print(f"FAILED: Status {resp.status_code}, {resp.text}")
            return

        # 3. Get Topics
        print(f"\n3. Fetching Topics for Chapter ID: {selected_chapter_id}...")
        resp = requests.get(f"{API_URL}/ncert/topics", params={"chapter_unique_id": selected_chapter_id})
        if resp.status_code == 200:
            topics = resp.json().get("topics", [])
            print(f"SUCCESS: Found {len(topics)} topics.")
            if topics:
                print(f"Sample Topic: {topics[0]}")
        else:
            print(f"FAILED: Status {resp.status_code}, {resp.text}")
            return
            
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to backend. Is it running on port 8000?")

if __name__ == "__main__":
    check_ncert_api()
