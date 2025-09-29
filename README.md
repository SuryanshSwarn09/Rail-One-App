# Rail One - Railway Reservation System

Rail One is a feature-rich, simulated Indian Railway ticket booking system built with Python and Flask. It provides a complete user journey, from creating an account to booking various types of tickets and managing them through a personalized dashboard.

## Features

This application is a comprehensive replica of a modern booking portal and includes the following key features:

### Core Features

  * **Complete User Authentication**: The system features a secure user management flow with distinct **Signup** and **Login** pages, using a local SQLite database for user storage. It uses Flask sessions to maintain user authentication, ensuring all booking features are secure and personalized.

  * **Journey Planner Dashboard**: After logging in, users are presented with a central dashboard offering four separate booking services:

      * **Reserved Tickets**: For long-distance travel with seat reservations.
      * **Unreserved Tickets**: For general compartment travel.
      * **Platform Tickets**: For station entry.
      * **Monthly Season Tickets (MST)**: For frequent travelers.

  * **Advanced Reserved Ticket Booking**:

      * **Class-Based System**: Users can book tickets in various travel classes like Sleeper (SL), 3 Tier AC (3A), 2 Tier AC (2A), AC Chair Car (CC), etc., with seat availability managed separately for each class.
      * **Dynamic Fare Calculation**: Fares are calculated on-the-fly based on the travel distance and the selected class, with each class having a different per-kilometer rate.
      * **Berth Preference & Allocation**: Users can select a berth preference (e.g., Lower, Upper). The system allocates specific berths, prioritizing lower berths for senior citizens (age 60+). The final ticket displays the allocated coach and berth number.

  * **Dynamic Unreserved Ticket System**:

      * **Geospatial Distance Calculation**: The system calculates the distance between two stations by using the **Haversine formula**. It computes the real-world straight-line distance based on the latitude and longitude of the stations, which are stored in a dedicated data file.
      * **Dynamic Fare Calculation**: Fares are calculated based on the computed distance, the chosen train type (e.g., Mail/Express, Superfast), and the number of adult and child passengers.

  * **Monthly Season Ticket (MST) Booking**:

      * Allows users to book a one-month travel pass between two stations for a single passenger.
      * The fare is calculated based on the cost of 30 single journeys, providing a realistic estimate for a monthly pass.

  * **Simulated Payment Gateway**: To create a realistic booking experience, all ticket purchases are finalized through a simulated payment page. The booking is held in a "pending" state until the user confirms the payment, after which the ticket is officially generated.

### User Experience and Ticket Management

  * **Unified "My Bookings" Page**: This section provides a comprehensive history of all tickets booked by the user—Reserved, Unreserved, Platform, and MST—each displayed in its own organized table with details like status and date.

  * **QR Code Integration**: Every generated ticket includes a scannable **QR code**. This QR code is created on-the-fly and contains all the essential ticket details (PNR, train info, passenger names, etc.), allowing for easy digital verification.

  * **Ticket Cancellation**: Users can cancel their reserved tickets. The system intelligently updates the ticket's status to "CANCELLED" and returns the seats to the available pool.

  * **Autocomplete Search**: To prevent errors and improve usability, the station input fields feature an autocomplete function. As the user types, a list of matching station names and codes is suggested.

  * **Printable Tickets and Support**: All tickets have a clean, printer-friendly version designed to be saved as a PDF. Additionally, a persistent "Rail Madad" button provides a quick way for users to get support by opening their email client.

## How to Run the Project

1.  **Prerequisites**

      * Python 3.x
      * Flask and its dependencies

2.  **Installation**

      * Clone the repository:
        ```bash
        git clone https://github.com/your-username/your-repository-name.git
        cd your-repository-name
        ```
      * Install the required Python packages:
        ```bash
        pip install Flask qrcode Pillow werkzeug
        ```

3.  **Running the Application**

      * From the `railway_webapp` directory, run the main application file:
        ```bash
        python app.py
        ```
      * Open your web browser and navigate to `http://127.0.0.1:5000`.

4.  **Usage**

      * **Create an Account**: Use the "Sign up" link to create a new user.
      * **Log In**: Use your credentials to log in. The default user from the initial setup is `suryansh` with the password `password123`.
      * **Book Tickets**: Navigate through the Journey Planner to book Reserved, Unreserved, Platform, or MST tickets.
      * **Manage Bookings**: View your ticket history and cancel reserved tickets from the "My Bookings" page.
