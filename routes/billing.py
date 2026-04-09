from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db
from models import Bill, BillItem, Client
from datetime import datetime
import uuid

# Blueprint setup
billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

@billing_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_bill():
    # Jab user "Generate Bill" dabayega, tab ye block chalega (POST request)
    if request.method == 'POST':
        client_id = request.form.get('client_id')
        
        # 1. Frontend se arrays fetch karna (getlist is the magic word!)
        item_names = request.form.getlist('item_name[]')
        quantities = request.form.getlist('quantity[]')
        mrps = request.form.getlist('mrp[]')
        
        if not client_id:
            flash("Please select a client.", "danger")
            return redirect(url_for('billing.create_bill'))

        # 2. Main Bill create karna
        new_bill = Bill(
            admin_id=current_user.id,
            client_id=client_id,
            bill_number=f"BILL-{uuid.uuid4().hex[:6].upper()}", # Random short unique ID
            date=datetime.utcnow(),
            total=0.0,
            status='UNPAID'
        )
        db.session.add(new_bill)
        db.session.flush() # ID generate karne ke liye taaki items link ho sakein

        grand_total = 0.0

        # 3. Arrays ko loop karke BillItems banana
        for i in range(len(item_names)):
            name = item_names[i].strip()
            if name: # Sirf tabhi add karo agar item ka naam khali na ho
                qty = float(quantities[i])
                mrp = float(mrps[i])
                row_total = qty * mrp
                grand_total += row_total

                new_item = BillItem(
                    bill_id=new_bill.id,
                    description=name,
                    quantity=qty,
                    unit_price=mrp,
                    total=row_total
                )
                db.session.add(new_item)
        
        # 4. Final Total update karke database mein save kar do
        new_bill.total = grand_total
        db.session.commit()

        flash('Bill generated successfully!', 'success')
        return redirect(url_for('main.dashboard')) # Abhi ke liye dashboard pe bhej rahe hain
        
    # GET Request - Form dikhane ke liye clients load karna
    clients = Client.query.filter_by(admin_id=current_user.id, is_active=True).all()
    return render_template('billing/create.html', clients=clients)