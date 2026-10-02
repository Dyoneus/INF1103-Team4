import json
import logging
import os

from groq import Groq

MODEL = "llama-3.3-70b-versatile"  
MAX_ATTEMPTS = 3

logger = logging.getLogger(__name__)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

#This allowed_values need to check with io_manger Team
ALLOWED_VALUES = {
    "issue_clarity": ["CLEAR", "UNCLEAR"],
    "location_quality": ["ADEQUATE", "VAGUE", "MISSING"],
    "date_quality": ["EXACT", "APPROXIMATE", "MISSING"],
    "time_quality": ["EXACT", "APPROXIMATE", "MISSING"],
    "safety_category": [
        "WORKING_AT_HEIGHT", "PPE", "ELECTRICAL", "FIRE_HAZARD",
        "MACHINERY", "HOUSEKEEPING", "OTHER",
    ],
}
