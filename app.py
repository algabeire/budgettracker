import os
import json
import jwt
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, redirect, url_for, render_template
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
JWT_SECRET = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET") or "dev_change_me_jwt_secret"

# Local directory to simulate isolated cloud document stores
DATA_DIR = "user_budgets"
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)

# --- stateless JWT Helper Utilities ---
def create_token(user_email):
    """Generates a secure stateless token expiring in 1 day."""
    payload = {
        "identity": user_email,
        # `python-jwt` expects JSON-serializable values; use UNIX timestamp for exp
        "exp": int((datetime.datetime.utcnow() + datetime.timedelta(days=1)).timestamp())
    }
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET_KEY not set in environment")
    key = OctetJWK(JWT_SECRET.encode())
    return jwt.JWT().encode(payload, key, alg="HS256")

def get_user_from_token():
    """Decodes the JWT from cookies to identify the user without a DB lookup."""
    token = request.cookies.get("auth_token")
    if not token:
        return None
    try:
        if not JWT_SECRET:
            return None
        key = OctetJWK(JWT_SECRET.encode())
        data = jwt.JWT().decode(token, key, do_verify=True, algorithms={"HS256"})
        return data.get("identity")
    except Exception:
        return None


def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

# --- Mock Identity Provider Route ---
@app.route("/mock-login")
def mock_login():
    """Simulates a successful 3rd-party Google/OAuth callback."""
    # In production, swap this out for actual Google OAuth verification token
    simulated_username = request.args.get("username", "guest")
    
    # Issue stateless token
    token = create_token(simulated_username)
    
    # Save token in browser cookie and redirect home
    response = redirect(url_for("dashboard"))
    response.set_cookie("auth_token", token, httponly=True, samesite="Strict")
    return response


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            return render_template('register.html', error='Username and password required')
        users = load_users()
        if username in users:
            return render_template('register.html', error='User already exists')
        users[username] = generate_password_hash(password)
        save_users(users)
        # create empty budget file for user
        user_file = os.path.join(DATA_DIR, f"{username}.json")
        if not os.path.exists(user_file):
            with open(user_file, 'w') as f:
                json.dump({"income": 0, "expenses": []}, f)
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        users = load_users()
        pw_hash = users.get(username)
        if not pw_hash or not check_password_hash(pw_hash, password):
            return render_template('login.html', error='Invalid credentials')
        token = create_token(username)
        response = redirect(url_for('dashboard'))
        response.set_cookie('auth_token', token, httponly=True, samesite='Strict')
        return response
    return render_template('login.html')

@app.route("/logout")
def logout():
    """Clears the client cookie to instantly log out statelessly."""
    response = redirect(url_for("home"))
    response.delete_cookie("auth_token")
    return response

# --- Application Logic Routes ---
@app.route("/")
def home():
    user = get_user_from_token()
    if user:
        return redirect(url_for("dashboard"))
    return render_template('index.html')

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    user = get_user_from_token()
    if not user:
        return redirect(url_for("home"))
    
    # Isolate user file path cleanly by email hash/name
    user_file = os.path.join(DATA_DIR, f"{user}.json")
    
    # Initialize budget file if empty
    if not os.path.exists(user_file):
        with open(user_file, "w") as f:
            json.dump({"income": 0, "expenses": []}, f)

    # Handle item updates
    if request.method == "POST":
        # `item` field removed per request; use `description` as the primary label
        description = request.form.get("description")
        category = request.form.get("category") or "Uncategorized"
        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0.0

        with open(user_file, "r+") as f:
            data = json.load(f)
            data["expenses"].append({
                "description": description,
                "category": category,
                "amount": amount,
            })
            f.seek(0)
            json.dump(data, f)
            f.truncate()

    # Read data to display
    with open(user_file, "r") as f:
        budget_data = json.load(f)

    # Render the dashboard template from the templates/ folder
    return render_template('dashboard.html', user=user, budget_data=budget_data)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
