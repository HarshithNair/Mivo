import secrets
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak,to_checksum_address
from backend.db import get_db
from backend.config import settings
from backend.models import WorldVerification,WalletChallenge,WalletConnection,CheckoutIntent,Payment,Order,Quote,Offer,Product,Audit,now,uid
from backend.services.auth import current_user
from backend.services.payments import enabled,typed_authorization,sign_authorization,verify_configuration,verified_receipt
router=APIRouter()
class AddressInput(BaseModel):address:str=Field(pattern=r'^0x[0-9a-fA-F]{40}$')
class WalletProof(BaseModel):
    challenge_id:str
    signature:str=Field(pattern=r'^0x[0-9a-fA-F]{130}$')
class ReceiptInput(BaseModel):transaction_hash:str=Field(pattern=r'^0x[0-9a-fA-F]{64}$')

@router.post('/wallet/challenge')
def challenge(body:AddressInput,user=Depends(current_user),db=Depends(get_db)):
    address=to_checksum_address(body.address)
    if int(address,16)==0:raise HTTPException(422,'Invalid wallet')
    identifier=uid();expiry=now()+300
    message=f'Mivo testnet wallet ownership\nOrigin: {settings.app_origin}\nAccount: {user.id}\nWallet: {address}\nChain: {settings.arc_chain_id}\nNonce: {identifier}\nExpires: {expiry}\nThis signature does not authorize any payment.'
    db.add(WalletChallenge(id=identifier,user_id=user.id,address=address,message=message,expires=expiry));db.commit()
    return {'id':identifier,'message':message,'expires':expiry}
@router.post('/wallet/verify')
def verify_wallet(body:WalletProof,user=Depends(current_user),db=Depends(get_db)):
    c=db.get(WalletChallenge,body.challenge_id)
    if not c or c.user_id!=user.id or c.used or c.expires<=now():raise HTTPException(409,'Wallet challenge is invalid or expired')
    try:recovered=Account.recover_message(encode_defunct(text=c.message),signature=body.signature)
    except Exception:raise HTTPException(422,'Invalid wallet signature')
    if recovered.lower()!=c.address.lower():raise HTTPException(403,'Wallet signature mismatch')
    result=db.execute(update(WalletChallenge).where(WalletChallenge.id==c.id,WalletChallenge.used==False).values(used=True))
    if result.rowcount!=1:db.rollback();raise HTTPException(409,'Challenge already used')
    connection=db.get(WalletConnection,user.id)
    if connection:connection.address=c.address;connection.verified=now()
    else:db.add(WalletConnection(user_id=user.id,address=c.address))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Wallet is already linked to another account')
    return {'address':c.address}
@router.get('/wallet')
def wallet(user=Depends(current_user),db=Depends(get_db)):
    connection=db.get(WalletConnection,user.id)
    return {'address':connection.address if connection else None,'chain_id':settings.arc_chain_id}

def intent_data(i):
    return {'id':i.id,'quote_id':i.quote_id,'chain_id':i.chain_id,'contract':i.contract_address,'token':i.token_address,'amount':i.token_amount,'status':i.status,'signature':i.signature,'authorization':{'quoteId':i.quote_hash,'buyer':i.buyer_address,'merchant':i.merchant_address,'amount':i.token_amount,'nonce':i.nonce,'deadline':i.expires}}
@router.post('/quotes/{qid}/intent')
async def create_intent(qid:str,user=Depends(current_user),db=Depends(get_db)):
    if not enabled():raise HTTPException(503,'Settlement configuration is incomplete')
    if settings.world_required:
        verification=db.get(WorldVerification,user.id)
        if not verification or verification.expires<=now() or (verification.sandbox and not settings.world_sandbox):raise HTTPException(403,'Fresh World verification is required before checkout')
    q=db.get(Quote,qid)
    if not q or q.buyer_id!=user.id:raise HTTPException(404,'Quote not found')
    existing=db.scalar(select(CheckoutIntent).where(CheckoutIntent.quote_id==qid))
    if existing:
        if existing.expires<=now() and existing.status!='paid':raise HTTPException(409,'Payment authorization expired')
        return intent_data(existing)
    if q.expires<=now() or q.status!='accepted':raise HTTPException(409,'Quote expired or unavailable')
    o=db.get(Offer,q.offer_id);p=db.get(Product,o.product_id)
    buyer=db.get(WalletConnection,user.id);merchant=db.get(WalletConnection,p.merchant_id)
    if not buyer or not merchant:raise HTTPException(409,'Buyer and merchant must verify dedicated testnet wallets first')
    if buyer.address.lower()==merchant.address.lower():raise HTTPException(409,'Buyer and merchant wallets must differ')
    if q.amount_cents<p.floor_cents:raise HTTPException(409,'Merchant pricing policy changed; negotiate again')
    try:cap=await verify_configuration()
    except Exception:raise HTTPException(503,'Settlement configuration verification failed')
    if settings.settlement_decimals<2:raise HTTPException(503,'Unsupported token decimals')
    amount=q.amount_cents*10**(settings.settlement_decimals-2)
    if amount>cap:raise HTTPException(409,'Quote exceeds the contract spending cap')
    nonce=secrets.randbits(128);quote_hash='0x'+keccak(text=q.id).hex()
    data=typed_authorization(quote_hash,buyer.address,merchant.address,amount,nonce,q.expires)
    try:signature=sign_authorization(data)
    except Exception:raise HTTPException(503,'Quote signer unavailable')
    if q.expires<=now():raise HTTPException(409,'Quote expired while preparing checkout')
    reserved=db.execute(update(Product).where(Product.id==p.id,Product.inventory>0).values(inventory=Product.inventory-1))
    if reserved.rowcount!=1:db.rollback();raise HTTPException(409,'Product sold out')
    i=CheckoutIntent(quote_id=q.id,buyer_id=user.id,merchant_id=p.merchant_id,product_id=p.id,buyer_address=buyer.address,merchant_address=merchant.address,chain_id=settings.arc_chain_id,contract_address=settings.settlement_contract,token_address=settings.settlement_token,token_amount=str(amount),nonce=str(nonce),expires=q.expires,signature=signature,quote_hash=quote_hash)
    db.add(i);db.add(Audit(actor=user.id,action='checkout_intent',reference=q.id))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Checkout was already created; retry')
    return intent_data(i)
@router.post('/intents/{iid}/confirm')
async def confirm(iid:str,body:ReceiptInput,user=Depends(current_user),db=Depends(get_db)):
    i=db.get(CheckoutIntent,iid)
    if not i or i.buyer_id!=user.id:raise HTTPException(404,'Checkout not found')
    previous=db.scalar(select(Payment).where(Payment.intent_id==i.id))
    if previous:
        if previous.transaction_hash.lower()!=body.transaction_hash.lower():raise HTTPException(409,'Checkout already paid with another transaction')
        return {'status':'paid','transaction_hash':previous.transaction_hash}
    try:r=await verified_receipt(i,body.transaction_hash)
    except ValueError as e:raise HTTPException(409,str(e))
    except Exception:raise HTTPException(503,'Receipt verification unavailable; retry safely')
    q=db.get(Quote,i.quote_id)
    payment=Payment(intent_id=i.id,transaction_hash=body.transaction_hash.lower(),block_number=int(r['blockNumber'],16),block_hash=r['blockHash'])
    try:
        db.add(payment);db.flush()
        db.add(Order(payment_id=payment.id,buyer_id=i.buyer_id,merchant_id=i.merchant_id,product_id=i.product_id,amount_cents=q.amount_cents))
        i.status='paid';q.status='paid';db.add(Audit(actor=user.id,action='receipt_verified',reference=payment.id));db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Transaction already reconciled')
    return {'status':'paid','transaction_hash':payment.transaction_hash}
@router.get('/orders')
def orders(user=Depends(current_user),db=Depends(get_db)):
    statement=select(Order).where(Order.merchant_id==user.id if user.role=='merchant' else Order.buyer_id==user.id).order_by(Order.created.desc())
    result=[]
    for o in db.scalars(statement.limit(100)):
        payment=db.get(Payment,o.payment_id);product=db.get(Product,o.product_id)
        result.append({'id':o.id,'product':product.name,'amount_cents':o.amount_cents,'status':'paid','transaction_hash':payment.transaction_hash,'block_number':payment.block_number,'created':o.created})
    return result
