import requests

BASE_URL = "http://localhost:8000"


def main():
    print("== SHORTEN ==")
    r = requests.post(f"{BASE_URL}/shorten", json={"url": "https://www.google.com"})
    print(r.status_code, r.json())
    code = r.json()["short_code"]

    print(f"\n== REDIRECT ({code}) ==")
    r = requests.get(f"{BASE_URL}/{code}", allow_redirects=False)
    print(r.status_code, r.headers.get("location"))

    print("\n== REDIRECT (missing code) ==")
    r = requests.get(f"{BASE_URL}/doesnotexist", allow_redirects=False)
    print(r.status_code, r.json())

    print("\n== Operation log ==")
    r = requests.get(f"{BASE_URL}/log")
    print(r.status_code, r.json())


if __name__ == "__main__":
    main()