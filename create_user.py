from app import app, db, User
from werkzeug.security import generate_password_hash
import secrets

# Generate a secure secret key
secret_key = secrets.token_urlsafe(32)
print("\nYour SECRET_KEY for Render:")
print(secret_key)

with app.app_context():
    # Create tables
    db.create_all()
    
    # Create user
    new_user = User(
        username='admin',
        password_hash=generate_password_hash('your_password')
    )
    
    # Add to database
    db.session.add(new_user)
    db.session.commit()
    print("\nUser created successfully!")