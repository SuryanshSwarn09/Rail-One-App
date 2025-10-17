import random
import string
from datetime import datetime, timedelta
import csv
import math
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

class RailwayReservationSystem:

    def __init__(self, db_path='railway.db'):
        self.db_path = db_path
        self._init_db()
        self.trains = self._load_trains_from_csv()
        self.booked_tickets = {}
        self.platform_tickets = {}
        self.unreserved_tickets = {}
        self.pending_tickets = {}
        self._station_coordinates = self._load_station_coordinates()
        self._station_codes = self._generate_station_codes()
        self.berth_inventory = self._generate_berth_inventory()
        self.mst_tickets = {}

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    google_id TEXT UNIQUE
                )
            ''')
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN google_id TEXT UNIQUE")
            except sqlite3.OperationalError:
                pass
            conn.commit()

    def get_user_by_id(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
            user_record = cursor.fetchone()
            if user_record:
                return User(id=user_record[0], username=user_record[1])
        return None

    def get_or_create_google_user(self, user_info):
        user_id = user_info['id']
        username = user_info['name']
        is_username_taken = self.get_user_by_username(username)
        if is_username_taken and not getattr(is_username_taken, 'google_id', None):
             username = f"{username}_{user_id[:4]}"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username FROM users WHERE google_id = ?", (user_id,))
            user_record = cursor.fetchone()
            if user_record:
                return User(id=user_record[0], username=user_record[1])
            else:
                try:
                    cursor.execute(
                        "INSERT INTO users (username, google_id) VALUES (?, ?)",
                        (username, user_id)
                    )
                    conn.commit()
                    new_user_id = cursor.lastrowid
                    return User(id=new_user_id, username=username)
                except sqlite3.IntegrityError:
                    return None

    def get_user_by_username(self, username):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, google_id FROM users WHERE username = ?", (username,))
            user_record = cursor.fetchone()
            if user_record:
                user = User(id=user_record[0], username=user_record[1])
                user.google_id = user_record[2]
                return user
        return None

    def create_user(self, username, password):
        password_hash = generate_password_hash(password)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def check_user(self, username, password):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password_hash FROM users WHERE username = ? AND password_hash IS NOT NULL", (username,))
            user_record = cursor.fetchone()
            if user_record and check_password_hash(user_record[2], password):
                return User(id=user_record[0], username=user_record[1])
        return None

    def book_ticket_logic(self, pnr, train_no, travel_class, passengers, user_id):
        allocated_passengers = self.allocate_berths(train_no, travel_class, passengers)
        if not allocated_passengers:
            return None
            
        train = self.trains.get(train_no)
        train_details = train['details']
        class_details = train['classes'].get(travel_class)
        
        ticket_details = {
            "pnr": pnr, 
            "user_id": user_id,
            "train_no": train_no, "train_name": train_details[0],
            "source": train_details[1], "destination": train_details[2],
            "departure": train_details[3], "arrival": train_details[4],
            "travel_class": f"{travel_class} - {class_details['name']}",
            "passengers": allocated_passengers,
            "status": "BOOKED",
            "booking_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "journey_date": (datetime.now() + timedelta(days=random.randint(1, 10))).strftime("%Y-%m-%d")
        }
        self.booked_tickets[pnr] = ticket_details
        return ticket_details

    def _load_trains_from_csv(self):
        trains_data = {}
        try:
            # IMPORTANT: Make sure this points to the new trains_with_codes.csv or your updated trains.csv
            with open('trains.csv', mode='r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    train_no = row['train_no']
                    if train_no not in trains_data:
                        trains_data[train_no] = {'details': [row['train_name'], row['source'], row['destination'], row['departure'], row['arrival']], 'classes': {}}
                    trains_data[train_no]['classes'][row['class_code']] = {'name': row['class_name'], 'seats': int(row['seats'])}
        except FileNotFoundError: return {}
        return trains_data

    def _load_station_coordinates(self):
        coordinates = {}
        try:
            with open('station_coordinates.csv', mode='r', newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    coordinates[row['station_code']] = {'name': row['station_name'], 'lat': float(row['latitude']), 'lon': float(row['longitude'])}
        except FileNotFoundError: return {}
        return coordinates

    def _generate_station_codes(self):
        codes = {}
        for code, data in self._station_coordinates.items():
            codes[data['name'].lower()] = code
            codes[code.lower()] = code
        return codes
    
    def _generate_berth_inventory(self):
        inventory = {}
        berth_types = ['LB', 'MB', 'UB', 'SLB', 'SUB']
        for train_no, train_data in self.trains.items():
            inventory[train_no] = {}
            for class_code, class_info in train_data['classes'].items():
                inventory[train_no][class_code] = {}
                seats_per_coach = 72 if class_code == 'SL' else 64
                num_coaches = math.ceil(class_info['seats'] / seats_per_coach)
                for i in range(1, num_coaches + 1):
                    coach_name = f"{class_code.replace('A', '')}{i}"
                    inventory[train_no][class_code][coach_name] = []
                    for seat_num in range(1, seats_per_coach + 1):
                        berth_info = {'number': seat_num, 'type': random.choice(berth_types)}
                        inventory[train_no][class_code][coach_name].append(berth_info)
        return inventory

    def allocate_berths(self, train_no, travel_class, passengers):
        if train_no not in self.berth_inventory or travel_class not in self.berth_inventory[train_no]:
            return None
        available_berths = self.berth_inventory[train_no][travel_class]
        updated_passengers = []
        seniors = [p for p in passengers if int(p.get('age', 0)) >= 60]
        others = [p for p in passengers if int(p.get('age', 0)) < 60]
        for senior in seniors:
            allocated = False
            for coach, berths in available_berths.items():
                for i, berth in enumerate(berths):
                    if berth['type'] == 'LB':
                        senior['coach'] = coach
                        senior['berth'] = f"{berth['number']}{berth['type']}"
                        updated_passengers.append(senior)
                        del berths[i]
                        allocated = True; break
                if allocated: break
            if not allocated: return None
        for passenger in others:
            allocated = False
            preference = passenger.get('preference')
            for coach, berths in available_berths.items():
                for i, berth in enumerate(berths):
                    if berth['type'] == preference:
                        passenger['coach'] = coach
                        passenger['berth'] = f"{berth['number']}{berth['type']}"
                        updated_passengers.append(passenger)
                        del berths[i]
                        allocated = True; break
                if allocated: break
            if not allocated:
                for coach, berths in available_berths.items():
                    if berths:
                        berth = berths.pop(0)
                        passenger['coach'] = coach
                        passenger['berth'] = f"{berth['number']}{berth['type']}"
                        updated_passengers.append(passenger)
                        allocated = True; break
            if not allocated: return None
        return updated_passengers

    def calculate_reserved_fare(self, train_no, travel_class, num_passengers):
        fare_rates = {'1A': 4.5, '2A': 2.5, '3A': 1.8, 'SL': 0.8, 'EC': 2.2, 'CC': 1.5, '2S': 0.6}
        train = self.trains.get(train_no)
        if not train: return 0
        source_name = train['details'][1].split('(')[0].strip()
        dest_name = train['details'][2].split('(')[0].strip()
        distance = self.get_distance(source_name, dest_name)
        rate = fare_rates.get(travel_class, 1.0)
        if not distance: return 0
        return round(distance * rate * num_passengers, 2)

    def get_station_list_for_autocomplete(self):
        return sorted([f"{data['name']} ({code})" for code, data in self._station_coordinates.items()])

    def get_distance(self, source_station, dest_station):
        try:
            source_code = self._station_codes.get(source_station.lower())
            dest_code = self._station_codes.get(dest_station.lower())
            if not source_code or not dest_code: return None
            source_coords = self._station_coordinates[source_code]
            dest_coords = self._station_coordinates[dest_code]
            lat1, lon1 = source_coords['lat'], source_coords['lon']
            lat2, lon2 = dest_coords['lat'], dest_coords['lon']
            R = 6371; lat1_rad, lat2_rad = math.radians(lat1), math.radians(lat2)
            delta_lat = math.radians(lat2 - lat1); delta_lon = math.radians(lon2 - lon1)
            a = math.sin(delta_lat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return int(R * c)
        except KeyError: return None

    def calculate_unreserved_fare(self, train_type, distance, adults, children):
        fares = {'MAIL': {'adult': 0.36, 'child': 0.18}, 'ORDINARY': {'adult': 0.19, 'child': 0.10}, 'SUPERFAST': {'adult': 0.39, 'child': 0.22}}
        rate = fares.get(train_type)
        if not rate: return 0
        return round((adults * rate['adult'] * distance) + (children * rate['child'] * distance), 2)

    def calculate_mst_fare(self, source_station, dest_station):
        distance = self.get_distance(source_station, dest_station)
        if not distance: return None
        return round(distance * 0.36 * 30, 2)

    def _generate_pnr(self):
        while True:
            pnr = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
            if pnr not in self.booked_tickets: return pnr

    def find_trains(self, source, destination):
        found_trains = {}
        if not source or not destination: return found_trains
        source_lower, destination_lower = source.lower(), destination.lower()
        for train_no, train_data in self.trains.items():
            train_source, train_destination = train_data['details'][1].lower(), train_data['details'][2].lower()
            if source_lower in train_source and destination_lower in train_destination:
                found_trains[train_no] = train_data
        return found_trains
