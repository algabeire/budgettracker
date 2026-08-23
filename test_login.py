from app import app

with app.test_client() as c:
    # register
    r = c.post('/register', data={'username':'__testuser__','password':'secret123'})
    print('register status', r.status_code)
    # login
    r2 = c.post('/login', data={'username':'__testuser__','password':'secret123'}, follow_redirects=True)
    print('login status', r2.status_code)
    print('login data snippet:', r2.data.decode()[:400])
