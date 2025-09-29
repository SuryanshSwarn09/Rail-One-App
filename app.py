from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
from reservation_system import RailwayReservationSystem
from datetime import datetime, time, timedelta
import random
from functools import wraps
import qrcode
import io
import uuid

app = Flask(__name__)
app.secret_key = 'a_very_secret_key_for_sessions'

# Initialize the reservation system
system = RailwayReservationSystem(db_path='railway.db')

def login_required(f):
    """Decorator to ensure a user is logged in before accessing a page."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'username' in session: return redirect(url_for('landing_page'))
    if request.method == 'POST':
        name = request.form.get('name')
        password = request.form.get('password')
        if not name or not password:
            flash("Username and password are required.", "error")
        elif system.create_user(name, password):
            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for('login'))
        else:
            flash("Username already exists. Please choose a different one.", "error")
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session: return redirect(url_for('landing_page'))
    if request.method == 'POST':
        name, password = request.form.get('name'), request.form.get('password')
        if system.check_user(name, password):
            session['username'] = name
            flash(f"Welcome back, {name.title()}!", "success")
            return redirect(url_for('landing_page'))
        else:
            flash("Invalid username or password. Please try again.", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash("You have been logged out successfully.", "success")
    return redirect(url_for('login'))

# --- NEW PAYMENT ROUTE ---
@app.route('/payment/<ticket_type>/<temp_id>', methods=['GET', 'POST'])
@login_required
def payment(ticket_type, temp_id):
    pending_ticket = system.pending_tickets.get(temp_id)
    if not pending_ticket:
        flash("Your booking session has expired. Please try again.", "error")
        return redirect(url_for('landing_page'))

    amount = 0
    if ticket_type == 'reserved':
        amount = system.calculate_reserved_fare(
            pending_ticket['train_no'],
            pending_ticket['travel_class_code'],
            len(pending_ticket.get('passengers', []))
        )
    else:
        amount = pending_ticket.get('total_fare') or pending_ticket.get('total_price')

    if request.method == 'POST':
        del system.pending_tickets[temp_id]
        if ticket_type == 'reserved':
            pnr = system._generate_pnr()
            ticket_details = system.book_ticket_logic(
                pnr,
                pending_ticket['train_no'],
                pending_ticket['travel_class_code'],
                pending_ticket['passengers']
            )
            if ticket_details:
                flash("Payment successful! Ticket booked.", "success")
                return redirect(url_for('view_ticket', pnr=pnr))
            else:
                flash("Booking failed after payment (seats may have become unavailable).", "error")
                return redirect(url_for('reserved_booking'))
        else:
            ticket_id = pending_ticket['ticket_id']
            if ticket_type == 'unreserved':
                system.unreserved_tickets[ticket_id] = pending_ticket
                flash("Payment successful! Ticket booked.", "success")
                return redirect(url_for('view_unreserved_ticket', ticket_id=ticket_id))
            elif ticket_type == 'platform':
                system.platform_tickets[ticket_id] = pending_ticket
                flash("Payment successful! Ticket booked.", "success")
                return redirect(url_for('view_platform_ticket', ticket_id=ticket_id))
            elif ticket_type == 'mst':
                system.mst_tickets[ticket_id] = pending_ticket
                flash("Payment successful! MST booked.", "success")
                return redirect(url_for('view_mst_ticket', ticket_id=ticket_id))

    return render_template('payment.html', amount=round(amount, 2))


@app.route('/')
@login_required
def landing_page():
    return render_template('landing_page.html', username=session.get('username'))

@app.route('/my_bookings')
@login_required
def my_bookings():
    return render_template('my_bookings.html',
                           reserved_tickets=system.booked_tickets,
                           unreserved_tickets=system.unreserved_tickets,
                           platform_tickets=system.platform_tickets,
                           mst_tickets=system.mst_tickets)

@app.route('/reserved_booking', methods=['GET', 'POST'])
@login_required
def reserved_booking():
    if request.method == 'POST':
        source, destination = request.form.get('source', '').strip(), request.form.get('destination', '').strip()
        found_trains = system.find_trains(source, destination)
        if not found_trains:
            flash(f"No trains found for that route.", "info")
        return render_template('trains.html', trains=found_trains, search_query=(source, destination))
    station_list = system.get_station_list_for_autocomplete()
    return render_template('reserved_booking_flow.html', stations=station_list)

@app.route('/book/details/<train_no>', methods=['GET', 'POST'])
@login_required
def enter_passenger_details(train_no):
    train = system.trains.get(train_no)
    if not train:
        flash("Invalid train number.", "error")
        return redirect(url_for('reserved_booking'))
    if request.method == 'POST':
        travel_class = request.form.get('travel_class')
        passengers = []
        i = 0
        while f'name_{i}' in request.form:
            name, age, gender = request.form.get(f'name_{i}'), request.form.get(f'age_{i}'), request.form.get(f'gender_{i}')
            if not all([name, age, gender]):
                flash("All fields are required for each passenger.", "error")
                return render_template('passenger_details.html', train_no=train_no, train=train)
            passengers.append({'name': name, 'age': age, 'gender': gender})
            i += 1

        if not passengers:
            flash("You must add at least one passenger.", "error")
            return render_template('passenger_details.html', train_no=train_no, train=train)

        temp_id = str(uuid.uuid4())
        system.pending_tickets[temp_id] = {'train_no': train_no, 'travel_class_code': travel_class, 'passengers': passengers}
        return redirect(url_for('payment', ticket_type='reserved', temp_id=temp_id))
    return render_template('passenger_details.html', train_no=train_no, train=train)

@app.route('/unreserved_ticket', methods=['GET', 'POST'])
@login_required
def unreserved_ticket_search():
    if request.method == 'POST':
        source, destination = request.form.get('source_station', '').strip(), request.form.get('dest_station', '').strip()
        distance = system.get_distance(source, destination)
        if distance:
            return redirect(url_for('unreserved_ticket_booking', source=source, destination=destination, dist=distance))
        else:
            flash(f"Sorry, we couldn't calculate the distance for that route.", "error")
    station_list = system.get_station_list_for_autocomplete()
    return render_template('unreserved_search.html', stations=station_list)


@app.route('/unreserved_ticket/book', methods=['GET', 'POST'])
@login_required
def unreserved_ticket_booking():
    source, destination = request.args.get('source'), request.args.get('destination')
    distance = request.args.get('dist', type=int)
    if not all([source, destination, distance is not None]):
        return redirect(url_for('unreserved_ticket_search'))
    if request.method == 'POST':
        train_type, adults, children = request.form.get('train_type'), request.form.get('num_adults', type=int, default=0), request.form.get('num_children', type=int, default=0)
        if not train_type or (adults + children) == 0:
            flash("Please select a train type and at least one passenger.", "error")
            return redirect(url_for('unreserved_ticket_booking', source=source, destination=destination, dist=distance))
        
        total_fare = system.calculate_unreserved_fare(train_type, distance, adults, children)
        temp_id = str(uuid.uuid4())
        ticket_id = f"UNRS-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
        system.pending_tickets[temp_id] = { 'ticket_id': ticket_id, 'source': source, 'destination': destination, 'distance': distance, 'train_type': train_type, 'adults': adults, 'children': children, 'total_fare': total_fare, 'booking_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'status': 'BOOKED' }
        return redirect(url_for('payment', ticket_type='unreserved', temp_id=temp_id))
    return render_template('unreserved_booking.html', source=source, destination=destination, distance=distance)

@app.route('/platform_ticket', methods=['GET', 'POST'])
@login_required
def platform_ticket_booking():
    if request.method == 'POST':
        station_name, num_persons = request.form.get('station_name', '').strip(), request.form.get('num_persons', type=int, default=0)
        if not station_name or num_persons <= 0:
            flash("Please enter a valid station name and number of persons.", "error")
            return redirect(url_for('platform_ticket_booking'))

        total_price = num_persons * 10
        temp_id = str(uuid.uuid4())
        ticket_id = f"PLAT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
        system.pending_tickets[temp_id] = { 'ticket_id': ticket_id, 'station_name': station_name, 'num_persons': num_persons, 'total_price': total_price, 'booking_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'status': 'CONFIRMED' }
        return redirect(url_for('payment', ticket_type='platform', temp_id=temp_id))
    return render_template('platform_booking.html')

@app.route('/mst_booking', methods=['GET', 'POST'])
@login_required
def mst_booking():
    """Handles the MST booking form."""
    if request.method == 'POST':
        source = request.form.get('source_station', '').strip()
        destination = request.form.get('dest_station', '').strip()
        passenger_name = request.form.get('passenger_name', '').strip()
        passenger_age = request.form.get('passenger_age') # Get new field
        phone_number = request.form.get('phone_number') # Get new field

        if not all([source, destination, passenger_name, passenger_age, phone_number]):
            flash("All fields are required.", "error")
            return redirect(url_for('mst_booking'))
        
        fare = system.calculate_mst_fare(source, destination)
        if fare is None:
            flash("Could not calculate fare for the selected route. Please try another.", "error")
            return redirect(url_for('mst_booking'))
        
        temp_id = str(uuid.uuid4())
        valid_from = datetime.now()
        valid_until = valid_from + timedelta(days=30)
        
        ticket_id = f"MST-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(100, 999)}"
        system.pending_tickets[temp_id] = {
            'ticket_id': ticket_id, 'source': source, 'destination': destination,
            'passenger_name': passenger_name, 
            'passenger_age': passenger_age, # Add to pending ticket
            'phone_number': phone_number, # Add to pending ticket
            'total_fare': fare,
            'valid_from': valid_from.strftime("%Y-%m-%d"),
            'valid_until': valid_until.strftime("%Y-%m-%d"),
            'status': 'BOOKED'
        }
        return redirect(url_for('payment', ticket_type='mst', temp_id=temp_id))

    station_list = system.get_station_list_for_autocomplete()
    return render_template('mst_booking.html', stations=station_list)


@app.route('/trains')
@login_required
def show_trains():
    return render_template('trains.html', trains=system.trains)

@app.route('/ticket/<pnr>')
@login_required
def view_ticket(pnr):
    ticket = system.booked_tickets.get(pnr)
    if not ticket:
        flash("Invalid PNR number.", "error")
        return redirect(url_for('my_bookings'))
    return render_template('ticket.html', ticket=ticket)

@app.route('/unreserved_ticket/view/<ticket_id>')
@login_required
def view_unreserved_ticket(ticket_id):
    ticket = system.unreserved_tickets.get(ticket_id)
    if not ticket:
        flash("Invalid unreserved ticket ID.", "error")
        return redirect(url_for('my_bookings'))
    return render_template('unreserved_ticket.html', ticket=ticket)

@app.route('/platform_ticket/view/<ticket_id>')
@login_required
def view_platform_ticket(ticket_id):
    ticket = system.platform_tickets.get(ticket_id)
    if not ticket:
        flash("Invalid platform ticket ID.", "error")
        return redirect(url_for('my_bookings'))
    return render_template('platform_ticket.html', ticket=ticket)

@app.route('/mst_ticket/view/<ticket_id>')
@login_required
def view_mst_ticket(ticket_id):
    ticket = system.mst_tickets.get(ticket_id)
    if not ticket:
        flash("Invalid MST ticket ID.", "error")
        return redirect(url_for('my_bookings'))
    return render_template('mst_ticket.html', ticket=ticket)

@app.route('/check_pnr', methods=['GET', 'POST'])
@login_required
def check_pnr():
    if request.method == 'POST':
        pnr = request.form.get('pnr', '').strip()
        if pnr in system.booked_tickets:
            return redirect(url_for('view_ticket', pnr=pnr))
        else:
            flash("Please enter a valid PNR number.", "error")
    return render_template('pnr_form.html')

@app.route('/cancel', methods=['GET', 'POST'])
@login_required
def cancel():
    if request.method == 'POST':
        pnr = request.form.get('pnr', '').strip()
        ticket = system.booked_tickets.get(pnr)
        if ticket and ticket['status'] != 'CANCELLED':
            train_no, travel_class_code, num_passengers = ticket['train_no'], ticket['travel_class'].split(' - ')[0], len(ticket['passengers'])
            system.trains[train_no]['classes'][travel_class_code]['seats'] += num_passengers
            system.booked_tickets[pnr]['status'] = 'CANCELLED'
            flash(f"Ticket with PNR {pnr} has been cancelled.", "success")
            return redirect(url_for('view_ticket', pnr=pnr))
        else:
            flash("Invalid PNR number or ticket already cancelled.", "error")
    return render_template('cancel_form.html')

@app.route('/ticket/print/<pnr>')
@login_required
def print_ticket_page(pnr):
    ticket = system.booked_tickets.get(pnr)
    if not ticket:
        flash("Invalid PNR number.", "error")
        return redirect(url_for('landing_page'))
    return render_template('printable_ticket.html', ticket=ticket)

@app.route('/unreserved_ticket/print/<ticket_id>')
@login_required
def print_unreserved_ticket(ticket_id):
    ticket = system.unreserved_tickets.get(ticket_id)
    if not ticket:
        flash("Invalid unreserved ticket ID.", "error")
        return redirect(url_for('landing_page'))
    return render_template('printable_unreserved_ticket.html', ticket=ticket)

@app.route('/platform_ticket/print/<ticket_id>')
@login_required
def print_platform_ticket(ticket_id):
    ticket = system.platform_tickets.get(ticket_id)
    if not ticket:
        flash("Invalid platform ticket ID.", "error")
        return redirect(url_for('landing_page'))
    return render_template('printable_platform_ticket.html', ticket=ticket)

@app.route('/mst_ticket/print/<ticket_id>')
@login_required
def print_mst_ticket(ticket_id):
    ticket = system.mst_tickets.get(ticket_id)
    if not ticket:
        flash("Invalid MST ticket ID.", "error")
        return redirect(url_for('my_bookings'))
    return render_template('printable_mst_ticket.html', ticket=ticket)

@app.route('/qr_code/<ticket_type>/<ticket_id>')
@login_required
def generate_qr_code(ticket_type, ticket_id):
    qr_data = "No ticket data available."
    if ticket_type == 'reserved':
        ticket = system.booked_tickets.get(ticket_id)
        if ticket:
            passengers = ", ".join([p['name'] for p in ticket['passengers']])
            qr_data = (f"Type: Reserved\nPNR: {ticket['pnr']}\nStatus: {ticket['status']}\nTrain: {ticket['train_no']} - {ticket['train_name']}\nFrom: {ticket['source']} To: {ticket['destination']}\nPassengers: {passengers}")
    elif ticket_type == 'unreserved':
        ticket = system.unreserved_tickets.get(ticket_id)
        if ticket:
            qr_data = (f"Type: Unreserved\nID: {ticket['ticket_id']}\nFrom: {ticket['source']} To: {ticket['destination']}\nFare: Rs. {ticket['total_fare']:.2f}")
    elif ticket_type == 'platform':
        ticket = system.platform_tickets.get(ticket_id)
        if ticket:
            qr_data = (f"Type: Platform\nID: {ticket['ticket_id']}\nStation: {ticket['station_name']}\nPersons: {ticket['num_persons']}")
    elif ticket_type == 'mst':
        ticket = system.mst_tickets.get(ticket_id)
        if ticket:
            qr_data = (f"Type: MST\nID: {ticket['ticket_id']}\n"
                       f"Passenger: {ticket['passenger_name']}, Age: {ticket['passenger_age']}\n"
                       f"Phone: {ticket['phone_number']}\n"
                       f"From: {ticket['source']} To: {ticket['destination']}\n"
                       f"Valid Until: {ticket['valid_until']}")
            
    img = qrcode.make(qr_data)
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return Response(buf, mimetype='image/png')

if __name__ == '__main__':
    app.run(debug=True)