from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os, datetime, random
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///users.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

def safe_int(value, default=None):
    if value is None or value == '' or str(value).strip() == '':
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_float(value, default=0.0):
    if value is None or value == '' or str(value).strip() == '':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)
    phone_number = db.Column(db.String(15), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")
    age = db.Column(db.Integer, nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def to_dict(self):
        return {'id': self.id, 'username': self.username, 'email': self.email,
                'phone_number': self.phone_number, 'role': self.role, 'age': self.age,
                'gender': self.gender, 'location': self.location,
                'created_at': self.created_at.strftime('%Y-%m-%d') if self.created_at else 'N/A'}

class UserLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(50))
    details = db.Column(db.String(300))
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    location = db.Column(db.String(120))
    past_purchases = db.Column(db.Integer)
    coupon_history = db.Column(db.Integer)
    time_of_day = db.Column(db.String(50))
    season = db.Column(db.String(50))
    category = db.Column(db.String(120))
    result = db.Column(db.String(20))
    probability = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    admin_decision = db.Column(db.String(20), default="pending")

class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    coupon_code = db.Column(db.String(50), unique=True, nullable=False)
    coupon_type = db.Column(db.String(50), nullable=False)
    discount_value = db.Column(db.Float)
    minimum_amount = db.Column(db.Float, default=0)
    maximum_discount = db.Column(db.Float)
    category = db.Column(db.String(100))
    brand = db.Column(db.String(100))
    platform = db.Column(db.String(100))
    valid_from = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    valid_till = db.Column(db.DateTime)
    usage_limit = db.Column(db.Integer)
    used_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'title': self.title, 'coupon_code': self.coupon_code,
                'coupon_type': self.coupon_type, 'discount_value': self.discount_value,
                'category': self.category, 'brand': self.brand, 'platform': self.platform,
                'is_active': self.is_active, 'used_count': self.used_count}

    @property
    def is_available(self):
        if not self.is_active:
            return False
        if self.valid_till and datetime.datetime.utcnow() > self.valid_till:
            return False
        if self.usage_limit and self.used_count >= self.usage_limit:
            return False
        return True

class CouponApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    coupon_id = db.Column(db.Integer, db.ForeignKey("coupon.id"), nullable=False)
    prediction_id = db.Column(db.Integer, db.ForeignKey("prediction.id"))
    status = db.Column(db.String(20), default="pending")
    applied_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    used = db.Column(db.Boolean, default=False)
    used_at = db.Column(db.DateTime, nullable=True)
    message = db.Column(db.Text)
    admin_notes = db.Column(db.Text)

    user = db.relationship('User', backref='coupon_applications')
    coupon = db.relationship('Coupon', backref='applications')
    prediction = db.relationship('Prediction', backref='coupon_applications')

@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))

def simple_model_probability(age, gender_txt, location, past, coupon_hist, time_of_day, season, category):
    gender = 1 if gender_txt and gender_txt.lower().startswith("m") else 0
    loc_boost = 5 if location else 0
    time_boost = 8 if time_of_day and time_of_day.lower() in ["evening", "night"] else 0
    season_boost = 6 if season and season.lower() in ["festival", "holiday", "summer"] else 0
    cat_boost = 5 if category else 0

    score = (past * 7) + (coupon_hist * 10) + (gender * 5)
    score += loc_boost + time_boost + season_boost + cat_boost
    score += max(0, (35 - abs(35 - age)))
    return min(100, max(0, score + random.randint(-3, 3)))

def ensure_admin():
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(username="admin", email="admin@system.com", role="admin", 
                    phone_number="9999999999", age=30, gender="Male", location="India")
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin created: admin/admin123")

def create_50_plus_coupons():
    """Create 50+ diverse coupons across 10 categories"""
    if Coupon.query.count() == 0:
        print("🎫 Creating 50+ diverse coupons...")

        coupons_data = [
            # Fashion & Apparel (8 coupons)
            {'title': '20% Off Fashion Items', 'coupon_code': 'FASHION20', 'coupon_type': 'percentage', 'discount_value': 20, 'category': 'Fashion', 'brand': 'Myntra', 'platform': 'Myntra', 'description': 'Get 20% discount on fashion', 'minimum_amount': 500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 100},
            {'title': 'Flat ₹300 Off Clothing', 'coupon_code': 'CLOTH300', 'coupon_type': 'fixed', 'discount_value': 300, 'category': 'Fashion', 'brand': 'AJIO', 'platform': 'AJIO', 'description': 'Flat discount on clothing', 'minimum_amount': 1000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=25), 'usage_limit': 80},
            {'title': '30% Off Footwear', 'coupon_code': 'SHOES30', 'coupon_type': 'percentage', 'discount_value': 30, 'category': 'Fashion', 'brand': 'Adidas', 'platform': 'Myntra', 'description': 'Special footwear discount', 'minimum_amount': 800, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=20), 'usage_limit': 90},
            {'title': 'Buy 2 Get 1 T-Shirts', 'coupon_code': 'TSHIRT_B2G1', 'coupon_type': 'bogo', 'discount_value': 33, 'category': 'Fashion', 'brand': 'H&M', 'platform': 'H&M', 'description': 'BOGO on T-shirts', 'minimum_amount': 600, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=15), 'usage_limit': 70},
            {'title': '25% Off Ethnic Wear', 'coupon_code': 'ETHNIC25', 'coupon_type': 'percentage', 'discount_value': 25, 'category': 'Fashion', 'brand': 'Meesho', 'platform': 'Meesho', 'description': 'Ethnic wear discount', 'minimum_amount': 700, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=28), 'usage_limit': 85},
            {'title': '₹400 Off Jeans', 'coupon_code': 'JEANS400', 'coupon_type': 'fixed', 'discount_value': 400, 'category': 'Fashion', 'brand': 'Levis', 'platform': 'Amazon', 'description': 'Jeans special offer', 'minimum_amount': 1500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=22), 'usage_limit': 60},
            {'title': '35% Off Sarees', 'coupon_code': 'SAREE35', 'coupon_type': 'percentage', 'discount_value': 35, 'category': 'Fashion', 'brand': 'Nykaa Fashion', 'platform': 'Nykaa', 'description': 'Saree collection', 'minimum_amount': 900, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=35), 'usage_limit': 75},
            {'title': 'Flat ₹200 Off Accessories', 'coupon_code': 'ACCESS200', 'coupon_type': 'fixed', 'discount_value': 200, 'category': 'Fashion', 'brand': 'Zara', 'platform': 'Zara', 'description': 'Fashion accessories', 'minimum_amount': 600, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=18), 'usage_limit': 95},

            # Electronics (8 coupons)
            {'title': '₹500 Off Electronics', 'coupon_code': 'ELEC500', 'coupon_type': 'fixed', 'discount_value': 500, 'category': 'Electronics', 'brand': 'Amazon', 'platform': 'Amazon', 'description': 'Electronics discount', 'minimum_amount': 2000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=15), 'usage_limit': 50},
            {'title': '15% Off Laptops', 'coupon_code': 'LAPTOP15', 'coupon_type': 'percentage', 'discount_value': 15, 'category': 'Electronics', 'brand': 'HP', 'platform': 'Flipkart', 'description': 'Laptop deals', 'minimum_amount': 25000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=40), 'usage_limit': 40},
            {'title': '₹1000 Off Smartphones', 'coupon_code': 'MOBILE1000', 'coupon_type': 'fixed', 'discount_value': 1000, 'category': 'Electronics', 'brand': 'Samsung', 'platform': 'Amazon', 'description': 'Smartphone offers', 'minimum_amount': 10000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=22), 'usage_limit': 60},
            {'title': '25% Off Accessories', 'coupon_code': 'EACC25', 'coupon_type': 'percentage', 'discount_value': 25, 'category': 'Electronics', 'brand': 'Croma', 'platform': 'Croma', 'description': 'Electronic accessories', 'minimum_amount': 750, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=28), 'usage_limit': 120},
            {'title': '₹2000 Off TVs', 'coupon_code': 'TV2000', 'coupon_type': 'fixed', 'discount_value': 2000, 'category': 'Electronics', 'brand': 'LG', 'platform': 'Flipkart', 'description': 'Television discount', 'minimum_amount': 20000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=35), 'usage_limit': 30},
            {'title': '₹800 Off Headphones', 'coupon_code': 'HEAD800', 'coupon_type': 'fixed', 'discount_value': 800, 'category': 'Electronics', 'brand': 'Sony', 'platform': 'Amazon', 'description': 'Headphone deals', 'minimum_amount': 2500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=25), 'usage_limit': 85},
            {'title': '20% Off Cameras', 'coupon_code': 'CAMERA20', 'coupon_type': 'percentage', 'discount_value': 20, 'category': 'Electronics', 'brand': 'Canon', 'platform': 'Flipkart', 'description': 'Camera discount', 'minimum_amount': 15000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=45), 'usage_limit': 45},
            {'title': '₹600 Off Smartwatch', 'coupon_code': 'WATCH600', 'coupon_type': 'fixed', 'discount_value': 600, 'category': 'Electronics', 'brand': 'Apple', 'platform': 'Amazon', 'description': 'Smartwatch offer', 'minimum_amount': 8000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 65},

            # Food & Grocery (8 coupons)
            {'title': 'Free Delivery Food', 'coupon_code': 'FOODFREE', 'coupon_type': 'free_shipping', 'discount_value': 0, 'category': 'Food', 'brand': 'Swiggy', 'platform': 'Swiggy', 'description': 'No delivery charges', 'minimum_amount': 300, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=7), 'usage_limit': 200},
            {'title': '₹200 Off Grocery', 'coupon_code': 'GROCERY200', 'coupon_type': 'fixed', 'discount_value': 200, 'category': 'Grocery', 'brand': 'BigBasket', 'platform': 'BigBasket', 'description': 'Grocery shopping', 'minimum_amount': 1000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=12), 'usage_limit': 150},
            {'title': 'Buy 1 Get 1 Snacks', 'coupon_code': 'SNACKS_BOGO', 'coupon_type': 'bogo', 'discount_value': 50, 'category': 'Food', 'brand': 'Zomato', 'platform': 'Zomato', 'description': 'BOGO snacks', 'minimum_amount': 200, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=10), 'usage_limit': 180},
            {'title': '30% Off Organic', 'coupon_code': 'ORGANIC30', 'coupon_type': 'percentage', 'discount_value': 30, 'category': 'Grocery', 'brand': 'Grofers', 'platform': 'Grofers', 'description': 'Organic products', 'minimum_amount': 800, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=18), 'usage_limit': 100},
            {'title': '₹150 Off First Order', 'coupon_code': 'FIRSTORDER', 'coupon_type': 'fixed', 'discount_value': 150, 'category': 'Food', 'brand': 'Dunzo', 'platform': 'Dunzo', 'description': 'First order special', 'minimum_amount': 500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=60), 'usage_limit': 250},
            {'title': '₹100 Off Breakfast', 'coupon_code': 'BREAK100', 'coupon_type': 'fixed', 'discount_value': 100, 'category': 'Food', 'brand': 'Uber Eats', 'platform': 'Uber Eats', 'description': 'Breakfast deals', 'minimum_amount': 250, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=14), 'usage_limit': 140},
            {'title': '25% Off Beverages', 'coupon_code': 'DRINK25', 'coupon_type': 'percentage', 'discount_value': 25, 'category': 'Grocery', 'brand': 'Amazon Fresh', 'platform': 'Amazon', 'description': 'Beverage discount', 'minimum_amount': 400, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=20), 'usage_limit': 110},
            {'title': 'Flat ₹250 Off Meat', 'coupon_code': 'MEAT250', 'coupon_type': 'fixed', 'discount_value': 250, 'category': 'Grocery', 'brand': 'FreshToHome', 'platform': 'FreshToHome', 'description': 'Fresh meat', 'minimum_amount': 1200, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=15), 'usage_limit': 70},

            # Beauty & Personal Care (8 coupons)
            {'title': '30% Off Beauty', 'coupon_code': 'BEAUTY30', 'coupon_type': 'percentage', 'discount_value': 30, 'category': 'Beauty', 'brand': 'Nykaa', 'platform': 'Nykaa', 'description': 'Beauty products', 'minimum_amount': 800, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=25), 'usage_limit': 140},
            {'title': 'Flat ₹400 Off Skincare', 'coupon_code': 'SKIN400', 'coupon_type': 'fixed', 'discount_value': 400, 'category': 'Beauty', 'brand': 'Mamaearth', 'platform': 'Nykaa', 'description': 'Skincare special', 'minimum_amount': 1200, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 90},
            {'title': '40% Off Makeup', 'coupon_code': 'MAKEUP40', 'coupon_type': 'percentage', 'discount_value': 40, 'category': 'Beauty', 'brand': 'Lakme', 'platform': 'Amazon', 'description': 'Makeup products', 'minimum_amount': 600, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=20), 'usage_limit': 110},
            {'title': 'Buy 2 Get 1 Haircare', 'coupon_code': 'HAIR_B2G1', 'coupon_type': 'bogo', 'discount_value': 33, 'category': 'Beauty', 'brand': 'L\'Oreal', 'platform': 'Flipkart', 'description': 'Haircare BOGO', 'minimum_amount': 500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=15), 'usage_limit': 95},
            {'title': '₹250 Off Perfumes', 'coupon_code': 'PERFUME250', 'coupon_type': 'fixed', 'discount_value': 250, 'category': 'Beauty', 'brand': 'Bella Vita', 'platform': 'Amazon', 'description': 'Perfume discount', 'minimum_amount': 1000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=35), 'usage_limit': 75},
            {'title': '35% Off Spa Products', 'coupon_code': 'SPA35', 'coupon_type': 'percentage', 'discount_value': 35, 'category': 'Beauty', 'brand': 'The Body Shop', 'platform': 'Nykaa', 'description': 'Spa products', 'minimum_amount': 1500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=28), 'usage_limit': 60},
            {'title': '₹300 Off Grooming', 'coupon_code': 'GROOM300', 'coupon_type': 'fixed', 'discount_value': 300, 'category': 'Beauty', 'brand': 'Gillette', 'platform': 'Amazon', 'description': 'Men grooming', 'minimum_amount': 900, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=25), 'usage_limit': 85},
            {'title': '20% Off Bath Products', 'coupon_code': 'BATH20', 'coupon_type': 'percentage', 'discount_value': 20, 'category': 'Beauty', 'brand': 'Dove', 'platform': 'Flipkart', 'description': 'Bath essentials', 'minimum_amount': 400, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 130},

            # Travel & Tourism (6 coupons)
            {'title': '₹500 Off Flights', 'coupon_code': 'FLIGHT500', 'coupon_type': 'fixed', 'discount_value': 500, 'category': 'Travel', 'brand': 'MakeMyTrip', 'platform': 'MakeMyTrip', 'description': 'Flight booking', 'minimum_amount': 3000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=60), 'usage_limit': 100},
            {'title': '20% Off Hotels', 'coupon_code': 'HOTEL20', 'coupon_type': 'percentage', 'discount_value': 20, 'category': 'Travel', 'brand': 'OYO', 'platform': 'OYO', 'description': 'Hotel stay', 'minimum_amount': 2000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=45), 'usage_limit': 120},
            {'title': '₹300 Off Bus', 'coupon_code': 'BUS300', 'coupon_type': 'fixed', 'discount_value': 300, 'category': 'Travel', 'brand': 'RedBus', 'platform': 'RedBus', 'description': 'Bus booking', 'minimum_amount': 800, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 150},
            {'title': '₹1000 Off Packages', 'coupon_code': 'PACKAGE1000', 'coupon_type': 'fixed', 'discount_value': 1000, 'category': 'Travel', 'brand': 'Yatra', 'platform': 'Yatra', 'description': 'Travel packages', 'minimum_amount': 10000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=90), 'usage_limit': 80},
            {'title': '15% Off Cabs', 'coupon_code': 'CAB15', 'coupon_type': 'percentage', 'discount_value': 15, 'category': 'Travel', 'brand': 'Ola', 'platform': 'Ola', 'description': 'Cab rides', 'minimum_amount': 200, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=20), 'usage_limit': 200},
            {'title': '₹400 Off Train', 'coupon_code': 'TRAIN400', 'coupon_type': 'fixed', 'discount_value': 400, 'category': 'Travel', 'brand': 'IRCTC', 'platform': 'IRCTC', 'description': 'Train tickets', 'minimum_amount': 1000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=50), 'usage_limit': 110},

            # Home & Furniture (5 coupons)
            {'title': '40% Off Home Decor', 'coupon_code': 'HOME40', 'coupon_type': 'percentage', 'discount_value': 40, 'category': 'Home', 'brand': 'Pepperfry', 'platform': 'Pepperfry', 'description': 'Home decor', 'minimum_amount': 1500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=35), 'usage_limit': 85},
            {'title': '₹1500 Off Furniture', 'coupon_code': 'FURNITURE1500', 'coupon_type': 'fixed', 'discount_value': 1500, 'category': 'Home', 'brand': 'Urban Ladder', 'platform': 'Urban Ladder', 'description': 'Furniture discount', 'minimum_amount': 10000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=40), 'usage_limit': 50},
            {'title': '25% Off Kitchen', 'coupon_code': 'KITCHEN25', 'coupon_type': 'percentage', 'discount_value': 25, 'category': 'Home', 'brand': 'Amazon', 'platform': 'Amazon', 'description': 'Kitchen appliances', 'minimum_amount': 2000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 100},
            {'title': '₹800 Off Bedding', 'coupon_code': 'BED800', 'coupon_type': 'fixed', 'discount_value': 800, 'category': 'Home', 'brand': 'HomeTown', 'platform': 'HomeTown', 'description': 'Bedding essentials', 'minimum_amount': 3000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=25), 'usage_limit': 70},
            {'title': '30% Off Lighting', 'coupon_code': 'LIGHT30', 'coupon_type': 'percentage', 'discount_value': 30, 'category': 'Home', 'brand': 'IKEA', 'platform': 'IKEA', 'description': 'Lighting fixtures', 'minimum_amount': 1200, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=35), 'usage_limit': 90},

            # Books & Education (4 coupons)
            {'title': 'Free Shipping Books', 'coupon_code': 'BOOKFREE', 'coupon_type': 'free_shipping', 'discount_value': 0, 'category': 'Books', 'brand': 'Amazon', 'platform': 'Amazon', 'description': 'Free book delivery', 'minimum_amount': 0, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=50), 'usage_limit': 300},
            {'title': 'Buy 2 Get 1 Books', 'coupon_code': 'BOOKS_B2G1', 'coupon_type': 'bogo', 'discount_value': 33, 'category': 'Books', 'brand': 'Flipkart', 'platform': 'Flipkart', 'description': 'BOGO books', 'minimum_amount': 500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=40), 'usage_limit': 120},
            {'title': '₹200 Off Courses', 'coupon_code': 'COURSE200', 'coupon_type': 'fixed', 'discount_value': 200, 'category': 'Education', 'brand': 'Udemy', 'platform': 'Udemy', 'description': 'Online courses', 'minimum_amount': 1000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=90), 'usage_limit': 200},
            {'title': '50% Off Stationery', 'coupon_code': 'STAT50', 'coupon_type': 'percentage', 'discount_value': 50, 'category': 'Books', 'brand': 'Classmate', 'platform': 'Amazon', 'description': 'Stationery items', 'minimum_amount': 300, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 150},

            # Sports & Fitness (3 coupons)
            {'title': '50% Off Fitness', 'coupon_code': 'FITNESS50', 'coupon_type': 'percentage', 'discount_value': 50, 'category': 'Sports', 'brand': 'Decathlon', 'platform': 'Decathlon', 'description': 'Fitness equipment', 'minimum_amount': 2000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 70},
            {'title': '₹400 Off Sports Gear', 'coupon_code': 'SPORTS400', 'coupon_type': 'fixed', 'discount_value': 400, 'category': 'Sports', 'brand': 'Nike', 'platform': 'Myntra', 'description': 'Sports gear', 'minimum_amount': 1500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=25), 'usage_limit': 90},
            {'title': '30% Off Yoga', 'coupon_code': 'YOGA30', 'coupon_type': 'percentage', 'discount_value': 30, 'category': 'Sports', 'brand': 'Cult.fit', 'platform': 'Cult.fit', 'description': 'Yoga equipment', 'minimum_amount': 800, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=35), 'usage_limit': 100},

            # Health & Wellness (3 coupons)
            {'title': '₹300 Off Medicines', 'coupon_code': 'MEDS300', 'coupon_type': 'fixed', 'discount_value': 300, 'category': 'Health', 'brand': 'PharmEasy', 'platform': 'PharmEasy', 'description': 'Medicine orders', 'minimum_amount': 1000, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=60), 'usage_limit': 150},
            {'title': '25% Off Supplements', 'coupon_code': 'SUPP25', 'coupon_type': 'percentage', 'discount_value': 25, 'category': 'Health', 'brand': 'HealthKart', 'platform': 'HealthKart', 'description': 'Health supplements', 'minimum_amount': 800, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=40), 'usage_limit': 120},
            {'title': '₹200 Off Lab Tests', 'coupon_code': 'LAB200', 'coupon_type': 'fixed', 'discount_value': 200, 'category': 'Health', 'brand': 'Thyrocare', 'platform': 'Thyrocare', 'description': 'Lab test packages', 'minimum_amount': 500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=90), 'usage_limit': 180},

            # Entertainment (2 coupons)
            {'title': '₹150 Off Movies', 'coupon_code': 'MOVIE150', 'coupon_type': 'fixed', 'discount_value': 150, 'category': 'Entertainment', 'brand': 'BookMyShow', 'platform': 'BookMyShow', 'description': 'Movie tickets', 'minimum_amount': 300, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=30), 'usage_limit': 200},
            {'title': '30% Off Streaming', 'coupon_code': 'STREAM30', 'coupon_type': 'percentage', 'discount_value': 30, 'category': 'Entertainment', 'brand': 'Netflix', 'platform': 'Netflix', 'description': 'Streaming plans', 'minimum_amount': 500, 'valid_till': datetime.datetime.utcnow() + datetime.timedelta(days=60), 'usage_limit': 250}
        ]

        for c in coupons_data:
            db.session.add(Coupon(**c))
        db.session.commit()
        print(f"✅ Created {len(coupons_data)} diverse coupons!")

def log_activity(user_id, action, details):
    try:
        log = UserLog(user_id=user_id, action=action, details=details)
        db.session.add(log)
        db.session.commit()
    except:
        pass

@app.route("/")
def index():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username_or_email = request.form.get("user", "").strip()
        password = request.form.get("pass", "")

        if not username_or_email or not password:
            flash("Please enter username and password", "error")
            return redirect(url_for("login"))

        user = User.query.filter_by(username=username_or_email).first()
        if not user:
            user = User.query.filter_by(email=username_or_email).first()

        if user and user.check_password(password):
            login_user(user)
            log_activity(user.id, "login", f"Role: {user.role}")
            if user.role == "admin":
                flash(f"Welcome Admin {user.username}!", "success")
                return redirect(url_for("admin_dashboard"))
            flash(f"Welcome {user.username}!", "success")
            return redirect(url_for("user_dashboard"))

        flash("Invalid username or password", "error")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        age_str = request.form.get("age", "").strip()
        gender = request.form.get("gender", "").strip()
        location = request.form.get("location", "").strip()

        if not username or not password:
            flash("Username and password are required", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters", "error")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists", "error")
            return redirect(url_for("register"))

        age = safe_int(age_str, None)

        try:
            user = User(username=username, email=email if email else None,
                       phone_number=phone_number if phone_number else None, role="user",
                       age=age, gender=gender if gender else None,
                       location=location if location else None)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Registration successful!", "success")
            return redirect(url_for("user_dashboard"))
        except Exception as e:
            db.session.rollback()
            flash(f"Registration error: {str(e)}", "error")
    return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    log_activity(current_user.id, "logout", "Logged out")
    logout_user()
    flash("Logged out successfully", "success")
    return redirect(url_for("index"))

@app.route("/user_dashboard")
@login_required
def user_dashboard():
    if current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    last_pred = Prediction.query.filter_by(user_id=current_user.id).order_by(Prediction.created_at.desc()).first()
    total_preds = Prediction.query.filter_by(user_id=current_user.id).count()
    apps = CouponApplication.query.filter_by(user_id=current_user.id).count()
    approved = CouponApplication.query.filter_by(user_id=current_user.id, status='approved').count()
    return render_template("user_dashboard.html", last_pred=last_pred, total_predictions=total_preds,
                         applied_coupons=apps, approved_coupons=approved)

@app.route("/predict_form")
@login_required
def predict_form():
    return render_template("predict_form.html")

@app.route("/predict", methods=["POST"])
@login_required
def predict():
    age = safe_int(request.form.get("age"), current_user.age or 25)
    gender = request.form.get("gender", current_user.gender or "Male")
    location = request.form.get("location", current_user.location or "")
    past = safe_int(request.form.get("past"), 0)
    coupon_hist = safe_int(request.form.get("coupon_hist"), 0)
    time_of_day = request.form.get("time_of_day", "")
    season = request.form.get("season", "")
    category = request.form.get("category", "")

    prob = simple_model_probability(age, gender, location, past, coupon_hist, time_of_day, season, category)
    result = "Yes" if prob >= 50 else "No"

    pred = Prediction(user_id=current_user.id, age=age, gender=gender, location=location,
                     past_purchases=past, coupon_history=coupon_hist, time_of_day=time_of_day,
                     season=season, category=category, result=result, probability=prob)
    db.session.add(pred)
    db.session.commit()
    log_activity(current_user.id, "predict", f"{result} ({prob}%)")
    flash(f"Prediction: {result} ({prob}% confidence)", "success")
    return redirect(url_for("user_dashboard"))

@app.route("/browse_coupons")
@login_required
def browse_coupons():
    category = request.args.get('category', '')
    platform = request.args.get('platform', '')
    coupon_type = request.args.get('type', '')
    brand = request.args.get('brand', '')

    query = Coupon.query.filter(Coupon.is_active == True)

    if category:
        query = query.filter(Coupon.category.ilike(f'%{category}%'))
    if platform:
        query = query.filter(Coupon.platform.ilike(f'%{platform}%'))
    if coupon_type:
        query = query.filter(Coupon.coupon_type == coupon_type)
    if brand:
        query = query.filter(Coupon.brand.ilike(f'%{brand}%'))

    coupons = query.filter(
        (Coupon.valid_till.is_(None)) | (Coupon.valid_till > datetime.datetime.utcnow())
    ).order_by(Coupon.created_at.desc()).all()

    categories = db.session.query(Coupon.category).distinct().filter(Coupon.category.isnot(None)).all()
    platforms = db.session.query(Coupon.platform).distinct().filter(Coupon.platform.isnot(None)).all()
    brands = db.session.query(Coupon.brand).distinct().filter(Coupon.brand.isnot(None)).all()
    coupon_types = db.session.query(Coupon.coupon_type).distinct().all()

    applied_ids = [app.coupon_id for app in CouponApplication.query.filter_by(user_id=current_user.id).all()]

    return render_template("browse_coupons.html", coupons=coupons,
                         categories=[c[0] for c in categories],
                         platforms=[p[0] for p in platforms],
                         brands=[b[0] for b in brands],
                         coupon_types=[t[0] for t in coupon_types],
                         applied_coupon_ids=applied_ids,
                         selected_category=category,
                         selected_platform=platform,
                         selected_brand=brand,
                         selected_type=coupon_type)

@app.route("/apply_coupon/<int:coupon_id>", methods=["POST"])
@login_required
def apply_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    if not coupon.is_available:
        return jsonify({'error': 'Coupon not available'}), 400
    existing = CouponApplication.query.filter_by(user_id=current_user.id, coupon_id=coupon_id).first()
    if existing:
        return jsonify({'error': 'Already applied'}), 400
    app = CouponApplication(user_id=current_user.id, coupon_id=coupon_id)
    db.session.add(app)
    db.session.commit()
    log_activity(current_user.id, "apply_coupon", f"Applied: {coupon.title}")
    return jsonify({'success': True})

@app.route("/my_applications")
@login_required
def my_applications():
    apps = CouponApplication.query.filter_by(user_id=current_user.id).order_by(CouponApplication.applied_at.desc()).all()
    return render_template("my_applications.html", applications=apps)

@app.route("/update_profile", methods=["GET", "POST"])
@login_required
def update_profile():
    if request.method == "POST":
        current_user.username = request.form.get("username", "").strip()
        current_user.email = request.form.get("email", "").strip() or None
        current_user.phone_number = request.form.get("phone_number", "").strip() or None
        current_user.age = safe_int(request.form.get("age"), None)
        current_user.gender = request.form.get("gender", "").strip() or None
        current_user.location = request.form.get("location", "").strip() or None
        db.session.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for("user_dashboard"))
    return render_template("update_profile.html")

@app.route("/download_report")
@login_required
def download_report():
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    content = [Paragraph(f"Report for {current_user.username}", styles['Title']), Spacer(1, 12)]
    preds = Prediction.query.filter_by(user_id=current_user.id).all()
    content.append(Paragraph(f"Total Predictions: {len(preds)}", styles['Normal']))
    doc.build(content)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Report_{current_user.username}.pdf", mimetype='application/pdf')

@app.route("/mark_coupon_used/<int:app_id>", methods=["POST"])
@login_required
def mark_coupon_used(app_id):
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    app = CouponApplication.query.get_or_404(app_id)
    app.used = True
    app.used_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})

@app.route("/admin_dashboard")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        flash("Access denied", "error")
        return redirect(url_for("user_dashboard"))

    total_users = User.query.filter_by(role="user").count()
    total_coupons = Coupon.query.count()
    active_coupons = Coupon.query.filter_by(is_active=True).count()
    total_applications = CouponApplication.query.count()
    pending_applications = CouponApplication.query.filter_by(status='pending').count()
    approved_applications = CouponApplication.query.filter_by(status='approved').count()
    rejected_applications = CouponApplication.query.filter_by(status='rejected').count()
    total_predictions = Prediction.query.count()
    pending_predictions = Prediction.query.filter_by(admin_decision='pending').count()
    used_coupons = CouponApplication.query.filter_by(status='approved', used=True).count()
    unused_coupons = CouponApplication.query.filter_by(status='approved', used=False).count()

    return render_template("admin_dashboard.html",
                         total_users=total_users, total_coupons=total_coupons,
                         active_coupons=active_coupons, total_applications=total_applications,
                         pending_applications=pending_applications, approved_applications=approved_applications,
                         rejected_applications=rejected_applications, total_predictions=total_predictions,
                         pending_predictions=pending_predictions, used_coupons=used_coupons,
                         unused_coupons=unused_coupons)

@app.route("/admin/user/add", methods=["POST"])
@login_required
def admin_add_user():
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json() if request.is_json else request.form
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400
    try:
        user = User(username=username, email=email if email else None, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return jsonify({'success': True, 'message': f'User {username} added!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route("/admin/user/edit/<int:user_id>", methods=["POST"])
@login_required
def admin_edit_user(user_id):
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    user = User.query.get_or_404(user_id)
    data = request.get_json() if request.is_json else request.form
    username = data.get("username", "").strip()
    if username and username != user.username:
        if User.query.filter_by(username=username).first():
            return jsonify({'error': 'Username exists'}), 400
        user.username = username
    if data.get("email"):
        user.email = data.get("email")
    user.role = data.get("role", user.role)
    db.session.commit()
    return jsonify({'success': True})

@app.route("/admin/user/change_role/<int:user_id>", methods=["POST"])
@login_required
def admin_change_role(user_id):
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot change own role'}), 400
    user.role = "admin" if user.role == "user" else "user"
    db.session.commit()
    return jsonify({'success': True, 'new_role': user.role})

@app.route("/admin/user/delete/<int:user_id>", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route("/admin/predictions")
@login_required
def admin_predictions():
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    preds = []
    for p in Prediction.query.order_by(Prediction.created_at.desc()).all():
        user = User.query.get(p.user_id)
        preds.append({'id': p.id, 'username': user.username if user else 'Unknown',
                     'result': p.result, 'probability': p.probability, 'admin_decision': p.admin_decision})
    return jsonify({'predictions': preds})

@app.route("/admin/prediction/decide/<int:pred_id>", methods=["POST"])
@login_required
def admin_decide_prediction(pred_id):
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    pred = Prediction.query.get_or_404(pred_id)
    pred.admin_decision = request.form.get("decision", "pending")
    db.session.commit()
    return jsonify({'success': True})

@app.route("/admin/coupons")
@login_required
def admin_coupons():
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    return jsonify({'coupons': [c.to_dict() for c in Coupon.query.order_by(Coupon.created_at.desc()).all()]})

@app.route("/admin/coupon/add", methods=["POST"])
@login_required
def admin_add_coupon():
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json() if request.is_json else request.form
    coupon = Coupon(title=data.get("title"), coupon_code=data.get("coupon_code"),
                   coupon_type=data.get("coupon_type"), discount_value=safe_float(data.get("discount_value")))
    db.session.add(coupon)
    db.session.commit()
    return jsonify({'success': True})

@app.route("/admin/coupon/toggle/<int:coupon_id>", methods=["POST"])
@login_required
def admin_toggle_coupon(coupon_id):
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()
    return jsonify({'success': True})

@app.route("/admin/applications")
@login_required
def admin_applications():
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    apps = []
    for a in CouponApplication.query.order_by(CouponApplication.applied_at.desc()).all():
        apps.append({'id': a.id, 'username': a.user.username, 'coupon_code': a.coupon.coupon_code,
                    'status': a.status, 'used': a.used})
    return jsonify({'applications': apps})

@app.route("/admin/application/decide/<int:app_id>", methods=["POST"])
@login_required
def admin_decide_application(app_id):
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    app = CouponApplication.query.get_or_404(app_id)
    app.status = request.form.get("decision", "pending")
    db.session.commit()
    return jsonify({'success': True})

@app.route("/admin/coupon_usage")
@login_required
def admin_coupon_usage():
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    usage_data = []
    for app in CouponApplication.query.filter_by(status='approved').all():
        usage_data.append({
            'id': app.id, 'username': app.user.username, 'coupon_code': app.coupon.coupon_code,
            'coupon_title': app.coupon.title,
            'approved_at': app.applied_at.strftime('%Y-%m-%d %H:%M'),
            'used': app.used,
            'used_at': app.used_at.strftime('%Y-%m-%d %H:%M') if app.used_at else 'N/A'
        })
    return jsonify({'usage': usage_data})

@app.route("/admin/users")
@login_required
def admin_users():
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    return jsonify({'users': [u.to_dict() for u in User.query.all()]})

@app.route("/admin/statistics")
@login_required
def admin_statistics():
    if current_user.role != "admin":
        return jsonify({'error': 'Access denied'}), 403
    stats = {
        'total_applications': CouponApplication.query.count(),
        'approved': CouponApplication.query.filter_by(status='approved').count(),
        'rejected': CouponApplication.query.filter_by(status='rejected').count(),
        'pending': CouponApplication.query.filter_by(status='pending').count(),
        'used_coupons': CouponApplication.query.filter_by(status='approved', used=True).count(),
        'unused_coupons': CouponApplication.query.filter_by(status='approved', used=False).count()
    }
    return jsonify({'statistics': stats})

def init_db():
    with app.app_context():
        db.create_all()
        ensure_admin()
        create_50_plus_coupons()
        print("✅ Database initialized!")

if __name__ == "__main__":
    init_db()
    print("\n" + "="*60)
    print("🚀 Coupon System - ULTIMATE VERSION")
    print("="*60)
    print("📍 URL: http://127.0.0.1:5000")
    print("👤 Admin: admin / admin123")
    print("🎫 50+ Coupons Available!")
    print("="*60 + "\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
