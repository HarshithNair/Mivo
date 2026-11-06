import secrets
from urllib.parse import urlencode
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,update,func
from sqlalchemy.exc import IntegrityError
from backend.db import get_db
from backend.models import WorldAttempt,WorldVerification,Audit,now
from backend.config import settings
from backend.services.auth import current_user
from backend.services.world import ISSUER,ACR,configured,digest,pkce,metadata,exchange_and_validate
router=APIRouter()
class Completion(BaseModel):
    state:str=Field(min_length=20,max_length=200)
    iss:str=Field(max_length=100)
    code:str|None=Field(default=None,max_length=2000)
    error:str|None=Field(default=None,max_length=100)
@router.get('/world/status')
def status(user=Depends(current_user),db=Depends(get_db)):
    v=db.get(WorldVerification,user.id)
    active=bool(v and v.expires>now())
    return {'configured':configured(),'required':settings.world_required,'verified':active and not v.sandbox,'sandbox_verified':active and v.sandbox,'sandbox':settings.world_sandbox,'expires':v.expires if v else None}
@router.post('/world/start')
async def start(user=Depends(current_user),db=Depends(get_db)):
    if not configured():raise HTTPException(503,'World developer credentials are not configured')
    count=db.scalar(select(func.count()).select_from(WorldAttempt).where(WorldAttempt.user_id==user.id,WorldAttempt.expires>now()))
    if count>=5:raise HTTPException(429,'Too many World requests; wait for an earlier request to expire')
    try:data=await metadata()
    except Exception:raise HTTPException(503,'World discovery is unavailable')
    state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    db.add(WorldAttempt(state_hash=digest(state),user_id=user.id,nonce=nonce,verifier=verifier,expires=now()+300));db.commit()
    params={'client_id':settings.world_client_id,'redirect_uri':settings.app_origin+'/world-callback','response_type':'code','response_mode':'query','scope':'openid','state':state,'nonce':nonce,'code_challenge':pkce(verifier),'code_challenge_method':'S256','max_age':'0','acr_values':' '.join(ACR)}
    return {'url':data['authorization_endpoint']+'?'+urlencode(params),'sandbox':settings.world_sandbox}
@router.post('/world/complete')
async def complete(body:Completion,user=Depends(current_user),db=Depends(get_db)):
    attempt=db.get(WorldAttempt,digest(body.state))
    if not attempt or attempt.user_id!=user.id or attempt.status!='pending' or attempt.expires<=now():raise HTTPException(409,'World request expired or already used')
    if body.iss!=ISSUER:raise HTTPException(403,'World issuer mismatch')
    claimed=db.execute(update(WorldAttempt).where(WorldAttempt.state_hash==attempt.state_hash,WorldAttempt.status=='pending').values(status='processing'))
    db.commit()
    if claimed.rowcount!=1:raise HTTPException(409,'World request already used')
    if body.error or not body.code:
        attempt.status='denied';attempt.verifier='';db.commit();raise HTTPException(403,'World verification was not completed')
    try:claims=await exchange_and_validate(body.code,attempt.verifier,attempt.nonce,settings.app_origin+'/world-callback')
    except Exception:
        attempt.status='failed';attempt.verifier='';db.commit();raise HTTPException(403,'World proof validation failed; start a new request')
    subject=digest(ISSUER+'|'+claims['sub']);v=db.get(WorldVerification,user.id)
    if v and v.subject_hash!=subject:
        attempt.status='failed';attempt.verifier='';db.commit();raise HTTPException(409,'Use the World identity already linked to this account')
    if not v:v=WorldVerification(user_id=user.id,subject_hash=subject);db.add(v)
    v.auth_time=claims['auth_time'];v.expires=min(claims['exp'],claims['auth_time']+300);v.assurance=claims['acr'];v.sandbox=settings.world_sandbox
    attempt.status='verified';attempt.verifier='';db.add(Audit(actor=user.id,action='world_sandbox_verified' if v.sandbox else 'world_verified',reference=attempt.state_hash))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'This World identity is already linked to another account')
    return {'verified':not v.sandbox,'sandbox_verified':v.sandbox,'expires':v.expires}
