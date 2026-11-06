import asyncio,time,json
import pytest,jwt,httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from urllib.parse import urlparse,parse_qs
from backend.services import world
from backend.api import world as endpoints
from backend.config import settings
from test_core import database,client,register

def claims():
    t=int(time.time());return {'iss':world.ISSUER,'sub':'test-subject','aud':'mivo-test-client','exp':t+300,'iat':t,'nonce':'expected','auth_time':t,'acr':world.ACR[0],'amr':['test-method']}

@pytest.mark.parametrize('change',[{'nonce':'wrong'},{'auth_time':0},{'auth_time':int(time.time())+1000},{'acr':'password-only'},{'amr':[]},{'sub':''},{'azp':'wrong'}])
def test_policy_rejects_invalid_claims(change,monkeypatch):
    monkeypatch.setattr(settings,'world_client_id','mivo-test-client')
    with pytest.raises(ValueError):world.validate_claims({**claims(),**change},'expected')

def test_signature_and_audience_validation(monkeypatch):
    monkeypatch.setattr(settings,'world_client_id','mivo-test-client');monkeypatch.setattr(settings,'world_client_secret','test-only-secret')
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()));jwk['kid']='test-key'
    data=claims();token=jwt.encode(data,private,algorithm='RS256',headers={'kid':'test-key'})
    metadata={'issuer':world.ISSUER,'authorization_endpoint':world.ISSUER+'/api/v1/authorize','token_endpoint':world.ISSUER+'/api/v1/token','jwks_uri':world.ISSUER+'/.well-known/jwks.json'}
    def handle(request):
        if request.url.path=='/.well-known/openid-configuration':return httpx.Response(200,json=metadata)
        if request.url.path=='/.well-known/jwks.json':return httpx.Response(200,json={'keys':[jwk]})
        return httpx.Response(200,json={'id_token':token})
    real_client=httpx.AsyncClient
    monkeypatch.setattr(world.httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
    result=asyncio.run(world.exchange_and_validate('test-code','test-verifier','expected','https://example.com/callback'))
    assert result['sub']=='test-subject'
    token=jwt.encode({**data,'aud':'another-client'},private,algorithm='RS256',headers={'kid':'test-key'})
    with pytest.raises(jwt.InvalidAudienceError):asyncio.run(world.exchange_and_validate('code','verifier','expected','https://example.com/callback'))
    token=jwt.encode(data,rsa.generate_private_key(public_exponent=65537,key_size=2048),algorithm='RS256',headers={'kid':'test-key'})
    with pytest.raises(jwt.InvalidSignatureError):asyncio.run(world.exchange_and_validate('code','verifier','expected','https://example.com/callback'))

def test_world_sandbox_binding_and_replay(client,monkeypatch):
    register(client);monkeypatch.setattr(settings,'world_client_id','mivo-test-client');monkeypatch.setattr(settings,'world_client_secret','test-only-secret')
    async def meta():return {'authorization_endpoint':world.ISSUER+'/api/v1/authorize'}
    async def exchange(code,verifier,nonce,redirect):return {**claims(),'nonce':nonce}
    monkeypatch.setattr(endpoints,'metadata',meta);monkeypatch.setattr(endpoints,'exchange_and_validate',exchange)
    start=client.post('/world/start').json();params=parse_qs(urlparse(start['url']).query)
    assert params['code_challenge_method']==['S256']
    body={'state':params['state'][0],'iss':world.ISSUER,'code':'test-code'}
    response=client.post('/world/complete',json=body);assert response.status_code==200
    assert response.json()['sandbox_verified'] is True and response.json()['verified'] is False
    assert client.post('/world/complete',json=body).status_code==409
    assert client.get('/world/status').json()['verified'] is False

def test_world_denial_does_not_verify(client,monkeypatch):
    register(client);monkeypatch.setattr(settings,'world_client_id','test');monkeypatch.setattr(settings,'world_client_secret','test-only-secret')
    async def meta():return {'authorization_endpoint':world.ISSUER+'/api/v1/authorize'}
    monkeypatch.setattr(endpoints,'metadata',meta)
    params=parse_qs(urlparse(client.post('/world/start').json()['url']).query)
    body={'state':params['state'][0],'iss':world.ISSUER,'error':'access_denied'}
    assert client.post('/world/complete',json=body).status_code==403
    assert client.get('/world/status').json()['sandbox_verified'] is False
