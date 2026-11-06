import secrets
from sqlalchemy import select
from pwdlib import PasswordHash
from backend.db import SessionLocal
from backend.models import User, Product

def seed():
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == 'demo-audio@mivo.invalid')): return
        merchants = []
        for slug, name in [('audio','SoundHub · Demo'),('tech','AudioKart · Demo'),('life','Everyday Studio · Demo')]:
            user = User(email=f'demo-{slug}@mivo.invalid', name=name, role='merchant', password_hash=PasswordHash.recommended().hash(secrets.token_urlsafe(40)))
            db.add(user); db.flush(); merchants.append(user)
        catalog = [
            ('Studio ANC Headphones','Headphones',14900,11900,'Rich sound, active noise cancellation and 40-hour battery.'),
            ('Everyday Wireless Buds','Headphones',7900,6200,'Pocket-sized wireless earbuds with a charging case.'),
            ('Pulse Smartwatch','Smartwatches',12900,9900,'Fitness tracking and a seven-day battery.'),
            ('Focus Laptop 14','Laptops',69900,64900,'Lightweight 14-inch laptop with 16GB memory.'),
            ('Pocket Digital Camera','Cameras',24900,21900,'Compact camera with optical zoom.'),
            ('Cloud Runner Sneakers','Lifestyle',8900,7200,'Cushioned everyday sneakers.'),
            ('Desk Mini Speaker','Audio',5900,4500,'Compact wireless speaker for your desk.'),
            ('Travel ANC Headphones','Headphones',19900,15900,'Foldable noise-cancelling headphones.'),
            ('Trail Smartwatch','Smartwatches',17900,14500,'Outdoor smartwatch with GPS.'),
            ('Everyday Backpack','Lifestyle',6900,5200,'Water-resistant backpack with laptop compartment.')]
        for i, (name,category,price,floor,description) in enumerate(catalog):
            db.add(Product(merchant_id=merchants[i%3].id,name=name,category=category,description=description,price_cents=price,floor_cents=floor,image=('/earbuds.svg' if 'Buds' in name else '/backpack.svg' if 'Backpack' in name else {'Smartwatches':'/watch.svg','Laptops':'/laptop.svg','Cameras':'/camera.svg','Audio':'/speaker.svg','Lifestyle':'/sneakers.svg'}.get(category,'/headphones-photo.png'))))
        for i in [1,2]:
            db.add(Product(merchant_id=merchants[i].id,name=catalog[0][0],category='Headphones',description=catalog[0][4],price_cents=14900+i*500,floor_cents=11500+i*200,image='/headphones-photo.png'))
        db.commit()
if __name__ == '__main__': seed()
