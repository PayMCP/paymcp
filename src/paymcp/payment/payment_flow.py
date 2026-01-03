from enum import Enum

class Mode(str, Enum):
    AUTO = "auto"
    TWO_STEP = "two_step"
    PROGRESS = "progress"
    ELICITATION = "elicitation"
    OOB = "oob"
    DYNAMIC_TOOLS = "dynamic_tools" 
    RESUBMIT = "resubmit"
    X402 = "x402"

PaymentFlow = Mode # Alias for backward compatibility; PaymentFlow will be deprecated in future versions
