import requests

s = requests.Session()
r = s.get('http://localhost:8001/')
csrftoken = s.cookies['csrftoken']
headers = {'X-CSRFToken': csrftoken}

# dummy pdf
with open('dummy.pdf', 'wb') as f:
    f.write(b'dummy content pdf' * 1024)

try:
    with open('dummy.pdf', 'rb') as f:
        files = {'file_0': f}
        data = {'message': 'ok', 'parecer_id': 1} # using any Parecer
        response = s.post('http://localhost:8001/chat/message/', files=files, data=data, headers=headers)
        print(f"Status Code: {response.status_code}")
        print(f"Content: {response.text[:200]}")
except Exception as e:
    print(f"Exception: {e}")
