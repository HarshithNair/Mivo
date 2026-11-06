"""World Agent Pass OIDC. Never treats a browser success callback as proof."""
import base64,hashlib,json,time
from urllib.parse import quote
import httpx,jwt
from backend.config import settings
ISSUER='https://auth.world.org'
DISCOVERY=ISSUER+'/.well-known/openid-configuration'
ACR=['https://world.org/oidc/acr/orb','https://world.org/oidc/acr/orb-face']

def configured():return bool(settings.world_client_id and settings.world_client_secret)
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def pkce(verifier):return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
async def metadata():
    async with httpx.AsyncClient(timeout=10) as client:
        r=await client.get(DISCOVERY);r.raise_for_status();data=r.json()
    expected={'issuer':ISSUER,'authorization_endpoint':ISSUER+'/api/v1/authorize','token_endpoint':ISSUER+'/api/v1/token','jwks_uri':ISSUER+'/.well-known/jwks.json'}
    if any(data.get(k)!=v for k,v in expected.items()):raise ValueError('Unexpected World discovery metadata')
    return data

def validate_claims(claims,nonce,current_time=None):
    current_time=int(time.time()) if current_time is None else current_time
    if claims.get('nonce')!=nonce:raise ValueError('Nonce mismatch')
    auth_time=claims.get('auth_time')
    if type(auth_time) is not int or not current_time-300<=auth_time<=current_time+30:raise ValueError('Fresh World authentication required')
    if claims.get('acr') not in ACR:raise ValueError('Required assurance missing')
    if not isinstance(claims.get('amr'),list) or not claims['amr'] or not all(isinstance(v,str) for v in claims['amr']):raise ValueError('Authentication method missing')
    if not isinstance(claims.get('sub'),str) or not claims['sub']:raise ValueError('Subject missing')
    if isinstance(claims.get('aud'),list) and len(claims['aud'])>1 and claims.get('azp')!=settings.world_client_id:raise ValueError('Authorized party missing')
    if 'azp' in claims and claims['azp']!=settings.world_client_id:raise ValueError('Authorized party mismatch')
    return claims

async def exchange_and_validate(code,verifier,nonce,redirect_uri):
    data=await metadata()
    async with httpx.AsyncClient(timeout=15) as client:
        response=await client.post(data['token_endpoint'],auth=httpx.BasicAuth(quote(settings.world_client_id,safe=''),quote(settings.world_client_secret,safe='')),data={'grant_type':'authorization_code','code':code,'redirect_uri':redirect_uri,'code_verifier':verifier})
        response.raise_for_status();token=response.json().get('id_token')
        if not isinstance(token,str) or len(token)>16000:raise ValueError('Invalid ID token')
        header=jwt.get_unverified_header(token)
        if header.get('alg')!='RS256' or not isinstance(header.get('kid'),str):raise ValueError('Unsupported signing algorithm')
        keys=await client.get(data['jwks_uri']);keys.raise_for_status()
        matches=[k for k in keys.json().get('keys',[]) if k.get('kid')==header['kid'] and k.get('kty')=='RSA' and k.get('use','sig')=='sig']
        if len(matches)!=1:raise ValueError('World signing key unavailable')
        key=jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(matches[0]))
        claims=jwt.decode(token,key,algorithms=['RS256'],audience=settings.world_client_id,issuer=ISSUER,leeway=15,options={'require':['iss','sub','aud','exp','iat','nonce','auth_time','acr','amr']})
    return validate_claims(claims,nonce)
