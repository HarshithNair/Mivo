from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=12, max_length=128)
class Registration(Credentials):
    name: str = Field(min_length=1, max_length=80)
    role: Literal['buyer','merchant'] = 'buyer'
class ProductInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: Literal['Headphones','Smartwatches','Laptops','Cameras','Lifestyle','Audio']
    description: str = Field(min_length=5, max_length=2000)
    price_cents: int = Field(gt=0, le=10000000, strict=True)
    floor_cents: int = Field(gt=0, le=10000000, strict=True)
    inventory: int = Field(ge=0, le=100000, strict=True)
    @model_validator(mode='after')
    def valid_floor(self):
        if self.floor_cents > self.price_cents: raise ValueError('Floor exceeds listing price')
        return self
class StartNegotiation(BaseModel):
    product_id: str
    budget_cents: int = Field(gt=0, le=10000000, strict=True)
class Proposal(BaseModel):
    amount_cents: int = Field(ge=1, le=10000000, strict=True)
class SearchIntent(BaseModel):
    category: str | None = None
    budget_cents: int | None = Field(default=None, ge=1, le=10000000)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    brands: list[str] = Field(default_factory=list, max_length=10)
    features: list[str] = Field(default_factory=list, max_length=10)
class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
class PriceRange(BaseModel):
    low: float | None = None
    high: float | None = None
class Identification(BaseModel):
    # Model output is untrusted and free-form: accept loosely, then trim to sane sizes.
    identified: bool = False
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    description: str | None = None
    key_features: list[str] = Field(default_factory=list)
    price_range_usd: PriceRange | None = None
    where_to_buy: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    @model_validator(mode='after')
    def trim(self):
        for key in ('name','brand','model','category'):
            value=getattr(self,key)
            if value: setattr(self,key,value[:120])
        if self.description: self.description=self.description[:600]
        self.key_features=[f[:120] for f in self.key_features[:10]]
        self.where_to_buy=[w[:80] for w in self.where_to_buy[:10]]
        self.confidence=min(max(self.confidence,0.0),1.0)
        return self
