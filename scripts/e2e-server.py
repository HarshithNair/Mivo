"""Run browser tests against an isolated disposable catalog with no live AI calls."""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory(prefix='mivo-browser-tests-') as temp:
    os.environ['DATABASE_URL']='sqlite:///'+str(Path(temp)/'test.db')
    os.environ['APP_ORIGIN']='http://localhost:3137'
    os.environ['GEMINI_API_KEY']=''
    os.environ['PAYMENT_ENABLED']='false'
    from backend.db import engine
    from backend.models import Base
    from backend.seed import seed
    Base.metadata.create_all(engine);seed()
    import uvicorn
    uvicorn.run('backend.api.main:app',host='127.0.0.1',port=8137)
