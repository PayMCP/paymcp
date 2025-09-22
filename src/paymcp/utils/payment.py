"""Payment utility functions."""


def normalize_status(status):
    """
    Normalize payment status to standard values: paid, canceled, or pending.

    Args:
        status: Raw status from payment provider

    Returns:
        str: Normalized status ('paid', 'canceled', or 'pending')
    """
    if not status:
        return "pending"

    # Convert to string and lowercase
    try:
        status_str = str(status).strip().lower()
    except:
        return "pending"

    # Map various statuses to standard values
    if status_str in [
        "paid",
        "complete",
        "completed",
        "succeeded",
        "success",
        "captured",
        "confirmed",
        "approved",
    ]:
        return "paid"

    if status_str in [
        "canceled",
        "cancelled",
        "failed",
        "expired",
        "error",
        "refused",
        "rejected",
        "voided",
    ]:
        return "canceled"

    # Default to pending for any other status
    return "pending"
