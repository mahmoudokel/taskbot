from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from dotenv import load_dotenv
import openai

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///taskbot.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-key')
openai.api_key = os.getenv('OPENAI_API_KEY')

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    tasks = db.relationship('Task', backref='user', lazy=True)
    notes = db.relationship('Note', backref='user', lazy=True)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    is_void = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Debug routes
@app.route('/debug-users')
def debug_users():
    users = User.query.all()
    return jsonify([{'id': user.id, 'username': user.username} for user in users])

@app.route('/init-db')
def initialize_database():
    with app.app_context():
        db.drop_all()
        db.create_all()
        
        # Create admin user
        admin = User(
            username='taskbot_admin',
            password_hash=generate_password_hash('admin123456')
        )
        db.session.add(admin)
        db.session.commit()
    return 'Database initialized with admin user'

# Main routes
@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    print(f"Login attempt for username: {data.get('username')}")  # Debug log
    
    user = User.query.filter_by(username=data['username']).first()
    if not user:
        print("User not found")  # Debug log
        return jsonify({'success': False, 'message': 'User not found'}), 401
    
    if not check_password_hash(user.password_hash, data['password']):
        print("Invalid password")  # Debug log
        return jsonify({'success': False, 'message': 'Invalid password'}), 401
    
    session['user_id'] = user.id
    print(f"Login successful for user ID: {user.id}")  # Debug log
    return jsonify({'success': True, 'message': 'Login successful'})

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

# Task routes
@app.route('/api/tasks', methods=['POST'])
def create_task():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    task = Task(
        description=data['description'],
        user_id=session['user_id']
    )
    db.session.add(task)
    db.session.commit()
    return jsonify({'message': 'Task created', 'id': task.id})

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    status = request.args.get('status')
    if status:
        tasks = Task.query.filter_by(user_id=session['user_id'], status=status).all()
    else:
        tasks = Task.query.filter_by(user_id=session['user_id']).all()
    
    return jsonify([{
        'id': task.id,
        'description': task.description,
        'status': task.status,
        'created_at': task.created_at.isoformat()
    } for task in tasks])

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    task = Task.query.filter_by(id=task_id, user_id=session['user_id']).first_or_404()
    data = request.json
    if 'description' in data:
        task.description = data['description']
    if 'status' in data:
        task.status = data['status']
    db.session.commit()
    return jsonify({'message': 'Task updated'})

# Note routes
@app.route('/api/notes', methods=['POST'])
def create_note():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    note = Note(
        content=data['content'],
        user_id=session['user_id']
    )
    db.session.add(note)
    db.session.commit()
    return jsonify({'message': 'Note created', 'id': note.id})

@app.route('/api/notes', methods=['GET'])
def get_notes():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    notes = Note.query.filter_by(
        user_id=session['user_id'],
        is_void=False
    ).all()
    
    return jsonify([{
        'id': note.id,
        'content': note.content,
        'created_at': note.created_at.isoformat()
    } for note in notes])

@app.route('/api/notes/<int:note_id>/void', methods=['PUT'])
def void_note(note_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    note = Note.query.filter_by(id=note_id, user_id=session['user_id']).first_or_404()
    note.is_void = True
    db.session.commit()
    return jsonify({'message': 'Note voided'})

if __name__ == '__main__':
    app.run(debug=True)