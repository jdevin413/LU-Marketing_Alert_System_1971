from monitor import parse_schedule_html, pair_events, describe_change

HTML_OLD = '''
<h1>2026 Football Schedule</h1><table><tr><th>Date</th><th>Time</th><th>At</th><th>Opponent</th><th>Location</th><th>Tournament</th><th>Result</th></tr>
<tr><td>Sep 12 (Sat)</td><td>6:00 PM ET</td><td>Home</td><td>Old Dominion</td><td>Lynchburg, Va.</td><td></td><td>-</td></tr>
<tr><td>Sep 19 (Sat)</td><td>1:00 PM ET</td><td>Away</td><td>No. 18 Virginia</td><td>Charlottesville, Va.</td><td></td><td>-</td></tr>
</table>'''
HTML_NEW = '''
<h1>2026 Football Schedule</h1><table><tr><th>Date</th><th>Time</th><th>At</th><th>Opponent</th><th>Location</th><th>Tournament</th><th>Result</th></tr>
<tr><td>Sep 12 (Sat)</td><td>7:30 PM ET</td><td>Home</td><td>Old Dominion</td><td>Lynchburg, Va.</td><td></td><td>-</td></tr>
<tr><td>Sep 19 (Sat)</td><td>1:00 PM ET</td><td>Away</td><td>No. 19 Virginia</td><td>Charlottesville, Va.</td><td></td><td>Canceled</td></tr>
</table>'''

old_label, old = parse_schedule_html(HTML_OLD)
new_label, new = parse_schedule_html(HTML_NEW)
assert old_label == new_label == "2026"
pairs, removed, added = pair_events(old, new)
assert not removed and not added
alerts = []
for a, b in pairs:
    alerts += describe_change("Test", a, b)
assert any(x["kind"] == "TIME CHANGE" for x in alerts), alerts
assert any(x["kind"] == "CANCELED" for x in alerts), alerts
print("tests passed")
