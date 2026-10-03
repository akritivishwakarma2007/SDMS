import urllib.request
import json
import urllib.error

# 1. Test wrong password
req_wrong = urllib.request.Request(
    'http://127.0.0.1:8000/auth/login',
    data=json.dumps({'username': 'admin', 'password': 'wrongpassword'}).encode(),
    headers={'Content-Type': 'application/json'}
)
try:
    urllib.request.urlopen(req_wrong)
    assert False, 'Wrong password should fail!'
except urllib.error.HTTPError as e:
    assert e.code == 401
    print('[PASS 1] Login with wrong password correctly rejected with 401')

# 2. Test login with user-configured password 'Akritiadmin'
req_correct = urllib.request.Request(
    'http://127.0.0.1:8000/auth/login',
    data=json.dumps({'username': 'admin', 'password': 'Akritiadmin'}).encode(),
    headers={'Content-Type': 'application/json'}
)
res = json.loads(urllib.request.urlopen(req_correct).read().decode())
assert 'access_token' in res
assert res['role'] == 'admin'
print('[PASS 2] Successfully authenticated admin with password Akritiadmin!')
print('Token generated:', res['access_token'][:35] + '...')

# 3. Check login form in HTML
html = urllib.request.urlopen('http://127.0.0.1:8000/').read().decode()
assert 'id="login-username" class="form-control" value="admin"' in html
assert 'id="login-password" class="form-control" value=""' in html
print('[PASS 3] Login form verified: username defaults to admin, password is completely blank.')
print('\nALL CHECKS PASSED PERFECTLY!')
