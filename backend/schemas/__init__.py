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
    amount_cents: int = Field(gt=0, le=10000000, strict=True)
class SearchIntent(BaseModel):
    category: str | None = None
    budget_cents: int | None = Field(default=None, gt=0, le=10000000)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    brands: list[str] = Field(default_factory=list, max_length=10)
    features: list[str] = Field(default_factory=list, max_length=10)
class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
