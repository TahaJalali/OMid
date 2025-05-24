import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, session, make_response
from datetime import datetime, timedelta, time as dt_time
import jdatetime
import pytz
import uuid

app = Flask(__name__)
# IMPORTANT: Change this secret key for production!
app.secret_key = 'your_very_secret_key_for_flash_messages_and_session_!@#$_MUST_CHANGE_VERY_MUCH_AGAIN'
DATABASE = 'appointments.db'
DEVICE_ID_COOKIE_NAME = 'app_device_id_v1' 

# --- Timezone and Calendar Constants ---
TEHRAN_TZ = pytz.timezone('Asia/Tehran')
SHAMSI_FORMAT_FULL = "%A، %d %B %Y، ساعت %H:%M"
SHAMSI_FORMAT_DATETIME_ONLY = "%d %B %Y، ساعت %H:%M"
SHAMSI_DISPLAY_FORMAT_CURRENT_TIME_BASE = "%A، %d %B %Y، ساعت " 
SHAMSI_DISPLAY_FORMAT_CURRENT_TIME = f"{SHAMSI_DISPLAY_FORMAT_CURRENT_TIME_BASE}<span id='live-time'>%H:%M:%S</span>"
APPOINTMENT_DURATION_MINUTES = 45

# --- Database Helper Functions ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()
    print("پایگاه داده با موفقیت مقداردهی اولیه شد.")

# --- Helper Functions for Time, Calendar, Appointments ---
def get_current_tehran_time():
    return datetime.now(TEHRAN_TZ)

def gregorian_to_shamsi_str(gregorian_dt_str, format_str=SHAMSI_FORMAT_FULL):
    try:
        gregorian_dt = datetime.strptime(gregorian_dt_str, "%Y-%m-%d %H:%M")
        shamsi_dt = jdatetime.datetime.fromgregorian(datetime=gregorian_dt)
        return shamsi_dt.strftime(format_str)
    except ValueError:
        return gregorian_dt_str

def gregorian_dt_to_shamsi_str_obj(gregorian_dt_object, format_str=SHAMSI_FORMAT_FULL):
    if gregorian_dt_object.tzinfo is not None: 
        gregorian_dt_object = gregorian_dt_object.astimezone(TEHRAN_TZ).replace(tzinfo=None)
    shamsi_dt = jdatetime.datetime.fromgregorian(datetime=gregorian_dt_object)
    return shamsi_dt.strftime(format_str)

def get_appointment_status(timeslot_gregorian_str, current_tehran_dt_aware):
    try:
        slot_start_gregorian_naive = datetime.strptime(timeslot_gregorian_str, "%Y-%m-%d %H:%M")
        slot_end_gregorian_naive = slot_start_gregorian_naive + timedelta(minutes=APPOINTMENT_DURATION_MINUTES)
        current_tehran_dt_naive = current_tehran_dt_aware.replace(tzinfo=None)

        if slot_end_gregorian_naive < current_tehran_dt_naive:
            return "passed"
        elif slot_start_gregorian_naive <= current_tehran_dt_naive < slot_end_gregorian_naive:
            return "ongoing"
        else:
            return "future"
    except ValueError:
        return "unknown"

# --- Core Logic Helper Functions ---
def get_booked_slots():
    db = get_db()
    return {slot['timeslot'] for slot in db.execute('SELECT timeslot FROM appointments').fetchall()}

def generate_time_slots():
    slots = []
    current_tehran_dt = get_current_tehran_time() 
    today_tehran_date = current_tehran_dt.date()
    days_to_show = 7
    slot_duration = timedelta(minutes=APPOINTMENT_DURATION_MINUTES)
    work_start_time = dt_time(10, 0) 
    work_end_time = dt_time(22, 0)  
    booked_slots = get_booked_slots()

    for day_offset in range(days_to_show):
        current_gregorian_day_to_process = today_tehran_date + timedelta(days=day_offset)
        if current_gregorian_day_to_process.weekday() in [3, 4]: 
            continue

        current_potential_slot_dt_naive = datetime.combine(current_gregorian_day_to_process, work_start_time)
        day_work_ends_dt_naive = datetime.combine(current_gregorian_day_to_process, work_end_time)

        while current_potential_slot_dt_naive + slot_duration <= day_work_ends_dt_naive:
            if current_gregorian_day_to_process == today_tehran_date and \
               current_potential_slot_dt_naive <= current_tehran_dt.replace(tzinfo=None):
                current_potential_slot_dt_naive += slot_duration
                continue
            
            slot_value_gregorian_str = current_potential_slot_dt_naive.strftime("%Y-%m-%d %H:%M")
            if slot_value_gregorian_str not in booked_slots:
                slots.append({
                    "value": slot_value_gregorian_str,
                    "display": gregorian_dt_to_shamsi_str_obj(current_potential_slot_dt_naive)
                })
            current_potential_slot_dt_naive += slot_duration
    return slots

# --- Context Processors ---
@app.context_processor
def inject_global_vars():
    current_tehran_datetime_obj = get_current_tehran_time()
    current_tehran_shamsi_display_for_layout = gregorian_dt_to_shamsi_str_obj(current_tehran_datetime_obj, SHAMSI_DISPLAY_FORMAT_CURRENT_TIME)
    initial_tehran_timestamp_ms = int(current_tehran_datetime_obj.timestamp() * 1000) # For JS clock
    
    return dict(
        current_tehran_shamsi_display_for_layout=current_tehran_shamsi_display_for_layout,
        logged_in_phone=session.get('logged_in_phone'),
        APPOINTMENT_DURATION_MINUTES=APPOINTMENT_DURATION_MINUTES,
        initial_tehran_timestamp_ms=initial_tehran_timestamp_ms 
    )

# --- Routes ---
@app.route('/', methods=['GET'])
def index():
    available_slots = generate_time_slots()
    return render_template('index.html', slots=available_slots)

@app.route('/book', methods=['POST'])
def book_appointment():
    selected_timeslots_gregorian = request.form.getlist('timeslot')
    phone_number = request.form.get('phone_number', '').strip()
    response_redirect_to_index = make_response(redirect(url_for('index')))

    if not selected_timeslots_gregorian:
        flash('لطفاً حداقل یک بازه زمانی را انتخاب کنید.', 'error'); return response_redirect_to_index
    if not phone_number:
        flash('وارد کردن شماره تلفن همراه الزامی است.', 'error'); return response_redirect_to_index
    if not phone_number.isdigit() or not (7 <= len(phone_number) <= 15):
        flash('فرمت شماره تلفن همراه نامعتبر است. لطفاً ۷ تا ۱۵ رقم عددی وارد کنید.', 'error'); return response_redirect_to_index

    db = get_db()
    successful_bookings_gregorian = []
    failed_booking_slots_shamsi = []
    current_db_booked_slots = get_booked_slots() 

    for timeslot_gregorian in selected_timeslots_gregorian:
        try:
            if timeslot_gregorian in current_db_booked_slots or timeslot_gregorian in successful_bookings_gregorian:
                failed_booking_slots_shamsi.append(gregorian_to_shamsi_str(timeslot_gregorian, SHAMSI_FORMAT_DATETIME_ONLY))
                continue
            db.execute('INSERT INTO appointments (timeslot, phone_number) VALUES (?, ?)',
                       (timeslot_gregorian, phone_number))
            successful_bookings_gregorian.append(timeslot_gregorian)
        except sqlite3.IntegrityError: 
            failed_booking_slots_shamsi.append(gregorian_to_shamsi_str(timeslot_gregorian, SHAMSI_FORMAT_DATETIME_ONLY))
        except Exception as e:
            db.rollback() 
            app.logger.error(f"DB error booking {timeslot_gregorian} for {phone_number}: {e}")
            failed_booking_slots_shamsi.append(f"{gregorian_to_shamsi_str(timeslot_gregorian, SHAMSI_FORMAT_DATETIME_ONLY)} (خطای سیستمی)")

    if successful_bookings_gregorian:
        db.commit() 
        session['last_booked_slots'] = successful_bookings_gregorian
        session['last_booked_phone'] = phone_number
        
        device_id = request.cookies.get(DEVICE_ID_COOKIE_NAME) or str(uuid.uuid4())
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        try:
            db.execute('''
                INSERT INTO user_devices (phone_number, device_id, user_agent, last_activity_time) 
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(phone_number) DO UPDATE SET 
                    device_id=excluded.device_id, user_agent=excluded.user_agent, 
                    last_activity_time=CURRENT_TIMESTAMP
            ''', (phone_number, device_id, user_agent))
            db.execute('''
                INSERT INTO user_devices (phone_number, device_id, user_agent, last_activity_time)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(device_id) DO UPDATE SET
                    phone_number=excluded.phone_number, user_agent=excluded.user_agent, 
                    last_activity_time=CURRENT_TIMESTAMP
            ''', (phone_number, device_id, user_agent))
            db.commit()
        except Exception as e:
            db.rollback(); app.logger.error(f"Error updating device info during booking: {e}")
        
        final_response = make_response(redirect(url_for('booking_confirmation')))
        final_response.set_cookie(DEVICE_ID_COOKIE_NAME, device_id, max_age=365*24*60*60, httponly=True, samesite='Lax')

        msg_parts = [f"نوبت(های) شما برای {', '.join([gregorian_to_shamsi_str(s, SHAMSI_FORMAT_DATETIME_ONLY) for s in successful_bookings_gregorian])} با موفقیت رزرو شد!"]
        if failed_booking_slots_shamsi:
            msg_parts.append(f"اما زمان(های) {', '.join(failed_booking_slots_shamsi)} موفق به رزرو نشد.")
        flash(" ".join(msg_parts), 'success' if not failed_booking_slots_shamsi else 'warning')
        return final_response
    else: 
        db.rollback()
        failed_msg = "، ".join(failed_booking_slots_shamsi) if failed_booking_slots_shamsi else "موردی برای رزرو انتخاب نشده یا همه موارد ناموفق بودند."
        flash(f"هیچ یک از زمان‌های انتخابی موفق به رزرو نشد. {failed_msg}", 'error')
        return response_redirect_to_index


@app.route('/confirmation')
def booking_confirmation():
    booked_slots_gregorian = session.pop('last_booked_slots', [])
    phone_number = session.pop('last_booked_phone', None)
    if not booked_slots_gregorian:
        flash('اطلاعاتی برای تأییدیه یافت نشد یا قبلاً نمایش داده شده است.', 'info')
        return redirect(url_for('index'))
    booked_slots_shamsi_display = [gregorian_to_shamsi_str(s, SHAMSI_FORMAT_DATETIME_ONLY) for s in booked_slots_gregorian]
    return render_template('booking_confirmation.html', 
                           booked_slots_display_list=booked_slots_shamsi_display, 
                           phone_number=phone_number)


@app.route('/my-appointments', methods=['GET', 'POST'])
def my_appointments():
    db = get_db()
    appointments_list = []
    device_info_to_display = None
    form_phone_number = "" 
    current_logged_in_phone = session.get('logged_in_phone')
    
    response_needed_for_cookie = False
    newly_generated_device_id = None

    if request.method == 'POST':
        phone_to_verify = request.form.get('phone_number_view', '').strip()
        if not phone_to_verify:
            flash('لطفاً شماره تلفن همراه خود را وارد کنید.', 'error')
        elif not phone_to_verify.isdigit() or not (7 <= len(phone_to_verify) <= 15):
            flash('فرمت شماره تلفن همراه نامعتبر است.', 'error')
            form_phone_number = phone_to_verify 
        else:
            session['logged_in_phone'] = phone_to_verify
            current_logged_in_phone = phone_to_verify
            
            device_id = request.cookies.get(DEVICE_ID_COOKIE_NAME)
            if not device_id:
                device_id = str(uuid.uuid4())
                newly_generated_device_id = device_id # Mark that we need to set this cookie
                response_needed_for_cookie = True

            user_agent = request.headers.get('User-Agent', 'Unknown')
            ip_address = request.remote_addr 
            try:
                db.execute('''
                    INSERT INTO user_devices (phone_number, device_id, user_agent, last_login_ip, last_activity_time)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(phone_number) DO UPDATE SET
                        device_id=excluded.device_id, user_agent=excluded.user_agent, 
                        last_login_ip=excluded.last_login_ip, last_activity_time=CURRENT_TIMESTAMP
                ''', (current_logged_in_phone, device_id, user_agent, ip_address))
                db.execute('''
                    INSERT INTO user_devices (phone_number, device_id, user_agent, last_login_ip, last_activity_time)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(device_id) DO UPDATE SET
                        phone_number=excluded.phone_number, user_agent=excluded.user_agent, 
                        last_login_ip=excluded.last_login_ip, last_activity_time=CURRENT_TIMESTAMP
                ''', (current_logged_in_phone, device_id, user_agent, ip_address))
                db.commit()
            except Exception as e:
                db.rollback(); app.logger.error(f"Error updating device info on login: {e}")
            
            flash(f'نوبت‌های شما برای شماره {current_logged_in_phone} نمایش داده شد.', 'success')
            # Redirect to GET to show the data and set cookie if needed
            response = make_response(redirect(url_for('my_appointments')))
            if newly_generated_device_id:
                response.set_cookie(DEVICE_ID_COOKIE_NAME, newly_generated_device_id, max_age=365*24*60*60, httponly=True, samesite='Lax')
            return response

    # This part handles GET requests or if POST had an issue before successful login
    if request.method == 'GET' and not current_logged_in_phone: 
        device_id_from_cookie = request.cookies.get(DEVICE_ID_COOKIE_NAME)
        if device_id_from_cookie:
            user_device_info = db.execute('SELECT phone_number FROM user_devices WHERE device_id = ?', (device_id_from_cookie,)).fetchone()
            if user_device_info:
                session['logged_in_phone'] = user_device_info['phone_number']
                current_logged_in_phone = user_device_info['phone_number']
                # No form_phone_number prefill here as it's an auto-login
                flash('نوبت‌های شما بر اساس اطلاعات دستگاه شما (ورود خودکار) نمایش داده شد.', 'info')
                ip_address = request.remote_addr
                try:
                    db.execute('UPDATE user_devices SET last_activity_time=CURRENT_TIMESTAMP, last_login_ip=? WHERE device_id = ?',
                               (ip_address, device_id_from_cookie))
                    db.commit()
                except Exception as e:
                    db.rollback(); app.logger.error(f"Error updating activity on auto-login: {e}")

    if current_logged_in_phone: 
        appts_from_db = db.execute('SELECT timeslot FROM appointments WHERE phone_number = ? ORDER BY timeslot ASC', (current_logged_in_phone,)).fetchall()
        current_tehran_dt_for_status = get_current_tehran_time()
        for appt in appts_from_db:
            timeslot_gregorian = appt['timeslot']
            appointments_list.append({
                'shamsi_display': gregorian_to_shamsi_str(timeslot_gregorian, SHAMSI_FORMAT_FULL),
                'status': get_appointment_status(timeslot_gregorian, current_tehran_dt_for_status)
            })
        device_data = db.execute('SELECT user_agent, last_login_ip FROM user_devices WHERE phone_number = ?', (current_logged_in_phone,)).fetchone()
        if device_data:
            device_info_to_display = {
                'user_agent': device_data['user_agent'],
                'ip_address': device_data['last_login_ip']
            }
    
    # This is for GET requests or if POST failed validation before redirect
    # form_phone_number should be set if POST failed validation
    if request.method == 'POST' and not current_logged_in_phone and not form_phone_number: # If POST failed early
        form_phone_number = request.form.get('phone_number_view', '').strip()


    return render_template('my_appointments.html',
                           appointments=appointments_list,
                           logged_in_phone=current_logged_in_phone, 
                           form_phone_number=form_phone_number, 
                           device_info=device_info_to_display)


@app.route('/logout')
def logout():
    session.pop('logged_in_phone', None)
    flash('شما با موفقیت از بخش پیگیری نوبت خارج شدید. برای مشاهده مجدد، شماره تلفن را وارد کنید.', 'info')
    return redirect(url_for('my_appointments'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')