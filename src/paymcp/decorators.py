from typing import Union
# paymcp/decorators.py

def price(price: float, currency: str = "USD"):
    def decorator(func):
        func._paymcp_price_info = {
            "price": price,
            "currency": currency
        }
        return func
    return decorator

def subscription(plan: Union[str, list[str]]):
    def decorator(func):
        func._paymcp_subscription_info = {
            "plan": plan,
        }
        return func
    return decorator