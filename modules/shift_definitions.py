# shift_definitions.py
"""
Module that defines the shift types and their attributes
"""

# Define shift information
day_shifts = {
    "D7B": {"rank": 1, "start_time": "0700"},
    "D7P": {"rank": 2, "start_time": "0700"},
    "D9L": {"rank": 3, "start_time": "0900"},
    "D11M": {"rank": 4, "start_time": "1100"},
    "D11B": {"rank": 5, "start_time": "1100"},
    "FW": {"rank": 6, "start_time": "1100"},
    "MG": {"rank": 7, "start_time": "1100"},
    "GR": {"rank": 8, "start_time": "0700"},
    "LG": {"rank": 9, "start_time": "0900"},
    "PG": {"rank": 10, "start_time": "0700"}
}

night_shifts = {
    "N7B": {"rank": 1, "start_time": "1900"},
    "N7P": {"rank": 2, "start_time": "1900"},
    "N9L": {"rank": 3, "start_time": "2100"},
    "NG": {"rank": 4, "start_time": "1900"},
    "NP": {"rank": 5, "start_time": "1900"}
}
