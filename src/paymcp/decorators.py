# paymcp/decorators.py


def price(price: float, currency: str = "USD"):
    def decorator(func):
        func._paymcp_price_info = {"price": price, "currency": currency}
        return func

    return decorator
