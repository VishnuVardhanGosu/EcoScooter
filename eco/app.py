from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import uuid
import os
import boto3
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))

# AWS Credentials
AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

# AWS SNS Topic ARN
BOOKING_TOPIC_ARN = 'arn:aws:sns:us-east-1:739275443297:EcoScooterBookings'

# Global constant for scooter type prices per day
PRICE_PER_DAY = {
    'electric': 500,
    'ebike': 800,
    'solar': 1200
}

# Scooter types information for the template
SCOOTER_TYPES = {
    'electric': {
        'title': 'Electric Scooter',
        'description': 'Lightweight and nimble electric scooters perfect for short trips around the city.',
        'price': 500,
        'icon': 'bolt',
        'badge': 'Most Popular',
        'features': [
            {'icon': 'tachometer-alt', 'text': '25 km/h'},
            {'icon': 'battery-full', 'text': '30 km range'},
            {'icon': 'weight', 'text': 'Light weight'}
        ]
    },
    'ebike': {
        'title': 'E-Bike',
        'description': 'Comfortable electric bicycles for longer journeys with pedal assist technology.',
        'price': 800,
        'icon': 'bicycle',
        'badge': '',
        'features': [
            {'icon': 'tachometer-alt', 'text': '28 km/h'},
            {'icon': 'battery-full', 'text': '50 km range'},
            {'icon': 'mountain', 'text': 'All terrain'}
        ]
    },
    'solar': {
        'title': 'Solar Scooter',
        'description': 'Advanced eco-friendly scooters with solar charging capabilities for extended range.',
        'price': 1200,
        'icon': 'sun',
        'badge': 'Premium',
        'features': [
            {'icon': 'tachometer-alt', 'text': '30 km/h'},
            {'icon': 'battery-full', 'text': '70 km range'},
            {'icon': 'leaf', 'text': 'Solar powered'}
        ]
    }
}

# AWS Services Setup with explicit credentials
def get_dynamodb_resource():
    try:
        return boto3.resource(
            'dynamodb',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY
        )
    except Exception as e:
        print(f"Error creating DynamoDB resource: {str(e)}")
        return None

def get_sns_client():
    try:
        return boto3.client(
            'sns',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY
        )
    except Exception as e:
        print(f"Error creating SNS client: {str(e)}")
        return None

def init_db():
    """Initialize DynamoDB tables if they don't exist"""
    # Check if AWS credentials are available
    if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
        print("Warning: AWS credentials not found in environment variables.")
        print("Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables.")
        return
    
    try:
        dynamodb = get_dynamodb_resource()
        existing_tables = [table.name for table in dynamodb.tables.all()]
        
        if 'EcoUsers' not in existing_tables:
            users_table = dynamodb.create_table(
                TableName='EcoUsers',
                KeySchema=[
                    {
                        'AttributeName': 'id',
                        'KeyType': 'HASH'  # Partition key
                    }
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'id',
                        'AttributeType': 'S'
                    },
                    {
                        'AttributeName': 'email',
                        'AttributeType': 'S'
                    }
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'EmailIndex',
                        'KeySchema': [
                            {
                                'AttributeName': 'email',
                                'KeyType': 'HASH'
                            }
                        ],
                        'Projection': {
                            'ProjectionType': 'ALL'
                        },
                        'ProvisionedThroughput': {
                            'ReadCapacityUnits': 5,
                            'WriteCapacityUnits': 5
                        }
                    }
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
            # Wait for the table to be created
            users_table.meta.client.get_waiter('table_exists').wait(TableName='EcoUsers')
        
        if 'EcoBookings' not in existing_tables:
            bookings_table = dynamodb.create_table(
                TableName='EcoBookings',
                KeySchema=[
                    {
                        'AttributeName': 'booking_id',
                        'KeyType': 'HASH'  # Partition key
                    }
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'booking_id',
                        'AttributeType': 'S'
                    },
                    {
                        'AttributeName': 'user_id',
                        'AttributeType': 'S'
                    }
                ],
                GlobalSecondaryIndexes=[
                    {
                        'IndexName': 'UserIdIndex',
                        'KeySchema': [
                            {
                                'AttributeName': 'user_id',
                                'KeyType': 'HASH'
                            }
                        ],
                        'Projection': {
                            'ProjectionType': 'ALL'
                        },
                        'ProvisionedThroughput': {
                            'ReadCapacityUnits': 5,
                            'WriteCapacityUnits': 5
                        }
                    }
                ],
                ProvisionedThroughput={
                    'ReadCapacityUnits': 5,
                    'WriteCapacityUnits': 5
                }
            )
            # Wait for the table to be created
            bookings_table.meta.client.get_waiter('table_exists').wait(TableName='EcoBookings')
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        print("Application will run without database initialization.")

# Helper functions for AWS
def get_user_by_email(email):
    dynamodb = get_dynamodb_resource()
    users_table = dynamodb.Table('EcoUsers')
    
    response = users_table.query(
        IndexName='EmailIndex',
        KeyConditionExpression=Key('email').eq(email)
    )
    
    if response['Items'] and len(response['Items']) > 0:
        return response['Items'][0]
    return None

def get_user(user_id):
    dynamodb = get_dynamodb_resource()
    users_table = dynamodb.Table('EcoUsers')
    
    response = users_table.get_item(
        Key={
            'id': user_id
        }
    )
    
    if 'Item' in response:
        return response['Item']
    return None

def get_user_bookings(user_id):
    dynamodb = get_dynamodb_resource()
    bookings_table = dynamodb.Table('EcoBookings')
    
    response = bookings_table.query(
        IndexName='UserIdIndex',
        KeyConditionExpression=Key('user_id').eq(user_id)
    )
    
    return sorted(response['Items'], key=lambda x: x['created_at'], reverse=True)

def create_sns_topic(topic_name):
    """Create SNS topic if it doesn't exist and return its ARN"""
    sns_client = get_sns_client()
    
    # Check if topic already exists
    topics = sns_client.list_topics()
    for topic in topics.get('Topics', []):
        if topic_name in topic['TopicArn']:
            return topic['TopicArn']
    
    # Create new topic
    response = sns_client.create_topic(Name=topic_name)
    return response['TopicArn']

def send_notification(topic_arn, message, subject):
    """Send SNS notification"""
    sns_client = get_sns_client()
    
    try:
        response = sns_client.publish(
            TopicArn=topic_arn,
            Message=message,
            Subject=subject
        )
        return True
    except Exception as e:
        print(f"SNS notification error: {str(e)}")
        return False

# Initialize database when app starts
try:
    init_db()
except Exception as e:
    print(f"Database initialization error: {str(e)}")
    print("Application will continue running, but database features may not work properly.")

# Home Route
@app.route('/')
def home():
    return render_template('home.html')

# Register Route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        mobile_number = request.form['mobile_number']
        
        try:
            # Check if user already exists
            if get_user_by_email(email):
                flash("Email already registered. Please login.", "danger")
                return redirect(url_for('login'))
            
            # Create new user
            user_id = str(uuid.uuid4())
            
            dynamodb = get_dynamodb_resource()
            users_table = dynamodb.Table('EcoUsers')
            
            users_table.put_item(
                Item={
                    'id': user_id,
                    'name': name,
                    'email': email,
                    'password': password,  # In production, use password hashing
                    'mobile_number': mobile_number,
                    'created_at': datetime.now().isoformat()
                }
            )
            
            flash("Thanks for registering!", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
    
    return render_template('register.html')

# Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            # Get user by email
            user = get_user_by_email(email)
            
            if user and user['password'] == password:  # In production, use password verification
                session['user_id'] = user['id']
                session['username'] = user['name']
                flash("Login successful!", "success")
                return redirect(url_for('scooter_type'))
            else:
                flash("Invalid login. Please try again.", "danger")
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
    
    return render_template('login.html')

# Check Scooter types
@app.route('/scooter_type', methods=['GET', 'POST'])
def scooter_type():
    # Add current year for the footer
    now = datetime.now()
    
    if request.method == 'POST':
        scooter_type = request.form['scooter_type']  # Retrieve the scooter type from the form
        if scooter_type in SCOOTER_TYPES:
            return redirect(url_for('book', scooter_type=scooter_type))
        else:
            flash("Invalid scooter type selected.", "danger")
            return redirect(url_for('scooter_type'))

    return render_template('scooter_type.html', scooter_types=SCOOTER_TYPES, now=datetime.now())

@app.route('/book/<scooter_type>', methods=['GET', 'POST'])
def book(scooter_type):
    if 'user_id' not in session:
        flash("Please login first to book a scooter", "danger")
        return redirect(url_for('login'))
    
    # Validate scooter type
    if scooter_type not in SCOOTER_TYPES:
        flash("Invalid scooter type selected.", "danger")
        return redirect(url_for('scooter_type'))
        
    if request.method == 'GET':
        # Pass the correct price based on the scooter type to the HTML
        return render_template('booking.html', scooter_type=scooter_type, price_per_day=PRICE_PER_DAY.get(scooter_type.lower(), 0))

    if request.method == 'POST':
        try:
            # Retrieve form inputs
            check_in = request.form['check_in']
            check_out = request.form['check_out']
            special_requests = request.form['special_requests']
            payment_mode = request.form['payment_mode']
            helmet_needed = request.form.get('helmet_needed', 'no')

            # Get user ID from session
            user_id = session.get('user_id')

            # Calculate the number of days
            check_in_date = datetime.strptime(check_in, "%Y-%m-%d")
            check_out_date = datetime.strptime(check_out, "%Y-%m-%d")
            num_days = (check_out_date - check_in_date).days
            
            # Validate date range
            if num_days <= 0:
                flash("Please select a valid date range.", "danger")
                return redirect(url_for('book', scooter_type=scooter_type))

            # Get the daily rate based on the scooter type
            daily_rate = PRICE_PER_DAY.get(scooter_type.lower(), 0)
            total_price = daily_rate * num_days

            # Create unique booking ID
            booking_id = str(uuid.uuid4())
            
            # Get user details for the booking
            user = get_user(user_id)
            
            # Insert booking into DynamoDB
            dynamodb = get_dynamodb_resource()
            bookings_table = dynamodb.Table('EcoBookings')
            
            booking_item = {
                'booking_id': booking_id,
                'user_id': user_id,
                'scooter_type': scooter_type,
                'num_days': num_days,
                'pickup': check_in,
                'dropoff': check_out,
                'helmet_needed': helmet_needed,
                'special_requests': special_requests,
                'payment_mode': payment_mode,
                'total_price': Decimal(str(total_price)),
                'status': 'confirmed',
                'created_at': datetime.now().isoformat()
            }
            
            bookings_table.put_item(Item=booking_item)
            
            # Send SNS notification for booking confirmation
            if user:
                notification_message = f"""
                Booking Confirmation
                ------------------------
                Name: {user['name']}
                Email: {user['email']}
                Mobile: {user['mobile_number']}
                
                Booking Details:
                - Scooter Type: {scooter_type.capitalize()}
                - Duration: {num_days} days
                - Pickup: {check_in}
                - Dropoff: {check_out}
                - Total Price: ₹{total_price}
                
                Thank you for choosing EcoScooter!
                """
                
                send_notification(
                    BOOKING_TOPIC_ARN, 
                    notification_message, 
                    f"New Booking: {scooter_type.capitalize()} scooter for {user['name']}"
                )
            
            return redirect(url_for('thank_you'))

        except Exception as e:
            flash(f"Error creating booking: {str(e)}", "danger")
            return redirect(url_for('scooter_type'))

# Thank You Route
@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')

# My Bookings Route
@app.route('/my_bookings')
def my_bookings():
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in to view your bookings.", "danger")
        return redirect(url_for('login'))

    try:
        bookings = get_user_bookings(user_id)
        
        # Convert Decimal values to float for template rendering
        for booking in bookings:
            booking['total_price'] = float(booking['total_price'])
        
        return render_template('my_bookings.html', bookings=bookings)
    except Exception as e:
        flash(f"Error retrieving bookings: {str(e)}", "danger")
        return render_template('my_bookings.html', bookings=[])

# Add a route to cancel booking
@app.route('/cancel_booking/<booking_id>', methods=['POST'])
def cancel_booking(booking_id):
    user_id = session.get('user_id')
    if not user_id:
        flash("You need to log in to cancel bookings.", "danger")
        return redirect(url_for('login'))
    
    try:
        dynamodb = get_dynamodb_resource()
        bookings_table = dynamodb.Table('EcoBookings')
        
        # Get the booking to verify it belongs to the user
        response = bookings_table.get_item(
            Key={
                'booking_id': booking_id
            }
        )
        
        if 'Item' not in response or response['Item']['user_id'] != user_id:
            flash("Unauthorized or booking not found.", "danger")
            return redirect(url_for('my_bookings'))
        
        booking = response['Item']
        
        # Update the booking status to cancelled
        bookings_table.update_item(
            Key={
                'booking_id': booking_id
            },
            UpdateExpression='SET #status = :status, cancelled_at = :cancelled_at',
            ExpressionAttributeNames={
                '#status': 'status'  # 'status' is a reserved word in DynamoDB
            },
            ExpressionAttributeValues={
                ':status': 'cancelled',
                ':cancelled_at': datetime.now().isoformat()
            }
        )
        
        # Get user details for the notification
        user = get_user(user_id)
        if user:
            # Send SNS notification for booking cancellation
            notification_message = f"""
            Booking Cancellation
            ------------------------
            Name: {user['name']}
            Email: {user['email']}
            Mobile: {user['mobile_number']}
            
            Cancelled Booking Details:
            - Booking ID: {booking_id}
            - Scooter Type: {booking['scooter_type'].capitalize()}
            - Pickup Date: {booking['pickup']}
            - Cancellation Time: {datetime.now().isoformat()}
            
            This booking has been cancelled.
            """
            
            send_notification(
                BOOKING_TOPIC_ARN,
                notification_message,
                f"Booking Cancellation: {booking['scooter_type'].capitalize()} by {user['name']}"
            )
        
        flash("Booking cancelled successfully.", "success")
    except Exception as e:
        flash(f"Error cancelling booking: {str(e)}", "danger")
    
    return redirect(url_for('my_bookings'))

# Add a logout route
@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('home'))

# Add a route to subscribe to SNS notifications
@app.route('/subscribe', methods=['GET', 'POST'])
def subscribe():
    if request.method == 'POST':
        email = request.form['email']
        
        try:
            # Subscribe the email to the SNS topic
            sns_client = get_sns_client()
            response = sns_client.subscribe(
                TopicArn=BOOKING_TOPIC_ARN,
                Protocol='email',
                Endpoint=email
            )
            
            flash("Subscription request sent! Please check your email to confirm.", "success")
            return redirect(url_for('home'))
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
    
    return render_template('subscribe.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
