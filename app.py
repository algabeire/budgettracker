import os
import json
import jwt
import datetime
import uuid
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
    # Support both PyJWT and python-jwt at runtime so deploys work across envs.
    # PyJWT exposes a module-level `encode` function, while python-jwt exposes
    # a `JWT` class and requires `OctetJWK` for symmetric keys.
    if hasattr(jwt, "encode"):
        # PyJWT
        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    else:
        # python-jwt
        from jwt.jwk import OctetJWK
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
        if hasattr(jwt, "decode") and hasattr(jwt, "encode"):
            # PyJWT
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            return data.get("identity")
        else:
            # python-jwt
            from jwt.jwk import OctetJWK
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
            # include last_reset to track monthly cycles (YYYY-MM)
            json.dump({"income": 0, "expenses": [], "last_reset": datetime.date.today().strftime("%Y-%m")}, f)

    # Load and possibly perform monthly reset if month changed
    with open(user_file, "r+") as f:
        data = json.load(f)
        current_month = datetime.date.today().strftime("%Y-%m")
        if data.get("last_reset") != current_month:
            # reset cycle for new month
            data["income"] = 0
            data["expenses"] = []
            data["last_reset"] = current_month
            f.seek(0)
            json.dump(data, f)
            f.truncate()

    # Handle item updates (create or edit)
    if request.method == "POST":
        description = request.form.get("description")
        category = request.form.get("category") or "Uncategorized"
        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0.0

        edit_id = request.form.get("edit_id")

        with open(user_file, "r+") as f:
            data = json.load(f)
            if edit_id:
                # find and update existing expense
                for e in data.get("expenses", []):
                    if e.get("id") == edit_id:
                        e["description"] = description
                        e["category"] = category
                        e["amount"] = amount
                        e["date"] = datetime.datetime.utcnow().isoformat()
                        break
            else:
                # append new expense with unique id
                new_exp = {
                    "id": uuid.uuid4().hex,
                    "description": description,
                    "category": category,
                    "amount": amount,
                    "date": datetime.datetime.utcnow().isoformat(),
                }
                data.setdefault("expenses", []).append(new_exp)
            f.seek(0)
            json.dump(data, f)
            f.truncate()

    # Read data to display
    with open(user_file, "r") as f:
        budget_data = json.load(f)

    # If the user is requesting to edit an expense, locate it and pass to template
    edit_id = request.args.get("edit_id")
    expense_to_edit = None
    if edit_id:
        for e in budget_data.get("expenses", []):
            if e.get("id") == edit_id:
                expense_to_edit = e
                break

    # Render the dashboard template from the templates/ folder
    return render_template('dashboard.html', user=user, budget_data=budget_data, expense_to_edit=expense_to_edit)


@app.route('/expense/delete', methods=['POST'])
def delete_expense():
    user = get_user_from_token()
    if not user:
        return redirect(url_for('home'))
    exp_id = request.form.get('id')
    user_file = os.path.join(DATA_DIR, f"{user}.json")
    if os.path.exists(user_file):
        with open(user_file, 'r+') as f:
            data = json.load(f)
            data['expenses'] = [e for e in data.get('expenses', []) if e.get('id') != exp_id]
            f.seek(0)
            json.dump(data, f)
            f.truncate()
    return redirect(url_for('dashboard'))


@app.route('/expense/edit', methods=['POST'])
def edit_expense():
    # This endpoint simply redirects to dashboard with ?edit_id= to prefill the form
    user = get_user_from_token()
    if not user:
        return redirect(url_for('home'))
    exp_id = request.form.get('id')
    if not exp_id:
        return redirect(url_for('dashboard'))
    return redirect(url_for('dashboard', edit_id=exp_id))

if __name__ == "__main__":
    app.run(debug=True, port=5000)
