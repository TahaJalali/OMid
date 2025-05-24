DROP TABLE IF EXISTS appointments;

CREATE TABLE appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeslot TEXT NOT NULL, -- Format: "YYYY-MM-DD HH:MM" Gregorian
    phone_number TEXT NOT NULL,
    booking_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ensures a timeslot can only be booked once by anyone
CREATE UNIQUE INDEX IF NOT EXISTS idx_timeslot_unique ON appointments (timeslot);
-- Index for fetching appointments by phone number
CREATE INDEX IF NOT EXISTS idx_phone_number ON appointments (phone_number);


-- New table for user device information
DROP TABLE IF EXISTS user_devices;
CREATE TABLE user_devices (
    phone_number TEXT PRIMARY KEY, -- Each phone number has one primary device association
    device_id TEXT NOT NULL UNIQUE, -- Unique ID stored in user's cookie
    user_agent TEXT,
    last_login_ip TEXT, -- New field for IP address
    last_activity_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Renamed from last_seen
);

CREATE INDEX IF NOT EXISTS idx_device_id ON user_devices (device_id);