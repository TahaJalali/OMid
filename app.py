import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g, session, make_response
from datetime import datetime, timedelta, time as dt_time
import jdatetime
import pytz
import uuid
import requests # Added for payment gateway
import json     # Added for payment gateway

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

# --- Payment Gateway Constants ---
# IMPORTANT: Replace with your actual Aqa-ye Pardakht PIN
AQAYEPARDARAKHT_PIN = 'YOUR_GATEWAY_PIN' # !!! REPLACE THIS !!!
AQAYEPARDARAKHT_CREATE_URL = 'https://panel.aqayepardakht.ir/api/v2/create'
AQAYEPARDARAKHT_VERIFY_URL = 'https://panel.aqayepardakht.ir/api/v2/verify'
AQAYEPARDARAKHT_STARTPAY_URL = 'https://panel.aqayepardakht.ir/startpay/'
APPOINTMENT_PRICE = 25000  # Price per APPOINTMENT_DURATION_MINUTES slot in Toman

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
        if current_gregorian_day_to_process.weekday() in [3, 4]: # Skip Thursdays (3) and Fridays (4)
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
    initial_tehran_timestamp_ms = int(current_tehran_datetime_obj.timestamp() * 1000)
    logged_in_phone = session.get('logged_in_phone')
    return dict(
        current_tehran_shamsi_display_for_layout=current_tehran_shamsi_display_for_layout,
        logged_in_phone=logged_in_phone,
        APPOINTMENT_DURATION_MINUTES=APPOINTMENT_DURATION_MINUTES,
        initial_tehran_timestamp_ms=initial_tehran_timestamp_ms,
        APPOINTMENT_PRICE=APPOINTMENT_PRICE # Pass price to templates if needed
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

    # Check if any selected slot is already booked (by someone else before payment process starts)
    current_db_booked_slots = get_booked_slots()
    for timeslot_gregorian in selected_timeslots_gregorian:
        if timeslot_gregorian in current_db_booked_slots:
            shamsi_slot = gregorian_to_shamsi_str(timeslot_gregorian, SHAMSI_FORMAT_DATETIME_ONLY)
            flash(f'متاسفانه زمان انتخابی {shamsi_slot} به تازگی توسط شخص دیگری رزرو شده است. لطفاً صفحه را رفرش کرده و مجدد تلاش کنید.', 'error')
            return response_redirect_to_index

    total_amount = len(selected_timeslots_gregorian) * APPOINTMENT_PRICE
    invoice_id = str(uuid.uuid4())

    # Store booking details in session before redirecting to payment
    session['pending_booking'] = {
        'timeslots': selected_timeslots_gregorian,
        'phone_number': phone_number,
        'amount': total_amount,
        'invoice_id': invoice_id
    }

    payment_data = {
        'pin': "28822683C383CB9442BF",
        'amount': total_amount,
        'callback': url_for('verify_payment', _external=True),
        'mobile': phone_number, # Optional, but good for AP records
        'invoice_id': invoice_id,
        'description': f"رزرو {len(selected_timeslots_gregorian)} نوبت از سامانه"
    }

    try:
        response = requests.post(AQAYEPARDARAKHT_CREATE_URL, data=payment_data, timeout=15)
        response.raise_for_status() # Check for HTTP errors
        payment_json_data = response.json()

        # IMPORTANT: Confirm the key for the transaction ID/token from Aqa-ye Pardakht documentation.
        # Common names are 'transid', 'path', 'authority', 'tracking_code'. Assuming 'transid' based on verify script.
        if payment_json_data.get('status') == 'success' and payment_json_data.get('transid'):
            redirect_token = payment_json_data['transid']
            payment_redirect_url = AQAYEPARDARAKHT_STARTPAY_URL + redirect_token
            return redirect(payment_redirect_url)
        else:
            error_message = payment_json_data.get('message', 'ایجاد تراکنش پرداخت با خطا مواجه شد.')
            app.logger.error(f"Aqa-ye Pardakht create error: {payment_json_data}")
            flash(f'خطا در اتصال به درگاه پرداخت: {error_message}', 'error')
            session.pop('pending_booking', None) # Clear pending booking
            return response_redirect_to_index

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Payment gateway request failed (create): {e}")
        flash('خطا در ارتباط با درگاه پرداخت. لطفاً لحظاتی دیگر مجدداً تلاش کنید.', 'error')
        session.pop('pending_booking', None)
        return response_redirect_to_index
    except json.JSONDecodeError:
        app.logger.error(f"Failed to decode JSON from payment gateway (create): {response.text if 'response' in locals() else 'No response text'}")
        flash('پاسخ دریافتی از درگاه پرداخت نامعتبر است.', 'error')
        session.pop('pending_booking', None)
        return response_redirect_to_index

@app.route('/payment/verify', methods=['GET']) # Aqa-ye Pardakht typically uses GET for callback
def verify_payment():
    pending_booking = session.get('pending_booking')
    if not pending_booking:
        flash('اطلاعات رزرو شما برای تایید پرداخت یافت نشد. ممکن است نشست شما منقضی شده باشد. لطفاً مجدداً تلاش کنید.', 'error')
        return redirect(url_for('index'))

    # Parameters from Aqa-ye Pardakht callback (confirm names from their docs)
    # Assuming they send 'transid' and 'invoice_id' (or 'factorNumber' for invoice_id)
    ap_trans_id = request.args.get('transid')
    ap_invoice_id = request.args.get('invoice_id') # Or 'factorNumber', check AP docs

    if not ap_trans_id:
        flash('اطلاعات تأیید پرداخت از درگاه به درستی دریافت نشد (کد تراکنش ناموجود).', 'error')
        # Don't clear pending_booking here, user might want to contact support or retry if possible
        return redirect(url_for('index'))

    # Optional: Verify if ap_invoice_id matches pending_booking['invoice_id']
    if ap_invoice_id and ap_invoice_id != pending_booking['invoice_id']:
        flash('شناسه پرداخت بازگشتی با شناسه پرداخت ارسالی مغایرت دارد.', 'error')
        # session.pop('pending_booking', None) # Security: clear if invoice IDs mismatch
        return redirect(url_for('index'))

    verify_data = {
        'pin': AQAYEPARDARAKHT_PIN,
        'amount': pending_booking['amount'],
        'transid': ap_trans_id
    }

    try:
        response = requests.post(AQAYEPARDARAKHT_VERIFY_URL, data=verify_data, timeout=15)
        response.raise_for_status()
        verify_json_data = response.json()

        if str(verify_json_data.get('code')) == '1': # Payment successful
            db = get_db()
            successful_bookings_gregorian = []
            failed_due_to_rebooking_shamsi = []

            phone_number = pending_booking['phone_number']
            selected_timeslots_gregorian = pending_booking['timeslots']
            invoice_id_for_db = pending_booking['invoice_id']

            # Re-check slots availability before final commit
            current_db_booked_slots = get_booked_slots()

            for timeslot_gregorian in selected_timeslots_gregorian:
                if timeslot_gregorian in current_db_booked_slots:
                    failed_due_to_rebooking_shamsi.append(gregorian_to_shamsi_str(timeslot_gregorian, SHAMSI_FORMAT_DATETIME_ONLY))
                    continue

                try:
                    db.execute('INSERT INTO appointments (timeslot, phone_number, invoice_id, payment_trans_id) VALUES (?, ?, ?, ?)',
                               (timeslot_gregorian, phone_number, invoice_id_for_db, ap_trans_id))
                    successful_bookings_gregorian.append(timeslot_gregorian)
                except sqlite3.IntegrityError: # Should be caught by current_db_booked_slots, but as a fallback
                    db.rollback() # Rollback individual insert if needed, or handle commit later
                    app.logger.error(f"Integrity error inserting {timeslot_gregorian} after payment, though it passed pre-check.")
                    failed_due_to_rebooking_shamsi.append(f"{gregorian_to_shamsi_str(timeslot_gregorian, SHAMSI_FORMAT_DATETIME_ONLY)} (خطای پایگاه داده)")
                except Exception as e:
                    db.rollback()
                    app.logger.error(f"DB error booking {timeslot_gregorian} for {phone_number} after payment: {e}")
                    failed_due_to_rebooking_shamsi.append(f"{gregorian_to_shamsi_str(timeslot_gregorian, SHAMSI_FORMAT_DATETIME_ONLY)} (خطای سیستمی)")


            if not successful_bookings_gregorian and selected_timeslots_gregorian:
                db.rollback() # Ensure nothing is committed if all failed
                flash_msg_parts = ["پرداخت موفق بود، اما متاسفانه تمام زمان‌های انتخابی شما در حین فرآیند پرداخت توسط دیگران رزرو شدند:"]
                if failed_due_to_rebooking_shamsi:
                     flash_msg_parts.append(f"زمان(های) پر شده: {', '.join(failed_due_to_rebooking_shamsi)}.")
                flash(" ".join(flash_msg_parts), 'error')
                session.pop('pending_booking', None)
                return redirect(url_for('index'))

            db.commit() # Commit all successful bookings
            session['last_booked_slots'] = successful_bookings_gregorian
            session['last_booked_phone'] = phone_number

            # Device ID and user agent update
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
                db.rollback(); app.logger.error(f"Error updating device info after payment verification: {e}")

            final_response = make_response(redirect(url_for('booking_confirmation')))
            if not request.cookies.get(DEVICE_ID_COOKIE_NAME) or request.cookies.get(DEVICE_ID_COOKIE_NAME) != device_id : # Set cookie if it wasn't there or changed
                 final_response.set_cookie(DEVICE_ID_COOKIE_NAME, device_id, max_age=365*24*60*60, httponly=True, samesite='Lax')

            flash_msg_parts = [f"پرداخت موفق! نوبت(های) شما برای {', '.join([gregorian_to_shamsi_str(s, SHAMSI_FORMAT_DATETIME_ONLY) for s in successful_bookings_gregorian])} با موفقیت رزرو شد!"]
            if failed_due_to_rebooking_shamsi:
                flash_msg_parts.append(f"توجه: زمان(های) {', '.join(failed_due_to_rebooking_shamsi)} در حین پرداخت توسط دیگران رزرو شده بود و برای شما ثبت نشد.")
            flash(" ".join(flash_msg_parts), 'success' if not failed_due_to_rebooking_shamsi else 'warning')

            session.pop('pending_booking', None)
            return final_response

        else: # Payment verification failed
            error_msg = verify_json_data.get('message', 'تراکنش توسط درگاه تایید نشد.')
            app.logger.warning(f"Aqa-ye Pardakht verify failed: {verify_json_data}")
            flash(f"پرداخت ناموفق یا توسط شما لغو شد: {error_msg} (کد: {verify_json_data.get('code')}). وجهی از حساب شما کسر نشده است.", 'error')
            session.pop('pending_booking', None)
            return redirect(url_for('index'))

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Payment verification request failed: {e}")
        flash('خطا در ارتباط با درگاه پرداخت برای تأیید نهایی. اگر پرداخت انجام شده، لطفاً با پشتیبانی تماس بگیرید.', 'error')
        # Do not clear pending_booking, as payment might be in an ambiguous state. Support might need invoice_id.
        return redirect(url_for('index'))
    except json.JSONDecodeError:
        app.logger.error(f"Failed to decode JSON from payment verification response: {response.text if 'response' in locals() else 'No response text'}")
        flash('پاسخ دریافتی از درگاه پرداخت برای تأیید نهایی قابل پردازش نبود. لطفاً با پشتیبانی تماس بگیرید.', 'error')
        return redirect(url_for('index'))


@app.route('/confirmation')
def booking_confirmation():
    booked_slots_gregorian = session.pop('last_booked_slots', [])
    phone_number = session.pop('last_booked_phone', None)
    if not booked_slots_gregorian: # Or if already shown and session cleared
        # flash('اطلاعاتی برای تأییدیه یافت نشد یا قبلاً نمایش داده شده است.', 'info')
        return redirect(url_for('index')) # Avoid re-showing confirmation on refresh
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
    newly_generated_device_id = None # Used to track if we need to set cookie on response

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
                newly_generated_device_id = device_id # Mark to set cookie

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
            response = make_response(redirect(url_for('my_appointments'))) # Redirect to GET
            if newly_generated_device_id:
                response.set_cookie(DEVICE_ID_COOKIE_NAME, newly_generated_device_id, max_age=365*24*60*60, httponly=True, samesite='Lax')
            return response

    # Handle GET requests or if POST had an issue before successful login/redirect
    if request.method == 'GET' and not current_logged_in_phone: # Auto-login attempt via cookie
        device_id_from_cookie = request.cookies.get(DEVICE_ID_COOKIE_NAME)
        if device_id_from_cookie:
            user_device_info = db.execute('SELECT phone_number FROM user_devices WHERE device_id = ?', (device_id_from_cookie,)).fetchone()
            if user_device_info and user_device_info['phone_number']:
                session['logged_in_phone'] = user_device_info['phone_number']
                current_logged_in_phone = user_device_info['phone_number']
                flash('نوبت‌های شما بر اساس اطلاعات دستگاه شما (ورود خودکار) نمایش داده شد.', 'info')
                ip_address = request.remote_addr
                try:
                    db.execute('UPDATE user_devices SET last_activity_time=CURRENT_TIMESTAMP, last_login_ip=? WHERE device_id = ?',
                               (ip_address, device_id_from_cookie))
                    db.commit()
                except Exception as e:
                    db.rollback(); app.logger.error(f"Error updating activity on auto-login: {e}")
            # else: No phone associated or device_id not found, user needs to login manually

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

    # Ensure form_phone_number is set if POST failed validation before redirect and didn't result in login
    if request.method == 'POST' and not current_logged_in_phone and not form_phone_number:
        form_phone_number = request.form.get('phone_number_view', '').strip()


    return render_template('my_appointments.html',
                           appointments=appointments_list,
                           logged_in_phone=current_logged_in_phone,
                           form_phone_number=form_phone_number,
                           device_info=device_info_to_display)


@app.route('/logout')
def logout():
    session.pop('logged_in_phone', None)
    response = make_response(redirect(url_for('my_appointments')))
    # response.delete_cookie(DEVICE_ID_COOKIE_NAME) # Keep device_id for potential auto-login convenience
    flash('شما با موفقیت خارج شدید. برای مشاهده مجدد، شماره تلفن را وارد کنید یا در صورت ذخیره بودن، به صورت خودکار وارد می‌شوید.', 'info')
    return response


if __name__ == '__main__':
    # init_db() # Uncomment to initialize DB if schema.sql is present and table doesn't exist
    app.run(debug=True, host='0.0.0.0', port=5000)