from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import requests
from celery import Celery
import datetime

app = Flask(__name__)

# Database Configuration (PostgreSQL)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://username:password@localhost/food_recipes'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Celery Configuration (for background tasks)
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# Spoonacular API Key
SPOONACULAR_API_KEY = "YOUR_SPOONACULAR_API_KEY"
SPOONACULAR_BASE_URL = "https://api.spoonacular.com"

# Database Model (User Favorites & Expiring Items)
class UserPreference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)
    ingredient = db.Column(db.String(100), nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)

class FavoriteRecipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)
    recipe_id = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    image = db.Column(db.String(500), nullable=False)

db.create_all()

# -------------------- 1. INPUT EXPIRED INGREDIENTS --------------------

@app.route('/add_expiring_items', methods=['POST'])
def add_expiring_items():
    data = request.json
    user_id = data.get("user_id")
    ingredients = data.get("ingredients", [])

    if not user_id or not ingredients:
        return jsonify({"error": "User ID and ingredients are required"}), 400

    for item in ingredients:
        new_item = UserPreference(
            user_id=user_id,
            ingredient=item["name"],
            expiry_date=datetime.datetime.strptime(item["expiry_date"], "%Y-%m-%d").date()
        )
        db.session.add(new_item)
    db.session.commit()

    return jsonify({"message": "Expiring items added successfully"}), 201

# -------------------- 2. FETCH RECIPES BASED ON INGREDIENTS --------------------

@app.route('/get_recipes', methods=['POST'])
def get_recipes():
    data = request.json
    ingredients = ",".join(data.get("ingredients", []))

    if not ingredients:
        return jsonify({"error": "No ingredients provided"}), 400

    response = requests.get(
        f"{SPOONACULAR_BASE_URL}/recipes/findByIngredients",
        params={
            "ingredients": ingredients,
            "number": 10,
            "apiKey": SPOONACULAR_API_KEY
        }
    )

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch recipes"}), 500

    recipes = response.json()

    recipe_list = [
        {"id": recipe["id"], "title": recipe["title"], "image": recipe["image"]}
        for recipe in recipes
    ]

    return jsonify({"recipes": recipe_list})

# -------------------- 3. FETCH PREPARATION STEPS --------------------

@app.route('/get_recipe_steps', methods=['GET'])
def get_recipe_steps():
    recipe_id = request.args.get("recipe_id")

    if not recipe_id:
        return jsonify({"error": "No recipe ID provided"}), 400

    response = requests.get(
        f"{SPOONACULAR_BASE_URL}/recipes/{recipe_id}/analyzedInstructions",
        params={"apiKey": SPOONACULAR_API_KEY}
    )

    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch recipe steps"}), 500

    instructions = response.json()

    steps = []
    if instructions:
        for section in instructions:
            for step in section["steps"]:
                steps.append(step["step"])

    return jsonify({"recipe_id": recipe_id, "steps": steps})

# -------------------- 4. SAVE FAVORITE RECIPES --------------------

@app.route('/save_favorite', methods=['POST'])
def save_favorite():
    data = request.json
    user_id = data.get("user_id")
    recipe_id = data.get("recipe_id")
    title = data.get("title")
    image = data.get("image")

    if not all([user_id, recipe_id, title, image]):
        return jsonify({"error": "Missing required fields"}), 400

    favorite = FavoriteRecipe(user_id=user_id, recipe_id=recipe_id, title=title, image=image)
    db.session.add(favorite)
    db.session.commit()

    return jsonify({"message": "Recipe saved successfully"}), 201

# -------------------- 5. SCHEDULER FOR EXPIRY REMINDER --------------------

@celery.task
def send_expiry_reminder():
    today = datetime.date.today()
    expiring_items = UserPreference.query.filter(UserPreference.expiry_date == today).all()

    for item in expiring_items:
        print(f"Reminder: Your ingredient '{item.ingredient}' is expiring today!")

# Schedule the task to run daily
@celery.task
def schedule_reminder():
    send_expiry_reminder.apply_async(countdown=86400)  # Runs every 24 hours

# -------------------- RUN APP --------------------
if __name__ == '__main__':
    app.run(debug=True)
