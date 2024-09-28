# app.py

from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, join_room
from threading import Thread
import datetime
import ctypes
import logging

# Initialize Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask and SocketIO
app = Flask(__name__)
app.config["MONGO_URI"] = "mongodb+srv://<username>:<password>@cluster0.mongodb.net/smart_city?retryWrites=true&w=majority"  # Replace with your MongoDB Atlas URI
mongo = PyMongo(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Load C++ Shared Library
calculator = ctypes.CDLL('./libcalculator.so')
calculator.add.argtypes = [ctypes.c_int, ctypes.c_int]
calculator.add.restype = ctypes.c_int

# Create Indexes
mongo.db.users.create_index("email", unique=True)
mongo.db.votes.create_index([("event_id", 1), ("vote", 1)])
mongo.db.results.create_index("event_id", unique=True)

# User Registration
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if mongo.db.users.find_one({"email": data['email']}):
        logger.warning(f"Registration attempt with existing email: {data['email']}")
        return jsonify({"error": "User already exists"}), 409

    hashed_password = generate_password_hash(data['password'])
    user = {
        "username": data['username'],
        "email": data['email'],
        "password_hash": hashed_password,
        "registered_at": datetime.datetime.utcnow()
    }
    mongo.db.users.insert_one(user)
    logger.info(f"User registered: {data['email']}")
    return jsonify({"message": "User registered successfully"}), 201

# Voting
@app.route('/vote', methods=['POST'])
def vote():
    data = request.get_json()
    user = mongo.db.users.find_one({"email": data['email']})
    if not user:
        logger.error(f"Vote attempt by non-existent user: {data['email']}")
        return jsonify({"error": "User not found"}), 404

    vote = {
        "user_id": user['_id'],
        "event_id": data['event_id'],
        "vote": data['vote'],
        "voted_at": datetime.datetime.utcnow()
    }
    mongo.db.votes.insert_one(vote)
    logger.info(f"Vote recorded for user {data['email']} on event {data['event_id']}")
    return jsonify({"message": "Vote recorded"}), 200

# Trigger Result Calculation
@app.route('/calculate_results/<event_id>', methods=['POST'])
def trigger_calculate_results(event_id):
    thread = Thread(target=calculate_results, args=(event_id,))
    thread.start()
    logger.info(f"Result calculation started for event {event_id}")
    return jsonify({"message": "Result calculation started"}), 202

# Calculate Results Function
def calculate_results(event_id):
    votes = list(mongo.db.votes.find({"event_id": event_id}))
    result_counts = {}
    for vote in votes:
        option = vote['vote']
        result_counts[option] = result_counts.get(option, 0) + 1
    result = {
        "event_id": event_id,
        "results": result_counts,
        "calculated_at": datetime.datetime.utcnow()
    }
    mongo.db.results.update_one(
        {"event_id": event_id},
        {"$set": result},
        upsert=True
    )
    socketio.emit('update', result, room=event_id)
    logger.info(f"Results calculated and emitted for event {event_id}")

# Get Results
@app.route('/results/<event_id>', methods=['GET'])
def get_results(event_id):
    results = mongo.db.results.find_one({"event_id": event_id})
    if not results:
        logger.error(f"Results not found for event {event_id}")
        return jsonify({"error": "Results not found"}), 404
    return jsonify({"results": results['results']}), 200

# WebSocket Events
@socketio.on('join')
def on_join(event_id):
    join_room(event_id)
    logger.info(f"Client joined room for event {event_id}")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
