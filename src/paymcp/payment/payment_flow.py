from enum import Enum

class PaymentFlow(str, Enum):
    TWO_STEP = "two_step"
    PROGRESS = "progress"
    ELICITATION = "elicitation"
    OOB = "oob"
    LIST_CHANGE = "list_change" 