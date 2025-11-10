"""Request/Response schemas for API communication"""
from pydantic import BaseModel, Field, field_validator, AliasChoices
from datetime import datetime
from typing import Optional, Dict, Any, List
from src.utils.helpers import clean_numeric_string, sanitize_text

class AuthResponse(BaseModel):
    """Schema for parsing the authentication response from the API."""
    authenticated: bool = Field(True, exclude=True)
    name: str = Field(..., validation_alias=AliasChoices('$$_contactId', 'name'))
    national_id: str = Field(
        ...,
        validation_alias=AliasChoices('contactId_nationalCode', 'contactId_nationalId', 'nationalId')
    )
    phone: Optional[str] = Field(None, validation_alias=AliasChoices('contactId_phone', 'phone'))
    city: Optional[str] = Field(None, validation_alias=AliasChoices('contactId_cityId', 'city'))

    orders: List[Dict[str, Any]] = Field([], validation_alias='items')
    factor_payment: Optional[Dict[str, Any]] = Field(None, validation_alias='factorPayment')
    payment_link: Optional[str] = Field(None, validation_alias='factorId_paymentLink')
    raw_data: Dict[str, Any] = Field({}, exclude=True)

    class Config:
        populate_by_name = True
        from_attributes = True
        extra = 'ignore'  

    @field_validator('name', 'city', 'phone', mode='before')
    def clean_texts(cls, v):
        return sanitize_text(v)

    @field_validator('national_id', mode='before')
    def normalize_id(cls, v):
        return clean_numeric_string(v)

class SubmissionResponse(BaseModel):
    """Standardized response for complaint/repair submissions."""
    ticket_number: str = Field(..., alias="ticketNumber")
    message: Optional[str] = Field("Success")
    reference_id: Optional[str] = Field(None, alias="recordId")
    submitted_at: str = Field(default_factory=lambda: datetime.now().isoformat(), alias="timestamp")

    class Config:
        populate_by_name = True
        extra = "ignore"