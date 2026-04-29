
from flask import Blueprint, render_template

main_bp = Blueprint('main', __name__)

@main_bp.route("/")
def admin():
    return render_template("admin.html")

@main_bp.route("/user")
def user():
    return render_template("user.html")
