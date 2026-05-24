from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime, timedelta
from database import db, User, Lot, Bid
import os
from threading import Thread
import time
import pytz

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///auction.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.secret_key = 'supersecretkey'

db.init_app(app)


def local_time(utc_time, timezone='Europe/Kiev'):
    utc_time = utc_time.replace(tzinfo=pytz.UTC)  
    local_tz = pytz.timezone(timezone)
    return utc_time.astimezone(local_tz) 


@app.context_processor
def inject_local_time():
    return dict(local_time=local_time)

with app.app_context():
    db.create_all()
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

def check_winner(lot_id):
    time.sleep(120)
    with app.app_context():
        lot = Lot.query.get(lot_id)
        if lot and lot.is_active:
            last_bid = Bid.query.filter_by(lot_id=lot_id).order_by(Bid.created_at.desc()).first()
            if last_bid:
                lot.is_active = False
                lot.closed_at = datetime.now()
                db.session.commit()
                print(f"Lot {lot_id} won by user {last_bid.user_id}")

@app.route('/')
def index():
    search_query = request.args.get('search', '').strip()
    if search_query:
        lots = Lot.query.filter(
            (Lot.name.ilike(f'%{search_query}%')) | (Lot.description.ilike(f'%{search_query}%')),
            Lot.is_active == True,
            Lot.is_published == True 
        ).all()
    else:
        lots = Lot.query.filter_by(is_active=True, is_published=True).all() 
    return render_template('index.html', lots=lots)
@app.route('/lot/<int:lot_id>', methods=['GET', 'POST'])
def lot(lot_id):
    lot = Lot.query.get_or_404(lot_id)
    if request.method == 'POST':
        if 'user_id' not in session:
            flash('You need to log in to place a bid!', 'error')
            return redirect(url_for('login'))


        if session['user_id'] == lot.owner_id:
            flash('You cannot place a bid on your own lot!', 'error')
            return redirect(url_for('lot', lot_id=lot_id))

        bid_amount = float(request.form['bid_amount'])
        if bid_amount <= lot.current_price:
            flash('Your bid must be higher than the current price!', 'error')
            return redirect(url_for('lot', lot_id=lot_id))

        new_bid = Bid(
            amount=bid_amount,
            user_id=session['user_id'],
            lot_id=lot_id
        )
        lot.current_price = bid_amount
        db.session.add(new_bid)
        db.session.commit()


        Thread(target=check_winner, args=(lot_id,)).start()

        flash('Your bid has been placed!', 'success')
        return redirect(url_for('lot', lot_id=lot_id))

    bids = Bid.query.filter_by(lot_id=lot_id).order_by(Bid.created_at.desc()).all()
    return render_template('lot.html', lot=lot, bids=bids)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('register'))

        new_user = User(username=username, email=email, password=password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password!', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


@app.route('/create_lot', methods=['GET', 'POST'])
def create_lot():
    if 'user_id' not in session:
        flash('You need to log in to create a lot!', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        start_price = float(request.form['start_price'])
        owner_id = session['user_id']

        image = request.files['image']
        if image:
            filename = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
            image.save(filename)
            image_path = f"uploads/{image.filename}"
        else:
            image_path = None

        new_lot = Lot(
            name=name,
            description=description,
            start_price=start_price,
            current_price=start_price,
            owner_id=owner_id,
            is_published=False,
            end_time=datetime.now() + timedelta(days=7),
            image_path=image_path
        )
        db.session.add(new_lot)
        db.session.commit()
        flash('Lot created successfully! Start the auction to make it visible.', 'success')
        return redirect(url_for('my_lots'))

    return render_template('create_lot.html')
@app.route('/my_lots')
def my_lots():
    if 'user_id' not in session:
        flash('You need to log in to view your lots!', 'error')
        return redirect(url_for('login'))


    user_lots = Lot.query.filter_by(owner_id=session['user_id']).all()
    return render_template('my_lots.html', lots=user_lots)


@app.route('/close_lot/<int:lot_id>')
def close_lot(lot_id):
    if 'user_id' not in session:
        flash('You need to log in to close a lot!', 'error')
        return redirect(url_for('login'))

    lot = Lot.query.get_or_404(lot_id)
    if lot.owner_id != session['user_id']:
        flash('You are not the owner of this lot!', 'error')
        return redirect(url_for('lot', lot_id=lot_id))

    lot.is_active = False
    lot.is_closed = True
    lot.closed_at = datetime.now() 
    db.session.commit()
    flash('Lot closed successfully!', 'success')
    return redirect(url_for('lot', lot_id=lot_id))

@app.route('/start_auction/<int:lot_id>', methods=['POST'])
def start_auction(lot_id):
    if 'user_id' not in session:
        flash('You need to log in to start an auction!', 'error')
        return redirect(url_for('login'))

    lot = Lot.query.get_or_404(lot_id)
    if lot.owner_id != session['user_id']:
        flash('You are not the owner of this lot!', 'error')
        return redirect(url_for('my_lots'))

    lot.is_published = True
    db.session.commit()
    flash('Auction started successfully! The lot is now visible to all users.', 'success')
    return redirect(url_for('my_lots'))
@app.route('/edit_lot/<int:lot_id>', methods=['GET', 'POST'])
def edit_lot(lot_id):
    if 'user_id' not in session:
        flash('You need to log in to edit a lot!', 'error')
        return redirect(url_for('login'))

    lot = Lot.query.get_or_404(lot_id)
    if lot.owner_id != session['user_id']:
        flash('You are not the owner of this lot!', 'error')
        return redirect(url_for('lot', lot_id=lot_id))

    if request.method == 'POST':
        lot.name = request.form['name']
        lot.description = request.form['description']

        if not lot.bids:
            lot.start_price = float(request.form['start_price'])
            lot.current_price = float(request.form['start_price'])

        db.session.commit()
        flash('Lot updated successfully!', 'success')
        return redirect(url_for('lot', lot_id=lot_id))

    return render_template('edit_lot.html', lot=lot)

@app.route('/completed_lots')
def completed_lots():
    search_query = request.args.get('search', '').strip()
    if search_query:
        completed_lots = Lot.query.filter(
            (Lot.name.ilike(f'%{search_query}%')) | (Lot.description.ilike(f'%{search_query}%')),
            (Lot.is_active == False) | (Lot.is_closed == True),
            Lot.is_published == True
        ).all()
    else:
        completed_lots = Lot.query.filter(
            (Lot.is_active == False) | (Lot.is_closed == True),
            Lot.is_published == True
        ).all()
    return render_template('completed_lots.html', completed_lots=completed_lots)



if __name__ == '__main__':
    app.run(debug=True)