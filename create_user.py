from app import app, db, User
from werkzeug.security import generate_password_hash
import secrets

with app.app_context():
    # Create tables
    db.create_all()
    
    # Create user with specific credentials
    new_user = User(
        username='admin123',  # This will be your username
        password_hash=generate_password_hash('password123')  # This will be your password
    )
    
    # Add to database
    db.session.add(new_user)
    db.session.commit()
    print("\nUser created successfully!")
    print("Username: admin123")
    print("Password: password123")