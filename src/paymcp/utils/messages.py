def open_link_message(url, amount, currency, payment_id=None):
    """Generate message for payment link."""
    return (
        f"To run this tool, please pay {amount} {currency} using the link below:\n\n"
        f"{url}\n\n"
        "After completing the payment, come back and confirm."
    )


def opened_webview_message(url, amount, currency, payment_id=None):
    """Generate message for opened webview."""
    return (
        f"To run this tool, please pay {amount} {currency}.\n"
        "A payment window should be open. If not, you can use this link:\n\n"
        f"{url}\n\n"
        "After completing the payment, come back and confirm."
    )


def description_with_price(description: str, price_info: dict):
    extra_desc = (
        f"\nThis is a paid function: {price_info['price']} {price_info['currency']}."
        " Payment will be requested during execution."
    )
    return description.strip() + extra_desc