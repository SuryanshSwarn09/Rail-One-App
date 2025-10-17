from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from reservation_system import RailwayReservationSystem, User
from datetime import datetime, time, timedelta
import random
import io
import uuid
import os
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport.requests import Request as GoogleRequest
import qrcode
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = 'a_very_secret_key_for_sessions'

load_dotenv()

# Securely get your secrets from the environment
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("Google OAuth credentials not found in .env file")


CLIENT_SECRETS = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://127.0.0.1:5000/google-callback"], "javascript_origins": ["http://127.0.0.1:5000"]
    }
}
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email', 'openid']

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'error'

@login_manager.user_loader
def load_user(user_id):
    return system.get_user_by_id(int(user_id))

system = RailwayReservationSystem(db_path='railway.db')

@app.route('/')
@login_required
def landing_page():
    upcoming_ticket = None
    candidate_tickets = []
    now = datetime.now()

    for pnr, ticket in system.booked_tickets.items():
        if ticket.get('user_id') == current_user.id and ticket.get('status') == 'BOOKED':
            try:
                departure_full_str = ticket['departure']
                journey_date_str = ticket['journey_date']

                # --- THIS IS THE KEY FIX ---
                # 1. Extract ONLY the time part from the departure string.
                #    If '2025-10-01 10:52', it takes '10:52'.
                #    If '17:00', it takes '17:00'.
                time_part = departure_full_str.split(' ')[-1]

                # 2. Reliably combine the saved future journey_date with the extracted time.
                full_journey_dt_str = f"{journey_date_str} {time_part}"
                journey_dt = datetime.strptime(full_journey_dt_str, "%Y-%m-%d %H:%M")

                if journey_dt > now:
                    candidate_tickets.append((journey_dt, ticket))

            except (ValueError, KeyError):
                continue

    if candidate_tickets:
        candidate_tickets.sort(key=lambda x: x[0])
        upcoming_ticket_details = candidate_tickets[0][1]
        journey_datetime_obj = candidate_tickets[0][0]
        
        upcoming_ticket = {
            'pnr': upcoming_ticket_details['pnr'],
            'source': upcoming_ticket_details['source'],
            'destination': upcoming_ticket_details['destination'],
            'train_no': upcoming_ticket_details['train_no'],
            'train_name': upcoming_ticket_details['train_name'],
            'journey_date': journey_datetime_obj.strftime('%d %b %Y'),
            'departure_time': journey_datetime_obj.strftime('%H:%M'),
            'coach': upcoming_ticket_details['passengers'][0].get('coach', 'N/A'),
            'berth': upcoming_ticket_details['passengers'][0].get('berth', 'N/A'),
            'num_passengers': len(upcoming_ticket_details['passengers'])
        }

    return render_template('landing_page.html', username=current_user.username, upcoming_ticket=upcoming_ticket)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated: return redirect(url_for('landing_page'))
    if request.method == 'POST':
        name, password = request.form.get('name'), request.form.get('password')
        if not name or not password: flash("Username and password are required.", "error")
        elif system.create_user(name, password):
            flash("Account created successfully! Please log in.", "success"); return redirect(url_for('login'))
        else: flash("Username already exists.", "error")
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('landing_page'))
    if request.method == 'POST':
        name, password = request.form.get('name'), request.form.get('password')
        user = system.check_user(name, password)
        if user:
            login_user(user); flash(f"Welcome back, {user.username.title()}!", "success")
            next_page = request.args.get('next'); return redirect(next_page or url_for('landing_page'))
        else: flash("Invalid username or password.", "error")
    return render_template('login.html')

@app.route('/google-login')
def google_login():
    flow = Flow.from_client_config(CLIENT_SECRETS, scopes=GOOGLE_SCOPES)
    flow.redirect_uri = url_for('google_callback', _external=True)
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['google_oauth_state'] = state
    return redirect(authorization_url)

@app.route('/google-callback')
def google_callback():
    if 'google_oauth_state' not in session or session['google_oauth_state'] != request.args.get('state'):
        flash("Invalid state.", "error"); return redirect(url_for('login'))
    flow = Flow.from_client_config(CLIENT_SECRETS, scopes=GOOGLE_SCOPES)
    flow.redirect_uri = url_for('google_callback', _external=True)
    try: flow.fetch_token(authorization_response=request.url)
    except Exception as e: flash(f"Error: {e}", "error"); return redirect(url_for('login'))
    credentials = flow.credentials
    try: id_info = id_token.verify_oauth2_token(credentials.id_token, GoogleRequest(), GOOGLE_CLIENT_ID)
    except ValueError as e: flash(f"Invalid token: {e}", "error"); return redirect(url_for('login'))
    user = system.get_or_create_google_user({'id': id_info.get('sub'), 'name': id_info.get('name'), 'email': id_info.get('email')})
    if user:
        login_user(user); flash(f"Welcome, {user.username.title()}!", "success"); return redirect(url_for('landing_page'))
    else: flash("Could not log in with Google.", "error"); return redirect(url_for('login'))

@app.route('/logout')
@login_required
def logout():
    logout_user(); session.clear(); flash("Logged out successfully.", "success"); return redirect(url_for('login'))

@app.route('/payment/<ticket_type>/<temp_id>', methods=['GET', 'POST'])
@login_required
def payment(ticket_type, temp_id):
    pending_ticket = system.pending_tickets.get(temp_id)
    if not pending_ticket: flash("Session expired.", "error"); return redirect(url_for('landing_page'))
    amount = 0
    if ticket_type == 'reserved':
        amount = system.calculate_reserved_fare(pending_ticket['train_no'], pending_ticket['travel_class_code'], len(pending_ticket.get('passengers', [])))
    else: amount = pending_ticket.get('total_fare') or pending_ticket.get('total_price')
    if request.method == 'POST':
        if temp_id not in system.pending_tickets: flash("Session expired.", "error"); return redirect(url_for('landing_page'))
        del system.pending_tickets[temp_id]
        if ticket_type == 'reserved':
            pnr = system._generate_pnr()
            ticket_details = system.book_ticket_logic(pnr, pending_ticket['train_no'], pending_ticket['travel_class_code'], pending_ticket['passengers'], current_user.id)
            if ticket_details: flash("Payment successful! Ticket booked.", "success"); return redirect(url_for('view_ticket', pnr=pnr))
            else: flash("Booking failed.", "error"); return redirect(url_for('reserved_booking'))
        else:
            ticket_id = pending_ticket['ticket_id']
            if ticket_type == 'unreserved':
                system.unreserved_tickets[ticket_id] = pending_ticket; flash("Payment successful! Ticket booked.", "success"); return redirect(url_for('view_unreserved_ticket', ticket_id=ticket_id))
            elif ticket_type == 'platform':
                system.platform_tickets[ticket_id] = pending_ticket; flash("Payment successful! Ticket booked.", "success"); return redirect(url_for('view_platform_ticket', ticket_id=ticket_id))
            elif ticket_type == 'mst':
                system.mst_tickets[ticket_id] = pending_ticket; flash("Payment successful! MST booked.", "success"); return redirect(url_for('view_mst_ticket', ticket_id=ticket_id))
    return render_template('payment.html', amount=round(amount, 2))

@app.route('/my_bookings')
@login_required
def my_bookings():
    return render_template('my_bookings.html', reserved_tickets=system.booked_tickets, unreserved_tickets=system.unreserved_tickets, platform_tickets=system.platform_tickets, mst_tickets=system.mst_tickets)

@app.route('/reserved_booking', methods=['GET', 'POST'])
@login_required
def reserved_booking():
    if request.method == 'POST':
        source, destination = request.form.get('source', '').strip(), request.form.get('destination', '').strip()
        found_trains = system.find_trains(source, destination)
        if not found_trains: flash(f"No trains found.", "info")
        return render_template('trains.html', trains=found_trains, search_query=(source, destination))
    return render_template('reserved_booking_flow.html', stations=system.get_station_list_for_autocomplete())

@app.route('/book/details/<train_no>', methods=['GET', 'POST'])
@login_required
def enter_passenger_details(train_no):
    train = system.trains.get(train_no)
    if not train: flash("Invalid train.", "error"); return redirect(url_for('reserved_booking'))
    if request.method == 'POST':
        travel_class = request.form.get('travel_class'); passengers = []
        i = 0
        while f'name_{i}' in request.form:
            name, age, gender, preference = request.form.get(f'name_{i}'), request.form.get(f'age_{i}'), request.form.get(f'gender_{i}'), request.form.get(f'preference_{i}', 'ANY')
            if not all([name, age, gender]): flash("All fields required.", "error"); return render_template('passenger_details.html', train_no=train_no, train=train)
            passengers.append({'name': name, 'age': age, 'gender': gender, 'preference': preference}); i += 1
        if not passengers: flash("Add at least one passenger.", "error"); return render_template('passenger_details.html', train_no=train_no, train=train)
        temp_id = str(uuid.uuid4()); system.pending_tickets[temp_id] = {'train_no': train_no, 'travel_class_code': travel_class, 'passengers': passengers}
        return redirect(url_for('payment', ticket_type='reserved', temp_id=temp_id))
    return render_template('passenger_details.html', train_no=train_no, train=train)

@app.route('/unreserved_ticket', methods=['GET', 'POST'])
@login_required
def unreserved_ticket_search():
    if request.method == 'POST':
        source, destination = request.form.get('source_station', '').strip(), request.form.get('dest_station', '').strip()
        distance = system.get_distance(source, destination)
        if distance: return redirect(url_for('unreserved_ticket_booking', source=source, destination=destination, dist=distance))
        else: flash(f"Could not calculate distance.", "error")
    return render_template('unreserved_search.html', stations=system.get_station_list_for_autocomplete())

@app.route('/unreserved_ticket/book', methods=['GET', 'POST'])
@login_required
def unreserved_ticket_booking():
    source, destination, distance = request.args.get('source'), request.args.get('destination'), request.args.get('dist', type=int)
    if not all([source, destination, distance is not None]): return redirect(url_for('unreserved_ticket_search'))
    if request.method == 'POST':
        train_type, adults, children = request.form.get('train_type'), request.form.get('num_adults', type=int, default=0), request.form.get('num_children', type=int, default=0)
        if not train_type or (adults + children) == 0: flash("Select train type and passengers.", "error"); return redirect(url_for('unreserved_ticket_booking', source=source, destination=destination, dist=distance))
        total_fare = system.calculate_unreserved_fare(train_type, distance, adults, children)
        temp_id, ticket_id = str(uuid.uuid4()), f"UNRS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
        system.pending_tickets[temp_id] = { 'ticket_id': ticket_id, 'source': source, 'destination': destination, 'distance': distance, 'train_type': train_type, 'adults': adults, 'children': children, 'total_fare': total_fare, 'booking_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'status': 'BOOKED' }
        return redirect(url_for('payment', ticket_type='unreserved', temp_id=temp_id))
    return render_template('unreserved_booking.html', source=source, destination=destination, distance=distance)

@app.route('/platform_ticket', methods=['GET', 'POST'])
@login_required
def platform_ticket_booking():
    if request.method == 'POST':
        station_name, num_persons = request.form.get('station_name', '').strip(), request.form.get('num_persons', type=int, default=0)
        if not station_name or num_persons <= 0: flash("Enter valid details.", "error"); return redirect(url_for('platform_ticket_booking'))
        total_price = num_persons * 10; temp_id, ticket_id = str(uuid.uuid4()), f"PLAT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
        system.pending_tickets[temp_id] = { 'ticket_id': ticket_id, 'station_name': station_name, 'num_persons': num_persons, 'total_price': total_price, 'booking_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'status': 'CONFIRMED' }
        return redirect(url_for('payment', ticket_type='platform', temp_id=temp_id))
    return render_template('platform_booking.html')

@app.route('/mst_booking', methods=['GET', 'POST'])
@login_required
def mst_booking():
    if request.method == 'POST':
        source, destination, passenger_name, passenger_age, phone_number = request.form.get('source_station', '').strip(), request.form.get('dest_station', '').strip(), request.form.get('passenger_name', '').strip(), request.form.get('passenger_age'), request.form.get('phone_number')
        if not all([source, destination, passenger_name, passenger_age, phone_number]): flash("All fields are required.", "error"); return redirect(url_for('mst_booking'))
        fare = system.calculate_mst_fare(source, destination)
        if fare is None: flash("Could not calculate fare.", "error"); return redirect(url_for('mst_booking'))
        temp_id = str(uuid.uuid4()); valid_from, valid_until = datetime.now(), datetime.now() + timedelta(days=30)
        ticket_id = f"MST-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
        system.pending_tickets[temp_id] = { 'ticket_id': ticket_id, 'source': source, 'destination': destination, 'passenger_name': passenger_name, 'passenger_age': passenger_age, 'phone_number': phone_number, 'total_fare': fare, 'valid_from': valid_from.strftime("%Y-%m-%d"), 'valid_until': valid_until.strftime("%Y-%m-%d"), 'status': 'BOOKED' }
        return redirect(url_for('payment', ticket_type='mst', temp_id=temp_id))
    return render_template('mst_booking.html', stations=system.get_station_list_for_autocomplete())

@app.route('/trains')
@login_required
def show_trains(): return render_template('trains.html', trains=system.trains)

@app.route('/ticket/<pnr>')
@login_required
def view_ticket(pnr):
    ticket = system.booked_tickets.get(pnr)
    if not ticket: flash("Invalid PNR.", "error"); return redirect(url_for('my_bookings'))
    return render_template('ticket.html', ticket=ticket)

@app.route('/unreserved_ticket/view/<ticket_id>')
@login_required
def view_unreserved_ticket(ticket_id):
    ticket = system.unreserved_tickets.get(ticket_id)
    if not ticket: flash("Invalid ticket ID.", "error"); return redirect(url_for('my_bookings'))
    return render_template('unreserved_ticket.html', ticket=ticket)

@app.route('/platform_ticket/view/<ticket_id>')
@login_required
def view_platform_ticket(ticket_id):
    ticket = system.platform_tickets.get(ticket_id)
    if not ticket: flash("Invalid ticket ID.", "error"); return redirect(url_for('my_bookings'))
    return render_template('platform_ticket.html', ticket=ticket)

@app.route('/mst_ticket/view/<ticket_id>')
@login_required
def view_mst_ticket(ticket_id):
    ticket = system.mst_tickets.get(ticket_id)
    if not ticket: flash("Invalid MST ID.", "error"); return redirect(url_for('my_bookings'))
    return render_template('mst_ticket.html', ticket=ticket)

@app.route('/check_pnr', methods=['GET', 'POST'])
@login_required
def check_pnr():
    if request.method == 'POST':
        pnr = request.form.get('pnr', '').strip()
        if pnr in system.booked_tickets: return redirect(url_for('view_ticket', pnr=pnr))
        else: flash("Invalid PNR.", "error")
    return render_template('pnr_form.html')

@app.route('/cancel', methods=['GET', 'POST'])
@login_required
def cancel():
    if request.method == 'POST':
        pnr = request.form.get('pnr', '').strip()
        ticket = system.booked_tickets.get(pnr)
        if ticket and ticket['status'] != 'CANCELLED':
            ticket['status'] = 'CANCELLED'; flash(f"Ticket {pnr} cancelled.", "success")
            return redirect(url_for('view_ticket', pnr=pnr))
        else: flash("Invalid PNR or already cancelled.", "error")
    return render_template('cancel_form.html')

@app.route('/ticket/print/<pnr>')
@login_required
def print_ticket_page(pnr):
    ticket = system.booked_tickets.get(pnr)
    if not ticket: flash("Invalid PNR.", "error"); return redirect(url_for('landing_page'))
    return render_template('printable_ticket.html', ticket=ticket)

@app.route('/unreserved_ticket/print/<ticket_id>')
@login_required
def print_unreserved_ticket(ticket_id):
    ticket = system.unreserved_tickets.get(ticket_id)
    if not ticket: flash("Invalid ticket ID.", "error"); return redirect(url_for('landing_page'))
    return render_template('printable_unreserved_ticket.html', ticket=ticket)

@app.route('/platform_ticket/print/<ticket_id>')
@login_required
def print_platform_ticket(ticket_id):
    ticket = system.platform_tickets.get(ticket_id)
    if not ticket: flash("Invalid ticket ID.", "error"); return redirect(url_for('landing_page'))
    return render_template('printable_platform_ticket.html', ticket=ticket)

@app.route('/mst_ticket/print/<ticket_id>')
@login_required
def print_mst_ticket(ticket_id):
    ticket = system.mst_tickets.get(ticket_id)
    if not ticket: flash("Invalid MST ID.", "error"); return redirect(url_for('my_bookings'))
    return render_template('printable_mst_ticket.html', ticket=ticket)

@app.route('/qr_code/<ticket_type>/<ticket_id>')
@login_required
def generate_qr_code(ticket_type, ticket_id):
    qr_data = "No ticket data available."
    ticket = None
    if ticket_type == 'reserved': ticket = system.booked_tickets.get(ticket_id)
    elif ticket_type == 'unreserved': ticket = system.unreserved_tickets.get(ticket_id)
    elif ticket_type == 'platform': ticket = system.platform_tickets.get(ticket_id)
    elif ticket_type == 'mst': ticket = system.mst_tickets.get(ticket_id)
    if ticket:
        if ticket_type == 'reserved': qr_data = f"PNR: {ticket['pnr']}, Train: {ticket['train_no']}, From: {ticket['source']}, To: {ticket['destination']}"
        elif ticket_type == 'unreserved': qr_data = f"ID: {ticket['ticket_id']}, From: {ticket['source']}, To: {ticket['destination']}"
        elif ticket_type == 'platform': qr_data = f"ID: {ticket['ticket_id']}, Station: {ticket['station_name']}"
        elif ticket_type == 'mst': qr_data = f"ID: {ticket['ticket_id']}, Passenger: {ticket['passenger_name']}, Route: {ticket['source']}-{ticket['destination']}"
    img = qrcode.make(qr_data); buf = io.BytesIO(); img.save(buf); buf.seek(0)
    return Response(buf, mimetype='image/png')

if __name__ == '__main__':
    app.run(debug=True)

    

