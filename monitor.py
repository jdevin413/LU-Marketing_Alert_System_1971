1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
49
50
51
52
53
54
55
56
57
58
59
60
61
62
63
64
65
66
67
68
69
70
71
72
73
74
75
76
77
78
79
80
81
82
83
84
85
86
87
88
89
90
91
92
93
94
95
96
97
98
99
100
101
102
103
104
105
106
107
108
109
110
111
112
113
114
115
116
117
118
119
120
121
122
123
124
125
126
127
128
#!/usr/bin/env python3
"""Monitor Liberty home athletics events plus official news for schedule disruptions."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
TIMEOUT = 30
USER_AGENT = "LibertyAthleticsScheduleMonitor/2.1 (+personal schedule-change notifier)"

# Liberty's NCAA menu has 18 sponsored teams; Cross Country and Track & Field each
# share one schedule page for the men's and women's programs, so 16 NCAA URLs cover all 18.
SOURCES = [
    ("Baseball", "https://libertyflames.com/sports/baseball/schedule/text"),
    ("Men's Basketball", "https://libertyflames.com/sports/mens-basketball/schedule/text"),
    ("Cross Country (M/W)", "https://libertyflames.com/sports/cross-country/schedule/text"),
    ("Football", "https://libertyflames.com/sports/football/schedule/text"),
    ("Men's Golf", "https://libertyflames.com/sports/mens-golf/schedule/text"),
    ("Men's Soccer", "https://libertyflames.com/sports/mens-soccer/schedule/text"),
    ("Men's Tennis", "https://libertyflames.com/sports/mens-tennis/schedule/text"),
    ("Track & Field (M/W)", "https://libertyflames.com/sports/track-and-field/schedule/text"),
    ("Women's Basketball", "https://libertyflames.com/sports/womens-basketball/schedule/text"),
    ("Field Hockey", "https://libertyflames.com/sports/field-hockey/schedule/text"),
    ("Women's Lacrosse", "https://libertyflames.com/sports/womens-lacrosse/schedule/text"),
    ("Women's Soccer", "https://libertyflames.com/sports/womens-soccer/schedule/text"),
    ("Softball", "https://libertyflames.com/sports/softball/schedule/text"),
    ("Women's Swimming & Diving", "https://libertyflames.com/sports/womens-swimming-and-diving/schedule/text"),
    ("Women's Tennis", "https://libertyflames.com/sports/womens-tennis/schedule/text"),
    ("Women's Volleyball", "https://libertyflames.com/sports/womens-volleyball/schedule/text"),
    # Club sports covered by the Liberty marketing video team.
    ("Men's D1 Hockey (Club)", "https://libertyclubsports.com/sports/mens-ice-hockey/schedule/text"),
    ("Men's Lacrosse (Club)", "https://libertyclubsports.com/sports/mens-lacrosse/schedule/text"),
]


# Sidearm's /schedule/text view can omit disruption labels that are visible on the
# normal schedule page. For Club Sports, check the normal page too and let an
# explicit status there override a blank status from the text feed.
STATUS_FALLBACK_URLS = {
    "Men's D1 Hockey (Club)": "https://libertyclubsports.com/sports/mens-ice-hockey/schedule",
    "Men's Lacrosse (Club)": "https://libertyclubsports.com/sports/mens-lacrosse/schedule",
}


# Phase 2: official Liberty story archives. These are an early-warning layer only.
# A news-source failure never prevents the schedule monitor from running.
NEWS_SOURCES = [
    ("Liberty Athletics News", "https://libertyflames.com/archives", "https://libertyflames.com"),
    ("Liberty Club Sports News", "https://libertyclubsports.com/archives", "https://libertyclubsports.com"),
]

# The final slug segment of Sidearm news URLs begins with the sport name. Matching
# the slug keeps an article about one sport from being mistaken for another.
SPORT_URL_HINTS = {
    "Baseball": ("baseball-",),
    "Men's Basketball": ("mens-basketball-",),
    "Cross Country (M/W)": ("cross-country-", "womens-cross-country-"),
    "Football": ("football-",),
    "Men's Golf": ("mens-golf-",),
    "Men's Soccer": ("mens-soccer-",),
    "Men's Tennis": ("mens-tennis-",),
    "Track & Field (M/W)": ("track-and-field-", "womens-track-and-field-"),
    "Women's Basketball": ("womens-basketball-",),
    "Field Hockey": ("field-hockey-",),
    "Women's Lacrosse": ("womens-lacrosse-",),
    "Women's Soccer": ("womens-soccer-",),
    "Softball": ("softball-",),
    "Women's Swimming & Diving": ("womens-swimming-and-diving-", "swimming-and-diving-"),
    "Women's Tennis": ("womens-tennis-",),
    "Women's Volleyball": ("womens-volleyball-",),
    "Men's D1 Hockey (Club)": ("mens-d1-hockey-",),
    "Men's Lacrosse (Club)": ("mens-lacrosse-",),
}

NEWS_DISRUPTION_PATTERNS = [
    ("CANCELED", re.compile(r"\b(cancelled|canceled)\b", re.I)),
    ("POSTPONED", re.compile(r"\bpostponed\b", re.I)),
    ("SUSPENDED", re.compile(r"\bsuspended\b", re.I)),
    ("DELAYED", re.compile(r"\b(delayed|weather delay|lightning delay)\b", re.I)),
    ("RESCHEDULED", re.compile(r"\brescheduled\b", re.I)),
    (
        "TIME/DATE CHANGE",
        re.compile(
            r"\b(?:game|match|meet|contest|doubleheader|first pitch|kickoff|tip-?off|face-?off|start(?: time)?)"
            r".{0,90}\b(?:moved|shifted|pushed|changed|adjusted)\b"
            r"|\b(?:will now|now scheduled to|new start time|time change|date change|schedule change|schedule adjusted)\b",
            re.I,
        ),
    ),
]

NEWS_SEEN_LIMIT = 250
NEWS_EVENT_LOOKAHEAD_DAYS = 120


STATUS_PATTERNS = [
    ("CANCELED", re.compile(r"\b(cancelled|canceled)\b", re.I)),
    ("POSTPONED", re.compile(r"\bpostponed\b", re.I)),
    ("DELAYED", re.compile(r"\b(delay|delayed)\b", re.I)),
    ("SUSPENDED", re.compile(r"\bsuspended\b", re.I)),
    ("RESCHEDULED", re.compile(r"\brescheduled\b", re.I)),
]

NON_COMPETITION = {
    "tryouts",
    "information meeting",
    "team meeting",
    "interest meeting",
}

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
)}

